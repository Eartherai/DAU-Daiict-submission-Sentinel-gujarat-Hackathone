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
