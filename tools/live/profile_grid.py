#!/usr/bin/env python3
"""Profile the live Sentinel Camera Grid before running anything expensive.

The first thirty minutes with a real feed are for measuring it, not for tuning
against it. This tool answers one question per camera — *what can this camera
actually deliver* — and answers it from a bounded, real-time sample with the
sample size attached to every number.

It runs **T0/T1 only** by default: decode, brightness, sharpness, scene motion.
Plate reading is opt-in (`--anpr`) because it is the expensive part and because
a plate yield taken before the stream characteristics are understood is a number
without a denominator.

Every stream is opened over RTSP/TCP, sampled, and **closed**. Each client gets
its own copy of the stream, so a probe that lingers is load the organiser's grid
carries for nothing.

    python tools/live/profile_grid.py --seconds 20
    python tools/live/profile_grid.py --seconds 45 --anpr --concurrency 5
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import itertools
import json
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import av
import numpy as np

from saakshya.common.paths import display
from saakshya.live import (
    CatalogueUnavailable,
    GridConfig,
    LiveCamera,
    discover_by_probe,
    fetch_catalogue,
    has_credential,
)
from saakshya.live.credentials import credentialed, redact

av.logging.set_level(av.logging.FATAL)

IST = timezone(timedelta(hours=5, minutes=30), "IST")

#: Provenance label. Every report this project produces carries one, and they
#: are never mixed: a figure from the synthetic corpus and a figure from the
#: government grid answer different questions.
PROVENANCE = "GOVERNMENT_LIVE"


def _luma(bgr: np.ndarray) -> np.ndarray:
    return (0.114 * bgr[:, :, 0] + 0.587 * bgr[:, :, 1]
            + 0.299 * bgr[:, :, 2]).astype(np.float32)


#: Mean channel spread below which a frame carries no usable colour.
#:
#: Several cameras on the live grid switch to infrared overnight. They still
#: deliver a three-channel frame, so nothing upstream notices — but every
#: channel carries the same value, and a colour estimator asked to read a
#: vehicle from it returns a confident answer that is pure fabrication. This is
#: the discriminator, and it costs one subtraction per sampled frame.
MONOCHROME_CHROMA = 0.04


def _chroma(bgr: np.ndarray) -> float:
    if bgr.ndim != 3 or bgr.shape[2] < 3:
        return 0.0
    f = bgr.astype(np.float32)
    return float((f.max(axis=2) - f.min(axis=2)).mean()) / 255.0


def _laplacian_var(g: np.ndarray) -> float:
    """Sharpness proxy. Downsampled first so a 1440p camera is not judged on a
    different scale from a 576p one."""
    if g.shape[0] > 480:
        step = max(1, g.shape[0] // 480)
        g = g[::step, ::step]
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
           - 4.0 * g[1:-1, 1:-1])
    return float(lap.var())


def profile_camera(cam: LiveCamera, *, seconds: float, cfg: GridConfig,
                   anpr: bool = False, sample_fps: float = 2.0) -> dict[str, Any]:
    """One camera, one bounded real-time sample."""
    url = cam.rtsp_url or cfg.rtsp(cam.camera_id)
    rec: dict[str, Any] = {
        "camera_id": cam.camera_id,
        "provenance": PROVENANCE,
        "transport": "rtsp-tcp",
        "url_host": url.split("//", 1)[-1].split("/", 1)[0],
        "sampled_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "sampled_at_ist": datetime.now(IST).isoformat(timespec="seconds"),
        "sample_seconds_requested": seconds,
        "reachable": False,
        "decoder_warnings": 0,
        "problems": [],
    }

    container = None
    t_open = time.perf_counter()
    try:
        container = av.open(
            credentialed(url),
            options={"rtsp_transport": "tcp", "stimeout": "15000000"},
            timeout=20.0)
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            rec["problems"].append("no video stream in the container")
            return rec
        rec["open_seconds"] = round(time.perf_counter() - t_open, 2)
        rec["reachable"] = True
        rec["codec"] = stream.codec_context.name
        rec["width"] = getattr(stream, "width", None)
        rec["height"] = getattr(stream, "height", None)
        rec["resolution"] = (f"{rec['width']}x{rec['height']}"
                             if rec["width"] else None)
        rec["time_base"] = str(stream.time_base)
        rec["declared_fps"] = (float(stream.average_rate)
                               if stream.average_rate else None)
        rec["declared_fps_note"] = (
            "reported by the container. Not used for any timing decision — the "
            "guide warns it mismatches delivery, and it does.")

        tb = float(stream.time_base)
        pts: list[float] = []
        wall: list[float] = []
        lumas: list[float] = []
        chromas: list[float] = []
        sharps: list[float] = []
        motions: list[float] = []
        regressions = 0
        big_jumps = 0
        prev_small: np.ndarray | None = None
        next_sample = 0.0
        t_start = time.perf_counter()
        deadline = t_start + seconds
        first_frame_wall = None
        frames = 0
        sampled = 0

        while time.perf_counter() < deadline:
            try:
                packet_frames = None
                for frame in container.decode(stream):
                    packet_frames = True
                    if frame.pts is None:
                        continue
                    t = float(frame.pts) * tb
                    now = time.perf_counter()
                    if first_frame_wall is None:
                        first_frame_wall = now
                        rec["first_frame_after_open_s"] = round(now - t_open, 2)
                    frames += 1
                    if pts:
                        d = t - pts[-1]
                        if d < -0.001:
                            regressions += 1
                        elif d > 5.0:
                            big_jumps += 1
                    pts.append(t)
                    wall.append(now)

                    # Sample by PTS, so a 10 fps and a 30 fps camera contribute
                    # the same number of measurements per second of video.
                    if t >= next_sample:
                        next_sample = t + 1.0 / sample_fps
                        img = frame.to_ndarray(format="bgr24")
                        g = _luma(img)
                        lumas.append(float(g.mean()) / 255.0)
                        chromas.append(_chroma(img))
                        sharps.append(_laplacian_var(g))
                        small = g[::8, ::8]
                        if prev_small is not None and small.shape == prev_small.shape:
                            motions.append(
                                float(np.abs(small - prev_small).mean()) / 255.0)
                        prev_small = small
                        sampled += 1
                    if now >= deadline:
                        break
                if packet_frames is None:
                    break
            except (av.FFmpegError, ValueError) as exc:
                # The guide is explicit that join-time decode warnings are
                # normal until the first IDR. Counted, never fatal.
                rec["decoder_warnings"] += 1
                rec.setdefault("first_decoder_warning",
                               f"{type(exc).__name__}: {str(exc)[:120]}")
                if rec["decoder_warnings"] > 200:
                    rec["problems"].append("sustained decoder errors")
                    break

        elapsed = time.perf_counter() - t_start
        rec["sample_seconds_actual"] = round(elapsed, 2)
        rec["frames_observed"] = frames
        rec["frames_sampled"] = sampled

        if len(pts) >= 2:
            span = pts[-1] - pts[0]
            rec["pts_span_s"] = round(span, 3)
            rec["measured_fps"] = round(frames / span, 2) if span > 0 else None
            gaps = [b - a for a, b in itertools.pairwise(pts) if b > a]
            if gaps:
                rec["mean_interframe_gap_s"] = round(statistics.fmean(gaps), 4)
                rec["max_interframe_gap_s"] = round(max(gaps), 3)
                rec["p95_interframe_gap_s"] = round(
                    sorted(gaps)[int(0.95 * len(gaps))], 4)
            rec["pts_regressions"] = regressions
            rec["pts_forward_jumps"] = big_jumps
            # A live stream must not outrun the wall clock for long. The join
            # burst is expected — a buffered GOP replays — so this is measured
            # over the whole sample rather than at the start.
            wall_span = wall[-1] - wall[0]
            rec["realtime_ratio"] = (round(span / wall_span, 3)
                                     if wall_span > 0 else None)
            rec["pts_health"] = (
                "OK" if regressions == 0 and big_jumps == 0
                else f"{regressions} regression(s), {big_jumps} forward jump(s)")

        if lumas:
            rec["mean_luma"] = round(statistics.fmean(lumas), 3)
            rec["mean_chroma"] = round(statistics.fmean(chromas), 4)
            rec["colour_mode"] = ("MONOCHROME_OR_IR"
                                  if rec["mean_chroma"] < MONOCHROME_CHROMA
                                  else "COLOUR")
            rec["median_sharpness"] = round(statistics.median(sharps), 1)
            rec["scene_motion"] = (round(statistics.fmean(motions), 4)
                                   if motions else None)
            hour = datetime.now(IST).hour
            rec["time_band"] = (
                "LOW_LIGHT" if rec["mean_luma"] < 0.22
                else ("DAY" if 6 <= hour < 18 else "NIGHT"))

        if anpr and sampled:
            rec.update(_anpr_sample(container, stream, seconds=min(20.0, seconds)))

    except Exception as exc:
        rec["problems"].append(f"{type(exc).__name__}: {redact(str(exc))[:160]}")
    finally:
        if container is not None:
            # Every client gets its own copy of the stream; a probe that fails
            # to close is load the organiser's grid carries for nothing.
            with contextlib.suppress(Exception):
                container.close()

    rec.update(grade(rec))
    return rec


def _anpr_sample(container: Any, stream: Any, *, seconds: float) -> dict[str, Any]:
    """Opt-in detection pass on frames already being decoded."""
    from saakshya.analytics.anpr import AnprEngine
    from saakshya.analytics.plates import parse

    engine = AnprEngine()
    tb = float(stream.time_base)
    seen = plates = valid = 0
    t_end = time.perf_counter() + seconds
    next_at = 0.0
    try:
        for frame in container.decode(stream):
            if time.perf_counter() > t_end:
                break
            if frame.pts is None:
                continue
            t = float(frame.pts) * tb
            if t < next_at:
                continue
            next_at = t + 1.0
            img = frame.to_ndarray(format="bgr24")
            seen += 1
            reads = engine.read_frame(img, t)
            plates += len(reads)
            # A detection is not a read. Only text that parses to a valid Indian
            # registration mark counts, and even then this is yield, not
            # accuracy — there is no ground truth for a live feed.
            for r in reads:
                canon = parse(r.text)
                if canon.valid:
                    valid += 1
    except Exception as exc:
        return {"anpr_error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return {
        "anpr_frames": seen,
        "anpr_plate_detections": plates,
        "anpr_valid_reads": valid,
        # Never called accuracy. Accuracy needs ground truth, which we do not
        # have for a live feed.
        "anpr_read_yield": round(valid / seen, 3) if seen else None,
        "anpr_note": ("read yield per sampled frame, not accuracy — there is no "
                      "ground truth for this feed"),
    }


#: Evidence floors. Below these the answer is UNKNOWN, whatever the numbers
#: happen to look like. A twenty-second sample cannot establish what a camera
#: does over a day, and saying so is the difference between a measurement and
#: a guess.
MIN_FRAMES_PRESENCE = 40
MIN_SAMPLES_QUALITY = 8

#: Illumination floor for appearance work, on mean luma (0..1).
#:
#: Measured on the first live profile of the grid: mean luma ranged 0.023 to
#: 0.572 across thirty cameras at ~00:20 IST. Two cameras (cam07, cam09) sit
#: near 0.03-0.06 — effectively black frames from which no colour can be
#: recovered, whatever the resolution says.
MIN_LUMA_APPEARANCE = 0.12
GOOD_LUMA_APPEARANCE = 0.20

#: A live stream delivering well under real time is missing frames, whatever
#: rate it reports. Measured: cam15 declares 10 fps, delivers 4.01, and its PTS
#: advances at 0.396x wall time.
MIN_REALTIME_RATIO = 0.80


def grade(rec: dict[str, Any]) -> dict[str, Any]:
    """Capability from the sample, with UNKNOWN as a first-class answer."""
    caps = {k: "UNKNOWN" for k in
            ("presence", "vehicle_detection", "vehicle_appearance", "anpr",
             "tracking", "forensic")}
    why: dict[str, str] = {}

    if not rec.get("reachable"):
        return {"capability": caps, "capability_reasons":
                {"presence": "camera was not reachable during this sample"},
                "evidence_confidence": "NONE",
                "recommended_tier": "UNASSIGNED"}

    frames = rec.get("frames_observed", 0)
    fps = rec.get("measured_fps") or 0
    gap = rec.get("max_interframe_gap_s") or 0
    sharp = rec.get("median_sharpness")
    luma = rec.get("mean_luma")
    height = rec.get("height") or 0

    # -- presence --------------------------------------------------------- #
    if frames < MIN_FRAMES_PRESENCE:
        why["presence"] = (f"{frames} frames in the sample; "
                           f"{MIN_FRAMES_PRESENCE} needed to grade delivery")
    elif rec.get("pts_regressions", 0) > 0:
        caps["presence"] = "DEGRADED"
        why["presence"] = (f"{rec['pts_regressions']} PTS regression(s) — "
                           "ordering is unreliable, so absence of a detection "
                           "here is not evidence of absence")
    elif (rec.get("realtime_ratio") or 1.0) < MIN_REALTIME_RATIO:
        caps["presence"] = "DEGRADED"
        why["presence"] = (
            f"PTS advanced at {rec['realtime_ratio']:.2f}x wall time over the "
            f"sample at {fps:.1f} fps — this stream is not keeping up with real "
            "time, so periods of it are simply not delivered")
    elif fps < 4:
        caps["presence"] = "DEGRADED"
        why["presence"] = (f"{fps:.1f} fps measured by PTS; vehicles will be "
                           "missed between frames")
    elif gap > 3.0:
        caps["presence"] = "DEGRADED"
        why["presence"] = f"largest inter-frame gap {gap:.1f}s"
    else:
        caps["presence"] = "GOOD"
        why["presence"] = (f"{frames} frames at {fps:.1f} fps by PTS, "
                           f"max gap {gap:.2f}s")

    # -- tracking --------------------------------------------------------- #
    if caps["presence"] == "UNKNOWN":
        why["tracking"] = "not enough delivery evidence"
    elif fps >= 8 and rec.get("pts_regressions", 0) == 0:
        caps["tracking"] = "GOOD"
        why["tracking"] = f"{fps:.1f} fps with monotonic PTS"
    elif fps >= 4:
        caps["tracking"] = "DEGRADED"
        why["tracking"] = (f"{fps:.1f} fps — association across frames will be "
                           "harder and tracks will fragment")
    else:
        caps["tracking"] = "UNSUITABLE"
        why["tracking"] = f"{fps:.1f} fps is too sparse to associate a vehicle"

    # -- vehicle detection and appearance --------------------------------- #
    if rec.get("frames_sampled", 0) < MIN_SAMPLES_QUALITY or sharp is None:
        why["vehicle_detection"] = "not enough sampled frames to judge the image"
    else:
        # Resolution and illumination gate; sharpness is recorded and NOT gated
        # on. Raw Laplacian variance is scene-dependent — a camera pointed at
        # foliage scores high and one pointed at clean tarmac scores low, at
        # identical focus — so an absolute threshold across cameras compares
        # scenes rather than optics. Measured on the first live profile: 221 to
        # 9261 across thirty cameras, with the lowest belonging to one of the
        # darkest rather than the softest. An earlier version of this grader
        # used a threshold of 100, below the observed *minimum*, so the test
        # passed for every camera and contributed nothing.
        if height >= 720:
            caps["vehicle_detection"] = "GOOD"
            why["vehicle_detection"] = (
                f"{rec['resolution']} (sharpness {sharp:.0f}, recorded but not "
                "gated on — it varies with scene content, not just optics)")
        elif height >= 480:
            caps["vehicle_detection"] = "DEGRADED"
            why["vehicle_detection"] = (
                f"{rec['resolution']} — vehicles detectable, small or distant "
                "ones unreliable")
        else:
            caps["vehicle_detection"] = "UNSUITABLE"
            why["vehicle_detection"] = f"{rec['resolution']} is below usable"

        lum = luma if luma is not None else 0.0
        chroma = rec.get("mean_chroma")
        if chroma is not None and chroma < MONOCHROME_CHROMA:
            # Not a judgement about the camera — a statement about the frame.
            # The estate's night mode is infrared on several cameras, and
            # colour-based appearance matching on an IR frame is fabrication
            # dressed as a measurement.
            caps["vehicle_appearance"] = "UNSUITABLE"
            why["vehicle_appearance"] = (
                f"monochrome / infrared frame (mean chroma {chroma:.4f}) — "
                "there is no colour in this image to match on. Vehicle "
                "detection and presence are unaffected.")
        elif lum < MIN_LUMA_APPEARANCE:
            caps["vehicle_appearance"] = "UNSUITABLE"
            why["vehicle_appearance"] = (
                f"mean luma {lum:.3f} — effectively no illumination in frame. "
                "No colour or appearance signal can be recovered here, and "
                "producing one would be inventing it.")
        elif lum > 0.85:
            caps["vehicle_appearance"] = "UNSUITABLE"
            why["vehicle_appearance"] = (
                f"mean luma {lum:.3f} — the frame is blown out")
        elif caps["vehicle_detection"] == "GOOD" and lum >= GOOD_LUMA_APPEARANCE:
            caps["vehicle_appearance"] = "GOOD"
            why["vehicle_appearance"] = (
                f"{rec['resolution']} at mean luma {lum:.3f}")
        elif caps["vehicle_detection"] in ("GOOD", "DEGRADED"):
            caps["vehicle_appearance"] = "DEGRADED"
            why["vehicle_appearance"] = (
                f"mean luma {lum:.3f} at {rec['resolution']} — appearance "
                "narrows a candidate list here; it does not identify a vehicle")
        else:
            caps["vehicle_appearance"] = "UNSUITABLE"
            why["vehicle_appearance"] = (
                f"{rec['resolution']} at mean luma {lum:.3f}")

    # -- ANPR -------------------------------------------------------------- #
    if "anpr_frames" in rec:
        n = rec["anpr_frames"]
        y = rec.get("anpr_read_yield") or 0.0
        if n < 10:
            why["anpr"] = f"only {n} frames passed through the reader"
        elif y >= 0.25:
            caps["anpr"] = "GOOD"
            why["anpr"] = f"{y:.0%} of sampled frames yielded a valid read"
        elif y > 0.02:
            caps["anpr"] = "DEGRADED"
            why["anpr"] = (f"{y:.0%} read yield — usable as corroboration, not "
                           "as sole identification")
        else:
            caps["anpr"] = "UNSUITABLE"
            why["anpr"] = (f"{y:.0%} read yield over {n} frames; route plate "
                           "work elsewhere")
    else:
        why["anpr"] = ("not measured in this pass — run with --anpr once the "
                       "stream characteristics are understood")

    # -- forensic ---------------------------------------------------------- #
    if caps["vehicle_detection"] == "GOOD" and (height or 0) >= 1080:
        caps["forensic"] = "GOOD"
        why["forensic"] = f"{rec['resolution']} supports re-processing a crop"
    elif caps["vehicle_detection"] != "UNKNOWN":
        caps["forensic"] = "DEGRADED"
        why["forensic"] = "resolution limits what re-processing can recover"

    known = sum(1 for v in caps.values() if v != "UNKNOWN")
    confidence = ("NONE" if known == 0
                  else "LOW" if rec.get("sample_seconds_actual", 0) < 15
                  else "MODERATE" if rec.get("sample_seconds_actual", 0) < 60
                  else "GOOD")

    tier = "T0"
    if caps["anpr"] in ("GOOD", "DEGRADED"):
        tier = "T2"
    elif caps["vehicle_appearance"] in ("GOOD", "DEGRADED"):
        tier = "T1"
    elif caps["presence"] in ("GOOD", "DEGRADED"):
        tier = "T0"
    if caps["presence"] == "UNKNOWN":
        tier = "UNASSIGNED"

    return {"capability": caps, "capability_reasons": why,
            "evidence_confidence": confidence,
            "recommended_tier": tier,
            "tier_note": ("recommended from this sample alone. A tier is a "
                          "scheduling decision, not a verdict, and it is "
                          "revised as observations accumulate.")}



def _fps_label(rec: dict[str, Any]) -> str:
    v = rec.get("measured_fps")
    return f"{v} fps" if v else "-"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0,
                    help="real-time sample per camera")
    ap.add_argument("--concurrency", type=int, default=5,
                    help="cameras open at once — each client gets its own copy "
                         "of the stream, so keep this modest")
    ap.add_argument("--anpr", action="store_true",
                    help="run plate detection during the sample (expensive)")
    ap.add_argument("--cameras", default=None,
                    help="comma-separated subset; default is the whole grid")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-json", type=Path,
                    default=ROOT / "var" / "reports" / "live_camera_profile.json")
    ap.add_argument("--out-md", type=Path,
                    default=ROOT / "var" / "reports" / "live_camera_profile.md")
    ap.add_argument("--db", default=None,
                    help="persist measured timebase health into this store")
    args = ap.parse_args()

    cfg = GridConfig.from_env()
    print("SAAKSHYA live grid profile")
    print(f"provenance : {PROVENANCE}")
    print(f"sample     : {args.seconds:.0f}s per camera, "
          f"{args.concurrency} concurrent, anpr={'on' if args.anpr else 'off'}")

    catalogue_status: dict[str, Any]
    try:
        cams = fetch_catalogue(cfg)
        catalogue_status = {"source": "catalogue", "url": cfg.catalogue_url,
                            "cameras": len(cams)}
        print(f"catalogue  : {len(cams)} cameras from {cfg.catalogue_url}")
    except CatalogueUnavailable as exc:
        print(f"catalogue  : UNAVAILABLE — {exc}")
        print("discovery  : probing the documented RTSP id pattern instead")
        cams = discover_by_probe(cfg)
        catalogue_status = {
            "source": "probe",
            "reason": str(exc),
            "credential_present": has_credential(),
            "cameras": len(cams),
            "caveat": ("The camera set was discovered by probing the documented "
                       "id pattern because the catalogue host requires a "
                       "signed-in session. It is not the authoritative set and "
                       "may miss cameras whose ids do not follow the pattern."),
        }
        print(f"discovered : {len(cams)} cameras")

    if args.cameras:
        wanted = {c.strip() for c in args.cameras.split(",") if c.strip()}
        cams = [c for c in cams if c.camera_id in wanted]
    if args.limit:
        cams = cams[:args.limit]
    if not cams:
        print("no cameras to profile", file=sys.stderr)
        return 2

    print(f"profiling  : {len(cams)} cameras\n")
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(profile_camera, c, seconds=args.seconds,
                               cfg=cfg, anpr=args.anpr): c for c in cams}
        for fut in cf.as_completed(futures):
            rec = fut.result()
            results.append(rec)
            caps = rec.get("capability", {})
            print(f"  {rec['camera_id']:8} "
                  f"{rec.get('resolution') or '-':11} "
                  f"{rec.get('codec') or '-':5} "
                  f"{_fps_label(rec):10} "
                  f"presence={caps.get('presence', '-'):11} "
                  f"tier={rec.get('recommended_tier', '-')}")

    results.sort(key=lambda r: r["camera_id"])
    elapsed = time.perf_counter() - t0

    # Timing health is the input to every cross-camera decision, so it belongs
    # in the store rather than only in a report a human reads.
    if args.db:
        _persist_timebase(args.db, results)
        print(f"timebase   : recorded for {len(results)} cameras in {args.db}")

    report = {
        "provenance": PROVENANCE,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "generated_at_ist": datetime.now(IST).isoformat(timespec="seconds"),
        "sample_seconds_per_camera": args.seconds,
        "concurrency": args.concurrency,
        "anpr_measured": args.anpr,
        "wall_seconds": round(elapsed, 1),
        "catalogue": catalogue_status,
        "cameras_profiled": len(results),
        "cameras_reachable": sum(1 for r in results if r.get("reachable")),
        "cameras": results,
        "method": ("Bounded real-time RTSP/TCP sample per camera. Every stream "
                   "was closed after sampling. Timing is from PTS; the "
                   "container's declared frame rate is recorded and not used."),
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2))
    args.out_md.write_text(render_markdown(report))

    print(f"\n{report['cameras_reachable']}/{len(results)} reachable "
          f"in {elapsed:.0f}s")
    # `relative_to` raises when the caller passes a relative path, which turned
    # a successful profiling run into a traceback on its last line.
    print(f"written: {display(args.out_json)}")
    print(f"         {display(args.out_md)}")
    return 0


def _persist_timebase(db_url: str, results: list[dict[str, Any]]) -> None:
    from saakshya.live.timebase import (
        OverlayClock,
        TimebaseHealth,
        TimebaseRegistry,
        assess_pts,
    )
    from saakshya.store import Store

    store = Store(db_url)
    store.create_all()
    registry = TimebaseRegistry(store)
    for r in results:
        health, why = assess_pts(
            regressions=r.get("pts_regressions", 0),
            forward_jumps=r.get("pts_forward_jumps", 0),
            realtime_ratio=r.get("realtime_ratio"),
            max_gap_s=r.get("max_interframe_gap_s"),
            frames=r.get("frames_observed", 0))
        # Existing cluster membership is preserved: it was established from
        # evidence a stream sample cannot see, and re-profiling must not erase
        # it.
        prior = registry.get(r["camera_id"])
        registry.record(TimebaseHealth(
            camera_id=r["camera_id"], pts_health=health,
            pts_regressions=r.get("pts_regressions", 0),
            pts_forward_jumps=r.get("pts_forward_jumps", 0),
            realtime_ratio=r.get("realtime_ratio"),
            measured_fps=r.get("measured_fps"),
            mean_interframe_gap_s=r.get("mean_interframe_gap_s"),
            max_interframe_gap_s=r.get("max_interframe_gap_s"),
            overlay_clock=(prior.overlay_clock if prior else OverlayClock.UNKNOWN),
            overlay_reading=(prior.overlay_reading if prior else None),
            time_cluster=(prior.time_cluster if prior else None),
            cluster_confidence=(prior.cluster_confidence if prior else "UNKNOWN"),
            evidence={"why": why, "sampled_at": r.get("sampled_at_utc")}))


def render_markdown(rep: dict[str, Any]) -> str:
    L: list[str] = []
    a = L.append
    a("# Live camera profile — Sentinel Camera Grid")
    a("")
    a(f"**Provenance:** `{rep['provenance']}` — the organiser's live grid. "
      "These figures are not comparable with the local synthetic corpus and are "
      "never merged with it.")
    a("")
    a(f"**Generated:** {rep['generated_at_ist']} (IST) · "
      f"{rep['generated_at_utc']} (UTC)")
    a(f"**Sample:** {rep['sample_seconds_per_camera']:.0f} s per camera, "
      f"{rep['concurrency']} concurrent, "
      f"ANPR {'measured' if rep['anpr_measured'] else 'not measured in this pass'}")
    a(f"**Reachable:** {rep['cameras_reachable']} of {rep['cameras_profiled']}")
    a("")
    cat = rep["catalogue"]
    if cat.get("source") == "probe":
        a("> **Camera set discovered by probing, not from the catalogue.**")
        a("> " + cat.get("caveat", ""))
        a(">")
        a(f"> Catalogue said: {cat.get('reason', '')}")
    else:
        a(f"Camera set from the catalogue at `{cat.get('url')}`.")
    a("")
    a("## Delivery")
    a("")
    a("| Camera | Codec | Resolution | Declared | **Measured (PTS)** | Mean gap "
      "| Max gap | PTS health | Warnings |")
    a("|---|---|---|---:|---:|---:|---:|---|---:|")
    for r in rep["cameras"]:
        if not r.get("reachable"):
            a(f"| `{r['camera_id']}` | — | — | — | — | — | — | "
              f"**unreachable** | — |")
            continue
        a(f"| `{r['camera_id']}` | {r.get('codec', '—')} | "
          f"{r.get('resolution', '—')} | "
          f"{r.get('declared_fps') or '—'} | "
          f"**{r.get('measured_fps') or '—'}** | "
          f"{r.get('mean_interframe_gap_s') or '—'} | "
          f"{r.get('max_interframe_gap_s') or '—'} | "
          f"{r.get('pts_health', '—')} | {r.get('decoder_warnings', 0)} |")
    a("")
    a("The declared rate is what the container reports. The measured rate is "
      "derived from presentation timestamps over the sample. Where they differ, "
      "the measured figure is the one every timing decision in this system uses.")
    a("")
    a("## Image and scene")
    a("")
    a("| Camera | Mean luma | Chroma | Colour mode | Sharpness | Scene motion "
      "| Band | Frames |")
    a("|---|---:|---:|---|---:|---:|---|---:|")
    for r in rep["cameras"]:
        if not r.get("reachable"):
            continue
        a(f"| `{r['camera_id']}` | {r.get('mean_luma', '—')} | "
          f"{r.get('mean_chroma', '—')} | {r.get('colour_mode', '—')} | "
          f"{r.get('median_sharpness', '—')} | {r.get('scene_motion', '—')} | "
          f"{r.get('time_band', '—')} | {r.get('frames_observed', 0)} |")
    a("")
    a("`MONOCHROME_OR_IR` means the camera is delivering a three-channel frame "
      "with no colour in it — infrared night mode. Nothing upstream would "
      "notice, and a colour estimator asked to read a vehicle from such a frame "
      "returns a confident answer that is fabricated. Appearance is graded "
      "UNSUITABLE on those cameras; detection and presence are unaffected.")
    a("")
    a("## Capability")
    a("")
    a("Measured from this sample. **UNKNOWN means not enough evidence, never "
      "poor quality** — a short sample cannot establish what a camera does "
      "across a day, and converting silence into a bad grade would slander "
      "working equipment.")
    a("")
    a("| Camera | Presence | Vehicle | Appearance | ANPR | Tracking | Forensic "
      "| Tier | Confidence |")
    a("|---|---|---|---|---|---|---|---|---|")
    for r in rep["cameras"]:
        c = r.get("capability", {})
        a(f"| `{r['camera_id']}` | {c.get('presence', '—')} | "
          f"{c.get('vehicle_detection', '—')} | "
          f"{c.get('vehicle_appearance', '—')} | {c.get('anpr', '—')} | "
          f"{c.get('tracking', '—')} | {c.get('forensic', '—')} | "
          f"**{r.get('recommended_tier', '—')}** | "
          f"{r.get('evidence_confidence', '—')} |")
    a("")
    a("## Why each grade")
    a("")
    for r in rep["cameras"]:
        reasons = r.get("capability_reasons") or {}
        if not reasons:
            continue
        a(f"**`{r['camera_id']}`**")
        a("")
        for k, v in reasons.items():
            a(f"- *{k}* — {v}")
        a("")
    problems = [(r["camera_id"], p) for r in rep["cameras"]
                for p in r.get("problems", [])]
    if problems:
        a("## Problems")
        a("")
        for cam, p in problems:
            a(f"- `{cam}` — {p}")
        a("")
    a("## Method")
    a("")
    a(rep["method"])
    a("")
    a("Nothing here was tuned against this feed. Profiling comes before model "
      "selection, and a threshold moved to improve a number on the first day of "
      "real data is a threshold fitted to noise.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
