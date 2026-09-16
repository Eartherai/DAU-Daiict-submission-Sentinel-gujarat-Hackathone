from saakshya.intelligence import CameraGraph, VehicleSearch
from saakshya.store import Store
from tests.conftest import make_observation


def _store(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'follow.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "A", "district": "Ahmedabad",
                         "lat": 23.03, "lon": 72.58, "tier": "A"})
    store.upsert_camera({"camera_id": "B", "district": "Ahmedabad",
                         "lat": 23.031, "lon": 72.581, "tier": "A"})
    store.upsert_camera({"camera_id": "FAR", "district": "Ahmedabad",
                         "lat": 24.5, "lon": 72.58, "tier": "A"})
    return store


def test_follow_ranks_same_plate_and_returns_timeline_and_evidence(tmp_path):
    store = _store(tmp_path)
    first = make_observation("A", plate="GJ01AA1111", offset_s=0)
    later = make_observation("B", plate="GJ01AA1111", offset_s=120,
                              track="T2")
    store.add_observations([first, later])
    result = VehicleSearch(store, CameraGraph(store).load()).follow_vehicle(
        "GJ01AA1111", actor="officer", case_id="FIR-1", purpose="follow-up")
    assert result["route"][0]["camera_id"] == "A"
    assert any(c["camera_id"] == "B" and c["terms"]["plate"] == 1
               for c in result["candidates"])
    assert result["timeline"]
    assert "evidence_refs" in result


def test_follow_excludes_impossible_transition_with_explicit_contradiction(tmp_path):
    store = _store(tmp_path)
    first = make_observation("A", plate="GJ01AA1111", offset_s=0)
    impossible = make_observation("FAR", plate="GJ01AA1111", offset_s=2,
                                   track="T2")
    store.add_observations([first, impossible])
    result = VehicleSearch(store, CameraGraph(store).load()).follow_vehicle(
        "GJ01AA1111", actor="officer", case_id="FIR-1", purpose="follow-up")
    assert not any(c["camera_id"] == "FAR" for c in result["candidates"])
    contradiction = next(c for c in result["contradictions"]
                          if c["to_camera"] == "FAR")
    assert contradiction["code"] == "ROUTE_CONTRADICTION"
    assert contradiction["distance_m"] > 0
    assert contradiction["elapsed_s"] == 2
    assert contradiction["implied_speed_kmh"] > 200
