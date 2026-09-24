"""Plates are searched at full resolution on high-resolution frames.

The plate detector's input is 640 px, so a 2560 px frame reached it at a
quarter scale and a 100 px plate arrived as 25 px: on 40 frames of the Mumbai
signal queue the old path found no valid plate at all. These tests pin the
geometry of the tiled pass with a fake detector - boxes found in a tile land
at the right place in the frame, a plate seen twice is kept once, and a frame
below the threshold is not tiled.
"""
from __future__ import annotations

import numpy as np

from saakshya.analytics.anpr import AnprConfig, AnprEngine
from saakshya.runtime.backend import Detection, OcrResult


class FakePlates:
    """Answers with one plate at a fixed frame position, wherever it is visible."""

    name = "fake"

    def __init__(self, plate_xy: tuple[int, int], frame_w: int, frame_h: int):
        self.px, self.py = plate_xy
        self.fw, self.fh = frame_w, frame_h
        self.calls: list[tuple[int, int]] = []

    def detect(self, image: np.ndarray) -> list[Detection]:
        h, w = image.shape[:2]
        self.calls.append((w, h))
        if (w, h) != (self.fw, self.fh) and w != 1280:
            # A tile: recover its origin from the marker painted into it.
            ys, xs = np.nonzero(image[:, :, 0] == 250)
            if not len(xs):
                return []
            x, y = int(xs.min()), int(ys.min())
            return [Detection(box=(x, y, x + 100, y + 25), score=0.9, label="plate")]
        return []                       # the plate is too small at 1280 px

    def ocr(self, crop: np.ndarray) -> OcrResult:
        return OcrResult(text="MH47AT1525", confidence=0.93)


def frame_with_plate(w: int, h: int, x: int, y: int) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[y:y + 25, x:x + 100, 0] = 250
    return img


def test_a_small_plate_is_found_in_a_tile_and_mapped_back() -> None:
    img = frame_with_plate(2560, 1440, 1700, 1100)
    fake = FakePlates((1700, 1100), 2560, 1440)
    eng = AnprEngine(AnprConfig(), backend=fake)
    reads = eng.read_frame(img, 0.0)
    assert len(reads) == 1, "a plate visible in two overlapping tiles is one plate"
    x1, y1, x2, y2 = reads[0].box
    assert abs(x1 - 1700) <= 8 and abs(y1 - 1100) <= 8 and x2 > x1 and y2 > y1
    assert reads[0].text == "MH47AT1525"


def test_a_frame_below_the_threshold_is_not_tiled() -> None:
    img = frame_with_plate(1280, 720, 600, 500)
    fake = FakePlates((600, 500), 1280, 720)
    AnprEngine(AnprConfig(), backend=fake).read_frame(img, 0.0)
    assert fake.calls == [(1280, 720)]
