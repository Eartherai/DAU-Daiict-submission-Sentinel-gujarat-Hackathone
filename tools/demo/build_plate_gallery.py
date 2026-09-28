#!/usr/bin/env python3
"""Government ANPR plate gallery for the deck and the government film.

Reads `reports/final_plate_gallery_manifest.csv` (one row per candidate crop
the project holds) and writes, under `--out`:

* `originals/` — each selected image copied byte for byte, and checked by
  SHA-256 after the copy. A sealed evidence frame is also checked against the
  `frame_sha256` its evidence row holds.
* `display/` — one card per selected image: the plate region enlarged with
  nearest-neighbour resampling only, and the camera, time, plate text and
  confidence printed beside it. No sharpening, no super-resolution, no
  retouching: every displayed pixel is a copy of a pixel in the original.
* `selected.json` — the selected rows.
* `stats.json` — computed over every government plate read in the store,
  not over the selection.
* `gallery.html` — self-contained (images inlined), sized for 1920x1080.

The manifest `image` is a path relative to `--root`, optionally with a W3C
media fragment `#xywh=x,y,w,h` naming the plate region of a larger frame
(the original stays the whole frame), or `store:<table>/<rowid>` for an image
held as a BLOB. A missing image, a checksum mismatch, or a selected row that is
not from a GOVERNMENT camera stops the run with a non-zero exit.

    python tools/demo/build_plate_gallery.py
    python tools/demo/build_plate_gallery.py --root /path/to/repo --out /tmp/gallery
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import json
import re
import shutil
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.command.domain import GOVERNMENT, classify_source_domain

COLUMNS = ("image", "source_domain", "camera", "timestamp", "plate_text",
           "confidence", "agreeing_reads", "track_id", "provenance",
           "included_in_deck", "included_in_government_video")

#: Same rule as `saakshya.reports.anpr.CONFIRM_VOTES` and the store's
#: `marks_in_latest_hour` / `stats()`: a read agreed across two or more frames
#: of one track is a confirmation; below that it is a lead.
CONFIRM_VOTES = 2

NOTE = ("gallery shows selected examples; statistics cover every government "
        "read in the store")

IST = timezone(timedelta(hours=5, minutes=30))
_XYWH = re.compile(r"^xywh=(\d+),(\d+),(\d+),(\d+)$")
_STORE = re.compile(r"^store:([A-Za-z_][A-Za-z0-9_]*)/(\d+)$")

CARD_W, CARD_H = 1200, 520
CROP_BOX = (720, 300)          # the area the enlarged plate may fill


class GalleryError(SystemExit):
    """Stops the run with a message and exit status 1."""

    def __init__(self, msg: str) -> None:
        super().__init__(f"build_plate_gallery: {msg}")


@dataclass
class Row:
    n: int
    data: dict[str, str]

    @property
    def selected(self) -> bool:
        return (self.data["included_in_deck"].strip().lower() == "yes"
                or self.data["included_in_government_video"].strip().lower() == "yes")


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def open_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise GalleryError(f"store not found: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def read_manifest(path: Path) -> list[Row]:
    if not path.exists():
        raise GalleryError(f"manifest not found: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        if tuple(rd.fieldnames or ()) != COLUMNS:
            raise GalleryError(f"manifest columns are {rd.fieldnames}, expected {list(COLUMNS)}")
        return [Row(i, dict(r)) for i, r in enumerate(rd, start=2)]


def camera_domains(con: sqlite3.Connection) -> dict[str, str]:
    """Domain per camera, resolved the way the application resolves it."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(cameras)")}
    sd = "source_domain" if "source_domain" in cols else "NULL"
    im = "integration_model" if "integration_model" in cols else "NULL"
    return {cid: classify_source_domain(cid, stored=s, integration_model=m)
            for cid, s, m in con.execute(f"SELECT camera_id, {sd}, {im} FROM cameras")}


