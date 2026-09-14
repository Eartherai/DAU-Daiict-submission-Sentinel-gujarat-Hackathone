"""A route that requires 4,000 km/h must never be scored LIKELY.

Found by demonstrating a multi-camera route on live infrastructure: two real
sightings four seconds apart on cameras 4.81 km apart were presented as **LIKELY
at 0.685**. That is 4,138 km/h.

The existing check was gated on `edge.trusted`, which needs three observed
samples of a transition — so on a first sighting no feasibility test ran at all.
Physics does not need learning. Where both cameras have a position, an implied
speed beyond any road vehicle is a contradiction on the first sighting and every
one after.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saakshya.intelligence.graph import CameraGraph
from saakshya.intelligence.trajectory import (
    MAX_PLAUSIBLE_SPEED_KMH,
    LegKind,
    TrajectorySolver,
)
from saakshya.store.repository import VehicleObservation

# Paldi Circle and Chimanbhai Bridge, the two used in the demonstration.
PALDI = (23.0169, 72.5668)
CHIMANBHAI = (23.0296, 72.5219)      # 4.81 km apart
BASE = datetime(2026, 9, 3, 3, 30, 0, tzinfo=UTC)


def graph_with(positions: dict[str, tuple[float, float] | None],
               tmp_path=None) -> CameraGraph:
    """A graph with the given camera positions and no learned edges.

    No learned edges is the point: the bug was that feasibility was only checked
    once an edge had been observed three times.
    """
    import tempfile

    from saakshya.store import Store
    store = Store(f"sqlite:///{tempfile.mkdtemp()}/graph.db")
    store.create_all()
    g = CameraGraph(store)
    for cam, pos in positions.items():
        g.cameras[cam] = {
            "camera_id": cam,
            "lat": pos[0] if pos else None,
            "lon": pos[1] if pos else None,
        }
    return g


def obs(camera: str, seconds: float, plate: str = "GJ01AB1234"
        ) -> VehicleObservation:
    t = BASE + timedelta(seconds=seconds)
    return VehicleObservation(
        observation_id=f"OB-{camera}-{seconds}", camera_id=camera,
        track_id=f"TR-{camera}", segment_id=f"{camera}-S1", pts_s=seconds,
        t_norm=t, t_ingest=t, dedup_key=f"{camera}:{seconds}", plate=plate,
        plate_confidence=0.94, observation_quality=0.9)


@pytest.fixture
def solver():
    return TrajectorySolver(graph_with({"cam04": PALDI, "cam01": CHIMANBHAI}))


def test_an_impossible_speed_is_a_contradiction_without_any_learned_edge(solver):
    """The exact case from the live demonstration."""
    leg = solver._classify_leg(obs("cam04", 0), obs("cam01", 4.2))
    assert leg.kind is LegKind.CONTRADICTION
    assert "4,138 km/h" in leg.explanation or "km/h" in leg.explanation
    assert "not one journey" in leg.explanation


def test_the_contradiction_offers_what_could_explain_it(solver):
    leg = solver._classify_leg(obs("cam04", 0), obs("cam01", 4.2))
    joined = " ".join(leg.alternatives).lower()
    for cause in ("ocr error", "cloned", "clock drift", "distinct vehicles"):
        assert cause in joined


def test_a_plausible_journey_is_not_flagged(solver):
    """4.81 km in 8 minutes is about 36 km/h — ordinary city traffic."""
    leg = solver._classify_leg(obs("cam04", 0), obs("cam01", 480))
    assert leg.kind is not LegKind.CONTRADICTION


def test_a_fast_but_possible_journey_is_not_flagged(solver):
    """4.81 km in 3 minutes is 96 km/h. Brisk, and not the target."""
    leg = solver._classify_leg(obs("cam04", 0), obs("cam01", 180))
    assert leg.kind is not LegKind.CONTRADICTION


def test_the_ceiling_is_generous_enough_not_to_police_the_brisk():
    assert MAX_PLAUSIBLE_SPEED_KMH >= 150, (
        "a ceiling near ordinary road speeds would flag real journeys")


def test_no_position_means_no_speed_claim():
    """A camera with no coordinates cannot support a physics argument either
    way, and inventing one would be worse than abstaining."""
    s = TrajectorySolver(graph_with({"cam04": PALDI, "cam21": None}))
    leg = s._classify_leg(obs("cam04", 0), obs("cam21", 4.2))
    assert leg.kind is not LegKind.CONTRADICTION


def test_sightings_a_moment_apart_make_no_speed_claim(solver):
    """Sub-second separation says the timestamps are too close to separate, not
    that the vehicle teleported."""
    assert solver._implied_speed_kmh(obs("cam04", 0), obs("cam01", 0.4),
                                     0.4) is None


def test_the_speed_is_computed_from_the_straight_line(solver):
    """The most generous reading of the pair: if even the direct line is
    impossible, the road route certainly is."""
    speed = solver._implied_speed_kmh(obs("cam04", 0), obs("cam01", 4.2), 4.2)
    assert speed is not None
    assert 4000 < speed < 4300


def test_a_whole_route_with_an_impossible_leg_is_not_accepted(solver):
    hyps = solver.solve([obs("cam04", 0), obs("cam01", 4.2)])
    assert hyps
    h = hyps[0]
    assert h.contradictions, "the impossible leg was not surfaced"
    assert str(h.status) != "LIKELY", (
        "a route requiring 4,000 km/h must not be presented as likely")
