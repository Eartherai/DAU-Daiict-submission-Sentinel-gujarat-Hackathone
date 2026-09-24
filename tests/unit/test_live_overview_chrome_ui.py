"""Live wall, Overview and command-mode chrome say what is true.

Reviewers using the app as officers found the wall and the landing page lying
by omission: a failed load turned into "0 government cameras indexed" over a
blank wall after one click, the Overview was a single red line with no way
forward, the icon rail printed letter fragments and stayed on for every later
view, and a Domain toggle navigated away while staying lit. Each was driven in
a browser at 2560x1440 and 1366x768 on a copy of the film store after the fix.
There is no JS runner in this repo, so the contract is pinned against ui/.
"""
from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "ui"
APP = (UI / "app.js").read_text(encoding="utf-8")
HTML = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")


def _fn(name: str, src: str = APP) -> str:
    """The body of a top-level function, up to the next top-level item."""
    start = src.index(f"function {name}(")
    end = re.compile(r"\n(?:async function |function |\$\$?\(|let |const |loaders\.)").search(
        src, start + 10)
    return src[start:end.start() if end else len(src)]


def _live_loader() -> str:
    start = APP.index("loaders.live = async () => {")
    return APP[start:APP.index("\n};\n", start)]


# ─── command mode belongs to the wall ────────────────────────────────────

def test_command_mode_is_only_on_while_live_is_the_active_view() -> None:
    """Visiting Live once left Evidence and Audit on the icon rail with the
    handling band gone."""
    chrome = _fn("applyCommandChrome")
    assert 'const onLive = !!$("#view-live")?.classList.contains("active");' in chrome
    assert 'toggle("wall-focus", onLive && !commandBarOpen)' in chrome
    leaving = APP[APP.index('  if (view !== "live") {'):APP.index("  } else {", APP.index('  if (view !== "live") {'))]
    assert "applyCommandChrome();" in leaving


def test_icon_rail_collapses_the_sub_links_and_pins_the_health_dot() -> None:
    assert "body.wall-focus .nav .sub-nav {" in CSS or "body.wall-focus .nav .sub-nav," in CSS
    rail = CSS[CSS.index("body.wall-focus .nav .primary-nav,"):]
    assert "font-size: 0" in rail[:200]
    assert "body.wall-focus .nav .sub-nav .count" in CSS
    assert "body.wall-focus .nav .dot { position: absolute;" in CSS


def test_command_bar_on_a_laptop_keeps_the_chrome_bands_collapsed() -> None:
    assert 'toggle("wall-bar", onLive && commandBarOpen)' in APP
    block = CSS[CSS.index("@media (max-width: 1399px) {\n  body.wall-bar"):]
    block = block[:block.index("\n}\n")]
    assert "body.wall-bar .handling" in block and "body.wall-bar .product-modes" in block
    assert "grid-template-rows: minmax(54px, auto) 0 0 1fr" in block


# ─── the wall's status line and tiles ────────────────────────────────────

def test_wall_status_line_is_not_capped_at_46_characters() -> None:
    assert "max-width: 46ch" not in CSS
    assert "node.title = node.textContent;" in _fn("renderLiveCount")
    assert "box.title = box.textContent;" in _fn("liveProgress")


def test_thirty_wall_tiles_anchor_their_overlaid_head_and_foot() -> None:
    """Only Dense tiles were positioned, so on the default Grid wall all thirty
    tile heads stacked over the wall's status line."""
    assert '#live[data-wall="30"] .live-tile { position: relative; }' in CSS


def test_missing_grid_credential_is_not_called_a_busy_grid() -> None:
    assert '(err.why || "").includes("no credential is configured")' in APP
    assert "&& !unpublished && !noCredential" in APP


# ─── failure and empty states ────────────────────────────────────────────

