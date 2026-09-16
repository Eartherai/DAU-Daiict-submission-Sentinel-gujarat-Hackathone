"""Daily live-store score for the remaining days before submit.

The evaluation asks for a designated vehicle traced across cameras, a
timestamped route, and a watchlist that fires. This command reports whether
the live government store has that evidence yet. It does not invent it.

    python tools/verify/daily_live_score.py --db sqlite:///var/live.db

If ``cross_camera_plates`` becomes 1 or more, stop other work and film that
plate on the live UI. Do not restart ingest to chase a drop: cameras
reconnect on their own.

Figures are MEASURED from the live store. camera_health STREAMING is only
honest after ingest is running the session-state persist; prefer the ingest
log line ``streaming=N/30`` while an older ingest process is still up.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "verify"))

from measured_results import _identity_among_marks

from saakshya.capability import TimeBand
from saakshya.store import Store
from saakshya.store import schema as S

# Keep in lockstep with PipelineConfig.person_dwell_s. This script must not
# import the analytics pipeline: that pulls detectors into a process that only
# needs to read the store.
PERSON_DWELL_S = 12.0


def _ingest_log_streaming(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    last = None
    for line in text.splitlines():
        m = re.search(r"streaming=(\d+)/(\d+)\s+frames=([0-9,]+)\s+"
                      r"observations=(\d+)", line)
        if m:
            last = {
                "streaming": int(m.group(1)),
                "workers": int(m.group(2)),
                "frames": int(m.group(3).replace(",", "")),
                "observations_written": int(m.group(4)),
                "line": line.strip(),
            }
    return last


def _top_marks(store: Store, n: int = 8) -> list[dict[str, Any]]:
    from sqlalchemy import func, select

    q = (
        select(
            S.observations.c.plate,
            func.count().label("hits"),
            func.count(func.distinct(S.observations.c.camera_id)).label("cameras"),
        )
        .where(S.observations.c.plate.isnot(None), S.observations.c.plate != "")
        .group_by(S.observations.c.plate)
        .order_by(func.count().desc())
        .limit(n)
    )
    with store.engine.connect() as c:
        return [{"plate": r[0], "hits": int(r[1]), "cameras": int(r[2])}
                for r in c.execute(q)]


def _anpr_grades(store: Store) -> dict[str, int]:
    cap = store.list_capability(time_band=str(TimeBand.ALL)) \
        or store.list_capability()
    by_camera: dict[str, str] = {}
    for r in cap:
        by_camera.setdefault(r["camera_id"], r.get("anpr_grade") or "UNKNOWN")
    out: dict[str, int] = {}
    for g in by_camera.values():
        out[g] = out.get(g, 0) + 1
    return out


def _health(store: Store) -> dict[str, int]:
    rows = store.list_health()
    counts: dict[str, int] = {}
    for row in rows.values():
        st = row.get("state") or "UNKNOWN"
        counts[st] = counts.get(st, 0) + 1
    return counts


def _open_alerts(store: Store) -> list[dict[str, Any]]:
    from sqlalchemy import select

    q = select(S.alerts.c.plate, S.alerts.c.camera_id, S.alerts.c.category,
               S.alerts.c.priority, S.alerts.c.status)
    with store.engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(q)]
    return [r for r in rows if (r.get("status") or "").upper() == "OPEN"]


def score(store: Store, *, ingest_log: Path | None) -> dict[str, Any]:
    st = store.stats()
    cross_n, lookalike_n, cross, lookalike = _identity_among_marks(store)
    dwell_s = PERSON_DWELL_S
    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "label": "MEASURED",
        "observations": st.get("observations", 0),
        "persons": st.get("observations_person", 0),
        "person_long_stay": st.get("observations_person_long_stay", 0),
        "person_long_stay_cameras": st.get("cameras_person_long_stay", 0),
        "person_dwell_s": dwell_s,
        "by_object_type": st.get("observations_by_object_type") or {},
        "distinct_plates": st.get("distinct_plates", 0),
        "cameras_with_plate": st.get("cameras_with_plate", 0),
        "plate_confirmed": st.get("observations_plate_confirmed", 0),
        "plate_leads": st.get("observations_plate_leads", 0),
        "raw_ocr_attempts": st.get("raw_ocr_read_records", 0),
        "watchlist": st.get("watchlist", 0),
        "alerts": st.get("alerts", 0),
        "open_alerts": _open_alerts(store),
        "cross_camera_plates": cross_n,
        "cross_camera": cross,
        "lookalike_pairs": lookalike_n,
        "lookalikes": lookalike,
        "top_marks": _top_marks(store),
        "anpr_grades": _anpr_grades(store),
        "health": _health(store),
        "ingest_log": _ingest_log_streaming(ingest_log),
        "action": None,
    }
    if cross:
        out["action"] = (
            "FILM NOW — exact cross-camera identity on the live grid: "
            + ", ".join(cross)
            + ". Do not restart ingest. Record the live UI trajectory."
        )
    return out


def render(d: dict[str, Any]) -> str:
    log = d.get("ingest_log") or {}
    health = d.get("health") or {}
    grades = d.get("anpr_grades") or {}
    lines = [
        f"MEASURED live score  {d['generated_at']}",
        f"  observations          {d['observations']:,}",
        f"  persons               {d['persons']:,}",
        f"  person long-stay      {d['person_long_stay']:,}  "
        f"(≥ {d['person_dwell_s']} s on one camera; not intrusion)",
        "  object mix            "
        + (", ".join(
            f"{v:,} {k}"
            for k, v in sorted((d.get("by_object_type") or {}).items(),
                               key=lambda kv: (-kv[1], kv[0]))
        ) or "none"),
        f"  distinct marks        {d['distinct_plates']}",
        f"  cameras with a mark   {d['cameras_with_plate']}",
        f"  confirmed / leads     {d['plate_confirmed']:,} / {d['plate_leads']:,}",
        f"  cross-camera plates   {d['cross_camera_plates']}",
        f"  OCR lookalike pairs   {d['lookalike_pairs']}",
        f"  watchlist / alerts    {d['watchlist']} / {d['alerts']}",
        "  ANPR grades           "
        + (", ".join(f"{v} {k}" for k, v in sorted(grades.items())) or "none"),
        "  camera_health         "
        + (", ".join(f"{v} {k}" for k, v in sorted(health.items())) or "none"),
    ]
    if log:
        lines.append(
            f"  ingest log            streaming={log['streaming']}/{log['workers']} "
            f"frames={log['frames']:,}  (prefer this over camera_health "
            f"until ingest is restarted onto session-state persist)"
        )
    open_a = d.get("open_alerts") or []
    if open_a:
        shown = ", ".join(
            f"{a.get('plate') or 'unplated'} {a.get('camera_id')} "
            f"{a.get('category')} {a.get('priority')}"
            for a in open_a[:5]
        )
        lines.append(f"  open alerts           {shown}")
    else:
        lines.append("  open alerts           none")
    if d.get("cross_camera"):
        lines.append("  cross-camera          " + ", ".join(d["cross_camera"]))
    top = d.get("top_marks") or []
    if top:
        bits = []
        for m in top[:5]:
            kind = "MULTI-CAMERA" if m["cameras"] > 1 else "single camera"
            bits.append(f"{m['plate']} {m['hits']} hits/{m['cameras']} cam ({kind})")
        lines.append("  top marks             " + "; ".join(bits))
    if d.get("action"):
        lines += ["", d["action"]]
    else:
        lines += [
            "",
            "No exact cross-camera repeat yet. Keep ingest running. "
            "Do not claim a live multi-camera trail.",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.environ.get("SAAKSHYA_DB",
                                                   "sqlite:///var/live.db"))
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--ingest-log", type=Path,
                    default=Path(os.environ.get(
                        "SAAKSHYA_INGEST_LOG",
                        "/tmp/saakshya-ingest-final.log")))
    args = ap.parse_args()
    store = Store(args.db)
    store.create_all()
    d = score(store, ingest_log=args.ingest_log)
    text = render(d)
    sys.stdout.write(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(d, indent=2) + "\n")
        print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
