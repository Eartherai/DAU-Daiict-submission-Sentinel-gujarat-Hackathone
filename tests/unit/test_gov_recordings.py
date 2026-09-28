"""Offline capture, provenance, file serving and frame alignment contracts."""
from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/demo"))
import analyse_own_feed as analyse
import capture_gov_footage as capture

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.command.domain import annotate_camera, classify_source_domain
from saakshya.reports.anpr import anpr_csv, anpr_rows
from saakshya.security import Role
from saakshya.store import Store
from tests.conftest import make_observation


def synthetic_clip(path, rate=Fraction(25), count=12):
    """Moving rectangle, explicitly synthetic; not a government image."""
    with av.open(str(path), "w") as out:
        stream = out.add_stream("libx264", rate=rate)
        stream.width, stream.height, stream.pix_fmt = 160, 96, "yuv420p"
        for i in range(count):
            img = np.zeros((96, 160, 3), dtype=np.uint8)
            img[25:55, 5 + i * 3:30 + i * 3] = (240, 160, 50)
            f = av.VideoFrame.from_ndarray(img, format="rgb24")
            f.pts, f.time_base = i, 1 / rate
            for packet in stream.encode(f):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


@pytest.fixture
def cam():
    return {"camera_id": "cam06", "name": "Test junction", "district": "Ahmedabad",
            "department": "Test department", "site": "Test site", "lat": 23.04, "lon": 72.58,
            "source_domain": "GOVERNMENT", "rtsp_url": "rtsp://example.invalid/cam06"}


@pytest.fixture
def captured(tmp_path, cam, monkeypatch):
    src = tmp_path / "synthetic.mp4"
    synthetic_clip(src)
    media = tmp_path / "media"
    monkeypatch.setenv("SAAKSHYA_MEDIA", str(media))
    manifest = capture.capture_one(cam, media, 1, local_source=src)
    return media, manifest


@pytest.mark.parametrize("rate", [Fraction(25), Fraction(30000, 1001), Fraction(12)])
def test_native_frame_rate_and_frames_are_preserved(tmp_path, cam, rate):
    src = tmp_path / "synthetic.mp4"
    synthetic_clip(src, rate)
    media = tmp_path / "media"
    result = capture.capture_one(cam, media, 1, local_source=src)
    assert result["synthetic"] and result["label"] == "SYNTHETIC OFFLINE TEST"
    assert result["source_url"] == "<redacted>"
    assert result["fps"] == pytest.approx(float(rate))
    assert result["frames"] == 12
    assert result["capture_start_ist"].endswith("+05:30")
    assert result["capture_end_ist"] >= result["capture_start_ist"]
    with av.open(str(media / result["file"])) as clip:
        times = [float(f.time) for f in clip.decode(video=0)]
    assert times == pytest.approx([i / float(rate) for i in range(12)], abs=0.00002)
    assert not list(media.glob("*.partial.mp4"))


def test_401_stops_all_retries_and_remaining_cameras(monkeypatch, tmp_path, cam):
    calls, sleeps = [], []
    def reject(*args, **kwargs):
        calls.append(args[0]["camera_id"])
        raise capture.Unauthorized("401")
    monkeypatch.setattr(capture, "capture_one", reject)
    with pytest.raises(capture.Unauthorized):
        capture.capture_batch([cam, dict(cam, camera_id="cam07")], tmp_path, 1, sleep=sleeps.append)
    assert calls == ["cam06"]
    assert sleeps == []


def test_sequential_stagger_and_bounded_backoff(monkeypatch, tmp_path, cam):
    calls, sleeps = [], []
    def attempt(row, *args):
        calls.append(row["camera_id"])
        if len(calls) < 3:
            raise capture.CaptureFailure()
        return {"camera_id": row["camera_id"]}
    monkeypatch.setattr(capture, "capture_one", attempt)
    capture.capture_batch([cam, dict(cam, camera_id="cam07")], tmp_path, 1, sleep=sleeps.append)
    assert calls == ["cam06", "cam06", "cam06", "cam07"]
    assert sleeps == [2, 4, 2]


def test_open_error_never_exposes_source_or_exception(monkeypatch, tmp_path, cam, capsys):
    monkeypatch.setattr(capture, "credentialed", lambda *a, **k: "rtsp://example.invalid/private")
    def fail(*args, **kwargs):
        raise RuntimeError("401 Unauthorized rtsp://example.invalid/private")
    monkeypatch.setattr(av, "open", fail)
    with pytest.raises(capture.Unauthorized) as exc:
        capture.capture_one(cam, tmp_path, 1)
    assert "rtsp" not in str(exc.value)
    assert capsys.readouterr() == ("", "")
    assert not list(tmp_path.iterdir())


