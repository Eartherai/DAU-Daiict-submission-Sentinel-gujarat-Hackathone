"""UI wall priority / decode-budget model (mirrors ui/app.js streamPriority)."""
from tools.gov_wall_scaling_cert import (
    build_managed_roster,
    decode_budget,
    stream_priority,
    wall_cams,
)


def test_primary_overrides_declared():
    cam = {"camera_id": "cam01", "stream_priority": "PREVIEW", "state": "STREAMING"}
    assert stream_priority(cam, primary_id="cam01") == "PRIMARY"


def test_failed_is_inactive():
    cam = {"camera_id": "cam99", "state": "FAILED"}
    assert stream_priority(cam) == "INACTIVE"


def test_wall_slices_to_mode():
    roster = build_managed_roster(30)
    visible = wall_cams(roster, wall_mode=9, primary_id="cam01")
    assert len(visible) == 9
    assert stream_priority(visible[0], primary_id="cam01") == "PRIMARY"


def test_decode_budget_keeps_30_managed_cheap():
    roster = build_managed_roster(30)
    pris = [stream_priority(c, primary_id="cam01") for c in roster]
    budget = decode_budget(pris)
    assert budget["browser_decode_candidates"] <= 4
    assert budget["inactive"] >= 15
    assert budget["browser_decode_candidates"] < 30
