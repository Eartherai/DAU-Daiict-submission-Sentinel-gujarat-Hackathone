"""Basemap config: Google Maps key wins; tiles are the no-key fallback."""
from types import SimpleNamespace

from saakshya.api.routes_ops import _map_public_config


def test_google_key_is_the_basemap_and_hides_raster_tiles():
    state = SimpleNamespace(
        google_maps_key="AIza-test-not-a-real-key",
        tile_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_attribution="© OpenStreetMap contributors")
    cfg = _map_public_config(state)
    assert cfg["google"]["enabled"] is True
    assert cfg["google"]["key"] == "AIza-test-not-a-real-key"
    assert cfg["tiles"] is False
    assert cfg["template"] is None


def test_raster_tiles_when_no_google_key():
    state = SimpleNamespace(
        google_maps_key="",
        tile_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_attribution="© OpenStreetMap contributors")
    cfg = _map_public_config(state)
    assert cfg["google"]["enabled"] is False
    assert cfg["google"]["key"] is None
    assert cfg["tiles"] is True
    assert "openstreetmap" in cfg["template"]


def test_graticule_when_nothing_configured():
    state = SimpleNamespace(
        google_maps_key="", tile_template="", tile_attribution="")
    cfg = _map_public_config(state)
    assert cfg["google"]["enabled"] is False
    assert cfg["tiles"] is False
    assert "graticule" in cfg["note"]
