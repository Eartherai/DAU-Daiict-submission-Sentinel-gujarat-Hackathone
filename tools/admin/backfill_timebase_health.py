"""Carry measured stream health into the timebase registry.

The correlation gate needs two independent things: that two cameras share a
timebase, and that each camera's own timing is sound. Cluster membership was
established from burned-in clocks; PTS soundness is measured every time the grid
is ingested — but only the separate profiling pass ever wrote it down, so
`usable_for_correlation` stayed false for every camera however much data had
been collected. Ingest now records it directly; this carries forward the runs
that happened before it did.

Nothing is invented: it reads `camera_health`, which holds frames observed, PTS
regressions and forward jumps as measured, and grades them with the same
`assess_pts` the profiler uses. A camera with no observed frames is left
UNKNOWN — silence is not evidence of good timing.

    python tools/admin/backfill_timebase_health.py --db sqlite:///var/live.db --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.live.timebase import (
    OverlayClock,
    TimebaseHealth,
    TimebaseRegistry,
    assess_pts,
)
from saakshya.store import Store


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    store = Store(a.db)

    store.create_all()      # a store older than the code is migrated, not queried
    registry = TimebaseRegistry(store)
    # Read the table directly rather than through a convenience accessor: this
    # tool exists because a value did not reach where it was needed, and the
    # fewest layers between the measurement and the check is the right choice.
    from sqlalchemy import select

    from saakshya.store import schema as S

    with store.engine.connect() as c:
        rows = {r._mapping["camera_id"]: dict(r._mapping)
                for r in c.execute(select(S.camera_health))}

    graded = skipped = 0
    print(f"{'camera':<10} {'frames':>8} {'regress':>8} {'jumps':>6}  verdict")
    for cam, h in sorted(rows.items()):
        frames = h.get("frames") or 0
        if frames <= 0:
            skipped += 1
            continue
        health, why = assess_pts(
            regressions=h.get("pts_regressions") or 0,
            forward_jumps=h.get("pts_forward_jumps") or 0,
            realtime_ratio=None, max_gap_s=None, frames=frames)
        print(f"{cam:<10} {frames:>8,} {h.get('pts_regressions') or 0:>8} "
              f"{h.get('pts_forward_jumps') or 0:>6}  {health}  — {why}")
        graded += 1
        if not a.apply:
            continue
        prior = registry.get(cam)
        registry.record(TimebaseHealth(
            camera_id=cam, pts_health=health,
            pts_regressions=h.get("pts_regressions") or 0,
            pts_forward_jumps=h.get("pts_forward_jumps") or 0,
            realtime_ratio=None, measured_fps=h.get("measured_fps"),
            mean_interframe_gap_s=(prior.mean_interframe_gap_s if prior else None),
            max_interframe_gap_s=(prior.max_interframe_gap_s if prior else None),
            overlay_clock=(prior.overlay_clock if prior else OverlayClock.UNKNOWN),
            overlay_reading=(prior.overlay_reading if prior else None),
            # Cluster membership rests on evidence this pass cannot see.
            time_cluster=(prior.time_cluster if prior else None),
            cluster_confidence=(prior.cluster_confidence if prior else "UNKNOWN"),
            evidence={"why": why, "source": "backfill from camera_health",
                      "frames": frames}))

    print(f"\ngraded {graded} camera(s); {skipped} left UNKNOWN "
          f"(no frames observed — silence is not evidence of good timing)")
    if not a.apply:
        print("dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
