"""A stream that decodes into garbage must not read as an empty road.

cam21 delivered 1,628 frames over fourteen minutes, 777 analysed, and produced
**zero** observations while the decoder reported no errors whatsoever. The
frames were decoder concealment — heavy macroblock artefacts and lost chroma
after reference frames went missing on a lossy link.

Every health counter said the camera was fine. Only the absence of detections
hinted at it, and an absence of detections is also exactly what a clear road
looks like. Those are opposite findings, and an investigator told "no vehicles
were seen" will act on the wrong one.
"""
from __future__ import annotations

import numpy as np
import pytest

from saakshya.analytics.corruption import (
    MACROBLOCK,
    SAMPLE,
    assess_corruption,
)


def clean_scene(h: int = 720, w: int = 1280) -> np.ndarray:
    """A photograph-like frame: gradients, solid objects, and sensor noise.

    The noise matters. An earlier version of this helper was a perfectly
    noiseless gradient, and its 8-bit quantisation stair-steps happened to fall
    near the macroblock grid — it measured a ratio of 7.5 and read as corrupt.
    No camera produces a noiseless image; every sensor has a noise floor, and a
    detector calibrated against imagery that has none is calibrated against
    nothing real. The fix belonged in the fixture, not in the thresholds.
    """
    rng = np.random.default_rng(11)
    y, x = np.mgrid[0:h, 0:w]
    base = 110 + 50 * np.sin(x / 190.0) + 25 * (y / h)
    # Broadband texture, not a single spatial frequency. A lone sinusoid
    # quantised to 8 bits produces evenly spaced stair-steps that can beat
    # against the 16-pixel grid by coincidence — which is what a real scene,
    # full of edges at every scale, never does.
    for scale, amp in ((3, 9.0), (11, 6.0), (37, 4.0)):
        coarse = rng.normal(0, amp, (h // scale + 2, w // scale + 2))
        base = base + np.kron(coarse, np.ones((scale, scale)))[:h, :w]
    base = base + rng.normal(0, 2.5, base.shape)          # sensor noise floor
    g = np.clip(base, 0, 255).astype(np.uint8)
    img = np.dstack([g, g, g]).astype(np.uint8)
    img[h // 3:h // 3 + 70, w // 4:w // 4 + 160] = (40, 40, 160)
    img[h // 2:h // 2 + 60, 2 * w // 3:2 * w // 3 + 130] = (30, 120, 40)
    return img


def blocked(h: int = 720, w: int = 1280, step: int = MACROBLOCK) -> np.ndarray:
    """Concealment: constant blocks on the codec's macroblock grid."""
    rng = np.random.default_rng(4)
    img = np.zeros((h, w, 3), np.uint8)
    for yy in range(0, h, step):
        for xx in range(0, w, step):
            img[yy:yy + step, xx:xx + step] = rng.integers(60, 200, 3)
    return img


def test_a_clean_frame_is_not_flagged():
    assert not assess_corruption(clean_scene()).suspect


def test_macroblock_artefacts_are_flagged():
    c = assess_corruption(blocked())
    assert c.suspect
    assert "macroblock" in c.reason


def test_a_clean_frame_and_a_corrupt_one_are_well_separated():
    """The threshold should not need to be delicate."""
    assert (assess_corruption(blocked()).blockiness
            > assess_corruption(clean_scene()).blockiness * 1.5)


def test_lost_chroma_rows_are_flagged():
    img = clean_scene()
    for yy in range(0, 240, MACROBLOCK * 2):        # green bands, no detail
        img[yy:yy + MACROBLOCK, :] = (20, 200, 20)
    c = assess_corruption(img, full=True)
    assert c.chroma_band_fraction > 0
    assert c.suspect


def test_the_sample_is_aligned_to_the_macroblock_grid():
    """Downscaling instead of cropping destroyed the signal outright — a
    corrupted frame measured 1.42 and read as clean — because scaling moves the
    discontinuities off the grid. A crop keeps them only if its origin is a
    multiple of 16."""
    big = blocked(1080, 1920)
    assert assess_corruption(big).suspect, "sampling lost the artefact"
    assert assess_corruption(big, full=True).suspect


def test_sampling_agrees_with_a_full_assessment_on_clean_frames():
    big = clean_scene(1080, 1920)
    assert assess_corruption(big).suspect is assess_corruption(big, full=True).suspect


def test_a_small_frame_is_assessed_whole():
    small = clean_scene(240, 320)
    assert small.shape[0] < SAMPLE
    assert not assess_corruption(small).suspect


def test_a_flat_frame_does_not_divide_by_zero():
    """A blacked-out camera has no discontinuity anywhere."""
    c = assess_corruption(np.zeros((720, 1280, 3), np.uint8))
    assert np.isfinite(c.blockiness)


@pytest.mark.parametrize("shape", [(720, 1280, 3), (240, 320, 3), (48, 48, 3)])
def test_it_never_raises_on_plausible_frame_shapes(shape):
    rng = np.random.default_rng(1)
    assess_corruption(rng.integers(0, 255, shape, dtype=np.uint8))


# ─── stream verdicts ─────────────────────────────────────────────────────────
# A symptom in a frame and a verdict about a stream are different questions, and
# conflating them produced a false alarm on the first live run: cam16 was called
# corrupt on 10 of 15 samples while producing 375 usable observations.
from saakshya.analytics.corruption import (
    STREAM_MIN_SAMPLES,
    stream_verdict,
)


def test_a_stream_that_is_almost_all_concealment_is_corrupt():
    """cam21, measured: 97% of 30 sampled frames."""
    state, why = stream_verdict(30, 29)
    assert state == "CORRUPT"
    assert "not the road" in why


def test_intermittent_loss_is_not_corruption():
    """cam16, measured: 27% of frames flagged, 375 usable observations in the
    same run. Ordinary packet loss on a live link must not condemn a camera."""
    assert stream_verdict(30, 8)[0] == "OK"


def test_a_healthy_stream_is_ok():
    """cam01, measured: 13%."""
    assert stream_verdict(30, 4)[0] == "OK"


def test_the_middle_band_is_degraded_not_condemned():
    state, why = stream_verdict(40, 20)
    assert state == "DEGRADED"
    assert "Usable" in why


def test_a_small_sample_is_unknown_never_ok():
    """The exact false alarm: 10 of 15 is an unlucky draw from a 27% rate.
    'We did not look hard enough' and 'it is fine' are different findings."""
    state, why = stream_verdict(15, 10)
    assert state == "UNKNOWN"
    assert str(STREAM_MIN_SAMPLES) in why


def test_a_clean_stream_with_too_few_samples_is_also_unknown():
    assert stream_verdict(3, 0)[0] == "UNKNOWN"


def test_the_thresholds_leave_margin_around_the_measured_gap():
    """cam21 at 97% and cam16 at 27% are far apart; the bar should not sit on
    top of either."""
    from saakshya.analytics.corruption import (
        STREAM_CORRUPT_RATE,
        STREAM_DEGRADED_RATE,
    )
    assert 0.30 < STREAM_DEGRADED_RATE < STREAM_CORRUPT_RATE < 0.95
    assert STREAM_CORRUPT_RATE - 0.27 > 0.4, "too close to the healthy case"
