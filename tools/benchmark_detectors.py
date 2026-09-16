"""Benchmark registered vehicle detectors without adding dependencies or models."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.models.registry import REGISTRY, Status, Task
from saakshya.runtime.backend import BACKENDS


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1], 3)


def _frames(path: Path, limit: int):
    container = av.open(str(path))
    stream = next(s for s in container.streams if s.type == "video")
    try:
        for frame in container.decode(stream):
            if frame.pts is not None:
                yield frame.to_ndarray(format="bgr24")
                limit -= 1
                if limit <= 0:
                    break
    finally:
        container.close()


def benchmark(record: Any, clips: list[Path], frame_limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {"model": record.key, "status": str(record.status),
                              "licence": record.licence, "frames": 0,
                              "detections": 0, "accuracy": None, "error": None}
    try:
        os.environ.setdefault("SAAKSHYA_MODELS_OFFLINE", "1")
        backend = BACKENDS.get(record)
        latencies: list[float] = []
        for clip in clips:
            for image in _frames(clip, frame_limit):
                started = time.perf_counter()
                detections = backend.detect(image)
                latencies.append((time.perf_counter() - started) * 1000)
                result["frames"] += 1
                result["detections"] += len(detections)
        elapsed = sum(latencies) / 1000
        result.update({
            "latency_ms_p50": _pct(latencies, 50),
            "latency_ms_p95": _pct(latencies, 95),
            "latency_ms_p99": _pct(latencies, 99),
            "throughput_fps": round(result["frames"] / elapsed, 3) if elapsed else 0.0,
            "accuracy": None,
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        result["unavailable_reason"] = "model or runtime is not available locally"
    return result


def run(media_dir: Path, frame_limit: int) -> dict[str, Any]:
    clips = sorted(media_dir.glob("*.mp4"))
    records = [r for r in REGISTRY.values()
               if r.task is Task.VEHICLE_DETECT and r.status is not Status.REJECTED]
    results = [benchmark(record, clips[:2], frame_limit) for record in records]
    return {
        "measurement_class": "MEASURED",
        "footage": [c.name for c in clips[:2]],
        "results": results,
        "caveats": [
            "No vehicle bounding-box ground truth is present, so accuracy is null.",
            "Unavailable candidates are recorded; no packages or weights are installed.",
            "FPS is inference-only and excludes decode; compare on the named footage and host.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-dir", default="var/media")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--out", default="reports/DETECTOR_BENCHMARK.json")
    args = parser.parse_args()
    result = run(ROOT / args.media_dir, args.frames)
    path = ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Detector benchmark", "", f"Footage: `{', '.join(result['footage'])}`", "",
             "| Detector | Frames | p50 ms | p95 ms | FPS | Accuracy | Availability |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for row in result["results"]:
        lines.append(f"| `{row['model']}` | {row['frames']} | {row.get('latency_ms_p50')} | "
                     f"{row.get('latency_ms_p95')} | {row.get('throughput_fps', 0)} | "
                     f"{row['accuracy']} | {'available' if not row['error'] else row['error']} |")
    lines += ["", "## Caveats", *[f"- {c}" for c in result["caveats"]]]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
