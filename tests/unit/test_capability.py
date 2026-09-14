"""Camera capability grading.

The tests that matter here are the ones that assert what the system *refuses*
to conclude. Grading a camera as unsuitable because it has seen nothing is the
single most damaging mistake this module could make on a government estate:
it would condemn working cameras pointed at quiet scenes, and it would teach
operators that the grades are noise.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from saakshya.capability import (
    DEFAULT_POLICY,
    CapabilityGrader,
    Grade,
    TimeBand,
    time_band,
)
from tests.conftest import make_observation

CAM = "GR-01"


@pytest.fixture
def grader(store):
    store.upsert_camera({"camera_id": CAM, "name": "grading target",
                         "district": "Ahmedabad", "lat": 23.0, "lon": 72.6})
    return CapabilityGrader(store)


def healthy(frames: int = 5000, fps: float = 12.0, errors: int = 0) -> dict:
    return {"state": "STREAMING", "reachable": True, "frames": frames,
            "measured_fps": fps, "decoder_errors": errors, "segment_breaks": 0}


# --------------------------------------------------------------------------- #
# UNKNOWN is a first-class outcome
# --------------------------------------------------------------------------- #
def test_a_silent_but_healthy_camera_is_unknown_not_unsuitable(grader):
    a = grader.grade_camera(CAM, health=healthy(), observations=[])
    assert a.presence is Grade.UNKNOWN
    assert a.anpr is Grade.UNKNOWN
    assert a.vehicle is Grade.UNKNOWN
    assert "not evidence of a fault" in a.reasons["presence"]


def test_too_few_frames_is_unknown(grader):
    a = grader.grade_camera(CAM, health=healthy(frames=10), observations=[])
    assert a.presence is Grade.UNKNOWN
    assert "not yet measured" in a.reasons["presence"]


def test_stored_detections_grade_presence_when_frame_counter_is_short(grader):
    """A missing or short decoder counter is not evidence of a dead camera
    when the store already holds detections from that stream."""
    obs = [make_observation(CAM, plate=None, offset_s=i) for i in range(30)]
    a = grader.grade_camera(CAM, health=healthy(frames=10), observations=obs)
    assert a.presence is Grade.GOOD
    assert "stored" in a.reasons["presence"]


def test_too_few_observations_is_unknown_for_anpr(grader):
    obs = [make_observation(CAM, plate=None, offset_s=i) for i in range(5)]
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.anpr is Grade.UNKNOWN
    assert "Insufficient evidence" in a.reasons["anpr"]


def test_unknown_camera_is_not_usable_for_anything(grader):
    a = grader.grade_camera(CAM, health=healthy(frames=0), observations=[])
    assert a.usable_for() == []


# --------------------------------------------------------------------------- #
# Real grades, from real distributions
# --------------------------------------------------------------------------- #
def test_a_good_anpr_camera_grades_good(grader):
    obs = [make_observation(CAM, plate=f"GJ01AA{1000 + i}", offset_s=i * 10)
           for i in range(30)]
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.anpr is Grade.GOOD
    assert a.presence is Grade.GOOD
    assert "anpr" in a.usable_for()
    assert a.evidence["plate_yield"] == 1.0


def test_a_camera_that_never_reads_a_plate_is_unsuitable(grader):
    obs = [make_observation(CAM, plate=None, offset_s=i * 10) for i in range(40)]
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.anpr is Grade.UNSUITABLE
    assert "not viable" in a.reasons["anpr"]
    # But it can still tell us something passed, which is the useful part.
    assert a.presence is Grade.GOOD
    assert "presence" in a.usable_for()


def test_intermittent_reads_grade_degraded(grader):
    obs = ([make_observation(CAM, plate=f"GJ01AA{2000 + i}", offset_s=i * 10)
            for i in range(6)]
           + [make_observation(CAM, plate=None, offset_s=100 + i * 10, track=f"n{i}")
              for i in range(34)])
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.anpr is Grade.DEGRADED
    assert "corroboration" in a.reasons["anpr"]


def test_small_plates_cap_the_grade_at_degraded(grader):
    obs = []
    for i in range(30):
        o = make_observation(CAM, plate=f"GJ01AA{3000 + i}", offset_s=i * 10)
        o.plate_pixel_width = 40.0          # well below the OCR threshold
        obs.append(o)
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.anpr is Grade.DEGRADED
    assert "below" in a.reasons["anpr"]


def test_low_fps_degrades_presence(grader):
    obs = [make_observation(CAM, plate=None, offset_s=i * 10) for i in range(30)]
    a = grader.grade_camera(CAM, health=healthy(fps=0.4), observations=obs)
    assert a.presence is Grade.DEGRADED
    assert "missed between frames" in a.reasons["presence"]


def test_decoder_errors_degrade_presence_with_the_right_reason(grader):
    obs = [make_observation(CAM, plate=None, offset_s=i * 10) for i in range(30)]
    a = grader.grade_camera(CAM, health=healthy(errors=500), observations=obs)
    assert a.presence is Grade.DEGRADED
    assert "absence of a detection here is not evidence of absence" in \
        a.reasons["presence"]


def test_colourless_observations_make_appearance_unsuitable(grader):
    obs = [make_observation(CAM, plate=None, colour=None, offset_s=i * 10)
           for i in range(30)]
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.vehicle is Grade.UNSUITABLE
    assert "appearance" not in a.usable_for()


# --------------------------------------------------------------------------- #
# The three grades are independent
# --------------------------------------------------------------------------- #
def test_grades_are_independent(grader):
    """The realistic municipal camera: sees vehicles, cannot read plates."""
    obs = [make_observation(CAM, plate=None, colour="white", offset_s=i * 10)
           for i in range(40)]
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    assert a.presence is Grade.GOOD
    assert a.vehicle is Grade.GOOD
    assert a.anpr is Grade.UNSUITABLE
    assert set(a.usable_for()) == {"appearance", "presence"}


# --------------------------------------------------------------------------- #
# Evidence and persistence
# --------------------------------------------------------------------------- #
def test_every_grade_carries_its_evidence(grader):
    obs = [make_observation(CAM, plate=f"GJ01AA{4000 + i}", offset_s=i * 10)
           for i in range(30)]
    a = grader.grade_camera(CAM, health=healthy(), observations=obs)
    for key in ("policy_version", "observations", "plate_yield",
                "median_plate_px", "median_sharpness", "frames"):
        assert key in a.evidence, f"missing evidence field {key}"
    assert a.evidence["policy_version"] == DEFAULT_POLICY.version
    assert set(a.reasons) == {"anpr", "vehicle", "presence"}


def test_grades_persist_and_read_back(store, grader):
    store.add_observations([
        make_observation(CAM, plate=f"GJ01AA{5000 + i}", offset_s=i * 10)
        for i in range(25)])
    store.upsert_health(CAM, healthy())
    out = grader.grade_all(bands=(TimeBand.ALL,))
    assert len(out) == 1
    rows = store.list_capability([CAM])
    assert rows and rows[0]["anpr_grade"] == "GOOD"
    assert rows[0]["presence_grade"] == "GOOD"
    summary = grader.summary()
    assert summary["grades"]["anpr"]["GOOD"] == 1


# --------------------------------------------------------------------------- #
# Time bands (§20) — measured, never a weather model
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("hour_utc,mean_luma,expect", [
    (4, 0.55, TimeBand.DAY),        # 09:30 IST
    (12, 0.55, TimeBand.DAY),       # 17:30 IST — still inside the day window
    (14, 0.55, TimeBand.NIGHT),     # 19:30 IST — past 18:00 IST
    (20, 0.45, TimeBand.NIGHT),     # 01:30 IST, artificially lit
    (4, 0.10, TimeBand.LOW_LIGHT),  # daytime underpass
    (20, 0.05, TimeBand.LOW_LIGHT),
])
def test_time_band_assignment(hour_utc, mean_luma, expect):
    """Bands are computed in IST, because the estate is in Gujarat and an
    officer reading "NIGHT" means their night, not UTC's."""
    t = datetime(2026, 9, 1, hour_utc, 0, tzinfo=UTC)
    assert time_band(t, mean_luma) is expect


