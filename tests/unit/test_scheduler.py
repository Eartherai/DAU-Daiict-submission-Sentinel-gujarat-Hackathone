"""Admission control, so a live government run is never lost to a benchmark.

A twenty-five minute capture of the live grid was killed without a traceback
because a vision-language benchmark, the release gate and a six-camera ingest
ran at once on a 24 GB machine. It produced nothing and the failure was
invisible until the store was inspected. Nothing knew the three jobs coexisted.

The rule is priority, not fairness: the live grid is never refused and never
displaced; benchmarking and verification refuse to start beside it.
"""
from __future__ import annotations

import json
import os

import pytest

from saakshya.runtime.scheduler import (
    BLOCKED_BY,
    JobClass,
    Lease,
    ResourceBusy,
    Scheduler,
    describe,
)


@pytest.fixture
def sched(tmp_path):
    return Scheduler(tmp_path / "leases", memory_mb=24576)


# ---- the relation itself ---------------------------------------------------- #
def test_the_live_class_is_blocked_by_nothing():
    assert BLOCKED_BY[JobClass.A_LIVE] == frozenset()


@pytest.mark.parametrize("heavy", [JobClass.C_BENCHMARK, JobClass.D_VERIFY])
def test_heavy_classes_yield_to_the_live_grid(heavy):
    """Written backwards once, and it read plausibly either way."""
    assert JobClass.A_LIVE in BLOCKED_BY[heavy]


def test_interactive_work_is_never_blocked():
    """An operator must be able to use the workspace while the grid runs."""
    assert BLOCKED_BY[JobClass.B_INTERACTIVE] == frozenset()


# ---- admission -------------------------------------------------------------- #
def test_benchmark_and_verify_refuse_beside_a_live_run(sched):
    with sched.lease(JobClass.A_LIVE, "live-30cam"):
        assert sched.why_blocked(JobClass.C_BENCHMARK, 9000)
        assert sched.why_blocked(JobClass.D_VERIFY, 2200)
        with (pytest.raises(ResourceBusy, match="A_LIVE"),
              sched.lease(JobClass.D_VERIFY, "release-check")):
            pass


def test_interactive_runs_beside_a_live_run(sched):
    with sched.lease(JobClass.A_LIVE, "live-30cam"):
        assert sched.why_blocked(JobClass.B_INTERACTIVE, 400) is None


def test_two_benchmarks_do_not_run_together(sched):
    with sched.lease(JobClass.C_BENCHMARK, "vlm-a"):
        assert sched.why_blocked(JobClass.C_BENCHMARK, 9000)


def test_the_machine_is_released_when_the_block_ends(sched):
    with sched.lease(JobClass.A_LIVE, "live"):
        pass
    assert sched.why_blocked(JobClass.C_BENCHMARK, 9000) is None
    assert sched.active() == []


# ---- memory ----------------------------------------------------------------- #
def test_a_job_that_would_exhaust_memory_is_refused(sched):
    """Tested with a class pair that is *not* blocked on class grounds, so the
    memory rule is what is actually being exercised."""
    small = Scheduler(sched.dir, memory_mb=8000)
    with small.lease(JobClass.B_INTERACTIVE, "api", working_set_mb=5000):
        reason = small.why_blocked(JobClass.B_INTERACTIVE, 2000)
        assert reason and "exceeds" in reason, reason


def test_class_blocking_is_reported_before_memory(sched):
    """The reason given must be the one that actually applies."""
    small = Scheduler(sched.dir, memory_mb=8000)
    with small.lease(JobClass.C_BENCHMARK, "vlm", working_set_mb=5000):
        reason = small.why_blocked(JobClass.D_VERIFY, 2200)
        assert reason and "does not start alongside" in reason


def test_the_live_grid_is_admitted_over_budget_not_refused(sched, caplog):
    """Refusing a government evaluation run because a benchmark is resident
    inverts the priority the whole scheme exists to express."""
    small = Scheduler(sched.dir, memory_mb=8000)
    with small.lease(JobClass.C_BENCHMARK, "vlm", working_set_mb=5000):
        with caplog.at_level("WARNING"):
            assert small.why_blocked(JobClass.A_LIVE, 2600) is None
        assert "OVER BUDGET" in caplog.text
        assert "vlm" in caplog.text, "the warning must name what to stop"


# ---- self-healing ------------------------------------------------------------ #
def test_a_lease_from_a_dead_process_is_reclaimed(sched):
    """A hard kill must not wedge the machine."""
    dead = Lease(JobClass.C_BENCHMARK, "killed", 999_999, 9000, 0.0)
    (sched.dir / "stale.json").write_text(json.dumps(dead.to_dict()))
    assert sched.active() == []
    assert sched.why_blocked(JobClass.D_VERIFY, 2200) is None


def test_an_unreadable_lease_is_not_a_claim(sched):
    (sched.dir / "corrupt.json").write_text("{not json")
    assert sched.active() == []


def test_a_live_lease_is_honoured(sched):
    mine = Lease(JobClass.A_LIVE, "live", os.getpid(), 2600, 0.0)
    (sched.dir / "mine.json").write_text(json.dumps(mine.to_dict()))
    assert [x.name for x in sched.active()] == ["live"]


# ---- waiting ----------------------------------------------------------------- #
def test_a_job_may_queue_behind_one_it_must_not_join(sched):
    with (sched.lease(JobClass.A_LIVE, "live"),
          pytest.raises(ResourceBusy),
          sched.lease(JobClass.D_VERIFY, "verify", wait_s=1.0)):
        pass


def test_describe_reports_what_is_running(sched):
    with sched.lease(JobClass.A_LIVE, "live-30cam"):
        d = describe(sched.dir)
        assert d["jobs"][0]["name"] == "live-30cam"
        assert d["committed_mb"] > 0
        assert d["budget_mb"] < d["total_memory_mb"]
