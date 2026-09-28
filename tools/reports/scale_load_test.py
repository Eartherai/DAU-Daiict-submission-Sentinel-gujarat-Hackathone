#!/usr/bin/env python3
"""Run the statewide load test and emit its report.

A named deliverable: "Scalability and load-test report for approximately
80,000 cameras". It runs the load rather than describing it, into a throwaway
database, and writes down what happened including the parts that do not
flatter the platform.

    python tools/reports/scale_load_test.py --n 80000 \
        --out reports/SCALE_80K_LOAD_TEST.md

What this proves and what it does not is stated in the report itself. The
registry, GIS and gap-analysis planes are exercised at full statewide scale.
The media and AI planes are not: those are bounded by concurrent WHEP sessions
and by inference throughput, and no amount of registry rows says anything
about either.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.command.scale import bulk_synthetic_cameras  # noqa: E402
from saakshya.gis.service import MapService  # noqa: E402
from saakshya.store.repository import Store  # noqa: E402


def _db_bytes(db: Path) -> int:
    """Every file the database actually occupies, not just the main one."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        f = db.with_name(db.name + suffix)
        if f.exists():
            total += f.stat().st_size
    return total


def _timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return (time.perf_counter() - t0) * 1000.0, out


def run(n: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="saakshya-scale-"))
    db = tmp / "scale.db"
    try:
        store = Store(f"sqlite:///{db}")
        store.create_all()
        svc = MapService(store)

        t0 = time.perf_counter()
        bulk_synthetic_cameras(store, n)
        onboard_s = time.perf_counter() - t0

        gaps_ms, gaps = _timed(svc.registry_gaps)
        cap_ms, cap = _timed(svc.capability)
        view_ms, view = _timed(
            lambda: svc.cameras(bbox=None, zoom=11.0, max_features=1500))
        look_ms, _ = _timed(lambda: store.get_camera(f"SYN-{n // 2:05d}"))
        filt_ms, filt = _timed(lambda: store.cameras_in_bbox(
            south=-90, west=-180, north=90, east=180,
            departments=["SYNTHETIC"], limit=n + 1))

        return {
            "n": n,
            "onboard_s": round(onboard_s, 3),
            "rate": int(n / onboard_s) if onboard_s else 0,
            "gaps_ms": round(gaps_ms, 1),
            "gaps_counted": gaps["cameras"],
            "capability_ms": round(cap_ms, 1),
            "viewport_ms": round(view_ms, 1),
            "viewport_features": len(view.get("features", [])),
            "lookup_ms": round(look_ms, 2),
            "filter_ms": round(filt_ms, 1),
            "filter_rows": len(filt),
            # SQLite runs in WAL mode, so most of a freshly written estate
            # is still in the -wal sidecar and the main file reads as almost
            # empty. Measuring only `scale.db` reported 0.0 MB for two
            # thousand cameras; the database is all of its files.
            "db_mb": round(_db_bytes(db) / 1048576, 2),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render(r: dict) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    n = r["n"]
    o: list[str] = []
    w = o.append

    w(f"# Scalability and load test — {n:,} cameras")
    w("")
    w(f"Generated {now}. The registry table below was measured by this script on a")
    w("throwaway database of synthetic camera rows; none is a live stream.")
    w("")

    w("## Registry plane, at statewide scale")
    w("")
    w("| Operation | Result |")
    w("|---|---:|")
    w(f"| Bulk onboarding of {n:,} cameras | **{r['onboard_s']}s** "
      f"({r['rate']:,}/s) |")
    w(f"| Registry gap analysis (all {r['gaps_counted']:,}) | "
      f"**{r['gaps_ms']} ms** |")
    w(f"| Capability grading summary | {r['capability_ms']} ms |")
    w(f"| Map viewport, zoom 11 → {r['viewport_features']:,} features | "
      f"{r['viewport_ms']} ms |")
    w(f"| Single camera lookup | **{r['lookup_ms']} ms** |")
    w(f"| Department filter over the whole estate "
      f"({r['filter_rows']:,} rows) | {r['filter_ms']} ms |")
    w(f"| Database size | {r['db_mb']} MB |")
    w("")
    w("The map viewport is a bounded query rather than a full dump: it returns")
    w(f"{r['viewport_features']:,} features from {n:,} cameras, so the cost of")
    w("drawing the map does not grow with the estate.")
    w("")

    w("## What this does not prove")
    w("")
    w("Registry rows say nothing about video or inference, and it would be")
    w("dishonest to present the numbers above as statewide readiness.")
    w("")
    w('- **Video plane.** CONTROL ROOM opens up to 30 direct WHEP sessions;')
    w('  OPTIMIZED VIEW holds at most 12 near the viewport (`ui/app.js`). These')
    w('  local policies are not Sentinel limits: availability varies with shared')
    w('  load (`docs/SENTINEL_SUPPORT_CLARIFICATION.md`). This run opens no streams.')
    w('- **AI plane.** The historical report recorded four selected cameras at')
    w('  roughly 1.4 fps each (~5.6 aggregate), before the current GPU recogniser.')
    w('  That measurement is not repeated by this registry-only harness. The GPU')
    w('  path is separately measured in `var/reports/pipeline_device.json` and')
    w('  `var/reports/ocr_indian_eval.json`. It does not analyse every registry row.')
    w('- **Storage.** These are synthetic camera metadata rows, not observations')
    w('  or retained video. Retention and media bandwidth are sized separately.')
    w('')
    w('## What the numbers imply for sizing')
    w('')
    w('Bounded viewport output keeps drawing manageable; gap analysis still scans')
    w('registry metadata, and this single-host result does not establish distributed')
    w('capacity. Current demonstration hardware limits simultaneous deep-inference')
    w('concurrency. Analytics workers scale horizontally, so additional GPU nodes')
    w('raise concurrent inference throughput without redesigning ingest, event,')
    w('watchlist, GIS or investigation services. Cluster capacities are MODELLED.')
    w('')
    w('This registry run used SQLite. PostgreSQL 18 + PostGIS 3.6 carries the same')
    w('schema; the government store was copied and served there with both chains')
    w('verified (`var/reports/store_engines.json`, `docs/HLD.md` §4.10). A district-scale')
    w('PostgreSQL deployment with replication and failover has not been exercised')
    w('here and should not be claimed.')
    return "\n".join(o) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80_000)
    ap.add_argument("--out", default="reports/SCALE_80K_LOAD_TEST.md")
    a = ap.parse_args()

    print(f"running the load test at {a.n:,} cameras…", flush=True)
    r = run(a.n)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(r), encoding="utf-8")
    print(f"wrote {out}")
    print(f"  onboard {r['onboard_s']}s ({r['rate']:,}/s) · "
          f"gaps {r['gaps_ms']}ms · lookup {r['lookup_ms']}ms · "
          f"{r['db_mb']}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
