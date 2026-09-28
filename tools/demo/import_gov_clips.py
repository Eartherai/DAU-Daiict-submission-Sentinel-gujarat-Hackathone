#!/usr/bin/env python3
"""Import the 15 Sep government RTSP clips as labelled ARCHIVAL_REPLAY recordings.

On 15 Sep 2026 ``tools/demo/capture_live_clips.py`` kept twelve seconds of
source time from each reachable government camera (the frames between 1.1 s
and 13.1 s of the stream's own presentation clock) and recorded the count in
``var/demo/live_clips/scores.json``. The container timestamps it wrote are
broken, so a browser cannot play the files at their real rate. This tool:

1. refuses any clip whose size differs from the one ``scores.json`` recorded
   at capture, or that does not decode to the recorded frame count;
2. re-times it at its measured source rate (frames / 12 s) without dropping,
   duplicating or altering a frame;
3. writes the same manifest ``capture_gov_footage.py`` writes, with the
   capture window taken from the file's own time, and registers
   ``GOVREC-camNN`` as ARCHIVAL_REPLAY through that tool's ``register``;
4. blurs heads with ``blur_heads.py`` unless ``--no-blur``.

No network is opened. Nothing here is labelled live.

    python tools/demo/import_gov_clips.py cam06 cam12 --register-db sqlite:///var/govfilm.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_gov_footage import CAM_ID, IST, digest, read_cameras, register  # noqa: E402

CLIPS = ROOT / "var" / "demo" / "live_clips"
MEDIA = ROOT / "var" / "media"
#: Source seconds kept per clip by capture_live_clips.py (scores.json "seconds").
SOURCE_WINDOW_S = 12


class ImportFailure(RuntimeError):
    pass


def scores(clips: Path) -> dict:
    data = json.loads((clips / "scores.json").read_text())
    if data.get("seconds") != SOURCE_WINDOW_S:
        raise ImportFailure("scores.json does not describe 12-second source windows")
    return {c["camera_id"]: c for c in data["cameras"]}


def import_clip(cid: str, score: dict, clips: Path, media: Path) -> dict:
    """Re-time one verified capture into media/GOVREC-<cid>.mp4 with a manifest."""
    import av

    if not CAM_ID.fullmatch(cid):
        raise ImportFailure("camera ids must be camNN")
    src = clips / f"{cid}.mp4"
    if not score.get("ok") or not score.get("show"):
        raise ImportFailure(f"{cid}: not a showable capture in scores.json")
    if not src.is_file() or src.stat().st_size != score.get("bytes"):
        raise ImportFailure(f"{cid}: clip changed since capture (size differs)")
    target = media / f"GOVREC-{cid}.mp4"
    manifest_path = target.with_suffix(".manifest.json")
    if target.exists() or manifest_path.exists():
        raise ImportFailure(f"{cid}: recording already exists")
    media.mkdir(parents=True, exist_ok=True)

    frames = int(score["frames"])
    rate = Fraction(frames, SOURCE_WINDOW_S)
    tmp = target.with_suffix(".partial.mp4")
    count = 0
    try:
        with av.open(str(src)) as inp, av.open(str(tmp), "w",
                                               options={"movflags": "+faststart"}) as out:
            vs = inp.streams.video[0]
            enc = out.add_stream("libx264", rate=rate)
            enc.width, enc.height = vs.codec_context.width, vs.codec_context.height
            enc.pix_fmt = "yuv420p"
            enc.options = {"preset": "medium", "crf": "16"}
            enc.time_base = Fraction(1, 90000)
            for vf in inp.decode(video=0):
                picture = vf.reformat(format="yuv420p")
                picture.pts = round(count / rate * 90000)
                picture.time_base = enc.time_base
                for packet in enc.encode(picture):
                    out.mux(packet)
                count += 1
            for packet in enc.encode():
                out.mux(packet)
        if count != frames:
            raise ImportFailure(f"{cid}: decoded {count} frames, capture recorded {frames}")
        end = datetime.fromtimestamp(src.stat().st_mtime, IST)
        start = end - timedelta(seconds=float(score["seconds"]))
        result = {
            "camera_id": f"GOVREC-{cid}", "source_camera_id": cid,
            "source_domain": "ARCHIVAL_REPLAY", "synthetic": False,
            "label": "RECORDED GOVERNMENT FOOTAGE",
            "capture_start_ist": start.isoformat(timespec="seconds"),
            "capture_end_ist": end.isoformat(timespec="seconds"),
            "timestamp_basis": ("file time of the 15 Sep capture by "
                                "tools/demo/capture_live_clips.py; not the original scene date"),
            "retiming": (f"{SOURCE_WINDOW_S} s source window; container timestamps rebuilt at "
                         "the measured rate (frames / 12 s); every frame kept, none added"),
            "frames": count, "fps": float(rate), "fps_fraction": str(rate),
            "duration_s": count / float(rate), "width": enc.width, "height": enc.height,
            "source_url": "<redacted>", "capture_sha256": digest(src),
            "sha256": digest(tmp), "file": target.name, "heads_blurred": None,
        }
        tmp.replace(target)
        manifest_path.write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        tmp.unlink(missing_ok=True)


def blur_clip(cid: str, media: Path) -> dict:
    """Blur heads in place; the manifest then describes the blurred bytes."""
    import blur_heads

    if media.resolve() != blur_heads.MEDIA.resolve():
        raise ImportFailure("blurring works on var/media only")
    camera = f"GOVREC-{cid}"
    clip = media / f"{camera}.mp4"
    source = media / f"{camera}.source.mp4"
    manifest_path = clip.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    unblurred = manifest["sha256"]
    try:
        heads = blur_heads.blur(camera)["heads_blurred"]
        note = "heads blurred by tools/demo/blur_heads.py (production person detector)"
    except SystemExit:
        # blur_heads refuses to publish when it found nobody; the unaltered
        # clip is then the file, and the manifest says no person was detected.
        if clip.exists() or not source.exists():
            raise
        shutil.move(str(source), str(clip))
        heads = 0
        note = "no person detected by the production person detector; nothing blurred"
    manifest.update(heads_blurred=heads, blur_note=note, unblurred_sha256=unblurred,
                    sha256=digest(clip))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cameras", nargs="+")
    ap.add_argument("--registry", type=Path, default=Path("var/live.db"))
    ap.add_argument("--clips", type=Path, default=CLIPS)
    ap.add_argument("--media", type=Path, default=MEDIA)
    ap.add_argument("--register-db", help="target SQLAlchemy URL (a film store, not live.db)")
    ap.add_argument("--no-blur", action="store_true")
    a = ap.parse_args()
    table = scores(a.clips)
    cams = read_cameras(a.registry, a.cameras)
    store = None
    if a.register_db:
        from saakshya.store import Store
        store = Store(a.register_db)
        store.create_all()
    for cam in cams:
        cid = cam["camera_id"]
        m = import_clip(cid, table.get(cid, {}), a.clips, a.media)
        print(f"GOVREC-{cid}: {m['frames']} frames at {m['fps']:.2f} fps, "
              f"{m['width']}x{m['height']}, captured {m['capture_start_ist']}", flush=True)
        if not a.no_blur:
            m = blur_clip(cid, a.media)
            print(f"GOVREC-{cid}: {m['blur_note']} ({m['heads_blurred']} regions)", flush=True)
        if store is not None:
            register(cam, a.media, store)
            print(f"GOVREC-{cid}: registered ARCHIVAL_REPLAY", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
