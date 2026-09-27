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


# --------------------------------------------------------------------------- #
# Upstream sessions on demand
# --------------------------------------------------------------------------- #
class _FakeWorker:
    def __init__(self):
        import queue
        self.q = queue.Queue()
        self.stats = type("S", (), {"state": "connecting", "measured_fps": None,
                                    "codec": None, "width": None, "height": None,
                                    "reconnects": 0, "frames": 0, "last_error": None})()

    def subscribe(self, name):
        return self.q


class _FakeManager:
    def __init__(self):
        self.added, self.removed, self.workers = [], [], {}

    def add(self, cid, url):
        self.added.append(cid)
        self.workers[cid] = _FakeWorker()
        return self.workers[cid]

    def remove(self, cid):
        self.removed.append(cid)
        w = self.workers.pop(cid, None)
        if w is not None:
            w.q.put(None)

    def get(self, cid):
        return self.workers.get(cid)

    def stop_all(self):
        for cid in list(self.workers):
            self.remove(cid)


def _cams():
    return [{"camera_id": "gov1", "source_domain": "GOVERNMENT", "rtsp_url": "rtsp://g/1"},
            {"camera_id": "gov2", "source_domain": "GOVERNMENT", "rtsp_url": "rtsp://g/2"},
            {"camera_id": "gov3", "source_domain": "GOVERNMENT", "rtsp_url": "rtsp://g/3"}]


def _wait(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not pred():
        time.sleep(0.01)
    return pred()


def test_no_government_session_opens_until_something_asks_for_it():
    # The organisers' guidance for the shared sandbox: keep open only the
    # streams actively required. The hub used to open all thirty at boot.
    hub = MediaHub(store=None, on_demand=True, idle_s=60)
    hub.mgr = _FakeManager()
    hub.start(_cams(), ai_ids=["gov3"], stagger_s=0.0)
    try:
        assert _wait(lambda: hub.mgr.added == ["gov3"])      # the AI camera only
        assert hub.media_state("gov1")["source"] == "IDLE"
        assert hub.snapshot()["upstream_sessions"] == 1 and hub.snapshot()["idle"] == 2
        assert hub.as_snapshot("gov1") is None               # asked for: it opens
        assert _wait(lambda: "gov1" in hub.mgr.added)
        assert "gov2" not in hub.mgr.added
    finally:
        hub.stop()


def test_a_session_nothing_asks_for_is_closed_but_not_the_ai_camera():
    hub = MediaHub(store=None, on_demand=True, idle_s=60)
    hub.mgr = _FakeManager()
    hub.start(_cams(), ai_ids=["gov3"], stagger_s=0.0)
    try:
        hub.demand("gov1")
        assert _wait(lambda: "gov1" in hub.mgr.added)
        assert hub.reap_idle(time.monotonic() + 10) == []    # recently asked for
        assert hub.reap_idle(time.monotonic() + 120) == ["gov1"]
        assert "gov3" not in hub.mgr.removed
        assert _wait(lambda: hub.media_state("gov1")["source"] == "IDLE")
        hub.demand("gov1")                                    # and it reopens
        assert _wait(lambda: hub.mgr.added.count("gov1") == 2)
    finally:
        hub.stop()


def test_always_open_when_on_demand_is_off():
    hub = MediaHub(store=None, on_demand=False)
    hub.mgr = _FakeManager()
    hub.start(_cams(), stagger_s=0.0)
    try:
        assert _wait(lambda: sorted(hub.mgr.added) == ["gov1", "gov2", "gov3"])
    finally:
        hub.stop()


def test_a_still_is_not_grabbed_beside_the_hubs_session(monkeypatch):
    from saakshya.live import hub as hub_mod
    from saakshya.live.snapshot import SnapshotService
    hub = MediaHub(store=None, on_demand=True, idle_s=60)
    hub.mgr = _FakeManager()
    hub.start(_cams(), stagger_s=0.0)
    monkeypatch.setattr(hub_mod, "_HUB", hub)
    svc = SnapshotService()
    grabs = []
    monkeypatch.setattr(svc, "_lock_for", lambda cid: grabs.append(cid))
    try:
        assert svc.get("gov2", "rtsp://g/2") is None
        assert grabs == [] and "no second grid session" in svc.last_error["gov2"]
    finally:
        hub.stop()
