"""Importing the 15 Sep government clips: verified, re-timed, labelled, never live."""
from __future__ import annotations

import json
import os
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/demo"))
import import_gov_clips as imp  # noqa: E402


def broken_clip(path: Path, count: int) -> None:
    """Synthetic moving rectangle whose container clock is wrong, as the capture's was."""
    with av.open(str(path), "w") as out:
        stream = out.add_stream("libx264", rate=15)
        stream.width, stream.height, stream.pix_fmt = 160, 96, "yuv420p"
        for i in range(count):
            img = np.zeros((96, 160, 3), dtype=np.uint8)
            img[25:55, 5 + i:30 + i] = (240, 160, 50)
            f = av.VideoFrame.from_ndarray(img, format="rgb24")
            f.pts, f.time_base = i, Fraction(1, 2700)  # 2700 fps: the broken clock
            for packet in stream.encode(f):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


@pytest.fixture
def clips(tmp_path):
    d = tmp_path / "clips"
    d.mkdir()
    broken_clip(d / "cam06.mp4", 36)
    os.utime(d / "cam06.mp4", (1789449000, 1789449000))  # 15 Sep 2026 10:40 IST
    score = {"camera_id": "cam06", "ok": True, "show": True, "frames": 36, "seconds": 15.8,
             "bytes": (d / "cam06.mp4").stat().st_size, "score": 44.0, "note": ""}
    (d / "scores.json").write_text(json.dumps({"seconds": 12, "cameras": [score]}))
    return d, score


def test_clip_is_retimed_at_measured_rate_with_every_frame(tmp_path, clips):
    d, score = clips
    media = tmp_path / "media"
    m = imp.import_clip("cam06", imp.scores(d)["cam06"], d, media)
    assert m["label"] == "RECORDED GOVERNMENT FOOTAGE" and not m["synthetic"]
    assert m["source_domain"] == "ARCHIVAL_REPLAY" and m["camera_id"] == "GOVREC-cam06"
    assert m["fps"] == pytest.approx(3.0) and m["frames"] == 36
    assert m["duration_s"] == pytest.approx(12.0)
    assert m["capture_end_ist"].startswith("2026-09-15T10:40") and m["capture_end_ist"].endswith("+05:30")
    assert m["source_url"] == "<redacted>" and "not the original scene date" in m["timestamp_basis"]
    with av.open(str(media / m["file"])) as clip:
        times = [float(f.time) for f in clip.decode(video=0)]
    assert times == pytest.approx([i / 3 for i in range(36)], abs=0.0001)
    assert json.loads((media / "GOVREC-cam06.manifest.json").read_text())["sha256"] == m["sha256"]
    assert not list(media.glob("*.partial.mp4"))


def test_changed_clip_is_refused(tmp_path, clips):
    d, _ = clips
    with open(d / "cam06.mp4", "ab") as f:
        f.write(b"\0")
    with pytest.raises(imp.ImportFailure, match="changed since capture"):
        imp.import_clip("cam06", imp.scores(d)["cam06"], d, tmp_path / "media")
    assert not (tmp_path / "media" / "GOVREC-cam06.mp4").exists()


def test_frame_count_mismatch_is_refused(tmp_path, clips):
    d, score = clips
    with pytest.raises(imp.ImportFailure, match="decoded 36 frames"):
        imp.import_clip("cam06", dict(score, frames=40), d, tmp_path / "media")
    assert not list((tmp_path / "media").glob("GOVREC-*"))


def test_unshowable_and_existing_recordings_are_refused(tmp_path, clips):
    d, score = clips
    with pytest.raises(imp.ImportFailure, match="not a showable"):
        imp.import_clip("cam06", dict(score, show=False), d, tmp_path / "media")
    imp.import_clip("cam06", score, d, tmp_path / "media")
    with pytest.raises(imp.ImportFailure, match="already exists"):
        imp.import_clip("cam06", score, d, tmp_path / "media")


def test_scores_must_describe_twelve_second_windows(tmp_path):
    (tmp_path / "scores.json").write_text(json.dumps({"seconds": 10, "cameras": []}))
    with pytest.raises(imp.ImportFailure):
        imp.scores(tmp_path)
