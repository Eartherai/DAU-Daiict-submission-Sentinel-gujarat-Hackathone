"""Own feeds play as video, with the pipeline's boxes following the picture.

The Intelligence view showed an own feed as a JPEG swapped every 450 ms from a
one-second snapshot cache, over boxes polled from a CPU-bound worker at about
1.4 frames a second. On a recorded file that is a slideshow — and it drew the
source's pixel coordinates straight onto a canvas of a different size under
`object-fit: cover`, so boxes sat in the wrong place, labelled with a
28-character track ULID that read to an officer like a garbage number plate.

Verified in a visible headless page against a live server: the video advanced
6.54 s -> 8.57 s over two seconds and the overlay followed it from frame 82 to
frame 108 of 377, with boxes landing on the vehicle.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.security import Role

ROOT = Path(__file__).resolve().parents[2]
APP_JS = (ROOT / "ui/app.js").read_text(encoding="utf-8")


def _setup(tmp_path, monkeypatch, *, analysed: bool = True, stale: bool = False):
    media = tmp_path / "media"
    media.mkdir()
    clip = media / "OWN-TEST.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
    monkeypatch.setenv("SAAKSHYA_MEDIA", str(media))

    if analysed:
        import hashlib
        digest = hashlib.sha256(clip.read_bytes()).hexdigest()
        if stale:
            digest = "0" * 64
        (media / "OWN-TEST.tracks.json").write_text(json.dumps({
            "camera_id": "OWN-TEST", "sha256": digest, "fps": 12.0,
            "width": 768, "height": 432, "frames": [[0.0, []]],
        }), encoding="utf-8")

    state = AppState(f"sqlite:///{tmp_path / 'p.db'}",
                     evidence_root=tmp_path / "evidence")
    state.store.upsert_camera({"camera_id": "OWN-TEST", "district": "Ahmedabad",
                               "source_domain": "OWN_FEED"})
    state.store.upsert_camera({"camera_id": "cam06", "district": "Ahmedabad",
                               "source_domain": "GOVERNMENT"})
    state.tokens.upsert_user("sup.test", Role.SUPERVISOR)
    headers = {"Authorization": f"Bearer {state.tokens.mint('sup.test')}"}
    return TestClient(create_app(state=state)), headers


def test_the_recording_is_served_and_seeks(tmp_path, monkeypatch):
    c, h = _setup(tmp_path, monkeypatch)
    r = c.get("/media/own/OWN-TEST/file", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    part = c.get("/media/own/OWN-TEST/file",
                 headers={**h, "Range": "bytes=0-99"})
    assert part.status_code == 206, "without Range support the player cannot seek"
    assert len(part.content) == 100


def test_the_frame_track_is_served_when_it_matches_the_file(tmp_path, monkeypatch):
    c, h = _setup(tmp_path, monkeypatch)
    r = c.get("/media/own/OWN-TEST/tracks", headers=h)
    assert r.status_code == 200
    assert r.json()["fps"] == 12.0


def test_a_government_camera_is_never_served_as_a_file(tmp_path, monkeypatch):
    """They are live streams. There is no recording to hand out."""
    c, h = _setup(tmp_path, monkeypatch)
    r = c.get("/media/own/cam06/file", headers=h)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_A_RECORDING"


def test_an_unanalysed_file_says_so(tmp_path, monkeypatch):
    c, h = _setup(tmp_path, monkeypatch, analysed=False)
    r = c.get("/media/own/OWN-TEST/tracks", headers=h)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_ANALYSED"


def test_boxes_computed_over_different_bytes_are_refused(tmp_path, monkeypatch):
    """The most convincing fabrication this platform could produce.

    Replace the footage and keep the old sidecar, and every box would be drawn
    with confidence over a picture it was never computed from.
    """
    c, h = _setup(tmp_path, monkeypatch, stale=True)
    r = c.get("/media/own/OWN-TEST/tracks", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STALE_ANALYSIS"


def test_no_token_no_footage(tmp_path, monkeypatch):
    c, _ = _setup(tmp_path, monkeypatch)
    assert c.get("/media/own/OWN-TEST/file").status_code == 401
    assert c.get("/media/own/OWN-TEST/tracks").status_code == 401


# -- the browser side -------------------------------------------------------- #

def test_the_stage_plays_the_file_rather_than_polling_stills() -> None:
    block = APP_JS[APP_JS.index("async function paintIntelStage(id, host)"):
                   APP_JS.index("async function paintIntelStageStill")]
    assert 'el("video"' in block
    assert "requestAnimationFrame" in block
    assert "setInterval" not in block, "the native path is back to polling"


def test_boxes_map_through_the_elements_object_fit() -> None:
    """Drawing source pixels onto a differently sized canvas misplaces them."""
    block = APP_JS[APP_JS.index("function videoContentRect"):
                   APP_JS.index("function drawOwnFrame")]
    assert "objectFit" in block
    assert "Math.max(w / vw, h / vh)" in block, "cover scaling is missing"
    assert "Math.min(w / vw, h / vh)" in block, "contain scaling is missing"


def test_the_overlay_labels_are_short_numbers_not_ulids() -> None:
    block = APP_JS[APP_JS.index("function drawOwnFrame"):
                   APP_JS.index("async function paintIntelStage(id, host)")]
    assert "track_id" not in block, (
        "a 28-character ULID over a car reads like a garbage number plate")
    # Short labels, and only where they fit: a tag on every box buried the
    # street under forty "#220 person 45%" labels.
    assert "const label = `${kind} ${conf}`" in block
    assert "confirmed && rw >= tw" in block
    # A plate is always drawn - it is the one label an officer came for.
    assert "if (plate) {" in block


def test_a_hidden_tab_does_not_leave_the_video_paused() -> None:
    """Chrome defers autoplay in hidden tabs; the workspace often opens in one."""
    block = APP_JS[APP_JS.index("async function paintIntelStage(id, host)"):
                   APP_JS.index("async function paintIntelStageStill")]
    assert "visibilitychange" in block
    assert "_userPaused" in block, "resuming must not override a deliberate pause"


def test_an_unanalysed_feed_falls_back_and_says_why() -> None:
    block = APP_JS[APP_JS.index("async function paintIntelStage(id, host)"):
                   APP_JS.index("async function paintIntelStageStill")]
    assert "paintIntelStageStill" in block
    assert "STILL PREVIEW" in block
