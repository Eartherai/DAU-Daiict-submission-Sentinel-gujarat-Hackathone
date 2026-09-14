"""Trajectory: multi-hypothesis, coverage gaps, contradictions, statuses."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saakshya.intelligence.graph import CameraGraph
from saakshya.intelligence.trajectory import LegKind, TrajectorySolver, TrajectoryStatus
from saakshya.store import Store, VehicleObservation

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)
CAMS = [("C-014", 23.0742, 72.6325), ("C-021", 23.0301, 72.5810),
        ("C-033", 23.1701, 72.8210), ("C-047", 23.2156, 72.6369),
        ("C-061", 23.0100, 72.6600)]

#: Travel times that match the distances between those cameras.
#:
#: They previously did not. C-021 to C-033 is 29.07 km and the fixture allowed
#: 400 seconds — **262 km/h** — and C-033 to C-047 is 19.48 km in 350 seconds,
#: exactly 200 km/h. The route these tests called "clean" was never physically
#: possible; nothing checked, so nothing complained. When a geometric
#: feasibility check was added the fixture failed, which is the check working.
#:
#: Recomputed at ordinary road speeds for the distance: about 40 km/h across
#: the city pair and 60 km/h on the longer runs.
LEGS = [("C-014", "C-021", 650),    #  7.20 km ->  40 km/h
        ("C-021", "C-033", 1750),   # 29.07 km ->  60 km/h
        ("C-033", "C-047", 1280)]   # 19.48 km ->  55 km/h


def ob(cam, plate, sec, key, colour="white", q=0.9):
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(camera_id=cam, pts_s=sec, t_norm=t, t_ingest=t,
                              dedup_key=key, plate=plate, colour=colour,
                              object_type="car", observation_quality=q)


@pytest.fixture
def solver():
    s = Store("sqlite:///:memory:")
    s.create_all()
    for cid, lat, lon in CAMS:
        s.upsert_camera({"camera_id": cid, "lat": lat, "lon": lon, "tier": "A"})
    n = 0
    for trip in range(8):
        base = trip * 9000
        for a, b, dt in LEGS:
            s.add_observations([ob(a, f"GJ{trip}HIST{n}", base, f"h{n}"),
                                ob(b, f"GJ{trip}HIST{n}", base + dt, f"h{n+1}")])
            n += 2
    g = CameraGraph(s).load()
    g.learn_from_observations()
    return TrajectorySolver(g), s, g


def test_clean_route_scores_well_and_has_no_gaps(solver):
    sol, _s, _g = solver
    t = 90000
    obs = [ob("C-014", "GJ05AB1234", t, "t1")]
    for i, (_a, b, dt) in enumerate(LEGS, start=2):
        t += dt
        obs.append(ob(b, "GJ05AB1234", t, f"t{i}"))
    h = sol.solve(obs, target="GJ05AB1234")[0]
    assert h.camera_sequence == ["C-014", "C-021", "C-033", "C-047"]
    assert h.plate_confirmed_count == 4
    assert not h.contradictions, (
        "a route the tests call clean must be physically possible: "
        f"{[c.explanation for c in h.contradictions]}")
    assert h.score > 0.6
    assert h.status in {TrajectoryStatus.CONFIRMED, TrajectoryStatus.LIKELY}


def test_impossible_transition_becomes_a_contradiction_not_a_silent_drop(solver):
    sol, _s, _g = solver
    obs = [ob("C-014", "GJ05AB1234", 90000, "c1"),
           ob("C-021", "GJ05AB1234", 90003, "c2")]      # 3s across a 300s edge
    h = sol.solve(obs, target="GJ05AB1234")[0]
    assert h.contradictions, "implausible transition was dropped"
    c = h.contradictions[0]
    assert c.kind is LegKind.CONTRADICTION
    assert len(c.alternatives) >= 3
    joined = " ".join(c.alternatives).lower()
    assert "ocr" in joined and "clon" in joined and "clock" in joined
    assert h.status is TrajectoryStatus.REQUIRES_VERIFICATION
    assert h.score <= 0.35, "a contradiction must cap the score"
    # Must not accuse.
    blob = str(h.to_dict()).lower()
    assert "fraud" not in blob and "crime" not in blob


def test_coverage_gap_is_absence_of_evidence_not_evidence_of_absence(solver):
    sol, _s, _g2 = solver
    # C-061 has no learned edges to C-014 in this fixture.
    obs = [ob("C-061", "GJ05AB1234", 90000, "k1"),
           ob("C-014", "GJ05AB1234", 90600, "k2")]
    h = sol.solve(obs, target="GJ05AB1234")[0]
    kinds = {leg.kind for leg in h.legs}
    assert LegKind.COVERAGE_GAP in kinds
    gap = h.coverage_gaps[0]
    assert "absence of evidence" in gap.explanation
    assert "not evidence" in gap.explanation


def test_appearance_candidate_produces_a_separate_lower_hypothesis(solver):
    sol, _s, _g = solver
    confirmed = [ob("C-014", "GJ05AB1234", 90000, "a1"),
                 ob("C-047", "GJ05AB1234", 91050, "a2")]
    cand = ob("C-033", None, 90700, "a3", q=0.35)
    hyps = sol.solve(confirmed, target="GJ05AB1234", candidates=[cand])
    assert len(hyps) >= 2, "candidate should create an alternative hypothesis"
    with_c = [h for h in hyps if "C-033" in h.camera_sequence]
    assert with_c, "candidate route missing"
    h = with_c[0]
    assert h.candidate_count == 1
    assert h.status is TrajectoryStatus.REQUIRES_VERIFICATION
    assert any("unverified" in n for n in h.notes)


def test_hypotheses_are_ranked(solver):
    sol, _s, _g = solver
    confirmed = [ob("C-014", "GJ05AB1234", 90000, "r1"),
                 ob("C-047", "GJ05AB1234", 91050, "r2")]
    good = ob("C-033", None, 90700, "r3", q=0.9)
    hyps = sol.solve(confirmed, target="GJ05AB1234", candidates=[good])
    scores = [h.score for h in hyps]
    assert scores == sorted(scores, reverse=True)


def test_output_is_fully_serialisable(solver):
    sol, _s, _g = solver
    obs = [ob("C-014", "GJ05AB1234", 90000, "s1"),
           ob("C-021", "GJ05AB1234", 90300, "s2")]
    d = sol.solve(obs, target="GJ05AB1234")[0].to_dict()
    for key in ("trajectory_id", "status", "score", "camera_sequence", "legs",
                "evidence", "coverage_gaps", "contradictions", "notes"):
        assert key in d, f"missing {key}"
    assert all("explanation" in leg for leg in d["legs"])


# --------------------------------------------------------------------------- #
# Track-fragment coalescing (CR-004)
# --------------------------------------------------------------------------- #
def test_same_camera_fragments_become_one_sighting(solver):
    """A vehicle passing one camera once is one sighting, however many track
    fragments the tracker produced.

    Occlusion by other traffic breaks a track and restarts it, so the same plate
    can be read several times in a few seconds at one camera. Left alone those
    become "legs" from a camera to itself, and the leg classifier — correctly
    finding no camera between them — labels each a COVERAGE GAP. To an
    investigator that reads as "the vehicle left the network here", which is the
    opposite of what happened. Observed on the demonstration corpus: four
    fragments of one pass at C-014 inside 3.2 seconds.
    """
    sol, _s, _g = solver
    obs = [ob("C-014", "GJ05AB1234", 90000 + sec, f"f{i}", q=q)
           for i, (sec, q) in enumerate(((0, 0.71), (2, 0.93), (3, 0.62), (4, 0.55)))]

    h = sol.solve(obs, target="GJ05AB1234")[0]

    assert h.camera_sequence == ["C-014"], (
        f"four fragments at one camera became {h.camera_sequence}")
    assert h.legs == [], "a leg from a camera to itself is not a leg"
    assert not h.coverage_gaps, (
        "track fragmentation was reported as a coverage gap — that tells the "
        "investigator the vehicle left the network when it did not")
    assert any("track fragments" in n for n in h.notes), (
        "the merge must be stated; silently dropping observations is worse "
        "than not merging them")


def test_coalescing_keeps_the_best_view(solver):
    """The surviving fragment is the highest-quality one, because it is what the
    investigator is shown and what becomes evidence."""
    sol, _s, _g = solver
    best = ob("C-014", "GJ05AB1234", 90002, "b2", q=0.93)
    obs = [ob("C-014", "GJ05AB1234", 90000, "b1", q=0.40),
           best,
           ob("C-014", "GJ05AB1234", 90004, "b3", q=0.51)]
    h = sol.solve(obs, target="GJ05AB1234")[0]
    assert h.observation_ids == [best.observation_id]


def test_distinct_passes_are_not_coalesced(solver):
    """Two genuine passes of the same camera, far apart, stay two sightings.
    A vehicle that returns is a finding, not a duplicate."""
    sol, _s, _g = solver
    obs = [ob("C-014", "GJ05AB1234", 90000, "r1"),
           ob("C-021", "GJ05AB1234", 90300, "r2"),
           ob("C-014", "GJ05AB1234", 91500, "r3")]
    h = sol.solve(obs, target="GJ05AB1234")[0]
    assert h.camera_sequence == ["C-014", "C-021", "C-014"]


def test_a_single_camera_loop_is_not_a_coverage_gap(solver):
    """Looping footage of one mark must not draw cam → cam as a missing camera.

    Measured on the live grid: GJ32AG0028 is 38 reads on cam06, one inter-read
    gap of 125 s (just outside the 120 s fragment window). That left two
    'passes' at the same mount, classified as a COVERAGE GAP over 1048 s.
    """
    sol, _s, _g = solver
    obs = [ob("C-014", "GJ32AG0028", 90000 + i * 20, f"loop{i}")
           for i in range(30)]
    obs.append(ob("C-014", "GJ32AG0028", 90000 + 30 * 20 + 130, "loop_gap"))
    h = sol.solve(obs, target="GJ32AG0028")[0]
    assert h.camera_sequence == ["C-014"]
    assert h.legs == []
    assert not h.coverage_gaps
    assert h.duration_s > 120
    assert any("one camera" in n.lower() and "coverage gap" in n.lower()
               for n in h.notes)


def test_different_plates_at_one_camera_are_not_coalesced(solver):
    """Coalescing is per registration mark. Two vehicles passing one camera
    seconds apart are two vehicles."""
    sol, _s, _g = solver
    obs = [ob("C-014", "GJ05AB1234", 90000, "p1"),
           ob("C-014", "GJ07XY9999", 90002, "p2")]
    h = sol.solve(obs)[0]
    assert len(h.observation_ids) == 2
