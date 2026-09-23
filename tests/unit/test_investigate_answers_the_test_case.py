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
    assert "ensurePurpose(" in block
    helper = APP[APP.index("function ensurePurpose"):]
    helper = helper[:helper.index("\n}\n") + 3]
    assert "#case-id" in helper and "#purpose" in helper
    assert "< 12" in helper, "the generated purpose must meet the 12-character rule"
    # The boxes listen for `input`; dispatching `change` filled them without
    # committing, and the request went out unbound. Commit directly.
    assert "syncPurpose()" in helper


def test_purpose_headers_survive_characters_outside_latin_1() -> None:
    """A default purpose with an em dash made fetch() throw before sending."""
    block = APP[APP.index("function authHeaders"):]
    block = block[:block.index("\n}\n") + 3]
    assert "encodeURIComponent(state.purpose)" in block
    assert '"X-Purpose-Encoding"' in block


def test_the_header_keeps_the_purpose_usable_on_a_1366_laptop() -> None:
    """Measured at 1366x768 after the change: status chips on one row, the
    Purpose field 188 px wide and fully on screen, content starting ~100 px
    higher. Before it, five chips stacked into a column one chip wide and
    covered the Purpose field every vehicle search requires."""
    css = (Path(__file__).resolve().parents[2] / "ui/style.css").read_text(encoding="utf-8")
    # Several 1440px blocks exist; take the one that shapes the header.
    blocks = [b for b in css.split("@media (max-width: 1440px)")[1:]]
    block = next((b[:b.index("\n}\n") + 3] for b in blocks if ".topbar" in b[:b.index("\n}\n")]), "")
    assert block, "no 1440px rule shapes the header"
    assert "flex-wrap: wrap" in block, "the header cannot become two rows"
    assert "min-width: 360px" in block, "the purpose bar may still shrink to nothing"
    assert "flex-wrap: nowrap" in block, "status chips may stack into a column again"


def test_deployment_plumbing_is_folded_away_from_the_officer() -> None:
    html = (Path(__file__).resolve().parents[2] / "ui/index.html").read_text(encoding="utf-8")
    det = html[html.index('id="deploy-details"'):html.index("</details>")]
    for ind in ("feed-government", "feed-own", "feed-central"):
        assert ind in det, f"{ind} is outside the disclosure"


def test_follow_vehicle_counts_confirmed_as_agreed_across_frames() -> None:
    """'7 confirmed sighting(s)' was printed for seven single-frame leads."""
    src = (Path(__file__).resolve().parents[2]
           / "src/saakshya/investigation/workspace.py").read_text(encoding="utf-8")
    block = src[src.index("def follow_vehicle"):src.index("def next_best_cameras")]
    assert '"confirmed_sightings": corroborated' in block
    assert '(r.get("plate_votes") or 0) >= 2' in block
    search = (Path(__file__).resolve().parents[2]
              / "src/saakshya/intelligence/search.py").read_text(encoding="utf-8")
    assert '"plate_votes": o.plate_votes' in search


def test_a_listed_near_match_is_said_first() -> None:
    """GJ18JX7787 with near matches returned seven reads of the listed stolen
    GJ18JX7786 under 'Not on any active watchlist'."""
    src = (Path(__file__).resolve().parents[2]
           / "src/saakshya/investigation/workspace.py").read_text(encoding="utf-8")
    assert 'payload["near_match_watchlist"] = near' in src
    block = APP[APP.index("function renderTargetCard"):APP.index("function renderNoSighting")]
    assert "near_match_watchlist" in block and "IS ON WATCHLIST" in block
    assert "Trace ${n.plate}" in block
