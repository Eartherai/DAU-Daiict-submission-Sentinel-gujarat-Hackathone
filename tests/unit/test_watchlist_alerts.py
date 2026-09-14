"""Watchlist versioning and alert policy: attribution, dedup, escalation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saakshya.store import Store, VehicleObservation
from saakshya.watchlist import (
    ADAPTERS,
    AlertEngine,
    Category,
    Priority,
    Status,
    VehicleOfInterest,
    WatchlistBundle,
    WatchlistService,
)

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)


def ob(cam, plate, sec, key, q=0.9, conf=0.98, votes=12):
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(camera_id=cam, pts_s=sec, t_norm=t, t_ingest=t,
                              dedup_key=key, plate=plate, object_type="car",
                              observation_quality=q, plate_confidence=conf,
                              plate_votes=votes)


@pytest.fixture
def wired():
    s = Store("sqlite:///:memory:")
    s.create_all()
    for cid in ["C-014", "C-021", "C-033", "C-047"]:
        s.upsert_camera({"camera_id": cid, "district": "Ahmedabad", "tier": "A"})
    return s, WatchlistService(s), AlertEngine(s)


def stolen(plate="GJ05AB1234", **kw) -> VehicleOfInterest:
    kw.setdefault("priority", Priority.HIGH)
    return VehicleOfInterest(
        plate=plate, category=Category.STOLEN_VEHICLE,
        authority="SP Ahmedabad Rural, FIR 123/2026",
        reason="reported stolen 2026-08-20",
        jurisdiction="Ahmedabad", created_by="officer.a", **kw)


# --------------------------------------------------------------------------- #
# Attribution and lifecycle
# --------------------------------------------------------------------------- #
def test_match_carries_authority_reason_and_version(wired):
    _s, wl, _ = wired
    wl.add(stolen())
    m = wl.match(ob("C-014", "GJ05AB1234", 10, "a"))[0]
    assert m.entry.authority.startswith("SP Ahmedabad")
    assert "stolen" in m.entry.reason
    assert m.entry.version == 1
    assert "authorised by" in m.explanation


def test_revoked_entry_never_matches(wired):
    _s, wl, _ = wired
    e = wl.add(stolen())
    wl.revoke(e.watchlist_id, actor="officer.b", reason="vehicle recovered")
    assert wl.match(ob("C-014", "GJ05AB1234", 10, "b")) == []


def test_expired_entry_never_matches(wired):
    _s, wl, _ = wired
    wl.add(stolen(valid_until=T0 - timedelta(days=1)))
    assert wl.match(ob("C-014", "GJ05AB1234", 10, "c")) == []


def test_not_yet_in_force_entry_never_matches(wired):
    _s, wl, _ = wired
    wl.add(stolen(valid_from=T0 + timedelta(days=1)))
    assert wl.match(ob("C-014", "GJ05AB1234", 10, "d")) == []


def test_amendment_creates_a_new_version_and_preserves_history(wired):
    _s, wl, _ = wired
    e = wl.add(stolen())
    v2 = wl.amend(e.watchlist_id, actor="officer.c", priority=Priority.CRITICAL)
    assert v2.version == 2
    assert wl.get(e.watchlist_id).status is Status.SUPERSEDED
    active = wl.active_entries("GJ05AB1234")
    assert len(active) == 1 and active[0].version == 2
    # The superseded row is retained, so an old alert stays explicable.
    assert wl.get(e.watchlist_id) is not None


def test_attributes_alone_never_produce_a_watchlist_hit(wired):
    """'A white car' is not a vehicle of interest. Alerting on attributes would
    flood the operator and erode trust in every genuine alert."""
    _s, wl, _ = wired
    wl.add(stolen())
    assert wl.match(ob("C-014", None, 10, "e")) == []


# --------------------------------------------------------------------------- #
# Alert policy
# --------------------------------------------------------------------------- #
def test_alert_is_generated_with_full_explanation(wired):
    _s, wl, ae = wired
    wl.add(stolen())
    m = wl.match(ob("C-014", "GJ05AB1234", 10, "f"))[0]
    a = ae.process(m)
    assert a is not None
    e = a.explain()
    for k in ("what_matched", "why", "where", "when", "how_strong",
              "evidence", "operator_action"):
        assert k in e, f"alert explanation missing {k}"
    assert e["authority"].startswith("SP Ahmedabad")


def test_a_single_vote_watchlist_hit_alerts_but_is_flagged(wired):
    """A stolen vehicle seen once must not vanish, and must not look confirmed."""
    _s, wl, ae = wired
    wl.add(stolen())
    m = wl.match(ob("C-014", "GJ05AB1234", 10, "lead", votes=1))[0]
    a = ae.process(m)
    assert a is not None
    assert any("single frame" in n for n in a.notes)
    assert a.terms.get("corroborated") is False


def test_low_confidence_is_suppressed_not_emitted(wired):
    _s, wl, ae = wired
    wl.add(stolen())
    m = wl.match(ob("C-014", "GJ05AB1234", 10, "g", q=0.1, conf=0.3))[0]
    assert ae.process(m) is None
    assert ae.stats()["suppressed_low_confidence"] == 1


def test_repeat_sightings_update_one_alert_rather_than_raising_many(wired):
    """One vehicle across four cameras is one investigation-worthy event."""
    _s, wl, ae = wired
    wl.add(stolen())
    ids = set()
    for i, cam in enumerate(["C-014", "C-021", "C-033", "C-047"]):
        m = wl.match(ob(cam, "GJ05AB1234", 10 + i * 60, f"h{i}"))[0]
        a = ae.process(m)
        assert a is not None
        ids.add(a.alert_id)
    assert len(ids) == 1, f"deduplication failed: {len(ids)} alerts"
    assert ae.stats()["deduplicated_sightings"] == 3
    assert len(ae.list_alerts()) == 1


def test_multiple_cameras_escalate_priority(wired):
    _s, wl, ae = wired
    wl.add(stolen(priority=Priority.MEDIUM))
    last = None
    for i, cam in enumerate(["C-014", "C-021", "C-033"]):
        m = wl.match(ob(cam, "GJ05AB1234", 10 + i * 60, f"i{i}"))[0]
        last = ae.process(m)
    assert last.priority == str(Priority.HIGH), f"got {last.priority}"
    assert any("escalated" in n for n in last.notes)


def test_low_quality_alert_is_marked_for_verification(wired):
    _s, wl, ae = wired
    wl.add(stolen())
    m = wl.match(ob("C-014", "GJ05AB1234", 10, "j", q=0.3, conf=0.95))[0]
    a = ae.process(m)
    assert a is not None
    assert "VERIFY" in a.recommended_action
    assert any("low" in n.lower() for n in a.notes)


def test_cleared_alert_does_not_block_a_genuinely_new_one(wired):
    _s, wl, ae = wired
    wl.add(stolen())
    m1 = wl.match(ob("C-014", "GJ05AB1234", 10, "k"))[0]
    a1 = ae.process(m1)
    ae.clear(a1.alert_id, actor="officer.d", reason="verified, wrong vehicle",
             false_positive=True)
    # Well outside the cooldown window.
    m2 = wl.match(ob("C-021", "GJ05AB1234", 10 + 5000, "l"))[0]
    a2 = ae.process(m2)
    assert a2 is not None and a2.alert_id != a1.alert_id


# --------------------------------------------------------------------------- #
# Edge bundle
# --------------------------------------------------------------------------- #
def test_bundle_verifies_and_detects_tampering(wired):
    _s, wl, _ = wired
    wl.add(stolen())
    wl.add(stolen(plate="GJ01CD5678"))
    b = WatchlistBundle.build(wl.active_entries(), issuer="SCRB Gandhinagar")
    ok, msg = b.verify()
    assert ok, msg

    b.entries[0]["plate"] = "GJ99ZZ9999"
    ok, msg = b.verify()
    assert not ok and "FAILED" in msg


def test_bundle_does_not_claim_to_authenticate_its_issuer(wired):
    """We have no PKI. The bundle must say so rather than imply a signature."""
    _s, wl, _ = wired
    wl.add(stolen())
    b = WatchlistBundle.build(wl.active_entries(), issuer="SCRB")
    d = b.to_dict()
    assert "signature" not in d
    assert "does not authenticate" in d["integrity_caveat"].lower()
    _ok, msg = b.verify()
    assert "issuer not authenticated" in msg


def test_bundle_roundtrips(wired):
    _s, wl, _ = wired
    wl.add(stolen())
    b = WatchlistBundle.build(wl.active_entries(), issuer="SCRB")
    again = WatchlistBundle.from_dict(b.to_dict())
    assert again.verify()[0]


# --------------------------------------------------------------------------- #
# Government adapters
# --------------------------------------------------------------------------- #
def test_government_adapters_refuse_to_pretend(wired):
    """No code path may imply a live government integration."""
    for adapter in ADAPTERS.values():
        with pytest.raises(NotImplementedError) as ei:
            adapter.fetch()
        assert "stub" in str(ei.value).lower() or "credentials" in str(ei.value).lower()
