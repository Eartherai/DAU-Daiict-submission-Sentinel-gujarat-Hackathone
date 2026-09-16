#!/usr/bin/env python3
"""Resource-aware stream tier scheduler for 30-camera walls.

Budgets seeded from Phase 10 MEASURED browser ceiling (≥16 PASS synthetic;
gov source peak ~12 PASS).
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/phase10/performance"


@dataclass
class MachineBudget:
    max_full_whep: int = 16
    max_secondary_whep: int = 4
    preview_refresh_hz: float = 2.0
    label: str = "SEEDED_FROM_PHASE10_SYNTHETIC_PASS_16"


@dataclass
class TierAssignment:
    camera_id: str
    tier: str
    representation: str
    path: str
    reason: str


def assign(cameras: list[dict], *, primary_id: str | None,
           budget: MachineBudget) -> list[TierAssignment]:
    out: list[TierAssignment] = []
    remaining_full = budget.max_full_whep
    remaining_sec = budget.max_secondary_whep
    ordered = sorted(
        cameras,
        key=lambda c: (0 if c.get("camera_id") == primary_id else 1,
                       0 if (c.get("codec") or "").lower() == "h264" else 1),
    )
    hevc = {"cam06", "cam12", "cam17"}
    for cam in ordered:
        cid = cam["camera_id"]
        codec = (cam.get("codec") or "h264").lower()
        path = "HEVC_TRANSCODED_H264" if codec == "hevc" or cid in hevc else "DIRECT_H264"
        if cid == primary_id and remaining_full > 0:
            tier, rep, reason = "PRIMARY", "full_whep", "operator focus"
            remaining_full -= 1
        elif remaining_full > 0:
            tier, rep, reason = "SECONDARY", "full_whep", "full WHEP budget"
            remaining_full -= 1
        elif remaining_sec > 0:
            tier, rep, reason = "SECONDARY", "secondary_whep", "secondary live"
            remaining_sec -= 1
        else:
            tier, rep, reason = "PREVIEW", "preview_live", "live preview (not still)"
        out.append(TierAssignment(cid, tier, rep, path, reason))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--primary", default="cam01")
    parser.add_argument("--max-full", type=int, default=16)
    parser.add_argument("--max-secondary", type=int, default=4)
    parser.add_argument("--out", type=Path, default=OUT / "stream_scheduler_30.json")
    args = parser.parse_args()

    h264 = ["cam01", "cam02", "cam05", "cam04", "cam11",
            "cam13", "cam14", "cam15", "cam19"]
    hevc = ["cam06", "cam12", "cam17"]
    ids = []
    for c in h264 + hevc:
        if c not in ids:
            ids.append(c)
    i = 1
    while len(ids) < args.n:
        filler = f"cam{i:02d}"
        if filler not in ids:
            ids.append(filler)
        i += 1
        if i > 80:
            break
    ids = ids[: args.n]
    cameras = [{"camera_id": c, "codec": "hevc" if c in hevc else "h264"} for c in ids]
    budget = MachineBudget(max_full_whep=args.max_full,
                           max_secondary_whep=args.max_secondary)
    assignments = assign(cameras, primary_id=args.primary, budget=budget)
    counts: dict[str, int] = {}
    for a in assignments:
        counts[a.tier] = counts.get(a.tier, 0) + 1
        counts[a.representation] = counts.get(a.representation, 0) + 1
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "budget": asdict(budget),
        "registered": len(assignments),
        "counts": counts,
        "assignments": [asdict(a) for a in assignments],
        "note": (
            "PREVIEW is live representation, not a static screenshot. "
            "Full WHEP budget seeded from Phase 10 synthetic PASS band (≥16); "
            "government source peak remains ~12 until auth/sources recover."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"registered": len(assignments), "counts": counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
