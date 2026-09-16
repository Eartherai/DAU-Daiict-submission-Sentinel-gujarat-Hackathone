#!/usr/bin/env python3
"""MediaResourceController — promote/demote cameras under resource pressure."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceSignals:
    cpu_percent: float
    ram_percent: float
    active_whep: int
    ai_queue_depth: int = 0
    measured_peak_pass: int = 12


@dataclass
class CameraDemand:
    camera_id: str
    operator_focus: bool = False
    alert: bool = False
    ai_priority: bool = False
    source_healthy: bool = True


def allocate(demands: list[CameraDemand], signals: ResourceSignals) -> list[dict]:
    pressure = 0
    if signals.cpu_percent > 85 or signals.ram_percent > 90:
        pressure = 3
    elif signals.cpu_percent > 70 or signals.ram_percent > 80:
        pressure = 2
    elif signals.cpu_percent > 55:
        pressure = 1

    full_budget = max(4, signals.measured_peak_pass - pressure * 2)
    if signals.ai_queue_depth > 20:
        full_budget = max(4, full_budget - 2)

    ordered = sorted(
        demands,
        key=lambda d: (
            0 if d.operator_focus else 1,
            0 if d.alert else 1,
            0 if d.ai_priority else 1,
            0 if d.source_healthy else 1,
        ),
    )
    out = []
    used = 0
    for d in ordered:
        if not d.source_healthy:
            tier, rep = "DEGRADED", "retry_live"
        elif d.operator_focus and used < full_budget:
            tier, rep = "PRIMARY", "full_whep"
            used += 1
        elif used < full_budget:
            tier, rep = "SECONDARY", "full_whep"
            used += 1
        else:
            tier, rep = "PREVIEW", "preview_live"
        out.append({
            "camera_id": d.camera_id,
            "tier": tier,
            "representation": rep,
            "full_budget": full_budget,
            "pressure": pressure,
        })
    return out


if __name__ == "__main__":
    demo = [CameraDemand("cam01", operator_focus=True)] + [
        CameraDemand(f"cam{i:02d}") for i in range(2, 31)
    ]
    alloc = allocate(demo, ResourceSignals(60, 70, 0, measured_peak_pass=12))
    print({
        "full_whep": sum(1 for a in alloc if a["representation"] == "full_whep"),
        "preview": sum(1 for a in alloc if a["representation"] == "preview_live"),
    })
