"""The Investigate view answers the Step 4 test case, not just the search.

Three failures an officer met in a rehearsal on the real store, each driven
again in a browser after this change at 1366x768:

  GJ18X6705 (on the stolen list)  -> red "ON WATCHLIST · STOLEN VEHICLE · HIGH",
                                     "14 open alerts", latest on cam06, in IST.
  GJ01ZZ9999 (never seen)         -> "no sighting on any of the 24 cameras in
                                     your jurisdiction", with next steps; the
                                     previous vehicle's route is gone.
  GJ18X67 (a witness's fragment)  -> finds GJ18X6705, flagged WATCHLIST.
"""
from __future__ import annotations

from pathlib import Path

APP = (Path(__file__).resolve().parents[2] / "ui/app.js").read_text(encoding="utf-8")


def _handler() -> str:
    return APP[APP.index('$("#search-form").addEventListener("submit"'):
               APP.index("function renderSearchError")]


def test_a_new_search_clears_the_previous_vehicle_first() -> None:
    h = _handler()
    assert "resetInvestigation(plate)" in h
    assert h.index("resetInvestigation(plate)") < h.index("await api(`/search?"), (
        "the reset must happen before the new answer arrives, or the old route "
        "is on screen while the new search runs")
    block = APP[APP.index("function resetInvestigation"):APP.index("function wlLabel")]
    for gone in ('"#traj-body"', '"#detail"', "map1.selected = null", '"trajectory", null'):
        assert gone in block, f"reset leaves {gone} behind"


def test_every_plate_search_says_whether_the_vehicle_is_wanted() -> None:
    h = _handler()
    assert "renderTargetCard(res)" in h
    card = APP[APP.index("function renderTargetCard"):APP.index("function renderNoSighting")]
    assert "ON WATCHLIST" in card
    assert "Not on any active watchlist" in card, (
        "a plate that is not listed must say so, with when it was checked")
    assert "open_alerts" in card


def test_a_plate_nobody_has_seen_gets_an_answer_and_next_steps() -> None:
    h = _handler()
    assert "renderNoSighting(res" in h
    panel = APP[APP.index("function renderNoSighting"):APP.index("function renderPatternResults")]
    for action in ("near matches", "partial plate", "time range", "Alert me"):
        assert action in panel, f"no-sighting panel lacks the '{action}' step"


def test_partial_plates_render_as_marks_character_by_character() -> None:
    h = _handler()
    assert '"plate_pattern"' in h and "renderPatternResults(res)" in h
    block = APP[APP.index("function renderPatternResults"):APP.index("window.SK_openInvestigation")]
    # the backend's CharMatch.to_dict() shape, not a guessed one
    assert "cm.ch" in block and "cm.kind" in block
    assert "x.pattern || x.raw" in block


def test_the_purpose_rule_is_stated_where_the_refusal_is_shown() -> None:
    """An officer filled both fields and was refused without being told why."""
    err = APP[APP.index("function renderSearchError"):APP.index("function renderResults")]
    assert "12 characters" in err


def test_alerts_can_open_an_investigation_without_a_raw_refusal() -> None:
    block = APP[APP.index("window.SK_openInvestigation"):]
    block = block[:block.index("};") + 2]
    assert "#case-id" in block and "#purpose" in block
    assert "< 12" in block, "the generated purpose must meet the 12-character rule"
