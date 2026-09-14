"""Vehicle attributes: colour classification, size class, agreement scoring."""
from __future__ import annotations

import numpy as np
import pytest

from saakshya.analytics.attributes import (
    classify_colour,
    classify_size,
    colour_agreement,
    extract,
    size_agreement,
)


def solid(bgr: tuple[int, int, int], h: int = 120, w: int = 200) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bgr
    return img


@pytest.mark.parametrize("bgr,expected", [
    ((235, 235, 235), "white"),
    ((128, 128, 128), "grey"),
    ((20, 20, 20), "black"),
    ((40, 40, 190), "red"),
    ((60, 150, 60), "green"),
    ((180, 70, 50), "blue"),
])
def test_colour_classification(bgr, expected):
    name, conf = classify_colour(np.array(bgr, dtype=np.float32))
    assert name == expected, f"{bgr} -> {name}, expected {expected}"
    assert 0.0 <= conf <= 1.0


def test_near_boundary_colour_reports_low_confidence():
    """A washed-out body must report weak evidence, not an arbitrary label."""
    _, strong = classify_colour(np.array([40, 40, 200], dtype=np.float32))
    _, weak = classify_colour(np.array([120, 125, 145], dtype=np.float32))
    assert weak < strong


def test_extract_on_a_synthetic_vehicle():
    img = np.full((360, 640, 3), 60, dtype=np.uint8)
    img[150:260, 200:420] = (225, 228, 232)      # pale body
    img[160:195, 240:340] = (30, 34, 40)         # dark windscreen
    a = extract(img, (200, 150, 420, 260))
    assert a.colour == "white", f"got {a.colour}"
    assert a.size_class in {"car", "van"}


def test_dark_regions_do_not_drag_colour_to_black():
    """Windscreen and tyres must not dominate the body colour."""
    img = np.full((360, 640, 3), 50, dtype=np.uint8)
    img[150:260, 200:420] = (200, 60, 60)        # blue body
    img[150:200, 200:420] = (5, 5, 5)            # large dark glass area
    a = extract(img, (200, 150, 420, 260))
    assert a.colour == "blue", f"dark pixels leaked into body colour: {a.colour}"


@pytest.mark.parametrize("box,frame,expected", [
    ((0, 0, 40, 60), (720, 1280), "motorcycle"),
    ((0, 0, 220, 130), (720, 1280), "car"),
    ((0, 0, 420, 130), (720, 1280), "truck_bus"),
])
def test_size_class(box, frame, expected):
    cls, _ = classify_size(box, frame)
    assert cls == expected, f"{box} -> {cls}, expected {expected}"


def test_colour_agreement_allows_expected_confusion():
    """White reading as grey on a dark camera is exactly the case the appearance
    path exists to recover — it must not be scored as a mismatch."""
    assert colour_agreement("white", "white") == 1.0
    assert colour_agreement("white", "grey") == 0.5
    assert colour_agreement("white", "red") == 0.0
    assert colour_agreement("white", None) == 0.0


def test_size_agreement_is_ordinal():
    assert size_agreement("car", "car") == 1.0
    assert size_agreement("car", "van") == 0.5
    assert size_agreement("car", "truck_bus") == 0.0


def test_tiny_box_declines_rather_than_guessing():
    img = np.full((100, 100, 3), 128, dtype=np.uint8)
    a = extract(img, (10, 10, 12, 12))
    assert a.colour is None
    assert a.reasons


# --------------------------------------------------------------------------- #
# Geometric plausibility (CR-005)
# --------------------------------------------------------------------------- #
def test_a_box_spanning_the_frame_is_not_a_vehicle():
    """Motion segmentation occasionally merges several vehicles and the road
    between them into one blob.

    That blob is well lit and confidently coloured, so the lit-fraction and
    colour-confidence gates from CR-003 pass it happily — they ask "is this crop
    readable", and nothing was asking "is this crop a car". Measured symptom on
    the denser corpus: a yellow car at C-021 published as WHITE at 0.73
    confidence from a box spanning the full 1280 px frame width.
    """
    from saakshya.analytics.pipeline import _is_plausible_vehicle_box

    shape = (720, 1280, 3)
    assert not _is_plausible_vehicle_box((0, 448, 1280, 720), shape), (
        "a box spanning the entire frame width was accepted as a vehicle")
    assert not _is_plausible_vehicle_box((0, 0, 1280, 720), shape)
    # A wide, shallow blob is a queue of traffic, not one vehicle.
    assert not _is_plausible_vehicle_box((100, 600, 1000, 700), shape)


def test_the_gate_is_generous_to_real_vehicles():
    """Deliberately loose: rejecting a legitimate close-range observation is a
    worse failure than tolerating an occasional merge, because the close ones
    are the highest-quality views the system gets."""
    from saakshya.analytics.pipeline import _is_plausible_vehicle_box

    shape = (720, 1280, 3)
    assert _is_plausible_vehicle_box((1105, 572, 1280, 716), shape)   # small, distant
    assert _is_plausible_vehicle_box((300, 200, 900, 640), shape)     # large, close
    assert _is_plausible_vehicle_box((100, 100, 800, 600), shape)     # very close
    assert _is_plausible_vehicle_box((600, 300, 700, 400), shape)     # tiny


# --------------------------------------------------------------------------- #
# Infrared / monochrome frames (CR-006, found on the live Gujarat grid)
# --------------------------------------------------------------------------- #
def test_infrared_frame_is_detected_as_carrying_no_colour():
    """Several cameras on the live grid switch to infrared overnight.

    They still deliver a three-channel frame, so nothing upstream notices — but
    every channel carries the same value. A colour estimator asked to read a
    vehicle from such a frame returns a confident answer that is fabricated,
    which is precisely the failure this system exists to avoid.
    """
    import numpy as np

    from saakshya.analytics.quality import MONOCHROME_CHROMA, assess

    rng = np.random.default_rng(7)
    grey = rng.integers(30, 200, size=(240, 320), dtype=np.uint8)
    ir = np.stack([grey, grey, grey], axis=2)          # identical channels

    q = assess(ir, vehicle_box=(20, 20, 300, 220))
    assert q.mean_chroma < MONOCHROME_CHROMA, (
        f"an infrared frame measured chroma {q.mean_chroma:.4f}")
    assert any("monochrome" in r or "infrared" in r for r in q.reasons), (
        "the frame carries no colour and the quality report does not say so")


def test_colour_frame_is_not_flagged_as_monochrome():
    """The discriminator must not fire on ordinary colour footage, including
    dim colour footage — several live cameras are dark *and* in colour."""
    import numpy as np

    from saakshya.analytics.quality import MONOCHROME_CHROMA, assess

    rng = np.random.default_rng(11)
    img = rng.integers(0, 60, size=(240, 320, 3), dtype=np.uint8)
    # A dim but genuinely coloured region.
    img[60:180, 80:240] = np.array([150, 40, 30], dtype=np.uint8)

    q = assess(img, vehicle_box=(80, 60, 240, 180))
    assert q.mean_chroma >= MONOCHROME_CHROMA, (
        f"a dim colour frame was read as monochrome (chroma {q.mean_chroma:.4f})")
