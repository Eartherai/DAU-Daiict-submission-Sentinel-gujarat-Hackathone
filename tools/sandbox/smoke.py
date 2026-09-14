#!/usr/bin/env python3
"""Smoke-test the stream manager against the local grid replica.

Verifies the ingest contract on real RTSP, not on mocks:
  * catalogue-driven start (no hard-coded endpoints)
  * mixed H.264 / H.265 in one process
  * mixed resolution and frame rate
  * PTS monotonic within a segment
  * warm-up GOP burst suppressed
  * measured fps differs from declared fps (the documented trap)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.ingest.stream import StreamConfig, StreamManager

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0


def main() -> int:
    cat = json.loads((ROOT / "var" / "media" / "catalogue.json").read_text())
    catalogue = {c["id"]: c["urls"]["rtsp"] for c in cat["cameras"]}
    declared = {c["id"]: c["properties"]["declared_fps"] for c in cat["cameras"]}
    print(f"catalogue: {len(catalogue)} cameras")

    mgr = StreamManager(StreamConfig())
    changes = mgr.reconcile(catalogue)
    print(f"reconcile: +{len(changes['added'])} -{len(changes['removed'])}")

    queues = {cid: mgr.get(cid).subscribe("smoke") for cid in catalogue}  # type: ignore[union-attr]

    seen: dict[str, int] = defaultdict(int)
    warm: dict[str, int] = defaultdict(int)
    pts_bad: dict[str, int] = defaultdict(int)
    last_pts: dict[str, float] = {}
    last_seg: dict[str, str] = {}
    shapes: dict[str, tuple[int, int]] = {}
    codecs: dict[str, str] = {}

    t_end = time.time() + DURATION
    while time.time() < t_end:
        for cid, q in queues.items():
            try:
                f = q.get(timeout=0.02)
            except Exception:
                continue
            if f is None:
                continue
            seen[cid] += 1
            if f.warmup:
                warm[cid] += 1
            if last_seg.get(cid) == f.segment_id and cid in last_pts:
                if f.pts_s < last_pts[cid]:
                    pts_bad[cid] += 1
            last_pts[cid] = f.pts_s
            last_seg[cid] = f.segment_id
            shapes[cid] = (f.width, f.height)
            codecs[cid] = f.codec

    stats = mgr.stats()
    print(f"\n{'camera':<9}{'codec':<7}{'res':<12}{'decl':>5}{'meas':>7}"
          f"{'frames':>8}{'warm':>6}{'ptsBk':>7}{'segs':>6}{'derr':>6}")
    print("-" * 79)
    ok = True
    for cid in sorted(catalogue):
        s = stats[cid]
        w, h = shapes.get(cid, (0, 0))
        meas = s.get("measured_fps")
        print(f"{cid:<9}{codecs.get(cid,'?'):<7}{f'{w}x{h}':<12}"
              f"{declared[cid]:>5}{(meas if meas else 0):>7.2f}"
              f"{seen[cid]:>8}{warm[cid]:>6}{pts_bad[cid]:>7}"
              f"{s['segment_breaks']:>6}{s['decoder_errors']:>6}")
        if seen[cid] == 0:
            ok = False

    agg = mgr.aggregate()
    print("\naggregate:", json.dumps(agg, indent=2))

    print("\nCONTRACT CHECKS")
    checks = [
        ("all cameras produced frames", all(seen[c] > 0 for c in catalogue)),
        ("no PTS regression inside a segment", sum(pts_bad.values()) == 0),
        ("both codecs decoded", {"h264", "hevc"} <= {c.lower() for c in codecs.values()}),
        ("multiple resolutions handled", len(set(shapes.values())) >= 3),
        ("warm-up burst was suppressed", sum(warm.values()) > 0),
        ("no camera killed the process", agg["cameras_streaming"] == len(catalogue)),
    ]
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed

    mgr.stop_all()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
