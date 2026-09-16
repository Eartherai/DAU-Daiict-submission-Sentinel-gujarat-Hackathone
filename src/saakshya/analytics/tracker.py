"""Per-camera multi-object tracker.

Algorithm is ByteTrack's (Zhang et al., ECCV 2022): associate high-confidence
detections first, then recover tracks using the low-confidence detections that a
single threshold would have discarded. The implementation is ours because the
published implementations are frame-indexed and abandoned (upstream ByteTrack:
803 days without a push; BoT-SORT: 753), and because two requirements here are
not served by any of them:

* **PTS-driven motion.** Velocity is computed from presentation-timestamp deltas,
  never from frame counts or arrival time. The sandbox replays a buffered GOP on
  connect, so frame-indexed motion models compute impossible velocities on every
  reconnect.
* **Segment awareness.** A stream discontinuity ends every track cleanly rather
  than letting identity leak across a scene cut.

The output identity is **local to (camera, segment)**. It is deliberately not a
statewide vehicle identity, and nothing in this module implies otherwise —
cross-camera association is the graph layer's job, on evidence, with a human in
the loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from saakshya.common.ids import new_id

Box = tuple[float, float, float, float]      # xyxy, pixels


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def centre(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


@dataclass
class Detection:
    box: Box
    score: float
    label: str = "vehicle"
    #: Set when this detection is a plate rather than a vehicle body. Plates are
    #: tracked too: on cameras where the vehicle detector is weak, the plate is
    #: often the only reliable anchor.
    is_plate: bool = False
    #: "vehicle" | "plate" | "motion". Downstream attribute extraction needs to
    #: know whether a box is a vehicle body or a proxy for one.
    source: str = "vehicle"


@dataclass
class Track:
    track_id: str
    box: Box
    score: float
    label: str
    first_pts_s: float
    last_pts_s: float
    first_t_norm: datetime
    last_t_norm: datetime
    hits: int = 1
    age_since_update: int = 0
    #: pixels/second, from PTS deltas. None until two observations exist.
    velocity: tuple[float, float] | None = None
    history: list[tuple[float, Box]] = field(default_factory=list)
    confirmed: bool = False
    #: Provenance of the current box, and the best body-like box ever seen for
    #: this track (a motion or vehicle box beats a plate box for attributes).
    source: str = "vehicle"
    best_body_box: Box | None = None
    best_body_source: str | None = None

    def predict(self, pts_s: float) -> Box:
        """Constant-velocity prediction over the *actual* elapsed stream time."""
        if self.velocity is None:
            return self.box
        dt = pts_s - self.last_pts_s
        if dt <= 0 or dt > 5.0:      # stale or nonsensical; do not extrapolate
            return self.box
        vx, vy = self.velocity
        dx, dy = vx * dt, vy * dt
        x1, y1, x2, y2 = self.box
        return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)

    def update(self, det: Detection, pts_s: float, t_norm: datetime) -> None:
        if pts_s <= self.last_pts_s:
            # A decoder can deliver a reordered frame after a reconnect. It
            # must not move track state backwards; the ingest layer will
            # normally rotate the segment, but this guard keeps direct replay
            # and tests conservative too.
            return
        dt = pts_s - self.last_pts_s
        if dt > 1e-3:
            (px, py), (cx, cy) = centre(self.box), centre(det.box)
            v = ((cx - px) / dt, (cy - py) / dt)
            # Light smoothing; a single noisy frame should not dominate.
            self.velocity = v if self.velocity is None else (
                0.6 * v[0] + 0.4 * self.velocity[0],
                0.6 * v[1] + 0.4 * self.velocity[1],
            )
        self.box = det.box
        self.score = det.score
        self.source = det.source
        if not det.is_plate:
            self.label = det.label
        # Keep the largest non-plate box: it is the best available proxy for the
        # vehicle body, and attributes read off a plate crop are meaningless.
        if not det.is_plate:
            area = (det.box[2] - det.box[0]) * (det.box[3] - det.box[1])
            prev = self.best_body_box
            prev_area = ((prev[2] - prev[0]) * (prev[3] - prev[1])) if prev else 0.0
            if area > prev_area:
                self.best_body_box = det.box
                self.best_body_source = det.source
        self.last_pts_s = pts_s
        self.last_t_norm = t_norm
        self.hits += 1
        self.age_since_update = 0
        self.history.append((pts_s, det.box))
        if len(self.history) > 256:
            self.history.pop(0)

    @property
    def duration_s(self) -> float:
        return self.last_pts_s - self.first_pts_s

    @property
    def direction_deg(self) -> float | None:
        """Bearing of travel in image space. Used as a weak association signal
        and to reject transitions whose direction is incompatible."""
        if self.velocity is None:
            return None
        vx, vy = self.velocity
        if abs(vx) < 1e-6 and abs(vy) < 1e-6:
            return None
        return float(np.degrees(np.arctan2(-vy, vx)) % 360.0)


@dataclass
class TrackerConfig:
    high_thresh: float = 0.5
    low_thresh: float = 0.15
    iou_match: float = 0.25
    #: A track is published only after this many hits — one-frame detections are
    #: overwhelmingly noise, and a spurious observation is worse than a missed one.
    min_hits: int = 2
    #: Seconds of *stream time* a track may survive without an update. Chosen in
    #: PTS, not frames, so it behaves identically at 2 fps and 15 fps.
    max_age_s: float = 1.5


class ByteTracker:
    """One instance per (camera, segment)."""

    def __init__(self, camera_id: str, segment_id: str,
                 config: TrackerConfig | None = None) -> None:
        self.camera_id = camera_id
        self.segment_id = segment_id
        self.cfg = config or TrackerConfig()
        self.tracks: dict[str, Track] = {}
        self.finished: list[Track] = []
        self.total_created = 0

    # -- association -------------------------------------------------------- #
    def _match(self, tracks: list[Track], dets: list[Detection], pts_s: float
               ) -> tuple[list[tuple[Track, Detection]], list[Track], list[Detection]]:
        """Greedy IoU matching against motion-predicted boxes.

        Greedy rather than Hungarian: at the object counts a single CCTV camera
        produces (typically <20), greedy is within noise of optimal and is far
        easier to reason about when a match looks wrong at 2 a.m.
        """
        if not tracks or not dets:
            return [], list(tracks), list(dets)
        cost = np.zeros((len(tracks), len(dets)), dtype=np.float32)
        for i, t in enumerate(tracks):
            pred = t.predict(pts_s)
            for j, d in enumerate(dets):
                cost[i, j] = iou(pred, d.box)

        pairs: list[tuple[Track, Detection]] = []
        used_t: set[int] = set()
        used_d: set[int] = set()
        while True:
            i, j = np.unravel_index(int(np.argmax(cost)), cost.shape)
            if cost[i, j] < self.cfg.iou_match:
                break
            pairs.append((tracks[i], dets[j]))
            used_t.add(int(i))
            used_d.add(int(j))
            cost[i, :] = -1.0
            cost[:, j] = -1.0
        return (pairs,
                [t for i, t in enumerate(tracks) if i not in used_t],
                [d for j, d in enumerate(dets) if j not in used_d])

    def step(self, detections: list[Detection], pts_s: float,
             t_norm: datetime) -> list[Track]:
        """Advance one analysed frame. Returns currently confirmed tracks."""
        high = [d for d in detections if d.score >= self.cfg.high_thresh]
        low = [d for d in detections
               if self.cfg.low_thresh <= d.score < self.cfg.high_thresh]

        active = list(self.tracks.values())

        # Pass 1 — confident detections.
        pairs, unmatched_tracks, unmatched_high = self._match(active, high, pts_s)
        for t, d in pairs:
            t.update(d, pts_s, t_norm)

        # Pass 2 — ByteTrack's contribution: recover surviving tracks from the
        # low-confidence detections a single threshold would have thrown away.
        # On degraded cameras this is most of the signal.
        pairs2, still_unmatched, _ = self._match(unmatched_tracks, low, pts_s)
        for t, d in pairs2:
            t.update(d, pts_s, t_norm)

        # Age out.
        for t in still_unmatched:
            t.age_since_update += 1
            if pts_s - t.last_pts_s > self.cfg.max_age_s:
                self.finished.append(t)
                self.tracks.pop(t.track_id, None)

        # New tracks from unmatched confident detections only.
        for d in unmatched_high:
            tid = new_id("TR")
            self.tracks[tid] = Track(
                track_id=tid, box=d.box, score=d.score, label=d.label,
                first_pts_s=pts_s, last_pts_s=pts_s,
                first_t_norm=t_norm, last_t_norm=t_norm,
                history=[(pts_s, d.box)], source=d.source,
                best_body_box=None if d.is_plate else d.box,
                best_body_source=None if d.is_plate else d.source,
            )
            self.total_created += 1

        for t in self.tracks.values():
            if t.hits >= self.cfg.min_hits:
                t.confirmed = True
        return [t for t in self.tracks.values() if t.confirmed]

    def close_segment(self) -> list[Track]:
        """Called on SEGMENT_BREAK. Ends every track cleanly.

        Identity must not survive a scene cut: the sandbox loops its recordings,
        and carrying a track across the loop point silently fabricates continuity
        that did not happen.
        """
        out = list(self.tracks.values())
        self.finished.extend(out)
        self.tracks.clear()
        return out

    def stats(self) -> dict[str, int]:
        return {"active": len(self.tracks), "finished": len(self.finished),
                "created": self.total_created}


class TrackerPool:
    """Holds one tracker per camera, rotating on segment breaks."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.cfg = config or TrackerConfig()
        self._by_camera: dict[str, ByteTracker] = {}

    def get(self, camera_id: str, segment_id: str) -> ByteTracker:
        t = self._by_camera.get(camera_id)
        if t is None or t.segment_id != segment_id:
            if t is not None:
                t.close_segment()
            t = ByteTracker(camera_id, segment_id, self.cfg)
            self._by_camera[camera_id] = t
        return t

    def stats(self) -> dict[str, dict[str, int]]:
        return {c: t.stats() for c, t in self._by_camera.items()}
