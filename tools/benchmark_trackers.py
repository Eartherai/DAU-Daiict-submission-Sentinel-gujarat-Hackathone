"""Measure the in-tree tracker on real project footage and report candidates."""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.motion import MotionDetector
from saakshya.analytics.tracker import ByteTracker, Detection


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1], 3)


def run_current(clip: Path, frame_limit: int) -> dict:
    container = av.open(str(clip))
    stream = next(s for s in container.streams if s.type == "video")
    timebase = float(stream.time_base)
    motion, tracker = MotionDetector(), ByteTracker(clip.stem, "BENCHMARK")
    latencies: list[float] = []
    frames = detections = 0
    try:
        for raw in container.decode(stream):
            if raw.pts is None:
                continue
            image = raw.to_ndarray(format="bgr24")
            pts = float(raw.pts) * timebase
            started = time.perf_counter()
            boxes = motion.detect(image)
            tracker.step(
                [Detection(tuple(box), float(score), source="motion")
                 for box, score in boxes],
                pts, datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=pts),
            )
            latencies.append((time.perf_counter() - started) * 1000)
            frames += 1
            detections += len(boxes)
            if frame_limit and frames >= frame_limit:
                break
    finally:
        container.close()
    elapsed = sum(latencies) / 1000
    return {
        "tracker": "ByteTracker (in-tree, PTS-aware)",
        "available": True, "frames": frames, "detections": detections,
        "tracks_created": len(tracker.finished) + len(tracker.tracks),
        "tracks_active": len(tracker.tracks),
        "latency_ms_p50": _pct(latencies, 50), "latency_ms_p95": _pct(latencies, 95),
        "latency_ms_p99": _pct(latencies, 99),
        "throughput_fps": round(frames / elapsed, 3) if elapsed else 0.0,
        "accuracy": None,
        "error": None,
    }


def run(media_dir: Path, frame_limit: int) -> dict:
    clips = sorted(media_dir.glob("*.mp4"))
    current = run_current(clips[0], frame_limit) if clips else {
        "tracker": "ByteTracker (in-tree, PTS-aware)", "available": False,
        "error": "no project footage found",
    }
    candidates = []
    for name, module in (("DeepSORT", "deep_sort_realtime"),
                         ("OC-SORT", "ocsort"), ("BoT-SORT", "boxmot")):
        candidates.append({
            "tracker": name, "available": importlib.util.find_spec(module) is not None,
            "accuracy": None,
            "error": None if importlib.util.find_spec(module) is not None
            else "candidate package is not installed; not installed by benchmark",
        })
    return {
        "measurement_class": "MEASURED",
        "footage": clips[0].name if clips else None,
        "results": [current, *candidates],
        "caveats": [
            "No track bounding-box or identity ground truth is present; accuracy is null.",
            "The measured input uses the project's model-free motion boxes, not fabricated boxes.",
            "Candidate availability is an environment check only; no migration or "
            "installation occurs.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-dir", default="var/media")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--out", default="reports/TRACKER_BENCHMARK.json")
    args = parser.parse_args()
    result = run(ROOT / args.media_dir, args.frames)
    path = ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Tracker benchmark", "", f"Footage: `{result['footage']}`", "",
             "| Tracker | Available | Frames | p50 ms | p95 ms | FPS | Accuracy |",
             "|---|---|---:|---:|---:|---:|---|"]
    for row in result["results"]:
        lines.append(f"| `{row['tracker']}` | {row['available']} | {row.get('frames', 0)} | "
                     f"{row.get('latency_ms_p50')} | {row.get('latency_ms_p95')} | "
                     f"{row.get('throughput_fps', 0)} | {row.get('accuracy')} |")
    lines += ["", "## Caveats", *[f"- {c}" for c in result["caveats"]]]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