def check_government(rows: list[Row], domains: dict[str, str]) -> None:
    """A selected row must be GOVERNMENT in the manifest *and* in the store."""
    for r in rows:
        cam = r.data["camera"].strip()
        stated = r.data["source_domain"].strip().upper()
        held = domains.get(cam)
        if held is not None and stated and stated != held:
            raise GalleryError(f"manifest line {r.n}: {cam} is labelled {stated} "
                               f"but the store says {held}")
        if not r.selected:
            continue
        if stated != GOVERNMENT or held != GOVERNMENT:
            raise GalleryError(
                f"manifest line {r.n}: {cam} ({held or 'not in store'}) is not a "
                "GOVERNMENT camera and cannot be shown as government evidence")


def load_image(root: Path, con: sqlite3.Connection, spec: str
               ) -> tuple[bytes, str, tuple[int, int, int, int] | None]:
    """(original bytes, file name, optional plate region) for one manifest image."""
    spec = spec.strip()
    m = _STORE.match(spec)
    if m:
        table, rowid = m.group(1), int(m.group(2))
        cols = [c[1] for c in con.execute(f'PRAGMA table_info("{table}")')
                if (c[2] or "").upper() == "BLOB" and c[1] != "embedding"]
        if len(cols) != 1:
            raise GalleryError(f"{spec}: table has {len(cols)} image BLOB columns, need one")
        got = con.execute(f'SELECT "{cols[0]}" FROM "{table}" WHERE rowid = ?',
                          (rowid,)).fetchone()
        if not got or not got[0]:
            raise GalleryError(f"manifest image missing: {spec}")
        return bytes(got[0]), f"{table}_{rowid}.bin", None
    path, _, frag = spec.partition("#")
    region = None
    if frag:
        fm = _XYWH.match(frag)
        if not fm:
            raise GalleryError(f"{spec}: fragment must be #xywh=x,y,w,h")
        x, y, w, h = (int(v) for v in fm.groups())
        region = (x, y, x + w, y + h)
    p = root / path
    if not p.is_file():
        raise GalleryError(f"manifest image missing: {p}")
    return p.read_bytes(), p.name, region


def check_sealed(con: sqlite3.Connection, name: str, data: bytes) -> None:
    """A sealed evidence frame must still hash to what its record says."""
    tabs = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "evidence" not in tabs:
        return
    got = con.execute("SELECT frame_sha256 FROM evidence WHERE evidence_id = ?",
                      (Path(name).stem,)).fetchone()
    if got and got[0] and hashlib.sha256(data).hexdigest() != got[0]:
        raise GalleryError(f"{name}: SHA-256 does not match its evidence record")


# --------------------------------------------------------------------------- #
# Statistics over the whole store
# --------------------------------------------------------------------------- #
def _iso(us: int | None) -> str:
    if us is None:
        return ""
    return datetime.fromtimestamp(us / 1e6, tz=UTC).astimezone(IST).isoformat(
        timespec="seconds")


#: The verified store snapshot closes at 24 Sep 2026 16:10:09 IST, the same
#: pin `tools/sizing/measure_compression.py` uses. Reads made after it (the
#: 28 Sep recording sessions) are reported with the film, not folded into
#: the snapshot statistics the deck and HLD quote.
SNAPSHOT_UNTIL_US = 1790246409848994


