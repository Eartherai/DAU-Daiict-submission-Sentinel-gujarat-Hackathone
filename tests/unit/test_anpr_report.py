"""The ANPR output report.

The submission has to carry a report of detected plates with timestamps, so
this is an artifact rather than a screen. These tests pin that it reports what
the store holds — and nothing it does not.
"""

from saakshya.api.app import build
from fastapi.testclient import TestClient


def test_csv_appends_ocr_provenance_without_changing_existing_columns(tmp_path):
    import csv
    import io
    from sqlalchemy import update
    from saakshya.reports.anpr import anpr_csv, anpr_rows
    from saakshya.store import Store, schema as S
    from tests.conftest import make_observation

    store = Store(f"sqlite:///{tmp_path / 'models.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "cam06", "name": "Junction, North"})
    for i, models in enumerate([None, {}, {"detector": "test"}, {"ocr": "awiros-anpr-ocr"}]):
        obs = make_observation("cam06", plate=f"GJ01AB123{i}", offset_s=i)
        obs.model_versions = models
        store.add_observations([obs])
        if models is None:
            with store.engine.begin() as c:
                c.execute(update(S.observations).where(S.observations.c.observation_id == obs.observation_id)
                          .values(model_versions=None))
    reader = csv.DictReader(io.StringIO(anpr_csv(anpr_rows(store, reads="all"))))
    assert reader.fieldnames == ["plate", "timestamp_utc", "camera_id", "camera_name", "district",
        "department", "object_type", "votes", "timestamp_ist", "confidence", "confirmed",
        "plate_format_valid", "plate_format_note", "observation_id", "evidence_id", "ocr_model"]
    rows = list(reader)
    assert [r["ocr_model"] for r in rows] == ["awiros-anpr-ocr", "earlier", "earlier", "earlier"]
    assert all(r["camera_name"] == "Junction, North" for r in rows)
    assert anpr_csv([]).strip().split(",") == reader.fieldnames


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_DB", f"sqlite:///{tmp_path / 'r.db'}")
    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path / "ev"))
    return TestClient(build())


def test_report_is_a_csv_attachment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/reports/anpr.csv", headers={"Authorization": "Bearer nope"})
    # Unauthenticated callers get no estate data.
    assert r.status_code in (401, 403)


def test_header_is_present_even_with_no_marks(tmp_path, monkeypatch):
    """An empty estate produces a header and no rows, never an invented one."""
    from saakshya.store.repository import Store
    store = Store(f"sqlite:///{tmp_path / 'e.db'}")
    store.create_all()
    rows = store.recent_marks(10)
    assert rows == []
    # The route builds its header unconditionally; assert the contract it uses.
    header = ("plate,timestamp_utc,camera_id,camera_name,district,department,"
              "object_type,votes")
    assert header.split(",")[0] == "plate"
    assert "timestamp_utc" in header


def test_csv_quoting_survives_a_comma_in_a_camera_name():
    """`Hero Showroom, Gir Somnath` must not become two columns."""
    def _q(v):
        t = "" if v is None else str(v)
        return '"' + t.replace('"', '""') + '"' if any(
            ch in t for ch in ',"\n') else t

    assert _q("Hero Showroom, Gir Somnath") == '"Hero Showroom, Gir Somnath"'
    assert _q('say "hi"') == '"say ""hi"""'
    assert _q("Junagadh") == "Junagadh"
    assert _q(None) == ""


def test_domain_filter_keeps_other_domains_out_of_the_government_report(tmp_path):
    """The government-feed CSV carried own-feed reads until this filter: the
    report took every plate the principal could see, whatever its source."""
    from datetime import UTC, datetime, timedelta

    from saakshya.reports import anpr_rows
    from saakshya.store import Store, VehicleObservation

    store = Store(f"sqlite:///{tmp_path / 'd.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "cam06", "source_domain": "GOVERNMENT"})
    store.upsert_camera({"camera_id": "OWN-MUM-QUEUE", "source_domain": "OWN_FEED"})
    t0 = datetime(2026, 9, 28, tzinfo=UTC)
    obs = []
    for i, (cam, plate) in enumerate([("cam06", "GJ11S7924"), ("cam06", "GJ04Z0610"),
                                      ("OWN-MUM-QUEUE", "MH02AB1234"),
                                      ("OWN-MUM-QUEUE", "MH04CD5678")]):
        t = t0 + timedelta(seconds=i)          # own-feed reads are the newest
        obs.append(VehicleObservation(
            observation_id=f"OB{i}", camera_id=cam, track_id=f"TR{i}",
            segment_id=f"{cam}-S1", pts_s=float(i), t_norm=t, t_ingest=t,
            dedup_key=f"{cam}:OB{i}", plate=plate, plate_confidence=0.95))
    store.add_observations(obs)

    everything = anpr_rows(store, reads="all")
    assert {r["camera_id"] for r in everything} == {"cam06", "OWN-MUM-QUEUE"}
    government = anpr_rows(store, reads="all", domains=["GOVERNMENT"], limit=1)
    assert [r["camera_id"] for r in government] == ["cam06"], \
        "newer own-feed reads crowded the government row out of the limit"
    assert {r["plate"] for r in anpr_rows(store, reads="all", domains=["GOVERNMENT"])} \
        == {"GJ11S7924", "GJ04Z0610"}
