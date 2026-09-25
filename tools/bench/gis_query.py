#!/usr/bin/env python3
"""Map queries on SQLite and on PostgreSQL + PostGIS, on the same estate.

    python tools/bench/gis_query.py --sqlite var/final_80k.db --pg "$URL" \\
        [--json var/reports/gis_postgis.json]

Both stores hold the same cameras (copied by tools/db/migrate.py). For a fixed
set of points taken from the estate itself, it times the two map questions -
the cameras in a city-sized viewport, and the cameras within 2 km of a point -
on each engine, and checks that both engines return the same cameras. For the
radius the distances may differ by up to 0.5%: PostGIS measures on the WGS 84
spheroid, the fallback on a sphere (2 m in 1.2 km at Gujarat's latitude), and
a camera that close to the radius may fall either side of it. A faster answer
that differs beyond that is a failure, not a win.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def timed(fn, reps: int) -> tuple[float, float, object]:
    fn()                                                   # warm
    out, ms = None, []
    for _ in range(reps):
        t = time.perf_counter()
        out = fn()
        ms.append((time.perf_counter() - t) * 1000)
    ms.sort()
    return statistics.median(ms), ms[int(0.95 * (len(ms) - 1))], out


def main() -> int:
    import random

    from saakshya.store import Store

    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, type=Path)
    ap.add_argument("--pg", required=True)
    ap.add_argument("--points", type=int, default=20)
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--radius-m", type=float, default=2000)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    # Read-only, and not `immutable`: that skips the write-ahead log, where a
    # store's newest rows sit until a checkpoint (see tools/db/migrate.py).
    lite = Store(f"sqlite:///file:{a.sqlite.resolve()}?mode=ro&uri=true")
    pg = Store(a.pg)
    pg.create_all()
    assert pg.postgis, "PostGIS is not enabled on the PostgreSQL store"
    cams = [c for c in lite.list_cameras() if c.get("lat") is not None]
    rnd = random.Random(7)
    pts = [(c["lat"], c["lon"]) for c in rnd.sample(cams, a.points)]

    res: dict[str, dict] = {"viewport_0.1deg": {}, f"near_{int(a.radius_m)}m": {}}
    mismatches = 0
    for name, store in (("sqlite", lite), ("postgis", pg)):
        vp, nr = [], []
        for lat, lon in pts:
            p50, p95, _ = timed(lambda s=store, la=lat, lo=lon: s.cameras_in_bbox(
                south=la - 0.05, north=la + 0.05, west=lo - 0.05, east=lo + 0.05), a.reps)
            vp.append((p50, p95))
            p50, p95, _ = timed(lambda s=store, la=lat, lo=lon: s.cameras_near(
                la, lo, a.radius_m, limit=500), a.reps)
            nr.append((p50, p95))
        for key, series in (("viewport_0.1deg", vp), (f"near_{int(a.radius_m)}m", nr)):
            res[key][name] = {"p50_ms": round(statistics.median(x[0] for x in series), 2),
                              "p95_ms": round(max(x[1] for x in series), 2)}

    counts = []
    for lat, lon in pts:
        box = dict(south=lat - 0.05, north=lat + 0.05, west=lon - 0.05, east=lon + 0.05)
        a_ids = {c["camera_id"] for c in lite.cameras_in_bbox(**box)}
        b_ids = {c["camera_id"] for c in pg.cameras_in_bbox(**box)}
        na = {c["camera_id"]: c["distance_m"]
              for c in lite.cameras_near(lat, lon, a.radius_m, limit=500)["cameras"]}
        nb = {c["camera_id"]: c["distance_m"]
              for c in pg.cameras_near(lat, lon, a.radius_m, limit=500)["cameras"]}
        def close(x: float, y: float) -> bool:
            return abs(x - y) <= max(1.0, 0.005 * max(x, y))
        edge = {k for k, d in {**na, **nb}.items() if close(d, a.radius_m)}
        same = (a_ids == b_ids and set(na) - edge == set(nb) - edge
                and all(close(na[k], nb[k]) for k in set(na) & set(nb)))
        mismatches += not same
        counts.append((len(a_ids), len(na)))
    out = {
        "cameras": len(cams), "points": a.points, "reps_per_point": a.reps,
        "postgis": pg.postgis,
        "mean_cameras_in_viewport": round(statistics.mean(c[0] for c in counts), 1),
        "mean_cameras_within_radius": round(statistics.mean(c[1] for c in counts), 1),
        "results": res, "answers_identical_at": f"{a.points - mismatches}/{a.points} points",
    }
    print(json.dumps(out, indent=1))
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
