"""Backend integration for the opt-in isolated 30-channel archival replay plane.

Uses stubs/mocks only — no subprocess, no network — to prove: the feature
never boots unless explicitly opted in, /config never claims government or
simulation video is browser-confirmed live, the registry endpoint serves the
static 30-camera catalog under the ARCHIVAL_REPLAY label, and the WHEP proxy
refuses unknown or not-ready cameras before ever forwarding anything.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.live import simulation
from saakshya.security import Role


def _state(tmp_path) -> AppState:
    return AppState(f"sqlite:///{tmp_path / 'sim.db'}", evidence_root=tmp_path / "evidence")


def _client(state: AppState) -> TestClient:
    return TestClient(create_app(state=state))


def _admin_headers(state: AppState) -> dict[str, str]:
    state.tokens.upsert_user("admin.sim", Role.ADMIN)
    token = state.tokens.mint("admin.sim")
    return {"Authorization": f"Bearer {token}"}


def test_simulation_enabled_false_under_pytest(monkeypatch):
    monkeypatch.setenv("SAAKSHYA_DEMO_SIMULATION", "1")
    assert simulation.simulation_enabled() is False


def test_simulation_enabled_requires_opt_in(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SAAKSHYA_DEMO_SIMULATION", raising=False)
    try:
        assert simulation.simulation_enabled() is False
        monkeypatch.setenv("SAAKSHYA_DEMO_SIMULATION", "true")
        assert simulation.simulation_enabled() is True
        monkeypatch.setenv("SAAKSHYA_DEMO_SIMULATION", "0")
        assert simulation.simulation_enabled() is False
    finally:
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "restored")


def test_boot_simulation_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(simulation, "simulation_enabled", lambda: False)
    assert simulation.boot_simulation() is None


def test_boot_simulation_cleans_up_only_its_own_instance_on_failure(monkeypatch):
    monkeypatch.setattr(simulation, "simulation_enabled", lambda: True)
    monkeypatch.setattr(simulation, "get_simulation", lambda: None)
    stopped = {"called": False}

    class _FailingRelay(simulation.SimulationRelay):
        def start(self, rows=None):
            raise RuntimeError("binaries unavailable")

        def stop(self):
            stopped["called"] = True

    monkeypatch.setattr(simulation, "SimulationRelay", _FailingRelay)
    result = simulation.boot_simulation()
    assert result is None
    assert stopped["called"] is True
    assert simulation.get_simulation() is None


def test_config_does_not_claim_simulation_or_government_browser_live(tmp_path):
    state = _state(tmp_path)
    client = _client(state)
    resp = client.get("/config", headers=_admin_headers(state))
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"]["relay"] is False
    assert body["simulation"]["enabled"] is False
    assert body["simulation"]["available"] is False
    for key in ("local_port", "rtsp_port", "whep_port", "api_port", "credential", "password"):
        assert key not in body["simulation"]


def test_registry_returns_503_when_disabled(tmp_path):
    state = _state(tmp_path)
    client = _client(state)
    resp = client.get("/demo-simulation/cameras", headers=_admin_headers(state))
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "SIMULATION_DISABLED"


def test_status_reports_disabled_without_fake_readiness(tmp_path):
    state = _state(tmp_path)
    client = _client(state)
    resp = client.get("/demo-simulation/status", headers=_admin_headers(state))
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["started"] is False
    assert body["ready_count"] == 0


def test_registry_uses_30_catalog_and_archival_replay_label(tmp_path, monkeypatch):
    state = _state(tmp_path)
    relay = simulation.SimulationRelay()
    state.simulation = relay
    client = _client(state)
    resp = client.get("/demo-simulation/cameras", headers=_admin_headers(state))
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_domain"] == "ARCHIVAL_REPLAY"
    assert body["label"] == "LIVE SIMULATION / ARCHIVAL REPLAY"
    assert body["catalog_count"] == 30
    assert len(body["cameras"]) == 30
    for cam in body["cameras"]:
        assert cam["source_domain"] == "ARCHIVAL_REPLAY"
        assert cam["demo_label"] == "LIVE SIMULATION / ARCHIVAL REPLAY"
        assert cam["browser_live"] is None
        assert cam["ready"] is False
        assert cam["asset_duration_s"] == 240
        assert cam["replay_end"] == 12 * 60 * 60


def test_whep_rejects_unknown_camera_before_forwarding(tmp_path):
    state = _state(tmp_path)
    relay = simulation.SimulationRelay()
    state.simulation = relay
    client = _client(state)
    resp = client.post(
        "/demo-simulation/cameras/CAM-999/whep",
        headers=_admin_headers(state), content=b"v=0")
    assert resp.status_code == 404


def test_whep_refuses_when_disabled_before_forwarding(tmp_path):
    state = _state(tmp_path)
    client = _client(state)
    resp = client.post(
        "/demo-simulation/cameras/CAM-001/whep",
        headers=_admin_headers(state), content=b"v=0")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "SIMULATION_DISABLED"


def test_whep_refuses_not_ready_camera_before_forwarding(tmp_path):
    state = _state(tmp_path)
    relay = simulation.SimulationRelay()
    state.simulation = relay
    client = _client(state)
    resp = client.post(
        "/demo-simulation/cameras/CAM-001/whep",
        headers=_admin_headers(state), content=b"v=0")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "SIMULATION_NOT_READY"


def test_whep_never_sends_sentinel_credential(tmp_path, monkeypatch):
    state = _state(tmp_path)
    relay = simulation.SimulationRelay()
    row = next(c for c in simulation.catalog() if c["camera_id"] == "CAM-001")
    slot = simulation._SimulationSlot(
        camera_id=row["camera_id"], media_path=row["media_path"],
        proc=None, ready=True)
    with relay._lock:
        relay._slots[row["camera_id"]] = slot
    state.simulation = relay
    client = _client(state)

    captured = {}

    class _FakeResp:
        status = 201

        def read(self):
            return b"v=0\r\n"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=8):
        captured["headers"] = dict(req.header_items())
        captured["url"] = req.full_url
        return _FakeResp()

    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", _fake_urlopen)

    resp = client.post(
        "/demo-simulation/cameras/CAM-001/whep",
        headers=_admin_headers(state), content=b"v=0")
    assert resp.status_code == 201
    assert "Authorization" not in captured.get("headers", {})
    assert "28889" in captured.get("url", "")
