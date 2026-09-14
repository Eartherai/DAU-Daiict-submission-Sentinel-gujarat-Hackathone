"""Scene-discontinuity detection.

Why this exists
---------------
The obvious way to detect a stream discontinuity is a PTS regression, and that
is implemented in the stream worker. Measuring the local grid replica showed it
is **not sufficient**: a publisher looping a file with ``-stream_loop -1``
advances PTS monotonically across the loop point (observed 77s of PTS on a 60s
clip, with zero regressions), so the scene cuts while the clock runs on.

The organiser's Integrator's Guide says the grid's feeds loop and that "at the
loop point the scene cuts abruptly, similar to a camera reboot", and warns that
long-lived state — background models, re-identification galleries, track ids —
must recover from a hard cut. If we relied on PTS alone we would carry track
state straight across that cut and silently corrupt cross-camera association.

So discontinuity is detected on two independent signals:

    PTS regression / large forward jump      (timing evidence)
    Block-level scene change                 (pixel evidence)

Method
------
Mean-absolute-difference over the whole frame is the naive choice and it is
wrong here: a large vehicle entering a small frame produces a big mean delta and
would be misread as a cut. Instead the frame is reduced to a coarse block grid
and we count the *fraction of blocks* that changed materially. A vehicle changes
a local cluster of blocks; a scene cut changes most of them. That separation is
what makes the detector safe to run on a busy junction camera.

The threshold adapts per camera: cameras differ enormously in noise (the
Panchayat camera in the corpus carries heavy sensor noise by design), so a fixed
threshold would either miss cuts on noisy cameras or false-fire on them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Frame is reduced to at most this many blocks per axis before comparison.
GRID = 16
#: A block counts as "changed" when its mean intensity moves by more than this
#: many 8-bit levels above the camera's own noise floor.
BLOCK_DELTA_FLOOR = 18.0
#: Fraction of blocks that must change simultaneously to call it a cut.
CUT_BLOCK_FRACTION = 0.55
#: Never fire twice within this many frames — a cut is one event, not a burst.
REFRACTORY_FRAMES = 8


@dataclass
class SceneCutDetector:
    """Per-camera detector. Cheap: one 16x16 reduction per frame."""

    camera_id: str
    grid: int = GRID
    block_delta_floor: float = BLOCK_DELTA_FLOOR
    cut_fraction: float = CUT_BLOCK_FRACTION
    refractory: int = REFRACTORY_FRAMES

    _prev: np.ndarray | None = field(default=None, repr=False)
    _noise: float = field(default=0.0, repr=False)
    _noise_n: int = field(default=0, repr=False)
    _since_cut: int = field(default=10_000, repr=False)
    cuts: int = field(default=0)
    last_fraction: float = field(default=0.0)

    def _reduce(self, image: np.ndarray) -> np.ndarray:
        """Downsample to a (grid x grid) float32 luma grid."""
        # BGR -> luma without pulling in cv2; the weights are ITU-R BT.601.
        if image.ndim == 3:
            luma = (
                image[:, :, 0].astype(np.float32) * 0.114
                + image[:, :, 1].astype(np.float32) * 0.587
                + image[:, :, 2].astype(np.float32) * 0.299
            )
        else:
            luma = image.astype(np.float32)
        h, w = luma.shape
        gh, gw = min(self.grid, h), min(self.grid, w)
        # Trim to a multiple of the grid, then block-mean via reshape.
        hh, ww = (h // gh) * gh, (w // gw) * gw
        if hh == 0 or ww == 0:
            return luma.reshape(1, 1)
        return luma[:hh, :ww].reshape(gh, hh // gh, gw, ww // gw).mean(axis=(1, 3))

    def update(self, image: np.ndarray) -> bool:
        """Feed a frame. Returns True exactly once per detected scene cut."""
        cur = self._reduce(image)
        self._since_cut += 1

        if self._prev is None or self._prev.shape != cur.shape:
            # First frame, or the resolution changed mid-stream (which is itself
            # a discontinuity the guide warns about, but the stream worker
            # handles that separately — here we just re-baseline).
            self._prev = cur
            return False

        delta = np.abs(cur - self._prev)
        self._prev = cur

        # Track this camera's own noise floor from the *typical* block delta, so
        # a grainy low-light camera does not permanently look like it is cutting.
        med = float(np.median(delta))
        self._noise_n += 1
        alpha = 1.0 / min(self._noise_n, 240)
        self._noise = (1 - alpha) * self._noise + alpha * med

        threshold = self.block_delta_floor + 2.5 * self._noise
        fraction = float((delta > threshold).mean())
        self.last_fraction = fraction

        if fraction >= self.cut_fraction and self._since_cut >= self.refractory:
            self._since_cut = 0
            self.cuts += 1
            return True
        return False

    def reset(self) -> None:
        self._prev = None
        self._since_cut = 10_000

    @property
    def noise_floor(self) -> float:
        return round(self._noise, 3)
