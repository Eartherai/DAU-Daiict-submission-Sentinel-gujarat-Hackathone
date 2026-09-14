"""Feed health must not call a camera with observations 'never ingested'."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from saakshya.api.routes_system import _feed_health
from saakshya.store import Store, VehicleObservation

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)


def _store() -> Store:
    s = Store("sqlite:///:memory:")
    s.create_all()
    for i, cid in enumerate(["C-014", "C-021", "C-033", "C-047"]):
        s.upsert_camera({"camera_id": cid, "name": f"cam {i}",
                         "district": "Ahmedabad", "department": "Test",
                         "lat": 23.0 + i, "lon": 72.0 + i})
    return s


def _obs(cam: str, sec: int) -> VehicleObservation:
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(
        camera_id=cam, pts_s=float(sec), t_norm=t, t_ingest=t,
        dedup_key=f"{cam}:SEG1:{sec}", plate=None, object_type="car")


def test_observed_camera_ids_ignore_health_rows():
    store = _store()
    store.add_observations([_obs("C-014", 1), _obs("C-021", 2)])
    assert store.observed_camera_ids() == {"C-014", "C-021"}
    assert store.list_health() == {}


def test_missing_health_with_observations_is_not_never_ingested():
    store = _store()
    store.add_observations([_obs("C-014", 1)])
    h = _feed_health(SimpleNamespace(store=store))
    assert "never ingested" not in h["detail"]
    assert h["health_pending"] == 1
    assert h["never_ingested"] == 3
    assert "observations" in h["detail"]


def test_health_pending_is_not_called_never_ingested():
    """The live-store shape: some leftover health rows, observations on all."""
    store = _store()
    store.upsert_health("C-014", {"state": "STREAMING", "decoder_errors": 2})
    store.upsert_health("C-021", {"state": "STREAMING", "decoder_errors": 0})
    store.add_observations([_obs("C-014", 1), _obs("C-021", 2),
                            _obs("C-033", 3), _obs("C-047", 4)])
    h = _feed_health(SimpleNamespace(store=store))
    assert "never ingested" not in h["detail"]
    assert h["health_pending"] == 2
    assert h["never_ingested"] == 0
    assert "no health row" in h["detail"]


def test_true_absence_is_still_named():
    store = _store()
    store.upsert_health("C-014", {"state": "STREAMING"})
    h = _feed_health(SimpleNamespace(store=store))
    assert h["never_ingested"] == 3
    assert "neither observations nor a health row" in h["detail"]


def test_grid_access_is_degraded_when_the_grid_refused_every_camera(monkeypatch):
    from saakshya.api.routes_system import _grid_access_health
    monkeypatch.setenv("SENTINEL_GRID_EMAIL", "officer@example.gov.in")
    monkeypatch.setenv("SENTINEL_GRID_PASSWORD", "not-a-real-key")
    store = _store()
    for cid in ("C-014", "C-021", "C-033", "C-047"):
        store.upsert_health(cid, {
            "state": "STREAMING",
            "last_error": "HTTPUnauthorizedError: Server returned 401 Unauthorized",
        })
    h = _grid_access_health(SimpleNamespace(store=store))
    assert h["state"] == "DEGRADED"
    assert "401" in h["detail"]
