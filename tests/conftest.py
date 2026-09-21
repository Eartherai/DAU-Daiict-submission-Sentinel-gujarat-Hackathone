"""Shared fixtures.

The world these tests run against is built from the camera catalogue, never from
constants. There is no camera id, plate or district written into a fixture that
the production code also knows about — the evaluation supplies an arbitrary
target on the day, and a suite that quietly depends on `C-014` would pass here
and fail there.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from saakshya.store import Store, VehicleObservation

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "var" / "media"

T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_production_maps_key(monkeypatch):
    """Keep real Maps keys out of the test process.

    AppState may otherwise read gitignored .env.local. A failing
    ``assert not state.google_maps_key`` would print the secret.
    """
    monkeypatch.setenv("SAAKSHYA_GOOGLE_MAPS_DISABLE", "1")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("SAAKSHYA_GOOGLE_MAPS_KEY", raising=False)


def _catalogue() -> list[dict]:
    p = MEDIA / "catalogue.json"
    if not p.is_file():
        pytest.skip("camera catalogue not present; run `make media`")
    return json.loads(p.read_text())["cameras"]


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(f"sqlite:///{tmp_path / 'test.db'}")
    s.create_all()
    return s


@pytest.fixture
def catalogue() -> list[dict]:
    return _catalogue()


@pytest.fixture
def seeded(store, catalogue) -> Store:
    """A store with the camera registry loaded and nothing else."""
    for c in catalogue:
        store.upsert_camera({
            "camera_id": c["id"], "name": c["name"],
            "department": c["department"], "district": c["district"],
            "lat": c["location"]["lat"], "lon": c["location"]["lon"],
            "codec": c["codec"], "width": c["properties"]["width"],
            "height": c["properties"]["height"],
            "declared_fps": c["properties"]["declared_fps"],
            "tier": "UNASSIGNED", "enabled": True})
    return store


def make_observation(camera_id: str, *, plate: str | None = None,
                     offset_s: float = 0.0, quality: float = 0.8,
                     district: str = "Ahmedabad", colour: str | None = "white",
                     track: str = "T1", lat: float | None = None,
                     lon: float | None = None) -> VehicleObservation:
    """A synthetic observation. Used where the test is about the *layer above*
    detection, so running the detector would only add noise and runtime."""
    when = T0 + timedelta(seconds=offset_s)
    return VehicleObservation(
        camera_id=camera_id, pts_s=offset_s, t_norm=when, t_ingest=when,
        dedup_key=f"{camera_id}|{track}|{offset_s}|{plate or 'none'}",
        district=district, department="Home (Traffic)", track_id=track,
        segment_id="SEG1", object_type="car", bbox=(10.0, 10.0, 130.0, 70.0),
        detection_confidence=0.9, plate=plate, plate_raw=plate,
        plate_confidence=0.85 if plate else None, plate_votes=3 if plate else 0,
        colour=colour, colour_confidence=0.7 if colour else None,
        observation_quality=quality, plate_pixel_width=110.0 if plate else None,
        sharpness=60.0, luminance=120.0, source_quality=quality,
        source_grade="B", lat=lat, lon=lon,
        model_versions={"detector": "test", "ocr": "test"})
