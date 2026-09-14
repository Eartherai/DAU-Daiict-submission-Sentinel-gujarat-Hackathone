"""A discovery pass must never erase what an operator curated.

This is a regression test for a real data-loss incident: a live ingest run
re-registered every camera from a probe that knows only ids and stream
properties, and in doing so overwrote nineteen surveyed positions, every
camera name and every district with None. The map emptied silently — no error,
no warning, and the UI correctly reported that no camera had a position.

The rule being pinned: for curated columns, None from a writer means "I do not
know", never "delete". Clearing is possible, but only when asked for by name.
"""
from __future__ import annotations

import pytest

from saakshya.live.grid import LiveCamera
from saakshya.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path}/curation.db")
    s.create_all()
    return s


def _curated(store):
    store.upsert_camera({
        "camera_id": "cam01", "name": "Chiman bhai Bridge",
        "site": "Chimanbhai Patel Bridge", "district": "Ahmedabad",
        "department": "Ahmedabad City Police",
        "lat": 23.0296, "lon": 72.5219,
        "location_precision": "LANDMARK", "location_basis": "DERIVED_FROM_NAME",
    })


def test_discovery_does_not_erase_curated_fields(store):
    _curated(store)
    # Exactly what a probe writes: it knows the id and the stream, nothing else.
    store.upsert_camera({"camera_id": "cam01", "name": None, "site": None,
                         "district": None, "department": None,
                         "lat": None, "lon": None,
                         "codec": "h264", "width": 1920, "height": 1080})
    cam = store.get_camera("cam01")
    assert cam["name"] == "Chiman bhai Bridge"
    assert cam["district"] == "Ahmedabad"
    assert (cam["lat"], cam["lon"]) == (23.0296, 72.5219)
    assert cam["location_precision"] == "LANDMARK"
    # ...while the stream facts it *did* measure are taken.
    assert (cam["codec"], cam["width"], cam["height"]) == ("h264", 1920, 1080)


def test_curation_still_overwrites_curation(store):
    """The protection is against None, not against a real correction."""
    _curated(store)
    store.upsert_camera({"camera_id": "cam01", "name": "Chimanbhai Patel Bridge",
                         "lat": 23.0300, "lon": 72.5225,
                         "location_basis": "CATALOGUE",
                         "location_precision": "LANDMARK"})
    cam = store.get_camera("cam01")
    assert cam["name"] == "Chimanbhai Patel Bridge"
    assert cam["lat"] == 23.0300
    assert cam["location_basis"] == "CATALOGUE"


def test_clearing_is_possible_but_must_be_named(store):
    _curated(store)
    store.upsert_camera({"camera_id": "cam01", "lat": None, "lon": None},
                        clear=frozenset({"lat", "lon"}))
    cam = store.get_camera("cam01")
    assert cam["lat"] is None and cam["lon"] is None
    assert cam["name"] == "Chiman bhai Bridge"     # untouched


def test_new_camera_is_named_after_its_id(store):
    store.upsert_camera({"camera_id": "cam99", "codec": "hevc"})
    assert store.get_camera("cam99")["name"] == "cam99"


def test_probe_row_omits_what_it_cannot_know():
    """The discovery row must not carry fabricated values at all.

    Sending `name=camera_id` is worse than sending nothing: it is a real string,
    so no None-guard can distinguish it from a genuine name, and it overwrites
    'Chiman bhai Bridge' with 'cam01'.
    """
    row = LiveCamera(camera_id="cam01",
                     rtsp_url="rtsp://host:8554/stream/cam01").to_registry_row()
    assert "name" not in row
    assert "lat" not in row and "lon" not in row
    assert "district" not in row
    assert row["camera_id"] == "cam01"


def test_probe_row_keeps_what_it_does_know():
    row = LiveCamera(camera_id="cam01", name="Janpath", district="Ahmedabad",
                     rtsp_url="rtsp://host:8554/stream/cam01").to_registry_row()
    assert row["name"] == "Janpath"
    assert row["district"] == "Ahmedabad"