def test_measured_brightness_beats_the_clock():
    noon_ist = datetime(2026, 9, 1, 6, 30, tzinfo=UTC)
    assert time_band(noon_ist, 0.62) is TimeBand.DAY
    assert time_band(noon_ist, 0.04) is TimeBand.LOW_LIGHT


def test_band_input_is_brightness_not_exposure_quality():
    """Regression: the band classifier once took the `luminance` field, which is
    an exposure *quality* score peaking at mid-grey, not brightness.

    Two consequences, both silent: a correctly exposed daylight crop scores near
    1.0 and a correctly exposed night crop also scores near 1.0, so night became
    indistinguishable from day; and with a raw-units threshold applied to a 0..1
    measurement, every observation fell into LOW_LIGHT. This test pins the units
    by asserting that a mid-grey daylight crop — the case that scores *highest*
    on exposure quality — is not classified as low light.
    """
    noon_ist = datetime(2026, 9, 1, 6, 30, tzinfo=UTC)
    # mean luma 0.45 is the exposure-quality optimum: a well-lit daylight scene.
    assert time_band(noon_ist, 0.45) is TimeBand.DAY
    # And the threshold lives in the 0..1 space, so no plausible brightness
    # value collapses every sample into one band.
    bands = {time_band(noon_ist, x) for x in (0.05, 0.2, 0.4, 0.6, 0.9)}
    assert len(bands) > 1, "every brightness fell into a single band"


