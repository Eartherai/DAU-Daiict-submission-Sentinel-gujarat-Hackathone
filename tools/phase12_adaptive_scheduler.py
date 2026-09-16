#!/usr/bin/env python3
"""Phase 12 adaptive media tier scheduler for real 30-camera wall.

Does not hardcode 8 WHEP. Budgets from MEASURED peak PASS band.
Tile UX states: LIVE, PREVIEW, CONNECTING, DEGRADED, RECONNECTING, NO_SIGNAL.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/phase10/performance"

TILE_STATES = (
    "LIVE", "PREVIEW", "CONNECTING", "DEGRADED", "RECONNECTING", "NO_SIGNAL",
)


@dataclass
class ResourceSnapshot:
    cpu_percent: float = 40.0
    gpu_pressure: float = 0.3  # 0..1
    ram_available_gb: float = 8.0
    active_full_whep: int = 0
    network_pressure: float = 0.2
    browser_memory_mb: float = 1500.0


@dataclass
class CameraDemand:
    camera_id: str
    priority: int = 50  # higher = more important
    operator_focus: bool = False
    alert_active: bool = False
    codec: str = "h264"
    whep_available: bool = True
    last_verdict: str = "UNKNOWN"


@dataclass
class Assignment:
    camera_id: str
    tier: str  # PRIMARY | SECONDARY | PREVIEW | INACTIVE
    representation: str  # FULL_WHEP | PREVIEW_LIVE | INACTIVE
    ux_state: str
    path: str
    reason: str


def budget_full_whep(res: ResourceSnapshot, *, measured_peak: int = 16) -> int:
    """Dynamic FULL_WHEP budget from resource pressure + measured peak."""
    base = measured_peak
    if res.cpu_percent > 85 or res.gpu_pressure > 0.85:
        base = max(4, measured_peak // 3)
    elif res.cpu_percent > 70 or res.gpu_pressure > 0.65:
        base = max(6, measured_peak // 2)
    elif res.cpu_percent > 55 or res.gpu_pressure > 0.5:
        base = max(8, int(measured_peak * 0.75))
    if res.ram_available_gb < 2.0:
        base = min(base, 6)
    if res.network_pressure > 0.8:
        base = max(4, base - 4)
    return max(1, min(base, measured_peak))


def assign(cameras: list[CameraDemand], res: ResourceSnapshot,
           *, measured_peak: int = 16) -> list[Assignment]:
    budget = budget_full_whep(res, measured_peak=measured_peak)
    ordered = sorted(
        cameras,
        key=lambda c: (
            0 if c.operator_focus else 1,
            0 if c.alert_active else 1,
            -c.priority,
            0 if c.codec == "h264" else 1,
        ),
    )
    out: list[Assignment] = []
    used = 0
    primary_set = False
    for cam in ordered:
        path = "HEVC_TRANSCODED_H264" if cam.codec == "hevc" else "DIRECT_H264"
        if not cam.whep_available:
            out.append(Assignment(
                cam.camera_id, "INACTIVE", "INACTIVE", "NO_SIGNAL", path,
                "whep unavailable / source down",
            ))
            continue
        if cam.last_verdict == "FAIL" and not cam.operator_focus:
            out.append(Assignment(
                cam.camera_id, "PREVIEW", "PREVIEW_LIVE", "RECONNECTING", path,
                "prior FAIL — retry as preview",
            ))
            continue
        want_full = cam.operator_focus or cam.alert_active or used < budget
        if want_full and used < budget:
            if not primary_set and (cam.operator_focus or cam.alert_active or used == 0):
                tier, reason = "PRIMARY", "operator focus / alert / first full"
                primary_set = True
            else:
                tier, reason = "SECONDARY", "within measured FULL_WHEP budget"
            used += 1
            state = "LIVE" if cam.last_verdict in {"PASS", "UNKNOWN", "AMBER"} else "DEGRADED"
            out.append(Assignment(
                cam.camera_id, tier, "FULL_WHEP", state, path, reason,
            ))
        else:
            out.append(Assignment(
                cam.camera_id, "PREVIEW", "PREVIEW_LIVE", "PREVIEW", path,
                "outside full WHEP budget — live preview",
            ))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--measured-peak", type=int, default=10)
    parser.add_argument("--focus", default="cam01")
    parser.add_argument("--alert", default="")
    parser.add_argument("--cpu", type=float, default=45.0)
    parser.add_argument(
        "--census", type=Path,
        default=OUT / "phase14_source_census.json",
        help="Phase 14 census JSON — drives whep_available / health",
    )
    parser.add_argument("--out", type=Path,
                        default=OUT / "phase12_adaptive_scheduler.json")
    args = parser.parse_args()

    census_by_id: dict = {}
    if args.census.exists():
        try:
            blob = json.loads(args.census.read_text())
            for row in blob.get("cameras") or []:
                census_by_id[row["camera_id"]] = row
        except Exception:
            census_by_id = {}

    ids = [f"cam{i:02d}" for i in range(1, args.n + 1)]
    hevc = {"cam06", "cam12", "cam17", "cam18", "cam22", "cam26"}
    cams = []
    for i, cid in enumerate(ids):
        crow = census_by_id.get(cid) or {}
        whep_ok = bool(crow.get("whep_frames")) if crow else True
        rtsp_ok = bool(crow.get("rtsp_frames")) if crow else True
        codec = crow.get("codec") or ("hevc" if cid in hevc else "h264")
        if crow.get("source_health") == "LIVE":
            verdict = "PASS"
        elif crow.get("source_health") in {"WHEP_UNAVAILABLE", "HEVC_UNSUPPORTED"}:
            verdict = "AMBER" if rtsp_ok else "FAIL"
        elif crow:
            verdict = "FAIL"
        else:
            verdict = "UNKNOWN"
        cams.append(CameraDemand(
            camera_id=cid,
            priority=100 - i if whep_ok else 40 - i,
            operator_focus=(cid == args.focus),
            alert_active=(cid == args.alert),
            codec=codec if codec in {"h264", "hevc"} else "h264",
            whep_available=whep_ok,
            last_verdict=verdict,
        ))
    res = ResourceSnapshot(cpu_percent=args.cpu)
    assignments = assign(cams, res, measured_peak=args.measured_peak)
    # Relabel: no WHEP + RTSP ok → AWAITING_SLOT-equivalent PREVIEW reason
    for a in assignments:
        crow = census_by_id.get(a.camera_id) or {}
        if crow and crow.get("rtsp_frames") and not crow.get("whep_frames"):
            if a.representation != "FULL_WHEP":
                a.ux_state = "NO_SIGNAL" if not crow.get("rtsp_frames") else "PREVIEW"
                a.reason = "RTSP live; browser WHEP unavailable — not false NO_SIGNAL source-down"
                a.representation = "PREVIEW_LIVE"
                a.tier = "PREVIEW"
    counts: dict[str, int] = {}
    for a in assignments:
        counts[a.tier] = counts.get(a.tier, 0) + 1
        counts[a.representation] = counts.get(a.representation, 0) + 1
        counts[a.ux_state] = counts.get(a.ux_state, 0) + 1

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "DESIGNED",
        "measured_peak_seed": args.measured_peak,
        "dynamic_full_whep_budget": budget_full_whep(res, measured_peak=args.measured_peak),
        "resource_snapshot": asdict(res),
        "tile_states_supported": list(TILE_STATES),
        "counts": counts,
        "assignments": [asdict(a) for a in assignments],
        "note": (
            "Budget is dynamic from resource pressure and MEASURED peak — "
            "not a hardcoded 8."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "budget": payload["dynamic_full_whep_budget"],
        "counts": counts,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
