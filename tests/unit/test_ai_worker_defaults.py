"""The AI plane must not default to a camera that cannot be analysed.

The default was the literal "OWN-TRAFFIC", which on this estate has no source.
The worker started, logged `ai worker has no source for OWN-TRAFFIC`, and sat
there: every figure on the Model 4 panel read NOT_MEASURED and the masthead
said AI DEGRADED — not because anything had failed, but because nothing had
been asked to run. A default that cannot work is worse than no default,
because it looks configured.
"""

from saakshya.analytics.worker import _default_ai_cameras
from saakshya.store.repository import Store


def _db(tmp_path, name="ai.db"):
    url = f"sqlite:///{tmp_path / name}"
    store = Store(url)
    store.create_all()
    return url, store


def test_defaults_to_cameras_that_have_a_stream(tmp_path):
    url, store = _db(tmp_path)
    store.upsert_camera({"camera_id": "cam01", "name": "one",
                         "rtsp_url": "rtsp://grid/stream/cam01"})
    store.upsert_camera({"camera_id": "cam02", "name": "two",
                         "rtsp_url": "rtsp://grid/stream/cam02"})
    store.upsert_camera({"camera_id": "nostream", "name": "paper only"})
    picked = _default_ai_cameras(url)
    assert "cam01" in picked and "cam02" in picked
    assert "nostream" not in picked


def test_capacity_slots_are_never_chosen(tmp_path):
    url, store = _db(tmp_path, "slots.db")
    store.upsert_camera({"camera_id": "CTL-00000", "name": "synthetic 0",
                         "rtsp_url": "rtsp://grid/stream/ctl"})
    store.upsert_camera({"camera_id": "cam01", "name": "real",
                         "rtsp_url": "rtsp://grid/stream/cam01"})
    assert _default_ai_cameras(url) == ["cam01"]


def test_a_disabled_camera_is_not_analysed(tmp_path):
    url, store = _db(tmp_path, "off.db")
    store.upsert_camera({"camera_id": "cam01", "name": "off",
                         "rtsp_url": "rtsp://x", "enabled": False})
    store.upsert_camera({"camera_id": "cam02", "name": "on",
                         "rtsp_url": "rtsp://y"})
    assert _default_ai_cameras(url) == ["cam02"]


def test_the_default_is_bounded(tmp_path):
    """Analysing everything by default would saturate any host."""
    url, store = _db(tmp_path, "many.db")
    for i in range(12):
        store.upsert_camera({"camera_id": f"cam{i:02d}", "name": str(i),
                             "rtsp_url": f"rtsp://grid/{i}"})
    assert len(_default_ai_cameras(url)) == 4
    assert len(_default_ai_cameras(url, limit=2)) == 2


def test_an_estate_with_no_streams_yields_no_worker(tmp_path):
    """Better to start nothing than to start something that cannot work."""
    url, store = _db(tmp_path, "empty.db")
    store.upsert_camera({"camera_id": "cam01", "name": "paper only"})
    assert _default_ai_cameras(url) == []
