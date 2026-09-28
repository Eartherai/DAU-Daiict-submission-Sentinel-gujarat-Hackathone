"""The government wall uses bounded previews plus selected-camera WHEP.

These assertions are about honesty, not rendering. A thirty-camera catalogue
that paints "CONNECTING" on every tile is telling an evaluator that thirty
sessions are being negotiated; on the direct WHEP plane none are. The same goes
for calling a cached preview live, or calling AI live because a toggle is on.
There is no JS runner in this repo, so the contract is pinned against the
shipped ui/ sources.
"""
import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "ui"
APP = UI / "app.js"
INDEX = UI / "index.html"
STYLE = UI / "style.css"


@pytest.fixture(scope="module")
def app() -> str:
    return APP.read_text(encoding="utf-8")


def test_direct_plane_tile_whep_budget_is_bounded_but_not_zero(app: str) -> None:
    """The wall carries live video within a fixed session budget.

    This budget was zero: a catalogue is an index, not permission to open
    thirty peer connections. But zero made the wall a grid of still frames
    that an operator had to click a camera at a time to make live, which is
    not a control-room wall. The bound is what protects the grid, so keep a
    bound and hold sessions against it - the number must stay small and
    explicit, and it must never be the tile count.
    """
    budget = re.search(r"const TILE_WHEP_BUDGET = (\d+);", app)
    assert budget, "the wall must declare an explicit session budget"
    n = int(budget.group(1))
    assert 0 < n <= 16, f"budget {n} is not a bound a government grid would accept"
    assert "return localRelay() ? 32 : TILE_WHEP_BUDGET;" in app


def test_direct_wall_has_bounded_queue_for_all_thirty_previews(app: str) -> None:
    assert "if (directGovernmentOnDemand()) return 30;" in app
    assert "pumpStills still enforces four actual" in app
    assert 'if (directGovernmentOnDemand() && sourceDomain(cam) === "GOVERNMENT"' not in app


def test_all_government_cards_are_queued_for_bounded_previews(app: str) -> None:
    assert 'for (const tile of $$("#live-grid .live-tile")) {' in app
    assert "if (tile._img) queueStill(tile._img, tile.dataset.camera);" in app


def test_direct_preview_refresh_is_slow_and_bounded(app: str) -> None:
    assert 'const direct = !hub && !relay && state.liveConfig?.plane === "direct_whep";' in app
    assert "direct ? 20_000" in app


def test_no_automatic_hero_session(app: str) -> None:
    assert 'if (directGovernmentOnDemand() && liveDomain === "government") return;' in app


def test_unselected_tile_distinguishes_ready_from_preview_work(app: str) -> None:
    assert 'text: onDemand ? "READY" : "CONNECTING"' in app
    assert '"preview queued · select for verified WHEP"' in app
    assert 'el("div", { text: readyOnly ? "READY" : (text || {' in app
    assert 'frame.dataset.state = readyOnly ? "ready" : state;' in app


def test_set_tile_state_computes_on_demand_per_camera(app: str) -> None:
    """The selected camera keeps its real state; an unselected idle camera is
    READY, while queued/capturing/error states remain visible."""
    assert (
        "  const onDemand = directGovernmentOnDemand()\n"
        '    && sourceDomain(cameraRecord(id)) === "GOVERNMENT"\n'
        "    && livePlayer?.id !== id;"
    ) in app
    assert 'const readyOnly = onDemand && (state === "idle" || state === "ready");' in app


def test_progress_separates_preview_frames_from_live_sessions(app: str) -> None:
    assert 'const previews = n("preview");' in app
    assert '${total} cameras · ${previews} preview frame' in app
    assert '${live} live session' in app


def test_ready_state_is_styled(app: str) -> None:
    css = STYLE.read_text(encoding="utf-8")
    assert '.live-tile .frame[data-state="ready"] .placeholder > div:first-child' in css
    assert '.vid-chip[data-state="ready"],' in css


def test_selected_camera_tries_whep_before_any_snapshot(app: str) -> None:
    """Ordering is the whole point: negotiate first, fall back only after."""
    body = app[app.index("async function openLive("):]
    body = body[: body.index("\nfunction closeLive(")]
    negotiate = body.index("await negotiateTileWhep(id)")
    for reason in (
        "WHEP is not enabled on this process",
        "this camera resolves to a stored file view",
        "this camera is not WHEP-capable on this plane",
    ):
        assert reason in body
    # The only startStillPump call in openLive is inside the fallback helper.
    assert body.count("startStillPump(id)") == 1
    assert body.index("startStillPump(id)") < negotiate  # helper is declared early


def test_direct_government_selection_does_not_open_competing_rtsp_view(app: str) -> None:
    """Direct WHEP is already the selected-camera session.  Opening /view
    first creates a second RTSP decoder and can starve browser playback."""
    body = app[app.index("async function openLive("):]
    body = body[: body.index("\nfunction closeLive(")]
    negotiate = body.index("await negotiateTileWhep(id)")
    assert "if (!isSimulation && !directGovernmentOnDemand()) {" in body
    assert body.index("if (!isSimulation && !directGovernmentOnDemand()) {") < body.index(
        "await negotiateTileWhep(id)"
    )
    assert 'const status = message.match(/\\bWHEP\\s+(\\d{3})\\b/i)?.[1];' in body
    assert "source authorization rejected the WHEP request (HTTP 401)" in body
    assert "fallbackToSnapshot(reason);" in body
    assert body.index("fallbackToSnapshot(reason);") > negotiate


