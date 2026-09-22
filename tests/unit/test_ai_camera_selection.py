"""Which cameras a scarce analysis slot is spent on.

One worker analyses a handful of cameras concurrently — measured on this host,
CPU-only, four at roughly 1.4 fps each. That ceiling is inference throughput
and is not the interesting part. What matters is *which* four, because the
challenge's Step 4 test case hands over a vehicle registration number on the
day and asks for its route across an estate of about fifty cameras.

The original rule sorted by camera_id and took the first four. Measured against
var/live.db on 22 Sep 2026 that chose cam01..cam04, every one of which is
graded UNSUITABLE for ANPR in all four of its time bands — four slots spent
where a plate cannot be read at any hour, while cameras with an ungraded band
sat idle. Alphabetical order is not a capability judgement.
"""
from __future__ import annotations

from saakshya.analytics.worker import _default_ai_cameras
from saakshya.store import Store


def _estate(tmp_path, spec: dict[str, list[str]]) -> str:
    """spec: camera_id -> anpr grade per time band."""
    url = f"sqlite:///{tmp_path/'t.db'}"
    store = Store(url)
    store.create_all()
    for cid, grades in spec.items():
        store.upsert_camera({"camera_id": cid, "district": "Ahmedabad",
                             "rtsp_url": f"rtsp://example/{cid}"})
        for i, g in enumerate(grades):
            store.upsert_capability(cid, f"band{i}", {"anpr_grade": g})
    return url


def test_a_measured_good_camera_outranks_an_alphabetically_earlier_one(tmp_path):
    url = _estate(tmp_path, {
        "cam01": ["UNSUITABLE"], "cam02": ["UNSUITABLE"],
        "cam90": ["GOOD"],
    })
    assert _default_ai_cameras(url, limit=1) == ["cam90"]


def test_never_graded_outranks_measured_unsuitable(tmp_path):
    """UNKNOWN is an absence of evidence, not a poor grade.

    A camera nobody has graded might read a plate, and analysing it is what
    produces the evidence either way. A camera measured UNSUITABLE has already
    answered the question.
    """
    url = _estate(tmp_path, {
        "cam01": ["UNSUITABLE"], "cam02": ["UNSUITABLE"],
        "cam50": ["UNKNOWN"],
    })
    assert _default_ai_cameras(url, limit=1) == ["cam50"]


def test_one_promising_band_is_enough_to_prefer_a_camera(tmp_path):
    """Grades are per time band, and a camera is worth its best hour.

    A camera unsuitable at night but never graded by day may well read a plate
    by day. This is the case that actually applies on the live estate: the
    chosen four are UNSUITABLE in three bands of four, and the alternative was
    cameras unsuitable in all four.
    """
    url = _estate(tmp_path, {
        "cam01": ["UNSUITABLE", "UNSUITABLE", "UNSUITABLE", "UNSUITABLE"],
        "cam07": ["UNSUITABLE", "UNSUITABLE", "UNSUITABLE", "UNKNOWN"],
    })
    assert _default_ai_cameras(url, limit=1) == ["cam07"]


def test_unsuitable_cameras_are_still_used_once_better_ones_run_out(tmp_path):
    """Detection and tracking work on a camera that cannot resolve a plate.

    Deprioritising UNSUITABLE must not mean refusing to analyse it, or an
    estate where everything grades UNSUITABLE would analyse nothing.
    """
    url = _estate(tmp_path, {
        "cam01": ["UNSUITABLE"], "cam02": ["UNSUITABLE"], "cam03": ["UNSUITABLE"],
    })
    assert _default_ai_cameras(url, limit=2) == ["cam01", "cam02"]


def test_the_order_is_reproducible_within_a_band(tmp_path):
    """A tie breaks alphabetically, so two runs choose the same cameras."""
    url = _estate(tmp_path, {c: ["UNKNOWN"] for c in
                             ("cam30", "cam10", "cam20")})
    assert _default_ai_cameras(url, limit=2) == ["cam10", "cam20"]
    assert _default_ai_cameras(url, limit=2) == ["cam10", "cam20"]


def test_a_camera_without_a_stream_is_never_chosen(tmp_path):
    """Capacity slots outnumber real cameras on this estate.

    22 of the 52 registry rows carry no stream url. Selecting one would spend
    a slot on a worker that logs "no source" and analyses nothing — which is
    how the previous default failed.
    """
    url = f"sqlite:///{tmp_path/'t.db'}"
    store = Store(url)
    store.create_all()
    store.upsert_camera({"camera_id": "CAP-0001", "district": "Ahmedabad"})
    store.upsert_capability("CAP-0001", "band0", {"anpr_grade": "GOOD"})
    store.upsert_camera({"camera_id": "cam88", "district": "Ahmedabad",
                         "rtsp_url": "rtsp://example/cam88"})
    store.upsert_capability("cam88", "band0", {"anpr_grade": "UNSUITABLE"})
    assert _default_ai_cameras(url, limit=4) == ["cam88"]


def test_an_ungraded_estate_still_gets_analysed(tmp_path):
    """Day one has no capability rows at all; that is not a reason to idle."""
    url = f"sqlite:///{tmp_path/'t.db'}"
    store = Store(url)
    store.create_all()
    for cid in ("cam02", "cam01"):
        store.upsert_camera({"camera_id": cid, "district": "Ahmedabad",
                             "rtsp_url": f"rtsp://example/{cid}"})
    assert _default_ai_cameras(url, limit=2) == ["cam01", "cam02"]


def test_unsuitable_ranks_worse_than_unknown_in_the_table() -> None:
    """The ordering is the whole point; pin it against a careless edit."""
    # Imported here, not at module scope: the behavioural tests above must
    # still run against a build that has no such table, or reverting the fix
    # would fail at collection and prove only that a constant is new.
    from saakshya.analytics.worker import _ANPR_PRIORITY

    assert _ANPR_PRIORITY["GOOD"] < _ANPR_PRIORITY["DEGRADED"]
    assert _ANPR_PRIORITY["DEGRADED"] < _ANPR_PRIORITY["UNKNOWN"]
    assert _ANPR_PRIORITY["UNKNOWN"] < _ANPR_PRIORITY["UNSUITABLE"]