def test_appearance_sharpness_threshold_is_normalised():
    """The sharpness a camera is graded against is the 0..1 normalised figure
    from analytics.quality, not raw Laplacian variance. A raw-units threshold
    here made a GOOD appearance grade unreachable for every camera."""
    from saakshya.capability import DEFAULT_POLICY
    assert 0.0 < DEFAULT_POLICY.vehicle_good_sharpness_norm <= 1.0


def test_no_weather_band_exists():
    """§20: weather is not classified, so there is no band pretending to."""
    assert {str(b) for b in TimeBand} == {"DAY", "NIGHT", "LOW_LIGHT", "ALL"}


def test_persons_do_not_dilute_plate_yield(grader):
    """Person detections share the COCO pass. Counting them in the ANPR
    denominator would make a camera that reads every vehicle look unsuitable."""
    vehicles = [make_observation(CAM, plate=f"GJ01AA{4000 + i}", offset_s=i * 10)
                for i in range(30)]
    people = []
    for i in range(200):
        o = make_observation(CAM, plate=None, offset_s=1000 + i, track=f"p{i}")
        o.object_type = "person"
        o.plate_pixel_width = None
        people.append(o)
    a = grader.grade_camera(CAM, health=healthy(), observations=vehicles + people)
    assert a.anpr is Grade.GOOD
    assert a.evidence["plate_yield"] == 1.0
    assert a.evidence["vehicle_observations"] == 30
    assert a.evidence["person_observations"] == 200
    assert a.samples == 230


def test_a_person_only_camera_is_unknown_for_anpr_not_unsuitable(grader):
    people = []
    for i in range(40):
        o = make_observation(CAM, plate=None, offset_s=i, track=f"p{i}")
        o.object_type = "person"
        o.colour = None
        people.append(o)
    a = grader.grade_camera(CAM, health=healthy(), observations=people)
    assert a.anpr is Grade.UNKNOWN
    assert "never plated" in a.reasons["anpr"]
    assert a.vehicle is Grade.UNKNOWN
    assert a.presence is Grade.GOOD
    assert "anpr" not in a.usable_for()
