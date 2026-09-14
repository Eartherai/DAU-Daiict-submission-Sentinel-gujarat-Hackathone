"""Render the government-feed demonstration video, with the detections drawn on.

The submission asks for a demonstration on the organiser's feed accompanied by
"an output report showing detected vehicles or number plates with corresponding
timestamps". A report on its own asks the reader to take the numbers on trust.
This renders the same detections onto the frames they came from, so the report
and the video are two views of one run rather than two claims that happen to
agree.

Nothing here is staged. Frames are decoded live from the catalogue's cameras,
run through the same `CameraPipeline` the platform uses, and drawn with the
boxes the tracker actually held at that frame. There is no replay path and no
saved-detection path: if the video shows a box, the detector produced it during
this run.

What is drawn is deliberately limited to what was measured:

  * a **confirmed** track is solid — the tracker has seen it enough times to
    stand behind it;
  * a **tentative** track is dashed and labelled as such, because a detection
    the tracker has not yet confirmed is not evidence of anything;
  * a registration mark appears only where ANPR actually read one, and carries
    its confidence. On most of this estate plate width is well under the
    readable threshold, so most cameras will show vehicles and no marks. That
    is the honest picture of the estate, and hiding it would misrepresent what
    the platform can do at these mountings.

Timestamps are the **normalised** timeline (PTS-derived), not wall clock at the
moment of drawing, because that is the timeline every cross-camera claim in
this platform is made on.

    python tools/demo/render_demo_video.py --db sqlite:///var/live.db \
        --seconds 25 --cameras 6 --out var/demo/government_feed

Credentials never reach the frame, the log, or the console: stream URLs are
redacted at every exit from this module.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
from saakshya.common.paths import display
from saakshya.ingest.frame import Frame
from saakshya.ingest.stream import StreamConfig, StreamManager
from saakshya.live.timebase import TimebaseRegistry
from saakshya.store import Store

# ── presentation ─────────────────────────────────────────────────────────────
# The same palette as the interface, for the same reason: an officer who has
# seen the console should recognise the video as the same system.
NAVY = (12, 33, 55)
NAVY_2 = (18, 44, 71)
SEAL = (200, 145, 47)
INK = (238, 242, 247)
INK_2 = (157, 178, 201)
CONFIRMED = (45, 212, 191)
TENTATIVE = (245, 196, 92)
PLATE = (255, 255, 255)

# Output is always 1080p. Camera pixels are letterboxed (never stretched) so
# plate width stays honest. Playback is 30 fps, with each source frame held
# for its real PTS interval — that is cinema pacing, not a detector slideshow.
# Encode is ffmpeg libx264, not PyAV's thin wrapper: CRF 12 / slow / high
# profile, typically 10–18 Mbps. The previous PyAV path sat around 2 Mbps and
# looked like a compressed GIF on a projector.
W, H = 1920, 1080
FPS = 30
BAND_TOP, BAND_BOTTOM = 96, 78
CRF = "8"
PRESET = "slow"

#: Waiting for a stream to open is a different wait from waiting for its next
#: frame, and conflating them refuses cameras that are merely still connecting.
OPEN_TIMEOUT_S = 30.0
FRAME_TIMEOUT_S = 6.0

#: Credentials appear in RTSP URLs. Everything that leaves this module goes
#: through here first — a redaction applied at one exit and not another is the
#: same as no redaction at all.
_CRED = re.compile(r"//[^/@\s]*:[^/@\s]*@")


def redact(url: str) -> str:
    """A stream URL with any embedded credential removed."""
    return _CRED.sub("//<redacted>@", url)


def _font(names: tuple[str, ...], size: int) -> Any:
    for n in names:
        for base in ("/System/Library/Fonts/Supplemental/",
                     "/System/Library/Fonts/", "/Library/Fonts/"):
            p = Path(base) / n
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    continue
    return ImageFont.load_default()


SANS = lambda s: _font(("Arial.ttf", "Helvetica.ttc", "SFNSDisplay.ttf"), s)      # noqa: E731
SANS_B = lambda s: _font(("Arial Bold.ttf", "Helvetica.ttc"), s)                  # noqa: E731
MONO = lambda s: _font(("Courier New.ttf", "Menlo.ttc", "SFNSMono.ttf"), s)       # noqa: E731


@dataclass
class Row:
    """One drawn detection, written to the log so video and report agree."""

    t_norm: str
    camera_id: str
    camera_name: str
    district: str
    department: str
    track_id: str
    object_type: str
    confirmed: bool
    score: float
    box: tuple[int, int, int, int]
    plate: str | None = None
    plate_confidence: float | None = None


@dataclass
class CameraRun:
    camera_id: str
    name: str
    district: str
    department: str
    codec: str = ""
    frames: int = 0
    tracks: set[str] = field(default_factory=set)
    plates: set[str] = field(default_factory=set)
    opened: bool = False
    note: str = ""
    #: The camera's measured time cluster, and how it was established. Printed
    #: on the frame because this estate's cameras carry burnt-in clocks that
    #: disagree with wall time by months — without the cluster on screen, that
    #: disagreement reads as a fault in this platform rather than a measured
    #: property of the grid.
    cluster: str = ""
    cluster_basis: str = "UNKNOWN"
    #: What this footage actually is, printed on every frame. The government
    #: banner was briefly drawn over the synthetic corpus because the label was
    #: hard-coded in the frame composer rather than carried by the run. A video
    #: that misstates its own provenance discredits every true thing beside it,
    #: so the label now travels with the footage and has no default.
    provenance: str = "PROVENANCE NOT STATED"

    #: Frames drawn per second of stream time — the rate detection actually
    #: achieved on this host, not a configured target.
    analysis_fps: float = 0.0
    span_s: float = 0.0


def _text(d: ImageDraw.ImageDraw, xy: tuple[int, int], s: str, font: Any,
          fill: tuple[int, int, int], spacing: float = 0.0) -> int:
    """Draw text, optionally letter-spaced. Returns the advance in pixels."""
    if not spacing:
        d.text(xy, s, font=font, fill=fill)
        return int(d.textlength(s, font=font))
    x0, y = float(xy[0]), xy[1]
    x = x0
    for ch in s:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return int(x - x0)


def _dashed(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
            colour: tuple[int, int, int], dash: int = 9, w: int = 2) -> None:
    x1, y1, x2, y2 = box
    for x in range(x1, x2, dash * 2):
        d.line([(x, y1), (min(x + dash, x2), y1)], fill=colour, width=w)
        d.line([(x, y2), (min(x + dash, x2), y2)], fill=colour, width=w)
    for y in range(y1, y2, dash * 2):
        d.line([(x1, y), (x1, min(y + dash, y2))], fill=colour, width=w)
        d.line([(x2, y), (x2, min(y + dash, y2))], fill=colour, width=w)


def _chip(d: ImageDraw.ImageDraw, xy: tuple[int, int], s: str, font: Any,
          fg: tuple[int, int, int], bg: tuple[int, int, int]) -> None:
    x, y = xy
    w = int(d.textlength(s, font=font))
    d.rectangle([x, y, x + w + 16, y + 26], fill=bg)
    d.text((x + 8, y + 4), s, font=font, fill=fg)


def ffmpeg_bin() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


class FfmpegWriter:
    """Stream RGB frames to ffmpeg. Holds at most one frame in the pipe."""

    def __init__(self, path: Path, w: int = W, h: int = H, fps: int = FPS):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.w, self.h, self.fps = path, w, h, fps
        self.n = 0
        self.proc = subprocess.Popen(
            [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
             "-an", "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
             "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
             "-x264-params",
             "ref=5:bframes=3:me=umh:subme=9:trellis=2:aq-mode=3:aq-strength=0.8",
             "-movflags", "+faststart", str(path)],
            stdin=subprocess.PIPE)
        if self.proc.stdin is None:
            raise RuntimeError("ffmpeg stdin missing")

    def write(self, im: Image.Image, times: int = 1) -> None:
        if im.mode != "RGB":
            im = im.convert("RGB")
        if im.size != (self.w, self.h):
            im = im.resize((self.w, self.h), Image.Resampling.LANCZOS)
        buf = im.tobytes()
        assert self.proc.stdin is not None
        for _ in range(max(1, times)):
            self.proc.stdin.write(buf)
            self.n += 1

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg encode failed ({rc}): {self.path}")


class RealtimePacer:
    """Hold each composed frame for the stream time it actually covers."""

    def __init__(self, writer: FfmpegWriter):
        self.writer = writer
        self.prev: Image.Image | None = None
        self.prev_pts: float | None = None

    def emit(self, img: Image.Image, pts: float) -> None:
        if self.prev is not None and self.prev_pts is not None:
            n = round((pts - self.prev_pts) * self.writer.fps)
            n = max(1, min(n, self.writer.fps * 3))
            self.writer.write(self.prev, n)
        self.prev, self.prev_pts = img, pts

    def flush(self, hold_s: float = 0.5) -> None:
        if self.prev is not None:
            self.writer.write(self.prev, max(1, round(hold_s * self.writer.fps)))
            self.prev = None


def hold_card(writer: FfmpegWriter, img: Image.Image, seconds: float) -> None:
    writer.write(img, max(1, round(seconds * writer.fps)))


def compose(image: np.ndarray, run: CameraRun, t_norm: datetime, pts_s: float,
            drawn: list[Row], totals: dict[str, int]) -> Image.Image:
    """One finished frame: the camera's picture, the boxes, and the chrome.

    The picture is letterboxed rather than stretched. A demonstration that
    changes a camera's aspect ratio changes the apparent width of every plate
    in it, and plate width is the measurement this platform grades cameras on.
    """
    src = Image.fromarray(image[:, :, ::-1])  # BGR24 → RGB
    inner_h = H - BAND_TOP - BAND_BOTTOM
    scale = min(W / src.width, inner_h / src.height)
    vw, vh = int(src.width * scale), int(src.height * scale)
    ox, oy = (W - vw) // 2, BAND_TOP + (inner_h - vh) // 2

    canvas = Image.new("RGB", (W, H), NAVY)
    pane = src.resize((vw, vh), Image.Resampling.LANCZOS)
    pane = pane.filter(ImageFilter.UnsharpMask(radius=1.4, percent=90, threshold=2))
    canvas.paste(pane, (ox, oy))
    d = ImageDraw.Draw(canvas)

    # ── detections, in source coordinates mapped onto the letterbox ─────────
    f_lab, f_mono = SANS_B(18), MONO(20)
    for r in drawn:
        x1, y1, x2, y2 = (int(v * scale) for v in r.box)
        bx = (ox + x1, oy + y1, ox + x2, oy + y2)
        colour = CONFIRMED if r.confirmed else TENTATIVE
        if r.confirmed:
            d.rectangle([bx[0] - 1, bx[1] - 1, bx[2] + 1, bx[3] + 1],
                        outline=(0, 0, 0), width=5)
            d.rectangle(bx, outline=colour, width=3)
        else:
            _dashed(d, bx, colour, dash=12, w=3)

        label = f"{r.object_type} {r.score:.2f}"
        if not r.confirmed:
            label += "  tentative"
        ly = max(oy, bx[1] - 28)
        _chip(d, (bx[0], ly), label, f_lab, NAVY, colour)

        # A registration mark is drawn only where one was actually read, and it
        # carries the confidence it was read at.
        if r.plate:
            _chip(d, (bx[0], min(bx[3] + 4, oy + vh - 30)),
                  f"{r.plate}  {r.plate_confidence:.2f}", f_mono, NAVY, PLATE)

    # ── top band: whose system, which camera ───────────────────────────────
    d.rectangle([0, 0, W, BAND_TOP], fill=NAVY)
    d.line([(0, BAND_TOP - 1), (W, BAND_TOP - 1)], fill=(30, 65, 102), width=1)
    d.ellipse([24, 24, 72, 72], outline=SEAL, width=3)
    _text(d, (88, 22), "SAAKSHYA", SANS_B(24), INK, spacing=2.8)
    _text(d, (88, 56), "GUJARAT POLICE · CCTV INTELLIGENCE & EVIDENCE",
          SANS(13), INK_2, spacing=1.2)

    name = f"{run.camera_id} · {run.name}"
    nw = int(d.textlength(name, font=SANS_B(22)))
    d.text((W - nw - 28, 22), name, font=SANS_B(22), fill=INK)
    place = f"{run.district} · {run.department} · {run.codec}"
    pw = int(d.textlength(place, font=SANS(16)))
    d.text((W - pw - 28, 56), place, font=SANS(16), fill=INK_2)

    # ── bottom band: the timeline every claim is made on ───────────────────
    y0 = H - BAND_BOTTOM
    d.rectangle([0, y0, W, H], fill=NAVY_2)
    d.line([(0, y0), (W, y0)], fill=(30, 65, 102), width=1)
    _text(d, (28, y0 + 12), "NORMALISED TIME (UTC)", SANS_B(11), INK_2, spacing=1.2)
    d.text((28, y0 + 36), t_norm.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
           font=MONO(22), fill=INK)

    _text(d, (420, y0 + 12), "STREAM PTS", SANS_B(11), INK_2, spacing=1.2)
    d.text((420, y0 + 36), f"{pts_s:9.3f} s", font=MONO(22), fill=INK)

    _text(d, (640, y0 + 12), "DRAWN THIS FRAME", SANS_B(11), INK_2, spacing=1.2)
    conf = sum(1 for r in drawn if r.confirmed)
    d.text((640, y0 + 36), f"{conf} confirmed · {len(drawn) - conf} tentative",
           font=MONO(22), fill=INK)

    _text(d, (1040, y0 + 12), "RUN TOTAL", SANS_B(11), INK_2, spacing=1.2)
    d.text((1040, y0 + 36),
           f"{totals['tracks']} vehicles · {totals['plates']} marks read",
           font=MONO(22), fill=INK)

    # The camera's own burnt-in clock is visible in the picture and will not
    # agree with the line on the left. Naming the cluster it was measured into
    # is what turns that from an apparent fault into the finding it is.
    _text(d, (1480, y0 + 12), "TIME CLUSTER", SANS_B(11), INK_2, spacing=1.2)
    d.text((1480, y0 + 36), f"{run.cluster or 'none'} · {run.cluster_basis}",
           font=MONO(18), fill=SEAL if run.cluster else INK_2)

    _text(d, (28, 6), "OFFICIAL · SENSITIVE", SANS_B(11), SEAL, spacing=1.4)
    lw = int(d.textlength(run.provenance, font=SANS(13)))
    _text(d, (W - lw - 28, 6), run.provenance, SANS(13), INK_2)
    return canvas


def card(lines: list[tuple[str, str]], title: str, sub: str = "") -> Image.Image:
    """A title card. Plain, because its job is to be read, not admired."""
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.ellipse([120, 110, 190, 180], outline=SEAL, width=3)
    _text(d, (214, 118), "SAAKSHYA", SANS_B(36), INK, spacing=4.0)
    _text(d, (214, 166), "GUJARAT POLICE · CCTV INTELLIGENCE & EVIDENCE",
          SANS(16), INK_2, spacing=1.4)
    d.line([(120, 236), (W - 120, 236)], fill=SEAL, width=3)

    d.text((120, 278), title, font=SANS_B(44), fill=INK)
    if sub:
        d.text((120, 342), sub, font=SANS(22), fill=INK_2)

    y = 430
    for k, v in lines:
        if not k and not v:
            y += 20
            continue
        _text(d, (120, y + 4), k, SANS_B(14), SEAL, spacing=1.4)
        for i, seg in enumerate(v.split("\n")):
            d.text((480, y + i * 30), seg, font=SANS(20), fill=INK)
        y += 30 * max(1, len(v.split("\n"))) + 18
    return img


def pace(shots: list[tuple[Image.Image, float]]) -> list[Image.Image]:
    """Repeat frames so the video runs at the camera's real pace."""
    if not shots:
        return []
    out: list[Image.Image] = []
    for i, (img, pts) in enumerate(shots):
        nxt = shots[i + 1][1] if i + 1 < len(shots) else pts + 1.0 / FPS
        out.extend([img] * max(1, min(round((nxt - pts) * FPS), FPS * 3)))
    return out


