"""Measure the real decode and analytics pipeline on available project media."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
from saakshya.ingest.frame import Frame


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1], 3)


def _stage(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "mean_ms": round(statistics.fmean(values), 3) if values else None,
    }


def run(media_dir: Path, max_seconds: float, max_cameras: int) -> dict[str, Any]:
    clips = sorted(media_dir.glob("*.mp4"))[:max_cameras]
    counters: dict[str, int] = {
        "frames_received": 0, "frames_processed": 0, "frames_skipped": 0,
        "detections": 0, "tracks_created": 0, "observations": 0, "errors": 0,
    }
    timings: dict[str, list[float]] = {"decode": [], "pipeline": [], "flush": []}
    errors: list[dict[str, str]] = []
    started = time.perf_counter()
    for clip in clips:
        pipeline: CameraPipeline | None = None
        container = None
        try:
            container = av.open(str(clip))
            stream = next(s for s in container.streams if s.type == "video")
            timebase = float(stream.time_base)
            pipeline = CameraPipeline(clip.stem, PipelineConfig())
            for raw in container.decode(stream):
                t0 = time.perf_counter()
                if raw.pts is None:
                    counters["frames_skipped"] += 1
                    continue
                pts = float(raw.pts) * timebase
                if pts > max_seconds:
                    break
                image = raw.to_ndarray(format="bgr24")
                timings["decode"].append((time.perf_counter() - t0) * 1000)
                counters["frames_received"] += 1
                frame = Frame(
                    camera_id=clip.stem, segment_id="PROFILE", pts_s=pts,
                    t_norm=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=pts),
                    t_ingest=datetime.now(UTC), image=image,
                    width=image.shape[1], height=image.shape[0], codec="h264",
                )
                t0 = time.perf_counter()
                try:
                    pipeline.process(frame)
                    timings["pipeline"].append((time.perf_counter() - t0) * 1000)
                except Exception as exc:
                    counters["errors"] += 1
                    errors.append({"camera": clip.stem, "stage": "pipeline",
                                   "error": f"{type(exc).__name__}: {exc}"[:240]})
            t0 = time.perf_counter()
            pipeline.flush()
            timings["flush"].append((time.perf_counter() - t0) * 1000)
            stats = pipeline.stats
            counters["frames_processed"] += stats.frames_analysed
            counters["detections"] += (stats.plate_detections + stats.vehicle_detections
                                        + stats.motion_detections)
            counters["tracks_created"] += stats.tracks_created
            counters["observations"] += stats.observations_emitted
        except Exception as exc:
            counters["errors"] += 1
            errors.append({"camera": clip.stem, "stage": "open",
                           "error": f"{type(exc).__name__}: {exc}"[:240]})
        finally:
            if container is not None:
                container.close()
    elapsed = time.perf_counter() - started
    bottlenecks = sorted(
        ((name, data["p95_ms"] or 0.0) for name, data in
         ((n, _stage(v)) for n, v in timings.items())),
        key=lambda item: item[1], reverse=True,
    )
    return {
        "measurement_class": "MEASURED",
        "media": str(media_dir),
        "clips": [p.name for p in clips],
        "counters": counters,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_fps": round(counters["frames_processed"] / elapsed, 3) if elapsed else 0.0,
        "stages": {name: _stage(values) for name, values in timings.items()},
        "top_bottlenecks": [{"stage": n, "p95_ms": ms} for n, ms in bottlenecks[:3]],
        "errors": errors,
        "caveats": ["CPU/GPU utilisation is not reported because it was not measured.",
                    "Accuracy is not inferred from timing; see detector/tracker reports."],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-dir", default="var/media")
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument("--max-cameras", type=int, default=6)
    parser.add_argument("--json", default="reports/PIPELINE_PROFILE.json")
    parser.add_argument("--report", default="reports/PIPELINE_PROFILE.md")
    args = parser.parse_args()
    result = run(ROOT / args.media_dir, args.max_seconds, args.max_cameras)
    json_path, report_path = ROOT / args.json, ROOT / args.report
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2) + "\n")
    rows = ["# Pipeline profile", "", "**Measurement:** measured on available project media.",
            "", "| Stage | Samples | p50 ms | p95 ms | p99 ms |", "|---|---:|---:|---:|---:|"]
    for name, values in result["stages"].items():
        rows.append(f"| {name} | {values['samples']} | {values['p50_ms']} | "
                    f"{values['p95_ms']} | {values['p99_ms']} |")
    rows += ["", f"Throughput: **{result['throughput_fps']} frames/s**",
             f"Errors: **{result['counters']['errors']}**", "",
             "## Top bottlenecks (measured p95)", ""]
    rows += [f"{i}. `{item['stage']}` — {item['p95_ms']} ms"
             for i, item in enumerate(result["top_bottlenecks"], 1)]
    rows += ["", "## Caveats", *[f"- {c}" for c in result["caveats"]]]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(rows) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
