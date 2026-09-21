"""Phase 18 command-center, federation, overlay and investigation helpers."""
from __future__ import annotations

from saakshya.command.investigate import entity_tracking, event_search, subject_label
from saakshya.command.scale import (
    adapter_load,
    analytics_logical_load,
    bulk_synthetic_cameras,
    measure_registry,
    seed_50_evaluation,
)
from saakshya.command.summary import live_object_counts
from saakshya.federation.adapters import RTSPAdapter, demo_connected_systems
from saakshya.federation.bus import EventBus, FederatedEvent
from saakshya.intelligence import CameraGraph, VehicleSearch
from saakshya.live.annotate import overlay_allows
from saakshya.store import Store
from saakshya.watchlist.alerts import AlertStatus, parse_alert_status
from tests.conftest import make_observation


def test_overlay_modes_do_not_invent_detections():
    assert overlay_allows("car", None, overlay="off") is False
    assert overlay_allows("person", None, overlay="vehicles") is False
    assert overlay_allows("car", None, overlay="vehicles") is True
    assert overlay_allows("person", None, overlay="people") is True
    assert overlay_allows("car", "GJ01AA1111", overlay="anpr") is True
    assert overlay_allows("car", None, overlay="anpr") is False


def test_people_count_is_zero_when_store_has_only_vehicles(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'c.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "CAM-001", "district": "Ahmedabad"})
    store.add_observations([
        make_observation("CAM-001", plate="GJ01AA1111", offset_s=0),
    ])
    c = live_object_counts(store, "CAM-001")
    assert c["people"] == 0
    assert c["vehicles"] >= 1


def test_subject_label_never_says_criminal():
    assert "criminal" not in subject_label(
        plate="GJ01AA1111", object_type="car", category="stolen_vehicle").lower()
    assert subject_label(plate=None, object_type="person", category=None) == "PERSON OF INTEREST"


def test_alert_status_aliases():
    assert parse_alert_status("ACK") is AlertStatus.ACKNOWLEDGED
    assert parse_alert_status("NEW") is AlertStatus.OPEN
    assert parse_alert_status("RESOLVED") is AlertStatus.CLEARED
    assert parse_alert_status("INVESTIGATING") is AlertStatus.INVESTIGATING


def test_connected_systems_are_labelled_demo():
    rows = demo_connected_systems()
    assert len(rows) >= 4
    assert all(r["provenance"] == "DEMO/TEST" for r in rows)
    a = RTSPAdapter(system_id="x", department="d", vendor="v",
                    cameras=[{"camera_id": "c1", "url": "rtsp://127.0.0.1/s",
                              "state": "STREAMING"}])
    assert a.discover_cameras()[0]["camera_id"] == "c1"
    assert a.health_check().cameras == 1


def test_event_bus_publish_subscribe():
    bus = EventBus()
    seen = []
    bus.subscribe("t", seen.append)
    ev = FederatedEvent(
        event_id="E1", camera_id="c", department=None,
        timestamp="2026-09-17T00:00:00+00:00", location=None,
        entity_id="GJ01AA1111", event_type="plate.read", confidence=0.9,
        evidence_ref=None, source_system="saakshya")
    bus.publish("t", ev)
    assert bus.throughput("t") == 1
    assert seen[0].entity_id == "GJ01AA1111"


def test_event_search_and_contradiction_card(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'e.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "A", "district": "Ahmedabad",
                         "lat": 23.03, "lon": 72.58, "site": "Signal A"})
    store.upsert_camera({"camera_id": "FAR", "district": "Ahmedabad",
                         "lat": 24.5, "lon": 72.58, "site": "Signal FAR"})
    store.add_observations([
        make_observation("A", plate="GJ01AA1111", offset_s=0),
        make_observation("FAR", plate="GJ01AA1111", offset_s=2, track="T2"),
    ])
    ev = event_search(store, plate="GJ01AA1111")
    assert ev["count"] >= 1
    follow = VehicleSearch(store, CameraGraph(store).load()).follow_vehicle(
        "GJ01AA1111", actor="t", case_id="FIR-1", purpose="test")
    card = entity_tracking(follow, category="stolen_vehicle")
    assert card["target"] == "WATCHLIST MATCH"
    assert any(t["result"] == "CONTRADICTION" for t in card["transitions"])
    assert card["hops"][0]["role"] == "FIRST SEEN"


def test_synthetic_registry_and_50_eval(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 's.db'}")
    store.create_all()
    bulk_synthetic_cameras(store, 120, prefix="SYN")
    m = measure_registry(store)
    assert m["cameras"] == 120
    assert m["lookup_ms"] >= 0
    fifty = Store(f"sqlite:///{tmp_path / 'f.db'}")
    fifty.create_all()
    spec = seed_50_evaluation(fifty)
    assert spec["onboarded"] == 50
    assert spec["real_probe_ids"] == 30
    assert spec["own_feeds"] == 2
    assert spec["synthetic_control"] == 18
    assert "not 50 government" in spec["label"]


def test_adapter_and_analytics_load_are_labelled_synthetic():
    a = adapter_load(5)
    assert a["systems"] == 5
    assert a["label"].startswith("SYNTHETIC")
    b = analytics_logical_load(25)
    assert b["gpu_utilization"] == "UNAVAILABLE"
    assert b["logical_streams"] == 25
