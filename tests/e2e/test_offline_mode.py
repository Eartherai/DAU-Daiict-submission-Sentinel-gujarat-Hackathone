"""End-to-end: a district node runs through a total loss of its uplink.

This is the scenario the architecture exists for. A district station loses
connectivity — a cut fibre, a power event, a saturated link during exactly the
incident that matters — and must keep detecting, matching its watchlist,
alerting locally and sealing evidence. When the link returns, everything that
happened in the dark must arrive at the centre exactly once, in the order it
was observed.

The test asserts the outcome an operator cares about, not the mechanism:

    link DOWN  → target detected, watchlist hit, alert raised, evidence sealed
    link UP    → queued events replay, central timeline reconstructed,
                 no duplicates, no loss

It runs the real classes with a real SQLite store on both sides. The only thing
faked is the wire, and it is faked by switching a flag on an in-process link —
the same code path a socket failure takes.
"""
from __future__ import annotations

import pytest

from saakshya.edge import (
    CentralReceiver,
    EdgeConfig,
    EdgeNode,
    HashOnlyVerifier,
    HmacVerifier,
    InProcessLink,
    MissingKeyMaterial,
)
from saakshya.evidence import EvidenceService
from saakshya.store import SearchFilter, Store
from saakshya.watchlist import (
    AlertEngine,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistBundle,
    WatchlistService,
)
from tests.conftest import make_observation

NODE = "node-district-01"
TARGET = "GJ18XY7788"
CAMERAS = ("EDGE-11", "EDGE-12", "EDGE-13")


@pytest.fixture
def deployment(tmp_path):
    """A central store and an edge node, wired together but not yet syncing."""
    central = Store(f"sqlite:///{tmp_path / 'central.db'}")
    central.create_all()
    edge_store = Store(f"sqlite:///{tmp_path / 'edge.db'}")
    edge_store.create_all()

    for i, cam in enumerate(CAMERAS):
        row = {"camera_id": cam, "name": f"Edge camera {i}",
               "district": "Ahmedabad", "department": "Home (Traffic)",
               "lat": 23.02 + i * 0.01, "lon": 72.58 + i * 0.01,
               "tier": "B", "enabled": True}
        central.upsert_camera(row)
        edge_store.upsert_camera(row)

    receiver = CentralReceiver(central)
    link = InProcessLink(receiver)
    node = EdgeNode(edge_store, EdgeConfig(node_id=NODE, site="District HQ",
                                           district="Ahmedabad"),
                    link=link, state_dir=tmp_path / "edgestate")
    return {"central": central, "edge": edge_store, "node": node, "link": link,
            "receiver": receiver, "tmp": tmp_path}


def _bundle() -> WatchlistBundle:
    voi = VehicleOfInterest(
        plate=TARGET, category=Category.STOLEN_VEHICLE,
        authority="SP Ahmedabad Rural, FIR 411/2026",
        reason="reported stolen 2026-08-28", priority=Priority.HIGH,
        jurisdiction="Ahmedabad", created_by="supervisor.test")
    return WatchlistBundle.build([voi], issuer="saakshya-central")


# --------------------------------------------------------------------------- #
# Watchlist distribution
# --------------------------------------------------------------------------- #
def test_01_node_accepts_a_valid_bundle(deployment):
    result = deployment["node"].install_bundle(_bundle())
    assert result["accepted"], result["checks"]
    assert len(deployment["node"].local_watchlist()) == 1
    # The limitation must travel with the bundle, not be buried in a doc.
    assert "NOT authenticated" in result["caveat"]


def test_02_node_refuses_a_tampered_bundle(deployment):
    node = deployment["node"]
    node.install_bundle(_bundle())
    good = node.local_watchlist()

    bad = _bundle()
    bad.entries[0]["plate"] = "GJ99ZZ0000"        # content changed, hash not
    result = node.install_bundle(bad)

    assert not result["accepted"], "a tampered bundle was accepted"
    assert any(c["check"] == "integrity" and not c["ok"] for c in result["checks"])
    # Crucially: it kept the one it had. It did not end up with no watchlist.
    assert node.local_watchlist() == good


