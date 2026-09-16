#!/usr/bin/env python3
"""Relay one government RTSP camera into local MediaMTX without writing secrets.

Credentials come from SENTINEL_GRID_* env vars and are injected only when
opening the government RTSP input in-process via PyAV. They are never written
to YAML/JSON/reports and are not passed to an ffmpeg child argv.

Usage:
  export SENTINEL_GRID_EMAIL=...
  export SENTINEL_GRID_PASSWORD=...
  python tools/gov_whep_relay.py cam01 --seconds 25 --whep-test
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

from saakshya.live.credentials import configured, credentialed, redact  # noqa: E402


def _api(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:9997{path}", timeout=3) as r:
        return json.load(r)


def write_config(camera_id: str) -> Path:
    path_name = f"stream/gov-{camera_id}"
    cfg = f"""# generated — no credentials
logLevel: warn
rtspAddress: :8554
rtspTransports: [tcp]
hlsAddress: :8888
hlsAlwaysRemux: yes
hlsAllowOrigins: ["*"]
webrtcAddress: :8889
webrtcAllowOrigins: ["*"]
api: yes
apiAddress: 127.0.0.1:9997
apiAllowOrigins: ["*"]
paths:
  {path_name}:
"""
    dst = ROOT / "var" / "mediamtx_gov.yml"
    dst.write_text(cfg)
    return dst


def ensure_mediamtx(config: Path) -> subprocess.Popen:
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.5)
    (ROOT / "var/logs").mkdir(parents=True, exist_ok=True)
    log = open(ROOT / "var/logs/mediamtx_gov.log", "ab")
    proc = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(config)],
        cwd=str(ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(30):
        time.sleep(0.4)
        try:
            _api("/v3/paths/list")
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("MediaMTX exited during startup")
    raise RuntimeError("MediaMTX API did not become ready")


def publish_copy(camera_id: str, *, seconds: float,
                 transcode_h264: bool = False) -> dict:
    """Open government RTSP in-process and republish to local MediaMTX.

    Reconnects for the full ``seconds`` window when the upstream demux ends
    early (common intermittent government session behaviour).
    """
    import av

    src = credentialed(
        f"rtsp://103.250.160.189:8554/stream/{camera_id}", required=True)
    local = f"rtsp://127.0.0.1:8554/stream/gov-{camera_id}"
    report = {
        "camera_id": camera_id,
        "source": redact(src),
        "local": local,
        "status": "UNAVAILABLE",
        "frames": 0,
        "reconnects": 0,
        "transcode_h264": transcode_h264,
        "error": None,
    }
    print(f"relay {redact(src)} -> {local} transcode={transcode_h264}", flush=True)
    started = time.monotonic()
    frames = 0
    deadline = started + max(seconds, 1.0)
    backoff = 2.0
    try:
        while time.monotonic() < deadline:
            inp = None
            out = None
            try:
                inp = av.open(
                    src,
                    options={"rtsp_transport": "tcp", "stimeout": "8000000"},
                    timeout=20,
                )
                v = next(s for s in inp.streams if s.type == "video")
                out = av.open(local, mode="w", format="rtsp",
                              options={"rtsp_transport": "tcp"})
                if transcode_h264:
                    # Prefer VideoToolbox encode on Apple Silicon when available.
                    codec_name = "libx264"
                    try:
                        av.codec.Codec("h264_videotoolbox", "w")
                        codec_name = "h264_videotoolbox"
                    except Exception:
                        pass
                    ov = out.add_stream(codec_name, rate=15)
                    ov.width = v.codec_context.width
                    ov.height = v.codec_context.height
                    ov.pix_fmt = "yuv420p"
                    if codec_name == "libx264":
                        ov.options = {
                            "profile": "baseline",
                            "bf": "0",
                            "preset": "veryfast",
                            "tune": "zerolatency",
                        }
                    else:
                        # VT path — keep B-frames off for WebRTC
                        ov.options = {"realtime": "1", "profile": "baseline"}
                    report["encode_codec"] = codec_name
                    for frame in inp.decode(v):
                        if time.monotonic() >= deadline:
                            break
                        frame.pts = None
                        for packet in ov.encode(frame):
                            out.mux(packet)
                        frames += 1
                        if frames == 30:
                            report["status"] = "PUBLISHING"
                    for packet in ov.encode(None):
                        out.mux(packet)
                else:
                    ov = out.add_stream_from_template(v)
                    for packet in inp.demux(v):
                        if time.monotonic() >= deadline:
                            break
                        if packet.dts is None:
                            continue
                        packet.stream = ov
                        out.mux(packet)
                        frames += 1
                        if frames == 30:
                            report["status"] = "PUBLISHING"
                backoff = 2.0
            except Exception as exc:
                report["error"] = redact(
                    f"{type(exc).__name__}: {str(exc)[:200]}"
                )
                report["reconnects"] += 1
                time.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            finally:
                if out is not None:
                    try:
                        out.close()
                    except Exception:
                        pass
                if inp is not None:
                    try:
                        inp.close()
                    except Exception:
                        pass
            # Upstream ended before deadline — reconnect with backoff.
            if time.monotonic() < deadline:
                report["reconnects"] += 1
                time.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
        if frames > 0 and report["status"] == "UNAVAILABLE":
            report["status"] = "PUBLISHING"
        if frames > 0:
            report["status"] = "PUBLISHING"
            report["error"] = None
    finally:
        report["frames"] = frames
        report["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    return report


def _child_env() -> dict[str, str]:
    keep = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
        "VIRTUAL_ENV", "PYTHONPATH", "PYTHONUNBUFFERED",
        "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
    }
    return {k: v for k, v in os.environ.items() if k in keep}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("camera_id", nargs="?", default="cam01")
    parser.add_argument("--seconds", type=float, default=25.0)
    parser.add_argument("--whep-test", action="store_true")
    parser.add_argument("--whep-seconds", type=float, default=12.0)
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--transcode", action="store_true",
                        help="HEVC/B-frame unsafe → baseline H.264 before WHEP")
    args = parser.parse_args()

    if args.publish_only:
        if not configured():
            print("credentials not configured", file=sys.stderr)
            return 2
        report = publish_copy(
            args.camera_id, seconds=args.seconds,
            transcode_h264=args.transcode)
        safe = {k: v for k, v in report.items()}
        if safe.get("error"):
            safe["error"] = redact(str(safe["error"]))
        if safe.get("source"):
            safe["source"] = redact(str(safe["source"]))
        print(json.dumps(safe))
        return 0 if report["frames"] > 0 else 1

    if not configured():
        print("SENTINEL_GRID_EMAIL/PASSWORD not configured", file=sys.stderr)
        return 2

    (ROOT / "var/reports/phase8c/gov").mkdir(parents=True, exist_ok=True)
    cfg = write_config(args.camera_id)
    mtx = ensure_mediamtx(cfg)
    pub = None
    try:
        pub_cmd = [sys.executable, str(Path(__file__)), args.camera_id,
                   "--seconds", str(args.seconds), "--publish-only"]
        if args.transcode:
            pub_cmd.append("--transcode")
        pub_log = open(
            ROOT / f"var/logs/gov_{args.camera_id}_publisher.log", "w")
        pub = subprocess.Popen(
            pub_cmd,
            cwd=str(ROOT),
            env=_child_env(),
            stdout=pub_log,
            stderr=subprocess.STDOUT,
        )
        ready = False
        for i in range(int(args.seconds) + 15):
            time.sleep(1)
            if pub.poll() is not None:
                print("publisher exited early", pub.returncode)
                break
            try:
                d = _api(f"/v3/paths/get/stream/gov-{args.camera_id}")
                print(
                    f"t={i+1} ready={d.get('ready')} "
                    f"bytes={d.get('bytesReceived')}"
                )
                if d.get("ready") and (d.get("bytesReceived") or 0) > 20000:
                    ready = True
                    break
            except Exception as exc:
                print(f"t={i+1} api {type(exc).__name__}")
        if not ready:
            print("path not ready")
            return 3
        if args.whep_test:
            sys.path.insert(0, str(ROOT))
            from tools.test_whep_camera import measure
            endpoint = (
                f"http://127.0.0.1:8889/stream/gov-{args.camera_id}/whep"
            )
            out_json = (
                ROOT / f"var/reports/phase8c/gov/{args.camera_id}_whep.json"
            )
            out_png = (
                ROOT / f"var/reports/phase8c/gov/{args.camera_id}_whep.png"
            )
            report = measure(
                endpoint, seconds=args.whep_seconds, screenshot=out_png)
            blob = json.dumps(report)
            if "@" in blob:
                raise RuntimeError("refusing to persist credential-like content")
            out_json.write_text(json.dumps(report, indent=2) + "\n")
            video = report.get("video") or {}
            print(
                "whep_status", report.get("status"),
                "luma", video.get("canvasMeanLuma"),
                "t", video.get("currentTime"),
                "size", f"{video.get('width')}x{video.get('height')}",
            )
            return 0 if report.get("status") == "MEASURED" else 4
        if pub.poll() is None:
            pub.wait(timeout=max(args.seconds, 1))
        return 0
    finally:
        if pub is not None and pub.poll() is None:
            pub.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
