"""A bounded window of recent frames, so an alert can seal what was seen.

The government grid is live and not seekable: by the time an alert fires the
moment is gone. Every evidence record so far is METADATA_ONLY for that reason.
This holds a short window so the sightings that matter can carry imagery —
without retaining government video at large, and without becoming the next
memory incident.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from saakshya.evidence.rolling import RollingBuffer, RollingEvidence


def frame(seed: int, w: int = 320, h: int = 240) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def at(i: int) -> datetime:
    return datetime(2026, 6, 14, 8, 0, 0, tzinfo=UTC) + timedelta(seconds=i)


# ---- the buffer ------------------------------------------------------------ #
def test_it_holds_recent_frames():
    b = RollingBuffer("cam01")
    for i in range(5):
        b.add(frame(i), pts_s=float(i), t_norm=at(i))
    assert len(b) == 5
    assert [h.pts_s for h in b.snapshot(3)] == [2.0, 3.0, 4.0]


def test_it_evicts_by_bytes_not_by_count():
    """Frame size varies by an order of magnitude across this estate — a random
    320x240 frame encodes to ~75 KB, a flat one to ~2.5 KB — so a count-based
    bound would be a memory bound in name only."""
    budget = 400_000
    b = RollingBuffer("cam01", budget_bytes=budget)
    for i in range(40):
        b.add(frame(i), pts_s=float(i), t_norm=at(i))
    assert b.evicted > 0, "nothing was evicted; the budget was never reached"
    assert len(b) < 40
    # Budget plus at most one frame: the newest is always kept.
    assert b.bytes_held <= budget + 100_000
    assert b.bytes_held > budget * 0.5, "evicting far below budget wastes it"


def test_the_newest_frame_survives_a_tiny_budget():
    """A budget smaller than one frame must still leave the latest one: an
    event arriving now needs the picture from now."""
    b = RollingBuffer("cam01", budget_bytes=1)
    for i in range(4):
        b.add(frame(i), pts_s=float(i), t_norm=at(i))
    assert len(b) == 1
    assert b.snapshot(1)[0].pts_s == 3.0


def test_a_hash_covers_the_retained_bytes():
    b = RollingBuffer("cam01")
    held = b.add(frame(1), pts_s=1.0, t_norm=at(1))
    import hashlib
    assert held.sha256 == hashlib.sha256(held.data).hexdigest()
    assert len(held.sha256) == 64


# ---- capture around an event ------------------------------------------------ #
@pytest.fixture
def rolling(tmp_path):
    return RollingEvidence(tmp_path / "rolling", pre_frames=3, post_frames=2)


def test_nothing_reaches_disk_until_an_event(rolling, tmp_path):
    for i in range(10):
        rolling.observe("cam01", frame(i), float(i), at(i))
    assert not (tmp_path / "rolling").exists(), (
        "a camera that never triggers must never write a byte of imagery")


def test_a_capture_carries_frames_from_before_the_event(rolling):
    for i in range(6):
        rolling.observe("cam01", frame(i), float(i), at(i))
    cap = rolling.on_event("cam01", "OB1", "watchlist match")
    assert [h.pts_s for h in cap.pre] == [3.0, 4.0, 5.0]


def test_post_event_frames_accumulate_as_they_arrive(rolling):
    for i in range(4):
        rolling.observe("cam01", frame(i), float(i), at(i))
    cap = rolling.on_event("cam01", "OB1", "watchlist match")
    assert not cap.complete
    rolling.observe("cam01", frame(90), 90.0, at(90))
    rolling.observe("cam01", frame(91), 91.0, at(91))
    assert cap.complete
    assert [h.pts_s for h in cap.post] == [90.0, 91.0]


def test_another_cameras_frames_do_not_enter_the_capture(rolling):
    for i in range(4):
        rolling.observe("cam01", frame(i), float(i), at(i))
    cap = rolling.on_event("cam01", "OB1", "watchlist match")
    rolling.observe("cam02", frame(50), 50.0, at(50))
    assert not cap.post, "a capture must not absorb a different camera's frames"


def test_closing_writes_hashed_frames_and_a_manifest(rolling, tmp_path):
    for i in range(5):
        rolling.observe("cam01", frame(i), float(i), at(i))
    cap = rolling.on_event("cam01", "OB1", "watchlist match")
    rolling.observe("cam01", frame(90), 90.0, at(90))
    rolling.observe("cam01", frame(91), 91.0, at(91))
    man = rolling.close(cap)

    assert man is not None
    assert man["pre_frames"] == 3
    assert man["post_frames"] == 2
    assert len(man["frames"]) == 5
    assert {f["phase"] for f in man["frames"]} == {"pre", "post"}

    import hashlib
    from pathlib import Path
    for entry in man["frames"]:
        path = Path(man["directory"]) / entry["file"]
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def test_the_manifest_states_that_frames_were_re_encoded(rolling):
    rolling.observe("cam01", frame(1), 1.0, at(1))
    man = rolling.close(rolling.on_event("cam01", "OB1", "match"))
    assert "re-encoded" in man["caveat"]
    assert "not the original compressed bitstream" in man["caveat"]
    assert "not seekable" in man["caveat"]


def test_an_event_with_no_buffered_frames_returns_nothing(rolling):
    """Inventing an empty record would be worse than saying there is none."""
    assert rolling.close(rolling.on_event("cam99", "OB1", "match")) is None


def test_memory_is_bounded_across_many_cameras(tmp_path):
    """Thirty cameras of unbounded buffering is the next outage.

    Held to the documented contract — budget plus at most one frame per camera —
    rather than to the budget alone, because the buffer deliberately keeps the
    newest frame however large it is.
    """
    budget, cameras, largest_frame = 300_000, 30, 100_000
    r = RollingEvidence(tmp_path / "r", budget_bytes=budget)
    for cam in range(cameras):
        for i in range(20):
            r.observe(f"cam{cam:02d}", frame(i), float(i), at(i))
    s = r.stats()
    assert s["cameras"] == cameras
    assert s["evicted"] > 0, "nothing was evicted; the budget was never reached"
    assert s["bytes_held"] <= cameras * (budget + largest_frame)
    # And an unbounded buffer would have held all 600 frames.
    assert s["frames_held"] < cameras * 20


def test_the_documented_bound_is_budget_plus_one_frame():
    """Stated in the docstring, so it is stated in a test as well."""
    b = RollingBuffer("cam01", budget_bytes=1)
    for i in range(5):
        b.add(frame(i), pts_s=float(i), t_norm=at(i))
    assert len(b) == 1
    assert b.bytes_held > 1, (
        "the bound is budget plus one frame; a caller sizing memory for a "
        "large estate must reckon on the frame")


def test_stats_report_what_is_held(rolling):
    for i in range(4):
        rolling.observe("cam01", frame(i), float(i), at(i))
    s = rolling.stats()
    assert s["frames_held"] == 4
    assert s["bytes_held"] > 0
    assert s["captures_retained"] == 0
