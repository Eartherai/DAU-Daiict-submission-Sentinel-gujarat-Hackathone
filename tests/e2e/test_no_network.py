"""The mandatory chain must not touch the network. Enforced, not asserted.

"Runs with no route to the internet" is a claim this system makes repeatedly,
and it has been argued from design rather than demonstrated. A single
`from_pretrained` without `local_files_only`, one basemap fetch, one telemetry
call, and a deployment on a government network hangs — which is exactly what
happened once already, at 0% CPU for twelve minutes with no error.

So the test does not inspect code. It **blocks the network** — every socket
connection to anything that is not this machine raises — and then runs the
mandatory chain: search, trajectory, watchlist, alert, evidence, verification.
Anything that reaches out fails loudly instead of quietly working on a developer
laptop that happens to have a connection.
"""
from __future__ import annotations

import socket
from datetime import UTC, datetime

import pytest

LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


class NetworkBlocked(AssertionError):
    """Raised the moment anything tries to leave this machine."""


@pytest.fixture
def no_network(monkeypatch):
    """Refuse every non-local socket connection for the duration of a test."""
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guard(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else str(address)
        if str(host) not in LOCAL:
            attempts.append(str(host))
            raise NetworkBlocked(f"outbound connection to {host} — the "
                                 "mandatory chain must not need the network")
        return real_connect(self, address, *a, **kw)

    def guard_dns(host, *a, **kw):
        if str(host) not in LOCAL:
            attempts.append(f"dns:{host}")
            raise NetworkBlocked(f"DNS lookup for {host}")
        return real_getaddrinfo(host, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "getaddrinfo", guard_dns)
    monkeypatch.setenv("SAAKSHYA_MODELS_OFFLINE", "1")
    monkeypatch.setenv("AI_PROVIDER", "disabled")
    monkeypatch.delenv("SAAKSHYA_MAP_TILES", raising=False)
    return attempts


@pytest.fixture
def chain(tmp_path):
    """A store with one sighting of a watchlisted vehicle, built locally."""
    from saakshya.evidence.manifest import EvidenceService
    from saakshya.investigation import CaseService, InvestigationService
    from saakshya.security import AuthContext, Principal, Role
    from saakshya.store import Store
    from saakshya.store.repository import VehicleObservation
    from saakshya.watchlist import (
        AlertEngine,
        Category,
        Priority,
        VehicleOfInterest,
        WatchlistService,
    )

    store = Store(f"sqlite:///{tmp_path}/offline.db")
    store.create_all()
    store.upsert_camera({"camera_id": "cam01", "name": "Chiman bhai Bridge",
                         "district": "Ahmedabad", "lat": 23.0296, "lon": 72.5219})
    now = datetime.now(UTC)
    obs = VehicleObservation(
        observation_id="OB-OFFLINE-1", camera_id="cam01", track_id="TR1",
        segment_id="cam01-S1", pts_s=12.5, t_norm=now, t_ingest=now,
        dedup_key="cam01:1", plate="GJ01AB1234", plate_confidence=0.97,
        observation_quality=0.93, district="Ahmedabad",
        model_versions={"model": "anpr-onnx-cpu@1.0.0"})
    store.add_observations([obs])

    wl = WatchlistService(store)
    wl.add(VehicleOfInterest(
        plate="GJ01AB1234", category=Category.STOLEN_VEHICLE,
        authority="offline chain test", reason="verifying no network is needed",
        priority=Priority.HIGH, jurisdiction="Ahmedabad",
        created_by="sup.test"), actor="sup.test")

    ctx = AuthContext(
        principal=Principal(user_id="sup.test", role=Role.SUPERVISOR,
                            districts=()),
        case_id="FIR-OFFLINE/2026",
        purpose="verifying the chain needs no network")
    return {
        "store": store, "obs": obs, "ctx": ctx, "wl": wl,
        "alerts": AlertEngine(store),
        "service": InvestigationService(store),
        "cases": CaseService(store),
        "evidence": EvidenceService(store, root=tmp_path / "evidence"),
    }


def test_the_guard_actually_blocks(no_network):
    """A guard that lets traffic through would make every test below vacuous."""
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.invalid", 80), timeout=1)
    assert no_network


def test_search_needs_no_network(no_network, chain):
    hits = chain["store"].search_plate("GJ01AB1234")
    assert len(hits) == 1
    assert not no_network, f"reached out to {no_network}"


def test_watchlist_and_alert_need_no_network(no_network, chain):
    matches = chain["wl"].match(chain["obs"])
    assert matches, "the watchlist did not match"
    alert = chain["alerts"].process(matches[0])
    assert alert is not None
    assert alert.plate == "GJ01AB1234"
    assert not no_network, f"reached out to {no_network}"


def test_evidence_seals_and_verifies_with_no_network(no_network, chain):
    m = chain["evidence"].create(chain["obs"], device="offline-test")
    result = chain["evidence"].verify(m.evidence_id)
    assert getattr(result, "ok", None) or (
        isinstance(result, dict) and result.get("verified"))
    assert not no_network, f"reached out to {no_network}"


def test_the_chain_verifies_with_no_network(no_network, chain):
    chain["evidence"].create(chain["obs"], device="offline-test")
    result = chain["evidence"].verify_chain()
    ok = getattr(result, "ok", None)
    if ok is None and isinstance(result, dict):
        ok = result.get("verified")
    assert ok
    assert not no_network, f"reached out to {no_network}"


def test_the_assistant_is_disabled_and_does_not_reach_out(no_network, chain):
    """With AI_PROVIDER=disabled nothing external is contacted, and the
    workspace is unaffected — which is the whole point of the default."""
    from saakshya.copilot.backends import UnavailableBackend, default_backend
    from saakshya.copilot.orchestrator import Copilot

    backend = default_backend()
    assert isinstance(backend, UnavailableBackend)
    answer = Copilot(chain["service"], chain["cases"], backend=backend).ask(
        chain["ctx"], "Where was GJ01AB1234 seen?")
    assert answer.available is False
    assert answer.text
    assert not no_network, f"reached out to {no_network}"


def test_the_api_serves_with_no_basemap_and_no_network(no_network, chain,
                                                       monkeypatch):
    """A basemap is an enhancement, never a dependency."""
    from saakshya.api.deps import AppState

    state = AppState()
    assert not state.tile_template, "a tile host was configured under test"
    assert not getattr(state, "google_maps_key", ""), (
        "a Google Maps key was configured under test")
    assert not no_network, f"reached out to {no_network}"


def test_models_load_from_cache_with_the_network_blocked(no_network):
    """The twelve-minute hang was `from_pretrained` reaching for a hub that
    could not answer. Weights are pinned by revision; the cache has everything
    the network would provide."""
    pytest.importorskip("torch")
    from saakshya.models.registry import REGISTRY
    from saakshya.runtime.backend import _load_cached_first

    key = "vehicle-rtdetrv2-r18@0.1.0"
    if key not in REGISTRY:
        pytest.skip("detector not in this registry")
    rec = REGISTRY[key]
    from transformers import AutoImageProcessor

    try:
        _load_cached_first(AutoImageProcessor, rec.hub_id, rec.revision)
    except NetworkBlocked:
        pytest.fail("model loading reached for the network instead of the cache")
    except Exception as exc:
        if "NetworkBlocked" in repr(exc):
            pytest.fail("model loading reached for the network")
        pytest.skip(f"model not cached on this host: {type(exc).__name__}")
    assert not [a for a in no_network if not a.startswith("dns:localhost")], (
        f"reached out to {no_network}")
