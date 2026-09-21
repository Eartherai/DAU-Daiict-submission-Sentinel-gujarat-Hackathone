"""Onboarding, and the guard that used to undo it.

Model 1 is the compulsory model and asks for bulk import, manual entry and
API-based onboarding. Two properties matter more than the endpoints:

* an import either applies or it does not, so an operator can always say what
  landed;
* what is onboarded stays onboarded.

The second was not true. `enforce_evaluation_50` deleted every camera it did
not recognise on each startup, so a department could import a spreadsheet, see
the cameras appear, and find them gone after a restart with no error anywhere.
"""

import pytest

from saakshya.command.domain import enforce_evaluation_50
from saakshya.store.repository import Store


def _store(tmp_path, name="onboard.db"):
    store = Store(f"sqlite:///{tmp_path / name}")
    store.create_all()
    return store


def _ids(store):
    return {c["camera_id"] for c in store.list_cameras()}


def test_an_onboarded_camera_survives_the_fixture_guard(tmp_path):
    store = _store(tmp_path)
    store.upsert_camera({"camera_id": "MC-0001", "name": "Municipal gate",
                         "department": "Municipal Corporation",
                         "lat": 23.03, "lon": 72.58})
    enforce_evaluation_50(store)
    assert "MC-0001" in _ids(store), (
        "a camera onboarded through the registry was deleted by the "
        "evaluation fixture guard")


def test_the_guard_still_removes_its_own_stale_fixtures(tmp_path):
    """Not deleting everything must not become deleting nothing."""
    store = _store(tmp_path, "fixtures.db")
    store.upsert_camera({"camera_id": "FAR", "name": "stale fixture"})
    enforce_evaluation_50(store)
    assert "FAR" not in _ids(store)


def test_the_guard_keeps_the_evaluation_set(tmp_path):
    store = _store(tmp_path, "fifty.db")
    out = enforce_evaluation_50(store)
    ids = _ids(store)
    assert "cam01" in ids and "cam30" in ids
    assert out["onboarded"] >= 50


@pytest.mark.parametrize("cid", ["cam07", "CTL-00003"])
def test_seeded_shapes_are_recognised_as_fixtures(tmp_path, cid):
    from saakshya.command.domain import _is_evaluation_fixture
    assert _is_evaluation_fixture(cid, {})


@pytest.mark.parametrize("cid", ["MC-0001", "HLT-DEMO-01", "rto-kalol-3"])
def test_onboarded_shapes_are_not_fixtures(tmp_path, cid):
    from saakshya.command.domain import _is_evaluation_fixture
    assert not _is_evaluation_fixture(cid, {})


def test_csv_coercion_rejects_a_number_that_is_not_one():
    from fastapi import HTTPException

    from saakshya.api.routes_registry import _coerce_csv_row
    with pytest.raises(HTTPException) as exc:
        _coerce_csv_row({"camera_id": "c1", "lat": "north-ish"}, line=4)
    assert "line 4" in exc.value.detail["message"]


def test_csv_coercion_ignores_columns_the_registry_does_not_hold():
    """A departmental export carries columns that are none of our business."""
    from saakshya.api.routes_registry import _coerce_csv_row
    out = _coerce_csv_row(
        {"camera_id": "c1", "lat": "23.03", "amc_vendor": "somebody"}, line=2)
    assert out == {"camera_id": "c1", "lat": 23.03}


def test_export_columns_round_trip_into_the_importer():
    """An export corrected in a spreadsheet has to be re-importable."""
    from saakshya.api.routes_registry import FIELDS, CameraIn
    accepted = set(CameraIn.model_fields)
    assert set(FIELDS) <= accepted, set(FIELDS) - accepted