def government_stats(con: sqlite3.Connection, store_label: str,
                     until_us: int | None = SNAPSHOT_UNTIL_US) -> dict[str, Any]:
    gov = sorted(c for c, d in camera_domains(con).items() if d == GOVERNMENT)
    marks = ",".join("?" * len(gov)) or "NULL"
    base = ("FROM observations WHERE plate IS NOT NULL AND plate != '' "
            f"AND camera_id IN ({marks})")
    args: list[Any] = list(gov)
    if until_us is not None:
        base += " AND t_norm_us <= ?"
        args.append(until_us)
    total, distinct, cams, t0, t1 = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT plate), COUNT(DISTINCT camera_id), "
        f"MIN(t_norm_us), MAX(t_norm_us) {base}", args).fetchone()
    confirmed = con.execute(
        f"SELECT COUNT(DISTINCT plate) {base} AND plate_votes >= ?",
        [*args, CONFIRM_VOTES]).fetchone()[0]
    confirmed_reads = con.execute(
        f"SELECT COUNT(*) {base} AND plate_votes >= ?", [*args, CONFIRM_VOTES]).fetchone()[0]
    return {
        "total_reads": int(total or 0),
        "distinct_plates": int(distinct or 0),
        "confirmed_registrations": int(confirmed or 0),
        "confirmed_reads": int(confirmed_reads or 0),
        "cameras_with_reads": int(cams or 0),
        "government_cameras_in_registry": len(gov),
        "window_start": _iso(t0),
        "window_end": _iso(t1),
        "snapshot_until": _iso(until_us) if until_us is not None else None,
        "source": store_label,
        "generated_at": datetime.now(UTC).astimezone(IST).isoformat(timespec="seconds"),
        "definitions": {
            "government": ("cameras whose domain resolves to GOVERNMENT via "
                           "saakshya.command.domain.classify_source_domain"),
            "read": ("one row of the observations table with a non-empty plate — "
                     "the rows the ANPR report (saakshya.reports.anpr) exports"),
            "confirmed_registrations": (
                f"distinct plates with at least one read of plate_votes >= {CONFIRM_VOTES} "
                "(saakshya.reports.anpr.CONFIRM_VOTES; the same rule as "
                "Repository.marks_in_latest_hour and Repository.stats)"),
            "confirmed_reads": f"reads with plate_votes >= {CONFIRM_VOTES}",
            "window": "earliest and latest t_norm of those reads, IST",
        },
        "note": NOTE,
    }


