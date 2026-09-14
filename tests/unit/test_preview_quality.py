"""Stored stills that are fit to put under a registration mark."""
from pathlib import Path

import numpy as np
from PIL import Image

from saakshya.live.preview import count_stills, preview_usable, write_preview


def _bgr(rgb: tuple[int, int, int], w: int = 160, h: int = 90) -> np.ndarray:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = (rgb[2], rgb[1], rgb[0])  # BGR
    return arr


def test_count_and_usable_night_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    rng = np.random.default_rng(2)
    ys = np.linspace(30, 110, 180)
    xs = np.linspace(20, 90, 320)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    night = np.stack([xx, yy * 0.65, yy * 0.35], axis=-1)
    night = np.clip(night + rng.integers(-5, 6, night.shape), 0, 255).astype(np.uint8)
    write_preview("cam01", night, max_width=320, quality=85)
    assert count_stills() == 1
    assert preview_usable("cam01") is True
    assert preview_usable("missing") is False


def test_rejects_green_false_colour(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    write_preview("cam10", _bgr((20, 180, 40), 320, 180), max_width=320, quality=85)
    assert preview_usable("cam10") is False


def test_rejects_checkerboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    h, w = 180, 320
    board = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            board[y, x] = 220 if ((x // 8) + (y // 8)) % 2 else 30
    write_preview("cam12", board, max_width=320, quality=90)
    assert preview_usable("cam12") is False


def test_recent_marks_prefers_usable_stills(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from saakshya.store import Store, VehicleObservation, to_us

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    preview = Path(tmp_path) / "preview"
    preview.mkdir()
    rng = np.random.default_rng(3)
    ok = np.clip(
        np.stack([np.full((180, 320), 50), np.full((180, 320), 62),
                  np.full((180, 320), 88)], axis=-1)
        + rng.integers(0, 18, (180, 320, 3)), 0, 255).astype(np.uint8)
    bad = np.clip(
        np.stack([np.full((180, 320), 20), np.full((180, 320), 210),
                  np.full((180, 320), 30)], axis=-1)
        + rng.integers(0, 8, (180, 320, 3)), 0, 255).astype(np.uint8)
    Image.fromarray(ok).save(preview / "cam01.jpg", quality=85)
    Image.fromarray(bad).save(preview / "cam10.jpg", quality=85)

    store = Store("sqlite:///:memory:")
    store.create_all()
    t0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)
    for cid in ("cam01", "cam10"):
        store.upsert_camera({"camera_id": cid, "name": cid, "district": "Ahmedabad"})
    for i, (cid, plate) in enumerate((("cam10", "GJ10AA0001"),
                                      ("cam01", "GJ01AA0001"))):
        t = t0 + timedelta(seconds=i)
        store.add_observations([VehicleObservation(
            camera_id=cid, pts_s=float(i), t_norm=t, t_ingest=t,
            dedup_key=f"{cid}:{i}", plate=plate, object_type="car",
            bbox=(0.2, 0.3, 0.55, 0.62) if cid == "cam01" else None)])
    marks = store.recent_marks(8)
    assert marks[0]["camera_id"] == "cam01"
    assert marks[0]["still_ok"] is True
    here = store.marks_for_camera("cam01", 8)
    assert here[0]["plate"] == "GJ01AA0001"
    assert here[0]["camera_id"] == "cam01"
    assert here[0]["bbox"] == [0.2, 0.3, 0.55, 0.62]
    assert any(m["camera_id"] == "cam10" and m["still_ok"] is False for m in marks)
