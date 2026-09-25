"""The platform on PostgreSQL + PostGIS, end to end.

The store was described as "SQLite <-> PostgreSQL, same schema" and had never
run on PostgreSQL. It could not have: microsecond timestamps (1.8e15) were
32-bit INTEGER columns there, and the embedding column used SQLite's BLOB.
These tests run the flows an officer depends on against a real PostgreSQL with
PostGIS, in a throwaway schema, and are skipped when no server is configured:

    tools/db/setup_postgres.sh
    SAAKSHYA_TEST_PG_URL="$(cat var/pg/url)" pytest tests/postgres
"""
from __future__ import annotations

import os
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from saakshya.store import Store
from tests.conftest import make_observation

BASE = os.environ.get("SAAKSHYA_TEST_PG_URL", "").strip()
pytestmark = pytest.mark.skipif(not BASE, reason="SAAKSHYA_TEST_PG_URL not set")


@pytest.fixture(scope="module")
def pg_url():
    # A database of its own, not a schema: PostGIS lives in `public`, and with
    # `public` on the search path SQLAlchemy finds the main database's tables
    # there and creates nothing in the test schema.
    name = f"saakshya_t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(BASE, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"CREATE DATABASE {name}"))
    url = make_url(BASE).set(database=name)
    yield url.render_as_string(hide_password=False)
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE {name} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture(scope="module")
def world(pg_url, tmp_path_factory):
    from saakshya.api.app import create_app
    from saakshya.api.deps import AppState
    from saakshya.security import Role, TokenService
    tmp = tmp_path_factory.mktemp("pg")
    state = AppState(pg_url, evidence_root=tmp / "ev")
    state.require_auth = True
    s = state.store
    for cid, name, lat, lon in (("CAM-A", "Paldi", 23.0100, 72.5600),
                                ("CAM-B", "Ashram Rd", 23.0300, 72.5700),
                                ("CAM-C", "Far away", 23.2100, 72.6300)):
        s.upsert_camera({"camera_id": cid, "name": name, "district": "Ahmedabad",
                         "lat": lat, "lon": lon, "tier": "A", "enabled": True})
    ts = TokenService(s)
    ts.upsert_user("sup", Role.SUPERVISOR)
    ts.upsert_user("adm", Role.ADMIN)
    tok = {u: ts.mint(u) for u in ("sup", "adm")}
    return {"state": state, "client": TestClient(create_app(state), raise_server_exceptions=False),
            "tok": tok}


def h(world, user, **extra):
    return {"Authorization": f"Bearer {world['tok'][user]}", **extra}


PURPOSE = {"X-Case-Id": "CASE-PG-1", "X-Purpose": "tracing a vehicle on postgresql"}


