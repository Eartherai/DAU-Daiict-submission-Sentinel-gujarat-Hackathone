"""The submission detection report must describe the store, not a 20k slice."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from saakshya.capability import TimeBand
from saakshya.store import Store, VehicleObservation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "verify"))

import detection_report as dr  # noqa: E402

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)


def _store(tmp_path) -> Store:
    s = Store(f"sqlite:///{tmp_path / 'r.db'}")
    s.create_all()
    s.upsert_camera({"camera_id": "cam01", "name": "one",
                     "district": "Ahmedabad", "lat": 23.0, "lon": 72.0})
    s.upsert_camera({"camera_id": "cam06", "name": "six",
                     "district": "Surat"})
    return s


def _obs(cam: str, sec: int, *, plate: str | None = None, otype: str = "car",
         votes: int = 0) -> VehicleObservation:
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(
        camera_id=cam, pts_s=float(sec), t_norm=t, t_ingest=t,
        dedup_key=f"{cam}:{sec}:{plate or otype}",
        plate=plate, object_type=otype,
        plate_votes=votes if plate else 0,
        plate_confidence=0.9 if plate else None,
    )


def test_summary_counts_the_store_not_a_truncated_export(tmp_path):
    s = _store(tmp_path)
    s.add_observations([
        _obs("cam01", i, otype="car") for i in range(5)
    ] + [
        _obs("cam06", 100 + i, plate="GJ32AG0028", votes=2) for i in range(3)
    ] + [
        _obs("cam01", 200, otype="person"),
    ])
    exported = dr.rows(s, plates_only=False, limit=4)
    assert len(exported) == 4
    summary = dr.summarise(s)
    assert summary["detections"] == 9
    assert summary["with_registration_mark"] == 3
    assert summary["distinct_marks"] == ["GJ32AG0028"]
    assert summary["cameras_contributing"] == 2
    by_type = dict(summary["by_object_type"])
    assert by_type["car"] == 8
    assert by_type["person"] == 1


def test_unlimited_export_includes_every_observation(tmp_path):
    s = _store(tmp_path)
    s.add_observations([_obs("cam01", i) for i in range(7)])
    assert len(dr.rows(s, plates_only=False, limit=0)) == 7


def test_looping_plate_collapses_to_one_mark_row(tmp_path):
    s = _store(tmp_path)
    s.add_observations([
        _obs("cam06", i, plate="GJ32AG0028", votes=2) for i in range(5)
    ])
    marks = dr.mark_rows(s)
    assert len(marks) == 1
    assert marks[0]["registration_mark"] == "GJ32AG0028"
    assert marks[0]["camera_id"] == "cam06"
    assert marks[0]["hits"] == 5


def test_anpr_unsuitable_uses_the_all_band_not_a_later_night_row(tmp_path):
    s = _store(tmp_path)
    s.upsert_capability("cam01", str(TimeBand.ALL), {"anpr_grade": "UNSUITABLE"})
    s.upsert_capability("cam01", str(TimeBand.NIGHT), {"anpr_grade": "UNKNOWN"})
    s.upsert_capability("cam06", str(TimeBand.ALL), {"anpr_grade": "UNSUITABLE"})
    s.add_observations([_obs("cam01", 1)])
    summary = dr.summarise(s)
    assert summary["anpr_unsuitable_cameras"] == ["cam01", "cam06"]


def test_skipped_csv_is_labelled_in_markdown():
    summary = {
        "detections": 10, "cameras_contributing": 1,
        "with_registration_mark": 0, "distinct_marks": [],
        "first": "t0", "last": "t1", "by_object_type": [("car", 10)],
        "anpr_unsuitable_cameras": [], "by_camera": [("cam01", 10)],
        "csv_skipped": True,
    }
    md = dr.markdown(summary, [], [], 40)
    assert "CSV was not rewritten this run" in md
    assert "counts are SQL over the whole store" in md
