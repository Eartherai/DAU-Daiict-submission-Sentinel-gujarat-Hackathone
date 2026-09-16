#!/usr/bin/env python3
"""Publish multiple government cameras into one MediaMTX and run multi-WHEP soaks.

Credentials stay in SENTINEL_GRID_* env vars. Never written to config or reports.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402
from saakshya.live.path_selector import (  # noqa: E402
    CameraStreamProfile,
    StreamPath,
    StreamPathSelector,
)


def _api(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:9997{path}", timeout=3) as r:
        return json.load(r)


def path_snapshot(cam: str) -> dict:
    try:
        d = _api(f"/v3/paths/get/stream/gov-{cam}")
        return {
            "ready": bool(d.get("ready")),
            "bytesReceived": int(d.get("bytesReceived") or 0),
            "online": bool(d.get("online") or d.get("ready")),
        }
    except Exception as exc:
        return {"ready": False, "bytesReceived": 0, "online": False,
                "error": type(exc).__name__}


def write_config(camera_ids: list[str], *, transcode: set[str]) -> Path:
    lines = [
        "# generated — no credentials",
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
        "apiAllowOrigins: [\"*\"]",
        "paths:",
    ]
    for cam in camera_ids:
        lines.append(f"  stream/gov-{cam}:")
    dst = ROOT / "var" / "mediamtx_gov_multi.yml"
    dst.write_text("\n".join(lines) + "\n")
    return dst


def child_env() -> dict[str, str]:
    keep = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
        "VIRTUAL_ENV", "PYTHONPATH", "PYTHONUNBUFFERED",
        "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
    }
    return {k: v for k, v in os.environ.items() if k in keep}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cameras", nargs="+")
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--whep-seconds", type=float, default=30)
    parser.add_argument("--transcode", nargs="*", default=[],
                        help="camera ids that must HEVC→H264 transcode")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "var/reports/phase8c/gov/wall_results.json")
    parser.add_argument(
        "--whep-cameras", nargs="*", default=None,
        help="subset to browser-measure (default: all). Others stay publish-only.",
    )
    args = parser.parse_args()
    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    transcode = set(args.transcode)
    selector = StreamPathSelector()
    decisions = []
    for cam in args.cameras:
        codec = "hevc" if cam in transcode else "h264"
        decisions.append(selector.select(CameraStreamProfile(
            cam, codec=codec,
            browser_hevc_supported=False,
            has_b_frames=False,
            whep_stable=True,
        )).to_dict())

    cfg = write_config(args.cameras, transcode=transcode)
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.5)
    (ROOT / "var/logs").mkdir(parents=True, exist_ok=True)
    log = open(ROOT / "var/logs/mediamtx_gov_multi.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        time.sleep(0.25)
        try:
            _api("/v3/paths/list")
            break
        except Exception:
            if mtx.poll() is not None:
                raise SystemExit("MediaMTX failed to start")

    pubs: list[subprocess.Popen] = []
    whep_cams = list(args.whep_cameras) if args.whep_cameras else list(args.cameras)
    try:
        # Publishers must outlive wait-for-ready + sequential WHEP soaks.
        # Prior hang: pubs exited while Chromium was still measuring later tiles.
        pub_seconds = (
            float(args.seconds)
            + 60.0
            + (float(args.whep_seconds) + 25.0) * max(1, len(whep_cams))
            + 60.0
        )
        for cam in args.cameras:
            cmd = [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), cam,
                   "--seconds", str(pub_seconds),
                   "--publish-only"]
            if cam in transcode:
                cmd.append("--transcode")
            pubs.append(subprocess.Popen(cmd, cwd=str(ROOT), env=child_env()))

        # Wait until all paths ready (or timeout)
        pending = set(args.cameras)
        for i in range(int(args.seconds) + 20):
            time.sleep(1)
            for cam in list(pending):
                try:
                    d = _api(f"/v3/paths/get/stream/gov-{cam}")
                    if d.get("ready") and (d.get("bytesReceived") or 0) > 15000:
                        print(f"ready {cam} t={i+1} bytes={d.get('bytesReceived')}",
                              flush=True)
                        pending.discard(cam)
                except Exception:
                    pass
            if not pending:
                break
            dead = [p.returncode for p in pubs if p.poll() is not None]
            if dead and pending:
                print("publisher exited while waiting", dead, flush=True)
        publishing = {cam: path_snapshot(cam) for cam in args.cameras}
        if pending:
            print("not ready", sorted(pending), flush=True)
            # Continue: measure whatever is ready; record others UNAVAILABLE.

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        from tools.test_whep_camera import measure
        results = {
            "decisions": decisions,
            "registered": list(args.cameras),
            "whep_cameras": whep_cams,
            "publishing": publishing,
            "cameras": {},
        }
        # Sequential browser soaks against concurrent publishers (one Chromium
        # at a time keeps the measurement honest per camera).
        for cam in whep_cams:
            snap = path_snapshot(cam)
            if not snap.get("ready"):
                results["cameras"][cam] = {
                    "status": "UNAVAILABLE",
                    "summary": None,
                    "error": f"path not ready before WHEP: {snap}",
                }
                print(cam, "UNAVAILABLE", snap, flush=True)
                continue
            endpoint = f"http://127.0.0.1:8889/stream/gov-{cam}/whep"
            png = ROOT / f"var/reports/phase8c/gov/wall_{cam}_whep.png"
            hard_timeout = float(args.whep_seconds) + 45.0
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        measure, endpoint, seconds=args.whep_seconds, screenshot=png)
                    report = fut.result(timeout=hard_timeout)
            except FuturesTimeout:
                report = {
                    "status": "UNAVAILABLE",
                    "summary": None,
                    "error": f"measure timed out after {hard_timeout}s",
                }
            except Exception as exc:
                report = {
                    "status": "UNAVAILABLE",
                    "summary": None,
                    "error": f"{type(exc).__name__}: {exc}"[:240],
                }
            blob = json.dumps(report)
            if "@" in blob:
                raise RuntimeError("secret-like content in report")
            (ROOT / f"var/reports/phase8c/gov/wall_{cam}_whep.json").write_text(
                json.dumps(report, indent=2) + "\n")
            results["cameras"][cam] = {
                "status": report.get("status"),
                "summary": report.get("summary"),
                "error": report.get("error"),
            }
            print(cam, report.get("status"), report.get("summary"), flush=True)

        # Non-WHEP registered cameras: publish-only evidence
        for cam in args.cameras:
            if cam in results["cameras"]:
                continue
            snap = publishing.get(cam) or path_snapshot(cam)
            results["cameras"][cam] = {
                "status": "PUBLISH_ONLY",
                "summary": snap,
                "error": None,
            }

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2) + "\n")
        print("wrote", args.out, flush=True)
        measured = [v for c, v in results["cameras"].items() if c in whep_cams]
        ok = measured and all(v.get("status") == "MEASURED" for v in measured)
        return 0 if ok else 4
    finally:
        for p in pubs:
            if p.poll() is None:
                p.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
