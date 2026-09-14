"""A bounded rolling buffer, so an alert can seal what the camera actually saw.

Government feeds here are live and not seekable: by the time an alert fires, the
moment is gone and cannot be fetched back. Every evidence record this system has
produced is therefore `METADATA_ONLY` — it attests what the system observed and
when, and says so on its face, but it is not a copy of the footage.

Holding a short window of recent frames closes that gap for the sightings that
matter, without retaining government video at large. The design constraints are
the interesting part:

  * **Bounded, per camera, in bytes.** Thirty cameras at 1080p is 6 MB a frame
    raw; ten seconds of that is gigabytes and the next outage. Frames are held
    JPEG-encoded and the buffer evicts by total size, not by count, because
    frame size varies by an order of magnitude across this estate.

  * **Only what was analysed.** Buffering every decoded frame would multiply
    memory by the decode rate for no evidential gain — the frames that matter
    are the ones an observation came from.

  * **Retained only on an event.** The buffer is a ring that overwrites itself.
    Nothing reaches disk until something asks for it, so a camera that never
    triggers an alert never writes a byte of imagery.

  * **Pre, event, and post.** An investigator needs the approach as well as the
    moment. Post-event frames arrive *after* the trigger, so a capture stays
    open and completes as they land rather than blocking the alert on them.
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("saakshya.evidence.rolling")

#: Bytes of encoded frames held per camera. 24 MB is roughly ten seconds at two
#: analysed frames per second on a 1080p stream, and thirty cameras of it is
#: 720 MB — affordable beside a 1.6 GB ingest, and bounded whatever the estate
#: does. A camera whose frames are unusually large simply holds fewer of them.
DEFAULT_BUDGET_BYTES = 24 * 1024 * 1024

#: JPEG quality for retained frames. Evidence should not be re-encoded at all,
#: and this is a compromise the manifest states plainly: the hash covers what
#: was retained, and what was retained is a re-encode of the decoded frame, not
#: the original compressed bitstream.
JPEG_QUALITY = 92


@dataclass
class Held:
    """One retained frame, with the timing that places it."""

    pts_s: float
    t_norm: datetime
    data: bytes
    width: int
    height: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class Capture:
    """An in-progress retention around one event."""

    camera_id: str
    observation_id: str
    reason: str
    pre: list[Held]
    post: list[Held] = field(default_factory=list)
    post_wanted: int = 0

    @property
    def complete(self) -> bool:
        return len(self.post) >= self.post_wanted

    @property
    def frames(self) -> list[Held]:
        return [*self.pre, *self.post]


class RollingBuffer:
    """Recent analysed frames for one camera, bounded by total encoded size."""

    def __init__(self, camera_id: str,
                 budget_bytes: int = DEFAULT_BUDGET_BYTES) -> None:
        self.camera_id = camera_id
        self.budget = budget_bytes
        self._frames: deque[Held] = deque()
        self._bytes = 0
        self._lock = threading.Lock()
        self.evicted = 0

    def __len__(self) -> int:
        return len(self._frames)

    @property
    def bytes_held(self) -> int:
        return self._bytes

    def add(self, image: np.ndarray, pts_s: float, t_norm: datetime) -> Held:
        """Encode and hold one analysed frame, evicting the oldest as needed.

        The buffer never empties itself completely: an event arriving now needs
        the picture from now, even on a camera whose single frame is larger than
        the whole budget. So the bound honoured here is **budget plus at most
        one frame**, not budget outright, and callers sizing memory for a large
        estate should reckon on that.
        """
        held = Held(pts_s=pts_s, t_norm=t_norm, data=_encode(image),
                    width=image.shape[1], height=image.shape[0])
        with self._lock:
            self._frames.append(held)
            self._bytes += len(held.data)
            while self._bytes > self.budget and len(self._frames) > 1:
                gone = self._frames.popleft()
                self._bytes -= len(gone.data)
                self.evicted += 1
        return held

    def snapshot(self, count: int) -> list[Held]:
        """The most recent `count` frames, oldest first."""
        with self._lock:
            if count <= 0:
                return []
            return list(self._frames)[-count:]


def _encode(image: np.ndarray) -> bytes:
    from PIL import Image

    rgb = image[:, :, ::-1] if image.ndim == 3 else image
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgb)).save(
        buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


class RollingEvidence:
    """Per-camera buffers, and the captures opened against them."""

    def __init__(self, root: Path | str, *,
                 budget_bytes: int = DEFAULT_BUDGET_BYTES,
                 pre_frames: int = 6, post_frames: int = 6) -> None:
        self.root = Path(root)
        self.budget = budget_bytes
        self.pre_frames = pre_frames
        self.post_frames = post_frames
        self._buffers: dict[str, RollingBuffer] = {}
        self._open: list[Capture] = []
        self._lock = threading.Lock()
        self.retained = 0

    def buffer(self, camera_id: str) -> RollingBuffer:
        with self._lock:
            buf = self._buffers.get(camera_id)
            if buf is None:
                buf = self._buffers[camera_id] = RollingBuffer(
                    camera_id, self.budget)
            return buf

    def observe(self, camera_id: str, image: np.ndarray, pts_s: float,
                t_norm: datetime) -> None:
        """Offer one analysed frame to the buffer and to any open capture."""
        held = self.buffer(camera_id).add(image, pts_s, t_norm)
        with self._lock:
            for cap in self._open:
                if cap.camera_id == camera_id and not cap.complete:
                    cap.post.append(held)

    def on_event(self, camera_id: str, observation_id: str, reason: str
                 ) -> Capture:
        """Open a retention around an event that has just fired.

        The pre-event frames are taken now; the post-event ones accumulate as
        they arrive. Waiting for them here would hold up the alert, and an alert
        that arrives late to spare the evidence is the wrong trade.
        """
        cap = Capture(camera_id=camera_id, observation_id=observation_id,
                      reason=reason,
                      pre=self.buffer(camera_id).snapshot(self.pre_frames),
                      post_wanted=self.post_frames)
        with self._lock:
            self._open.append(cap)
        return cap

    def close(self, cap: Capture) -> dict[str, Any] | None:
        """Write a completed capture to disk and return its manifest.

        Returns None when nothing was held — a camera whose buffer was empty at
        the moment of the event has no imagery to offer, and inventing an empty
        record would be worse than saying so.
        """
        with self._lock:
            if cap in self._open:
                self._open.remove(cap)
        frames = cap.frames
        if not frames:
            log.info("no buffered frames for %s at %s; the record stays "
                     "metadata-only", cap.camera_id, cap.observation_id)
            return None

        out = self.root / cap.observation_id
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for i, f in enumerate(frames):
            name = f"{i:03d}_pts{f.pts_s:.3f}.jpg"
            (out / name).write_bytes(f.data)
            written.append({"file": name, "pts_s": round(f.pts_s, 3),
                            "t_norm": f.t_norm.isoformat(),
                            "sha256": f.sha256, "bytes": len(f.data),
                            "width": f.width, "height": f.height,
                            "phase": "pre" if i < len(cap.pre) else "post"})
        self.retained += 1
        return {
            "observation_id": cap.observation_id,
            "camera_id": cap.camera_id,
            "reason": cap.reason,
            "frames": written,
            "pre_frames": len(cap.pre),
            "post_frames": len(cap.post),
            "directory": str(out),
            "caveat": (
                "Frames were re-encoded to JPEG from the decoded picture; the "
                "hashes cover what was retained, which is not the original "
                "compressed bitstream. The grid is live and not seekable, so "
                "this window is what could be preserved, not a selection from "
                "a recording."),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cameras": len(self._buffers),
                "frames_held": sum(len(b) for b in self._buffers.values()),
                "bytes_held": sum(b.bytes_held for b in self._buffers.values()),
                "budget_per_camera": self.budget,
                "evicted": sum(b.evicted for b in self._buffers.values()),
                "captures_open": len(self._open),
                "captures_retained": self.retained,
            }
