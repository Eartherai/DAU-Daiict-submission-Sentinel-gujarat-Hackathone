"""The relay's media plane: closed to the LAN, and honest about time.

Two findings from officers who used the running relay. MediaMTX was listening
on every interface with anonymous publish (anyone on the LAN could read a
government camera or replace its feed), and the publisher stamped its output
with a frame counter, so a camera delivering four frames a second was
published as twelve and its keyframes drifted three to six seconds apart.
"""
from __future__ import annotations

from fractions import Fraction

import av
import numpy as np
import pytest

from saakshya.live.relay import (
    PublisherCredential,
    mediamtx_relay_config,
    non_loopback_listeners,
)
from saakshya.live.relay_publisher import (
    OUTPUT_CLOCK,
    WallTimebase,
    _copy_or_transcode,
    _publish_destination,
)

yaml = pytest.importorskip("yaml")


def _config(**kw):
    cred = PublisherCredential(user="relaytest", password="s3cret-pw")
    return cred, yaml.safe_load(mediamtx_relay_config(["cam01", "cam02"], cred, **kw))


# --------------------------------------------------------------------------- #
# live_mediamtx_exposed_lan
# --------------------------------------------------------------------------- #
def test_every_listener_binds_loopback_and_unused_protocols_are_off():
    _, cfg = _config()
    for key in ("rtspAddress", "hlsAddress", "webrtcAddress",
                "webrtcLocalUDPAddress", "apiAddress"):
        assert str(cfg[key]).startswith("127.0.0.1:"), key
    # The protocols that were bound to *:1935, *:8890 and *:8892/8893.
    for proto in ("rtmp", "srt", "moq", "playback", "metrics", "pprof"):
        assert cfg[proto] is False, proto
    assert cfg["webrtcLocalTCPAddress"] == ""
    assert cfg["rtspTransports"] == ["tcp"]
    # Interface discovery would advertise a LAN address nobody listens on.
    assert cfg["webrtcIPsFromInterfaces"] is False
    assert cfg["webrtcAdditionalHosts"] == ["127.0.0.1"]


def test_anonymous_users_cannot_publish_and_nothing_is_open_to_any_ip():
    cred, cfg = _config()
    users = cfg["authInternalUsers"]
    for user in users:
        # An empty ips list means "any IP" to MediaMTX.
        assert user["ips"] and set(user["ips"]) <= {"127.0.0.1", "::1"}
    publishers = [u for u in users
                  if any(p["action"] == "publish" for p in u["permissions"])]
    assert [u["user"] for u in publishers] == [cred.user]
    assert publishers[0]["pass"] == cred.password
    anon = [u for u in users if u["user"] == "any"]
    assert anon and all(p["action"] != "publish"
                        for u in anon for p in u["permissions"])
    assert cfg["pathDefaults"]["overridePublisher"] is False


def test_browser_origins_are_named_never_a_wildcard():
    _, cfg = _config(origins=("http://127.0.0.1:8136",))
    for key in ("hlsAllowOrigins", "webrtcAllowOrigins", "apiAllowOrigins"):
        assert cfg[key] == ["http://127.0.0.1:8136"], key
        assert "*" not in cfg[key]


def test_config_lists_every_relay_path():
    _, cfg = _config()
    assert set(cfg["paths"]) == {"cam01", "cam02"}


def test_publisher_credential_is_per_boot_and_only_in_the_authority():
    a, b = PublisherCredential.generate(), PublisherCredential.generate()
    assert a != b and len(a.password) >= 24
    url = a.authority("rtsp://127.0.0.1:18554/cam01")
    assert url.startswith("rtsp://relay") and url.endswith("@127.0.0.1:18554/cam01")
    # An authority that already carries a user is left alone.
    assert a.authority("rtsp://x:y@127.0.0.1/cam") == "rtsp://x:y@127.0.0.1/cam"


def test_publisher_takes_the_credential_from_its_environment(monkeypatch):
    monkeypatch.delenv("SAAKSHYA_RELAY_PUBLISH_USER", raising=False)
    assert _publish_destination("rtsp://127.0.0.1:18554/cam01") == \
        "rtsp://127.0.0.1:18554/cam01"
    monkeypatch.setenv("SAAKSHYA_RELAY_PUBLISH_USER", "relayab")
    monkeypatch.setenv("SAAKSHYA_RELAY_PUBLISH_PASS", "p/w@x")
    assert _publish_destination("rtsp://127.0.0.1:18554/cam01") == \
        "rtsp://relayab:p%2Fw%40x@127.0.0.1:18554/cam01"


LSOF_EXPOSED = """\
COMMAND    PID    USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
mediamtx 74742 earther    4u  IPv4 0x68814745e4579345      0t0  TCP 127.0.0.1:18554 (LISTEN)
mediamtx 74742 earther    5u  IPv6  0xd1479d5506865aa      0t0  TCP *:1935 (LISTEN)
mediamtx 74742 earther    8u  IPv6 0x969341ad76aa3fb9      0t0  UDP *:8189
mediamtx 74742 earther    9u  IPv4 0x4e0a1dfae71809ac      0t0  UDP 192.168.1.5:8890
mediamtx 74742 earther  147u  IPv4 0x9ca98ede8e18b266      0t0  TCP 127.0.0.1:18554->127.0.0.1:63846 (ESTABLISHED)
"""
LSOF_CLOSED = """\
COMMAND    PID    USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
mediamtx 87594 earther    4u  IPv4 0xf5f521cb31097fac      0t0  TCP 127.0.0.1:38554 (LISTEN)
mediamtx 87594 earther    7u  IPv4 0x34ffe3bdfde2b4a1      0t0  UDP 127.0.0.1:38189
mediamtx 87594 earther    8u  IPv6 0x7e1e9f95fe65e2af      0t0  TCP [::1]:39997 (LISTEN)
"""


