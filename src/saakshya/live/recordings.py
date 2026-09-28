"""Public provenance for locally captured government recordings (no URLs)."""
from __future__ import annotations

import json
from pathlib import Path

from saakshya.live.snapshot import local_media_url


def recording_metadata(camera_id: str) -> dict:
    path = local_media_url(camera_id)
    if not path or not camera_id.startswith("GOVREC-"):
        return {}
    try:
        data = json.loads(Path(path).with_suffix(".manifest.json").read_text())
        if data["camera_id"] != camera_id or data["source_camera_id"] != camera_id.removeprefix("GOVREC-"):
            return {}
        captured = data["capture_start_ist"]
        label = "SYNTHETIC OFFLINE TEST" if data.get("synthetic") else "RECORDED"
        return {"recorded_file": True, "source_camera_id": data["source_camera_id"],
                "capture_start_ist": captured, "capture_end_ist": data["capture_end_ist"],
                "recording_label": f"{label} · captured {captured[:10]}",
                "synthetic": bool(data.get("synthetic"))}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
