"""A bounded rolling buffer, so live evidence can include the frames.

Government feeds are live and not seekable. There is no going back to fetch the
moment an alert fired, so by the time anyone knows a frame mattered it is gone —
which is why every evidence record sealed from the live grid so far has been
`METADATA_ONLY`: truthful, and much weaker than it needs to be.

This keeps the last few seconds of selected cameras in memory, encoded, so that
when an event fires the system can retain what led up to it as well as the
moment itself. Three windows, because an investigator asks three questions:

    pre     what was approaching
    event   the sighting the alert rests on
    post    where it went

Bounded by construction, in three independent ways. Frames are JPEG-encoded on
arrival rather than held as arrays — a 1920x1080 BGR frame is 6 MB raw and about
150 KB encoded, and the buffer would otherwise be the largest thing in the
process. Each camera keeps a fixed number of frames. And the total byte budget
is enforced across all cameras, evicting oldest-first, so adding cameras cannot
grow memory without limit.

Nothing here decides *whether* to retain. That is the caller's decision, made
against a policy, and recorded in the audit log.
"""
from __future__ import annotations

import io
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

log = logging.getLogger("saakshya.evidence.buffer")

#: About five seconds at the tiers that matter, and a hard ceiling per camera.
DEFAULT_FRAMES_PER_CAMERA = 24
#: Across every camera. 48 MB holds roughly 320 encoded 1080p frames — enough
#: for a dozen cameras at five seconds each, and small enough that the buffer is
#: never the reason a live run runs out of memory.
DEFAULT_BUDGET_BYTES = 48 * 1024 * 1024
#: Encode quality. High enough that a plate legible in the frame stays legible;
#: low enough that the budget holds a useful window.
JPEG_QUALITY = 88


@dataclass(frozen=True)
class BufferedFrame:
    camera_id: str
    segment_id: str
    pts_s: float
    t_norm: datetime
    jpeg: bytes
    width: int
    height: int

    @property
    def nbytes(self) -> int:
        return len(self.jpeg)

    def to_array(self) -> np.ndarray:
        """Decode back to BGR, for hashing or writing a still."""
        from PIL import Image

        with Image.open(io.BytesIO(self.jpeg)) as im:
            return np.asarray(im.convert("RGB"))[:, :, ::-1].copy()


def encode(image: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(image[:, :, ::-1]).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class RollingBuffer:
    """Recent frames for selected cameras, bounded in count and in bytes.

    Thread-safe: camera workers write from their own threads, and an alert
    handler reads from another. The lock is held only around deque mutation,
    never across encoding or I/O.
    """

    def __init__(self, *, frames_per_camera: int = DEFAULT_FRAMES_PER_CAMERA,
                 budget_bytes: int = DEFAULT_BUDGET_BYTES) -> None:
        self.frames_per_camera = frames_per_camera
        self.budget_bytes = budget_bytes
        self._cams: dict[str, deque[BufferedFrame]] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        self.dropped_for_budget = 0

    # -- writing ------------------------------------------------------------ #
    def offer(self, camera_id: str, segment_id: str, pts_s: float,
              t_norm: datetime, image: np.ndarray) -> None:
        """Add a frame. Encoding happens outside the lock, deliberately.

        A camera worker calling this is holding an RTSP session open on the
        organiser's grid; it must not wait on another camera's encode.
        """
        jpeg = encode(image)
        h, w = image.shape[:2]
        frame = BufferedFrame(camera_id, segment_id, pts_s, t_norm, jpeg, w, h)
        with self._lock:
            q = self._cams.setdefault(camera_id, deque(maxlen=self.frames_per_camera))
            if len(q) == q.maxlen and q:
                self._bytes -= q[0].nbytes
            q.append(frame)
            self._bytes += frame.nbytes
            self._evict_to_budget()

    def _evict_to_budget(self) -> None:
        """Oldest-first across every camera. Caller holds the lock."""
        while self._bytes > self.budget_bytes:
            oldest_cam, oldest = None, None
            for cam, q in self._cams.items():
                if q and (oldest is None or q[0].t_norm < oldest.t_norm):
                    oldest_cam, oldest = cam, q[0]
            if oldest_cam is None:
                return
            self._bytes -= self._cams[oldest_cam].popleft().nbytes
            self.dropped_for_budget += 1

    # -- reading ------------------------------------------------------------ #
    def window(self, camera_id: str, *, at_pts_s: float,
               pre_s: float = 3.0, post_s: float = 3.0) -> list[BufferedFrame]:
        """Frames around a moment, by PTS.

        Selected on presentation timestamp, never on arrival order: frames from
        a stream that reconnected mid-window arrive out of order and would
        otherwise produce a "clip" whose frames are not contiguous in the
        video's own time.
        """
        with self._lock:
            frames = list(self._cams.get(camera_id, ()))
        lo, hi = at_pts_s - pre_s, at_pts_s + post_s
        return sorted((f for f in frames if lo <= f.pts_s <= hi),
                      key=lambda f: f.pts_s)

    def nearest(self, camera_id: str, at_pts_s: float,
                tolerance_s: float = 1.5) -> BufferedFrame | None:
        """The single frame closest to a moment, or None if none is close.

        Returning a frame from six seconds away because nothing nearer survived
        would attach the wrong image to a sighting, which is worse than
        attaching none.
        """
        with self._lock:
            frames = list(self._cams.get(camera_id, ()))
        if not frames:
            return None
        best = min(frames, key=lambda f: abs(f.pts_s - at_pts_s))
        return best if abs(best.pts_s - at_pts_s) <= tolerance_s else None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            per_cam = {c: len(q) for c, q in self._cams.items()}
            held = self._bytes
        return {
            "cameras": len(per_cam),
            "frames": sum(per_cam.values()),
            "bytes": held,
            "budget_bytes": self.budget_bytes,
            "frames_per_camera": self.frames_per_camera,
            "dropped_for_budget": self.dropped_for_budget,
            "per_camera": per_cam,
            "note": ("Live feeds are not seekable. Without this, an alert can "
                     "only ever be evidenced by metadata, because the frame it "
                     "rests on is gone by the time anyone knows it mattered."),
        }
