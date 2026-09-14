"""The wrong-case harness must be able to fail.

A suite that passes on a broken system is worse than no suite: it converts an
absence of checking into a claim of correctness. §75 of the directive asks for
exactly this — break the thing deliberately, confirm the relevant check goes
red, then restore.

Each test here breaks one safety property and asserts the harness notices.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from saakshya.store import Store
from saakshya.watchlist import service as wl_service

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "wrong_cases", ROOT / "tools" / "verify" / "wrong_cases.py")
wc = importlib.util.module_from_spec(_spec)
# Registered before execution: `@dataclass` resolves annotations through
# `sys.modules[cls.__module__]`, and a module loaded by path alone is not there.
sys.modules["wrong_cases"] = wc
_spec.loader.exec_module(wc)


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path}/wrong.db")
    s.create_all()
    for cam in ("cam01", "cam02"):
        s.upsert_camera({"camera_id": cam, "name": cam, "district": "Ahmedabad"})
    return s


def case(cases, name_fragment):
    for c in cases:
        if name_fragment in c.name:
            return c
    raise AssertionError(f"no case matching {name_fragment!r} in "
                         f"{[c.name for c in cases]}")


def test_a_healthy_store_passes_every_case(store):
    for c in wc.run(store):
        assert c.passed, f"{c.name}: {c.observed}"


def test_it_catches_an_expiry_check_that_stopped_working(store, monkeypatch):
    """Break the check `match` actually consults, not a namesake beside it.

    A first version patched `is_valid`, which nothing on this path calls; the
    mutation changed nothing and the test passed while proving nothing. The seam
    is `active_at`, and finding that out is the point of writing these.
    """
    monkeypatch.setattr(
        wl_service.VehicleOfInterest, "active_at",
        lambda self, when: (True, "validity checking disabled for this test"))
    assert not case(wc.run(store), "expired watchlist entry").passed


def test_it_catches_a_confidence_floor_that_stopped_suppressing(store, monkeypatch):
    """Drop the floor to zero and a hopeless read raises an alert.

    Patching the dataclass *attribute* does nothing: the generated `__init__`
    closes over the default, so `AlertPolicy()` still returns 0.55. The seam is
    the constructor.
    """
    from saakshya.watchlist import alerts as alerts_mod

    original = alerts_mod.AlertPolicy

    def permissive(*a, **kw):
        kw["min_confidence"] = 0.0
        return original(*a, **kw)

    monkeypatch.setattr(alerts_mod, "AlertPolicy", permissive)
    assert not case(wc.run(store), "too poor to act on").passed


def _all_entries(svc, plate=None):
    """Every entry regardless of status — the SQL revocation filter removed."""
    from sqlalchemy import select

    from saakshya.store import schema as S
    q = select(S.watchlist)
    if plate:
        q = q.where(S.watchlist.c.plate == plate)
    with svc.store.engine.connect() as c:
        return [wl_service.VehicleOfInterest.from_row(r) for r in c.execute(q)]


def test_revocation_is_enforced_twice(store, monkeypatch):
    """Removing the SQL filter alone does not let a revoked entry match.

    `active_entries` filters on status in the query, and `match` then asks each
    entry `active_at`, which refuses a revoked one again. Defence in depth is
    only worth the name if it has been checked, so this removes one layer and
    asserts the other still holds.
    """
    monkeypatch.setattr(wl_service.WatchlistService, "active_entries", _all_entries)
    assert case(wc.run(store), "revoked watchlist entry").passed, (
        "with the SQL filter gone, active_at must still refuse a revoked entry")


def test_it_catches_revocation_failing_at_both_layers(store, monkeypatch):
    """And when both layers go, the harness notices."""
    monkeypatch.setattr(wl_service.WatchlistService, "active_entries", _all_entries)
    monkeypatch.setattr(
        wl_service.VehicleOfInterest, "active_at",
        lambda self, when: (True, "validity checking disabled for this test"))
    assert not case(wc.run(store), "revoked watchlist entry").passed


def test_it_catches_a_search_that_answers_for_a_plate_it_never_saw(store, monkeypatch):
    """The most dangerous failure: inventing a sighting."""
    monkeypatch.setattr(
        type(store), "search_plate",
        lambda self, plate, **kw: ["a sighting that does not exist"])
    cases = wc.run(store)
    assert not case(cases, "never seen").passed
    assert not case(cases, "malformed mark").passed


def test_it_catches_correlation_allowed_without_a_shared_timebase(store, monkeypatch):
    """A blanket ALLOWED is the failure that draws journeys that never happened."""
    from saakshya.live import timebase as tb

    store.upsert_camera({"camera_id": "cam09", "name": "cam09"})
    reg = tb.TimebaseRegistry(store)
    reg.record(tb.TimebaseHealth(
        camera_id="cam01", pts_health=tb.PtsHealth.OK, time_cluster="C1",
        cluster_confidence="MEASURED"))
    reg.record(tb.TimebaseHealth(camera_id="cam09", pts_health=tb.PtsHealth.OK))

    healthy = wc.run(store)
    assert case(healthy, "no shared timebase").passed

    monkeypatch.setattr(
        tb.TimebaseRegistry, "may_correlate",
        lambda self, a, b: (tb.Correlation.ALLOWED, "always allowed, for this test"))
    assert not case(wc.run(store), "no shared timebase").passed


def test_the_allowed_case_guards_against_a_blanket_refusal(store, monkeypatch):
    """Refusing everything would pass every refusal test and be useless.

    The harness carries a positive case for exactly this reason; breaking
    correlation the other way must also be caught.
    """
    from saakshya.live import timebase as tb

    reg = tb.TimebaseRegistry(store)
    for cam in ("cam01", "cam02"):
        reg.record(tb.TimebaseHealth(
            camera_id=cam, pts_health=tb.PtsHealth.OK, time_cluster="C1",
            cluster_confidence="MEASURED"))
    assert case(wc.run(store), "one measured cluster").passed

    monkeypatch.setattr(
        tb.TimebaseRegistry, "may_correlate",
        lambda self, a, b: (tb.Correlation.REFUSED, "always refused, for this test"))
    assert not case(wc.run(store), "one measured cluster").passed


def test_an_expired_entry_is_genuinely_expired_in_the_fixture(store):
    """Guards the harness's own setup: if the entry were not actually expired,
    the expiry case would pass for the wrong reason."""
    wl = wl_service.WatchlistService(store)
    entries = [e for e in wc.run(store) if "expired" in e.name]
    assert entries and entries[0].detail.get("watchlist_id")
    voi = wl.get(entries[0].detail["watchlist_id"])
    assert voi is not None
    assert voi.valid_until is not None
    assert voi.valid_until < datetime.now(UTC) + timedelta(seconds=1)
