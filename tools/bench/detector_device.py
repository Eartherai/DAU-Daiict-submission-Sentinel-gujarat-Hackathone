#!/usr/bin/env python3
"""CPU against Apple GPU (MPS) for the production detector, on real frames.

The live worker and the media hub set SAAKSHYA_FORCE_CPU=1 by default, so the
detector ran on CPU while the M-series GPU sat idle. No reason was recorded
for it. The backend's own comment claims MPS is 3.5x faster; a claim in a
comment is not a measurement, and a faster device that returns different
boxes is not an improvement. This measures both, on the same decoded frames:

* time per frame (median and p95), after a warm-up the timing excludes;
* parity: for each frame, every CPU detection above the pipeline's vehicle
  and person thresholds is matched to an MPS detection of the same label at
  IoU >= 0.9; the unmatched share on either side is reported.

    python tools/bench/detector_device.py --camera OWN-MUM-QUEUE --frames 90

writes var/reports/detector_device.json. Each device runs in its own process,
because the backend picks its device once, at load.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
KEEP = {"car", "truck", "bus", "motorcycle", "bicycle", "person"}


def _frames(camera: str, n: int, stride: int):
    import av
    out = []
    with av.open(str(ROOT / "var" / "media" / f"{camera}.mp4")) as c:
        for i, vf in enumerate(c.decode(video=0)):
            if i % stride == 0:
                out.append(vf.to_ndarray(format="bgr24"))
            if len(out) >= n:
                break
    return out


def run_one(camera: str, n: int, stride: int, warmup: int) -> dict:
    """Runs in a child process with the device already chosen by env."""
    from saakshya.analytics.pipeline import PipelineConfig
    from saakshya.models.registry import get
    from saakshya.runtime.backend import BACKENDS, quiet_transformers

    quiet_transformers()
    rec = get(PipelineConfig().vehicle_detector_key)
    be = BACKENDS.get(rec)
    frames = _frames(camera, n + warmup, stride)
    for f in frames[:warmup]:
        be.detect(f)
    times, dets = [], []
    for f in frames[warmup:]:
        t0 = time.perf_counter()
        ds = be.detect(f)
        times.append((time.perf_counter() - t0) * 1000)
        dets.append([[*d.box, d.label, round(d.score, 4)] for d in ds
                     if (d.label or "").lower() in KEEP and d.score >= 0.3])
    times.sort()
    return {"device": getattr(be, "_device", "?"), "frames": len(times),
            "ms_median": round(statistics.median(times), 1),
            "ms_p95": round(times[int(0.95 * (len(times) - 1))], 1),
            "fps": round(1000 / statistics.median(times), 2),
            "resolution": f"{frames[0].shape[1]}x{frames[0].shape[0]}",
            "detections": dets}


def run_pipeline(camera: str, n: int) -> dict:
    """The whole per-frame path the live worker runs: detect, track, plate, OCR."""
    from datetime import UTC, datetime, timedelta

    import av

    from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
    from saakshya.ingest.frame import Frame
    from saakshya.runtime.backend import quiet_transformers

    quiet_transformers()
    pipe = CameraPipeline(camera, PipelineConfig(validate_models=False), district="bench")
    epoch = datetime.now(UTC)
    times, plates, obs = [], set(), 0
    with av.open(str(ROOT / "var" / "media" / f"{camera}.mp4")) as c:
        fps = float(c.streams.video[0].average_rate or 30)
        for i, vf in enumerate(c.decode(video=0)):
            if i >= n:
                break
            img = vf.to_ndarray(format="bgr24")
            fr = Frame(camera_id=camera, segment_id="BENCH", pts_s=i / fps,
                       t_norm=epoch + timedelta(seconds=i / fps), t_ingest=datetime.now(UTC),
                       image=img, width=img.shape[1], height=img.shape[0], codec="h264",
                       frame_index=i)
            t0 = time.perf_counter()
            out = pipe.process(fr)
            if i >= 5:                               # warm-up excluded
                times.append((time.perf_counter() - t0) * 1000)
            for o in out or []:
                obs += 1
                if getattr(o, "plate", None):
                    plates.add(o.plate)
    times.sort()
    return {"frames": len(times), "ms_median": round(statistics.median(times), 1),
            "ms_p95": round(times[int(0.95 * (len(times) - 1))], 1),
            "fps": round(1000 / statistics.median(times), 2),
            "observations": obs, "plates": sorted(plates)}


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def parity(cpu: list, gpu: list) -> dict:
    total = unmatched_cpu = unmatched_gpu = 0
    for fc, fg in zip(cpu, gpu, strict=False):
        used = set()
        for d in fc:
            total += 1
            hit = next((j for j, g in enumerate(fg) if j not in used and g[4] == d[4]
                        and _iou(d, g) >= 0.9), None)
            if hit is None:
                unmatched_cpu += 1
            else:
                used.add(hit)
        unmatched_gpu += len(fg) - len(used)
    return {"cpu_detections": total,
            "cpu_unmatched_on_gpu": unmatched_cpu,
            "gpu_unmatched_on_cpu": unmatched_gpu,
            "agreement": round(1 - (unmatched_cpu / total), 4) if total else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="OWN-MUM-QUEUE")
    ap.add_argument("--frames", type=int, default=90)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--child", choices=["cpu", "mps"])
    ap.add_argument("--pipeline", action="store_true",
                    help="time the whole per-frame pipeline instead of the detector")
    a = ap.parse_args()
    if a.child:
        print(json.dumps(run_pipeline(a.camera, a.frames) if a.pipeline
                         else run_one(a.camera, a.frames, a.stride, a.warmup)))
        return 0
    if a.pipeline:
        res = {}
        for dev in ("cpu", "mps"):
            env = dict(os.environ, SAAKSHYA_FORCE_CPU="1" if dev == "cpu" else "0")
            p = subprocess.run([sys.executable, __file__, "--child", dev, "--pipeline",
                                "--camera", a.camera, "--frames", str(a.frames)],
                               env=env, capture_output=True, text=True, check=True)
            res[dev] = json.loads(p.stdout.strip().splitlines()[-1])
        out = {"what": "whole per-frame pipeline (detect, track, plate, OCR), CPU vs MPS "
                       "for the detector; plate models stay on ONNX CPU",
               "camera": a.camera, "cpu": res["cpu"], "mps": res["mps"],
               "speedup_median": round(res["cpu"]["ms_median"] / res["mps"]["ms_median"], 2),
               "same_plates": res["cpu"]["plates"] == res["mps"]["plates"],
               "same_observation_count": res["cpu"]["observations"] == res["mps"]["observations"],
               "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        dest = ROOT / "var" / "reports" / "pipeline_device.json"
        dest.write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))
        return 0
    res = {}
    for dev in ("cpu", "mps"):
        env = dict(os.environ, SAAKSHYA_FORCE_CPU="1" if dev == "cpu" else "0")
        p = subprocess.run([sys.executable, __file__, "--child", dev, "--camera", a.camera,
                            "--frames", str(a.frames), "--stride", str(a.stride),
                            "--warmup", str(a.warmup)],
                           env=env, capture_output=True, text=True, check=True)
        res[dev] = json.loads(p.stdout.strip().splitlines()[-1])
    out = {
        "what": "RT-DETRv2-R18 (the production vehicle/person detector), CPU vs Apple MPS",
        "camera": a.camera, "frames": res["cpu"]["frames"],
        "resolution": res["cpu"]["resolution"],
        "cpu": {k: v for k, v in res["cpu"].items() if k != "detections"},
        "mps": {k: v for k, v in res["mps"].items() if k != "detections"},
        "speedup_median": round(res["cpu"]["ms_median"] / res["mps"]["ms_median"], 2),
        "parity": parity(res["cpu"]["detections"], res["mps"]["detections"]),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    dest = ROOT / "var" / "reports" / "detector_device.json"
    dest.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
