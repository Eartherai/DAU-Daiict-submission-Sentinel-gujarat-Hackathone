"""A bounded rolling buffer, so live evidence can include the frames.

Government feeds are live and not seekable: by the time anyone knows a frame
mattered it is gone, which is why every evidence record sealed from the live
grid so far has been METADATA_ONLY — truthful, and much weaker than necessary.

The properties that matter are the bounds. A buffer that can grow without limit
in a process already holding thirty decoders is not a feature, it is the next
outage.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from saakshya.evidence.buffer import RollingBuffer, encode

T0 = datetime(2026, 6, 14, 8, 1, tzinfo=UTC)


def frame(seed: int, h: int = 180, w: int = 320) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 255, (h, w, 3), dtype=np.uint8)


def fill(buf: RollingBuffer, camera: str, n: int, *, step: float = 0.5) -> None:
    for i in range(n):
        buf.offer(camera, "s1", i * step, T0 + timedelta(seconds=i * step), frame(i))


def test_a_camera_never_holds_more_than_its_cap():
    buf = RollingBuffer(frames_per_camera=8)
    fill(buf, "cam01", 40)
    assert buf.stats()["per_camera"]["cam01"] == 8


def test_the_byte_budget_holds_across_cameras():
    """Adding cameras must not grow memory without limit."""
    buf = RollingBuffer(frames_per_camera=50, budget_bytes=120_000)
    for cam in ("cam01", "cam02", "cam03", "cam04"):
        fill(buf, cam, 25)
    s = buf.stats()
    assert s["bytes"] <= s["budget_bytes"]
    assert s["dropped_for_budget"] > 0, "eviction never ran; the test is not testing"


def scene(h: int = 1080, w: int = 1920) -> np.ndarray:
    """A frame that compresses like a photograph rather than like noise.

    Random pixels are the worst case JPEG can be handed and nothing like a
    street scene: an early version of the test below used them and measured a
    compression ratio no real camera would ever produce.
    """
    y, x = np.mgrid[0:h, 0:w]
    road = (120 + 60 * np.sin(x / 240.0) + 30 * (y / h)).astype(np.uint8)
    img = np.dstack([road, road, road]).astype(np.uint8)
    img[h // 3: h // 3 + 90, w // 4: w // 4 + 220] = (40, 40, 160)     # a vehicle
    img[h // 2: h // 2 + 70, 2 * w // 3: 2 * w // 3 + 180] = (30, 120, 40)
    return img


def test_frames_are_encoded_not_held_raw():
    """A 1080p BGR frame is ~6 MB raw and a fraction of that encoded. Held raw,
    the buffer would be the largest thing in a process that already carries
    thirty decoders."""
    img = scene()
    assert img.nbytes > 6_000_000
    assert len(encode(img)) < img.nbytes // 10


def test_a_window_is_selected_by_pts_not_arrival():
    """A stream that reconnected delivers frames out of order; selecting on
    arrival would produce a clip whose frames are not contiguous in the video's
    own time."""
    buf = RollingBuffer(frames_per_camera=16)
    for pts in (3.0, 1.0, 2.0, 5.0, 4.0):          # deliberately out of order
        buf.offer("cam01", "s1", pts, T0, frame(int(pts)))
    got = [f.pts_s for f in buf.window("cam01", at_pts_s=3.0, pre_s=1.0, post_s=1.0)]
    assert got == [2.0, 3.0, 4.0]


def test_a_window_covers_before_and_after_the_moment():
    buf = RollingBuffer(frames_per_camera=32)
    fill(buf, "cam01", 20)
    w = buf.window("cam01", at_pts_s=5.0, pre_s=2.0, post_s=2.0)
    assert w[0].pts_s <= 3.0 and w[-1].pts_s >= 7.0


def test_nearest_refuses_a_frame_that_is_too_far_away():
    """Attaching an image from six seconds away is worse than attaching none."""
    buf = RollingBuffer(frames_per_camera=8)
    fill(buf, "cam01", 8)
    assert buf.nearest("cam01", 3.4, tolerance_s=0.5) is not None
    assert buf.nearest("cam01", 90.0, tolerance_s=1.5) is None


def test_an_unknown_camera_yields_nothing_rather_than_raising():
    buf = RollingBuffer()
    assert buf.window("cam99", at_pts_s=1.0) == []
    assert buf.nearest("cam99", 1.0) is None


def test_a_buffered_frame_decodes_back_to_an_image():
    buf = RollingBuffer(frames_per_camera=4)
    buf.offer("cam01", "s1", 1.0, T0, frame(7, 240, 320))
    got = buf.nearest("cam01", 1.0)
    assert got is not None
    arr = got.to_array()
    assert arr.shape == (240, 320, 3)
    assert arr.dtype == np.uint8


@pytest.mark.parametrize("workers", [4])
def test_concurrent_writers_do_not_corrupt_the_buffer(workers):
    """Camera workers write from their own threads while an alert handler reads."""
    import threading

    buf = RollingBuffer(frames_per_camera=12, budget_bytes=4_000_000)
    errors: list[BaseException] = []

    def writer(cam: str):
        try:
            fill(buf, cam, 30)
        except BaseException as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(60):
                buf.window("cam0", at_pts_s=5.0)
                buf.stats()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(f"cam{i}",)) for i in range(workers)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    s = buf.stats()
    assert s["bytes"] <= s["budget_bytes"]
    assert all(n <= 12 for n in s["per_camera"].values())
