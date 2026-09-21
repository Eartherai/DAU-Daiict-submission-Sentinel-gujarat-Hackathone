import os
from pathlib import Path

import pytest

from saakshya.live import simulation
from saakshya.live.relay import RTSP_PORT as RELAY_RTSP_PORT
from saakshya.live.relay import WHEP_PORT as RELAY_WHEP_PORT

_REQUIRED_FIELDS = {
    "camera_id", "display_name", "department", "city", "location",
    "latitude", "longitude", "source_domain", "media_mode", "codec",
    "width", "height", "source_fps", "current_fps", "replay_start",
    "replay_end", "asset_duration_s", "loop_period_s", "loop_enabled",
    "analytics_capability", "anpr_capability",
    "ai_enabled", "priority", "media_status", "media_path", "demo_label",
}

_ALLOWED_ASSETS = {"C-014.mp4", "C-033.mp4", "C-052.mp4", "C-061.mp4"}

_ALLOWED_DEPARTMENTS = {"Health", "Police", "GSRTC", "Panchayat", "Municipal"}

_ASSET_METADATA = {
    "C-014.mp4": {"width": 1280, "height": 720, "fps": 15},
    "C-033.mp4": {"width": 640, "height": 480, "fps": 10},
    "C-052.mp4": {"width": 960, "height": 540, "fps": 8},
    "C-061.mp4": {"width": 1280, "height": 720, "fps": 15},
}


def test_catalog_count_and_ids():
    cams = simulation.catalog()
    assert len(cams) == 30
    ids = [c["camera_id"] for c in cams]
    assert ids == [f"CAM-{i:03d}" for i in range(1, 31)]


def test_catalog_fields_exact():
    for cam in simulation.catalog():
        assert set(cam.keys()) == _REQUIRED_FIELDS


def test_catalog_provenance_and_assets():
    for cam in simulation.catalog():
        assert cam["source_domain"] == "ARCHIVAL_REPLAY"
        assert cam["source_domain"] != "LIVE_SIMULATION"
        assert cam["media_mode"] == "LIVE_SIMULATION_LOOPED"
        assert cam["demo_label"] == "LIVE SIMULATION / ARCHIVAL REPLAY"
        assert cam["media_status"] == "LOOPED_4M_ASSET_NOT_12H_UNIQUE"
        asset = cam["media_path"].rsplit("/", 1)[-1]
        assert asset in _ALLOWED_ASSETS
        assert cam["media_path"] == f"var/media/{asset}"


def test_catalog_departments_restricted():
    for cam in simulation.catalog():
        assert cam["department"] in _ALLOWED_DEPARTMENTS
        assert cam["department"] not in {"Traffic", "Home (Police)"}


def test_catalog_asset_metadata_matches_mapping():
    for cam in simulation.catalog():
        asset = cam["media_path"].rsplit("/", 1)[-1]
        expected = _ASSET_METADATA[asset]
        assert cam["width"] == expected["width"]
        assert cam["height"] == expected["height"]
        assert cam["source_fps"] == expected["fps"]
        # Catalog is inactive (no publisher running); current_fps must not
        # be fabricated.
        assert cam["current_fps"] is None
        assert cam["codec"] == "h264"


def test_catalog_capabilities_not_measured_until_worker_attaches():
    for cam in simulation.catalog():
        assert cam["analytics_capability"] == simulation.NOT_MEASURED
        assert cam["anpr_capability"] == simulation.NOT_MEASURED
        assert cam["ai_enabled"] is False


def test_catalog_timebase_fields_truthful():
    for cam in simulation.catalog():
        assert cam["replay_start"] == 0
        assert cam["replay_end"] == 12 * 60 * 60
        assert cam["asset_duration_s"] == 240
        assert cam["loop_period_s"] == 240


def test_simulation_ports_defaults_distinct_from_relay():
    ports = simulation.SimulationPorts()
    assert ports.rtsp_port == 28554
    assert ports.whep_port == 28889
    assert ports.api_port == 29997
    assert ports.rtsp_port != RELAY_RTSP_PORT
    assert ports.whep_port != RELAY_WHEP_PORT


def test_simulation_ports_from_env(monkeypatch):
    monkeypatch.setenv("SAAKSHYA_SIMULATION_RTSP_PORT", "31000")
    monkeypatch.setenv("SAAKSHYA_SIMULATION_WHEP_PORT", "31001")
    monkeypatch.setenv("SAAKSHYA_SIMULATION_API_PORT", "31002")
    ports = simulation.SimulationPorts.from_env()
    assert (ports.rtsp_port, ports.whep_port, ports.api_port) == (31000, 31001, 31002)


def test_simulation_ports_reject_collision():
    with pytest.raises(ValueError):
        simulation.SimulationPorts(rtsp_port=1000, whep_port=1000, api_port=1001)
    with pytest.raises(ValueError):
        simulation.SimulationPorts(rtsp_port=1000, whep_port=1001, api_port=1000)


