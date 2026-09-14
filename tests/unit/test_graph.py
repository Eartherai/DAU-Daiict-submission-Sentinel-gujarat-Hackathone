"""Camera Link Model: learning, pruning, next-best-camera, anomaly reporting."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saakshya.intelligence.graph import CameraGraph, Transition, haversine_m
from saakshya.store import Store, VehicleObservation

T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)

# Ahmedabad -> Gandhinagar, roughly 25 km apart.
CAMS = [("C-014", 23.0742, 72.6325, "Ahmedabad"),
        ("C-021", 23.0301, 72.5810, "Ahmedabad"),
        ("C-033", 23.1701, 72.8210, "Gandhinagar"),
        ("C-047", 23.2156, 72.6369, "Gandhinagar")]


@pytest.fixture
def store() -> Store:
    s = Store("sqlite:///:memory:")
    s.create_all()
    for cid, lat, lon, dist in CAMS:
        s.upsert_camera({"camera_id": cid, "lat": lat, "lon": lon, "district": dist})
    return s


def obs(cam: str, plate: str, sec: float, key: str) -> VehicleObservation:
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(camera_id=cam, pts_s=sec, t_norm=t, t_ingest=t,
                              dedup_key=key, plate=plate, object_type="car")


def test_haversine_is_sane():
    d = haversine_m(23.0742, 72.6325, 23.2156, 72.6369)
    assert 15_000 < d < 17_000, f"got {d:.0f} m"


def test_graph_learns_transitions_with_no_manual_configuration(store):
    """The property that makes this deployable: it bootstraps from its own data."""
    n = 0
    for trip in range(6):
        base = trip * 1000
        store.add_observations([
            obs("C-014", f"GJ01AA{trip:04d}", base + 0, f"k{n}"),
            obs("C-021", f"GJ01AA{trip:04d}", base + 300, f"k{n+1}"),
        ])
        n += 2
    g = CameraGraph(store).load()
    assert g.learn_from_observations() >= 1
    e = g.edge("C-014", "C-021")
    assert e is not None and e.source == "observed"
    assert e.support_count == 6
    assert 250 < e.travel_p50_s < 350, f"p50 {e.travel_p50_s}"
    assert e.trusted


def test_untrusted_edge_does_not_prune(store):
    """With one sample we must not exclude a real journey. Refusing to answer is
    better than pruning on no evidence."""
    store.add_observations([obs("C-014", "GJ01AA0001", 0, "a"),
                            obs("C-021", "GJ01AA0001", 300, "b")])
    g = CameraGraph(store).load()
    g.learn_from_observations()
    e = g.edge("C-014", "C-021")
    assert not e.trusted
    assert e.feasible(30) and e.feasible(1200), "single-sample edge must stay permissive"


def test_trusted_edge_rejects_impossible_transition(store):
    for trip in range(8):
        store.add_observations([
            obs("C-014", f"GJ02BB{trip:04d}", trip * 1000, f"x{trip}"),
            obs("C-021", f"GJ02BB{trip:04d}", trip * 1000 + 300, f"y{trip}"),
        ])
    g = CameraGraph(store).load()
    g.learn_from_observations()
    e = g.edge("C-014", "C-021")
    assert e.trusted
    assert not e.feasible(5), "5s across a 300s edge should be infeasible"
    assert e.feasible(300)
    assert e.plausibility(300) > e.plausibility(900)


def test_gis_seed_prevents_cold_start_and_never_overwrites_observed(store):
    g = CameraGraph(store).load()
    assert g.seed_from_gis() > 0
    seeded = g.edge("C-014", "C-047")
    assert seeded is not None and seeded.source == "gis_seed"
    assert not seeded.trusted, "a seed must never be treated as evidence"

    for trip in range(5):
        store.add_observations([
            obs("C-014", f"GJ03CC{trip:04d}", trip * 2000, f"p{trip}"),
            obs("C-047", f"GJ03CC{trip:04d}", trip * 2000 + 600, f"q{trip}"),
        ])
    g.learn_from_observations()
    assert g.edge("C-014", "C-047").source == "observed"


def test_next_best_camera_ranks_and_explains(store):
    for trip in range(6):
        store.add_observations([
            obs("C-014", f"GJ04DD{trip:04d}", trip * 1000, f"r{trip}"),
            obs("C-021", f"GJ04DD{trip:04d}", trip * 1000 + 300, f"s{trip}"),
        ])
    for trip in range(3):
        store.add_observations([
            obs("C-014", f"GJ05EE{trip:04d}", 50000 + trip * 1000, f"t{trip}"),
            obs("C-033", f"GJ05EE{trip:04d}", 50000 + trip * 1000 + 900, f"u{trip}"),
        ])
    g = CameraGraph(store).load()
    g.learn_from_observations()
    ranked = g.next_best_cameras("C-014", T0, horizon_s=600)
    assert ranked, "no next-best cameras returned"
    names = [r[0] for r in ranked]
    assert "C-021" in names
    assert names[0] == "C-021", f"better-supported edge should rank first: {names}"
    assert all(r[2] for r in ranked), "every ranking must carry an explanation"


def test_capability_influences_ranking(store):
    for trip in range(6):
        for cam, off in (("C-021", 300), ("C-033", 320)):
            store.add_observations([
                obs("C-014", f"GJ06FF{cam}{trip}", trip * 1000, f"{cam}a{trip}"),
                obs(cam, f"GJ06FF{cam}{trip}", trip * 1000 + off, f"{cam}b{trip}"),
            ])
    g = CameraGraph(store).load()
    g.learn_from_observations()
    good = g.next_best_cameras("C-014", T0, capability={"C-021": 0.95, "C-033": 0.05})
    bad = g.next_best_cameras("C-014", T0, capability={"C-021": 0.05, "C-033": 0.95})
    assert good[0][0] == "C-021"
    assert bad[0][0] == "C-033", "measured capability must be able to change the order"


def test_impossible_transition_is_reported_as_ambiguous_not_fraud(store):
    for trip in range(8):
        store.add_observations([
            obs("C-014", f"GJ07GG{trip:04d}", trip * 1000, f"m{trip}"),
            obs("C-021", f"GJ07GG{trip:04d}", trip * 1000 + 300, f"n{trip}"),
        ])
    g = CameraGraph(store).load()
    g.learn_from_observations()

    target = [obs("C-014", "GJ99ZZ9999", 0, "z1"), obs("C-021", "GJ99ZZ9999", 4, "z2")]
    found = g.anomalies(target)
    assert len(found) == 1
    a = found[0]
    assert a["type"] == "TRAJECTORY_ANOMALY"
    assert a["assessment"].startswith("AMBIGUOUS")
    assert len(a["hypotheses"]) == 3
    joined = " ".join(a["hypotheses"]).lower()
    assert "ocr" in joined and "clon" in joined and "clock" in joined
    # The system must not accuse.
    assert "fraud" not in str(a).lower()
    assert "crime" not in str(a).lower()


def test_normal_transition_raises_no_anomaly(store):
    for trip in range(8):
        store.add_observations([
            obs("C-014", f"GJ08HH{trip:04d}", trip * 1000, f"g{trip}"),
            obs("C-021", f"GJ08HH{trip:04d}", trip * 1000 + 300, f"h{trip}"),
        ])
    g = CameraGraph(store).load()
    g.learn_from_observations()
    ok = [obs("C-014", "GJ88YY8888", 0, "w1"), obs("C-021", "GJ88YY8888", 305, "w2")]
    assert g.anomalies(ok) == []


def test_transition_explains_itself():
    t = Transition("A", "B", support_count=9, travel_p05_s=100,
                   travel_p50_s=200, travel_p95_s=400, source="observed")
    text = t.explain(5)
    assert "9 observed transitions" in text
    assert "OUTSIDE" in text
