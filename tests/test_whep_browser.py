from tools.test_whep_camera import _origin_root, _safe_sdp


def test_safe_sdp_keeps_codec_and_removes_connection_secrets():
    sdp = (
        "o=- 1 2 IN IP4 127.0.0.1\n"
        "a=ice-ufrag:secret\n"
        "a=ice-pwd:secret\n"
        "a=fingerprint:sha-256 AA:BB\n"
        "a=candidate:1 1 udp 1 192.0.2.1 8189 typ host\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 108\n"
        "a=rtpmap:108 H264/90000\n"
        "a=fmtp:108 packetization-mode=1;profile-level-id=42e01f\n"
    )
    safe = _safe_sdp(sdp)
    assert "H264/90000" in safe
    assert "packetization-mode=1" in safe
    assert "secret" not in safe
    assert "192.0.2.1" not in safe


def test_origin_root_uses_whep_host():
    assert _origin_root("http://127.0.0.1:8889/stream/C-014/whep") == \
        "http://127.0.0.1:8889/"
    assert _origin_root("not-a-url") == "about:blank"