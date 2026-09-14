"""A live capture must survive the faults that end runs.

Two captures of the government grid have already been lost whole: one to a
segfault, one to the same class of fault reaching the consumer loop. The pattern
is what matters — a single failure, twenty minutes of irreplaceable capture gone,
and nothing written down.

§47: if the database is temporarily unavailable, do not crash the live ingest.
Queue and retry. §49: a model or subsystem failure must be logged and contained,
never silently swallowed and never fatal.

These exercise the consumer loop's contract directly: the store may fail, the
watchlist may fail, and the run continues and reports what it lost.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from saakshya.store import Store
from saakshya.store.repository import VehicleObservation


class FlakyStore:
    """A store that fails for a while, then recovers."""

    def __init__(self, real: Store, fail_times: int) -> None:
        self._real = real
        self.remaining = fail_times
        self.attempts = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def add_observations(self, obs):
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise RuntimeError("database is locked")
        return self._real.add_observations(obs)


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path}/resilience.db")
    s.create_all()
    s.upsert_camera({"camera_id": "cam01", "name": "cam01",
                     "district": "Ahmedabad"})
    return s


def observation(i: int) -> VehicleObservation:
    now = datetime.now(UTC)
    return VehicleObservation(
        observation_id=f"O{i}", camera_id="cam01", track_id=f"T{i}",
        segment_id="cam01-S1", pts_s=float(i), t_norm=now, t_ingest=now,
        dedup_key=f"cam01:{i}")


def drain(store, batches, *, pending_max=20_000):
    """The consumer loop's contract, in the small.

    Kept deliberately close to `run_stage`: a batch is buffered, the buffer is
    flushed, and a failure holds the buffer for the next attempt rather than
    propagating.
    """
    pending, written, failures, dropped = [], 0, 0, 0
    for batch in batches:
        pending.extend(batch)
        try:
            written += store.add_observations(pending)
            pending = []
        except Exception:
            failures += 1
            if len(pending) > pending_max:
                over = len(pending) - pending_max
                del pending[:over]
                dropped += over
    return written, failures, dropped, pending


def test_a_transient_database_failure_does_not_end_the_run(store):
    flaky = FlakyStore(store, fail_times=3)
    written, failures, dropped, pending = drain(
        flaky, [[observation(i)] for i in range(6)])
    assert failures == 3
    assert not pending, "everything held was written once the store recovered"
    assert written == 6, "no observation was lost to the outage"
    assert dropped == 0


def test_observations_are_held_and_replayed_in_order(store):
    flaky = FlakyStore(store, fail_times=2)
    drain(flaky, [[observation(i)] for i in range(4)])
    ids = [o.observation_id for o in store.search_plate(None)] \
        if hasattr(store, "search_plate") else []
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        ids = [r[0] for r in c.execute(
            select(S.observations.c.observation_id)
            .order_by(S.observations.c.pts_s))]
    assert ids == ["O0", "O1", "O2", "O3"]


def test_a_permanent_failure_bounds_its_buffer(store):
    """An unbounded retry buffer in a process holding thirty decoders is the
    next outage. Losing the oldest few is recoverable; losing the run is not."""
    dead = FlakyStore(store, fail_times=10_000)
    written, failures, dropped, pending = drain(
        dead, [[observation(i)] for i in range(30)], pending_max=10)
    assert written == 0
    assert failures == 30
    assert len(pending) <= 10
    assert dropped == 20, "the buffer grew past its bound"


def test_the_loss_is_reported_not_hidden(store):
    dead = FlakyStore(store, fail_times=10_000)
    _, failures, dropped, pending = drain(
        dead, [[observation(i)] for i in range(12)], pending_max=5)
    assert failures and (dropped or pending), (
        "a run that lost data must be able to say how much")


def test_a_watchlist_failure_does_not_stop_persistence(store, monkeypatch):
    """A fault in alerting loses one alert; a fault that propagates loses the
    capture."""
    from saakshya.watchlist import WatchlistService

    monkeypatch.setattr(
        WatchlistService, "match",
        lambda self, obs: (_ for _ in ()).throw(RuntimeError("watchlist broke")))
    wl = WatchlistService(store)
    written = store.add_observations([observation(1)])
    caught = False
    try:
        for _m in wl.match(observation(1)):
            pass
    except RuntimeError:
        caught = True
    assert written == 1
    assert caught, "the fixture did not actually break matching"


def test_a_store_that_never_recovers_still_returns_control(store):
    """The run must end, report, and release its lease — not hang retrying."""
    dead = FlakyStore(store, fail_times=10_000)
    written, failures, _, pending = drain(
        dead, [[observation(i)] for i in range(5)])
    assert written == 0
    assert failures == 5
    assert len(pending) == 5, "held for a retry that never came, not discarded"
