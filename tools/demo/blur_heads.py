#!/usr/bin/env python3
"""Blur the head of every person the pipeline found, before footage is shown.

The own-feed recordings are licensed stock footage of real streets, and the
people in them did not agree to appear in a police demonstration. The user's
rule for this submission: faces are blurred in anything published.

This platform deliberately has no face detector — "no biometric
identification" is a design decision recorded in the HLD — so blurring is done
without one. The pipeline already draws a box round every person it tracks;
the top of that box is where the head is. That region is blurred, frame by
frame, using the boxes the production pipeline produced for that exact frame
(the sidecar written by analyse_own_feed.py). No face is ever located, and
nothing is added to the platform that could later be turned to identify one.

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


def blur(camera_id: str, *, crf: int = 16) -> dict:
    import av
    import cv2

    clip = MEDIA / f"{camera_id}.mp4"
    side = MEDIA / f"{camera_id}.tracks.json"
    source = MEDIA / f"{camera_id}.source.mp4"
    if not source.exists():
        if not clip.exists():
            raise SystemExit(f"no recording for {camera_id}")
        shutil.move(str(clip), str(source))
    if not side.exists():
        raise SystemExit(f"{camera_id} has not been analysed; run analyse_own_feed.py first")
    tracks = json.loads(side.read_text(encoding="utf-8"))
    import hashlib
    h = hashlib.sha256(source.read_bytes()).hexdigest()
    if tracks.get("sha256") != h:
        raise SystemExit("the sidecar was not computed over the source file; "
                         "refusing to blur from boxes that belong to other bytes")
    frames = tracks["frames"]

    with av.open(str(source)) as c:
        vs = c.streams.video[0]
        width, height = vs.codec_context.width, vs.codec_context.height
        fps = tracks.get("fps") or float(vs.average_rate)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
           "-r", f"{fps}", "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    blurred = 0
    with av.open(str(source)) as c:
        for i, vf in enumerate(c.decode(video=0)):
            img = vf.to_ndarray(format="bgr24")
            boxes = frames[i][1] if i < len(frames) else []
            for (x1, y1, x2, y2) in head_regions(boxes, width, height):
                roi = img[y1:y2, x1:x2]
                k = max(15, ((max(x2 - x1, y2 - y1) // 2) | 1))
                # Pixelate, then soften: unmistakably anonymised, not smeared.
                small = cv2.resize(roi, (max(1, (x2 - x1) // 10), max(1, (y2 - y1) // 10)),
                                   interpolation=cv2.INTER_LINEAR)
                roi = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
                img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
                blurred += 1
            enc.stdin.write(img.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("encoding the blurred file failed")
    # The sidecar describes the source's bytes; move it so it cannot be served
    # over the blurred copy (the server would refuse it anyway).
    side.rename(MEDIA / f"{camera_id}.source.tracks.json")
    return {"camera_id": camera_id, "heads_blurred": blurred,
            "frames": len(frames), "out": str(clip.relative_to(ROOT))}


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
