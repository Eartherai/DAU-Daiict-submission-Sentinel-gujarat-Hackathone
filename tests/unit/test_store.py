"""Persistence: idempotency, ordering, filtering, audit integrity."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from saakshya.store import SearchFilter, Store, VehicleObservation, to_us

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def store() -> Store:
    s = Store("sqlite:///:memory:")
    s.create_all()
    for i, (cid, dist) in enumerate([("C-014", "Ahmedabad"), ("C-021", "Ahmedabad"),
                                     ("C-033", "Gandhinagar"), ("C-047", "Gandhinagar")]):
        s.upsert_camera({"camera_id": cid, "name": f"cam {i}", "district": dist,
                         "department": "Test", "lat": 23.0 + i, "lon": 72.0 + i})
    return s


def _obs(cam: str, plate: str | None, sec: int, **kw) -> VehicleObservation:
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(
        camera_id=cam, pts_s=float(sec), t_norm=t, t_ingest=t,
        dedup_key=kw.pop("dedup_key", f"{cam}:SEG1:{sec}"),
        plate=plate, object_type=kw.pop("object_type", "car"), **kw)


def test_roundtrip_preserves_fields(store):
    v = np.random.default_rng(0).normal(size=384).astype(np.float32)
    o = _obs("C-014", "GJ05AB1234", 10, colour="white", plate_confidence=0.97,
             embedding=v, embedding_model="dinov2", observation_quality=0.81)
    assert store.add_observations([o]) == 1
    got = store.search_plate("GJ05AB1234")[0]
    assert got.plate == "GJ05AB1234"
    assert got.colour == "white"
    assert got.observation_quality == pytest.approx(0.81)
    assert got.embedding is not None and got.embedding.size == 384
    # float16 storage: close, not identical. Cosine similarity must survive.
    cos = float(np.dot(v, got.embedding) / (np.linalg.norm(v) * np.linalg.norm(got.embedding)))
    assert cos > 0.999


def test_ingestion_is_idempotent(store):
    """Offline replay must not duplicate. This is the property that makes
    at-least-once delivery safe."""
    batch = [_obs("C-014", "GJ05AB1234", s) for s in (10, 20, 30)]
    assert store.add_observations(batch) == 3
    assert store.add_observations(batch) == 0          # exact replay
    assert store.add_observations([*batch, _obs("C-014", "GJ05AB1234", 40)]) == 1
    assert store.count_observations() == 4


def test_survives_reconnect_reordering(store):
    """A queue that replays out of order must still land in time order."""
    store.add_observations([_obs("C-014", "GJ05AB1234", s) for s in (30, 10, 20)])
    got = store.search_plate("GJ05AB1234")
    assert [o.pts_s for o in got] == [10.0, 20.0, 30.0]


def test_time_and_district_filters(store):
    store.add_observations([
        _obs("C-014", "GJ05AB1234", 10), _obs("C-033", "GJ05AB1234", 200),
        _obs("C-047", "GJ05AB1234", 400),
    ])
    mid = store.search(SearchFilter(plate="GJ05AB1234",
                                    t_from=T0 + timedelta(seconds=100),
                                    t_to=T0 + timedelta(seconds=300)))
    assert [o.camera_id for o in mid] == ["C-033"]
    gnr = store.search(SearchFilter(plate="GJ05AB1234", districts=["Gandhinagar"]))
    assert {o.camera_id for o in gnr} == {"C-033", "C-047"}


def test_observations_without_plate_are_first_class(store):
    """The unreadable-plate case: the observation must still exist and be
    findable by appearance, or the hard case is impossible."""
    v = np.ones(128, dtype=np.float32)
    store.add_observations([_obs("C-033", None, 50, embedding=v, colour="white")])
    assert store.count_observations() == 1
    hits = store.search(SearchFilter(has_embedding=True, colours=["white"]))
    assert len(hits) == 1 and hits[0].plate is None


def test_track_grouping(store):
    store.add_observations([
        _obs("C-014", "GJ05AB1234", 10, track_id="T1"),
        _obs("C-014", "GJ05AB1234", 12, track_id="T1"),
        _obs("C-014", "GJ01CD5678", 20, track_id="T2"),
    ])
    assert len(store.observations_for_track("C-014", "T1")) == 2
    assert len(store.observations_for_track("C-014", "T2")) == 1


def test_audit_chain_detects_tampering(store):
    store.audit("officer.a", "search_plate", case_id="FIR-1",
                purpose="stolen vehicle", target="GJ05AB1234", result_count=3)
    store.audit("officer.a", "get_evidence", case_id="FIR-1", target="EZ1")
    ok, err = store.verify_audit_chain()
    assert ok and err is None

    from sqlalchemy import text
    with store.engine.begin() as c:
        c.execute(text("UPDATE audit_log SET target='GJ99ZZ9999' WHERE id=1"))
    ok, err = store.verify_audit_chain()
    assert not ok and "broken" in err


def test_stats_are_real(store):
    store.add_observations([_obs("C-014", "GJ05AB1234", 10),
                            _obs("C-014", None, 11)])
    s = store.stats()
    assert s["observations"] == 2
    assert s["observations_with_plate"] == 1
    assert s["observations_plate_confirmed"] == 0
    assert s["observations_plate_leads"] == 0
    assert s["observations_person"] == 0
    assert s["observations_person_long_stay"] == 0
    assert s["cameras_person_long_stay"] == 0
    assert s["cameras"] == 4
    assert s["cameras_with_plate"] == 1
    assert s["distinct_plates"] == 1
    assert s["raw_ocr_read_records"] == 0
    assert s["observations_by_object_type"].get("car") == 2

    store.add_observations([
        _obs("C-021", "GJ05AB9999", 20, plate_votes=2, dedup_key="c21-conf"),
        _obs("C-021", "GJ05AB1111", 21, plate_votes=1, dedup_key="c21-lead"),
        _obs("C-033", None, 22, object_type="person", dedup_key="c33-p",
             model_versions={"dwell_s": 4.0, "dwell_exceeded": False}),
        _obs("C-047", None, 23, object_type="person", dedup_key="c47-p",
             model_versions={"dwell_s": 18.0, "dwell_exceeded": True}),
    ])
    s2 = store.stats()
    assert s2["observations_plate_confirmed"] == 1
    assert s2["observations_plate_leads"] == 1
    assert s2["observations_person"] == 2
    assert s2["observations_person_long_stay"] == 1
    assert s2["cameras_person_long_stay"] == 1
    assert s2["cameras_with_plate"] == 2
    assert s2["distinct_plates"] == 3
    assert s2["observations_by_object_type"].get("person") == 2
    assert s2["observations_by_object_type"].get("car", 0) >= 1


def test_stats_cache_invalidates_on_write(store):
    """A cached overview must not hide observations that just arrived."""
    store._stats_ttl_s = 60.0
    store.add_observations([_obs("C-014", "GJ05AB1234", 10)])
    first = store.stats()["observations"]
    store.add_observations([_obs("C-014", None, 11, dedup_key="later")])
    assert store.stats()["observations"] == first + 1


def test_plate_reads_are_stored_and_invalidate_stats(store):
    """Forensic OCR rows are a real table, not an observation counter."""
    store._stats_ttl_s = 60.0
    empty = store.stats()["raw_ocr_read_records"]
    n = store.add_plate_reads([{
        "camera_id": "C-014", "track_id": "t1", "segment_id": "SEG1",
        "pts_s": 1.0, "t_norm_us": to_us(T0), "raw_text": "XXXX",
        "canonical": "XXXX", "valid": False,
        "reject_reason": "does not match any Indian registration format",
        "ocr_confidence": 0.9, "det_confidence": 0.8,
        "plate_pixel_width": 50.0,
    }])
    assert n == 1
    assert store.stats()["raw_ocr_read_records"] == empty + 1


# --------------------------------------------------------------------------- #
# Schema evolution (CR-006)
# --------------------------------------------------------------------------- #
def test_a_column_added_after_creation_is_applied_in_place(tmp_path):
    """`metadata.create_all` creates tables and never touches an existing one,
    so every column added to the schema silently breaks every query against a
    database created before it.

    Found by the release gate — two checks failed with
    `no such column: observations.mean_chroma` against a store built the day
    before. In development the answer was to delete the database; in a
    deployment that answer does not exist.
    """
    from sqlalchemy import Column, Float

    from saakshya.store import Store
    from saakshya.store import schema as S

    url = f"sqlite:///{tmp_path / 'evolve.db'}"
    Store(url).create_all()

    # Add a column to the declared schema after the database exists, then make
    # a second Store see it.
    new = Column("late_addition_metric", Float)
    S.observations.append_column(new)
    try:
        store = Store(url)
        store.create_all()
        cols = store._existing_columns("observations")
        assert "late_addition_metric" in cols, (
            "a nullable column added to the schema did not reach an existing "
            "database, so every query against it would now fail")
        # And the table is still queryable, which is the point.
        from saakshya.store import SearchFilter
        assert store.search(SearchFilter(limit=1)) == []
    finally:
        S.observations._columns.remove(new)


def test_a_change_that_cannot_be_applied_in_place_is_reported(tmp_path):
    """A NOT NULL column cannot be added to a populated table in place. It must
    be reported rather than skipped, so a deployment fails at startup instead of
    at the first query."""
    from sqlalchemy import Column, String

    from saakshya.store import Store
    from saakshya.store import schema as S

    url = f"sqlite:///{tmp_path / 'pending.db'}"
    Store(url).create_all()

    new = Column("mandatory_field", String(8), nullable=False)
    S.observations.append_column(new)
    try:
        store = Store(url)
        store.create_all()
        pending = store.pending_migrations()
        assert any("mandatory_field" in p for p in pending), (
            "an inapplicable schema change was silently skipped")
    finally:
        S.observations._columns.remove(new)


def test_a_nul_held_as_its_stand_in_still_verifies_and_nothing_else_does(store):
    # A store written before the API refused NUL, copied to PostgreSQL, holds
    # U+2400 where the NUL was. The entry must verify against the hash made
    # when it was written - and no other substitute may.
    from sqlalchemy import text

    from saakshya.store.repository import NUL_STAND_IN
    store.audit("sup.live", "search_plate", case_id="FIR-1",
                purpose="security scorecard", target="\x00'\"", result_count=0)
    store.audit("sup.live", "search_plate", case_id="FIR-1", target="GJ05AB1234")
    with store.engine.begin() as c:
        c.execute(text("UPDATE audit_log SET target=:t WHERE id=1"),
                  {"t": NUL_STAND_IN + "'\""})
    assert store.verify_audit_chain() == (True, None)
    with store.engine.begin() as c:
        c.execute(text("UPDATE audit_log SET target=:t WHERE id=1"), {"t": "?'\""})
    ok, err = store.verify_audit_chain()
    assert not ok and "id=1" in err
