#!/usr/bin/env python3
"""Build the local Sentinel Camera Grid replica.

Renders a heterogeneous camera corpus, writes bounding-box ground truth, and
emits a MediaMTX config that loops each clip forever — reproducing the sandbox's
documented behaviour (mixed H.264/H.265, mixed resolution and frame rate, loop
discontinuity, GOP replay on connect).

Run:  python tools/sandbox/make_media.py [--force]
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene import Degradation, SceneRenderer, SceneSpec, VehiclePass

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).resolve().parents[2]

def display(path, base=None):
    """Shorten a path for display, never raising. See saakshya.common.paths."""
    p = Path(path)
    if base is None:
        return str(p)
    try:
        return str(p.resolve().relative_to(Path(base).resolve()))
    except (ValueError, OSError):
        return str(p)

OUT = ROOT / "var" / "media"

TARGET = "GJ05AB1234"

WHITE = (216, 221, 227)
RED = (150, 47, 47)
BLUE = (47, 85, 150)
YELLOW = (201, 162, 39)
GREEN = (63, 107, 63)


@dataclass
class CameraSpec:
    camera_id: str
    name: str
    department: str
    district: str
    lat: float
    lon: float
    width: int
    height: int
    fps: int
    codec: str
    duration: float
    quality_note: str
    passes: list[VehiclePass] = field(default_factory=list)
    degradation: Degradation = field(default_factory=Degradation)


# --------------------------------------------------------------------------- #
# The corpus mirrors the five departments the organisers named — Health, Police,
# GSRTC, Panchayat, Municipal — because the point of this system is that those
# cameras were never built for ANPR. C-033 is the hard case.
# --------------------------------------------------------------------------- #
CAMERAS: list[CameraSpec] = [
    CameraSpec(
        "C-014", "Naroda Circle Junction", "Home (Traffic)", "Ahmedabad",
        23.0742, 72.6325, 1280, 720, 15, "libx264", 60,
        "Daylight traffic chokepoint — ANPR viable",
        passes=[
            VehiclePass(TARGET, WHITE, "white", "car", 6, 5.0, lane=0),
            VehiclePass("GJ01CD5678", RED, "red", "car", 18, 6.0, lane=1),
            VehiclePass("GJ18XY9012", BLUE, "blue", "truck", 34, 7.0, lane=0, scale=1.3),
        ],
    ),
    CameraSpec(
        "C-021", "GSRTC Depot Gate 2", "GSRTC", "Ahmedabad",
        23.0301, 72.5810, 1280, 720, 12, "libx265", 60,
        "Bus depot gate — moderate angle, some motion blur",
        passes=[
            VehiclePass("GJ01CD5678", RED, "red", "car", 8, 6.0, lane=1),
            VehiclePass(TARGET, WHITE, "white", "car", 17, 5.0, lane=0),
            VehiclePass("GJ06MN3344", YELLOW, "yellow", "bus", 40, 8.0, lane=1, scale=1.45),
        ],
        degradation=Degradation(blur_sigma=0.7, noise_sigma=3.0),
    ),
    CameraSpec(
        # HARD CASE — Panchayat office camera. Low mount, low light, soft optics,
        # low resolution. The vehicle is clearly visible to a human; the plate is
        # not recoverable by OCR. Tuned against measured plate legibility below.
        "C-033", "Dehgam Panchayat Office", "Panchayat", "Gandhinagar",
        23.1701, 72.8210, 640, 480, 10, "libx264", 60,
        "Low-light, low-res, soft focus — ANPR not viable, vehicle still usable",
        passes=[
            VehiclePass(TARGET, WHITE, "white", "car", 25, 6.0, lane=0),
            VehiclePass("GJ27PQ7788", GREEN, "green", "car", 44, 6.0, lane=1),
        ],
        degradation=Degradation(blur_sigma=2.4, brightness=0.62, contrast=0.80,
                                noise_sigma=7.0, jpeg_like=2),
    ),
    CameraSpec(
        "C-047", "Gandhinagar Sector 21 Chowk", "Municipal", "Gandhinagar",
        23.2156, 72.6369, 1920, 1080, 15, "libx265", 60,
        "High-resolution municipal junction — ANPR viable",
        passes=[
            VehiclePass("GJ18XY9012", BLUE, "blue", "truck", 12, 7.0, lane=1, scale=1.3),
            VehiclePass(TARGET, WHITE, "white", "car", 34, 5.0, lane=0),
        ],
    ),
    CameraSpec(
        "C-052", "Civil Hospital Gate", "Health", "Ahmedabad",
        23.0530, 72.6050, 960, 540, 8, "libx264", 60,
        "Hospital gate — glare from canopy lighting",
        passes=[VehiclePass("GJ27PQ7788", GREEN, "green", "car", 15, 7.0, lane=0)],
        degradation=Degradation(glare_strength=0.34, blur_sigma=0.5),
    ),
    CameraSpec(
        # Decoy: a white car with a plate one character-class from the target,
        # on a route the target never took. Exists to catch false positives.
        "C-061", "Vastral Police Chowky", "Home (Police)", "Ahmedabad",
        23.0100, 72.6600, 1280, 720, 15, "libx264", 60,
        "Police post camera",
        passes=[VehiclePass("GJ05AB9999", WHITE, "white", "car", 20, 5.0, lane=0)],
    ),
]



# --------------------------------------------------------------------------- #
# Background traffic.
#
# The original corpus carried two or three vehicles per camera, which was enough
# to test detection and tracking and not remotely enough for anything
# statistical. Capability grading refuses to grade a camera on fewer than twenty
# observations, the graph refuses to trust an edge on fewer than three
# transitions, and both refusals are correct — so the corpus had to grow rather
# than the thresholds shrink.
#
# Two populations, generated deterministically from a fixed seed:
#
#   * **Corridor commuters** traverse several cameras in order, giving the graph
#     repeated transitions to learn a travel-time distribution from. Without
#     these, every edge stays untrusted and the route reasoning has nothing
#     measured to stand on.
#   * **Local traffic** passes a single camera. It is the noise the search has to
#     work through, and it is what makes a plate yield or a colour-confidence
#     yield mean anything.
#
# The scripted passes above are untouched: they encode the scenario the
# demonstration follows, and regenerating traffic must never move the target.
# --------------------------------------------------------------------------- #
CORPUS_SECONDS = 240.0

#: Cameras in corridor order, with the in-clip time offset applied when the
#: recordings are laid onto a single normalised timeline. A commuter seen at
#: t=30 on the first camera is seen at t=30 on the second, which after offsets
#: is five minutes later — a plausible urban leg.
CORRIDOR = ["C-014", "C-021", "C-033", "C-047"]

_BODY_COLOURS = [
    (WHITE, "white"), (RED, "red"), (BLUE, "blue"), (YELLOW, "yellow"),
    (GREEN, "green"), ((92, 96, 104), "grey"), ((28, 30, 34), "black"),
    ((176, 180, 188), "silver"),
]
_TYPES = [("car", 1.0), ("car", 1.0), ("car", 1.0), ("truck", 1.3), ("bus", 1.45)]


def _plate(rng: random.Random, taken: set[str]) -> str:
    """A syntactically valid Indian registration mark that is not already in use.

    Generated rather than listed so the corpus can grow without a hand-written
    table, and seeded so two runs produce the same corpus — an evaluation that
    cannot be repeated is not an evaluation.
    """
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"      # I and O omitted: OCR confusables
    while True:
        p = (f"GJ{rng.randint(1, 38):02d}"
             f"{rng.choice(letters)}{rng.choice(letters)}"
             f"{rng.randint(1000, 9999)}")
        if p not in taken:
            taken.add(p)
            return p


def generate_traffic(cameras: list[CameraSpec], *, seed: int = 20260901,
                     commuters: int = 40, local_per_camera: int = 14) -> None:
    """Append generated passes to every camera, in place."""
    rng = random.Random(seed)
    by_id = {c.camera_id: c for c in cameras}
    taken = {p.plate for c in cameras for p in c.passes}

    # -- corridor commuters ------------------------------------------------- #
    for _ in range(commuters):
        plate = _plate(rng, taken)
        body, colour = rng.choice(_BODY_COLOURS)
        vtype, scale = rng.choice(_TYPES)
        # Enters the corridor somewhere in the first two thirds so it has time
        # to reach the far end within the clip.
        t = rng.uniform(4.0, CORPUS_SECONDS * 0.62)
        # Not every vehicle traverses the whole corridor; a vehicle that leaves
        # part-way is exactly the case trajectory reasoning must handle.
        # Weighted towards longer runs so consecutive edges accumulate the
        # three transitions the graph needs before it will trust one.
        stop = rng.choices([2, 3, 4], weights=[2, 3, 5])[0]
        for i, cam_id in enumerate(CORRIDOR[:stop]):
            cam = by_id.get(cam_id)
            if cam is None:
                continue
            # Jitter per leg, so the learned travel time has a real spread
            # rather than a single repeated value.
            t_cam = t + rng.uniform(-14.0, 14.0) * (1 if i else 0)
            t_cam = max(2.0, min(CORPUS_SECONDS - 9.0, t_cam))
            cam.passes.append(VehiclePass(
                plate, body, colour, vtype, round(t_cam, 2),
                rng.uniform(4.5, 7.0), lane=i % 2, scale=scale))

    # -- local traffic ------------------------------------------------------ #
    for cam in cameras:
        for _ in range(local_per_camera):
            plate = _plate(rng, taken)
            body, colour = rng.choice(_BODY_COLOURS)
            vtype, scale = rng.choice(_TYPES)
            cam.passes.append(VehiclePass(
                plate, body, colour, vtype,
                round(rng.uniform(2.0, CORPUS_SECONDS - 9.0), 2),
                rng.uniform(4.5, 7.0), lane=rng.randint(0, 1), scale=scale))
        # Passes are rendered by time; sorting keeps overlapping vehicles drawn
        # in a stable order between runs.
        cam.passes.sort(key=lambda p: (p.t_enter, p.plate))
        cam.duration = CORPUS_SECONDS


def render(cam: CameraSpec, force: bool = False) -> tuple[Path, list[dict], float]:
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{cam.camera_id}.mp4"

    spec = SceneSpec(
        camera_id=cam.camera_id, width=cam.width, height=cam.height,
        fps=cam.fps, duration=cam.duration, passes=cam.passes,
        degradation=cam.degradation,
    )
    r = SceneRenderer(spec)

    # Measure plate legibility at the mid-point of each pass. This is what lets
    # us say "ANPR not viable here" as a measurement rather than an assertion.
    legibility = []
    for p in cam.passes:
        legibility.append(r.measured_plate_legibility(p.t_enter + p.duration / 2))
    mean_leg = sum(legibility) / max(1, len(legibility))

    frame_truth: list[dict] = []
    n_frames = int(cam.duration * cam.fps)

    if dst.exists() and not force:
        # Still recompute truth (cheap relative to encoding) so it stays in sync.
        for i in range(n_frames):
            t = i / cam.fps
            _, truth = r.frame(t)
            if truth:
                frame_truth.append({"t": round(t, 3), "objects": truth})
        print(f"  {cam.camera_id}: exists, skipped encode (legibility {mean_leg:.3f})")
        return dst, frame_truth, mean_leg

    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{cam.width}x{cam.height}", "-r", str(cam.fps), "-i", "-",
        "-c:v", cam.codec, "-pix_fmt", "yuv420p",
        "-g", str(cam.fps * 2),
        "-b:v", "2000k" if cam.width >= 1280 else "900k",
    ]
    if cam.codec == "libx264":
        # MediaMTX WebRTC rejects H.264 with B-frames ("WebRTC doesn't support
        # H264 streams with B-frames"). Baseline + bf=0 keeps WHEP stable.
        cmd += ["-profile:v", "baseline", "-bf", "0", "-x264-params", "bframes=0"]
    if cam.codec == "libx265":
        cmd += ["-tag:v", "hvc1", "-x265-params", "log-level=error"]
    cmd += [str(dst)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for i in range(n_frames):
            t = i / cam.fps
            bgr, truth = r.frame(t)
            proc.stdin.write(bgr.tobytes())
            if truth:
                frame_truth.append({"t": round(t, 3), "objects": truth})
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed for {cam.camera_id} (rc={proc.returncode})")

    print(f"  {cam.camera_id}: {cam.width}x{cam.height}@{cam.fps} {cam.codec} "
          f"legibility={mean_leg:.3f} -> {dst.name}")
    return dst, frame_truth, mean_leg


def write_ground_truth(truths: dict[str, list[dict]], legibility: dict[str, float]) -> Path:
    obs = []
    for cam in CAMERAS:
        for p in cam.passes:
            obs.append({
                "camera_id": cam.camera_id,
                "plate": p.plate,
                "t_enter_s": p.t_enter,
                "t_exit_s": p.t_enter + p.duration,
                "colour": p.colour_name,
                "vehicle_type": p.vtype,
                "measured_plate_legibility": round(legibility[cam.camera_id], 4),
            })
    target_obs = sorted((o for o in obs if o["plate"] == TARGET),
                        key=lambda o: (o["camera_id"]))
    gt = {
        "target_vehicle": TARGET,
        "route_expected": ["C-014", "C-021", "C-033", "C-047"],
        "route_note": "Order is the intended physical route. Each clip loops "
                      "independently, so the harness aligns observations by "
                      "reported segment start, not by absolute clip time.",
        "hard_case_camera": "C-033",
        "observations": obs,
        "target_observations": target_obs,
        "decoys": [{"plate": "GJ05AB9999", "camera_id": "C-061",
                    "why": "White car, plate shares GJ05AB prefix with target. "
                           "Must not be merged into the target trajectory."}],
        "watchlist_truth": [{"plate": TARGET, "category": "stolen_vehicle"}],
        "per_camera_legibility": {k: round(v, 4) for k, v in legibility.items()},
        "frame_level": truths,
    }
    dst = ROOT / "tests" / "evaluation" / "ground_truth.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(gt, indent=2))
    return dst


def write_catalogue(host: str = "127.0.0.1") -> Path:
    items = []
    for cam in CAMERAS:
        sid = cam.camera_id
        items.append({
            "id": sid, "name": cam.name, "department": cam.department,
            "district": cam.district,
            "location": {"lat": cam.lat, "lon": cam.lon},
            "codec": "h265" if cam.codec == "libx265" else "h264",
            "live": True,
            "properties": {"width": cam.width, "height": cam.height,
                           "declared_fps": cam.fps},
            "quality_note": cam.quality_note,
            "urls": {
                "rtsp": f"rtsp://{host}:8554/stream/{sid}",
                "whep": f"http://{host}:8889/stream/{sid}/whep",
                "hls": f"http://{host}:8888/stream/{sid}/index.m3u8",
            },
        })
    dst = OUT / "catalogue.json"
    dst.write_text(json.dumps({"cameras": items}, indent=2))
    return dst


def write_mediamtx_config() -> Path:
    # Symlink ffmpeg to a space-free relative location.
    link = ROOT / "var" / "bin" / "ffmpeg"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(FFMPEG)

    lines = [
        "# GENERATED by tools/sandbox/make_media.py",
        "# Local replica of the Sentinel Camera Grid.",
        "# Ports mirror the organiser's documented layout: RTSP 8554, HLS 8888,",
        "# WebRTC/WHEP 8889 — MediaMTX defaults, which is itself the evidence",
        "# that the sandbox is MediaMTX or a close equivalent.",
        "logLevel: warn",
        "rtspAddress: :8554",
        "rtspTransports: [tcp, udp]",
        "hlsAddress: :8888",
        "hlsAlwaysRemux: yes",
        "hlsAllowOrigins: [\"*\"]",
        "webrtcAddress: :8889",
        "webrtcAllowOrigins: [\"*\"]",
        "api: yes",
        "apiAddress: 127.0.0.1:9997",
        "apiAllowOrigins: [\"*\"]",
        "paths:",
    ]
    # Relative paths only. The project root can contain spaces, and MediaMTX
    # runs runOnInit through a shell without quoting for us, so absolute paths
    # silently fail to publish. ffmpeg is symlinked into var/bin for this.
    for cam in CAMERAS:
        lines += [
            f"  stream/{cam.camera_id}:",
            "    runOnInit: >-",
            "      var/bin/ffmpeg -hide_banner -loglevel error -re -stream_loop -1",
            f"      -i var/media/{cam.camera_id}.mp4 -c copy -f rtsp",
            f"      rtsp://127.0.0.1:8554/stream/{cam.camera_id}",
            "    runOnInitRestart: yes",
        ]
    dst = ROOT / "var" / "mediamtx.yml"
    dst.write_text("\n".join(lines) + "\n")
    return dst


def main() -> int:
    force = "--force" in sys.argv
    if "--no-traffic" not in sys.argv:
        generate_traffic(CAMERAS)
    print(f"ffmpeg: {FFMPEG}")
    print(f"Rendering {len(CAMERAS)} cameras -> {OUT}")
    for cam in CAMERAS:
        print(f"  {cam.camera_id}: {len(cam.passes)} vehicle passes "
              f"over {cam.duration:.0f}s")
    truths, legib = {}, {}
    for cam in CAMERAS:
        _, ft, leg = render(cam, force=force)
        truths[cam.camera_id] = ft
        legib[cam.camera_id] = leg
    gt = write_ground_truth(truths, legib)
    cat = write_catalogue()
    cfg = write_mediamtx_config()
    print(f"\nground truth : {display(gt, ROOT)}")
    print(f"catalogue    : {display(cat, ROOT)}")
    print(f"mediamtx cfg : {display(cfg, ROOT)}")
    total = sum(f.stat().st_size for f in OUT.glob("*.mp4"))
    print(f"media size   : {total/1e6:.1f} MB")
    print("\nmeasured plate legibility (higher = more ANPR-viable):")
    for k, v in sorted(legib.items(), key=lambda kv: -kv[1]):
        bar = "#" * int(v * 40)
        print(f"  {k}  {v:.3f}  {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