def test_listener_self_test_names_what_the_old_relay_exposed():
    assert non_loopback_listeners(LSOF_EXPOSED) == [
        "TCP *:1935", "UDP *:8189", "UDP 192.168.1.5:8890"]
    assert non_loopback_listeners(LSOF_CLOSED) == []


def test_listener_self_test_allows_an_interface_the_operator_named():
    text = LSOF_CLOSED + (
        "mediamtx 1 u 9u IPv4 0x1 0t0 UDP 10.0.0.7:18189\n")
    assert non_loopback_listeners(text) == ["UDP 10.0.0.7:18189"]
    assert non_loopback_listeners(text, allowed_host="10.0.0.7") == []


# --------------------------------------------------------------------------- #
# live_relay_pts_counter
# --------------------------------------------------------------------------- #
def test_output_pts_is_source_time_not_a_frame_counter():
    tb = WallTimebase(12)
    stamps = []
    for i in range(8):  # a camera delivering 4 fps
        s = 100.0 + i * 0.25
        assert tb.admit(s)
        stamps.append(tb.stamp(s)[0])
    assert stamps == [round(i * 0.25 * OUTPUT_CLOCK) for i in range(8)]


def test_idr_is_forced_by_source_time_whatever_the_frame_rate():
    for fps_in in (4, 12, 25):
        tb = WallTimebase(12)
        idr_times, admitted = [], []
        for i in range(fps_in * 6):
            s = i / fps_in
            if not tb.admit(s):
                continue
            admitted.append(s)
            _, key = tb.stamp(s)
            if key:
                idr_times.append(s)
        gaps = np.diff(idr_times)
        frame_gap = np.diff(admitted).max()
        assert len(idr_times) >= 5, fps_in
        # An IDR lands on the first published frame at or after one second.
        assert gaps.max() <= 1.0 + frame_gap + 1e-6, (fps_in, gaps)
        assert gaps.min() >= 1.0 - 1e-6, (fps_in, gaps)


def test_timestamps_stay_monotonic_through_a_source_reset():
    tb = WallTimebase(12)
    out = []
    for s in [10.0, 10.25, 10.5, 2.0, 2.25, 2.5]:  # camera rebooted
        assert tb.admit(s)
        pts, key = tb.stamp(s)
        out.append((pts, key))
    pts = [p for p, _ in out]
    assert pts == sorted(pts) and len(set(pts)) == len(pts)
    # After the reset the clock continues about one frame on, not +1 tick for
    # ever and not minutes away, and the next frame is an IDR.
    assert pts[3] - pts[2] == round(OUTPUT_CLOCK / 12)
    assert pts[4] - pts[3] == round(0.25 * OUTPUT_CLOCK)
    assert out[3][1] is True
    assert tb.rebases == 1


def _slow_camera_clip(path, fps: int, seconds: int) -> None:
    """A clip whose PTS says ``fps`` frames a second, like a slow camera."""
    with av.open(str(path), "w") as out:
        st = out.add_stream("libx264", rate=fps)
        st.width, st.height, st.pix_fmt = 320, 240, "yuv420p"
        st.time_base = Fraction(1, 90000)
        st.codec_context.time_base = Fraction(1, 90000)
        st.options = {"g": "250", "bf": "0"}  # a long source GOP, as on the grid
        for i in range(fps * seconds):
            img = np.full((240, 320, 3), (i * 7) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            frame.pts = round(i * 90000 / fps)
            frame.time_base = Fraction(1, 90000)
            for pkt in st.encode(frame):
                out.mux(pkt)
        for pkt in st.encode(None):
            out.mux(pkt)


def test_published_stream_keeps_source_timing_and_one_second_idrs(tmp_path):
    """End to end through the real encoder: a 4 fps camera on a 12 fps wall.

    Before the fix this published 24 frames claiming 12 fps (two seconds of
    video for six seconds of camera) with one keyframe in six seconds.
    """
    src = tmp_path / "slow.mp4"
    dst = tmp_path / "wall.mkv"
    _slow_camera_clip(src, fps=4, seconds=6)
    _copy_or_transcode(str(src), str(dst), "transcode", "400k", 240, 12,
                       software=True)
    with av.open(str(dst)) as inp:
        st = inp.streams.video[0]
        packets = [p for p in inp.demux(st) if p.pts is not None]
    times = sorted(float(p.pts * p.time_base) for p in packets)
    key_times = sorted(float(p.pts * p.time_base) for p in packets if p.is_keyframe)
    assert len(times) == 24
    assert times[-1] == pytest.approx(5.75, abs=0.02)  # six seconds of camera
    assert np.diff(times) == pytest.approx([0.25] * 23, abs=0.002)
    assert len(key_times) >= 5
    assert max(np.diff(key_times)) <= 1.0 + 1e-3