def test_03_node_refuses_a_rollback(deployment):
    node = deployment["node"]
    first = _bundle()
    node.install_bundle(first)
    result = node.install_bundle(first)
    assert not result["accepted"]
    assert any(c["check"] == "version" and not c["ok"] for c in result["checks"])


def test_04_untrusted_issuer_is_refused(deployment):
    node = EdgeNode(deployment["edge"],
                    EdgeConfig(node_id="node-strict",
                               trusted_issuers=("saakshya-central",)),
                    state_dir=deployment["tmp"] / "strict")
    forged = WatchlistBundle.build(
        [VehicleOfInterest(plate=TARGET, category=Category.STOLEN_VEHICLE,
                           authority="unknown", reason="unknown",
                           priority=Priority.HIGH, created_by="?")],
        issuer="someone-else")
    result = node.install_bundle(forged)
    assert not result["accepted"]
    assert any(c["check"] == "issuer" and not c["ok"] for c in result["checks"])


def test_05_hmac_verifier_requires_provisioned_key(monkeypatch):
    monkeypatch.delenv("SAAKSHYA_BUNDLE_KEY", raising=False)
    with pytest.raises(MissingKeyMaterial) as exc:
        HmacVerifier()
    assert "must not be written into configuration" in str(exc.value)


def test_06_hash_verifier_does_not_claim_to_authenticate():
    outcome = HashOnlyVerifier().verify(_bundle())
    assert outcome.accepted
    assert outcome.authenticates_issuer is False


# --------------------------------------------------------------------------- #
# The outage
# --------------------------------------------------------------------------- #
@pytest.fixture
def outage(deployment):
    """Run the target through three cameras with the link down."""
    node, edge = deployment["node"], deployment["edge"]
    node.install_bundle(_bundle())
    deployment["link"].up = False                     # ---- link goes down ----

    observations = [
        make_observation(CAMERAS[0], plate=TARGET, offset_s=0, track="TA"),
        make_observation(CAMERAS[1], plate=TARGET, offset_s=240, track="TB"),
        make_observation(CAMERAS[2], plate=TARGET, offset_s=520, track="TC"),
        # Two other vehicles, so the test is not a single-row special case.
        make_observation(CAMERAS[0], plate="GJ01ZZ0001", offset_s=30, track="TD"),
        make_observation(CAMERAS[1], plate="GJ01ZZ0002", offset_s=300, track="TE"),
    ]
    recorded = node.record(observations)

    hits = [o for o in observations if node.match(o)]
    evidence = EvidenceService(edge, root=deployment["tmp"] / "edge_evidence")
    sealed = [evidence.create(o, device=f"edge:{NODE}") for o in hits]

    return {**deployment, "observations": observations, "recorded": recorded,
            "hits": hits, "sealed": sealed, "evidence": evidence}


def test_10_detection_continues_with_the_link_down(outage):
    assert outage["recorded"]["stored"] == 5, "local persistence stopped"
    assert outage["recorded"]["queued"] == 5, "events were not queued for replay"
    stored = outage["edge"].search(SearchFilter(limit=100))
    assert len(stored) == 5


def test_11_watchlist_matching_is_local(outage):
    assert len(outage["hits"]) == 3, "the local watchlist did not match"
    assert {o.camera_id for o in outage["hits"]} == set(CAMERAS)


def test_12_alerts_are_raised_locally(outage):
    """The alert is raised on the node, from the node's own watchlist."""
    wl = WatchlistService(outage["edge"])
    entry = outage["node"].local_watchlist()[0]
    wl.add(VehicleOfInterest(
        plate=entry["plate"], category=Category(entry["category"]),
        authority=entry["authority"], reason=entry["reason"],
        priority=Priority(entry["priority"]), jurisdiction=entry["jurisdiction"],
        created_by="edge-node"), actor=f"edge:{NODE}")
    engine = AlertEngine(outage["edge"])
    raised = [a for o in outage["hits"] for m in wl.match(o)
              if (a := engine.process(m))]
    assert raised, "no alert was raised while offline"
    assert len({a.alert_id for a in raised}) == 1, "one vehicle produced many alerts"


def test_13_evidence_is_sealed_and_verifies_offline(outage):
    assert len(outage["sealed"]) == 3
    for m in outage["sealed"]:
        assert outage["evidence"].verify(m.evidence_id).ok
    assert outage["evidence"].verify_chain().ok


