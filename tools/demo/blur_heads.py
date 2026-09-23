#!/usr/bin/env python3
"""Blur the head of every person the pipeline found, before footage is shown.

The own-feed recordings are licensed stock footage of real streets, and the
people in them did not agree to appear in a police demonstration. The user's
rule for this submission: faces are blurred in anything published.

This platform deliberately has no face detector — "no biometric
identification" is a design decision recorded in the HLD — so blurring is done
without one. The production pipeline's person detector puts a box round every
person it sees; the top of that box is where the head is. That region is
blurred, frame by frame. No face is ever located, and nothing is added to the
platform that could later be turned to identify one.

The first version blurred from the analysis sidecar, and checked by eye it
missed people in plain view: two men beside a parked car, a man by a tree. The
sidecar holds the *presentation* boxes, and presentation deliberately drops a
person whose box sits inside a vehicle's, treating them as a passenger. That
is right for a readable overlay and wrong for privacy. The second version ran
the detector through the pipeline and blurred from the raw tracker pool; by
eye it still missed small and half-hidden people, because the detector sees
the 2560 px frame shrunk to 640 px. This version runs the production detector
on the whole frame and again on overlapping tiles, at a lower confidence than
the overlay uses, and blurs each region for a few frames either side of the
one it was found on — because over-blurring costs nothing and a missed face is
the failure that matters.

    python tools/demo/blur_heads.py OWN-MUM-AUTOSTAND

keeps the untouched file as <CAMERA>.source.mp4 and writes the blurred one as
<CAMERA>.mp4. The sidecar belonged to the old bytes, so it is moved aside:
re-run analyse_own_feed.py on the blurred file, and the server's SHA-256 check
guarantees nothing computed over the original is ever drawn over the copy.

Limits, stated: a person the pipeline did not detect — usually small and
distant — is not blurred. At the distances in these clips such a figure is a
few pixels high and not identifiable, but the rule is "blur what we detect",
not "no face can appear", and the published films should be checked by eye.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
MEDIA = ROOT / "var" / "media"

#: Fraction of a person box, from the top, treated as the head. A standing
#: adult's head is roughly an eighth of their height; the margin covers a
#: turned head, a raised arm and loose tracker boxes.
HEAD_FRACTION = 0.24
#: Horizontal widening, as a fraction of box width on each side.
HEAD_WIDEN = 0.12


def head_regions(boxes: list, width: int, height: int) -> list[tuple[int, int, int, int]]:
    out = []
    for b in boxes:
        x1, y1, x2, y2, code = b[0], b[1], b[2], b[3], b[4]
        if code != "p":
            continue
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            continue
        hx1 = max(0, int(x1 - w * HEAD_WIDEN))
        hx2 = min(width, int(x2 + w * HEAD_WIDEN))
        hy1 = max(0, int(y1 - h * 0.03))
        hy2 = min(height, int(y1 + h * HEAD_FRACTION))
        if hx2 - hx1 >= 2 and hy2 - hy1 >= 2:
            out.append((hx1, hy1, hx2, hy2))
    return out


#: Tiles per axis for the second detection pass. The detector sees a 640 px
#: input; a 2560 px frame shrinks four times and a person 60 px tall becomes
#: 15 px, below what it finds reliably. Overlapping tiles double the scale.
TILES = (3, 2)
TILE_OVERLAP = 0.14
#: A region is blurred on this many frames either side of the one it was
#: detected on, so a detection that flickers out for a frame stays covered.
TEMPORAL_PAD = 3


def _tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    nx, ny = TILES
    tw, th = width / nx, height / ny
    ox, oy = tw * TILE_OVERLAP, th * TILE_OVERLAP
    out = []
    for j in range(ny):
        for i in range(nx):
            x1, y1 = max(0, int(i * tw - ox)), max(0, int(j * th - oy))
            x2, y2 = min(width, int((i + 1) * tw + ox)), min(height, int((j + 1) * th + oy))
            out.append((x1, y1, x2, y2))
    return out


def _detector():
    """The production vehicle/person detector, from the registry, as deployed."""
    from saakshya.analytics.pipeline import PipelineConfig
    from saakshya.models.registry import get
    from saakshya.runtime.backend import BACKENDS

    rec = get(PipelineConfig().vehicle_detector_key)
    if rec is None:
        raise SystemExit("the vehicle detector is not in the model registry")
    return BACKENDS.get(rec)


def detect_people(img, backend, person_conf: float) -> list[list]:
    """Every person box on the whole frame and on each tile, in frame pixels."""
    h, w = img.shape[:2]
    boxes = []
    for (tx1, ty1, tx2, ty2) in [(0, 0, w, h), *_tiles(w, h)]:
        for d in backend.detect(img[ty1:ty2, tx1:tx2]):
            if (d.label or "").lower() == "person" and d.score >= person_conf:
                x1, y1, x2, y2 = d.box
                boxes.append([x1 + tx1, y1 + ty1, x2 + tx1, y2 + ty1, "p"])
    return boxes


def blur(camera_id: str, *, crf: int = 16, person_conf: float = 0.25) -> dict:
    import av
    import cv2

    clip = MEDIA / f"{camera_id}.mp4"
    side = MEDIA / f"{camera_id}.tracks.json"
    source = MEDIA / f"{camera_id}.source.mp4"
    if not source.exists():
        if not clip.exists():
            raise SystemExit(f"no recording for {camera_id}")
        shutil.move(str(clip), str(source))

    with av.open(str(source)) as c:
        vs = c.streams.video[0]
        width, height = vs.codec_context.width, vs.codec_context.height
        fps = float(vs.average_rate) if vs.average_rate else 30.0

    # Pass 1: find every head. Regions only are kept, not frames.
    backend = _detector()
    regions: list[list[tuple[int, int, int, int]]] = []
    with av.open(str(source)) as c:
        for i, vf in enumerate(c.decode(video=0)):
            img = vf.to_ndarray(format="bgr24")
            regions.append(head_regions(detect_people(img, backend, person_conf),
                                        width, height))
            if i and i % 50 == 0:
                print(f"  {camera_id}: {i} frames searched for people", flush=True)

    # Pass 2: blur the union of each frame's neighbours' regions and encode.
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
           "-r", f"{fps}", "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    blurred = frames = 0
    n = len(regions)
    with av.open(str(source)) as c:
        for i, vf in enumerate(c.decode(video=0)):
            img = vf.to_ndarray(format="bgr24")
            todo = {r for k in range(max(0, i - TEMPORAL_PAD), min(n, i + TEMPORAL_PAD + 1))
                    for r in regions[k]}
            for (x1, y1, x2, y2) in todo:
                roi = img[y1:y2, x1:x2]
                k = max(15, ((max(x2 - x1, y2 - y1) // 2) | 1))
                # Pixelate, then soften: unmistakably anonymised, not smeared.
                small = cv2.resize(roi, (max(1, (x2 - x1) // 10), max(1, (y2 - y1) // 10)),
                                   interpolation=cv2.INTER_LINEAR)
                roi = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
                img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
            blurred += len(regions[i]) if i < n else 0
            enc.stdin.write(img.tobytes())
            frames += 1
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("encoding the blurred file failed")
    if frames and not blurred:
        # A footage clip of a street with nobody detected is possible; a blur
        # pass that silently did nothing is the failure this guards against.
        clip.unlink(missing_ok=True)
        raise SystemExit(f"{camera_id}: no person detected in {frames} frames - "
                         "refusing to publish an unblurred copy; check the detector")
    # Any sidecar describes other bytes now; move it so it cannot be served over
    # the blurred copy (the server would refuse it on SHA-256 anyway).
    if side.exists():
        side.rename(MEDIA / f"{camera_id}.source.tracks.json")
    return {"camera_id": camera_id, "heads_blurred": blurred,
            "frames": frames, "out": str(clip.relative_to(ROOT))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cameras", nargs="+")
    a = ap.parse_args()
    for cid in a.cameras:
        r = blur(cid)
        print(f"{cid}: blurred {r['heads_blurred']} head regions over "
              f"{r['frames']} frames -> {r['out']}. Re-run analyse_own_feed.py {cid}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
