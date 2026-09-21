"""The two named Model 1 / Model 4 report deliverables.

Both are generated from real data rather than written, so they cannot drift
from what the platform holds. These tests pin the properties that make them
worth submitting: the figures come from the store, and the reports state their
own limits rather than implying statewide readiness from registry rows.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reports"))

from saakshya.gis.service import MapService
from saakshya.store.repository import Store


def _store(tmp_path, name="rep.db"):
    store = Store(f"sqlite:///{tmp_path / name}")
    store.create_all()
    return store


def test_gap_report_names_absent_departments(tmp_path):
    from gap_analysis import render

    store = _store(tmp_path)
    store.upsert_camera({"camera_id": "cam01", "name": "one",
                         "department": "Home (Police)",
                         "lat": 23.0, "lon": 72.5})
    text = render(MapService(store).registry_gaps(), "sqlite:///x")
    assert "Health" in text and "Municipal Corporation" in text
    # It must say what an absence means, not just print a number.
    assert "not a field the" in text or "not errors" in text.lower()


def test_gap_report_states_a_gap_is_not_a_platform_limit(tmp_path):
    from gap_analysis import render

    store = _store(tmp_path, "limits.db")
    store.upsert_camera({"camera_id": "cam01", "name": "one"})
    text = render(MapService(store).registry_gaps(), "sqlite:///x")
    assert "exists in the schema" in text


def test_gap_report_counts_come_from_the_store(tmp_path):
    from gap_analysis import render

    store = _store(tmp_path, "counts.db")
    for i in range(3):
        store.upsert_camera({"camera_id": f"cam{i:02d}", "name": str(i)})
    gaps = MapService(store).registry_gaps()
    text = render(gaps, "sqlite:///x")
    assert str(gaps["cameras"]) in text


def test_scale_report_refuses_to_imply_statewide_readiness():
    """Registry rows say nothing about video or inference."""
    from scale_load_test import render

    text = render({
        "n": 80_000, "onboard_s": 1.26, "rate": 63_540, "gaps_ms": 168.2,
        "gaps_counted": 80_000, "capability_ms": 262.9, "viewport_ms": 377.8,
        "viewport_features": 1665, "lookup_ms": 0.65, "filter_ms": 645.2,
        "filter_rows": 80_000, "db_mb": 28.7,
    })
    assert "What this does not prove" in text
    for plane in ("Video plane", "AI plane", "Storage"):
        assert plane in text
    # And it must not claim the PostgreSQL migration it has not run.
    # Normalised: the sentence wraps, so a literal match would be brittle.
    flat = " ".join(text.split())
    assert "has not been exercised here and should not be claimed" in flat


def test_scale_report_reports_the_measured_numbers():
    from scale_load_test import render

    text = render({
        "n": 80_000, "onboard_s": 1.26, "rate": 63_540, "gaps_ms": 168.2,
        "gaps_counted": 80_000, "capability_ms": 262.9, "viewport_ms": 377.8,
        "viewport_features": 1665, "lookup_ms": 0.65, "filter_ms": 645.2,
        "filter_rows": 80_000, "db_mb": 28.7,
    })
    assert "80,000" in text and "63,540" in text and "0.65 ms" in text


def test_the_load_test_actually_loads(tmp_path):
    """A load test that does not load is a document, not a test."""
    from scale_load_test import run

    r = run(2_000)
    assert r["n"] == 2_000
    assert r["gaps_counted"] == 2_000, "the report must count every camera"
    assert r["onboard_s"] > 0 and r["lookup_ms"] >= 0
    assert r["db_mb"] > 0, "a load test that writes nothing measured nothing"
