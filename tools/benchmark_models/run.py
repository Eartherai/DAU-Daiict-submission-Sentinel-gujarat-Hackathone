#!/usr/bin/env python3
"""Model benchmark harness.

Compares registry models on identical inputs and emits CSV, JSON and Markdown.
Built so that a model swap is justified by a number rather than by a preference,
and so the same command produces comparable results on DEV_CPU and on a GPU host
— which is how a CPU-only laptop can still make defensible model decisions.

Every result is stamped with the runtime profile and the hardware summary,
because a latency figure without the hardware it was measured on is not a
result. Nothing here writes back into the registry: promoting a model from
CANDIDATE to ACTIVE is a human decision.

Usage
-----
    python tools/benchmark_models/run.py --task plate_detect_ocr
    python tools/benchmark_models/run.py --task plate_detect_ocr --fps 2 --out var/logs/bench
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.anpr import AnprConfig, AnprEngine, PlateVoter
from saakshya.analytics.plates import agreement
from saakshya.common.paths import display
from saakshya.models.registry import REGISTRY, ModelRecord, Task
from saakshya.runtime.profile import context

CORPUS_LABEL = "LOCAL SYNTHETIC CORPUS"


@dataclass
class ModelResult:
    model_key: str
    licence: str
    runtime: str
    approved_for_demo: bool

    frames: int = 0
    detections: int = 0
    valid_reads: int = 0

    plates_found: list[str] = field(default_factory=list)
    plates_expected: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)

    plate_recall: float = 0.0
    ocr_exact_match: float = 0.0
    ocr_char_accuracy: float = 0.0

    latency_ms_mean: float = 0.0
    latency_ms_p50: float = 0.0
    latency_ms_p95: float = 0.0
    throughput_fps: float = 0.0
    peak_rss_mb: float = 0.0

    error: str | None = None
    declined_cameras: list[str] = field(default_factory=list)


def _rss_mb() -> float:
    try:
        import resource

        v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes, Linux kilobytes.
        return v / 1e6 if v > 1e7 else v / 1e3
    except Exception:
        return 0.0


def decode_sampled(clip: Path, fps: float):
    c = av.open(str(clip))
    s = next(x for x in c.streams if x.type == "video")
    tb = float(s.time_base)
    step, nxt = 1.0 / fps, 0.0
    for f in c.decode(s):
        if f.pts is None:
            continue
        t = float(f.pts) * tb
        if t + 1e-6 < nxt:
            continue
        nxt = t + step
        yield t, f.to_ndarray(format="bgr24")
    c.close()


def bench_anpr(record: ModelRecord, cams: dict, truth: dict, fps: float) -> ModelResult:
    res = ModelResult(model_key=record.key, licence=record.licence,
                      runtime=record.runtime, approved_for_demo=record.approved_for_demo)
    try:
        engine = AnprEngine(AnprConfig(), record=record)
    except Exception as exc:
        res.error = f"load failed: {type(exc).__name__}: {exc}"[:200]
        return res

    latencies: list[float] = []
    found: set[str] = set()
    expected: set[str] = set()
    char_scores: list[float] = []
    t_start = time.perf_counter()

    for cid in sorted(cams):
        clip = ROOT / "var" / "media" / f"{cid}.mp4"
        if not clip.exists():
            continue
        exp = truth.get(cid, set())
        expected |= exp
        voter = PlateVoter(AnprConfig())
        try:
            for pts, img in decode_sampled(clip, fps):
                t0 = time.perf_counter()
                reads = engine.read_frame(img, pts)
                latencies.append((time.perf_counter() - t0) * 1000)
                res.frames += 1
                res.detections += len(reads)
                voter.add(cid, reads)
        except Exception as exc:
            res.error = f"inference failed on {cid}: {type(exc).__name__}: {exc}"[:200]
            return res

        voted = voter.resolve_all(cid)
        res.valid_reads += sum(v.votes for v in voted)
        cam_found = {v.plate.canonical for v in voted}
        found |= cam_found
        if not cam_found:
            res.declined_cameras.append(cid)
        # Character accuracy: best agreement between each expected plate and any
        # read on that camera. Rewards a near-miss over silence, which matters
        # when comparing OCR heads.
        for e in exp:
            best = max((agreement(e, v.plate.canonical) for v in voted), default=0.0)
            char_scores.append(best)

    wall = time.perf_counter() - t_start
    res.plates_found = sorted(found)
    res.plates_expected = sorted(expected)
    res.false_positives = sorted(found - expected)
    res.plate_recall = round(len(found & expected) / max(1, len(expected)), 4)
    res.ocr_exact_match = res.plate_recall
    res.ocr_char_accuracy = round(statistics.fmean(char_scores), 4) if char_scores else 0.0
    if latencies:
        latencies.sort()
        res.latency_ms_mean = round(statistics.fmean(latencies), 2)
        res.latency_ms_p50 = round(latencies[len(latencies) // 2], 2)
        res.latency_ms_p95 = round(latencies[int(len(latencies) * 0.95)], 2)
    res.throughput_fps = round(res.frames / wall, 2) if wall > 0 else 0.0
    res.peak_rss_mb = round(_rss_mb(), 1)
    return res


def write_reports(results: list[ModelResult], task: str, out_dir: Path, fps: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = context()
    meta = {
        "task": task,
        "corpus": CORPUS_LABEL,
        "sampling_fps": fps,
        "runtime_profile": str(ctx.profile),
        "hardware": ctx.hardware.summary,
        "measurement_class": "MEASURED (on the corpus and hardware named above)",
        "caveat": (
            "These are regression numbers on a synthetic corpus, not real-world "
            "accuracy. They are valid for comparing models against each other on "
            "identical inputs. They must not be quoted as field accuracy."
        ),
    }
    rows = [asdict(r) for r in results]

    (out_dir / f"{task}.json").write_text(
        json.dumps({"meta": meta, "results": rows}, indent=2))

    with (out_dir / f"{task}.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        for r in rows:
            w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()})

    md = [f"# Model benchmark — {task}", "",
          f"**Corpus:** {CORPUS_LABEL}  ",
          f"**Profile:** {ctx.profile}  ",
          f"**Hardware:** {ctx.hardware.summary}  ",
          f"**Sampling:** {fps} fps", "",
          "> " + meta["caveat"], "",
          "| Model | Licence | Approved | Recall | Char acc | p50 ms | p95 ms | FPS | Notes |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: -x.plate_recall):
        note = r.error or (f"declined: {','.join(r.declined_cameras)}"
                           if r.declined_cameras else "")
        if r.false_positives:
            note = f"**FP: {','.join(r.false_positives)}** {note}"
        md.append(
            f"| `{r.model_key}` | {r.licence} | {'yes' if r.approved_for_demo else 'no'} "
            f"| {r.plate_recall:.2f} | {r.ocr_char_accuracy:.2f} | {r.latency_ms_p50:.0f} "
            f"| {r.latency_ms_p95:.0f} | {r.throughput_fps:.1f} | {note} |")
    (out_dir / f"{task}.md").write_text("\n".join(md) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="plate_detect_ocr",
                    choices=[t.value for t in Task])
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--out", default="var/logs/benchmark")
    ap.add_argument("--include-rejected", action="store_true",
                    help="also benchmark REJECTED models, to evidence the rejection")
    args = ap.parse_args()

    ctx = context()
    task = Task(args.task)
    gt = json.loads((ROOT / "tests" / "evaluation" / "ground_truth.json").read_text())
    cat = json.loads((ROOT / "var" / "media" / "catalogue.json").read_text())
    cams = {c["id"]: c for c in cat["cameras"]}
    truth: dict[str, set[str]] = defaultdict(set)
    for o in gt["observations"]:
        truth[o["camera_id"]].add(o["plate"])

    from saakshya.models.registry import Status

    models = [m for m in REGISTRY.values() if m.task == task
              and (args.include_rejected or m.status is not Status.REJECTED)]
    if not models:
        print(f"no models registered for task {task}")
        return 1

    print(f"Benchmark: {task}  |  corpus: {CORPUS_LABEL}")
    print(f"Profile: {ctx.profile}  |  {ctx.hardware.summary}")
    print(f"Models: {len(models)}  |  sampling {args.fps} fps\n")

    results = []
    for m in models:
        print(f"  -> {m.key} ({m.licence}) ...", end=" ", flush=True)
        if task in (Task.PLATE_DETECT_OCR,):
            r = bench_anpr(m, cams, truth, args.fps)
        else:
            r = ModelResult(m.key, m.licence, m.runtime, m.approved_for_demo,
                            error=f"no benchmark implemented for task {task}")
        results.append(r)
        print(r.error if r.error else
              f"recall {r.plate_recall:.2f}  p50 {r.latency_ms_p50:.0f} ms")

    out_dir = ROOT / args.out
    write_reports(results, str(task), out_dir, args.fps)

    print(f"\n{'model':<38}{'lic':<12}{'recall':>7}{'char':>7}{'p50ms':>8}{'fps':>7}")
    print("-" * 79)
    for r in sorted(results, key=lambda x: -x.plate_recall):
        print(f"{r.model_key:<38}{r.licence:<12}{r.plate_recall:>7.2f}"
              f"{r.ocr_char_accuracy:>7.2f}{r.latency_ms_p50:>8.0f}{r.throughput_fps:>7.1f}")
    print(f"\nreports: {display(out_dir, ROOT)}/{task}.{{json,csv,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