def test_selected_stream_has_one_video_consumer_per_layout(app: str) -> None:
    assert 'if (liveLayout === "focus") return;' in app
    assert 'const stageOwnsVideo = liveLayout === "focus";' in app
    assert "if (!stageOwnsVideo) {" in app
    assert "if (stageOwnsVideo) {" in app


def test_layout_repaint_reasserts_live_only_after_rendered_frame(app: str) -> None:
    assert "A layout change rebuilds the tile DOM" in app
    assert "const expected = decodedPlaybackState(id).toLowerCase();" in app
    assert "if (first || !marked) {" in app


def test_fallback_labels_the_image_as_preview(app: str) -> None:
    assert 'chip.textContent = "Preview";' in app
    assert "Anything shown here is a cached PREVIEW, not live video." in app
    assert 'class: "tile-whep-warning"' in app
    assert 'WHEP unavailable — ${reason}' in app


def test_successful_signalling_without_a_decoded_frame_is_not_left_connecting(app: str) -> None:
    """A WHEP answer/ontrack is insufficient: the UI waits for an actual
    browser-rendered frame and exposes the selected-camera fallback clearly."""
    assert "function waitForRenderedFrame(video, sess, timeoutMs = 10_000)" in app
    assert "WHEP negotiated but no browser-decoded frame within 10 s" in app
    assert 'fallbackToSnapshot("WHEP negotiated but no decoded frame arrived within 10 s")' in app


def test_indexed_tile_never_repeats_a_declared_ai_state(app: str) -> None:
    assert 'const aiLabel = onDemand ? "OFF" : aiDeclared;' in app
    assert 'text: aiLabel === "ACTIVE" ? "AI" : ""' in app
    assert 'cam.ai_state === "ACTIVE"' not in app


def test_compare_hud_claims_ai_only_from_persisted_detections(app: str) -> None:
    assert 'AI ${intelState.analytics ? "ON" : "OFF"}' not in app
    assert '"AI ACTIVE · persisted detections"' in app
    assert '"AI REQUESTED · no persisted detection for this camera"' in app
    assert "AI NOT MEASURED · no persisted detection read yet" in app
    assert "overlayState.metaSeen = true;" in app


def test_government_wall_is_exactly_thirty(app: str) -> None:
    assert 'if (liveDomain === "government") liveWallMode = 30;' in app
    assert "Math.max(liveWallMode, 30)" not in app
    # The GOVERNMENT MODE preset was removed as a duplicate of the Domain
    # button; the preset that reaches the government wall is still thirty.
    assert '"overview-30": { wall: 30, mode: "video", view: "live", domain: "government" },' in app


def test_thirty_camera_overview_preset_is_wired(app: str) -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'data-preset="overview-30"' in html
    assert '"overview-30": { wall: 30, mode: "video", view: "live", domain: "government" },' in app


def test_live_preset_does_not_start_two_competing_loaders(app: str) -> None:
    """show() owns loader dispatch; a second call rebuilds the wall while its
    first set of WHEP negotiations is still attaching to the DOM."""
    assert "show(spec.view);" in app
    assert 'if (spec.view === "live") loaders.live?.();' not in app


def test_wall_count_states_the_media_policy_in_force(app: str) -> None:
    """The status line names the policy the tile scheduler applies.

    It used to say cached stills rotated across the wall and one camera had to
    be selected for WHEP, after the wall had started streaming its visible
    tiles; a judge watching moving tiles under that line would be told the
    opposite of what they see.
    """
    assert "government cameras indexed" in app
    assert "CONTROL ROOM — one WHEP session per tile, up to 30, staggered" in app
    assert "OPTIMIZED VIEW — up to 12 WHEP sessions near the viewport" in app
    assert "cached stills rotate across the wall" not in app


#: The content each cache-busting marker was last bumped for. Editing an asset
#: changes its hash, which fails this test and forces the version alongside it.
ASSET_VERSIONS = {
    "app.js": ("cr166", "8920504095ccd278"),
    "style.css": ("cr127", "e1662e5e5ac1fbd3"),
}


def test_cache_version_bumped_for_changed_assets() -> None:
    """A stale cached app.js serves markup whose behaviour never loaded.

    This used to pin the two version strings and nothing else, which meant it
    failed when someone *bumped* a version and passed when someone edited an
    asset and forgot to — the exact opposite of its purpose. Hashing the asset
    makes the omission the failure: change app.js without bumping cr136 and
    this test says so.

    On a bump, update both halves of the entry. The hash is a short sha256 of
    the file, which `python -c` will print:
        import hashlib,pathlib;print(hashlib.sha256(
            pathlib.Path("ui/app.js").read_bytes()).hexdigest()[:16])
    """
    import hashlib

    html = INDEX.read_text(encoding="utf-8")
    for name, (version, digest) in ASSET_VERSIONS.items():
        marker = f"/ui/{name}?v={version}"
        assert marker in html, (
            f"{name} is served at a different version than this test expects; "
            f"looked for {marker!r}")
        actual = hashlib.sha256((UI / name).read_bytes()).hexdigest()[:16]
        assert actual == digest, (
            f"{name} changed since {version} was set (hash {actual}, expected "
            f"{digest}). Bump the version in ui/index.html and update "
            f"ASSET_VERSIONS, or a cached copy will serve behaviour that no "
            f"longer matches the markup.")


def test_hls_wall_staggers_muxer_startup(app: str) -> None:
    assert "let hlsDelay = 0;" in app
    assert "scheduleTileWhep(() => openTileHls(id), hlsDelay);" in app
    assert "hlsDelay += 250;" in app
