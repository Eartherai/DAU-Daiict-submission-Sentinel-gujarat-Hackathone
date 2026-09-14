"""Latest still from the ingest process, so the live wall does not open a second stream.

The integrator guide is explicit: each connected client receives its own copy.
A thirty-camera ingest already holds thirty RTSP sessions. A live wall that then
opens a snapshot per tile is thirty more, and under that load a capture waits
past its timeout and the wall looks down.

Ingest writes one JPEG per camera as it analyses. The API reads that file when
it is fresh and never opens the grid for a preview. The file is a still, not
evidence — same class as the snapshot service's own capture.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def preview_dir() -> Path:
    root = os.environ.get("SAAKSHYA_EVIDENCE", "var/live_evidence")
    return Path(root) / "preview"


def preview_path(camera_id: str) -> Path | None:
    if not camera_id or not _SAFE_ID.match(camera_id):
        return None
    return preview_dir() / f"{camera_id}.jpg"


def write_preview(camera_id: str, bgr: np.ndarray, *,
                  max_width: int = 1280, quality: int = 90) -> None:
    """Overwrite the latest still for this camera. Best-effort; never raises."""
    path = preview_path(camera_id)
    if path is None or bgr is None or bgr.size == 0:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        w = bgr.shape[1]
        if w > max_width:
            step = max(1, w // max_width)
            bgr = bgr[::step, ::step]
        rgb = np.ascontiguousarray(bgr[:, :, ::-1])
        Image.fromarray(rgb).save(path, format="JPEG", quality=quality,
                                  optimize=True)
    except Exception:
        return


def read_preview(camera_id: str, *, max_age_s: float = 20.0
                 ) -> tuple[bytes, int, int, float] | None:
    """JPEG bytes, width, height, age in seconds — or None if missing/stale."""
    path = preview_path(camera_id)
    if path is None or not path.is_file():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > max_age_s:
            return None
        data = path.read_bytes()
        if not data:
            return None
        with Image.open(path) as im:
            w, h = im.size
        return data, w, h, age
    except Exception:
        return None


def count_stills() -> int:
    """How many cameras have a stored JPEG, regardless of age.

    Overview uses this for "showing a frame" when ingest is paused: the wall
    still has pictures, and pretending those cameras show nothing made the
    command picture look empty.
    """
    root = preview_dir()
    if not root.is_dir():
        return 0
    n = 0
    try:
        for path in root.glob("*.jpg"):
            try:
                if path.is_file() and path.stat().st_size > 800:
                    n += 1
            except OSError:
                continue
    except OSError:
        return 0
    return n


def preview_usable(camera_id: str) -> bool:
    """Whether the stored still is fit to put on a plate card.

    Some government cameras publish a JPEG that is IR false-colour, a decode
    mosaic, or nearly black. Those files are still the camera — they must not
    be the picture under a registration mark on the command picture.
    """
    import numpy as np

    path = preview_path(camera_id)
    if path is None or not path.is_file():
        return False
    try:
        if path.stat().st_size < 1_500:
            return False
        with Image.open(path) as im:
            rgb = im.convert("RGB").resize((96, 54))
        arr = np.asarray(rgb, dtype=np.float32)
        r, g, b = (float(x) for x in arr.mean(axis=(0, 1)))
        if (g - max(r, b)) > 28:
            return False
        mean = float(arr.mean())
        if mean < 18 or mean > 222:
            return False
        chroma = float(np.mean(np.std(arr, axis=2)))
        if chroma < 1.8:
            return False
        gray = arr.mean(axis=2)
        dx = float(np.abs(np.diff(gray, axis=1)).mean())
        dy = float(np.abs(np.diff(gray, axis=0)).mean())
        if dx > 19 or dy > 19:
            return False
        return True
    except Exception:
        return False


def ingest_is_publishing(*, max_age_s: float = 90.0) -> bool:
    """Whether the ingest process has written a still recently.

    Used by the snapshot service to refuse a second RTSP session while thirty
    already exist. A missing file for one camera is not a reason to open the
    grid; it is a reason to say that camera has not published a still yet.
    """
    root = preview_dir()
    if not root.is_dir():
        return False
    now = time.time()
    try:
        for path in root.glob("*.jpg"):
            if now - path.stat().st_mtime <= max_age_s:
                return True
    except OSError:
        return False
    return False
