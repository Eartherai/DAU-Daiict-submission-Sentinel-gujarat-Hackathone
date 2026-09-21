"""Model 1 asks the registry to report what it does not know.

A registry that lists only what it holds hides exactly the fields that block
onboarding a department, so these tests pin the shape of the gap report and,
more importantly, that an absence is reported as an absence.
"""

from saakshya.gis.service import MapService
from saakshya.store.repository import Store


def _store(tmp_path, name="gaps.db"):
    store = Store(f"sqlite:///{tmp_path / name}")
    store.create_all()
    return store


def test_absent_expected_department_is_named(tmp_path):
    store = _store(tmp_path)
    store.upsert_camera({"camera_id": "c1", "name": "one",
                         "department": "Home (Police)",
                         "lat": 23.0, "lon": 72.5})
    gaps = MapService(store).registry_gaps()
    assert gaps["cameras"] == 1
    assert gaps["departments_present"] == {"Home (Police)": 1}
    # Four of the five expected departments have nothing onboarded.
    assert "Health" in gaps["departments_absent"]
    assert "Municipal Corporation" in gaps["departments_absent"]
    assert "Home (Police)" not in gaps["departments_absent"]


def test_unfilled_fields_are_counted_not_rounded_away(tmp_path):
    store = _store(tmp_path, "f.db")
    store.upsert_camera({"camera_id": "c1", "name": "one", "lat": 23.0,
                         "lon": 72.5, "vms": "Milestone"})
    store.upsert_camera({"camera_id": "c2", "name": "two", "lat": 23.1,
                         "lon": 72.6})
    by_field = {g["field"]: g for g in MapService(store).registry_gaps()["field_gaps"]}
    assert by_field["vms"]["missing"] == 1
    assert by_field["vms"]["of"] == 2
    assert by_field["vms"]["pct"] == 50.0
    assert "c2" in by_field["vms"]["cameras"]
    assert "c1" not in by_field["vms"]["cameras"]


def test_camera_without_coordinates_is_a_gap_not_an_omission(tmp_path):
    store = _store(tmp_path, "u.db")
    store.upsert_camera({"camera_id": "placed", "name": "p",
                         "lat": 23.0, "lon": 72.5})
    store.upsert_camera({"camera_id": "unplaced", "name": "u"})
    gaps = MapService(store).registry_gaps()
    # The unlocated camera is still part of the estate being reported on.
    assert gaps["cameras"] == 2
    coords = next(g for g in gaps["field_gaps"] if g["field"] == "coordinates")
    assert coords["missing"] == 1
    assert coords["cameras"] == ["unplaced"]


def test_capacity_slots_are_not_counted_as_cameras(tmp_path):
    store = _store(tmp_path, "s.db")
    store.upsert_camera({"camera_id": "cam01", "name": "real",
                         "lat": 23.0, "lon": 72.5})
    store.upsert_camera({"camera_id": "CTL-00000", "name": "synthetic 0",
                         "lat": 20.0, "lon": 68.5})
    gaps = MapService(store).registry_gaps()
    assert gaps["cameras"] == 1
    assert gaps["capacity_slots"] == 1
    for g in gaps["field_gaps"]:
        assert "CTL-00000" not in g["cameras"]


def test_the_report_counts_past_the_map_viewport_limit(tmp_path):
    """A report must not inherit a viewport's row cap.

    The first version walked `cameras_in_bbox`, which stops at 20,000 rows
    because it exists to fill a map. On a statewide estate that reported gaps
    for a quarter of the cameras and said nothing about the other sixty
    thousand — a silent truncation is worse than no report at all.
    """
    from saakshya.command.scale import bulk_synthetic_cameras

    store = _store(tmp_path, "big.db")
    n = 20_500  # deliberately past the 20,000 viewport cap
    bulk_synthetic_cameras(store, n)
    gaps = MapService(store).registry_gaps()
    assert gaps["cameras"] == n
    # And the per-field counts must cover the whole estate, not the first page.
    vms = next(g for g in gaps["field_gaps"] if g["field"] == "vms")
    assert vms["missing"] == n
    assert vms["of"] == n
    # The sample stays bounded even though the count does not.
    assert len(vms["cameras"]) <= 40
    assert vms["truncated"] == n - len(vms["cameras"])