def test_a_failed_wall_load_is_kept_and_shown_with_retry() -> None:
    loader = _live_loader()
    assert "liveLoadError = err;" in loader
    assert "box.append(liveFailureNotice(err));" in loader
    assert "`${err.code}: ${err.message}`" not in loader
    notice = _fn("liveFailureNotice")
    assert '"Retry"' in notice and "loaders.live()" in notice
    # The simulation disclosure survives the rewrite.
    assert "LIVE SIMULATION / ARCHIVAL REPLAY is not available here." in notice


def test_wall_size_and_priority_reload_instead_of_repainting_a_failure() -> None:
    repaint = _fn("repaintLiveWall")
    assert "if (liveLoadError) { loaders.live(); return; }" in repaint
    for attr in ("data-live-wall", "data-live-priority"):
        start = APP.index(f'$$("[{attr}]").forEach((b) => b.addEventListener("click"')
        handler = APP[start:APP.index("}));", start)]
        assert "repaintLiveWall();" in handler, attr
        assert "paintLiveWorkspace(liveCamsAll)" not in handler, attr


def test_an_empty_wall_says_why_it_is_empty() -> None:
    assert "if (!cams.length) box.prepend(liveEmptyNotice());" in _fn("paintLiveWorkspace")
    empty = _fn("liveEmptyNotice")
    assert "if (liveLoadError) return liveFailureNotice(liveLoadError);" in empty
    assert "No camera on this wall matches" in empty
    assert "No government camera is indexed in this store." in empty


def test_overview_failure_offers_retry_and_keeps_what_loaded() -> None:
    assert 'api("/overview").catch((err) => err),' in APP
    assert "await paintOverviewFailure(box, err, marksPay);" in APP
    page = _fn("paintOverviewFailure")
    assert '"Retry"' in page and "loaders.overview()" in page
    assert '"/alerts?status=OPEN&limit=4"' in page
    assert "dutyBrief()" in page and "plateCard" in page


# ─── controls ────────────────────────────────────────────────────────────

def test_wall_sizes_are_in_order() -> None:
    sizes = [int(n) for n in re.findall(r'data-live-wall="(\d+)"', HTML)]
    assert sizes == sorted(sizes) == [4, 9, 12, 16, 25, 30, 50]


def test_simulation_domain_is_offered_only_when_the_plane_runs() -> None:
    button = re.search(r'<button[^>]*data-live-domain="simulation"[^>]*>', HTML, re.S)
    assert button and " hidden" in button.group(0)
    assert "if (simButton) simButton.hidden = !state.simulationConfig.available;" in APP


def test_domain_group_only_changes_the_wall() -> None:
    """INTELLIGENCE DEMO as a Domain toggle moved the officer to another page
    and stayed lit over the government wall."""
    assert 'data-live-domain="intelligence"' not in HTML
    assert "syncLiveDomainButtons();" in _live_loader()
    start = APP.index('$$("[data-live-domain]").forEach((b) => b.addEventListener("click"')
    handler = APP[start:APP.index("}));", start)]
    assert 'show("intelligence")' not in handler


def test_presets_do_not_repeat_the_domain_buttons() -> None:
    presets = re.findall(r'data-preset="([^"]+)"', HTML)
    assert "government" not in presets
    assert len(presets) == len(set(presets))
    spec = APP[APP.index('$$("[data-preset]")'):APP.index("}[id];")]
    for pid in presets:
        assert f'"{pid}": {{' in spec, f"preset button {pid} has no spec"
    assert '"government": { wall: 30' not in spec


def test_masthead_search_promises_only_what_it_does() -> None:
    """The box runs a vehicle search; it offered cameras and cases too."""
    assert 'placeholder="Search a plate"' in HTML
    assert "Search cameras, plates, cases" not in HTML


def test_mark_without_a_still_is_a_compact_card() -> None:
    card = _fn("plateCard")
    assert 'showStill ? el("div", { class: "still" }, img) : null' in card
    assert "still.replaceChildren(plateRead(m.plate))" not in card
    assert ".plate-card .still > .plate-read" not in CSS
    assert "display: flex; flex-direction: column; justify-content: flex-start;" in CSS
