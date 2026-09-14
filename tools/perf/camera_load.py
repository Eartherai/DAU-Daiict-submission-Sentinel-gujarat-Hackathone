#!/usr/bin/env python3
"""Concurrent camera simulation (§57).

Runs N simultaneous RTSP sources through the real ingest and analytics path,
kills some of them mid-run, and reports what actually happened. The purpose is
to replace a modelled claim with a measured one: "designed for 80,000 cameras"
is an architectural statement, and the only number this project is entitled to
quote as tested is the one this harness produces on the machine it ran on.

The sources are the corpus clips republished under N distinct path names, so
the codec and frame-rate mix is genuinely heterogeneous — h264 and h265, 8 to
15 fps, 640x480 to 1920x1080 — which is the situation on the real estate and
the reason a single-codec load test would prove nothing.

    python tools/perf/camera_load.py --cameras 50 --seconds 60
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import httpx

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig, persist_pipeline
from saakshya.common.paths import display
from saakshya.ingest.stream import StreamConfig, StreamManager
from saakshya.runtime.backend import quiet_transformers
from saakshya.store import Store

API = "http://127.0.0.1:9997/v3"
MEDIA = ROOT / "var" / "media"
FFMPEG = "var/bin/ffmpeg"


def publish_cmd(clip: str, name: str) -> str:
    # Relative paths only: an absolute path here contains a space on this
    # machine, and MediaMTX splits runOnInit on whitespace. That failure is
    # silent — the path simply never becomes ready — and cost an afternoon once.
    return (f"{FFMPEG} -hide_banner -loglevel error -re -stream_loop -1 "
            f"-i var/media/{clip} -c copy -f rtsp "
            f"rtsp://127.0.0.1:8554/{name}")


def wait_ready(names: list[str], timeout: float = 90.0) -> dict[str, bool]:
    deadline = time.time() + timeout
    ready: dict[str, bool] = {}
    while time.time() < deadline and len(ready) < len(names):
        try:
            r = httpx.get(f"{API}/paths/list?itemsPerPage=1000", timeout=8.0)
            items = {i["name"]: i["ready"] for i in r.json().get("items", [])}
        except Exception as exc:  # the replica may still be starting
            print(f"  waiting for the replica API: {exc}")
            time.sleep(2)
            continue
        for n in names:
            if items.get(n):
                ready[n] = True
        if len(ready) < len(names):
            time.sleep(1.5)
    return {n: ready.get(n, False) for n in names}


def main() -> int:
    quiet_transformers()
    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", type=int, default=50)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--fps", type=float, default=1.0,
                    help="analytics sampling rate per camera, by PTS")
    ap.add_argument("--kill", type=int, default=6,
                    help="cameras to fail mid-run to measure recovery")
    ap.add_argument("--db", default="sqlite:///var/loadtest.db")
    ap.add_argument("--json", type=Path,
                    default=ROOT / "var" / "reports" / "camera_load.json")
    args = ap.parse_args()

    clips = sorted(p.name for p in MEDIA.glob("*.mp4"))
    if not clips:
        print("no corpus; run `make media` first", file=sys.stderr)
        return 2

    names = [f"stream/LOAD-{i:03d}" for i in range(args.cameras)]
    assignment = {n: clips[i % len(clips)] for i, n in enumerate(names)}

    print(f"cameras   : {args.cameras} paths over {len(clips)} distinct source clips")
    print(f"codecs    : mixed (as rendered) — {', '.join(clips)}")
    print("registering paths with the replica…")
    added = 0
    for n in names:
        try:
            r = httpx.post(f"{API}/config/paths/add/{quote(n, safe='')}",
                           json={"runOnInit": publish_cmd(assignment[n], n),
                                 "runOnInitRestart": True}, timeout=10.0)
            added += r.status_code < 300
        except Exception as exc:
            print(f"  ! {n}: {exc}")
    print(f"registered: {added}/{len(names)}")
    if added == 0:
        print("the replica is not running. Start it with `make sandbox`.",
              file=sys.stderr)
        return 2

    ready = wait_ready(names)
    live = [n for n, ok in ready.items() if ok]
    print(f"ready     : {len(live)}/{len(names)} paths publishing")

    catalogue = {n.split("/", 1)[1]: f"rtsp://127.0.0.1:8554/{n}" for n in live}
    store = Store(args.db)
    store.create_all()
    for cid in catalogue:
        store.upsert_camera({"camera_id": cid, "name": cid,
                             "district": "LoadTest", "department": "LoadTest",
                             "lat": 23.0, "lon": 72.6, "enabled": True})

    mgr = StreamManager(StreamConfig())
    mgr.reconcile(catalogue)
    pipes = {cid: CameraPipeline(cid, PipelineConfig(), district="LoadTest")
             for cid in catalogue}
    queues = {cid: mgr.get(cid).subscribe("load") for cid in catalogue}

    t_end = time.time() + args.seconds
    kill_at = time.time() + args.seconds * 0.4
    killed: list[str] = []
    next_analyse: dict[str, float] = {}
    written = 0
    # Ingest capacity and analytics capacity are different numbers and must be
    # reported separately. A single-process consumer polling 50 queues cannot
    # keep up with 50 cameras, and reporting only the observation count makes
    # that look like a detection failure rather than what it is — a throughput
    # limit with a known architectural answer.
    frames_taken = 0        # frames the consumer actually pulled off a queue
    frames_analysed = 0     # frames that reached the analytics pipeline
    analysis_s = 0.0
    samples: list[dict] = []
    last_report = time.time()

    print(f"\nrunning for {args.seconds:.0f}s "
          f"(analytics at {args.fps} fps per camera, sampled by PTS)")
    while time.time() < t_end:
        for cid, q in queues.items():
            try:
                fr = q.get(timeout=0.002)
            except Exception:
                continue
            if fr is None:
                continue
            frames_taken += 1
            if fr.pts_s < next_analyse.get(cid, 0.0):
                continue
            next_analyse[cid] = fr.pts_s + 1.0 / args.fps
            t_a = time.perf_counter()
            obs = pipes[cid].process(fr)
            analysis_s += time.perf_counter() - t_a
            frames_analysed += 1
            written += persist_pipeline(store, obs, pipes[cid])

        if not killed and time.time() >= kill_at and args.kill:
            # Fail a subset the way a real outage does — remove the publisher,
            # not the network — and let the ingest layer discover it.
            for n in live[:args.kill]:
                httpx.delete(f"{API}/config/paths/delete/{quote(n, safe='')}",
                             timeout=8.0)
                killed.append(n)
            print(f"  [{time.strftime('%H:%M:%S')}] failed {len(killed)} cameras")

        if time.time() - last_report >= 10:
            a = mgr.aggregate()
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)
            samples.append({"t": round(time.time() - (t_end - args.seconds), 1),
                            **a, "observations": written,
                            "frames_analysed": frames_analysed,
                            "rss_mb": round(rss, 1)})
            print(f"  streaming={a['cameras_streaming']}/{a['cameras_total']} "
                  f"frames={a['frames']:,} reconnects={a['reconnects']} "
                  f"obs={written} rss={rss:.0f}MB")
            last_report = time.time()

    for cid, p in pipes.items():
        obs = p.flush()
        written += persist_pipeline(store, obs, p)
        h = mgr.stats().get(cid)
        if h:
            store.upsert_health(cid, h)

    agg = mgr.aggregate()
    per_cam = mgr.stats()
    mgr.stop_all()

    # Restore the paths we removed, so the replica is left as we found it.
    for n in killed:
        httpx.post(f"{API}/config/paths/add/{quote(n, safe='')}",
                   json={"runOnInit": publish_cmd(assignment[n], n),
                         "runOnInitRestart": True}, timeout=10.0)

    fps_each = [s.get("measured_fps") for s in per_cam.values()
                if s.get("measured_fps")]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)
    t0 = time.perf_counter()
    plates = store.distinct_plates()
    search_ms = (time.perf_counter() - t0) * 1000
    hit_ms = None
    if plates:
        t0 = time.perf_counter()
        store.search_plate(plates[0])
        hit_ms = (time.perf_counter() - t0) * 1000

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": {"platform": sys.platform, "cpus": os.cpu_count()},
        "requested_cameras": args.cameras,
        "paths_ready": len(live),
        "duration_s": args.seconds,
        "analytics_fps_per_camera": args.fps,
        "cameras_failed_mid_run": len(killed),
        "aggregate": agg,
        "observations_written": written,
        "frames_delivered_by_ingest": agg.get("frames"),
        "frames_taken_by_consumer": frames_taken,
        "frames_analysed": frames_analysed,
        "analysis_seconds": round(analysis_s, 1),
        "analysis_fps_per_process": (round(frames_analysed / analysis_s, 1)
                                     if analysis_s > 0 else None),
        "cameras_one_process_can_analyse": (
            round(frames_analysed / analysis_s / max(1.0, args.fps), 1)
            if analysis_s > 0 else None),
        "distinct_plates": len(plates),
        "peak_rss_mb": round(rss, 1),
        "plate_index_query_ms": round(hit_ms, 2) if hit_ms else None,
        "distinct_plates_query_ms": round(search_ms, 2),
        "timeline": samples,
        "measurement_note": (
            "Ingest, decode, tracking, ANPR and persistence on one machine, in "
            "ONE process. MEASURED at this scale on this host; not an "
            "extrapolation and not to be quoted as one. Ingest capacity and "
            "analytics capacity are reported separately on purpose: a single "
            "process polling N queues is the analytics bottleneck, and the "
            "architectural answer is more processes, not a faster loop."),
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2))

    print(f"\n{'':-<62}")
    print(f"cameras streaming at end : {agg['cameras_streaming']}/{agg['cameras_total']}")
    print(f"frames decoded           : {agg['frames']:,}")
    print(f"reconnects               : {agg['reconnects']}")
    print(f"decoder errors           : {agg.get('decoder_errors', 0)}")
    print(f"frames taken by consumer : {frames_taken:,}")
    print(f"frames analysed          : {frames_analysed:,}")
    if analysis_s > 0:
        rate = frames_analysed / analysis_s
        print(f"analytics throughput     : {rate:.1f} frames/s in ONE process "
              f"→ ~{rate / max(1.0, args.fps):.0f} cameras/process at "
              f"{args.fps:g} fps")
    print(f"observations written     : {written:,} ({len(plates)} distinct plates)")
    if fps_each:
        fps_each.sort()
        print(f"per-camera fps           : min {fps_each[0]:.1f}  "
              f"median {fps_each[len(fps_each)//2]:.1f}  max {fps_each[-1]:.1f}")
    print(f"peak RSS                 : {rss:.0f} MB")
    print(f"failed mid-run           : {len(killed)} "
          f"(restored: {len(killed)})")
    print(f"\nwritten: {display(args.json, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
