"""Unit tests for evidence-based StreamPathSelector."""
from saakshya.live.path_selector import (
    CameraStreamProfile,
    StreamPath,
    StreamPathSelector,
)


def test_h264_direct_when_stable_no_bframes():
    d = StreamPathSelector().select(CameraStreamProfile(
        "cam01", codec="h264", has_b_frames=False, whep_stable=True))
    assert d.path == StreamPath.DIRECT_H264
    assert d.transport == "whep"
    assert d.needs_transcode is False


def test_h264_with_bframes_marks_transcode():
    d = StreamPathSelector().select(CameraStreamProfile(
        "camX", codec="h264", has_b_frames=True))
    assert d.path == StreamPath.DIRECT_H264
    assert d.needs_transcode is True


def test_hevc_transcodes_when_browser_unsupported():
    d = StreamPathSelector().select(CameraStreamProfile(
        "cam06", codec="hevc", browser_hevc_supported=False))
    assert d.path == StreamPath.HEVC_TRANSCODED_H264
    assert d.needs_transcode is True


def test_hevc_native_when_supported():
    d = StreamPathSelector().select(CameraStreamProfile(
        "cam06", codec="hevc", browser_hevc_supported=True, whep_stable=True))
    assert d.path == StreamPath.HEVC_NATIVE


def test_unstable_whep_falls_back_to_hls():
    d = StreamPathSelector().select(CameraStreamProfile(
        "camY", codec="h264", has_b_frames=False, whep_stable=False))
    assert d.path == StreamPath.HLS_FALLBACK


def test_both_unstable_is_degraded():
    d = StreamPathSelector().select(CameraStreamProfile(
        "camZ", codec="h264", raw_stable=False, whep_stable=False))
    assert d.path == StreamPath.DEGRADED
