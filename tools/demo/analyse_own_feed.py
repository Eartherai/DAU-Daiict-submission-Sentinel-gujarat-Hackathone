#!/usr/bin/env python3
"""Run the production pipeline over a recorded file and keep every frame's result.

The Intelligence view used to show an own feed as a JPEG swapped every 450 ms
from a snapshot cache with a one-second lifetime, over boxes polled from the
live AI worker at roughly 1.4 frames a second. On a 12 fps clip that is a
slideshow, and an assessor watching requirement 3 — "AI-powered detection and
analytics" — saw a still photograph with a box that jumped once a second.

A recorded file does not need to be sampled like a live camera. The browser can
play the MP4 at its own frame rate, and the detections can be drawn against
`video.currentTime` — provided they exist for every frame. This produces them,
using the same `CameraPipeline` the government grid runs, not a demo detector.

    python tools/demo/analyse_own_feed.py OWN-TRAFFIC OWN-PEOPLE

writes `var/media/<CAMERA>.tracks.json` beside each file. The sidecar records
the file's SHA-256; the server refuses to serve boxes for a file whose bytes
have changed since, so replacing the footage can never leave stale boxes drawn
over a different picture.

What is drawn is presentation of what the pipeline saw, and the output says so:
track ids are renumbered #1, #2… because a 28-character ULID over a car reads to
an officer like a garbage number plate, and a plate appears only once the
pipeline's own vote has accepted it - and stays on the film only if it is the
plate the track ended up publishing, the one the store records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

MEDIA = ROOT / "var" / "media"

#: Object classes, encoded as one character so a two-minute 30 fps clip stays a
#: few hundred kilobytes rather than tens of megabytes.
TYPE_CODE = {"person": "p", "car": "c", "truck": "t", "bus": "b",
             "motorcycle": "m", "bicycle": "y", "auto": "a"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _accepted_now(pipe, anpr_cfg) -> dict[str, str]:
    """Plates the per-track vote would publish now, without resolving it.

    PlateVoter.resolve counts its rejections, so calling it every frame would
    distort those counters; this asks the voter's own side-effect-free parts
    instead: at least `min_votes` agreeing valid reads, holding `min_agreement`
    of the reads that look like the plate (never-issued lookalikes included)
    and ahead of each of them, with mean OCR confidence at or above
    `min_confidence`.
    """
    from collections import Counter

    out: dict[str, str] = {}
    for track_id, voter in getattr(pipe, "_voters", {}).items():
        reads = voter._reads.get(track_id) or []
        valid, unissued = voter.tally(reads)
        if not valid:
            continue
        counts = Counter(p.canonical for p, _ in valid)
        ranked = counts.most_common(2)
        best, votes = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0
        # Drawn on screen, a plate must hold: three agreeing reads and a clear
        # lead over the next reading. At the pipeline's own two, an early pair
        # (MH46Z0518) was drawn and then replaced (MH46Z8518) as reads came in.
        # What the store records is still decided at the end of the track.
        if votes < max(3, anpr_cfg.min_votes) or votes < runner + 2:
            continue
        if not voter.agreed(best, votes, counts, unissued):
            continue
        conf = sum(r.confidence for p, r in valid if p.canonical == best) / votes
        if conf >= anpr_cfg.min_confidence:
            out[track_id] = best
    return out


def _settle_drawn_plates(frames: list[list], track_of: dict[int, str],
                         final_plate: dict[str, str]) -> int:
    """Blank every drawn plate its track did not end up publishing.

    A plate is drawn from the frame on which the vote would accept it, but the
    vote can withdraw that acceptance as reads come in: a blurred plate read
    MH01EX0900 three times was drawn from the third read on, the scattered
    reads after it made the agreement rule refuse it, and the store recorded no
    plate for the track - while the film went on showing the invented mark.
    Once the file has been read, a box may carry only the plate the store holds
    for its track. Returns how many boxes lost a plate.
    """
    cleared = 0
    for _, boxes in frames:
        for box in boxes:
            if box[7] and box[7] != final_plate.get(track_of.get(box[5], "")):
                box[7] = ""
                cleared += 1
    return cleared


def analyse(camera_id: str, *, max_seconds: float | None = None,
            tidy: bool = True, record: str | None = None,
            media: Path = MEDIA) -> dict:
    import av
    from render_demo_video import Row, _tidy_drawn  # reuse the render's filter

    from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
    from saakshya.ingest.frame import Frame

    path = media / f"{camera_id}.mp4"
    if not path.is_file():
        raise SystemExit(f"no recorded file for {camera_id}: {path}")

    provenance = {}
    if camera_id.startswith("GOVREC-"):
        provenance = json.loads(path.with_suffix(".manifest.json").read_text())
        if provenance.get("camera_id") != camera_id or provenance.get("sha256") != sha256_file(path):
            raise ValueError("recording manifest does not match footage")

    cfg = PipelineConfig()
    cfg.validate_models = True
    cfg.enable_vehicle_detector = True
    cfg.enable_person_detector = True
    # A plate is drawn only once the pipeline's own vote accepts it. The live
    # peek at a single unvoted read is what put nonsense on screen before.
    cfg.anpr.enable_single_read_leads = False

    store = None
    district = "Ahmedabad"
    if record:
        from saakshya.store.repository import Store
        store = Store(record)
        store.create_all()
        cam = store.get_camera(camera_id) or {}
        if provenance and cam.get("source_domain") != "ARCHIVAL_REPLAY":
            raise ValueError("register this camera as ARCHIVAL_REPLAY before recording findings")
        district = cam.get("district") or district
    pipe = CameraPipeline(camera_id, cfg, district=district)
    # Government replays use the measured platform capture window plus file
    # PTS, never an invented original scene date. Own feeds retain processing
    # time because their capture date is unknown.
    epoch = (datetime.fromisoformat(provenance["capture_start_ist"])
             if provenance else datetime.now(UTC))
    segment = f"SG-{camera_id}-{epoch.strftime('%Y%m%dT%H%M%S')}"
    recorded: list = []
    n_recorded = 0

    plate_of: dict[str, str] = {}
    final_plate: dict[str, str] = {}
    short_id: dict[str, int] = {}
    frames: list[list] = []
    classes: dict[str, int] = {}
    started = time.time()

    with av.open(str(path)) as container:
        vs = container.streams.video[0]
        try:
            fps = float(vs.average_rate) if vs.average_rate else 15.0
        except (TypeError, ValueError):
            fps = 15.0
        if provenance and not (0 < fps <= 240):
            raise ValueError("recording frame rate unavailable")
        if not provenance and not (4.0 <= fps <= 60.0):
            fps = 15.0
        width = vs.codec_context.width
        height = vs.codec_context.height
        codec = vs.codec_context.name
        n = 0
        first_pts = None
        for i, vf in enumerate(container.decode(video=0)):
            # New captures preserve presentation timestamps, including gaps.
            # Older own-feed files retain their established frame-rate timing.
            if provenance:
                current = float(vf.time) if vf.time is not None else i / fps
                if first_pts is None:
                    first_pts = current
                pts = current - first_pts
            else:
                pts = i / fps
            if max_seconds is not None and pts > max_seconds:
                break
            frame = Frame(camera_id=camera_id, segment_id=segment, pts_s=pts,
                          t_norm=epoch + timedelta(seconds=pts),
                          t_ingest=datetime.now(UTC),
                          image=vf.to_ndarray(format="bgr24"),
                          width=vf.width, height=vf.height,
                          codec=codec, frame_index=i)
            for ob in pipe.process(frame):
                if ob.plate and ob.track_id:
                    plate_of[ob.track_id] = ob.plate
                    final_plate[ob.track_id] = ob.plate
                if store is not None:
                    recorded.append(ob)
            if store is not None and len(recorded) >= 200:
                n_recorded += store.add_observations(recorded) or len(recorded)
                recorded = []

            # A track's plate is known to the tracker only when the track ends
            # and its observation is emitted - by then it is no longer drawn,
            # so no frame of the first films ever carried a plate. The vote is
            # read live instead, by the pipeline's own rule, and a plate is
            # drawn from the frame on which that rule would accept it.
            plate_of.update(_accepted_now(pipe, cfg.anpr))

            drawn: list = []
            seen: set[str] = set()
            for pool in (pipe.tracks.get(camera_id, segment),
                         pipe.people.get(camera_id, segment)):
                for t in pool.tracks.values():
                    if t.track_id in seen:
                        continue
                    seen.add(t.track_id)
                    drawn.append(Row(
                        t_norm=frame.t_norm.isoformat(), camera_id=camera_id,
                        camera_name=camera_id, district="", department="",
                        track_id=t.track_id, object_type=t.label,
                        confirmed=bool(t.confirmed), score=float(t.score),
                        box=tuple(int(v) for v in t.box),  # type: ignore[arg-type]
                        plate=plate_of.get(t.track_id), plate_confidence=None))
            if tidy:
                drawn = _tidy_drawn(drawn)

            boxes = []
            for r in drawn:
                num = short_id.setdefault(r.track_id, len(short_id) + 1)
                kind = (r.object_type or "vehicle").lower()
                classes[kind] = classes.get(kind, 0) + 1
                x1, y1, x2, y2 = r.box
                boxes.append([x1, y1, x2, y2, TYPE_CODE.get(kind, "v"), num,
                              round(r.score * 100), r.plate or "",
                              1 if r.confirmed else 0])
            frames.append([round(pts, 6), boxes])
            n += 1
            if n % 50 == 0:
                rate = n / max(0.001, time.time() - started)
                print(f"  {camera_id}: {n} frames · {rate:.1f} fps analysed",
                      flush=True)

    for ob in pipe.flush():
        if ob.plate and ob.track_id:
            plate_of[ob.track_id] = ob.plate
            final_plate[ob.track_id] = ob.plate
        if store is not None:
            recorded.append(ob)
    if store is not None and recorded:
        n_recorded += store.add_observations(recorded) or len(recorded)
    _settle_drawn_plates(frames, {num: tid for tid, num in short_id.items()}, final_plate)

    duration = (frames[-1][0] + 1 / fps) if frames else 0.0
    # The plates a track ended with - the published result - not every value
    # the overlay held on the way there.
    plates = sorted(set(final_plate.values()))
    return {
        "camera_id": camera_id,
        "source_domain": "ARCHIVAL_REPLAY" if provenance else "OWN_FEED",
        "source_camera_id": provenance.get("source_camera_id"),
        "capture_start_ist": provenance.get("capture_start_ist"),
        "synthetic": provenance.get("synthetic", False),
        "timing": "presentation_timestamps" if provenance else "frame_rate",
        "timestamp_basis": "capture window + file PTS" if provenance else "processing time",
        "file": path.name,
        "sha256": sha256_file(path),
        "width": width, "height": height, "fps": round(fps, 3),
        "codec": codec, "duration_s": round(duration, 3),
        "frame_count": len(frames),
        "generated_at": datetime.now(UTC).isoformat(),
        "analysed_in_s": round(time.time() - started, 1),
        "pipeline": "saakshya.analytics.pipeline.CameraPipeline "
                    "(the same pipeline the government grid runs)",
        "label": ("Detections produced by this platform's pipeline over this "
                  "recorded file, frame by frame. Presentation drops nested "
                  "duplicates and cabin occupants; the pipeline saw every box."),
        "type_codes": {v: k for k, v in TYPE_CODE.items()} | {"v": "vehicle"},
        "tracks": len(short_id),
        "class_counts": classes,
        "plates_accepted": plates,
        "observations_recorded": n_recorded,
        "recorded_into": "configured store" if record else None,
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cameras", nargs="+")
    ap.add_argument("--media", type=Path, default=MEDIA)
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--record", metavar="DB_URL", default=None,
                    help="also write the pipeline's observations into this "
                         "store, so plates read off the file are searchable")
    a = ap.parse_args()
    for cid in a.cameras:
        print(f"analysing {cid}…", flush=True)
        out = analyse(cid, max_seconds=a.max_seconds, record=a.record, media=a.media)
        dest = a.media / f"{cid}.tracks.json"
        temporary = dest.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        temporary.replace(dest)
        kb = dest.stat().st_size / 1024
        print(f"wrote {dest.name} — {out['frame_count']} frames, "
              f"{out['tracks']} tracks, plates {out['plates_accepted'] or 'none'}, "
              f"{out['observations_recorded']} observations recorded, "
              f"{kb:.0f} KB, analysed in {out['analysed_in_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
