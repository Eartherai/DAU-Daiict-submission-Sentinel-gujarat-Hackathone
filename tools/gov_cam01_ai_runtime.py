#!/usr/bin/env python3
"""Phase A: AI-off vs AI-on runtime on government cam01 managed path.

Architecture preserved:

  Government RTSP → PyAV relay → MediaMTX
       ├─ WHEP → Chromium (browser playback measurement)
       └─ local RTSP → CameraPipeline (AI, independent process)

Credentials stay in SENTINEL_GRID_* env only. AI never touches browser playback.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig  # noqa: E402
from saakshya.ingest.frame import Frame  # noqa: E402
from saakshya.live.credentials import configured  # noqa: E402
from saakshya.runtime.inference_scheduler import (  # noqa: E402
    AdaptiveInferenceScheduler,
    InferenceMode,
    SchedulerPolicy,
)
from tools.test_whep_camera import measure  # noqa: E402

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


MODES = (
    "VIDEO_ONLY",
    "DETECTION",
    "DETECTION_TRACKER",
    "DETECTION_TRACKER_OCR",
    "FULL",
)


@dataclass
class ModeConfig:
    name: str
    run_ai: bool
    enable_vehicle: bool = True
    enable_motion: bool = True
    enable_person: bool = False
    ocr_every: int = 10**9  # never
    infer_every: int = 2
    sample_every: int = 2
    mode: InferenceMode = InferenceMode.NORMAL


MODE_CONFIGS: dict[str, ModeConfig] = {
    "VIDEO_ONLY": ModeConfig("VIDEO_ONLY", run_ai=False),
    "DETECTION": ModeConfig(
        "DETECTION", True, enable_vehicle=True, enable_motion=True,
        ocr_every=10**9, infer_every=2, sample_every=2),
    "DETECTION_TRACKER": ModeConfig(
        "DETECTION_TRACKER", True, enable_vehicle=True, enable_motion=True,
        ocr_every=10**9, infer_every=1, sample_every=1),
    "DETECTION_TRACKER_OCR": ModeConfig(
        "DETECTION_TRACKER_OCR", True, enable_vehicle=True, enable_motion=True,
        ocr_every=4, infer_every=2, sample_every=2),
    "FULL": ModeConfig(
        "FULL", True, enable_vehicle=True, enable_motion=True,
        enable_person=True, ocr_every=2, infer_every=1, sample_every=1,
        mode=InferenceMode.HIGH_PRIORITY),
}


def _api(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:9997{path}", timeout=3) as r:
        return json.load(r)


def _rss_mb() -> float | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux KiB — normalize heuristically.
        return round(usage / (1024 * 1024) if usage > 10_000_000 else usage / 1024, 1)
    except Exception:
        return None


def _sample_process(pid: int) -> dict[str, Any]:
    if psutil is None:
        return {"cpu_percent": None, "rss_mb": None, "note": "psutil unavailable"}
    try:
        p = psutil.Process(pid)
        return {
            "cpu_percent": p.cpu_percent(interval=0.2),
            "rss_mb": round(p.memory_info().rss / (1024 * 1024), 1),
        }
    except Exception as exc:
        return {"cpu_percent": None, "rss_mb": None, "error": type(exc).__name__}


def run_ai_worker(
    local_rtsp: str,
    mode_cfg: ModeConfig,
    seconds: float,
    out_queue: list[dict[str, Any]],
) -> None:
    """Consume local MediaMTX RTSP and run CameraPipeline. Never opens gov auth URL."""
    result: dict[str, Any] = {
        "mode": mode_cfg.name,
        "status": "UNAVAILABLE",
        "frames_in": 0,
        "frames_analysed": 0,
        "detections": 0,
        "tracks_created": 0,
        "observations": 0,
        "errors": 0,
        "pipeline_ms": [],
        "elapsed_s": None,
        "rss_mb_end": None,
    }
    if not mode_cfg.run_ai:
        result["status"] = "SKIPPED"
        out_queue.append(result)
        return

    started = time.perf_counter()
    container = None
    try:
        scheduler = AdaptiveInferenceScheduler(
            mode_cfg.mode,
            policy={
                mode_cfg.mode: SchedulerPolicy(
                    sample_every=mode_cfg.sample_every,
                    infer_every=mode_cfg.infer_every,
                    ocr_every=mode_cfg.ocr_every,
                    reid_every=max(mode_cfg.ocr_every, 12),
                )
            },
        )
        cfg = PipelineConfig(
            enable_vehicle_detector=mode_cfg.enable_vehicle,
            enable_motion=mode_cfg.enable_motion,
            enable_person_detector=mode_cfg.enable_person,
            validate_models=True,
            inference_scheduler=scheduler,
        )
        pipeline = CameraPipeline("cam01", cfg)
        container = av.open(
            local_rtsp,
            options={"rtsp_transport": "tcp", "stimeout": "8000000"},
            timeout=20,
        )
        stream = next(s for s in container.streams if s.type == "video")
        tb = float(stream.time_base) if stream.time_base else (1 / 25)
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                raw = next(container.decode(stream))
            except (StopIteration, av.AVError, Exception):
                try:
                    container.close()
                except Exception:
                    pass
                time.sleep(1.0)
                try:
                    container = av.open(
                        local_rtsp,
                        options={"rtsp_transport": "tcp", "stimeout": "8000000"},
                        timeout=20,
                    )
                    stream = next(s for s in container.streams if s.type == "video")
                    tb = float(stream.time_base) if stream.time_base else tb
                except Exception:
                    time.sleep(2.0)
                continue
            if raw.pts is None:
                continue
            pts = float(raw.pts) * tb
            image = raw.to_ndarray(format="bgr24")
            frame = Frame(
                camera_id="cam01", segment_id="AI_RUNTIME",
                pts_s=pts,
                t_norm=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=pts),
                t_ingest=datetime.now(UTC), image=image,
                width=image.shape[1], height=image.shape[0], codec="h264",
            )
            t0 = time.perf_counter()
            try:
                pipeline.process(frame)
                result["pipeline_ms"].append((time.perf_counter() - t0) * 1000)
            except Exception:
                result["errors"] += 1
        try:
            pipeline.flush()
        except Exception:
            result["errors"] += 1
        stats = pipeline.stats
        result.update({
            "status": "MEASURED",
            "frames_in": stats.frames_in,
            "frames_analysed": stats.frames_analysed,
            "detections": (stats.vehicle_detections + stats.motion_detections
                           + stats.plate_detections),
            "tracks_created": stats.tracks_created,
            "observations": stats.observations_emitted,
            "plate_detections": stats.plate_detections,
            "vehicle_detections": stats.vehicle_detections,
        })
    except Exception as exc:
        result["status"] = "FAIL"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        result["elapsed_s"] = round(time.perf_counter() - started, 3)
        result["rss_mb_end"] = _rss_mb()
        ms = result.pop("pipeline_ms")
        if ms:
            ms_sorted = sorted(ms)
            result["pipeline_latency"] = {
                "samples": len(ms),
                "p50_ms": round(ms_sorted[len(ms_sorted) // 2], 2),
                "p95_ms": round(ms_sorted[min(len(ms_sorted) - 1, int(len(ms_sorted) * 0.95))], 2),
                "mean_ms": round(sum(ms) / len(ms), 2),
            }
        else:
            result["pipeline_latency"] = None
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
        out_queue.append(result)


def ensure_relay(seconds: float) -> tuple[subprocess.Popen, subprocess.Popen]:
    """Start MediaMTX + cam01 publisher for long enough to cover all modes."""
    pub_log = open(ROOT / "var/logs/gov_cam01_ai_runtime_pub.log", "w")
    from tools.gov_whep_relay import ensure_mediamtx, write_config, _child_env
    cfg = write_config("cam01")
    mtx = ensure_mediamtx(cfg)
    pub = subprocess.Popen(
        [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), "cam01",
         "--seconds", str(seconds), "--publish-only"],
        cwd=str(ROOT), env=_child_env(), stdout=pub_log, stderr=subprocess.STDOUT,
    )
    for i in range(40):
        time.sleep(1)
        if pub.poll() is not None:
            raise RuntimeError(f"publisher exited early rc={pub.returncode}")
        try:
            d = _api("/v3/paths/get/stream/gov-cam01")
            if d.get("ready") and (d.get("bytesReceived") or 0) > 20000:
                print(f"relay ready t={i+1}s bytes={d.get('bytesReceived')}")
                return mtx, pub
        except Exception:
            pass
    raise RuntimeError("gov-cam01 path not ready")


def run_mode(mode: str, seconds: float) -> dict[str, Any]:
    cfg = MODE_CONFIGS[mode]
    endpoint = "http://127.0.0.1:8889/stream/gov-cam01/whep"
    local_rtsp = "rtsp://127.0.0.1:8554/stream/gov-cam01"
    ai_box: list[dict[str, Any]] = []
    ai_thread = None
    if cfg.run_ai:
        ai_thread = threading.Thread(
            target=run_ai_worker,
            args=(local_rtsp, cfg, seconds + 5, ai_box),
            daemon=True,
        )
        ai_thread.start()
        time.sleep(2.0)  # let AI attach before browser soak

    out_json = ROOT / f"var/reports/phase8c/gov/cam01_ai_{mode.lower()}_whep.json"
    out_png = ROOT / f"var/reports/phase8c/gov/cam01_ai_{mode.lower()}_whep.png"
    whep = measure(endpoint, seconds=seconds, screenshot=out_png)
    blob = json.dumps(whep)
    if "@" in blob:
        raise RuntimeError("refusing credential-like WHEP report content")
    out_json.write_text(json.dumps(whep, indent=2) + "\n")

    if ai_thread is not None:
        ai_thread.join(timeout=seconds + 30)

    ai = ai_box[0] if ai_box else {"status": "SKIPPED", "mode": mode}
    summary = whep.get("summary") or {}
    verdict = "FAIL"
    if whep.get("status") == "MEASURED" and (summary.get("currentTime") or 0) > seconds * 0.5:
        if (summary.get("freezes") or 0) <= 2 and (summary.get("packetsLost_end") or 0) == 0:
            verdict = "PASS"
        else:
            verdict = "AMBER"
    elif whep.get("status") == "MEASURED":
        verdict = "AMBER"

    return {
        "mode": mode,
        "verdict": verdict,
        "duration_s": seconds,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "browser": {
            "status": whep.get("status"),
            "summary": summary,
            "artifact_json": str(out_json.relative_to(ROOT)),
            "artifact_png": str(out_png.relative_to(ROOT)) if out_png.exists() else None,
            "error": whep.get("error"),
        },
        "ai": ai,
        "resources": {
            "parent_rss_mb": _rss_mb(),
            "note": "AI and browser are separate consumers of the same MediaMTX fanout",
        },
    }


def write_report(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Government cam01 AI runtime certification",
        "",
        f"Measured UTC: {datetime.now(UTC).isoformat()}",
        "",
        "Path: Government RTSP → PyAV relay → MediaMTX → (WHEP browser ‖ local RTSP AI)",
        "",
        "Camera: **cam01** (GOLDEN). Credentials: environment only.",
        "",
        "| Mode | Verdict | browser currentTime | freezes | pkt loss | AI status | AI frames | pipeline p50 ms |",
        "|---|---|---:|---:|---:|---|---:|---:|",
    ]
    for r in results:
        b = (r.get("browser") or {}).get("summary") or {}
        ai = r.get("ai") or {}
        lat = ai.get("pipeline_latency") or {}
        lines.append(
            f"| {r['mode']} | **{r['verdict']}** | {b.get('currentTime')} | "
            f"{b.get('freezes')} | {b.get('packetsLost_end')} | {ai.get('status')} | "
            f"{ai.get('frames_analysed')} | {lat.get('p50_ms')} |"
        )
    lines.extend([
        "",
        "## Acceptance",
        "",
        "- Browser path remains alive with AI enabled on the same gateway fanout.",
        "- AI does not crash the browser measurement process.",
        "- No credentials in artifacts (secret scan required after run).",
        "",
        "## Machine-readable",
        "",
        "`var/reports/phase8c/gov/cam01_ai_runtime.json`",
        "",
    ])
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    args = parser.parse_args()
    if not configured():
        print("SENTINEL_GRID credentials not configured", file=sys.stderr)
        return 2

    (ROOT / "var/reports/phase8c/gov").mkdir(parents=True, exist_ok=True)
    (ROOT / "var/logs").mkdir(parents=True, exist_ok=True)

    # One long relay covering all modes with buffer.
    total = args.seconds * len(args.modes) + 90
    mtx = pub = None
    try:
        mtx, pub = ensure_relay(total)
        results = []
        for mode in args.modes:
            print(f"==== MODE {mode} ====", flush=True)
            results.append(run_mode(mode, args.seconds))
            print(json.dumps({
                "mode": mode,
                "verdict": results[-1]["verdict"],
                "browser_t": (results[-1]["browser"].get("summary") or {}).get("currentTime"),
                "ai": results[-1]["ai"].get("status"),
            }), flush=True)
        out = ROOT / "var/reports/phase8c/gov/cam01_ai_runtime.json"
        payload = {
            "camera_id": "cam01",
            "path": "DIRECT_H264 managed gateway",
            "seconds_per_mode": args.seconds,
            "modes": results,
        }
        text = json.dumps(payload, indent=2) + "\n"
        if "@" in text:
            raise RuntimeError("secret-like content in runtime report")
        out.write_text(text)
        write_report(results, ROOT / "reports/GOV_CAM01_AI_RUNTIME_CERTIFICATION.md")
        print("wrote", out)
        return 0 if all(r["verdict"] in {"PASS", "AMBER"} for r in results) else 4
    finally:
        if pub is not None and pub.poll() is None:
            pub.terminate()
        if mtx is not None:
            try:
                mtx.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
