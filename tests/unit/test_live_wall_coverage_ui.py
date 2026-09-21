"""Every tile the operator can see should be showing something real.

The wall had three distinct ways to leave a visible tile blank, and each is
pinned here because each was found by measurement rather than by reading:

* the still that was never requested (the observer's first callback was
  dropped while capture was still disabled, and a tile that never leaves the
  viewport never intersects again);
* the WHEP session that negotiated and then never decoded a frame;
* the capture that failed once and was never retried, on a grid whose 503
  means "not right now" rather than "never".
"""

from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "ui"


@pytest.fixture(scope="module")
def app() -> str:
    return (UI / "app.js").read_text(encoding="utf-8")


def test_visible_tiles_are_primed_rather_than_waiting_for_a_scroll(app: str) -> None:
    assert "function primeVisibleStills()" in app
    # It must run as part of the ordinary sync pass, not only on entry.
    sync = app.split("function syncTileWhep()", 1)[1][:400]
    assert "primeVisibleStills();" in sync


def test_a_tile_already_showing_something_is_not_re_requested(app: str) -> None:
    """Priming must not churn captures for tiles that are already covered."""
    body = app.split("function primeVisibleStills()", 1)[1].split("\n}", 1)[0]
    assert 'video.dataset.ready === "1"' in body
    assert 'shown.getAttribute("src")' in body


def test_failed_still_is_retried_on_a_cooldown(app: str) -> None:
    body = app.split("function primeVisibleStills()", 1)[1].split("\n}", 1)[0]
    assert "STILL_RETRY_MS" in body
    assert "stillTry" in body
    # A cooldown that is too short hammers a grid that is already declining.
    retry = int(app.split("const STILL_RETRY_MS = ", 1)[1].split(";", 1)[0])
    assert 3000 <= retry <= 30000


def test_a_session_that_never_decodes_is_renegotiated(app: str) -> None:
    assert "function reopenStalledTileWhep()" in app
    body = app.split("function reopenStalledTileWhep()", 1)[1].split("\n}\n", 1)[0]
    # Only sessions that have never rendered a frame.
    assert "sess.firstFrameAt" in body
    # And never one that is currently delivering pictures.
    assert "videoWidth > 16" in body
    deadline = int(app.split("const WHEP_FIRST_FRAME_MS = ", 1)[1].split(";", 1)[0])
    assert 5000 <= deadline <= 30000


def test_the_wall_has_a_heartbeat_that_outlives_the_entry_retries(app: str) -> None:
    """The entry retries stop at four seconds; stalls happen after that."""
    assert "function startWallHeartbeat()" in app
    assert "function stopWallHeartbeat()" in app
    assert "stopWallHeartbeat();" in app  # torn down when Live is left
    ms = int(app.split("const WALL_HEARTBEAT_MS = ", 1)[1].split(";", 1)[0])
    assert 2000 <= ms <= 15000


def test_decoders_survive_a_wall_rebuild(app: str) -> None:
    """Changing the wall size must not throw away the decoders.

    A WebRTC track decodes into the element it was attached to. Rebuilding the
    wall used to destroy those elements and hand the same MediaStream to fresh
    ones, which have no keyframe to start from and never receive another
    unasked. Measured: switching from the 30-wall to the 12-wall left twelve
    negotiated sessions and zero decoding, still zero two minutes later.
    """
    assert "const survivors = new Map()" in app
    body = app.split("const survivors = new Map()", 1)[1][:600]
    # Only elements that are actually decoding are worth carrying over.
    assert "videoWidth > 16" in body
    assert "survivors.set(" in body
    # And they must be put back into the rebuilt tiles.
    assert "for (const [cam, video] of survivors)" in app
    rehome = app.split("for (const [cam, video] of survivors)", 1)[1][:400]
    assert "frame.prepend(video)" in rehome
    assert 'video.dataset.ready = "1"' in rehome


def test_a_video_that_decodes_but_never_paints_falls_back_to_its_still(app: str) -> None:
    """Having a frame and showing black is the one state to avoid.

    A <video> can decode without painting: an occluded or throttled surface
    drops frames at the compositor, so videoWidth reports 1920 while nothing
    reaches the screen. Measured on an unfocused pane: eight "ready" tiles,
    99.6% of frames dropped, zero rendered in five seconds — and because each
    tile had already hidden its still, the wall showed black squares while
    believing itself live.
    """
    assert "function reviewRenderedFrames()" in app
    body = app.split("function reviewRenderedFrames()", 1)[1].split("\n}\n", 1)[0]
    # Painted frames are total minus dropped — decoding alone is not painting.
    assert "droppedVideoFrames" in body
    assert "totalVideoFrames" in body
    # A stalled tile gives its still back rather than staying black...
    assert "delete video.dataset.ready" in body
    # ...and a tile that resumes painting is promoted again.
    assert "markTileVideoReady(video)" in body
    # One quiet sample must not flicker a healthy tile.
    assert "n < 2" in body
    # It has to run on the heartbeat, not only on entry.
    assert "reviewRenderedFrames();" in app.split("wallTimer = setInterval", 1)[1][:300]


def test_the_visible_tiles_are_fetched_together_on_first_paint(app: str) -> None:
    """The pump protects the wall; it should not ration the visible screen.

    The bounded pump exists so a thirty-tile wall does not open thirty
    captures at once, which is right for the wall at large. But it also filled
    the nine tiles an operator is looking at a few at a time: measured, five of
    nine at t+7s and still five past t+19s. Asked directly, the grid answered
    all nine concurrently in 1.6-7.4s — it was never the bottleneck. After the
    change: nine of nine by t+10s.
    """
    body = app.split("function primeVisibleStills()", 1)[1].split("\n}\n", 1)[0]
    # The first pass goes straight to the fetch, once.
    assert "primeVisibleStills.done" in body
    assert "refreshTile(tile._img" in body
    # Every later pass goes back through the bounded queue.
    assert "queueStill(tile._img" in body
    # A rebuilt wall is allowed to burst again.
    assert "primeVisibleStills.done = false;" in app


def test_a_capture_cannot_hold_a_slot_for_ever(app: str) -> None:
    """A slot is shared, so holding one is a promise to give it back."""
    assert "SNAPSHOT_TIMEOUT_MS" in app
    ms = int(app.split("const SNAPSHOT_TIMEOUT_MS = ", 1)[1].split(";", 1)[0])
    # Long enough that a genuinely cold camera still succeeds — an 8s deadline
    # turned 12 requests with 8 answers into 24 requests with 4.
    assert 15000 <= ms <= 45000
    assert "clearTimeout(deadline)" in app
