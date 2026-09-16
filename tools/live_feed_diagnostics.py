#!/usr/bin/env python3
"""Bounded, provenance-aware diagnostics for a local media file or stream URL.

This is an observation tool, not a stream health oracle.  Missing PyAV,
unreachable URLs, absent PTS, and unavailable pixel measurements are reported
as ``null`` (with an explanation) rather than inferred from declared FPS.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "1"
URL_SCHEMES = frozenset({"http", "https", "rtmp", "rtmps", "rtsp", "rtsps"})


def _empty(source: str, started: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "source_kind": "url" if urlparse(source).scheme in URL_SCHEMES else "file",
        "started_at_utc": started,
        "finished_at_utc": None,
        "availability": "UNKNOWN",
        "error": None,
        "stream": {
            "codec": None, "width": None, "height": None, "resolution": None,
            "pixel_format": None, "time_base": None, "declared_fps": None,
            "duration_seconds": None,
        },
        "timing": {
            "frames_decoded": 0, "frames_with_pts": 0, "missing_pts": 0,
            "pts_regressions": 0, "pts_jumps": 0, "pts_first": None,
            "pts_last": None, "observed_fps": None, "inter_frame_seconds": {},
        },
        "quality": {
            "frames_sampled": 0, "black_frames": 0, "freeze_frames": 0,
            "corrupt_frames": 0, "mean_luma": None, "black_ratio": None,
            "freeze_ratio": None,
        },
        "reconnect": {"attempts": 0, "reconnects": 0},
        "limitations": [],
    }


def _redact(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}{parsed.path}"
    return value


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int((len(values) - 1) * p))], 6)


def _ffprobe(source: str, result: dict[str, Any]) -> bool:
    """Fill stream metadata when PyAV is absent, without pretending to decode."""
    executable = shutil.which("ffprobe")
    if not executable:
        result["limitations"].append("PyAV and ffprobe are unavailable")
        return False
    try:
        completed = subprocess.run(
            [executable, "-v", "error", "-show_streams", "-of", "json", source],
            capture_output=True, text=True, timeout=15, check=True,
        )
        streams = json.loads(completed.stdout).get("streams", [])
        stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not stream:
            result["error"] = "no video stream found"
            return False
        out = result["stream"]
        out.update(codec=stream.get("codec_name"), width=stream.get("width"),
                   height=stream.get("height"), pixel_format=stream.get("pix_fmt"),
                   time_base=stream.get("time_base"), declared_fps=stream.get("r_frame_rate"))
        if out["width"] and out["height"]:
            out["resolution"] = f"{out['width']}x{out['height']}"
        result["availability"] = "METADATA_ONLY"
        result["limitations"].append("ffprobe metadata only; frame timing and pixels unavailable")
        return True
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return False


def inspect_source(source: str | Path, *, seconds: float = 10.0,
                   max_frames: int = 300, retries: int = 0,
                   sample_every: int = 1) -> dict[str, Any]:
    """Inspect one source for a bounded interval.

    ``reconnects`` means additional open attempts, not a claim that a remote
    service itself disconnected.  A single open attempt cannot measure that.
    """
    source_text = str(source)
    started = datetime.now(UTC).isoformat()
    result = _empty(_redact(source_text), started)
    result["reconnect"]["attempts"] = retries + 1
    container = None
    try:
        import av  # type: ignore[import-not-found]
    except ImportError:
        _ffprobe(source_text, result)
        result["finished_at_utc"] = datetime.now(UTC).isoformat()
        return result

    open_source = source_text
    if urlparse(source_text).scheme in {"rtsp", "rtsps"}:
        from saakshya.live.credentials import credentialed
        open_source = credentialed(source_text)
    for attempt in range(retries + 1):
        try:
            container = av.open(open_source,
                                options={"rtsp_transport": "tcp"},
                                timeout=max(1.0, min(seconds, 30.0)))
            break
        except Exception as exc:  # PyAV exposes version-specific error classes.
            result["error"] = f"{type(exc).__name__}: {_redact(str(exc))[:240]}"
            if attempt < retries:
                result["reconnect"]["reconnects"] += 1
                continue
    if container is None:
        result["availability"] = "UNAVAILABLE"
        result["limitations"].append("source could not be opened; no frame measurements")
        result["finished_at_utc"] = datetime.now(UTC).isoformat()
        return result

    try:
        stream = next((item for item in container.streams if item.type == "video"), None)
        if stream is None:
            result["error"] = "no video stream found"
            result["availability"] = "UNAVAILABLE"
            return result
        out = result["stream"]
        codec = getattr(getattr(stream, "codec_context", None), "name", None)
        out.update(codec=codec, width=getattr(stream, "width", None),
                   height=getattr(stream, "height", None),
                   pixel_format=getattr(getattr(stream, "codec_context", None),
                                        "format", None))
        if out["pixel_format"] is not None:
            out["pixel_format"] = str(out["pixel_format"])
        if out["width"] and out["height"]:
            out["resolution"] = f"{out['width']}x{out['height']}"
        out["time_base"] = str(stream.time_base) if stream.time_base else None
        declared = float(stream.average_rate) if stream.average_rate else None
        if declared is not None and not 0 < declared <= 120:
            out["declared_fps"] = None
            result["limitations"].append(
                "declared FPS was outside the plausible 0-120 range")
        else:
            out["declared_fps"] = declared
        if getattr(stream, "duration", None) is not None and stream.time_base:
            out["duration_seconds"] = round(float(stream.duration * stream.time_base), 6)
        tb = float(stream.time_base) if stream.time_base else None
        timing, quality = result["timing"], result["quality"]
        pts_values: list[float] = []
        deltas: list[float] = []
        last_signature: bytes | None = None
        deadline = time.monotonic() + max(0.0, seconds)
        for frame in container.decode(stream):
            if time.monotonic() > deadline or timing["frames_decoded"] >= max_frames:
                break
            timing["frames_decoded"] += 1
            if frame.pts is None or tb is None:
                timing["missing_pts"] += 1
            else:
                pts = float(frame.pts) * tb
                timing["frames_with_pts"] += 1
                if pts_values:
                    delta = pts - pts_values[-1]
                    deltas.append(delta)
                    if delta < 0:
                        timing["pts_regressions"] += 1
                    if delta > 5.0:
                        timing["pts_jumps"] += 1
                pts_values.append(pts)
            if timing["frames_decoded"] % max(1, sample_every):
                continue
            try:
                image = frame.to_ndarray(format="gray")
                quality["frames_sampled"] += 1
                mean = float(image.mean()) / 255.0
                quality["mean_luma"] = (
                    mean if quality["mean_luma"] is None
                    else (quality["mean_luma"] * (quality["frames_sampled"] - 1) + mean)
                    / quality["frames_sampled"])
                black = mean < 0.03 and float(image.std()) / 255.0 < 0.04
                quality["black_frames"] += int(black)
                signature = image[::8, ::8].tobytes()
                quality["freeze_frames"] += int(signature == last_signature)
                last_signature = signature
            except Exception:
                quality["corrupt_frames"] += 1
        if pts_values:
            timing["pts_first"], timing["pts_last"] = pts_values[0], pts_values[-1]
            if len(pts_values) > 1 and timing["pts_first"] == timing["pts_last"]:
                result["limitations"].append(
                    "decoded frames carried no advancing PTS; observed FPS is unavailable")
        if deltas:
            timing["inter_frame_seconds"] = {
                "p50": _percentile(deltas, 0.50), "p95": _percentile(deltas, 0.95),
                "min": round(min(deltas), 6), "max": round(max(deltas), 6),
            }
            positive = [d for d in deltas if d > 0]
            if positive:
                timing["observed_fps"] = round(1.0 / (sum(positive) / len(positive)), 6)
        sampled = quality["frames_sampled"]
        if sampled:
            quality["black_ratio"] = round(quality["black_frames"] / sampled, 6)
            quality["freeze_ratio"] = round(quality["freeze_frames"] / sampled, 6)
        if timing["frames_decoded"] == 0:
            result["availability"] = "PARTIAL"
            result["limitations"].append(
                "stream opened but no video frames were decoded in the bounded window")
        else:
            result["availability"] = "MEASURED"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {_redact(str(exc))[:240]}"
        result["availability"] = "PARTIAL"
    finally:
        container.close()
        result["finished_at_utc"] = datetime.now(UTC).isoformat()
    return result


def to_markdown(report: dict[str, Any]) -> str:
    """Render a compact report; null values are explicitly unavailable."""
    stream, timing, quality = report["stream"], report["timing"], report["quality"]
    def value(item: Any) -> str:
        return "unavailable" if item is None else str(item)
    lines = ["# Live-feed diagnostics", "", f"- Source: `{report['source']}`",
             f"- Availability: **{report['availability']}**",
             f"- Schema: `{report['schema_version']}`", ""]
    if report["error"]:
        lines += [f"- Error: `{report['error']}`", ""]
    lines += ["## Stream", "", "| Field | Value |", "|---|---|"]
    lines += [f"| {key} | {value(stream[key])} |" for key in
              ("codec", "resolution", "pixel_format", "time_base", "declared_fps",
               "duration_seconds")]
    lines += ["", "## Timing and quality", "", "| Field | Value |", "|---|---|"]
    lines += [f"| {key} | {value(section[key])} |" for section in (timing, quality)
              for key in section]
    if report["limitations"]:
        lines += ["", "## Limitations", ""] + [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="local media path or URL")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect_source(args.source, seconds=args.seconds, max_frames=args.max_frames,
                            retries=args.retries, sample_every=args.sample_every)
    rendered = json.dumps(report, indent=2) if args.format == "json" else to_markdown(report)
    if args.output:
        args.output.write_text(
            rendered + ("" if rendered.endswith("\n") else "\n"), encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["availability"] in {"MEASURED", "METADATA_ONLY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