def test_simulation_relay_publisher_command_semantics():
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")
    cmd = relay.publisher_command(row)
    assert "-re" in cmd
    assert "-stream_loop" in cmd
    idx = cmd.index("-stream_loop")
    assert cmd[idx + 1] == "-1"
    assert "-c:v" in cmd
    idx = cmd.index("-c:v")
    assert cmd[idx + 1] == "copy"
    assert "-an" in cmd
    i_idx = cmd.index("-i")
    assert cmd[i_idx + 1] == row["media_path"]
    assert cmd[-1] == f"rtsp://127.0.0.1:{relay.ports.rtsp_port}/CAM-001"


def test_simulation_relay_source_has_no_pkill():
    src = Path(simulation.__file__).read_text()
    assert "pkill" not in src


def test_simulation_relay_no_subprocess_spawned_without_start():
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")
    relay.publisher_command(row)
    with relay._lock:
        assert relay._slots == {}
    assert relay._mtx is None
    assert relay._started is False


def test_simulation_relay_snapshot_before_start_reports_zero_ready():
    relay = simulation.SimulationRelay()
    snap = relay.snapshot()
    assert snap["publisher_count"] == 0
    assert snap["ready_count"] == 0
    assert snap["started"] is False
    assert snap["browser_live"] is None
    assert snap["catalog_count"] == 30
    assert snap["label"] == simulation.DEMO_LABEL
    assert snap["label"] == "LIVE SIMULATION / ARCHIVAL REPLAY"
    assert snap["source_domain"] == "ARCHIVAL_REPLAY"
    assert snap["replay_start"] == 0
    assert snap["replay_end"] == 12 * 60 * 60
    assert snap["asset_duration_s"] == 240
    assert snap["loop_period_s"] == 240


def test_simulation_relay_snapshot_exposes_all_30_cameras_before_start():
    relay = simulation.SimulationRelay()
    snap = relay.snapshot()
    cameras = snap["cameras"]
    assert len(cameras) == 30
    assert [c["camera_id"] for c in cameras] == [f"CAM-{i:03d}" for i in range(1, 31)]
    for cam in cameras:
        assert cam["ready"] is False
        assert cam["current_fps"] is None


def test_validate_catalog_accepts_default_catalog():
    simulation.validate_catalog(simulation.catalog())


def test_validate_catalog_rejects_missing_media_file(tmp_path, monkeypatch):
    monkeypatch.setattr(simulation, "ROOT", tmp_path)
    rows = simulation.catalog()
    with pytest.raises(RuntimeError, match="media file not found"):
        simulation.validate_catalog(rows)


def test_validate_catalog_rejects_duplicate_camera_id():
    rows = simulation.catalog()
    rows[1] = dict(rows[1])
    rows[1]["camera_id"] = rows[0]["camera_id"]
    with pytest.raises(RuntimeError, match="duplicate"):
        simulation.validate_catalog(rows)


def test_validate_catalog_rejects_wrong_count():
    rows = simulation.catalog()[:29]
    with pytest.raises(RuntimeError, match="exactly 30"):
        simulation.validate_catalog(rows)


def test_validate_catalog_rejects_bad_source_domain():
    rows = simulation.catalog()
    rows[0] = dict(rows[0])
    rows[0]["source_domain"] = "LIVE_SIMULATION"
    with pytest.raises(RuntimeError, match="source_domain"):
        simulation.validate_catalog(rows)


def test_validate_catalog_rejects_bad_media_mode():
    rows = simulation.catalog()
    rows[0] = dict(rows[0])
    rows[0]["media_mode"] = "SOMETHING_ELSE"
    with pytest.raises(RuntimeError, match="media_mode"):
        simulation.validate_catalog(rows)


def test_validate_catalog_rejects_unapproved_asset_name():
    rows = simulation.catalog()
    rows[0] = dict(rows[0])
    rows[0]["media_path"] = "var/media/not-approved.mp4"
    with pytest.raises(RuntimeError, match="approved baseline asset"):
        simulation.validate_catalog(rows)


def test_simulation_ports_defaults_include_dedicated_webrtc_ice_ports():
    ports = simulation.SimulationPorts()
    assert ports.webrtc_udp_port == 28890
    assert ports.webrtc_tcp_port == 28891
    assert len({
        ports.rtsp_port, ports.whep_port, ports.api_port,
        ports.webrtc_udp_port, ports.webrtc_tcp_port,
    }) == 5


def test_simulation_ports_from_env_webrtc_ice(monkeypatch):
    monkeypatch.setenv("SAAKSHYA_SIMULATION_WEBRTC_UDP_PORT", "32000")
    monkeypatch.setenv("SAAKSHYA_SIMULATION_WEBRTC_TCP_PORT", "32001")
    ports = simulation.SimulationPorts.from_env()
    assert ports.webrtc_udp_port == 32000
    assert ports.webrtc_tcp_port == 32001


def test_simulation_ports_reject_webrtc_ice_collision_with_other_ports():
    with pytest.raises(ValueError):
        simulation.SimulationPorts(webrtc_udp_port=28554)
    with pytest.raises(ValueError):
        simulation.SimulationPorts(webrtc_tcp_port=28889)
    with pytest.raises(ValueError):
        simulation.SimulationPorts(webrtc_udp_port=28891, webrtc_tcp_port=28891)


