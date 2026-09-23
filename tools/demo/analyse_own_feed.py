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


def analyse(camera_id: str, *, max_seconds: float | None = None,
            tidy: bool = True) -> dict:
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

    pipe = CameraPipeline(camera_id, cfg, district="Ahmedabad")
    segment = f"SG-{camera_id}"
    epoch = datetime.fromtimestamp(path.stat().st_mtime, UTC)

    plate_of: dict[str, str] = {}
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

    duration = len(frames) / fps if fps else 0.0
    plates = sorted(set(plate_of.values()))
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
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cameras", nargs="+")
    ap.add_argument("--max-seconds", type=float, default=None)
    a = ap.parse_args()
    for cid in a.cameras:
        print(f"analysing {cid}…", flush=True)
        out = analyse(cid, max_seconds=a.max_seconds)
        dest = MEDIA / f"{cid}.tracks.json"
        dest.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        kb = dest.stat().st_size / 1024
        print(f"wrote {dest.relative_to(ROOT)} — {out['frame_count']} frames, "
              f"{out['tracks']} tracks, plates {out['plates_accepted'] or 'none'}, "
              f"{kb:.0f} KB, analysed in {out['analysed_in_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
