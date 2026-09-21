"""Local MediaMTX relay: WHEP is loopback, JPEG is fallback, pytest stays off."""
from __future__ import annotations

from saakshya.live.relay import (
    COPY_BLOCKED_REASON,
    HEVC_READY_TIMEOUT_S,
    LocalRelay,
    READY_TIMEOUT_S,
    RelaySlot,
    local_hls,
    local_rtsp,
    local_whep,
    relay_enabled,
    _publisher_env,
)
from saakshya.live.relay_publisher import AUTH_BACKOFF_S, _encoder, _wall_geometry


def test_relay_disabled_under_pytest():
    assert relay_enabled() is False


def test_local_urls_are_loopback_without_credentials():
    assert local_whep("cam01") == "http://127.0.0.1:18889/cam01/whep"
    assert local_rtsp("cam01") == "rtsp://127.0.0.1:18554/cam01"
    assert "@" not in local_whep("cam01")
    assert "103.250" not in local_whep("cam01")
    assert local_hls("cam01") == "http://127.0.0.1:18888/cam01/index.m3u8"
    assert "@" not in local_hls("cam01")


def test_government_sources_transcode_for_browser_safe_local_whep_wall():
    relay = LocalRelay()
    mode, reason = relay._choose_mode("cam01", "GOVERNMENT", "rtsp://grid/stream/cam01")
    assert mode == "transcode"
    assert "WHEP" in reason
    # cam17 was named here when the HEVC list was a guess. The list was later
    # corrected against what the grid actually publishes, and cam17 is H.264:
    # assert the rule against a camera that really is HEVC, and assert cam17
    # is no longer claimed to be one.
    from saakshya.live.relay import HEVC_SOURCES
    assert "cam17" not in HEVC_SOURCES
    hevc_cam = sorted(HEVC_SOURCES)[0]
    hevc, hevc_reason = relay._choose_mode(hevc_cam, "GOVERNMENT", "rtsp://x")
    assert hevc == "transcode"
    assert "HEVC" in hevc_reason


def test_government_source_stays_clean_until_the_in_process_publisher(monkeypatch):
    monkeypatch.setenv("SENTINEL_GRID_EMAIL", "operator@example.gov.in")
    monkeypatch.setenv("SENTINEL_GRID_PASSWORD", "test-access-key")
    relay = LocalRelay()
    source = relay._source_url({
        "camera_id": "cam01",
        "source_domain": "GOVERNMENT",
        "rtsp_url": "rtsp://grid.example:8554/stream/cam01",
    })

    assert source == "rtsp://grid.example:8554/stream/cam01"
    assert "@" not in source


def test_authorised_backup_account_splits_even_camera_publishers(monkeypatch):
    monkeypatch.setenv("SENTINEL_GRID_EMAIL", "primary@example.gov.in")
    monkeypatch.setenv("SENTINEL_GRID_PASSWORD", "primary-key")
    monkeypatch.setenv("SENTINEL_GRID_EMAIL_BACKUP", "backup@example.gov.in")
    monkeypatch.setenv("SENTINEL_GRID_PASSWORD_BACKUP", "backup-key")
    odd = _publisher_env("cam01")
    even = _publisher_env("cam02")
    assert odd["SENTINEL_GRID_EMAIL"] == "primary@example.gov.in"
    assert even["SENTINEL_GRID_EMAIL"] == "backup@example.gov.in"
    assert "SENTINEL_GRID_EMAIL_BACKUP" not in odd
    assert "SENTINEL_GRID_PASSWORD_BACKUP" not in even


def test_wall_rendition_cap_preserves_even_aspect_ratio():
    assert _wall_geometry(1920, 1080, 720) == (1280, 720)
    assert _wall_geometry(1280, 960, 720) == (960, 720)
    assert _wall_geometry(960, 576, 720) == (960, 576)


def test_software_encoder_can_be_selected_for_a_hardware_reject():
    assert _encoder(software=True) == "libx264"


def test_authentication_backoff_is_longer_than_reconnect_churn():
    assert AUTH_BACKOFF_S >= 300


def test_hevc_readiness_window_allows_a_slow_keyframe_join():
    assert HEVC_READY_TIMEOUT_S > READY_TIMEOUT_S


def test_own_feed_tries_copy_first():
    relay = LocalRelay()
    mode, reason = relay._choose_mode("OWN-TRAFFIC", "OWN_FEED", "/tmp/OWN-TRAFFIC.mp4")
    assert mode == "copy"
    assert "fallback" in reason.lower() or "copy" in reason.lower()


def test_ready_path_is_not_claimed_browser_live_own_feed_is_replay():
    relay = LocalRelay()
    gov = RelaySlot(camera_id="cam01", domain="GOVERNMENT", src="rtsp://x", ready=True)
    own = RelaySlot(camera_id="OWN-PEOPLE", domain="OWN_FEED", src="file.mp4", ready=True)
    assert relay._planes(gov) == ("CONNECTED", "CONNECTING")
    assert relay._planes(own) == ("CONNECTED", "REPLAY")
    connecting = RelaySlot(camera_id="cam02", domain="GOVERNMENT", src="rtsp://x")
    assert relay._planes(connecting)[1] in {"CONNECTING", "NO SIGNAL"}


def test_capability_table_does_not_transcode_everyone():
    relay = LocalRelay()
    relay._slots["cam01"] = RelaySlot(
        camera_id="cam01", domain="GOVERNMENT", src="x",
        mode="transcode", passthrough=False, transcode=True, reason=COPY_BLOCKED_REASON)
    relay._slots["OWN-TRAFFIC"] = RelaySlot(
        camera_id="OWN-TRAFFIC", domain="OWN_FEED", src="y",
        mode="copy", passthrough=True, transcode=False, reason="file copy")
    table = {r["camera"]: r for r in relay.capability_table()}
    assert table["cam01"]["passthrough"] is False
    assert table["OWN-TRAFFIC"]["passthrough"] is True
    assert table["cam01"]["transcode"] is True