def test_config_text_disables_unused_mediamtx_services():
    relay = simulation.SimulationRelay()
    text = relay.config_text(["CAM-001", "CAM-002"])
    assert "rtmp: no" in text
    assert "hls: no" in text
    assert "srt: no" in text
    assert "moq: no" in text
    assert "playback: no" in text
    assert "metrics: no" in text
    assert "pprof: no" in text


def test_config_text_sets_dedicated_webrtc_local_ice_addresses():
    relay = simulation.SimulationRelay()
    text = relay.config_text(["CAM-001"])
    assert f"webrtcLocalUDPAddress: :{relay.ports.webrtc_udp_port}" in text
    assert f"webrtcLocalTCPAddress: :{relay.ports.webrtc_tcp_port}" in text


def test_config_text_includes_expected_signaling_ports():
    relay = simulation.SimulationRelay()
    text = relay.config_text(["CAM-001"])
    assert f"rtspAddress: :{relay.ports.rtsp_port}" in text
    assert f"webrtcAddress: :{relay.ports.whep_port}" in text
    assert f"apiAddress: 127.0.0.1:{relay.ports.api_port}" in text


def test_simulation_ports_reject_non_positive():
    with pytest.raises(ValueError):
        simulation.SimulationPorts(rtsp_port=0, whep_port=28889, api_port=29997)
    with pytest.raises(ValueError):
        simulation.SimulationPorts(rtsp_port=28554, whep_port=-1, api_port=29997)


def test_validate_catalog_rejects_path_traversal_outside_root(tmp_path, monkeypatch):
    monkeypatch.setattr(simulation, "ROOT", tmp_path)
    rows = simulation.catalog()
    rows[0] = dict(rows[0])
    rows[0]["media_path"] = "../C-014.mp4"
    with pytest.raises(RuntimeError, match="outside the workspace root"):
        simulation.validate_catalog(rows)


def test_snapshot_publisher_count_reflects_only_live_processes_after_stop():
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")

    class _FakeProc:
        def __init__(self):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self._alive = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self._alive = False

    fake_proc = _FakeProc()
    slot = simulation._SimulationSlot(
        camera_id=row["camera_id"], media_path=row["media_path"],
        proc=fake_proc, ready=True)
    with relay._lock:
        relay._slots[row["camera_id"]] = slot
    relay._started = True

    snap = relay.snapshot()
    assert snap["publisher_count"] == 1
    assert snap["catalog_count"] == 30

    relay.stop()

    snap = relay.snapshot()
    assert snap["publisher_count"] == 0
    assert snap["catalog_count"] == 30


def test_snapshot_current_fps_never_fabricated_when_ready():
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")
    slot = simulation._SimulationSlot(
        camera_id=row["camera_id"], media_path=row["media_path"],
        proc=None, ready=True)
    with relay._lock:
        relay._slots[row["camera_id"]] = slot

    snap = relay.snapshot()
    cam = next(c for c in snap["cameras"] if c["camera_id"] == "CAM-001")
    assert cam["ready"] is True
    assert cam["current_fps"] is None


def test_simulation_relay_has_wait_ready_and_inbound_bytes_methods():
    assert hasattr(simulation.SimulationRelay, "_wait_ready")
    assert hasattr(simulation.SimulationRelay, "_has_inbound_bytes")


def test_ready_false_for_absent_camera():
    relay = simulation.SimulationRelay()
    assert relay.ready("CAM-001") is False


def test_ready_false_for_stopped_camera():
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")
    slot = simulation._SimulationSlot(
        camera_id=row["camera_id"], media_path=row["media_path"],
        proc=None, ready=False)
    with relay._lock:
        relay._slots[row["camera_id"]] = slot
    assert relay.ready("CAM-001") is False


def test_ready_true_with_injected_ready_slot():
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")
    slot = simulation._SimulationSlot(
        camera_id=row["camera_id"], media_path=row["media_path"],
        proc=None, ready=True)
    with relay._lock:
        relay._slots[row["camera_id"]] = slot
    assert relay.ready("CAM-001") is True


def test_boot_simulation_failure_does_not_raise_nameerror_and_clears_singleton(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "")
    monkeypatch.setenv("SAAKSHYA_DEMO_SIMULATION", "1")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(simulation, "get_simulation", lambda: None)
    simulation.set_simulation(None)

    def _boom(self, rows=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(simulation.SimulationRelay, "start", _boom)
    try:
        result = simulation.boot_simulation()
        assert result is None
        assert simulation.get_simulation() is None
    finally:
        simulation.set_simulation(None)


def test_catalog_import_does_not_affect_seed_50_evaluation():
    from saakshya.command.scale import seed_50_evaluation
    from saakshya.store.repository import Store

    store = Store("sqlite:///:memory:")
    store.create_all()
    result = seed_50_evaluation(store)
    assert result.get("onboarded") == 50 or len(store.list_cameras()) == 50