def test_14_nothing_reached_the_centre_yet(outage):
    assert outage["central"].stats()["observations"] == 0
    rep = outage["node"].sync()
    assert rep.link_up is False
    assert rep.remaining == 5, "events were lost while the link was down"


def test_15_queue_reports_its_backlog(outage):
    stats = outage["node"].queue.stats()
    assert stats["pending"] == 5
    assert stats["oldest_pending_age_s"] is not None
    assert outage["node"].status()["mode"].startswith("LOCAL")


# --------------------------------------------------------------------------- #
# Reconnection
# --------------------------------------------------------------------------- #
def test_20_replay_reconstructs_the_central_timeline(outage):
    outage["link"].up = True                          # ---- link returns ----
    rep = outage["node"].sync()

    assert rep.link_up, rep.error
    assert rep.acknowledged == 5, f"only {rep.acknowledged} of 5 acknowledged"
    assert rep.remaining == 0, "the queue did not drain"

    central = outage["central"].search(SearchFilter(limit=100))
    assert len(central) == 5, "events were lost in replay"

    # Ordering is by observation time, recovered from PTS — not by arrival.
    times = [o.t_norm for o in sorted(central, key=lambda x: x.t_norm)]
    assert times == sorted(times)
    target_path = [o.camera_id for o in
                   sorted((o for o in central if o.plate == TARGET),
                          key=lambda x: x.t_norm)]
    assert target_path == list(CAMERAS), f"route came back scrambled: {target_path}"


def test_21_replaying_twice_creates_no_duplicates(outage):
    outage["link"].up = True
    outage["node"].sync()
    before = outage["central"].stats()["observations"]

    # Force a full replay: exactly what happens when acknowledgements are lost.
    from sqlalchemy import update

    from saakshya.store import schema as S
    with outage["edge"].engine.begin() as c:
        c.execute(update(S.edge_queue).values(state="PENDING", acked_at_us=None))
    outage["node"].queue._seq = outage["node"].queue._last_sequence()

    second = outage["receiver"].receive(NODE, [
        e.to_dict() for e in outage["node"].queue.pending(100)])

    assert second.received == 5
    assert second.applied == 0, "a replay created new rows"
    assert second.duplicates == 5, "duplicates were not detected and reported"
    assert outage["central"].stats()["observations"] == before


def test_22_partial_delivery_retries_the_rest(outage):
    """A centre that accepts only part of a batch must not lose the remainder."""
    outage["link"].up = True

    class PartialReceiver:
        def __init__(self, inner):
            self.inner = inner

        def receive(self, node_id, events):
            result = self.inner.receive(node_id, events[:2])
            # Acknowledge only what was applied — the rest must come back.
            result.acknowledged = result.acknowledged[:2]
            result.received = len(events)
            return result

    outage["link"].receiver = PartialReceiver(outage["receiver"])
    rep = outage["node"].sync(max_batches=1)
    assert rep.acknowledged == 2
    assert rep.failed == 3
    assert outage["node"].queue.depth() == 3, "unacknowledged events were dropped"

    outage["link"].receiver = outage["receiver"]
    rep2 = outage["node"].sync()
    assert rep2.remaining == 0
    assert outage["central"].stats()["observations"] == 5


def test_23_acknowledged_events_are_kept_until_purged(outage):
    outage["link"].up = True
    outage["node"].sync()
    stats = outage["node"].queue.stats()
    assert stats["by_state"].get("ACKED") == 5, \
        "events were deleted on send rather than acknowledged"
    assert outage["node"].queue.purge_acked(older_than_s=0.0) == 5


def test_24_central_records_the_node(outage):
    outage["link"].up = True
    outage["node"].sync()
    from sqlalchemy import select

    from saakshya.store import schema as S
    with outage["central"].engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(select(S.edge_nodes))]
    assert len(rows) == 1
    assert rows[0]["node_id"] == NODE
    assert rows[0]["state"] == "SYNCED"
    assert rows[0]["last_ack_sequence"] == 5


def test_25_the_replay_is_audited(outage):
    outage["link"].up = True
    outage["node"].sync()
    ok, err = outage["central"].verify_audit_chain()
    assert ok, err
