#!/usr/bin/env python3
"""Run the production pipeline over an own-feed file and keep every frame's result.

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
pipeline's own vote has accepted it.
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
    distort those counters; this repeats its acceptance rule side-effect free:
    at least `min_votes` agreeing valid reads with mean OCR confidence at or
    above `min_confidence`.
    """
    from collections import Counter

    from saakshya.analytics.plates import slot_typed as parse

    out: dict[str, str] = {}
    for track_id, voter in getattr(pipe, "_voters", {}).items():
        reads = voter._reads.get(track_id) or []
        valid = [(parse(r.text), r) for r in reads]
        valid = [(p, r) for p, r in valid if p.valid]
        if not valid:
            continue
        ranked = Counter(p.canonical for p, _ in valid).most_common(2)
        best, votes = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0
        # Drawn on screen, a plate must hold: three agreeing reads and a clear
        # lead over the next reading. At the pipeline's own two, an early pair
        # (MH46Z0518) was drawn and then replaced (MH46Z8518) as reads came in.
        # What the store records is still decided at the end of the track.
        if votes < max(3, anpr_cfg.min_votes) or votes < runner + 2:
            continue
        conf = sum(r.confidence for p, r in valid if p.canonical == best) / votes
        if conf >= anpr_cfg.min_confidence:
            out[track_id] = best
    return out


def analyse(camera_id: str, *, max_seconds: float | None = None,
            tidy: bool = True, record: str | None = None) -> dict:
    import av

    from render_demo_video import Row, _tidy_drawn  # reuse the render's filter
    from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
    from saakshya.ingest.frame import Frame

    path = MEDIA / f"{camera_id}.mp4"
    if not path.is_file():
        raise SystemExit(f"no own-feed file for {camera_id}: {path}")

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
        district = cam.get("district") or district
    pipe = CameraPipeline(camera_id, cfg, district=district)
    # Observations are stamped with the time this platform processed the file.
    # The footage's own capture date is not known, and inventing one would put
    # a fabricated timestamp into an evidence store.
    epoch = datetime.now(UTC)
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
        if not (4.0 <= fps <= 60.0):
            fps = 15.0
        width = vs.codec_context.width
        height = vs.codec_context.height
        codec = vs.codec_context.name
        n = 0
        for i, vf in enumerate(container.decode(video=0)):
            # Frame index over the measured rate, not the container pts: dumped
            # clips often carry a collapsed timebase, and the browser plays the
            # picture at its rate, which is what the overlay must match.
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
                              int(round(r.score * 100)), r.plate or "",
                              1 if r.confirmed else 0])
            frames.append([round(pts, 3), boxes])
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

    duration = len(frames) / fps if fps else 0.0
    # The plates a track ended with - the published result - not every value
    # the overlay held on the way there.
    plates = sorted(set(final_plate.values()))
    return {
        "camera_id": camera_id,
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
        "recorded_into": record or None,
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cameras", nargs="+")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--record", metavar="DB_URL", default=None,
                    help="also write the pipeline's observations into this "
                         "store, so plates read off the file are searchable")
    a = ap.parse_args()
    for cid in a.cameras:
        print(f"analysing {cid}…", flush=True)
        out = analyse(cid, max_seconds=a.max_seconds, record=a.record)
        dest = MEDIA / f"{cid}.tracks.json"
        dest.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        kb = dest.stat().st_size / 1024
        print(f"wrote {dest.relative_to(ROOT)} — {out['frame_count']} frames, "
              f"{out['tracks']} tracks, plates {out['plates_accepted'] or 'none'}, "
              f"{out['observations_recorded']} observations recorded, "
              f"{kb:.0f} KB, analysed in {out['analysed_in_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
