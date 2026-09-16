#!/usr/bin/env python3
"""Benchmark OCR on explicitly labelled plate crops.

The command never invents labels. Rows without a verified ``plate`` are
reported as unavailable and excluded from accuracy, while missing crops or an
unloadable backend produce an explicit unavailable report and exit successfully.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from saakshya.analytics.plates import normalise

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("items", data.get("observations", []))
    return data if isinstance(data, list) else []


def _char_accuracy(expected: str, got: str) -> float:
    if not expected:
        return 0.0
    return sum(a == b for a, b in zip(expected, got, strict=False)) / max(
        len(expected), len(got), 1)


def benchmark(
    crops: Path, truth: Path, *, record_key: str = "anpr-onnx-cpu@1.0.0"
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unavailable", "dataset": str(truth), "crops": str(crops),
        "records": 0, "scored": 0, "unavailable": 0, "empty": 0,
        "exact_accuracy": None, "normalized_accuracy": None,
        "character_accuracy": None, "latency_ms_p50": None, "latency_ms_p95": None,
        "error": None,
    }
    if not truth.exists():
        result["error"] = "ground-truth dataset not found"
        return result
    rows = _rows(truth)
    result["records"] = len(rows)
    if not rows:
        result["error"] = "ground-truth dataset is empty"
        return result
    try:
        from PIL import Image

        from saakshya.models.registry import ANPR_CPU
        from saakshya.runtime.backend import BACKENDS

        backend = BACKENDS.get(ANPR_CPU)
    except Exception as exc:  # optional analytics dependencies are environment-specific
        result["error"] = f"OCR backend unavailable: {type(exc).__name__}: {exc}"
        return result

    expected_exact = expected_norm = chars = 0
    latencies: list[float] = []
    for row in rows:
        expected = row.get("plate")
        if not row.get("verified", True) or not isinstance(expected, str) or not expected.strip():
            result["unavailable"] += 1
            continue
        image_path = Path(str(row.get("image", "")))
        image_path = (
            image_path if image_path.is_absolute() else truth.parent.parent.parent / image_path
        )
        if not image_path.exists() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            result["unavailable"] += 1
            continue
        try:
            image = __import__("numpy").asarray(Image.open(image_path).convert("RGB"))[:, :, ::-1]
            start = time.perf_counter()
            prediction = backend.ocr(image)
            latencies.append((time.perf_counter() - start) * 1000)
        except Exception as exc:
            result["error"] = f"OCR failed: {type(exc).__name__}: {exc}"
            return result
        if prediction is None or not prediction.text:
            result["empty"] += 1
            continue
        got = prediction.text
        expected_exact += got.upper() == expected.upper()
        expected_norm += normalise(got) == normalise(expected)
        chars += _char_accuracy(normalise(expected), normalise(got))
        result["scored"] += 1

    if result["scored"]:
        result["exact_accuracy"] = expected_exact / result["scored"]
        result["normalized_accuracy"] = expected_norm / result["scored"]
        result["character_accuracy"] = chars / result["scored"]
        result["status"] = "measured"
    elif result["error"] is None:
        result["error"] = "no labelled crops were available for scoring"
    if latencies:
        result["latency_ms_p50"] = statistics.median(latencies)
        result["latency_ms_p95"] = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops", type=Path, default=Path("var/evaluation/crops"))
    parser.add_argument("--ground-truth", type=Path,
                        default=Path("evaluation/ground_truth_lite/template.jsonl"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = benchmark(args.crops, args.ground_truth)
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
