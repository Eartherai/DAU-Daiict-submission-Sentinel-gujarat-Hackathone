"""Tier-0 presence detection by background modelling.

Why this exists, when a detector is already available:

The research review established that a COCO-trained detector loses accuracy
moving to an unseen camera network, and measurement confirmed it here — on the
degraded Panchayat camera the detector returns almost nothing usable. If
tracking depends on a learned detector, then **the cameras that most need the
appearance fallback are exactly the cameras that produce no observations at
all**, and the unreadable-plate case becomes impossible.

Background subtraction has the opposite failure profile. It knows nothing about
vehicles, so it cannot be wrong about vehicles; it only asserts *something moved
here*, which on a fixed CCTV camera is close to always true when something did.
It costs no model, no weights, no licence and no domain adaptation.

So the tiers compose as designed:

    T0  motion            always on, model-free, works on any camera
    T1  + detector        adds class and refines boxes where the model is usable
    T2  + plate/embedding on cameras measured capable of supporting it

The tracker consumes the union. On a good camera the detector dominates; on a
degraded one motion carries it. That is the point.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class MotionConfig:
    #: Working resolution for the background model. Small is the point: it
    #: suppresses sensor noise for free and keeps the whole stage sub-millisecond.
    work_width: int = 160
    #: Exponential background update rate. Slow enough that a vehicle waiting at
    #: a signal is not absorbed into the background within a typical dwell.
    alpha: float = 0.02
    #: Foreground threshold in 8-bit levels, above the measured noise floor.
    delta_floor: float = 14.0
    noise_mult: float = 3.0
    #: Minimum blob area as a fraction of the working frame.
    min_area_frac: float = 0.0012
    max_area_frac: float = 0.60
    #: Frames of background accumulation before any detection is emitted.
    warmup_frames: int = 8
    #: Plausible vehicle aspect (w/h) in image space; filters poles and shadows.
    min_aspect: float = 0.6
    max_aspect: float = 6.0


class MotionDetector:
    """One per camera. Reset on segment break — the background is scene-specific."""

    def __init__(self, config: MotionConfig | None = None) -> None:
        self.cfg = config or MotionConfig()
        self._bg: np.ndarray | None = None
        self._noise: float = 0.0
        self._n: int = 0
        self._scale: float = 1.0

    def reset(self) -> None:
        self._bg = None
        self._n = 0
        self._noise = 0.0

    def _work(self, image: np.ndarray) -> np.ndarray:
        """Downsample, keeping colour channels.

        Colour, not luma. A luma-only background model is blind to any vehicle
        whose brightness matches the road, and that is not a rare case: the red
        car in our corpus has luma 58.8 against road luma 65.3, so it was almost
        invisible and only its bottom edge triggered. A red car on grey tarmac is
        an entirely ordinary sight on an Indian road.
        """
        w = image.shape[1]
        self._scale = min(1.0, self.cfg.work_width / float(w))
        step = max(1, round(1.0 / self._scale))
        small = image[::step, ::step]
        self._step = step
        if small.ndim == 2:
            small = small[:, :, None]
        return small.astype(np.float32)

    @staticmethod
    def _components(mask: np.ndarray, min_px: int) -> list[tuple[int, int, int, int]]:
        """Connected components by row-run merging.

        Hand-rolled rather than pulling in cv2: this module must stay clear of
        the PyAV/OpenCV native-library conflict, and at 160px working width the
        cost is negligible.
        """
        h, w = mask.shape
        labels = np.zeros((h, w), dtype=np.int32)
        nxt = 1
        parent: dict[int, int] = {}

        def find(x: int) -> int:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        for y in range(h):
            row = mask[y]
            for x in range(w):
                if not row[x]:
                    continue
                left = labels[y, x - 1] if x > 0 else 0
                up = labels[y - 1, x] if y > 0 else 0
                if left and up:
                    labels[y, x] = min(left, up)
                    union(left, up)
                elif left:
                    labels[y, x] = left
                elif up:
                    labels[y, x] = up
                else:
                    labels[y, x] = nxt
                    parent[nxt] = nxt
                    nxt += 1

        boxes: dict[int, list[int]] = {}
        ys, xs = np.nonzero(labels)
        for y, x in zip(ys, xs, strict=False):
            r = find(int(labels[y, x]))
            b = boxes.get(r)
            if b is None:
                boxes[r] = [x, y, x, y, 1]
            else:
                b[0] = min(b[0], x)
                b[1] = min(b[1], y)
                b[2] = max(b[2], x)
                b[3] = max(b[3], y)
                b[4] += 1
        return [(b[0], b[1], b[2], b[3]) for b in boxes.values() if b[4] >= min_px]

    @staticmethod
    def _merge_nearby(boxes: list[tuple[int, int, int, int]], gap: int = 1
                      ) -> list[tuple[int, int, int, int]]:
        """Union boxes that are close enough to be one object.

        A low-contrast vehicle produces several disconnected foreground patches
        (bonnet, roof, shadow gap). Treating each as its own object yields tiny
        boxes and, downstream, nonsense attributes. Merging is done on the
        working grid where `gap` of 3 cells is a few percent of frame width.
        """
        if len(boxes) < 2:
            return boxes
        merged = list(boxes)
        changed = True
        while changed:
            changed = False
            out: list[tuple[int, int, int, int]] = []
            while merged:
                a = merged.pop()
                hit = None
                for i, b in enumerate(out):
                    if (a[0] <= b[2] + gap and b[0] <= a[2] + gap
                            and a[1] <= b[3] + gap and b[1] <= a[3] + gap):
                        hit = i
                        break
                if hit is None:
                    out.append(a)
                else:
                    b = out[hit]
                    out[hit] = (min(a[0], b[0]), min(a[1], b[1]),
                                max(a[2], b[2]), max(a[3], b[3]))
                    changed = True
            merged = out
        return merged

    def detect(self, image: np.ndarray) -> list[tuple[tuple[float, float, float, float], float]]:
        """Return [(box_xyxy_full_res, score)]. Score is normalised blob energy."""
        g = self._work(image)
        if self._bg is None or self._bg.shape != g.shape:
            self._bg = g.copy()
            self._n = 1
            return []

        # Max absolute difference across channels: a change in any channel is a
        # change, even when overall brightness is unchanged.
        diff = np.abs(g - self._bg).max(axis=2)
        med = float(np.median(diff))
        a = 1.0 / min(self._n, 200)
        self._noise = (1 - a) * self._noise + a * med
        self._n += 1

        # Update the background *before* thresholding, so a stationary object is
        # absorbed gradually rather than flickering in and out of foreground.
        self._bg = (1 - self.cfg.alpha) * self._bg + self.cfg.alpha * g

        if self._n < self.cfg.warmup_frames:
            return []


        thresh = self.cfg.delta_floor + self.cfg.noise_mult * self._noise
        mask = diff > thresh
        if not mask.any():
            return []

        h, w = mask.shape
        total = h * w
        min_px = max(6, int(total * self.cfg.min_area_frac))
        max_px = int(total * self.cfg.max_area_frac)

        comps = self._merge_nearby(self._components(mask, min_px))
        out = []
        for x1, y1, x2, y2 in comps:
            bw, bh = (x2 - x1 + 1), (y2 - y1 + 1)
            area = bw * bh
            if area > max_px:
                continue
            aspect = bw / max(1, bh)
            if not (self.cfg.min_aspect <= aspect <= self.cfg.max_aspect):
                continue
            energy = float(diff[y1:y2 + 1, x1:x2 + 1].mean())
            score = float(np.clip(energy / (thresh * 3.0), 0.0, 1.0))
            s = self._step
            out.append((((x1 * s), (y1 * s), ((x2 + 1) * s), ((y2 + 1) * s)), score))
        out.sort(key=lambda t: -t[1])
        return out[:12]