def encode(frames: list[Image.Image], out: Path, fps: int = FPS) -> None:
    """Mux to H.264 via ffmpeg so walkthroughs and overlays share one encoder."""
    if not frames:
        raise ValueError("no frames to encode")
    w, h = frames[0].size
    wr = FfmpegWriter(out, w, h, fps)
    try:
        for im in frames:
            wr.write(im)
    finally:
        wr.close()


def run_camera(mgr: StreamManager, cam: dict[str, Any], seconds: float,
               rows: list[Row], timebase: TimebaseRegistry | None = None,
               pacer: RealtimePacer | None = None
               ) -> tuple[list[tuple[Image.Image, float]], CameraRun]:
    """Decode one camera for `seconds`, detecting and drawing as we go."""
    cid = cam["camera_id"]
    run = CameraRun(cid, cam.get("name") or cid, cam.get("district") or "—",
                    cam.get("department") or "—", cam.get("codec") or "")
    run.provenance = "LIVE GOVERNMENT FEED · NOT A REPLAY"
    tb = timebase.get(cid) if timebase else None
    if tb is not None:
        run.cluster = tb.time_cluster or ""
        run.cluster_basis = tb.cluster_confidence

    pipe = CameraPipeline(cid, PipelineConfig(), district=run.district)
    worker = mgr.add(cid, cam["rtsp_url"])
    q = worker.subscribe("demo")
    # Composed frames with the stream time they represent, so the encode can
    # pace them in real time rather than assuming a fixed analysis rate.
    out: list[tuple[Image.Image, float]] = []
    totals = {"tracks": 0, "plates": 0}

    # Plate reads arrive on track close, so a mark read for a vehicle is
    # attached to every frame that vehicle appeared in — otherwise the mark
    # would flash for one frame at the end and be unreadable at output fps.
    plate_of: dict[str, tuple[str, float]] = {}
    deadline = time.time() + seconds
    first = True

    first_pts: float | None = None
    last_pts: float | None = None
    while time.time() < deadline:
        # Opening a stream on this estate was measured at 1.3-10.4 s, so the
        # wait for the *first* frame is nothing like the wait for the next one.
        # A single short timeout for both refused three of five cameras that
        # were working: they simply had not finished connecting.
        try:
            frame = q.get(timeout=OPEN_TIMEOUT_S if first else FRAME_TIMEOUT_S)
        except Exception:
            break
        first = False
        if frame is None:
            break
        run.opened = True
        if frame.warmup:
            continue

        closed = pipe.process(frame)
        for ob in closed:
            if ob.plate and ob.track_id:
                plate_of[ob.track_id] = (ob.plate, ob.plate_confidence or 0.0)
                run.plates.add(ob.plate)

        run.frames += 1
        if first_pts is None:
            first_pts = frame.pts_s
        last_pts = frame.pts_s
        run.codec = run.codec or frame.codec

        tracker = pipe.tracks.get(cid, frame.segment_id)
        drawn: list[Row] = []
        for t in tracker.tracks.values():
            run.tracks.add(t.track_id)
            p = plate_of.get(t.track_id)
            box = tuple(int(v) for v in t.box)
            r = Row(t_norm=frame.t_norm.isoformat(), camera_id=cid,
                    camera_name=run.name, district=run.district,
                    department=run.department, track_id=t.track_id,
                    object_type=t.label, confirmed=bool(t.confirmed),
                    score=float(t.score), box=box,  # type: ignore[arg-type]
                    plate=p[0] if p else None,
                    plate_confidence=p[1] if p else None)
            drawn.append(r)
            rows.append(r)

        totals["tracks"], totals["plates"] = len(run.tracks), len(run.plates)
        img = compose(frame.image, run, frame.t_norm, frame.pts_s, drawn, totals)
        if pacer is not None:
            pacer.emit(img, frame.pts_s)
        else:
            out.append((img, frame.pts_s))

    if first_pts is not None and last_pts is not None and last_pts > first_pts:
        run.span_s = last_pts - first_pts
        run.analysis_fps = run.frames / run.span_s

    worker.unsubscribe("demo")
    # Anything still open at the end is closed so its plate votes are counted.
    for ob in pipe.flush():
        if ob.plate:
            run.plates.add(ob.plate)
    if not run.opened:
        run.note = "stream did not open within the window"
    return out, run