# --------------------------------------------------------------------------- #
# Display cards
# --------------------------------------------------------------------------- #
def _font(size: int, mono: bool = False):
    from PIL import ImageFont
    names = (["Menlo.ttc", "DejaVuSansMono.ttf", "Courier.ttc"] if mono
             else ["Helvetica.ttc", "DejaVuSans.ttf", "Arial.ttf"])
    for n in names:
        for d in ("/System/Library/Fonts", "/usr/share/fonts/truetype/dejavu", ""):
            try:
                return ImageFont.truetype(str(Path(d) / n) if d else n, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


#: Faces are blurred in anything published (the rule `blur_heads.py` records
#: for the own feed). The whole-frame thumbnail on a card shows riders and
#: pedestrians, so it is blurred with the same production person detector and
#: head geometry; the plate crop is cut from the untouched frame.
_PEOPLE: Any = None


def blur_faces(img: Any, detect: Callable[[Any], list[list]] | None = None) -> tuple[Any, int]:
    """A copy of the PIL image with every detected person's head blurred.

    ``detect`` maps a BGR array to person boxes; by default it is the
    production detector run whole-frame and tiled, as `blur_heads.py` does.
    Raises if that detector cannot load: an unblurred face is not published.
    """
    import numpy as np
    from PIL import ImageFilter

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from blur_heads import detect_people, head_regions

    global _PEOPLE
    if detect is None:
        if _PEOPLE is None:
            from blur_heads import _detector
            _PEOPLE = _detector()
        backend = _PEOPLE

        def detect(bgr: Any) -> list[list]:
            return detect_people(bgr, backend, person_conf=0.25)

    rgb = np.asarray(img.convert("RGB"))
    regions = head_regions(detect(rgb[:, :, ::-1].copy()), img.width, img.height)
    out = img.copy()
    for box in regions:
        patch = out.crop(box)
        radius = max(6, max(patch.size) // 3)
        out.paste(patch.filter(ImageFilter.GaussianBlur(radius)), box)
    return out, len(regions)


def plate_only(original: bytes, region: tuple[int, int, int, int], k: int) -> bytes:
    """The plate region alone, enlarged by the card's integer factor.

    For slides and films, where the card's own text would be too small to
    read. Nearest neighbour, like the card: every pixel is a copy of one in
    the sealed frame, so nothing is made clearer than it was.
    """
    from PIL import Image

    crop = Image.open(io.BytesIO(original)).convert("RGB").crop(region)
    big = crop.resize((crop.width * k, crop.height * k), Image.NEAREST)
    out = io.BytesIO()
    big.save(out, format="PNG")
    return out.getvalue()


def display_card(original: bytes, region: tuple[int, int, int, int] | None,
                 row: dict[str, str],
                 detect: Callable[[Any], list[list]] | None = None) -> tuple[bytes, int]:
    """The card PNG and the integer enlargement used."""
    from PIL import Image, ImageDraw

    src = Image.open(io.BytesIO(original)).convert("RGB")
    crop = src.crop(region) if region else src
    # Integer factor, nearest neighbour: each source pixel becomes an exact
    # k x k block, so nothing is interpolated, sharpened or invented.
    k = max(1, min(CROP_BOX[0] // crop.width, CROP_BOX[1] // crop.height))
    big = crop.resize((crop.width * k, crop.height * k), Image.NEAREST)

    card = Image.new("RGB", (CARD_W, CARD_H), (248, 247, 244))
    d = ImageDraw.Draw(card)
    d.rectangle((0, 0, 759, CARD_H), fill=(24, 26, 30))
    card.paste(big, (20 + (CROP_BOX[0] - big.width) // 2, 20 + (CROP_BOX[1] - big.height) // 2))
    if region:
        # Where the plate sits in the frame: a small copy of the whole frame
        # with the region outlined. The outline is on the thumbnail only.
        th, _ = blur_faces(src, detect)
        th.thumbnail((320, 180))
        s = th.width / src.width
        ImageDraw.Draw(th).rectangle(
            [int(region[0] * s) - 2, int(region[1] * s) - 2,
             int(region[2] * s) + 2, int(region[3] * s) + 2], outline=(255, 196, 0), width=2)
        card.paste(th, (20, CARD_H - th.height - 20))
        d.text((360, CARD_H - 150), "whole sealed frame,\nfaces blurred;\nplate region outlined",
               font=_font(18), fill=(190, 190, 190))

    ink, dim = (20, 22, 26), (95, 98, 105)
    # (text, size, mono, colour, advance). The feed's burned-in clock can
    # differ (a replayed source keeps its own date), so the card says which
    # clock it prints.
    lines = [
        (row["camera"], 30, False, ink, 46),
        (row["timestamp"].replace("T", "  "), 22, False, dim, 28),
        ("time SAAKSHYA read it (IST), not the camera overlay", 15, False, dim, 34),
        ("plate read", 18, False, dim, 26),
        (row["plate_text"] or "—", 44, True, ink, 70),
        (f"OCR confidence  {row['confidence'] or '—'}", 24, False, ink, 36),
        (f"agreeing reads  {row['agreeing_reads'] or '—'}", 24, False, ink, 60),
        (f"crop enlarged x{k}, nearest-neighbour;\nno sharpening or enhancement",
         17, False, dim, 0),
    ]
    y = 34
    for text, size, mono, colour, advance in lines:
        d.text((790, y), text, font=_font(size, mono=mono), fill=colour)
        y += advance
    out = io.BytesIO()
    card.save(out, format="PNG")
    return out.getvalue(), k


# --------------------------------------------------------------------------- #
# Gallery page
# --------------------------------------------------------------------------- #
def gallery_html(cards: list[tuple[dict[str, Any], bytes]], stats: dict[str, Any]) -> str:
    cols = 3 if len(cards) <= 6 else 4
    tiles = []
    for sel, png in cards:
        uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        alt = f"{sel['camera']} {sel['timestamp']} {sel['plate_text']}"
        tiles.append(f'<figure><img src="{uri}" alt="{html.escape(alt)}"></figure>')
    line = (f"{stats['total_reads']:,} government plate reads · "
            f"{stats['distinct_plates']:,} distinct plates · "
            f"{stats['confirmed_registrations']:,} confirmed (≥{CONFIRM_VOTES} agreeing reads) · "
            f"{stats['cameras_with_reads']} cameras with reads · "
            f"{stats['window_start'][:10]} to {stats['window_end'][:10]} IST")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Government ANPR gallery</title>
<style>
:root {{ --bg:#f8f7f4; --ink:#16181c; --dim:#5f6269; --rule:#d9d6cf; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:16px/1.4 -apple-system, "Helvetica Neue", Arial, sans-serif; }}
main {{ max-width:1920px; margin:0 auto; padding:28px 40px 20px; }}
h1 {{ margin:0 0 6px; font-size:34px; font-weight:600; }}
.stats {{ margin:0 0 18px; color:var(--dim); font-size:18px; }}
.grid {{ display:grid; grid-template-columns:repeat({cols}, 1fr); gap:16px; }}
figure {{ margin:0; border:1px solid var(--rule); background:#fff; }}
img {{ display:block; width:100%; height:auto; }}
footer {{ margin-top:16px; color:var(--dim); font-size:14px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns:1fr; }} main {{ padding:16px; }} }}
</style></head><body><main>
<h1>Government ANPR — measured observations</h1>
<p class="stats">{html.escape(line)}</p>
<div class="grid">
{chr(10).join(tiles)}
</div>
<footer>Source: {html.escape(stats['source'])} (opened read-only) and
reports/final_plate_gallery_manifest.csv. {html.escape(NOTE[0].upper() + NOTE[1:])}.
Plate crops are pixel regions of the retained frames, enlarged by nearest-neighbour only.
Generated {html.escape(stats['generated_at'])}.</footer>
</main></body></html>
"""


# --------------------------------------------------------------------------- #
def build(root: Path, out: Path, manifest: Path, store: Path,
          detect: Callable[[Any], list[list]] | None = None) -> dict[str, Any]:
    rows = read_manifest(manifest)
    con = open_ro(store)
    try:
        check_government(rows, camera_domains(con))
        # Every manifest image must exist, selected or not: a manifest that
        # names files nobody holds is not a record of what was found.
        loaded = {r.n: load_image(root, con, r.data["image"]) for r in rows}
        try:
            label = str(store.resolve().relative_to(root.resolve()))
        except ValueError:
            label = str(store)
        stats = government_stats(con, label)
        for d in ("originals", "display", "plate"):
            shutil.rmtree(out / d, ignore_errors=True)
            (out / d).mkdir(parents=True, exist_ok=True)
        selected, cards = [], []
        for r in rows:
            if not r.selected:
                continue
            data, name, region = loaded[r.n]
            check_sealed(con, name, data)
            orig = out / "originals" / name
            if not orig.exists():
                orig.write_bytes(data)
            if hashlib.sha256(orig.read_bytes()).digest() != hashlib.sha256(data).digest():
                raise GalleryError(f"{orig}: copy is not byte-identical")
            png, k = display_card(data, region, r.data, detect)
            stem = f"{r.data['camera']}_{r.data['plate_text'] or 'unread'}"
            disp = out / "display" / f"{len(selected) + 1:02d}_{stem}.png"
            disp.write_bytes(png)
            sel = {
                "image": r.data["image"],
                "original_image": str(orig.relative_to(out)),
                "original_sha256": hashlib.sha256(data).hexdigest(),
                "display_image": str(disp.relative_to(out)),
                "display_scale": k,
                "plate_image": None,
                "camera": r.data["camera"],
                "timestamp": r.data["timestamp"],
                "plate_text": r.data["plate_text"],
                "confidence": r.data["confidence"],
                "agreeing_reads": r.data["agreeing_reads"],
                "provenance": r.data["provenance"],
            }
            if region:
                plate = out / "plate" / disp.name
                plate.write_bytes(plate_only(data, region, k))
                sel["plate_image"] = str(plate.relative_to(out))
            selected.append(sel)
            cards.append((sel, png))
    finally:
        con.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / "selected.json").write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    (out / "gallery.html").write_text(gallery_html(cards, stats), encoding="utf-8")
    return {"candidates": len(rows), "selected": len(selected), "stats": stats}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repository whose var/ holds the images and store")
    ap.add_argument("--out", type=Path, help="default: <root>/var/demo/plate_gallery")
    ap.add_argument("--manifest", type=Path,
                    help="default: <root>/reports/final_plate_gallery_manifest.csv")
    ap.add_argument("--store", type=Path, help="default: <root>/var/live.db")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    res = build(root,
                a.out or root / "var/demo/plate_gallery",
                a.manifest or root / "reports/final_plate_gallery_manifest.csv",
                a.store or root / "var/live.db")
    s = res["stats"]
    print(f"{res['selected']} of {res['candidates']} candidates selected; "
          f"store: {s['total_reads']} government reads, {s['distinct_plates']} plates, "
          f"{s['confirmed_registrations']} confirmed, {s['cameras_with_reads']} cameras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
