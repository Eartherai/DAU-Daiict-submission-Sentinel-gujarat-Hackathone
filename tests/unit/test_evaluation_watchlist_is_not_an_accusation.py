"""A real person's car is never filed as stolen to make a demonstration fire.

Plates read off the government evaluation footage were put on the watchlist to
show the alert path on live data, and filed as "stolen_vehicle". Nothing is
known about those vehicles except that a camera read them. Applied to a copy of
the live store: 18 entries and 129 alerts re-filed, 6 test-harness rows
revoked, one audit entry written.
"""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from saakshya.store import Store, VehicleObservation

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "recat", ROOT / "tools/admin/recategorise_evaluation_watchlist.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _store(tmp_path) -> Store:
    from sqlalchemy import insert

    from saakshya.store import schema as S
    store = Store(f"sqlite:///{tmp_path/'w.db'}")
    store.create_all()
    now = datetime(2026, 9, 20, tzinfo=UTC)
    store.add_observations([VehicleObservation(
        camera_id="cam06", pts_s=0.0, t_norm=now, t_ingest=now,
        dedup_key="real-1", plate="GJ18X6705", object_type="car")])
    with store.engine.begin() as c:
        for wid, plate, reason, status in (
                ("W1", "GJ18X6705", "live-read plate placed on watchlist during evaluation", "ACTIVE"),
                ("W2", "GJ05AB1234", "synthetic corpus", "ACTIVE"),
                ("W3", "GJ99EX0001", "expired entry under test", "ACTIVE")):
            c.execute(insert(S.watchlist).values(
                watchlist_id=wid, entity_type="vehicle", plate=plate,
                category="stolen_vehicle", authority="test", reason=reason,
                priority="HIGH", jurisdiction="STATE", valid_from_us=0,
                version=1, status=status, source_system="REPRESENTATIVE"))
    return store


def _rows(store, table):
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        return {r._mapping["plate"]: dict(r._mapping)
                for r in c.execute(select(getattr(S, table)))}


def test_a_plate_read_off_real_footage_is_refiled(tmp_path):
    store = _store(tmp_path)
    tool = _tool()
    tool.apply(store, tool.plan(store), "admin.test")
    wl = _rows(store, "watchlist")
    assert wl["GJ18X6705"]["category"] == "evaluation_designated"
    assert wl["GJ18X6705"]["version"] == 2


def test_a_fictional_plate_keeps_its_category(tmp_path):
    """The synthetic corpus's plates belong to nobody; nothing to correct."""
    store = _store(tmp_path)
    tool = _tool()
    tool.apply(store, tool.plan(store), "admin.test")
    assert _rows(store, "watchlist")["GJ05AB1234"]["category"] == "stolen_vehicle"


def test_test_harness_rows_are_revoked_with_a_reason_not_deleted(tmp_path):
    store = _store(tmp_path)
    tool = _tool()
    tool.apply(store, tool.plan(store), "admin.test")
    row = _rows(store, "watchlist")["GJ99EX0001"]
    assert row["status"] == "REVOKED"
    assert "test fixture" in row["reason"]


def test_the_dry_run_writes_nothing(tmp_path):
    store = _store(tmp_path)
    tool = _tool()
    p = tool.plan(store)
    assert len(p["refile"]) == 1 and len(p["harness"]) == 1
    assert _rows(store, "watchlist")["GJ18X6705"]["category"] == "stolen_vehicle"


def test_the_target_card_and_the_alert_use_the_same_words():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    inc = (ROOT / "src/saakshya/watchlist/incidents.py").read_text(encoding="utf-8")
    phrase = "designated vehicle of interest (evaluation)"
    assert phrase in app and phrase in inc
