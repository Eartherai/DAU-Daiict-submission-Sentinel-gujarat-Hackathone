#!/usr/bin/env python3
"""Measure hub AI: boxes, observations, alerts. Never invent detections."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("SAAKSHYA_BASE", "http://127.0.0.1:8080")
TOKEN = Path("/tmp/saakshya-demo-token.raw")


def _get(path: str) -> dict:
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Bearer {TOKEN.read_text().strip()}",
                 "X-Case-Id": "FIR-214/2026",
                 "X-Purpose": "hub AI measurement"},
    )
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def main() -> int:
    hub = _get("/media/hub")
    out: dict = {
        "plane": hub.get("plane"),
        "ai_cameras": hub.get("ai_cameras") or [],
        "cameras": {},
        "label": "MEASURED — zeros mean the pipeline produced nothing, not a fake",
    }
    for cid in hub.get("ai_cameras") or ["OWN-PEOPLE", "OWN-TRAFFIC"]:
        row = next((c for c in hub.get("cameras") or [] if c.get("camera_id") == cid), {})
        try:
            boxes = _get(f"/command/cameras/{cid}/boxes?overlay=full&people=true&vehicles=true&anpr=true")
        except Exception as exc:
            boxes = {"error": type(exc).__name__}
        try:
            scene = _get(f"/command/cameras/{cid}/scene")
        except Exception as exc:
            scene = {"error": type(exc).__name__}
        out["cameras"][cid] = {
            "source": row.get("source"),
            "video": row.get("video"),
            "ai": row.get("ai"),
            "dropped_ai": row.get("dropped_ai"),
            "jpeg_fps": row.get("jpeg_fps"),
            "hub_boxes": len(boxes.get("boxes") or []) if isinstance(boxes, dict) else 0,
            "people": (boxes.get("people") if isinstance(boxes, dict) else None),
            "vehicles": (boxes.get("vehicles") if isinstance(boxes, dict) else None),
            "tracked": (boxes.get("tracked") if isinstance(boxes, dict) else None),
            "scene": scene,
            "label": row.get("label") or "MEASURED_OWN_FEED",
        }
        print(cid, out["cameras"][cid]["ai"],
              "boxes", out["cameras"][cid]["hub_boxes"],
              "people", out["cameras"][cid]["people"],
              "vehicles", out["cameras"][cid]["vehicles"],
              flush=True)
    dest = ROOT / "reports/final_live_qa/hub_ai.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
