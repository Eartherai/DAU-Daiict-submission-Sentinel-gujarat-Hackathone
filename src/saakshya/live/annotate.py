"""Draw current detections on an ingest still.

The live wall is a JPEG the ingest process already decoded. Overlaying the
boxes that were published in the last few seconds is how an operator sees
vehicles and plates on the same picture, without a second RTSP session.

Boxes are detector labels, not identity. A person box is not a face. A plate
box is a read attempt, not a confirmation.
"""
from __future__ import annotations

import io
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from saakshya.store import Store, to_us
from saakshya.store import schema as S

log = logging.getLogger("saakshya.live.annotate")

_COLOURS = {
    "person": (0, 180, 220),
    "car": (255, 200, 40),
    "truck": (255, 140, 40),
    "bus": (255, 100, 60),
    "van": (255, 160, 50),
    "truck_bus": (255, 140, 40),
    "motorcycle": (40, 220, 120),
    "bicycle": (80, 200, 90),
    "face": (210, 90, 160),
}
_PLATE = (40, 220, 90)
_WINDOW_S = 12.0
_PTS_WINDOW_S = 1.2
_MAX_BOXES = 24
_rows_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

# Overlay modes are metadata filters. They never invent detections.
OVERLAY_OFF = frozenset({"off", "none", "video", "video-only", "video_only"})
OVERLAY_VEHICLES = frozenset({"vehicles", "vehicle", "cars"})
OVERLAY_PEOPLE = frozenset({"people", "person", "persons"})
OVERLAY_ANPR = frozenset({"anpr", "plates", "plate"})


def overlay_allows(otype: str | None, plate: str | None, *,
                   overlay: str = "full",
                   people: bool = True, vehicles: bool = True,
                   anpr: bool = True, tracking: bool = True) -> bool:
    """Whether a stored observation should be drawn for this operator mode."""
    mode = (overlay or "full").strip().lower()
    if mode in OVERLAY_OFF:
        return False
    kind = (otype or "").lower()
    is_person = kind == "person"
    if mode in OVERLAY_VEHICLES:
        return (not is_person) and vehicles
    if mode in OVERLAY_PEOPLE:
        return is_person and people
    if mode in OVERLAY_ANPR:
        return bool(plate) and anpr
    if is_person and not people:
        return False
    if (not is_person) and not vehicles:
        return bool(plate) and anpr
    if not anpr and plate and not vehicles and not people:
        return False
    _ = tracking  # track-id is a label choice; boxes still come from store
    return True


