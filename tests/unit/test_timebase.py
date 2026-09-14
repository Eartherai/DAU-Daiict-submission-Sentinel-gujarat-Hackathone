"""Timebase health and cross-camera correlation.

The question these tests pin down is the one the live grid forced: **may these
two observations be placed on one timeline?**

On the organiser's grid the answer is not uniform. Twelve cameras replay a
common window; others are hours apart; four are on entirely different dates.
A system that assumes a global clock joins a scene from 14 June to one from
4 August and calls it a journey. A system that assumes none refuses correlations
that are perfectly sound. Both are wrong, and the difference is measurable.
"""
from __future__ import annotations

import pytest

from saakshya.live.timebase import (
    ClusterBasis,
    Correlation,
    PtsHealth,
    TimebaseHealth,
    TimebaseRegistry,
    assess_pts,
)


@pytest.fixture
def registry(store) -> TimebaseRegistry:
    r = TimebaseRegistry(store)
    for cam in ("cam01", "cam04", "cam05"):
        store.upsert_camera({"camera_id": cam})
        r.record(TimebaseHealth(camera_id=cam, pts_health=PtsHealth.OK,
                                realtime_ratio=1.0, measured_fps=15.0))
    store.upsert_camera({"camera_id": "cam08"})
    r.record(TimebaseHealth(camera_id="cam08", pts_health=PtsHealth.UNRELIABLE,
                            pts_regressions=22, realtime_ratio=0.4))
    store.upsert_camera({"camera_id": "cam20"})   # never measured
    return r


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #
def test_too_few_frames_is_unknown_not_healthy():
    """The evidence floor applies to timing as much as to capability."""
    health, why = assess_pts(regressions=0, forward_jumps=0, realtime_ratio=1.0,
                             max_gap_s=0.05, frames=10)
    assert health is PtsHealth.UNKNOWN
    assert "not enough" in why


def test_frequent_regressions_make_a_camera_unusable_for_correlation():
    """Measured on the live grid: cam08 produced 22 PTS regressions in three
    minutes. A stream that restarts that often cannot be ordered across a
    restart, so it cannot be placed on a shared timeline at all."""
    health, why = assess_pts(regressions=22, forward_jumps=0, realtime_ratio=0.4,
                             max_gap_s=2.0, frames=800)
    assert health is PtsHealth.UNRELIABLE
    assert "regressions" in why
    assert not TimebaseHealth(camera_id="x",
                              pts_health=health).usable_for_correlation


def test_a_stream_behind_real_time_is_degraded_not_ok():
    """cam15 declares 10 fps, delivers 4.01, and its PTS advances at 0.396x wall
    time — periods of it are simply not delivered."""
    health, why = assess_pts(regressions=0, forward_jumps=0, realtime_ratio=0.396,
                             max_gap_s=1.2, frames=200)
    assert health is PtsHealth.DEGRADED
    assert "wall time" in why


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #
def test_same_cluster_is_allowed(registry):
    registry.declare_cluster("GRID-A", ["cam01", "cam04", "cam05"],
                             basis=ClusterBasis.MEASURED_OVERLAY)
    verdict, why = registry.may_correlate("cam01", "cam04")
    assert verdict is Correlation.ALLOWED
    assert "GRID-A" in why


def test_different_clusters_are_refused(registry):
    """Two cameras replaying different windows must never be joined. On the live
    grid this is cam01 (14 June) and cam20 (4 August) — seven weeks apart."""
    registry.declare_cluster("GRID-A", ["cam01", "cam04"])
    registry.record(TimebaseHealth(camera_id="cam20", pts_health=PtsHealth.OK,
                                   realtime_ratio=1.0, time_cluster="GRID-B"))
    verdict, why = registry.may_correlate("cam01", "cam20")
    assert verdict is Correlation.REFUSED
    assert "never coexisted" in why


def test_unmeasured_camera_is_restricted_not_allowed(registry):
    """The default without evidence is RESTRICTED. Permitting by default is how
    a route across seven weeks gets presented as a journey."""
    verdict, why = registry.may_correlate("cam01", "cam20")
    assert verdict is Correlation.RESTRICTED
    assert "has not been measured" in why


def test_broken_timing_is_refused_even_within_a_cluster(registry):
    """Cluster membership does not rescue a camera whose own PTS jumps
    backwards — it cannot be placed on any timeline, shared or not."""
    registry.declare_cluster("GRID-A", ["cam01", "cam08"])
    verdict, why = registry.may_correlate("cam01", "cam08")
    assert verdict is Correlation.REFUSED
    assert "UNRELIABLE" in why


def test_a_camera_correlates_with_itself(registry):
    assert registry.may_correlate("cam01", "cam01")[0] is Correlation.ALLOWED


def test_partition_separates_the_three_kinds(registry):
    registry.declare_cluster("GRID-A", ["cam01", "cam04"])
    part = registry.correlatable_set(["cam01", "cam04", "cam08", "cam20"])
    assert part["clusters"]["GRID-A"] == ["cam01", "cam04"]
    assert part["unclustered"] == ["cam20"]
    assert [u["camera_id"] for u in part["unusable_timing"]] == ["cam08"]


def test_cluster_basis_travels_with_the_cluster(registry):
    """A cluster read off the cameras' own clocks and one asserted in a config
    file are both usable and are not equally strong. The interface says which."""
    registry.declare_cluster("GRID-A", ["cam01"],
                             basis=ClusterBasis.MEASURED_OVERLAY)
    registry.declare_cluster("GRID-B", ["cam04"], basis=ClusterBasis.DECLARED)
    by_id = {c["cluster_id"]: c for c in registry.clusters()}
    assert by_id["GRID-A"]["basis"] == "MEASURED_OVERLAY"
    assert by_id["GRID-B"]["basis"] == "DECLARED"
    assert registry.get("cam01").cluster_confidence == "MEASURED"
    assert registry.get("cam04").cluster_confidence == "DECLARED"
