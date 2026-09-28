"""The Model 3 federated analytics report deliverable.

The report is generated from the store, so the properties worth pinning are that
its figures come from the data, that it splits everything by source provenance,
and that it surfaces the one thing federation exists to produce: a vehicle seen
under more than one source domain. The store is also opened read-only, which the
tool promises and this test exercises end to end.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reports"))

import federated_report as fr

from saakshya.store import schema as S
from saakshya.store.repository import Store, VehicleObservation, now_us


def _obs(cam, plate, t, *, otype="car", votes=2, seq=0):
    return VehicleObservation(
        camera_id=cam, pts_s=float(seq), t_norm=t, t_ingest=t,
        dedup_key=f"{cam}:seg:{plate}:{seq}", object_type=otype,
        plate=plate, plate_votes=votes, plate_confidence=0.9 if plate else None)


def _build(tmp_path) -> str:
    """A two-domain store: a government mark also seen on an own feed."""
    url = f"sqlite:///{tmp_path / 'fed.db'}"
    store = Store(url)
    store.create_all()
    # GOVERNMENT: cam01, cam02 (id pattern classifies these).
    store.upsert_camera({"camera_id": "cam01", "name": "Junction",
                         "department": "Home (Police)",
                         "source_domain": "GOVERNMENT", "lat": 23.0, "lon": 72.5})
    store.upsert_camera({"camera_id": "cam02", "name": "Bridge",
                         "department": "Transport",
                         "source_domain": "GOVERNMENT", "lat": 23.1, "lon": 72.6})
    # OWN_FEED: the golden traffic feed.
    store.upsert_camera({"camera_id": "OWN-TRAFFIC", "name": "Own traffic",
                         "department": "Own estate",
                         "source_domain": "OWN_FEED", "lat": 23.04, "lon": 72.58})

    base = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    obs = [
        # GJ01AA1111: cam01 (gov) -> cam02 (gov) -> OWN-TRAFFIC (own): cross-source.
        _obs("cam01", "GJ01AA1111", base, seq=1),
        _obs("cam02", "GJ01AA1111", base + timedelta(minutes=5), seq=2),
        _obs("OWN-TRAFFIC", "GJ01AA1111", base + timedelta(minutes=9), seq=3),
        # GJ02BB2222: government only, one camera, single read -> a lead.
        _obs("cam02", "GJ02BB2222", base + timedelta(minutes=2), votes=1, seq=4),
        # A person detection with no plate on the own feed.
        _obs("OWN-TRAFFIC", None, base + timedelta(minutes=1),
             otype="person", votes=0, seq=5),
    ]
    assert store.add_observations(obs) == len(obs)

    # One watchlist entry and one alert on a government camera.
    with store.engine.begin() as c:
        c.execute(insert(S.watchlist).values(
            watchlist_id="WL1", plate="GJ01AA1111", category="STOLEN",
            authority="Test SP", reason="test", status="ACTIVE",
            created_at_us=now_us()))
        c.execute(insert(S.alerts).values(
            alert_id="AL1", watchlist_id="WL1", camera_id="cam01",
            plate="GJ01AA1111", category="STOLEN", priority="HIGH",
            status="OPEN", t_norm_us=now_us(), created_at_us=now_us()))
    # Fold the WAL back into the main file on a fresh connection (a read-only
    # open cannot create the -shm it would otherwise need), so the reopen sees
    # everything the writer committed.
    store.engine.dispose()
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "fed.db"))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    return url


def test_read_only_url_rewrites_a_plain_sqlite_path():
    ro = fr.read_only_url("sqlite:///var/demo.db")
    assert ro.startswith("sqlite:///file:")
    assert "mode=ro" in ro and "uri=true" in ro
    # Already-URI and non-sqlite URLs are left alone.
    assert fr.read_only_url("sqlite:///file:/x?mode=ro&uri=true").count("mode=ro") == 1
    assert fr.read_only_url("postgresql://h/db") == "postgresql://h/db"


def test_immutable_report_cli_reads_snapshot_without_writes(tmp_path):
    import sqlite3
    import pytest

    url = _build(tmp_path)
    db = tmp_path / "fed.db"
    before = db.read_bytes()
    immutable_url = fr.read_only_url(url, immutable=True)
    assert "immutable=1" in immutable_url
    assert "mode=ro" in fr.read_only_url("sqlite:///file:/x?mode=rw&uri=true", immutable=True)
    assert fr.read_only_url(immutable_url, immutable=True) == immutable_url
    out = tmp_path / "report.md"
    assert fr.main(["--db", url, "--immutable", "--out", str(out)]) == 0
    assert "| GOVERNMENT | 2 |" in out.read_text()
    assert db.read_bytes() == before
    assert not Path(str(db) + "-wal").exists()
    assert not Path(str(db) + "-shm").exists()
    with sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True) as con:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("delete from cameras")


def test_report_opens_read_only_and_counts_from_the_store(tmp_path):
    url = _build(tmp_path)
    store = Store(fr.read_only_url(url))
    assert "mode=ro" in store.url
    data = fr.gather(store)

    assert data["cameras_total"] == 3
    assert data["cameras_by_domain"] == {"GOVERNMENT": 2, "OWN_FEED": 1}
    # Observations split by provenance, not lumped together.
    assert data["observations_by_domain"]["GOVERNMENT"] == 3
    assert data["observations_by_domain"]["OWN_FEED"] == 2
    assert data["obs_domain_type"]["OWN_FEED"]["person"] == 1


def test_report_isolates_cross_source_vehicles(tmp_path):
    url = _build(tmp_path)
    data = fr.gather(Store(fr.read_only_url(url)))

    # GJ01AA1111 spans government and own feed; GJ02BB2222 does not.
    assert set(data["cross_source"]) == {"GJ01AA1111"}
    assert data["cross_source"]["GJ01AA1111"]["domains"] == {"GOVERNMENT", "OWN_FEED"}
    # It was seen by three cameras, so it is cross-camera too.
    assert "GJ01AA1111" in data["cross_camera"]
    assert len(data["cross_camera"]["GJ01AA1111"]["cameras"]) == 3

    # Confirmed vs leads, per domain.
    assert data["plates_by_domain"]["GOVERNMENT"]["confirmed"] == 1  # GJ01AA1111
    assert data["plates_by_domain"]["GOVERNMENT"]["leads"] == 1      # GJ02BB2222


def test_report_attributes_watchlist_incidents_to_a_source(tmp_path):
    url = _build(tmp_path)
    data = fr.gather(Store(fr.read_only_url(url)))
    assert data["alerts_total"] == 1
    assert data["incidents_by_domain"] == {"GOVERNMENT": 1}


def test_report_tolerates_a_store_missing_a_nullable_column(tmp_path):
    """It opens read-only and so cannot migrate; a column added after the store
    was made must degrade to id-pattern provenance, not raise 'no such column'."""
    import sqlite3

    url = _build(tmp_path)
    con = sqlite3.connect(str(tmp_path / "fed.db"))
    try:
        con.execute("ALTER TABLE cameras DROP COLUMN source_domain")
        con.commit()
    except sqlite3.OperationalError:
        import pytest
        pytest.skip("this SQLite build cannot DROP COLUMN")
    finally:
        con.close()

    data = fr.gather(Store(fr.read_only_url(url)))
    # cam01/cam02 fall back to the id-pattern classifier -> GOVERNMENT.
    assert data["cameras_by_domain"]["GOVERNMENT"] == 2
    assert data["cameras_by_domain"]["OWN_FEED"] == 1


def test_render_reflects_the_gathered_figures(tmp_path):
    url = _build(tmp_path)
    data = fr.gather(Store(fr.read_only_url(url)))
    text = fr.render(data, url)

    assert "# Federated analytics report" in text
    # The federation headline appears with the real count.
    assert "1** marks were seen under more than one" in text
    assert "GJ01AA1111" in text
    assert "GOVERNMENT, OWN_FEED" in text
    # Provenance columns are present.
    assert "Cameras per source domain" in text
    assert "Watchlist incidents per source" in text
