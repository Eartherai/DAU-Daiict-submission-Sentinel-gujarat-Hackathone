"""Graph-first hybrid search: ordering, pruning, decomposition, honesty."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saakshya.analytics.anpr import plate_status
from saakshya.intelligence.graph import CameraGraph
from saakshya.intelligence.search import VehicleSearch
from saakshya.store import Store, VehicleObservation

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)
CAMS = [("C-014", 23.0742, 72.6325), ("C-021", 23.0301, 72.5810),
        ("C-033", 23.1701, 72.8210), ("C-047", 23.2156, 72.6369),
        ("C-061", 23.0100, 72.6600)]


def ob(cam, plate, sec, key, colour=None, otype="car", q=0.9, votes=12):
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(camera_id=cam, pts_s=sec, t_norm=t, t_ingest=t,
                              dedup_key=key, plate=plate, colour=colour,
                              object_type=otype, observation_quality=q,
                              plate_votes=votes if plate else 0,
                              plate_confidence=0.98 if plate else None)


@pytest.fixture
def wired():
    s = Store("sqlite:///:memory:")
    s.create_all()
    for cid, lat, lon in CAMS:
        s.upsert_camera({"camera_id": cid, "lat": lat, "lon": lon})
    # Traffic history so the graph has evidenced edges.
    n = 0
    for trip in range(8):
        base = trip * 5000
        for (a, b, dt) in [("C-014", "C-021", 300), ("C-021", "C-033", 400),
                           ("C-033", "C-047", 350), ("C-014", "C-033", 700)]:
            s.add_observations([ob(a, f"GJ{trip:02d}XX{n:04d}", base, f"hist{n}"),
                                ob(b, f"GJ{trip:02d}XX{n:04d}", base + dt, f"hist{n+1}")])
            n += 2
    g = CameraGraph(s).load()
    g.learn_from_observations()
    return s, g, VehicleSearch(s, g)


def test_repeated_reads_on_one_camera_are_not_a_route(wired):
    """Looping footage of one mark is one camera, not a fleet."""
    s, _g, vs = wired
    s.add_observations([
        ob("C-014", "GJ32AG0028", 90000 + i * 60, f"loop{i}", "white")
        for i in range(6)
    ])
    r = vs.search_plate("GJ32AG0028")
    assert r.sighting is not None
    assert r.sighting["type"] == "SINGLE_CAMERA"
    assert r.sighting["camera_id"] == "C-014"
    assert r.sighting["hits"] == 6
    assert r.sighting["cross_camera"] is False
    assert "one camera" in r.sighting["message"].lower()


def test_reads_on_two_cameras_are_flagged_as_cross_camera(wired):
    s, _g, vs = wired
    s.add_observations([
        ob("C-014", "GJ05AB1234", 90000, "x1", "white"),
        ob("C-021", "GJ05AB1234", 90300, "x2", "white"),
    ])
    r = vs.search_plate("GJ05AB1234")
    assert r.sighting is not None
    assert r.sighting["type"] == "MULTI_CAMERA"
    assert r.sighting["cross_camera"] is True
    assert r.sighting["cameras"] == ["C-014", "C-021"]


def test_exact_plate_search_is_confirmed_not_a_candidate(wired):
    s, _g, vs = wired
    s.add_observations([ob("C-014", "GJ05AB1234", 90000, "sc-t1", "white"),
                        ob("C-047", "GJ05AB1234", 91000, "sc-t2", "white")])
    r = vs.search_plate("GJ05AB1234")
    assert len(r.candidates) == 2
    assert all(c.status == "CONFIRMED_BY_PLATE" for c in r.candidates)
    assert all(c.score == 1.0 for c in r.candidates)


def test_a_single_vote_plate_is_a_lead_not_a_confirmation(wired):
    s, _g, vs = wired
    s.add_observations([ob("C-014", "GJ05AB1234", 90000, "lead1", "white",
                           votes=1)])
    r = vs.search_plate("GJ05AB1234")
    assert len(r.candidates) == 1
    assert r.candidates[0].status == "REQUIRES_VERIFICATION"
    assert r.candidates[0].status == plate_status(votes=1)
    assert r.candidates[0].score < 1.0
    assert any("single frame" in w for w in r.candidates[0].warnings)


def test_an_ocr_confusion_of_the_query_is_found_and_not_called_exact(wired):
    """O/0 in the query must not read as 'not found' on a hard plate.

    The stored mark is unchanged. The hit is a lookalike of what was asked.
    """
    s, _g, vs = wired
    s.add_observations([ob("C-014", "GJ05AB1234", 90000, "ocr1", "white")])
    r = vs.search_plate("GJO5AB1234")
    assert len(r.candidates) == 1
    assert r.candidates[0].observation.plate == "GJ05AB1234"
    assert r.candidates[0].status == "REQUIRES_VERIFICATION"
    assert r.stage_counts.get("exact") == 0
    assert r.stage_counts.get("ocr_repair") == 1
    assert any("OCR confusion" in w for w in r.candidates[0].warnings)


def test_exact_hits_are_not_diluted_with_ocr_lookalikes(wired):
    s, _g, vs = wired
    s.add_observations([ob("C-014", "GJ05AB1234", 90000, "ex1", "white")])
    r = vs.search_plate("GJ05AB1234")
    assert all(c.status == "CONFIRMED_BY_PLATE" for c in r.candidates)
    assert "ocr_repair" not in r.stage_counts


def test_separator_forms_reach_the_same_observations(wired):
    s, _g, vs = wired
    s.add_observations([ob("C-014", "GJ05AB1234", 90000, "sc-u1", "white")])
    assert len(vs.search_plate("GJ 05 AB 1234").candidates) == 1
    assert len(vs.search_plate("gj-05-ab-1234").candidates) == 1


def test_gap_search_prunes_by_graph_and_reports_what_it_skipped(wired):
    """The stage that protects the weak appearance signal."""
    s, _g, vs = wired
    a = ob("C-014", "GJ05AB1234", 90000, "sc-g1", "white")
    b = ob("C-047", "GJ05AB1234", 91050, "sc-g2", "white")
    s.add_observations([a, b])
    # The unreadable-plate observation on the intermediate camera.
    s.add_observations([ob("C-033", None, 90420, "sc-g3", "white", q=0.35)])
    # A decoy on a camera that is NOT on any route between them.
    s.add_observations([ob("C-061", None, 90400, "sc-g4", "white", q=0.95)])

    r = vs.find_gap_candidates([a, b])
    names = [c.observation.camera_id for c in r.candidates]
    assert "C-033" in names, f"intermediate camera not surfaced: {names}"
    assert "C-061" not in names, "graph prune failed — unreachable camera scored"
    assert r.cameras_pruned, "prune must report what it did not search"
    assert "reachable" in r.prune_reason


def test_gap_candidate_never_asserts_identity(wired):
    s, _g, vs = wired
    a = ob("C-014", "GJ05AB1234", 90000, "sc-h1", "white")
    b = ob("C-047", "GJ05AB1234", 91050, "sc-h2", "white")
    s.add_observations([a, b, ob("C-033", None, 90420, "sc-h3", "white", q=0.35)])
    r = vs.find_gap_candidates([a, b])
    assert r.candidates
    for c in r.candidates:
        assert c.status == "REQUIRES_VERIFICATION"
        assert c.score < 1.0
        assert any("not established by plate" in w for w in c.warnings)


def test_score_is_fully_decomposed(wired):
    s, _g, vs = wired
    a = ob("C-014", "GJ05AB1234", 90000, "sc-i1", "white")
    b = ob("C-047", "GJ05AB1234", 91050, "sc-i2", "white")
    s.add_observations([a, b, ob("C-033", None, 90420, "sc-i3", "white", q=0.35)])
    c = vs.find_gap_candidates([a, b]).candidates[0]
    e = c.explain()
    names = {t["name"] for t in e["terms"]}
    assert names == {"plate", "colour", "size_class", "route_plausibility",
                     "source_quality"}
    assert abs(sum(t["contribution"] for t in e["terms"]) - 0) > 0
    assert e["primary_weakness"], "must name the weakest signal"
    # The plate term must be present and zero, not omitted.
    plate = next(t for t in e["terms"] if t["name"] == "plate")
    assert plate["value"] == 0.0 and "could not support ANPR" in plate["detail"]


def test_low_quality_observation_scores_below_an_identical_high_quality_one(wired):
    s, _g, vs = wired
    a = ob("C-014", "GJ05AB1234", 90000, "sc-j1", "white")
    b = ob("C-047", "GJ05AB1234", 91050, "sc-j2", "white")
    s.add_observations([a, b])
    s.add_observations([ob("C-033", None, 90420, "sc-j3", "white", q=0.9)])
    hi = vs.find_gap_candidates([a, b]).candidates[0].score

    s2 = Store("sqlite:///:memory:")
    s2.create_all()
    for cid, lat, lon in CAMS:
        s2.upsert_camera({"camera_id": cid, "lat": lat, "lon": lon})
    for r in s.all_transition_samples():
        s2.add_transition_samples([r])
    g2 = CameraGraph(s2).load()
    g2.recompute()
    s2.add_observations([a, b, ob("C-033", None, 90420, "sc-j4", "white", q=0.2)])
    lo = VehicleSearch(s2, g2).find_gap_candidates([a, b]).candidates[0].score
    assert lo < hi, f"quality must discount the score: low={lo:.3f} high={hi:.3f}"


def test_wrong_colour_is_penalised_but_expected_confusion_is_not(wired):
    s, _g, vs = wired
    a = ob("C-014", "GJ05AB1234", 90000, "sc-k1", "white")
    b = ob("C-047", "GJ05AB1234", 91050, "sc-k2", "white")
    s.add_observations([a, b])
    s.add_observations([ob("C-033", None, 90400, "sc-k3", "grey", q=0.5),
                        ob("C-033", None, 90440, "sc-k4", "red", q=0.5)])
    cands = {c.observation.colour: c.score for c in vs.find_gap_candidates([a, b]).candidates}
    assert cands["grey"] > cands["red"], "white->grey must beat white->red"


def test_search_is_audited(wired):
    s, _g, vs = wired
    s.add_observations([ob("C-014", "GJ05AB1234", 90000, "sc-l1", "white")])
    vs.search_plate("GJ05AB1234", actor="officer.x", case_id="FIR-9",
                    purpose="stolen vehicle")
    ok, err = s.verify_audit_chain()
    assert ok, err
    assert s.stats()["audit_entries"] >= 1


def test_no_gap_reports_no_gap(wired):
    s, _g, vs = wired
    a = ob("C-014", "GJ05AB1234", 90000, "sc-m1", "white")
    b = ob("C-021", "GJ05AB1234", 90300, "sc-m2", "white")
    s.add_observations([a, b])
    r = vs.find_gap_candidates([a, b])
    assert r.candidates == []
    assert "no unexplained gap" in r.prune_reason


def test_person_attribute_search_does_not_claim_vehicle_identity(wired):
    from saakshya.investigation import InvestigationService
    from saakshya.security import AuthContext, Principal, Role

    s, _g, _vs = wired
    s.add_observations([ob("C-014", None, 92000, "person-1", otype="person")])
    svc = InvestigationService(s)
    ctx = AuthContext(
        Principal(user_id="sup.p", role=Role.SUPERVISOR),
        case_id="FIR-P-1", purpose="person presence at a junction")
    r = svc.search_target(ctx, object_types=("person",))
    assert r["result_count"] >= 1
    assert r["candidates"][0]["object_type"] == "person"
    assert "identity is not" in r["caveat"].lower()
    assert "vehicle" not in r["caveat"].lower()


def test_vehicle_attribute_search_still_refuses_to_identify(wired):
    from saakshya.investigation import InvestigationService
    from saakshya.security import AuthContext, Principal, Role

    s, _g, _vs = wired
    svc = InvestigationService(s)
    ctx = AuthContext(
        Principal(user_id="sup.v", role=Role.SUPERVISOR),
        case_id="FIR-V-1", purpose="colour filter of traffic")
    r = svc.search_target(ctx, object_types=("car",))
    assert "do not identify a vehicle" in r["caveat"]
