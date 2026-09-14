"""Tracker: PTS-driven motion, segment isolation, low-confidence recovery."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saakshya.analytics.tracker import ByteTracker, Detection, TrackerConfig, TrackerPool, iou

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def t_at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def moving(x: float, y: float = 300.0, w: float = 120.0, h: float = 80.0):
    return (x, y, x + w, y + h)


def test_iou_basics():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert 0.1 < iou((0, 0, 10, 10), (5, 0, 15, 10)) < 0.5


def test_single_vehicle_keeps_one_id():
    tr = ByteTracker("C-014", "SEG1")
    ids = set()
    for i in range(10):
        pts = i * 0.25
        tracks = tr.step([Detection(moving(100 + i * 30), 0.9)], pts, t_at(pts))
        ids.update(t.track_id for t in tracks)
    assert len(ids) == 1, f"expected one identity, got {ids}"


def test_two_vehicles_get_distinct_ids():
    """The multi-vehicle failure that per-camera plate voting produced must not
    recur at the tracking layer."""
    tr = ByteTracker("C-014", "SEG1")
    ids = set()
    for i in range(10):
        pts = i * 0.25
        dets = [Detection(moving(100 + i * 30, y=300), 0.9),
                Detection(moving(900 - i * 30, y=460), 0.9)]
        ids.update(t.track_id for t in tr.step(dets, pts, t_at(pts)))
    assert len(ids) == 2, f"expected two identities, got {len(ids)}"


def test_velocity_uses_pts_not_frame_count():
    """The core rule. Two runs with identical boxes but different PTS spacing
    must produce different velocities — a frame-indexed tracker gives the same."""
    def run(step_s: float) -> tuple[float, float]:
        tr = ByteTracker("C", "S")
        for i in range(5):
            pts = i * step_s
            tr.step([Detection(moving(100 + i * 50), 0.9)], pts, t_at(pts))
        return next(iter(tr.tracks.values())).velocity

    fast = run(0.1)     # 50 px per 0.1 s -> ~500 px/s
    slow = run(1.0)     # 50 px per 1.0 s -> ~50 px/s
    assert fast[0] > 4 * slow[0], f"PTS ignored: {fast=} {slow=}"
    assert 400 < fast[0] < 600
    assert 40 < slow[0] < 60


def test_gop_burst_does_not_produce_impossible_velocity():
    """Frames arriving faster than real time must not inflate velocity, because
    velocity comes from PTS. This is the documented sandbox failure mode."""
    tr = ByteTracker("C", "S")
    for i in range(6):
        pts = i * 0.5                      # stream time advances normally
        tr.step([Detection(moving(100 + i * 40), 0.9)], pts, t_at(pts))
    v = next(iter(tr.tracks.values())).velocity
    assert 60 < v[0] < 100, f"velocity should reflect PTS, got {v}"


def test_low_confidence_recovers_a_track():
    """ByteTrack's contribution: a track survives a run of weak detections that a
    single threshold would discard. This is most of the signal on bad cameras."""
    tr = ByteTracker("C", "S", TrackerConfig(high_thresh=0.5, low_thresh=0.15))
    for i in range(3):
        tr.step([Detection(moving(100 + i * 30), 0.9)], i * 0.2, t_at(i * 0.2))
    tid = next(iter(tr.tracks))
    for i in range(3, 7):
        tr.step([Detection(moving(100 + i * 30), 0.25)], i * 0.2, t_at(i * 0.2))
    assert tid in tr.tracks, "track lost despite recoverable low-confidence detections"
    assert tr.tracks[tid].hits >= 6


def test_track_ages_out_on_pts_not_frames():
    tr = ByteTracker("C", "S", TrackerConfig(max_age_s=1.0))
    tr.step([Detection(moving(100), 0.9)], 0.0, t_at(0))
    tr.step([Detection(moving(130), 0.9)], 0.2, t_at(0.2))
    assert len(tr.tracks) == 1
    tr.step([], 2.0, t_at(2.0))            # 1.8 s of stream time with nothing
    assert len(tr.tracks) == 0
    assert len(tr.finished) == 1


def test_segment_break_ends_tracks():
    """Identity must not survive a scene cut — the corpus loops, and carrying a
    track across the loop fabricates continuity."""
    pool = TrackerPool()
    a = pool.get("C-014", "SEG1")
    for i in range(4):
        a.step([Detection(moving(100 + i * 30), 0.9)], i * 0.2, t_at(i * 0.2))
    first_ids = set(a.tracks)
    assert first_ids

    b = pool.get("C-014", "SEG2")          # discontinuity
    assert b is not a
    assert not b.tracks
    b.step([Detection(moving(100), 0.9)], 0.0, t_at(0))
    assert set(b.tracks).isdisjoint(first_ids)


def test_direction_is_reported():
    tr = ByteTracker("C", "S")
    for i in range(5):
        tr.step([Detection(moving(100 + i * 50), 0.9)], i * 0.2, t_at(i * 0.2))
    d = next(iter(tr.tracks.values())).direction_deg
    assert d is not None and (d < 20 or d > 340), f"left-to-right should be ~0 deg, got {d}"
