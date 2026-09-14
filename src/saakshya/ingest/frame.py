"""The single internal frame interface.

Every analytics component consumes frames through this type and nothing else.
That keeps the video architecture in one place instead of one bespoke decode
path per model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass(slots=True)
class Frame:
    camera_id: str
    segment_id: str
    #: Presentation timestamp in seconds, from the stream. Ground truth for timing.
    pts_s: float
    #: Projected normalised timeline. Use this for motion and cross-camera reasoning.
    t_norm: datetime
    #: Wall-clock arrival. Diagnostics only — never use for motion.
    t_ingest: datetime
    #: BGR24 ndarray, HxWx3.
    image: np.ndarray
    width: int
    height: int
    codec: str
    #: True while the connection is still replaying its buffered GOP faster than
    #: real time. Consumers must not open tracks or compute velocity on these.
    warmup: bool = False
    #: Monotonic per (camera, segment).
    frame_index: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width