def run_file(path: Path, cam: dict[str, Any], seconds: float,
             rows: list[Row], pacer: RealtimePacer | None = None
             ) -> tuple[list[tuple[Image.Image, float]], CameraRun]:
    """Decode a local recording, detecting and drawing as we go.

    A recording is not a stream and must not be pushed through the stream
    worker. That worker flags frames as *warmup* while a connection replays its
    buffer faster than real time — which is a correct thing to do for a camera
    and exactly wrong for a file, because a file is always faster than real
    time. Every frame would be flagged, and the run would draw nothing.

    Recording time is the file's own PTS offset from its modification time,
    which is stated on screen rather than presented as a capture clock: this is
    our own footage, and the honest label for it is a recording, not a feed.
    """
    cid = cam["camera_id"]
    run = CameraRun(cid, cam.get("name") or cid, cam.get("district") or "—",
                    cam.get("department") or "—")
    run.cluster, run.cluster_basis = "local corpus", "LOCAL"
    run.provenance = "LOCAL SYNTHETIC CORPUS · NOT GOVERNMENT DATA"
    pipe = CameraPipeline(cid, PipelineConfig(), district=run.district)
    out: list[tuple[Image.Image, float]] = []
    totals = {"tracks": 0, "plates": 0}
    plate_of: dict[str, tuple[str, float]] = {}
    epoch = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    segment = f"SG-{path.stem}"

    first_pts = last_pts = None
    with av.open(str(path)) as container:
        vs = container.streams.video[0]
        run.codec = vs.codec_context.name
        for i, vf in enumerate(container.decode(video=0)):
            tb = vs.time_base
            pts = (float(vf.pts * tb) if vf.pts is not None and tb is not None
                   else i / FPS)
            if pts > seconds:
                break
            frame = Frame(camera_id=cid, segment_id=segment, pts_s=pts,
                          t_norm=epoch + timedelta(seconds=pts),
                          t_ingest=datetime.now(UTC),
                          image=vf.to_ndarray(format="bgr24"),
                          width=vf.width, height=vf.height,
                          codec=run.codec, frame_index=i)
            run.opened = True
            for ob in pipe.process(frame):
                if ob.plate and ob.track_id:
                    plate_of[ob.track_id] = (ob.plate, ob.plate_confidence or 0.0)
                    run.plates.add(ob.plate)

            run.frames += 1
            if first_pts is None:
                first_pts = pts
            last_pts = pts

            tracker = pipe.tracks.get(cid, segment)
            drawn: list[Row] = []
            for t in tracker.tracks.values():
                run.tracks.add(t.track_id)
                pl = plate_of.get(t.track_id)
                r = Row(t_norm=frame.t_norm.isoformat(), camera_id=cid,
                        camera_name=run.name, district=run.district,
                        department=run.department, track_id=t.track_id,
                        object_type=t.label, confirmed=bool(t.confirmed),
                        score=float(t.score),
                        box=tuple(int(v) for v in t.box),  # type: ignore[arg-type]
                        plate=pl[0] if pl else None,
                        plate_confidence=pl[1] if pl else None)
                drawn.append(r)
                rows.append(r)

            totals["tracks"], totals["plates"] = len(run.tracks), len(run.plates)
            img = compose(frame.image, run, frame.t_norm, pts, drawn, totals)
            if pacer is not None:
                pacer.emit(img, pts)
            else:
                out.append((img, pts))

    for ob in pipe.flush():
        if ob.plate:
            run.plates.add(ob.plate)
    if first_pts is not None and last_pts is not None and last_pts > first_pts:
        run.span_s = last_pts - first_pts
        run.analysis_fps = run.frames / run.span_s
    return out, run


