"""Model 1's "role-based search, filtering, export" reaches the portal.

The estate table listed measured capability and none of the registry metadata
an integrator acts on — which VMS a feed must be integrated through, how long
its footage survives — and offered no way to narrow fifty-eight rows. Those
are the same fields /gis/gaps reports as unsupplied, so the portal named a
problem it gave nobody the means to inspect.

Driven in a browser against a copy of the live store: 58 rows, search
"panchayat" showed 8, department "Home (Police)" showed 33, and the
missing-metadata filter showed 56 — which agrees with the gap report's 94%.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "ui/app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "ui/index.html").read_text(encoding="utf-8")
SERVICE = (ROOT / "src/saakshya/gis/service.py").read_text(encoding="utf-8")


def test_the_capability_payload_carries_the_registry_metadata() -> None:
    """Filtering by VMS is impossible if the API never sends it."""
    block = SERVICE[SERVICE.index("feats.append({"):
                    SERVICE.index('"bands": [')]
    for field in ("department", "vms", "vendor", "camera_type",
                  "storage_location", "retention_days"):
        assert f'"{field}"' in block, f"capability features omit {field}"


def test_the_gap_report_fields_are_the_filterable_fields() -> None:
    """The registry must be inspectable along the axis it reports as missing."""
    for field in ("vms", "storage_location", "retention_days", "vendor",
                  "camera_type"):
        assert f'"{field}"' in APP, f"{field} is not part of the UI filter"


def test_search_covers_the_columns_an_operator_would_type() -> None:
    block = APP[APP.index("function regRowMatches"):APP.index("function applyRegFilter")]
    for field in ("camera_id", "name", "department", "district", "vms", "vendor"):
        assert f'"{field}"' in block, f"free-text search ignores {field}"


def test_a_filtered_table_states_both_numbers() -> None:
    """Showing 8 of 58 rows without the denominator reads as an estate of 8."""
    block = APP[APP.index("function applyRegFilter"):APP.index("function populateRegFilters")]
    assert "of ${total} rows" in block


def test_absence_is_rendered_rather_than_blanked() -> None:
    """A registry distinguishes "nobody told us" from "nothing to tell".

    An empty cell says neither, and this platform's entire argument is that an
    unknown is a first-class answer.
    """
    assert "function metaCell" in APP
    block = APP[APP.index("function metaCell"):APP.index("const regFilter")]
    assert "not supplied" in block
    assert "/registry/cameras/import" in block, (
        "the empty-state does not say how the field would be supplied")


def test_the_filter_offers_the_estate_its_own_values() -> None:
    """Typing a department by hand is how near-duplicates get created."""
    assert "function populateRegFilters" in APP
    assert 'id="reg-dept"' in INDEX and 'id="reg-district"' in INDEX


def test_the_filters_can_be_cleared() -> None:
    assert 'id="btn-reg-clear"' in INDEX
    assert "btn-reg-clear" in APP


def test_the_search_field_is_labelled_for_a_screen_reader() -> None:
    block = INDEX[INDEX.index('class="reg-filter"'):INDEX.index('id="cameras"')]
    assert "sr-only" in block or "aria-label" in block
    for sel in ('id="reg-dept"', 'id="reg-district"', 'id="reg-anpr"'):
        i = block.index(sel)
        assert "aria-label" in block[i - 120:i + 120], f"{sel} has no label"
