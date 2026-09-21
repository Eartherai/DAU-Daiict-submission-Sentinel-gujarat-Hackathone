"""Local media hub: latest-frame-wins, LIVE vs PREVIEW, 50-camera composition."""
from __future__ import annotations

import time

from saakshya.command.domain import enforce_evaluation_50
from saakshya.live.hub import LIVE_AGE_S, MediaHub, _video_from_age
from saakshya.store import Store


def test_latest_jpeg_wins():
    hub = MediaHub(store=None)
    hub._slots["cam01"] = hub._slots.get("cam01")
    from saakshya.live.hub import HubSlot
    hub._slots["cam01"] = HubSlot(camera_id="cam01", domain="GOVERNMENT", url="rtsp://x")
    hub._slots["cam01"].jpeg = b"aaaa"
    hub._slots["cam01"].captured_at = time.time()
    hub._slots["cam01"].width = 64
    hub._slots["cam01"].height = 36
    hub._slots["cam01"].jpeg = b"bbbb"
    assert hub.as_snapshot("cam01").jpeg == b"bbbb"


def test_stale_frame_is_preview_not_live():
    assert _video_from_age("CONNECTED", 0.4) == "LIVE"
    assert _video_from_age("CONNECTED", LIVE_AGE_S + 1) == "PREVIEW"
    assert _video_from_age("CONNECTED", 30) == "NO_SIGNAL"
    assert _video_from_age("CONNECTING", None) == "CONNECTING"


def test_own_feed_is_replay_not_live():
    assert _video_from_age("CONNECTED", 0.2, "OWN_FEED") == "REPLAY"
    assert _video_from_age("CONNECTED", 30, "OWN_FEED") == "NO_SIGNAL"


def test_enforce_50_drops_far(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/t.db")
    store.create_all()
    store.upsert_camera({
        "camera_id": "FAR", "district": "X", "source_domain": "GOVERNMENT",
        "lat": 24.6, "lon": 72.58,
    })
    out = enforce_evaluation_50(store)
    ids = {c["camera_id"] for c in store.list_cameras()}
    assert "FAR" not in ids
    assert out["onboarded"] == 50
    assert out["composition"]["government"] == 30
    assert out["composition"]["own_feed"] == 2
    assert out["composition"]["synthetic_control"] == 18