def write_report(out: Path, rows: list[Row], runs: list[CameraRun],
                 started: datetime, source: str, seconds: float,
                 n_frames: int) -> None:
    """The output report, written from the rows that were actually drawn.

    Both files come from one list. A report generated separately from the video
    could disagree with it and nobody would know which was right; generated from
    the same rows, they cannot.
    """
    with out.with_suffix(".csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp_utc_normalised", "camera_id", "camera_name",
                    "district", "department", "track_id", "object_type",
                    "track_state", "detection_confidence", "bbox_x1", "bbox_y1",
                    "bbox_x2", "bbox_y2", "registration_mark", "mark_confidence"])
        for r in rows:
            w.writerow([r.t_norm, r.camera_id, r.camera_name, r.district,
                        r.department, r.track_id, r.object_type,
                        "CONFIRMED" if r.confirmed else "TENTATIVE",
                        f"{r.score:.3f}", *r.box, r.plate or "",
                        f"{r.plate_confidence:.3f}"
                        if r.plate_confidence is not None else ""])

    rated = [r.analysis_fps for r in runs if r.analysis_fps > 0]
    plates = sorted({p for r in runs for p in r.plates})
    out.with_suffix(".json").write_text(json.dumps({
        "generated_at": started.isoformat(),
        "source": source,
        "seconds_per_camera": seconds,
        "video_fps": FPS,
        "video_width": W,
        "video_height": H,
        "video_crf": int(CRF),
        "video_encoder": "ffmpeg-libx264",
        "cameras": [{"camera_id": r.camera_id, "name": r.name,
                     "district": r.district, "department": r.department,
                     "opened": r.opened, "frames_drawn": r.frames,
                     "vehicles_tracked": len(r.tracks),
                     "marks_read": sorted(r.plates), "note": r.note,
                     "time_cluster": r.cluster or None,
                     "cluster_basis": r.cluster_basis,
                     "analysis_fps": round(r.analysis_fps, 2),
                     "stream_span_s": round(r.span_s, 1)} for r in runs],
        "totals": {
            "cameras_opened": sum(1 for r in runs if r.opened),
            "vehicles": sum(len(r.tracks) for r in runs),
            "mean_analysis_fps": round(sum(rated) / len(rated), 2) if rated else 0.0,
            "distinct_marks": len(plates), "rows": len(rows),
            "video_seconds": round(n_frames / FPS, 1)},
    }, indent=2) + "\n")

    print(f"\nvideo  : {display(out.with_suffix('.mp4'))} "
          f"({n_frames / FPS:.0f}s, {n_frames} frames)")
    print(f"report : {display(out.with_suffix('.csv'))} ({len(rows)} rows)")
    print(f"summary: {display(out.with_suffix('.json'))}")


