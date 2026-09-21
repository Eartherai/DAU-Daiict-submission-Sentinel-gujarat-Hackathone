"""Basemap config: Google Maps enabled without publishing the key."""
from types import SimpleNamespace

from saakshya.api.routes_ops import _map_public_config


def test_google_enabled_does_not_publish_key():
    state = SimpleNamespace(
        google_maps_key="test-maps-key-not-real",
        tile_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_attribution="© OpenStreetMap contributors")
    cfg = _map_public_config(state)
    assert cfg["google"]["enabled"] is True
    assert cfg["google"]["key"] is None
    assert cfg["google"]["loader"] == "/maps/google-api"
    assert "test-maps-key-not-real" not in str(cfg)
    assert cfg["tiles"] is True
    assert "openstreetmap" in (cfg["template"] or "")


def test_raster_tiles_when_no_google_key():
    state = SimpleNamespace(
        google_maps_key="",
        tile_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_attribution="© OpenStreetMap contributors")
    cfg = _map_public_config(state)
    assert cfg["google"]["enabled"] is False
    assert cfg["google"]["key"] is None
    assert cfg["google"]["loader"] is None
    assert cfg["tiles"] is True
    assert "openstreetmap" in cfg["template"]


def test_appstate_skips_maps_key_when_disabled(monkeypatch):
    from saakshya.api.deps import AppState, _load_google_maps_key

    monkeypatch.setenv("SAAKSHYA_GOOGLE_MAPS_DISABLE", "1")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-maps-key-not-real")
    assert _load_google_maps_key() == ""
    assert AppState().google_maps_key == ""


def test_live_note_proxy_describes_on_demand_single_camera(monkeypatch):
    from saakshya.api.routes_ops import _live_note

    monkeypatch.setattr("saakshya.api.routes_ops._whep_proxy_ready",
                        lambda state: True)
    note = _live_note(SimpleNamespace(whep_base=""))
    assert "on-demand" in note.lower()
    assert "one verified whep session" in note.lower()
    assert "every wall tile" in note.lower()


def test_graticule_when_nothing_configured():
    state = SimpleNamespace(
        google_maps_key="", tile_template="", tile_attribution="")
    cfg = _map_public_config(state)
    assert cfg["google"]["enabled"] is False
    assert cfg["tiles"] is False
    assert "graticule" in cfg["note"]
