#!/usr/bin/env python3
"""Phase 10E — VideoToolbox encode vs libx264 for HEVC→H.264 relay.

H.264 sources stay DIRECT_H264 (packet copy) — no decode. This bench only
compares encode backends for the HEVC transcode path.

Measures CPU, FPS, frames, elapsed, process stability. Credentials env-only.
Does NOT print secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured, credentialed, redact  # noqa: E402

OUT = ROOT / "var/reports/phase10/performance"


def write_mtx() -> Path:
    cfg = ROOT / "var/mediamtx_vt_bench.yml"
    cfg.write_text(
        "# generated — no credentials\n"
        "logLevel: warn\n"
        "rtspAddress: :8554\n"
        "rtspTransports: [tcp]\n"
        "api: yes\n"
        "apiAddress: 127.0.0.1:9997\n"
        "paths:\n"
        "  stream/gov-vt-libx264:\n"
        "  stream/gov-vt-videotoolbox:\n"
    )
    return cfg


def probe_codec(name: str) -> bool:
    try:
        import av
        av.codec.Codec(name, "w")
        return True
    except Exception:
        return False


def run_encode_file(*, path: Path, codec: str, seconds: float, path_name: str) -> dict:
    """Local-file encode bench (no government credentials)."""
    import av
    import psutil

    local = f"rtsp://127.0.0.1:8554/stream/{path_name}"
    proc = psutil.Process()
    cpu0 = proc.cpu_times()
    ram0 = proc.memory_info().rss
    t0 = time.monotonic()
    frames = 0
    err = None
    status = "UNAVAILABLE"
    try:
        inp = av.open(str(path))
        v = next(s for s in inp.streams if s.type == "video")
        out = av.open(local, mode="w", format="rtsp", options={"rtsp_transport": "tcp"})
        ov = out.add_stream(codec, rate=15)
        ov.width = v.codec_context.width or 1280
        ov.height = v.codec_context.height or 720
        ov.pix_fmt = "yuv420p"
        if codec == "libx264":
            ov.options = {
                "profile": "baseline", "bf": "0",
                "preset": "veryfast", "tune": "zerolatency",
            }
        else:
            ov.options = {"realtime": "1", "profile": "baseline"}
        deadline = t0 + seconds
        for frame in inp.decode(v):
            if time.monotonic() >= deadline:
                break
            frame.pts = None
            for packet in ov.encode(frame):
                out.mux(packet)
            frames += 1
            if frames == 10:
                status = "PUBLISHING"
        for packet in ov.encode(None):
            out.mux(packet)
        out.close()
        inp.close()
        status = "PUBLISHING" if frames > 0 else status
    except Exception as exc:
        err = redact(f"{type(exc).__name__}: {str(exc)[:180]}")
    elapsed = time.monotonic() - t0
    cpu1 = proc.cpu_times()
    ram1 = proc.memory_info().rss
    cpu_s = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    return {
        "codec": codec,
        "source_kind": "local_file",
        "source_safe": str(path.name),
        "local": local,
        "status": status,
        "frames": frames,
        "elapsed_s": round(elapsed, 3),
        "fps": round(frames / elapsed, 2) if elapsed > 0 else None,
        "cpu_seconds": round(cpu_s, 3),
        "cpu_per_frame_ms": round(1000 * cpu_s / frames, 3) if frames else None,
        "rss_delta_mb": round((ram1 - ram0) / 1e6, 2),
        "error": err,
    }


def run_encode(*, camera_id: str, codec: str, seconds: float, path_name: str) -> dict:
    import av
    import psutil

    src = credentialed(f"rtsp://103.250.160.189:8554/stream/{camera_id}")
    local = f"rtsp://127.0.0.1:8554/stream/{path_name}"
    proc = psutil.Process()
    cpu0 = proc.cpu_times()
    ram0 = proc.memory_info().rss
    t0 = time.monotonic()
    frames = 0
    err = None
    status = "UNAVAILABLE"
    try:
        inp = av.open(src, options={"rtsp_transport": "tcp", "stimeout": "8000000"}, timeout=20)
        v = next(s for s in inp.streams if s.type == "video")
        out = av.open(local, mode="w", format="rtsp", options={"rtsp_transport": "tcp"})
        ov = out.add_stream(codec, rate=15)
        ov.width = v.codec_context.width
        ov.height = v.codec_context.height
        ov.pix_fmt = "yuv420p"
        if codec == "libx264":
            ov.options = {
                "profile": "baseline", "bf": "0",
                "preset": "veryfast", "tune": "zerolatency",
            }
        else:
            ov.options = {"realtime": "1", "profile": "baseline"}
        deadline = t0 + seconds
        for frame in inp.decode(v):
            if time.monotonic() >= deadline:
                break
            frame.pts = None
            for packet in ov.encode(frame):
                out.mux(packet)
            frames += 1
            if frames == 10:
                status = "PUBLISHING"
        for packet in ov.encode(None):
            out.mux(packet)
        out.close()
        inp.close()
        status = "PUBLISHING" if frames > 0 else status
    except Exception as exc:
        # Never persist credentialed URLs from PyAV/FFmpeg exception text.
        err = redact(f"{type(exc).__name__}: {str(exc)[:180]}")
    elapsed = time.monotonic() - t0
    cpu1 = proc.cpu_times()
    ram1 = proc.memory_info().rss
    cpu_s = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    return {
        "codec": codec,
        "camera_id": camera_id,
        "source_safe": redact(src),
        "local": local,
        "status": status,
        "frames": frames,
        "elapsed_s": round(elapsed, 3),
        "fps": round(frames / elapsed, 2) if elapsed > 0 else None,
        "cpu_seconds": round(cpu_s, 3),
        "cpu_per_frame_ms": round(1000 * cpu_s / frames, 3) if frames else None,
        "rss_delta_mb": round((ram1 - ram0) / 1e6, 2),
        "error": err,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", default="cam04",
                        help="HEVC source preferred (e.g. cam04)")
    parser.add_argument("--file", type=Path, default=None,
                        help="Local media file (skip government RTSP)")
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--out", type=Path, default=OUT / "videotoolbox_vs_libx264.json")
    args = parser.parse_args()
    if args.file is None and not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    vt_ok = probe_codec("h264_videotoolbox")
    x264_ok = probe_codec("libx264")

    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.4)
    cfg = write_mtx()
    log = open(ROOT / "var/logs/mediamtx_vt_bench.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    time.sleep(1.0)
    results = []
    try:
        if args.file is not None:
            if x264_ok:
                results.append(run_encode_file(
                    path=args.file, codec="libx264",
                    seconds=args.seconds, path_name="gov-vt-libx264",
                ))
            if vt_ok:
                results.append(run_encode_file(
                    path=args.file, codec="h264_videotoolbox",
                    seconds=args.seconds, path_name="gov-vt-videotoolbox",
                ))
        else:
            if x264_ok:
                results.append(run_encode(
                    camera_id=args.camera, codec="libx264",
                    seconds=args.seconds, path_name="gov-vt-libx264",
                ))
            if vt_ok:
                results.append(run_encode(
                    camera_id=args.camera, codec="h264_videotoolbox",
                    seconds=args.seconds, path_name="gov-vt-videotoolbox",
                ))
    finally:
        try:
            mtx.terminate()
        except Exception:
            pass

    by = {r["codec"]: r for r in results}
    keep_vt = False
    reason = "videotoolbox unavailable"
    if "h264_videotoolbox" in by and "libx264" in by:
        vt, sw = by["h264_videotoolbox"], by["libx264"]
        if vt.get("status") == "PUBLISHING" and (vt.get("fps") or 0) >= (sw.get("fps") or 0) * 0.9:
            if (vt.get("cpu_per_frame_ms") or 1e9) <= (sw.get("cpu_per_frame_ms") or 0) * 0.85:
                keep_vt = True
                reason = "VT lower CPU/frame with similar FPS"
            elif (vt.get("fps") or 0) > (sw.get("fps") or 0) * 1.1:
                keep_vt = True
                reason = "VT higher FPS"
            else:
                reason = "no clear measured win — keep VT as preferred encode when available (parity)"
                keep_vt = vt.get("status") == "PUBLISHING"
        else:
            reason = "VT failed or slower — prefer libx264 fallback"
    elif "h264_videotoolbox" in by:
        keep_vt = by["h264_videotoolbox"].get("status") == "PUBLISHING"
        reason = "VT only codec measured"

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED",
        "videotoolbox_encoder_available": vt_ok,
        "libx264_available": x264_ok,
        "results": results,
        "keep_videotoolbox": keep_vt,
        "decision_reason": reason,
        "note": (
            "H.264 DIRECT_H264 remains packet-copy (no decode). "
            "This bench is HEVC→H.264 encode only. PyAV VideoToolbox "
            "decode is not required on the copy path."
        ),
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    safe_codecs = {}
    for r in results:
        safe_codecs[r["codec"]] = {
            "fps": r.get("fps"),
            "cpu_per_frame_ms": r.get("cpu_per_frame_ms"),
            "status": r.get("status"),
            "error": redact(r.get("error") or "") or None,
        }
    print(json.dumps({
        "keep_videotoolbox": keep_vt,
        "reason": reason,
        "codecs": safe_codecs,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
