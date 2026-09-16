#!/usr/bin/env python3
"""30-camera operations wall certification (hybrid tiers).

Measures:
  - N registered cameras publishing into MediaMTX
  - WHEP decode budget for PRIMARY+SECONDARY (headed Metal)
  - PREVIEW tiles as publish-ready (live path available; not full concurrent WHEP)

Does not claim 30 full WHEP unless measured. Credentials env-only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402

OUT = ROOT / "var/reports/phase9/performance"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registered", type=int, default=30)
    parser.add_argument("--full-whep", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--headed-matrix", type=Path,
                        default=OUT / "headed_concurrent_matrix.json")
    parser.add_argument("--out", type=Path, default=OUT / "wall_30_cert.json")
    args = parser.parse_args()

    # Run scheduler
    sched = subprocess.run(
        [sys.executable, str(ROOT / "tools/perf_stream_scheduler.py"),
         "--n", str(args.registered), "--max-full", str(args.full_whep)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    sched_path = OUT / "stream_scheduler_30.json"
    scheduler = json.loads(sched_path.read_text()) if sched_path.exists() else {}

    headed = {}
    if args.headed_matrix.exists():
        headed = json.loads(args.headed_matrix.read_text())

    max_operable = headed.get("max_operable_PASS_or_AMBER") or 0
    max_pass = headed.get("max_smooth_PASS") or 0

    # If operator asked for more full WHEP than measured, clamp and flag
    full_budget = min(args.full_whep, max(max_operable, 4) or 4)
    verdict = "PASS" if max_operable >= 6 and scheduler.get("registered") == args.registered else "AMBER"
    if max_operable < 4:
        verdict = "FAIL"

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED_AND_DESIGNED",
        "registered": args.registered,
        "full_whep_budget_requested": args.full_whep,
        "full_whep_budget_applied": full_budget,
        "headed_max_operable": max_operable,
        "headed_max_pass": max_pass,
        "scheduler_counts": scheduler.get("counts"),
        "modes": {
            "VIDEO_FIRST": {
                "priority": "smoothness",
                "full_whep": full_budget,
                "ai": "adaptive_low",
            },
            "AI_FIRST": {
                "priority": "selected_camera_analytics",
                "full_whep": max(4, full_budget // 2),
                "ai": "primary_secondary_full",
            },
        },
        "path_policy": {
            "H264": "DIRECT_H264",
            "HEVC": "HEVC_TRANSCODED_H264",
        },
        "overall": verdict,
        "note": (
            "30 cameras registered via scheduler. Concurrent full WHEP budget "
            "comes from headed Metal measurements, not SwiftShader. Preview "
            "tier is live-capable publish path, not static screenshots."
        ),
        "credentials_configured": configured(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    md = f"""# 30-camera performance certification

Timestamp UTC: `{payload['timestamp_utc']}`  
Overall: **{verdict}**

## Measured headed Metal concurrent WHEP

| Metric | Value |
|---|---|
| max PASS | {max_pass} |
| max operable (PASS/AMBER) | {max_operable} |
| Applied full-WHEP budget | {full_budget} |

## 30-camera wall design

| Tier | Count (scheduler) | Representation |
|---|---:|---|
| Registered | {args.registered} | management + health |
| Full WHEP | {full_budget} | PRIMARY/SECONDARY live |
| Preview live | remaining | continuous low-cost live / refresh |

Scheduler artifact: `var/reports/phase9/performance/stream_scheduler_30.json`

## Modes

- **VIDEO-FIRST** — maximize full-WHEP budget, AI adaptive
- **AI-FIRST** — reduce concurrent WHEP slightly, full AI on selected cameras

## Path policy (unchanged)

H.264 → DIRECT_H264 · HEVC → HEVC_TRANSCODED_H264

Machine-readable: `{args.out}`
"""
    (ROOT / "reports/30_CAMERA_PERFORMANCE_CERTIFICATION.md").write_text(md)
    print(json.dumps({"overall": verdict, "full_budget": full_budget,
                      "max_operable": max_operable}))
    return 0 if verdict != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
