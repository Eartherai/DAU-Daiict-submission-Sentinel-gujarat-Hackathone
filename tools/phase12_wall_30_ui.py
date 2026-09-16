#!/usr/bin/env python3
"""Phase 12 — 30-camera operator wall (direct Sentinel WHEP + adaptive tiers).

Opens headed Chromium Metal with 30 tiles. Assigns FULL_WHEP to measured budget
and marks remaining as PREVIEW/CONNECTING/NO_SIGNAL. Does not start MediaMTX.
Credentials: Authorization Basic header only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402
from saakshya.live.grid import GridConfig  # noqa: E402
from tools.phase12_adaptive_scheduler import (  # noqa: E402
    CameraDemand, ResourceSnapshot, assign, budget_full_whep,
)
from tools.sentinel_direct_whep import (  # noqa: E402
    basic_authorization_header, measure_direct_wall, summarize,
    refuse_secrets, safe, whep_url,
)

OUT = ROOT / "var/reports/phase10/performance"

# Strong set from Phase 12 MEASURED_REAL peak PASS band
STRONG = [
    "cam01", "cam02", "cam05", "cam04", "cam13",
    "cam14", "cam15", "cam19", "cam03", "cam06",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--full-budget", type=int, default=10,
                        help="Seed from MEASURED peak PASS (~8–10 real)")
    parser.add_argument("--focus", default="cam01")
    parser.add_argument("--seconds", type=float, default=25)
    parser.add_argument("--negotiate-concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path,
                        default=OUT / "phase12_wall_30_ui.json")
    args = parser.parse_args()
    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    cfg = GridConfig.from_env()
    auth = basic_authorization_header()
    ids = [f"cam{i:02d}" for i in range(1, args.n + 1)]
    hevc = {"cam06", "cam12", "cam17"}

    # Prefer strong cams for FULL_WHEP slots
    demands = []
    for i, cid in enumerate(ids):
        pri = 200 - i if cid in STRONG else 50 - i
        if cid == args.focus:
            pri = 1000
        demands.append(CameraDemand(
            camera_id=cid,
            priority=pri,
            operator_focus=(cid == args.focus),
            codec="hevc" if cid in hevc else "h264",
            whep_available=True,
        ))
    res = ResourceSnapshot(cpu_percent=50.0)
    budget = min(args.full_budget, budget_full_whep(res, measured_peak=args.full_budget))
    assignments = assign(demands, res, measured_peak=budget)

    full_cams = [
        a.camera_id for a in assignments if a.representation == "FULL_WHEP"
    ]
    print(f"FULL_WHEP budget={budget} cams={full_cams}", flush=True)

    # Measure only FULL_WHEP tiles (browser capacity band)
    endpoints = [whep_url(c, cfg) for c in full_cams]
    wall = measure_direct_wall(
        endpoints, auth_header=auth, seconds=args.seconds,
        negotiate_concurrency=args.negotiate_concurrency, retries=1,
    )
    measured = summarize(
        full_cams, wall, seconds=args.seconds,
        path_label="DIRECT_SENTINEL_WHEP_REAL_30WALL",
    )
    by_id = {t["camera_id"]: t for t in measured.get("tiles") or []}

    # Merge UX states for all 30
    tiles_ui = []
    for a in assignments:
        m = by_id.get(a.camera_id)
        if a.representation == "FULL_WHEP" and m:
            if m["verdict"] == "PASS":
                ux = "LIVE"
            elif m["verdict"] == "AMBER":
                ux = "DEGRADED"
            elif m["verdict"] == "NO_FRAME":
                ux = "CONNECTING"
            else:
                ux = "NO_SIGNAL"
            tiles_ui.append({
                **{k: getattr(a, k) for k in (
                    "camera_id", "tier", "representation", "path", "reason")},
                "ux_state": ux,
                "measured": {
                    "verdict": m["verdict"],
                    "first_frame_ms": m.get("first_frame_ms"),
                    "currentTime": m.get("currentTime"),
                    "freezes": m.get("freezes"),
                    "effective_fps": m.get("effective_fps"),
                    "whep_http_status": m.get("whep_http_status"),
                },
            })
        else:
            # Preview tier — live representation deferred; never label LIVE
            tiles_ui.append({
                "camera_id": a.camera_id,
                "tier": a.tier,
                "representation": a.representation,
                "path": a.path,
                "reason": a.reason,
                "ux_state": "PREVIEW" if a.representation == "PREVIEW_LIVE" else a.ux_state,
                "measured": None,
                "note": (
                    "Preview slot — not labeled LIVE until live transport attached. "
                    "Not a static screenshot placeholder in product path."
                ),
            })

    live = sum(1 for t in tiles_ui if t["ux_state"] == "LIVE")
    preview = sum(1 for t in tiles_ui if t["ux_state"] == "PREVIEW")
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED_REAL_AND_DESIGNED",
        "registered": args.n,
        "full_whep_budget": budget,
        "full_whep_measured": measured.get("wall_summary"),
        "full_whep_overall": measured.get("overall"),
        "ux_counts": {
            "LIVE": live,
            "PREVIEW": preview,
            "DEGRADED": sum(1 for t in tiles_ui if t["ux_state"] == "DEGRADED"),
            "CONNECTING": sum(1 for t in tiles_ui if t["ux_state"] == "CONNECTING"),
            "NO_SIGNAL": sum(1 for t in tiles_ui if t["ux_state"] == "NO_SIGNAL"),
            "RECONNECTING": sum(1 for t in tiles_ui if t["ux_state"] == "RECONNECTING"),
        },
        "tiles": tiles_ui,
        "browser": measured.get("browser_wall"),
        "catalogue_authoritative": False,
        "credentials_in_artifact": False,
    }
    blob = json.dumps(payload, indent=2) + "\n"
    refuse_secrets(blob)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(blob)
    print(json.dumps({
        "full_whep_overall": measured.get("overall"),
        "full_summary": measured.get("wall_summary"),
        "ux_counts": payload["ux_counts"],
    }), flush=True)
    return 0 if measured.get("overall") != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
