"""Selected-camera live view and local own-feed media. No grid required."""
from pathlib import Path

from saakshya.live.snapshot import (
    SelectedView, SnapshotService, file_view_wait_s, local_media_url,
)


def test_local_media_url_finds_the_corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_MEDIA", str(tmp_path))
    (tmp_path / "C-014.mp4").write_bytes(b"fake")
    assert local_media_url("C-014").endswith("C-014.mp4")
    assert local_media_url("cam01") == ""
    assert local_media_url("../etc") == ""
    assert local_media_url("C-014/../../x") == ""


def test_selected_view_stop_is_safe_when_never_started():
    v = SelectedView()
    v.stop()
    assert v.latest("cam01") is None


def test_snapshot_service_has_a_selected_view():
    svc = SnapshotService()
    assert svc.selected.latest("cam01") is None
    svc.selected.stop()


def test_ancient_preview_is_served_without_opening_rtsp(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    preview = tmp_path / "preview"
    preview.mkdir()
    Image.new("RGB", (64, 36), (20, 30, 40)).save(preview / "cam01.jpg",
                                                  quality=80)
    svc = SnapshotService()
    snap = svc.get("cam01", "")
    assert snap is not None
    assert snap.source in ("ingest", "ingest-stale")
    assert snap.width == 64


def test_file_view_wait_is_realtime_from_pts():
    # 1.0s of recording at rate 1.0 is due in 1.0s; at 0.5 it is due in 2.0s.
    assert file_view_wait_s(1.0, 0.0, 10.0, 1.0, 10.0) == 1.0
    assert file_view_wait_s(1.0, 0.0, 10.0, 0.5, 10.0) == 2.0
    assert file_view_wait_s(0.0, 0.0, 10.0, 1.0, 10.0) == 0.0


def test_selected_wait_returns_immediately_when_not_this_camera():
    v = SelectedView()
    v.camera_id = "cam02"
    assert v.wait_for("cam01", timeout_s=0.4) is None
    v.stop()