def render_own(media: Path, out: Path, seconds: float, limit: int) -> int:
    """The own-feed demonstration: the same platform, on the local corpus.

    This footage is generated, not filmed. That is stated on the opening card,
    on every frame, and in the report, because a demonstration that lets a
    viewer believe synthetic frames are government video has misled them about
    the one thing they most need to judge.
    """
    cat = json.loads((media / "catalogue.json").read_text())["cameras"][:limit]
    started = datetime.now(UTC)
    print(f"rendering own recordings from {display(media)} → {display(out)}.mp4")

    rows: list[Row] = []
    runs: list[CameraRun] = []
    writer = FfmpegWriter(out.with_suffix(".mp4"))
    try:
        hold_card(writer, card(
            [("FOOTAGE", "The local synthetic corpus. Generated, not filmed,\n"
                          "and not government material — every frame is\n"
                          "labelled so on screen."),
             ("WHY SYNTHETIC", "Its registration marks are known in advance, so a\n"
                               "read can be scored right or wrong. On real\n"
                               "footage nobody can say what the correct answer\n"
                               "was, only that a plate looks plausible."),
             ("PLATFORM", "The same detector, tracker and ANPR the government\n"
                          "grid runs. There is no demonstration path in this\n"
                          "code and no per-camera special case."),
             ("", ""),
             ("SOLID BOX", "track confirmed by the tracker"),
             ("DASHED BOX", "tentative — detected, not yet confirmed"),
             ("WHITE CHIP", "registration mark read, with its confidence")],
            "Own-feed demonstration",
            "Local synthetic corpus, processed by the platform end to end."),
                 5.0)

        for c in cat:
            path = media / f"{c['id']}.mp4"
            if not path.exists():
                continue
            cam = {"camera_id": c["id"], "name": c.get("name"),
                   "district": c.get("district"), "department": c.get("department")}
            print(f"  {c['id']:<8} {(c.get('name') or '')[:38]:<40} ", end="",
                  flush=True)
            t0 = time.time()
            pacer = RealtimePacer(writer)
            _got, run = run_file(path, cam, seconds, rows, pacer)
            pacer.flush()
            runs.append(run)
            print(f"{run.frames:4d} frames  {len(run.tracks):3d} vehicles  "
                  f"{len(run.plates):2d} marks  {run.analysis_fps:4.1f} fps  "
                  f"{time.time() - t0:5.1f}s")

        tracks = sum(len(r.tracks) for r in runs)
        plates = sorted({p for r in runs for p in r.plates})
        hold_card(writer, card(
            [("CLIPS", f"{len(runs)} processed from the local corpus"),
             ("VEHICLES", f"{tracks} tracked"),
             ("MARKS READ", f"{len(plates)} distinct"
                            + (f" — {', '.join(plates[:8])}" if plates else "")),
             ("", ""),
             ("REPORT", f"{display(out)}.csv — every detection, with timestamps")],
            "What this run measured",
            started.strftime("Run started %Y-%m-%d %H:%M:%SZ")), 6.0)
    finally:
        writer.close()

    write_report(out, rows, runs, started,
                 "LOCAL SYNTHETIC CORPUS (var/media) — not government data",
                 seconds, writer.n)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="sqlite:///var/live.db")
    ap.add_argument("--out", default="var/demo/government_feed")
    ap.add_argument("--seconds", type=float, default=20.0,
                    help="decode window per camera")
    ap.add_argument("--cameras", type=int, default=6)
    ap.add_argument("--camera", action="append", default=[],
                    help="specific camera id; repeatable")
    ap.add_argument("--media", metavar="DIR",
                    help="render our own recordings from DIR (with its "
                         "catalogue.json) instead of the live grid")
    a = ap.parse_args()

    if a.media:
        return render_own(Path(a.media), Path(a.out), a.seconds, a.cameras)

    store = Store(a.db)
    # Migrate before reading. This tool only reads, but a read against an older
    # schema fails on a missing column just as surely as a write does.
    store.create_all()
    catalogue = [c for c in store.list_cameras() if c.get("rtsp_url")]
    if a.camera:
        want = set(a.camera)
        catalogue = [c for c in catalogue if c["camera_id"] in want]
    else:
        catalogue = catalogue[:a.cameras]
    if not catalogue:
        print("no cameras with a stream URL in this store", file=sys.stderr)
        return 2

    out = Path(a.out)
    started = datetime.now(UTC)
    print(f"rendering from {len(catalogue)} camera(s), "
          f"{a.seconds:.0f}s each → {display(out)}.mp4")

    mgr = StreamManager(StreamConfig())
    timebase = TimebaseRegistry(store)
    rows: list[Row] = []
    runs: list[CameraRun] = []
    writer = FfmpegWriter(out.with_suffix(".mp4"))
    try:
        hold_card(writer, card(
            [("FEED", "Live government CCTV, decoded during this run"),
             ("DETECTION", "RT-DETRv2 vehicle detection, ByteTrack association,\n"
                           "ANPR where plate width supports a read"),
             ("TIMELINE", "PTS-derived normalised time, not wall clock"),
             ("CAMERA CLOCKS", "Several cameras on this estate carry a burnt-in\n"
                               "clock that disagrees with wall time by months.\n"
                               "The platform measures that rather than trusting\n"
                               "it, and names the time cluster each camera was\n"
                               "measured into. Only cameras in one cluster may\n"
                               "be compared to each other."),
             ("", ""),
             ("SOLID BOX", "track confirmed by the tracker"),
             ("DASHED BOX", "tentative — detected, not yet confirmed"),
             ("WHITE CHIP", "registration mark read, with its confidence")],
            "Government feed demonstration",
            "Every box in this video was produced by the detector during "
            "this run. Nothing is replayed."), 5.0)

        for cam in catalogue:
            print(f"  {cam['camera_id']:<8} {cam.get('name','')[:38]:<40} ",
                  end="", flush=True)
            t0 = time.time()
            pacer = RealtimePacer(writer)
            try:
                _got, run = run_camera(mgr, cam, a.seconds, rows, timebase, pacer)
            except Exception as exc:
                print(f"failed: {type(exc).__name__}")
                runs.append(CameraRun(cam["camera_id"], cam.get("name") or "",
                                      "—", "—",
                                      note=f"failed: {type(exc).__name__}"))
                continue
            pacer.flush()
            runs.append(run)
            print(f"{run.frames:4d} frames  {len(run.tracks):3d} vehicles  "
                  f"{len(run.plates):2d} marks  {run.analysis_fps:4.1f} fps  "
                  f"{time.time() - t0:5.1f}s"
                  + (f"  [{run.note}]" if run.note else ""))

        mgr.reconcile({})

        tracks = sum(len(r.tracks) for r in runs)
        rated = [r.analysis_fps for r in runs if r.analysis_fps > 0]
        rate = sum(rated) / len(rated) if rated else 0.0
        plates = sorted({p for r in runs for p in r.plates})
        opened = [r for r in runs if r.opened]
        hold_card(writer, card(
            [("CAMERAS", f"{len(opened)} of {len(runs)} opened and decoded"),
             ("VEHICLES", f"{tracks} tracked across those cameras"),
             ("MARKS READ", f"{len(plates)} distinct"
                            + (f" — {', '.join(plates[:6])}" if plates else "")),
             ("", ""),
             ("WHY SO FEW MARKS", "Plate width at most mountings on this estate is\n"
                                  "below the readable threshold. The platform grades\n"
                                  "each camera for ANPR and says which cameras can\n"
                                  "carry a registration claim and which cannot."),
             ("", ""),
             ("ANALYSIS RATE", f"{rate:.1f} frames/s of stream time on this host.\n"
                               "Playback is paced to real time, so a vehicle takes\n"
                               "as long to cross the frame here as on the road."),
             ("", ""),
             ("REPORT", f"{display(out)}.csv — every row above, with timestamps")],
            "What this run measured",
            started.strftime("Run started %Y-%m-%d %H:%M:%SZ")), 7.0)
    finally:
        writer.close()

    write_report(out, rows, runs, started, a.db, a.seconds, writer.n)

    print(f"\n{len(opened)}/{len(runs)} cameras decoded · {tracks} vehicles · "
          f"{len(plates)} distinct marks read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