def annotate_jpeg(jpeg: bytes, store: Store, camera_id: str, *,
                  preview_wh: tuple[int, int],
                  camera_wh: tuple[int | None, int | None],
                  pts_s: float | None = None,
                  overlay: str = "full",
                  people: bool = True, vehicles: bool = True,
                  anpr: bool = True) -> bytes:
    """Return a JPEG with recent boxes. On any failure, return the original.

    `pts_s` is the selected-camera decode clock. When it is set, boxes come
    from that moment in the recording — not the newest rows in the store.
    Overlay filters never fabricate detections: empty store → clean still.
    """
    if not jpeg:
        return jpeg
    if (overlay or "full").strip().lower() in OVERLAY_OFF:
        return jpeg
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return jpeg
    try:
        rows = _recent(store, camera_id, pts_s=pts_s)
        rows = [r for r in rows if overlay_allows(
            r.get("object_type"), r.get("plate"), overlay=overlay,
            people=people, vehicles=vehicles, anpr=anpr)]
        if not rows:
            return jpeg
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
        draw = ImageDraw.Draw(im)
        pw, ph = im.size
        cw, ch = camera_wh
        for rec in rows:
            otype, plate, bbox = rec.get("object_type"), rec.get("plate"), rec.get("bbox")
            box = _scale(bbox, pw, ph, cw, ch)
            if box is None:
                continue
            x1, y1, x2, y2 = box
            colour = _PLATE if plate else _COLOURS.get((otype or "").lower(),
                                                       (220, 220, 220))
            draw.rectangle([x1, y1, x2, y2], outline=colour, width=3)
            bits = [plate or (otype or "object")]
            if rec.get("track_id") and overlay not in OVERLAY_ANPR:
                bits.append(str(rec["track_id"]))
            if rec.get("confidence") is not None:
                bits.append(f"{float(rec['confidence']):.2f}")
            label = " · ".join(bits)
            try:
                font = ImageFont.truetype(
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", 13)
            except Exception:
                font = ImageFont.load_default()
            tb = draw.textbbox((0, 0), label, font=font)
            tw = max(tb[2] - tb[0] + 8, 12)
            th = max(tb[3] - tb[1] + 4, 12)
            top = max(0, y1 - th)
            draw.rectangle([x1, top, x1 + tw, y1], fill=colour)
            draw.text((x1 + 4, top + 1), label, fill=(10, 10, 10), font=font)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception as exc:
        log.info("annotate skipped for %s: %s", camera_id, type(exc).__name__)
        return jpeg


def live_boxes(store: Store, camera_id: str, *,
               overlay: str = "full",
               people: bool = True, vehicles: bool = True,
               anpr: bool = True,
               pts_s: float | None = None) -> dict[str, Any]:
    """Metadata overlay payload for native <video>. Never fabricates boxes."""
    rows = _recent(store, camera_id, pts_s=pts_s)
    people_n = vehicles_n = plated = 0
    tracks: set[str] = set()
    boxes: list[dict[str, Any]] = []
    for rec in rows:
        otype = (rec.get("object_type") or "").lower()
        if otype == "person":
            people_n += 1
        else:
            vehicles_n += 1
        if rec.get("track_id"):
            tracks.add(str(rec["track_id"]))
        if rec.get("plate"):
            plated += 1
        if not overlay_allows(rec.get("object_type"), rec.get("plate"),
                              overlay=overlay, people=people,
                              vehicles=vehicles, anpr=anpr):
            continue
        boxes.append(rec)
    return {
        "camera_id": camera_id,
        "overlay": overlay,
        "boxes": boxes,
        "people": people_n,
        "vehicles": vehicles_n,
        "tracked": len(tracks),
        "plates": plated,
        "note": ("Counts and boxes are recent store observations. "
                 "Zero means none stored — detections are never invented."),
    }


def _recent(store: Store, camera_id: str, *,
            pts_s: float | None = None) -> list[dict[str, Any]]:
    now = time.monotonic()
    bucket = f"{camera_id}:{round(pts_s, 1)}" if pts_s is not None else camera_id
    hit = _rows_cache.get(bucket)
    if hit and now - hit[0] < (0.12 if pts_s is not None else 0.8):
        return hit[1]
    out: list[dict[str, Any]] = []
    with store.engine.connect() as c:
        if pts_s is not None:
            window = _PTS_WINDOW_S
            rows = list(c.execute(
                select(S.observations)
                .where(S.observations.c.camera_id == camera_id,
                       S.observations.c.pts_s >= pts_s - window,
                       S.observations.c.pts_s <= pts_s + window)
                .order_by(S.observations.c.pts_s.desc())
                .limit(_MAX_BOXES)))
        else:
            cut = to_us(datetime.now(UTC) - timedelta(seconds=_WINDOW_S))
            rows = list(c.execute(
                select(S.observations)
                .where(S.observations.c.camera_id == camera_id,
                       S.observations.c.t_ingest_us >= cut)
                .order_by(S.observations.c.t_ingest_us.desc())
                .limit(_MAX_BOXES)))
            if not rows:
                newest = c.execute(
                    select(S.observations.c.t_ingest_us)
                    .where(S.observations.c.camera_id == camera_id)
                    .order_by(S.observations.c.t_ingest_us.desc())
                    .limit(1)).first()
                if newest is not None:
                    t0 = newest[0]
                    # Same moment in the recording, not 24 boxes from the whole clip.
                    window_us = 400_000
                    rows = list(c.execute(
                        select(S.observations)
                        .where(S.observations.c.camera_id == camera_id,
                               S.observations.c.t_ingest_us >= t0 - window_us,
                               S.observations.c.t_ingest_us <= t0 + window_us)
                        .order_by(S.observations.c.t_ingest_us.desc())
                        .limit(_MAX_BOXES)))
        for r in rows:
            m = r._mapping
            bbox = None
            if m["bbox_x1"] is not None:
                bbox = (m["bbox_x1"], m["bbox_y1"], m["bbox_x2"], m["bbox_y2"])
            conf = m["detection_confidence"]
            if conf is None:
                conf = m["plate_confidence"]
            out.append({
                "object_type": m["object_type"] or "object",
                "plate": m["plate"],
                "bbox": bbox,
                "track_id": m["track_id"],
                "confidence": float(conf) if conf is not None else None,
                "observation_id": m["observation_id"],
                "pts_s": m["pts_s"],
                "evidence_ref": m["evidence_ref"],
            })
    _rows_cache[bucket] = (now, out)
    return out


def _scale(bbox, pw: int, ph: int, cw: int | None, ch: int | None
           ) -> tuple[int, int, int, int] | None:
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = (float(v) for v in bbox)
    mx = max(abs(x1), abs(y1), abs(x2), abs(y2))
    if mx <= 1.5:
        x1, x2 = x1 * pw, x2 * pw
        y1, y2 = y1 * ph, y2 * ph
    elif cw and ch and cw > 1 and ch > 1:
        x1, x2 = x1 * pw / cw, x2 * pw / cw
        y1, y2 = y1 * ph / ch, y2 * ph / ch
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x1 = max(0, min(pw - 1, x1))
    x2 = max(1, min(pw, x2))
    y1 = max(0, min(ph - 1, y1))
    y2 = max(1, min(ph, y2))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return int(x1), int(y1), int(x2), int(y2)


def crop_plate_jpeg(jpeg: bytes, bbox, *,
                    camera_wh: tuple[int | None, int | None],
                    pad: float = 0.22) -> bytes | None:
    """A crop of the plate region from a still. None if the box is unusable."""
    if not jpeg or not bbox:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    except Exception:
        return None
    pw, ph = im.size
    box = _scale(bbox, pw, ph, camera_wh[0], camera_wh[1])
    if box is None:
        return None
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    px, py = int(w * pad), int(h * pad)
    crop = im.crop((max(0, x1 - px), max(0, y1 - py),
                    min(pw, x2 + px), min(ph, y2 + py)))
    if crop.width < 8 or crop.height < 8:
        return None
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=88)
    return buf.getvalue()
