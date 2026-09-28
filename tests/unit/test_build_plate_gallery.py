"""The government plate gallery: evidence copies, honest statistics, and no
own-feed or synthetic crop passed off as government evidence."""

import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "demo"))

import build_plate_gallery as gallery


def _png(path: Path, seed: int) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (200, 100))
    im.putdata([((x * 7 + seed) % 256, (y * 5) % 256, (x ^ y) % 256)
                for y in range(100) for x in range(200)])
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, format="PNG")
    return path.read_bytes()


def _row(image, camera, domain, plate="", selected=False):
    yes = "yes" if selected else "no"
    return {"image": image, "source_domain": domain, "camera": camera,
            "timestamp": "2026-09-21T02:13:45+05:30", "plate_text": plate,
            "confidence": "0.965" if plate else "", "agreeing_reads": "6" if plate else "",
            "track_id": "", "provenance": "fixture", "included_in_deck": yes,
            "included_in_government_video": yes}


@pytest.fixture()
def world(tmp_path):
    root = tmp_path / "repo"
    gov = _png(root / "var/evidence/EZTEST.png", 1)
    _png(root / "var/live_samples/own_plate.png", 2)
    db = root / "var/live.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE cameras (camera_id TEXT PRIMARY KEY, source_domain TEXT,
                              integration_model TEXT);
        CREATE TABLE observations (observation_id TEXT, camera_id TEXT, plate TEXT,
                                   plate_votes INTEGER, t_norm_us INTEGER);
        CREATE TABLE evidence (evidence_id TEXT PRIMARY KEY, frame_sha256 TEXT);
    """)
    con.executemany("INSERT INTO cameras VALUES (?,?,?)", [
        ("cam06", "GOVERNMENT", "REAL_PROBE_ID"), ("cam21", "GOVERNMENT", "REAL_PROBE_ID"),
        ("OWN-TRAFFIC", "OWN_FEED", "OWN_FEED"), ("CTL-00001", "SYNTHETIC_CONTROL", "SYNTHETIC")])
    t = 1_789_900_000_000_000
    con.executemany("INSERT INTO observations VALUES (?,?,?,?,?)", [
        ("o1", "cam06", "GJ11S7924", 6, t), ("o2", "cam06", "GJ11S7924", 1, t + 1),
        ("o3", "cam06", "GJ10CG4786", 1, t + 2), ("o4", "cam21", "GJ38BH5815", 2, t + 3),
        ("o5", "cam21", "GJ01DY5552", 1, t + 4),
        ("o6", "cam06", None, 0, t + 5),                       # no plate: not a read
        ("o7", "OWN-TRAFFIC", "MH02AB1234", 5, t + 6),         # not government
        ("o8", "CTL-00001", "GJ01XX0001", 3, t + 7)])          # not government
    con.execute("INSERT INTO evidence VALUES (?,?)",
                ("EZTEST", hashlib.sha256(gov).hexdigest()))
    con.commit()
    con.close()
    return root


def _manifest(root: Path, rows) -> Path:
    p = root / "reports/final_plate_gallery_manifest.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=gallery.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return p


def _build(root: Path):
    out = root / "var/demo/plate_gallery"
    return gallery.build(root, out, root / "reports/final_plate_gallery_manifest.csv",
                         root / "var/live.db"), out


def test_originals_are_byte_identical_and_cards_are_made(world):
    _manifest(world, [
        _row("var/evidence/EZTEST.png#xywh=40,20,120,50", "cam06", "GOVERNMENT",
             "GJ11S7924", selected=True),
        _row("var/live_samples/own_plate.png", "OWN-TRAFFIC", "OWN_FEED")])
    res, out = _build(world)
    assert res["selected"] == 1 and res["candidates"] == 2
    src = (world / "var/evidence/EZTEST.png").read_bytes()
    assert (out / "originals/EZTEST.png").read_bytes() == src
    sel = json.loads((out / "selected.json").read_text())
    assert sel[0]["original_sha256"] == hashlib.sha256(src).hexdigest()
    assert (out / sel[0]["display_image"]).is_file()
    # An unselected row is not copied anywhere.
    assert not (out / "originals/own_plate.png").exists()
    page = (out / "gallery.html").read_text()
    assert "Government ANPR — measured observations" in page
    assert "data:image/png;base64," in page and "var/live.db" in page


def test_the_display_crop_is_only_enlarged(world):
    """Every card pixel in the plate area is a copy of an original pixel."""
    import io

    from PIL import Image
    orig = (world / "var/evidence/EZTEST.png").read_bytes()
    row = _row("x", "cam06", "GOVERNMENT", "GJ11S7924", selected=True)
    png, k = gallery.display_card(orig, (40, 20, 160, 70), row)
    card = Image.open(io.BytesIO(png)).convert("RGB")
    crop = Image.open(io.BytesIO(orig)).convert("RGB").crop((40, 20, 160, 70))
    ox = 20 + (gallery.CROP_BOX[0] - crop.width * k) // 2
    oy = 20 + (gallery.CROP_BOX[1] - crop.height * k) // 2
    for x, y in [(0, 0), (17, 9), (119, 49), (63, 31)]:
        assert card.getpixel((ox + x * k, oy + y * k)) == crop.getpixel((x, y))


def test_stats_cover_every_government_read_not_the_selection(world):
    _manifest(world, [
        _row("var/evidence/EZTEST.png#xywh=40,20,120,50", "cam06", "GOVERNMENT",
             "GJ11S7924", selected=True)])
    _, out = _build(world)
    s = json.loads((out / "stats.json").read_text())
    assert s["total_reads"] == 5                 # o1..o5; not the one selected row
    assert s["distinct_plates"] == 4
    assert s["confirmed_registrations"] == 2     # GJ11S7924 (6), GJ38BH5815 (2)
    assert s["confirmed_reads"] == 2
    assert s["cameras_with_reads"] == 2
    assert s["note"] == gallery.NOTE
    assert s["source"] == "var/live.db"


def test_own_feed_cannot_be_selected_as_government_evidence(world):
    _manifest(world, [_row("var/live_samples/own_plate.png", "OWN-TRAFFIC",
                           "OWN_FEED", "MH02AB1234", selected=True)])
    with pytest.raises(SystemExit, match="not a GOVERNMENT camera"):
        _build(world)


def test_a_non_government_camera_relabelled_government_is_refused(world):
    _manifest(world, [_row("var/live_samples/own_plate.png", "CTL-00001",
                           "GOVERNMENT", "GJ01XX0001", selected=True)])
    with pytest.raises(SystemExit, match="store says SYNTHETIC_CONTROL"):
        _build(world)


def test_a_missing_image_fails_loudly(world):
    _manifest(world, [_row("var/evidence/NOPE.png", "cam06", "GOVERNMENT")])
    with pytest.raises(SystemExit, match="manifest image missing"):
        _build(world)


def test_a_sealed_frame_that_no_longer_matches_its_record_is_refused(world):
    _manifest(world, [_row("var/evidence/EZTEST.png", "cam06", "GOVERNMENT",
                           "GJ11S7924", selected=True)])
    p = world / "var/evidence/EZTEST.png"
    p.write_bytes(p.read_bytes() + b"\0")
    with pytest.raises(SystemExit, match="does not match its evidence record"):
        _build(world)


def test_the_committed_manifest_is_well_formed():
    p = ROOT / "reports/final_plate_gallery_manifest.csv"
    rows = gallery.read_manifest(p)
    picked = [r for r in rows if r.selected]
    assert rows and 1 <= len(picked) <= 12
    for r in picked:
        assert r.data["source_domain"] == "GOVERNMENT"
        assert r.data["camera"].startswith("cam")
        assert r.data["plate_text"] and r.data["confidence"]
