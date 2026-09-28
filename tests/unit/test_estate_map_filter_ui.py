"""The estate map's "search camera" box is wired, and filters without hiding.

It shipped as a bare input with no handler: typing into it did nothing.
"""
from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "ui"


def test_search_camera_box_has_a_handler():
    app = (UI / "app.js").read_text(encoding="utf-8")
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'id="map-filter-q"' in html
    assert '$("#map-filter-q")' in app and 'addEventListener("input"' in app
    assert "mapFilterQ = filterBox.value.trim().toLowerCase()" in app


def test_filter_matches_registry_fields_and_asks_for_every_camera():
    app = (UI / "app.js").read_text(encoding="utf-8")
    assert "[c.camera_id, c.name, c.district, c.department, c.site]" in app
    # A filtered map drops the viewport bbox and clustering, so a match
    # cannot be hidden off screen or inside a cluster.
    assert 'const filtering = map === map2 && !!mapFilterQ;' in app
    assert 'if (bbox && !filtering)' in app
    assert 'q.set("zoom", filtering ? "16" : String(Math.round(map.zoom)));' in app
    # The registry strip says it is filtered rather than reporting a smaller estate.
    assert "cameras match “${mapFilterQ}”" in app


def test_alert_layer_forbidden_to_the_role_is_empty_not_an_error():
    """ADMIN holds no alert:read; the estate map must not toast that as a failure."""
    app = (UI / "app.js").read_text(encoding="utf-8")
    block = app[app.index("async function refreshMapLayers"):]
    block = block[:block.index("\nfunction wireMapControls")]
    assert "if (err.status !== 403) throw err;" in block
    assert block.index("/gis/alerts") < block.index("if (err.status !== 403) throw err;")