def test_postgis_column_and_indexes_exist(world):
    s: Store = world["state"].store
    assert s.postgis, "PostGIS was not enabled on this PostgreSQL"
    with s.engine.connect() as c:
        idx = {r[0] for r in c.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'cameras'"))}
        geom = c.execute(text(
            "SELECT ST_AsText(geom) FROM cameras WHERE camera_id = 'CAM-A'")).scalar()
    assert {"ix_cameras_geom", "ix_cameras_geog"} <= idx
    assert geom == "POINT(72.56 23.01)"


def test_microsecond_timestamps_survive(world):
    s: Store = world["state"].store
    s.add_observations([make_observation("CAM-A", plate="GJ01PG1111", offset_s=0)])
    o = s.search_plate("GJ01PG1111")[0]
    assert o.t_norm.year >= 2026


def test_search_trajectory_alert_evidence_audit(world):
    c = world["client"]
    s: Store = world["state"].store
    a = make_observation("CAM-A", plate="GJ01PG2222", offset_s=100, track="T1")
    b = make_observation("CAM-B", plate="GJ01PG2222", offset_s=400, track="T2")
    s.add_observations([a, b])
    world["state"].investigation.refresh()
    r = c.get("/search?plate=GJ01PG2222", headers=h(world, "sup", **PURPOSE))
    assert r.status_code == 200 and len(r.json()["candidates"]) == 2
    tr = c.get("/trajectory/GJ01PG2222", headers=h(world, "sup", **PURPOSE))
    assert tr.status_code == 200, tr.text[:300]
    ev = world["state"].evidence.create(a, frame=np.zeros((24, 24, 3), dtype=np.uint8))
    chain = c.get("/evidence/chain/verify?fresh=1", headers=h(world, "sup")).json()
    assert chain["verified"] and any(r["evidence_id"] == ev.evidence_id for r in chain["records"])
    rep = c.get("/reports/vehicle/GJ01PG2222.html", headers=h(world, "sup", **PURPOSE))
    assert rep.status_code == 200 and "Paldi" in rep.text
    audit = c.get("/audit?limit=200", headers=h(world, "sup")).json()
    assert audit["chain_verified"], audit["chain_error"]


def test_zone_rule_on_postgresql(world):
    c = world["client"]
    s: Store = world["state"].store
    from datetime import UTC, datetime

    from saakshya.store import VehicleObservation
    t = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
    s.add_observations([VehicleObservation(
        camera_id="CAM-A", pts_s=0.0, t_norm=t, t_ingest=t, dedup_key="pg-zone",
        track_id="Z1", segment_id="S", object_type="person",
        bbox=(100.0, 100.0, 140.0, 300.0), detection_confidence=0.9,
        district="Ahmedabad", model_versions={"dwell_s": 9.0, "dwell_exceeded": True})])
    r = c.post("/zones", headers=h(world, "adm"), json={
        "camera_id": "CAM-A", "name": "Carriageway",
        "polygon": [[0, 200], [400, 200], [400, 400], [0, 400]],
        "classes": ["person"], "reason": "pedestrians off the carriageway",
        "authority": "test rule"})
    assert r.status_code == 201, r.text[:300]
    got = c.get(f"/zones/{r.json()['rule_id']}/entries", headers=h(world, "sup")).json()
    assert got["count"] >= 1


def test_nearby_cameras_use_postgis_and_agree_with_haversine(world, tmp_path):
    c = world["client"]
    r = c.get("/gis/near?lat=23.0100&lon=72.5600&radius_m=5000", headers=h(world, "sup")).json()
    assert r["engine"].startswith("postgis")
    ids = [x["camera_id"] for x in r["cameras"]]
    assert ids[:2] == ["CAM-A", "CAM-B"] and "CAM-C" not in ids     # CAM-C is ~23 km away
    lite = Store(f"sqlite:///{tmp_path / 'l.db'}")
    lite.create_all()
    for cam in world["state"].store.list_cameras():
        lite.upsert_camera({k: cam[k] for k in
                            ("camera_id", "name", "district", "lat", "lon", "tier")})
    h2 = lite.cameras_near(23.0100, 72.5600, 5000)
    assert h2["engine"].startswith("haversine")
    by = {x["camera_id"]: x["distance_m"] for x in h2["cameras"]}
    for x in r["cameras"]:
        assert abs(x["distance_m"] - by[x["camera_id"]]) < 10.0   # geodesic vs sphere


def test_viewport_query_matches_lat_lon_ranges(world):
    s: Store = world["state"].store
    box = s.cameras_in_bbox(south=23.0, west=72.55, north=23.05, east=72.60)
    inside = {c["camera_id"] for c in box}
    assert inside == {"CAM-A", "CAM-B"}
    # `&&` alone compared float4 boxes rounded outward, and ST_MakeEnvelope
    # put an inverted box's corners in order. Neither is what the lat/lon
    # ranges select, which is the SQLite answer.
    s.upsert_camera({"camera_id": "CAM-EDGE", "district": "Ahmedabad",
                     "lat": 23.5, "lon": 72.500001})
    try:
        assert s.cameras_in_bbox(south=23.4, west=72.4, north=23.6, east=72.5) == []
        assert s.cameras_in_bbox(south=23.0, west=72.60, north=23.05, east=72.55) == []
        assert [c["camera_id"] for c in s.cameras_in_bbox(
            south=23.4, west=72.4, north=23.6, east=72.500001)] == ["CAM-EDGE"]
    finally:
        s.delete_camera("CAM-EDGE")


@pytest.mark.parametrize("evil", ["GJ01AA1111\x00", "\x00'\"", "GJ\x1b[2J01"])
def test_control_characters_are_audited_not_a_server_error(world, evil):
    # The security scorecard's probe. SQLite once stored it verbatim in the
    # audit log; PostgreSQL text cannot hold NUL.
    c = world["client"]
    r = c.get("/search", params={"plate": evil}, headers=h(world, "sup", **PURPOSE))
    assert r.status_code in (200, 400, 422), r.text[:200]
    audit = c.get("/audit?limit=5", headers=h(world, "sup")).json()
    assert audit["chain_verified"], audit["chain_error"]


def test_a_nul_in_a_json_body_is_refused_not_a_server_error(world):
    c = world["client"]
    r = c.post("/zones", headers=h(world, "adm"), json={
        "camera_id": "CAM-A", "name": "Zone\u0000X",
        "polygon": [[0, 0], [10, 0], [10, 10]], "classes": ["person"],
        "reason": "nul probe", "authority": "test"})
    r2 = c.post("/cases", headers=h(world, "sup"), json={
        "case_id": "CASE-NUL-1", "title": "a\u0000b", "purpose": "probing nul handling"})
    assert r.status_code == r2.status_code == 400
    assert r.json()["detail"]["code"] == "NUL_CHARACTER" and r.headers.get("X-Request-Id")
    for path in ("/cameras/CAM%00A", "/observations/OB%00"):
        assert c.get(path, headers=h(world, "sup")).status_code == 400
    ok = c.post("/cases", headers=h(world, "sup"), json={
        "case_id": "CASE-NUL-2", "title": "spelled \\u0000 as text",
        "purpose": "probing nul handling"})
    assert ok.status_code in (200, 201), ok.text[:200]


def test_overview_counts_on_postgresql(world):
    # stats() counted long-stay people with SQLite's json_extract.
    r = world["client"].get("/overview", headers=h(world, "sup"))
    assert r.status_code == 200, r.text[:200]
    assert world["state"].store.stats()["observations_person_long_stay"] >= 1


def test_the_index_walk_gives_what_distinct_gives(world):
    s: Store = world["state"].store
    with s.engine.connect() as c:
        cams = {r[0] for r in c.execute(text("SELECT DISTINCT camera_id FROM observations"))}
        plates = {r[0] for r in c.execute(text(
            "SELECT DISTINCT plate FROM observations WHERE plate IS NOT NULL"))}
    assert s.observed_camera_ids() == cams and len(cams) >= 2
    assert set(s.distinct_plates()) == plates and len(plates) >= 2


def _observations(s: Store) -> int:
    with s.engine.connect() as c:
        return int(c.execute(text("SELECT count(*) FROM observations")).scalar() or 0)


def test_a_replayed_batch_keeps_every_new_observation(world):
    """PostgreSQL inserted row by row in one transaction and swallowed errors.
    The first duplicate aborted the transaction and the commit became a
    rollback: [new, already stored, new] stored nothing and reported 1 written.
    The same went for one row from a camera the registry does not hold, which
    PostgreSQL refused by foreign key and SQLite has always stored."""
    s: Store = world["state"].store
    a = make_observation("CAM-A", plate="GJ01PG9001", offset_s=9001)
    b = make_observation("CAM-A", plate="GJ01PG9002", offset_s=9002)
    c = make_observation("CAM-B", plate="GJ01PG9003", offset_s=9003)
    n0 = _observations(s)
    assert s.add_observations([a]) == 1
    assert s.add_observations([b, a, c]) == 2 and _observations(s) == n0 + 3
    stray = make_observation("CAM-UNREGISTERED", plate="GJ01PG9004", offset_s=9004)
    e = make_observation("CAM-B", plate="GJ01PG9005", offset_s=9005)
    assert s.add_observations([e, stray]) == 2 and _observations(s) == n0 + 5
    assert s.search_plate("GJ01PG9004")[0].camera_id == "CAM-UNREGISTERED"
    # And a camera that has been seen can be removed; its observations stay.
    s.upsert_camera({"camera_id": "CAM-GONE", "district": "Ahmedabad",
                     "lat": 23.02, "lon": 72.58})
    s.add_observations([make_observation("CAM-GONE", plate="GJ01PG9006", offset_s=9006)])
    assert s.delete_camera("CAM-GONE")
    assert s.search_plate("GJ01PG9006")[0].camera_id == "CAM-GONE"


def test_an_edge_replay_stores_what_it_acknowledges(world):
    """The receiver acknowledges every event it is sent, so the node purges
    them; a replay whose new events were rolled back lost them for good."""
    from saakshya.edge.queue import CentralReceiver
    s: Store = world["state"].store

    def event(i: int) -> dict:
        o = make_observation("CAM-A", plate=f"GJ01PG81{i:02d}", offset_s=8100 + i)
        return {"event_id": f"pg-edge-{i}", "event_type": "observation",
                "dedup_key": o.dedup_key, "sequence": i,
                "payload": {"camera_id": o.camera_id, "pts_s": o.pts_s,
                            "t_norm": o.t_norm.isoformat(),
                            "t_ingest": o.t_ingest.isoformat(),
                            "observation_id": o.observation_id, "plate": o.plate}}

    rx = CentralReceiver(s)
    e1, e2, e3 = event(1), event(2), event(3)
    assert rx.receive("pg-node", [e1]).applied == 1
    n0 = _observations(s)
    res = rx.receive("pg-node", [e1, e2, e3])          # the lost-ack resend
    assert (res.applied, res.duplicates) == (2, 1)
    assert sorted(res.acknowledged) == ["pg-edge-1", "pg-edge-2", "pg-edge-3"]
    assert _observations(s) == n0 + 2


def test_a_database_made_with_the_camera_foreign_key_loses_it(world):
    """create_all removes observations -> cameras from a PostgreSQL store made
    while the schema declared it (under the name PostgreSQL gave it); the other
    tables' keys to cameras stay."""
    s: Store = world["state"].store
    q = text("SELECT conrelid::regclass::text, conname FROM pg_constraint "
             "WHERE contype = 'f' AND confrelid = 'cameras'::regclass")
    with s.engine.begin() as c:
        before = set(c.execute(q).all())
        assert "observations" not in {t for t, _ in before}
        assert {"camera_health", "camera_capability"} <= {t for t, _ in before}
        c.execute(text(
            "ALTER TABLE observations ADD CONSTRAINT observations_camera_id_fkey "
            "FOREIGN KEY (camera_id) REFERENCES cameras (camera_id) NOT VALID"))
    s.create_all()
    with s.engine.connect() as c:
        assert set(c.execute(q).all()) == before


def test_a_partial_health_write_merges_as_on_sqlite(world):
    """PostgreSQL deleted the row and inserted only the fields passed, so a
    flush of state and fps reset connects to 0 and last_seen_us to NULL."""
    s: Store = world["state"].store
    s.upsert_health("CAM-C", {"state": "STREAMING", "measured_fps": 12.5,
                              "last_seen_us": 1_790_000_000_000_000, "connects": 3})
    s.upsert_health("CAM-C", {"state": "DOWN", "last_error": "timeout"})
    got = s.list_health(["CAM-C"])["CAM-C"]
    assert (got["state"], got["last_error"]) == ("DOWN", "timeout")
    assert (got["measured_fps"], got["last_seen_us"], got["connects"]) == (
        12.5, 1_790_000_000_000_000, 3)
    s.upsert_capability("CAM-C", "DAY", {"samples": 40, "sharpness": 61.0})
    s.upsert_capability("CAM-C", "DAY", {"samples": 41})
    cap = s.list_capability(["CAM-C"], "DAY")[0]
    assert (cap["samples"], cap["sharpness"]) == (41, 61.0)
    s.upsert_transition({"from_camera": "CAM-A", "to_camera": "CAM-C",
                         "support_count": 5, "travel_p50_s": 600.0})
    s.upsert_transition({"from_camera": "CAM-A", "to_camera": "CAM-C", "support_count": 6})
    tr = next(t for t in s.get_transitions("CAM-A") if t["to_camera"] == "CAM-C")
    assert (tr["support_count"], tr["travel_p50_s"]) == (6, 600.0)
