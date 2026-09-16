#!/usr/bin/env python3
"""Synthetic multi-stream WHEP scale (browser ceiling isolation).

Publishes N looped local H.264 files into MediaMTX and runs the headed
Metal WHEP session scheduler. Label: SYNTHETIC — not government cameras.

Used when government RTSP auth is unavailable, and for 50-logical scale.
Credentials are not required.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tools.perf_whep_session_scheduler import (  # noqa: E402
    measure_wall, summarize, write_mtx_config, api, stop_all,
)

OUT = ROOT / "var/reports/phase10/performance"


def find_ffmpeg() -> str:
    for p in (ROOT / "var/bin/ffmpeg", Path("/opt/homebrew/bin/ffmpeg"),
              Path("/usr/local/bin/ffmpeg")):
        if p.exists():
            return str(p)
    return "ffmpeg"


def media_files(n: int) -> list[Path]:
    clips = sorted((ROOT / "var/demo/live_clips").glob("cam*.mp4"))
    media = sorted((ROOT / "var/media").glob("C-*.mp4"))
    media = [p for p in media if "bframes" not in p.name]
    pool = []
    for p in clips + media:
        # Skip files corrupted / non-openable (e.g. accidental text scrub)
        try:
            import av
            inp = av.open(str(p))
            next(s for s in inp.streams if s.type == "video")
            inp.close()
            pool.append(p)
        except Exception:
            continue
    if not pool:
        raise SystemExit("no local media files for synthetic publish")
    out = []
    i = 0
    while len(out) < n:
        out.append(pool[i % len(pool)])
        i += 1
    return out


def start_synthetic(n: int, seconds: float):
    cams = [f"syn{i:02d}" for i in range(1, n + 1)]
    files = media_files(n)
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.4)
    cfg = write_mtx_config(cams)
    # rewrite paths for syn*
    lines = [
        "# generated — synthetic — no credentials",
        "logLevel: warn",
        "rtspAddress: :8554",
        "rtspTransports: [tcp]",
        "hlsAddress: :8888",
        "hlsAlwaysRemux: yes",
        "hlsAllowOrigins: [\"*\"]",
        "webrtcAddress: :8889",
        "webrtcAllowOrigins: [\"*\"]",
        "api: yes",
        "apiAddress: 127.0.0.1:9997",
        "paths:",
    ]
    for cam in cams:
        lines.append(f"  stream/gov-{cam}:")
    cfg.write_text("\n".join(lines) + "\n")
    log = open(ROOT / "var/logs/mediamtx_synthetic.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        time.sleep(0.25)
        try:
            api("/v3/paths/list")
            break
        except Exception:
            if mtx.poll() is not None:
                raise SystemExit("MediaMTX failed")
    ff = find_ffmpeg()
    pubs = []
    for cam, src in zip(cams, files):
        dst = f"rtsp://127.0.0.1:8554/stream/gov-{cam}"
        cmd = [
            ff, "-hide_banner", "-loglevel", "error",
            "-re", "-stream_loop", "-1", "-i", str(src),
            "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp", dst,
        ]
        pubs.append(subprocess.Popen(cmd, cwd=str(ROOT)))
    # wait ready
    pending = set(cams)
    for i in range(60):
        time.sleep(1)
        for cam in list(pending):
            try:
                d = api(f"/v3/paths/get/stream/gov-{cam}")
                if d.get("ready") and (d.get("bytesReceived") or 0) > 8000:
                    pending.discard(cam)
                    print(f"ready {cam} t={i+1}", flush=True)
            except Exception:
                pass
        if not pending:
            break
    if pending:
        print("not_ready", sorted(pending), flush=True)
    return cams, mtx, pubs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=16)
    parser.add_argument("--negotiate-concurrency", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    cams, mtx, pubs = start_synthetic(args.n, args.seconds + 90)
    try:
        endpoints = [f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in cams]
        wall = measure_wall(
            endpoints, seconds=args.seconds,
            negotiate_concurrency=args.negotiate_concurrency, retries=1,
        )
        row = summarize(cams, wall, seconds=args.seconds,
                        negotiate_concurrency=args.negotiate_concurrency)
        row["source"] = "SYNTHETIC_LOCAL_FILES"
        row["label"] = "MEASURED_SYNTHETIC"
    finally:
        stop_all(mtx, pubs)
        for p in pubs:
            if p.poll() is None:
                p.kill()

    out = args.out or (OUT / f"synthetic_scale_n{args.n}.json")
    out.write_text(json.dumps(row, indent=2) + "\n")
    print(json.dumps({
        "n": args.n,
        "overall": row["overall"],
        "wall_summary": row["wall_summary"],
        "source": "SYNTHETIC",
        "out": str(out),
    }))
    return 0 if row["overall"] != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
