"""Measure the complete pipeline against the cameras that actually exist.

This intentionally does not invent missing cameras or performance numbers.
The catalogue source is recorded as ``government`` or ``synthetic`` and both
catalogue and processed counts are emitted.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
from saakshya.ingest.frame import Frame
from saakshya.runtime.inference_scheduler import AdaptiveInferenceScheduler


def run(
    target: int,
    catalogue: Path,
    out: Path,
    source: str,
    max_seconds: float,
    adaptive: bool = False,
) -> dict:
    data = json.loads(catalogue.read_text())
    cameras = data.get("cameras", [])
    available = [c for c in cameras if (ROOT / "var" / "media" / f"{c['id']}.mp4").exists()]
    selected = available[:target]
    counters = {
        "frames_received": 0,
        "frames_processed": 0,
        "frames_dropped": 0,
        "detections": 0,
        "tracks_created": 0,
        "ocr_reads": 0,
        "observations": 0,
        "errors": 0,
    }
    started = time.perf_counter()
    for camera in selected:
        camera_id = str(camera["id"])
        container = av.open(str(ROOT / "var" / "media" / f"{camera_id}.mp4"))
        stream = next(s for s in container.streams if s.type == "video")
        tb = float(stream.time_base)
        config = PipelineConfig(
            inference_scheduler=AdaptiveInferenceScheduler()
            if adaptive else None
        )
        pipeline = CameraPipeline(camera_id, config)
        camera_received = 0
        for raw in container.decode(stream):
            if raw.pts is None:
                continue
            pts = float(raw.pts) * tb
            if pts > max_seconds:
                break
            image = raw.to_ndarray(format="bgr24")
            counters["frames_received"] += 1
            camera_received += 1
            try:
                pipeline.process(Frame(
                    camera_id=camera_id, segment_id="BENCHMARK", pts_s=pts,
                    t_norm=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=pts),
                    t_ingest=datetime.now(UTC), image=image,
                    width=image.shape[1], height=image.shape[0], codec="h264"))
            except Exception:
                counters["errors"] += 1
                continue
        try:
            pipeline.flush()
        except Exception:
            counters["errors"] += 1
        stats = pipeline.stats
        counters["frames_processed"] += stats.frames_analysed
        counters["frames_dropped"] += camera_received - stats.frames_analysed
        counters["detections"] += (
            stats.plate_detections + stats.vehicle_detections + stats.motion_detections)
        counters["tracks_created"] += stats.tracks_created
        counters["ocr_reads"] += stats.plate_detections
        counters["observations"] += stats.observations_emitted
        container.close()
    elapsed = time.perf_counter() - started
    result = {
        "measurement_class": f"{source.upper()} CATALOGUE",
        "source": source,
        "scheduler": "adaptive" if adaptive else "baseline",
        "target_catalogue_size": target,
        "catalogue_count": len(cameras),
        "available_media_count": len(available),
        "processed_camera_count": len(selected),
        **counters,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_fps": round(counters["frames_processed"] / elapsed, 3) if elapsed else 0.0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    md = [
        f"# Complete pipeline benchmark ({target})",
        "",
        f"**Measurement class:** `{result['measurement_class']}`  ",
        f"**Scheduler:** `{result['scheduler']}`  ",
        f"**Catalogue:** {result['catalogue_count']} entries; "
        f"available media {result['available_media_count']}; "
        f"processed cameras {result['processed_camera_count']}",
        "",
        "| Stage counter | Count |",
        "|---|---:|",
    ]
    md.extend(f"| {key.replace('_', ' ').title()} | {result[key]} |"
              for key in counters)
    md.extend(["", f"Elapsed seconds: {result['elapsed_seconds']}",
               f"Processed throughput (frames/s): {result['throughput_fps']}"])
    out.with_suffix(".md").write_text("\n".join(md) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main(default_target: int) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", default="var/media/catalogue.json")
    parser.add_argument("--out", default=f"var/reports/benchmark_{default_target}.json")
    parser.add_argument("--source", choices=("government", "synthetic"), default="synthetic")
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument("--adaptive", action="store_true",
                        help="enable the adaptive inference scheduler")
    args = parser.parse_args()
    run(default_target, ROOT / args.catalogue, ROOT / args.out, args.source,
        args.max_seconds, args.adaptive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(30))
