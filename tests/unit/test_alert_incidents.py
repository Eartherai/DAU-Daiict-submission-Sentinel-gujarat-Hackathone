"""The alert queue an officer works: incidents, honest priority, lifecycle.

Officers who used the Alerts view found 128 open rows that were really thirteen
vehicles, every one printed HIGH although forty rested on a single frame, and a
lifecycle that stopped at "Acknowledged". These tests pin the three fixes at
the service layer: grouping per (plate, watchlist entry), a shown priority that
drops a single-frame read one step and says why, and a New → Acknowledged →
Investigating → Resolved lifecycle whose every step is attributed and audited.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from saakshya.store import Store, VehicleObservation
from saakshya.store import schema as S
from saakshya.watchlist import (
    AlertEngine,
    AlertPolicy,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)
from saakshya.watchlist.incidents import (
    compare_plates,
    derive_priority,
    enrich,
    group,
    status_counts,
)

T0 = datetime(2026, 9, 21, 4, 0, 0, tzinfo=UTC)
# Fictional marks only. Real plates never go on a watchlist in test data.
PLATE_A = "GJ05ZZ0001"
PLATE_B = "GJ05ZZ0002"


def ob(cam, plate, minute, key, votes=4):
    t = T0 + timedelta(minutes=minute)
    return VehicleObservation(camera_id=cam, pts_s=minute * 60.0, t_norm=t,
                              t_ingest=t, dedup_key=key, plate=plate,
                              object_type="car", observation_quality=0.9,
                              plate_confidence=0.97, plate_votes=votes,
                              bbox=(100.0, 100.0, 400.0, 300.0),
                              district="Ahmedabad")


@pytest.fixture
def world():
    s = Store("sqlite:///:memory:")
    s.create_all()
    for cid in ("C-1", "C-2", "C-3"):
        s.upsert_camera({"camera_id": cid, "district": "Ahmedabad", "tier": "A"})
    wl = WatchlistService(s)
    # Cooldown shorter than the gaps below, so each sighting is its own alert
    # row, as it is on the evaluation store (alerts ~30 min apart).
    eng = AlertEngine(s, AlertPolicy(cooldown_s=60))
    return s, wl, eng


def listed(wl, plate, priority=Priority.HIGH):
    return wl.add(VehicleOfInterest(
        plate=plate, category=Category.WANTED_VEHICLE,
        authority="test authority", reason="fictional entry under test",
        priority=priority, jurisdiction="Ahmedabad"))


def raise_alert(s, wl, eng, o):
    s.add_observations([o])
    [m] = wl.match(o)
    return eng.process(m)


# --------------------------------------------------------------------------- #
# Priority
# --------------------------------------------------------------------------- #
def test_single_frame_read_is_not_shown_at_the_listed_priority():
    shown, why = derive_priority("HIGH", votes=1, cameras=1)
    assert shown == "MEDIUM"
    assert "single-frame" in why and "verify" in why


def test_voted_read_keeps_the_listed_priority_and_says_why():
    shown, why = derive_priority("HIGH", votes=6, cameras=1)
    assert shown == "HIGH"
    assert "6 frames" in why


def test_unknown_frame_count_is_treated_as_unverified_not_as_confirmed():
    shown, why = derive_priority("HIGH", votes=None, cameras=1)
    assert shown == "MEDIUM" and "verify" in why


def test_three_cameras_escalate_one_step():
    shown, why = derive_priority("HIGH", votes=1, cameras=3)
    assert shown == "CRITICAL" and "3 distinct cameras" in why


# --------------------------------------------------------------------------- #
# Read against list
# --------------------------------------------------------------------------- #
def test_exact_match_is_exact():
    c = compare_plates("GJ05ZZ0001", "GJ05ZZ0001")
    assert c["kind"] == "EXACT" and c["differing"] == 0
    assert all(p["state"] == "same" for p in c["positions"])


def test_ocr_lookalike_is_near_and_names_the_position():
    c = compare_plates("GJ05ZZ00O1", "GJ05ZZ0001")
    assert c["kind"] == "NEAR"
    diff = [p for p in c["positions"] if p["state"] != "same"]
    assert diff == [{"read": "O", "listed": "0", "state": "confusion"}]
    assert "O↔0" in c["summary"]


def test_a_genuinely_different_character_is_not_near():
    c = compare_plates("GJ05ZZ0071", "GJ05ZZ0001")
    assert c["kind"] == "DIFFERENT"


def test_missing_character_aligns_as_a_gap():
    c = compare_plates("GJ05Z0001", "GJ05ZZ0001")
    assert [p["state"] for p in c["positions"]].count("gap") == 1
    assert c["kind"] == "DIFFERENT"


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #
def _seed_many(world):
    """Two vehicles. A: 5 alerts on one camera across two passes. B: one
    single-frame alert."""
    s, wl, eng = world
    listed(wl, PLATE_A)
    listed(wl, PLATE_B)
    for k, minute in enumerate((0, 3, 6, 120, 124)):
        raise_alert(s, wl, eng, ob("C-1", PLATE_A, minute, f"a{k}"))
    raise_alert(s, wl, eng, ob("C-2", PLATE_B, 200, "b0", votes=1))
    return eng.list_alerts()


def test_many_alerts_about_two_vehicles_group_to_two_incidents(world):
    rows = _seed_many(world)
    assert len(rows) == 6
    groups = group(enrich(world[0], rows), window_s=600)
    assert len(groups) == 2
    a = next(g for g in groups if g["plate"] == PLATE_A)
    assert a["count"] == 5
    assert a["passes"] == 2, "a read two hours later is a second pass"
    assert a["camera_count"] == 1
    assert a["latest_alert_id"] == a["alert_ids"][-1]
    assert a["first_seen_us"] < a["last_seen_us"]


def test_window_is_configurable(world):
    rows = _seed_many(world)
    a = next(g for g in group(enrich(world[0], rows), window_s=60)
             if g["plate"] == PLATE_A)
    assert a["passes"] == 5, "with a one-minute window every read is its own pass"


def test_single_frame_incident_is_shown_lower_than_listed(world):
    rows = _seed_many(world)
    groups = group(enrich(world[0], rows))
    b = next(g for g in groups if g["plate"] == PLATE_B)
    assert b["listed_priority"] == "HIGH"
    assert b["display_priority"] == "MEDIUM"
    assert "single-frame" in b["priority_reason"]
    a = next(g for g in groups if g["plate"] == PLATE_A)
    assert a["display_priority"] == "HIGH"
    # Priority first, then recency: the voted HIGH incident outranks the
    # newer single-frame lead.
    assert groups[0]["plate"] == PLATE_A


def test_votes_come_from_observations_not_the_stale_alert_terms(world):
    """A repeat sighting replaced the alert's terms, dropping plate_votes, so
    reading votes there showed 'unknown' for well-voted reads."""
    s, wl, eng = world
    listed(wl, PLATE_A)
    raise_alert(s, wl, eng, ob("C-1", PLATE_A, 0, "x0", votes=9))
    [row] = eng.list_alerts()
    blob = json.loads(row["match_reason"])
    assert "plate_votes" not in blob["terms"]
    [e] = enrich(s, [row])
    assert e["plate_votes"] == 9 and e["corroborated"] is True


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def test_lifecycle_applies_to_a_whole_group_and_is_attributed(world):
    s, _wl, eng = world
    rows = _seed_many(world)
    a_ids = [r["alert_id"] for r in rows if r["plate"] == PLATE_A]
    res = eng.transition(a_ids, "acknowledge", actor="sup.1", group_id="g1")
    assert sorted(res["changed"]) == sorted(a_ids)
    res = eng.transition(a_ids, "investigate", actor="sup.1", case_id="FIR-7/2026")
    assert len(res["changed"]) == 5
    res = eng.transition(a_ids, "resolve", actor="sup.2",
                         disposition="false_positive", reason="misread: 0 for O")
    assert len(res["changed"]) == 5
    with s.engine.connect() as c:
        got = [r._mapping for r in c.execute(
            select(S.alerts).where(S.alerts.c.alert_id.in_(a_ids)))]
    for r in got:
        assert r["status"] == "FALSE_POSITIVE"
        assert r["disposition"] == "false_positive"
        assert r["case_id"] == "FIR-7/2026"
        steps = json.loads(r["lifecycle"])
        assert [x["action"] for x in steps] == ["acknowledge", "investigate", "resolve"]
        assert steps[0]["by"] == "sup.1" and steps[-1]["by"] == "sup.2"
        assert steps[-1]["reason"] == "misread: 0 for O"


def test_every_transition_is_in_the_hash_chained_audit_log(world):
    s, _wl, eng = world
    rows = _seed_many(world)
    ids = [r["alert_id"] for r in rows]
    eng.transition(ids, "acknowledge", actor="op.1")
    eng.transition(ids[:2], "resolve", actor="op.1", disposition="cleared",
                   reason="owner verified at checkpoint")
    with s.engine.connect() as c:
        log = [r._mapping for r in c.execute(select(S.audit_log))]
    acks = [r for r in log if r["action"] == "alert_acknowledge"]
    res = [r for r in log if r["action"] == "alert_resolve"]
    assert sorted(r["target"] for r in acks) == sorted(ids)
    assert len(res) == 2 and "cleared" in res[0]["purpose"]
    ok, _ = s.verify_audit_chain()
    assert ok


def test_resolve_requires_a_disposition_and_a_reason(world):
    _s, _wl, eng = world
    ids = [r["alert_id"] for r in _seed_many(world)]
    with pytest.raises(ValueError, match="disposition"):
        eng.transition(ids, "resolve", actor="x", reason="long enough")
    with pytest.raises(ValueError, match="reason"):
        eng.transition(ids, "resolve", actor="x", disposition="cleared", reason="no")


def test_a_resolved_alert_is_skipped_not_reopened(world):
    _s, _wl, eng = world
    ids = [r["alert_id"] for r in _seed_many(world)]
    eng.transition(ids[:1], "resolve", actor="x", disposition="confirmed",
                   reason="vehicle intercepted")
    res = eng.transition(ids, "acknowledge", actor="x")
    assert ids[0] not in res["changed"]
    assert res["skipped"][0]["alert_id"] == ids[0]
    assert "CLEARED" in res["skipped"][0]["why"]
    counts = status_counts(eng.list_alerts())
    assert counts["RESOLVED"] == 1 and counts["ACKNOWLEDGED"] == 5


def test_single_alert_acknowledge_goes_through_the_lifecycle(world):
    s, _wl, eng = world
    ids = [r["alert_id"] for r in _seed_many(world)]
    eng.acknowledge(ids[0], actor="op.1")
    with s.engine.connect() as c:
        r = c.execute(select(S.alerts).where(S.alerts.c.alert_id == ids[0])).first()
    assert r._mapping["acknowledged_by"] == "op.1"
    assert json.loads(r._mapping["lifecycle"])[0]["action"] == "acknowledge"
