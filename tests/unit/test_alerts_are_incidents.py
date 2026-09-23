"""The Alerts view shows the vehicles, not the rows.

On the evaluation store 126 open alert rows were thirteen vehicles, every one
printed HIGH, and the view showed the first twelve rows - so an in-charge saw
one vehicle twelve times and never reached the other twelve. Driven in a
browser at 1366x768 on a copy of the live store after this change: "126 alerts
· 13 vehicles", thirteen incident cards, each with its sealed still.
"""
from __future__ import annotations

from pathlib import Path

APP = (Path(__file__).resolve().parents[2] / "ui/app.js").read_text(encoding="utf-8")
SLOT = APP[APP.index("/* ═══ SLOT S2"):APP.index("/* ═══ END SLOT S2 ═══ */")]


def test_the_queue_asks_for_incidents() -> None:
    assert "/alerts?grouped=true" in SLOT
    assert "`/alerts?status=${alertStatus}&limit=200`" not in APP, (
        "the row-by-row loader is still defined and may be edited by mistake")


def test_each_incident_sets_the_read_against_the_listed_plate() -> None:
    assert "function readVsList" in SLOT
    assert "✓ EXACT" in SLOT and "≈ NEAR" in SLOT


def test_the_thumbnail_is_the_full_sealed_frame_not_a_mismatched_crop() -> None:
    """The stored box and the sealed still come from different moments of a
    pass; the crop showed empty road captioned as the vehicle."""
    # Check the request, not the comment that explains why it changed.
    assert "frame.jpg?crop=full" in SLOT
    assert "frame.jpg?crop=vehicle" not in SLOT


def test_one_decision_applies_to_every_read_of_the_vehicle() -> None:
    assert '"/alerts/transition"' in SLOT
    assert "alert_ids: g.alert_ids" in SLOT


def test_resolving_requires_a_disposition_and_a_reason() -> None:
    block = SLOT[SLOT.index("function resolveForm"):SLOT.index("function friendlyError")]
    for d in ("confirmed", "false_positive", "cleared"):
        assert d in block
    assert "why.value.trim().length < 4" in block


def test_investigate_opens_the_vehicle_instead_of_a_raw_refusal() -> None:
    assert "window.SK_openInvestigation" in SLOT


def test_keyboard_triage_ignores_typing() -> None:
    block = SLOT[SLOT.index('document.addEventListener("keydown"'):]
    assert '"input", "textarea", "select"' in block
    assert 'classList.contains("active")' in block


def test_zero_is_a_true_answer_on_the_overview() -> None:
    """`hour.distinct || distinct_plates` printed the all-time total (178)
    under "last hour" whenever the last hour was genuinely empty."""
    assert "hour.distinct || o.observations.distinct_plates" not in APP
    assert "hour.distinct ?? 0" in APP


def test_withheld_alerts_never_print_null() -> None:
    """Roles that may not read alerts get `open: null`; String(null) is 'null'."""
    assert "String(o.alerts.open)" not in APP
    assert "o.alerts.withheld" in APP