def test_registration_copies_location_without_live_urls(captured, cam, tmp_path):
    media, manifest = captured
    store = Store(f"sqlite:///{tmp_path / 'registry.db'}")
    store.create_all()
    store.upsert_camera(cam)
    capture.register(cam, media, store)
    row = store.get_camera("GOVREC-cam06")
    for key in ("name", "district", "site", "lat", "lon"):
        assert row[key] == cam[key]
    assert row["source_domain"] == "ARCHIVAL_REPLAY"
    assert not row["rtsp_url"] and not row["whep_url"]
    public = annotate_camera(row)
    assert public["tile_status"] == "REPLAY"
    assert public["source_camera_id"] == "cam06"
    assert public["recording_label"].startswith("SYNTHETIC OFFLINE TEST · captured ")
    assert classify_source_domain("GOVREC-cam06") == "ARCHIVAL_REPLAY"
    assert store.get_camera("cam06")["source_domain"] == "GOVERNMENT"
    with (media / manifest["file"]).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError):
        capture.register(cam, media, store)


def test_analysis_visits_every_frame_and_uses_file_pts(captured, monkeypatch):
    media, manifest = captured
    frames = []
    class Pipe:
        def __init__(self, *args, **kwargs):
            self.tracks = self.people = SimpleNamespace(get=lambda *a: SimpleNamespace(tracks={}))
        def process(self, frame):
            frames.append(frame)
            return []
        def flush(self):
            return []
    monkeypatch.setattr("saakshya.analytics.pipeline.CameraPipeline", Pipe)
    result = analyse.analyse("GOVREC-cam06", media=media)
    assert result["frame_count"] == len(frames) == manifest["frames"]
    assert [f.pts_s for f in frames] == pytest.approx([i / 25 for i in range(12)])
    assert frames[0].t_norm.isoformat() == manifest["capture_start_ist"]
    assert result["timing"] == "presentation_timestamps"
    assert result["source_domain"] == "ARCHIVAL_REPLAY"
    assert result["synthetic"] is True


def test_analysis_refuses_unregistered_findings(captured, tmp_path):
    media, _ = captured
    with pytest.raises(ValueError, match="register"):
        analyse.analyse("GOVREC-cam06", media=media, record=f"sqlite:///{tmp_path / 'bad.db'}")


def test_api_serves_replay_ranges_and_rejects_stale_boxes(captured, cam, tmp_path):
    media, manifest = captured
    state = AppState(f"sqlite:///{tmp_path / 'api.db'}", evidence_root=tmp_path / "evidence")
    state.store.upsert_camera(cam)
    capture.register(cam, media, state.store)
    state.tokens.upsert_user("test.replay", Role.SUPERVISOR)
    headers = {"Authorization": f"Bearer {state.tokens.mint('test.replay')}"}
    client = TestClient(create_app(state=state))
    base = "/media/own/GOVREC-cam06/"
    assert client.get(base + "file").status_code == 401
    assert client.get(base + "file", headers={**headers, "Range": "bytes=0-99"}).status_code == 206
    assert client.get("/media/own/cam06/file", headers=headers).status_code == 404
    side = media / "GOVREC-cam06.tracks.json"
    side.write_text(json.dumps({"camera_id": "GOVREC-cam06", "sha256": manifest["sha256"], "frames": []}))
    assert client.get(base + "tracks", headers=headers).status_code == 200
    side.write_text(json.dumps({"camera_id": "GOVREC-cam06", "sha256": "wrong", "frames": []}))
    assert client.get(base + "tracks", headers=headers).status_code == 409


def test_replay_findings_are_excluded_from_government_report(captured, cam, tmp_path):
    media, _ = captured
    store = Store(f"sqlite:///{tmp_path / 'report.db'}")
    store.create_all()
    store.upsert_camera(cam)
    capture.register(cam, media, store)
    store.add_observations([make_observation("cam06", plate="GJ01AB1234"),
                            make_observation("GOVREC-cam06", plate="GJ01AB5678")])
    rows = anpr_rows(store, domains=["GOVERNMENT"])
    assert [r["camera_id"] for r in rows] == ["cam06"]
    rows = anpr_rows(store, domains=["ARCHIVAL_REPLAY"])
    assert rows[0]["source_domain"] == "ARCHIVAL_REPLAY"
    assert "ARCHIVAL_REPLAY" in anpr_csv(rows)


def test_browser_frame_lookup_seeks_loops_and_handles_variable_pts():
    source = (ROOT / "ui/app.js").read_text()
    helper = source[source.index("function recordingFrameIndex("):source.index("function recordedGovernmentTile(")]
    script = helper + '''
const assert = require('node:assert/strict');
const t = {timing: 'presentation_timestamps', frames: [[0, []], [.04, []], [.12, []], [.16, []]]};
assert.equal(recordingFrameIndex(t, .10), 1);
assert.equal(recordingFrameIndex(t, .12), 2);
assert.equal(recordingFrameIndex(t, 0), 0);
assert.equal(recordingFrameIndex(t, .16), 3);
assert.equal(recordingFrameIndex(t, .04), 1);
'''
    subprocess.run(["node", "-e", script], check=True)
