#!/usr/bin/env python3
"""Government-feed intake: validate, characterise, report.

Run this the moment real feeds become available, **before** any model
evaluation. Its job is to answer "what did we actually receive?" — not "how well
do we do on it". Those are different questions and conflating them is how teams
end up tuning against a dataset they never characterised.

Deliberately cheap. It samples a handful of frames per camera rather than
decoding everything, because characterising 50 cameras must take minutes, not
hours, and because a profile computed from the whole stream tells you no more
than one computed from a representative sample.

    python tools/data_intake/profile.py --catalogue <url-or-file> [--sample 12]
    python tools/data_intake/profile.py --catalogue var/media/catalogue.json --offline

Writes docs/REAL_DATA_READINESS_REPORT.md and var/reports/camera_profiles.json.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.quality import assess
from saakshya.common.paths import display

#: Formats we can decode today. Anything else is reported, never silently skipped.
SUPPORTED_CODECS = {"h264", "hevc", "h265", "mpeg4", "mjpeg", "vp8", "vp9", "av1"}


@dataclass
class CameraProfile:
    camera_id: str
    source: str = ""
    reachable: bool = False
    error: str | None = None

    codec: str | None = None
    width: int | None = None
    height: int | None = None
    declared_fps: float | None = None
    measured_fps: float | None = None
    bitrate_kbps: float | None = None

    frames_sampled: int = 0
    pts_monotonic: bool = True
    pts_gaps: int = 0
    first_pts_s: float | None = None
    last_pts_s: float | None = None

    mean_luminance: float | None = None
    mean_sharpness: float | None = None
    scene_activity: float | None = None
    estimated_scene: str = "unknown"

    warnings: list[str] = field(default_factory=list)
    #: Set only where evidence supports it; otherwise stays INSUFFICIENT_DATA.
    initial_tier_hint: str = "INSUFFICIENT_DATA"

    def to_dict(self) -> dict:
        return asdict(self)


def load_catalogue(source: str, *, token: str | None = None) -> list[dict]:
    """Read the camera catalogue from a URL or a local file.

    The catalogue is the contract — camera ids and the camera set change, and
    hard-coding endpoints is the first documented way to fail on this grid.
    """
    if source.startswith(("http://", "https://")):
        import httpx

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = httpx.get(source, headers=headers, timeout=30.0)
        r.raise_for_status()
        data = r.json()
    else:
        data = json.loads(Path(source).read_text())

    # Accept the shapes a government API plausibly returns rather than demanding
    # one. Normalising here keeps the rest of the tool simple.
    if isinstance(data, dict):
        for key in ("cameras", "items", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return data if isinstance(data, list) else []


def normalise_entry(raw: dict) -> dict:
    """Map a catalogue entry onto our registry fields, tolerantly."""
    def pick(*names, default=None):
        for n in names:
            if n in raw and raw[n] not in (None, ""):
                return raw[n]
            # one level of nesting
            for parent in ("properties", "location", "meta", "attributes"):
                p = raw.get(parent)
                if isinstance(p, dict) and p.get(n) not in (None, ""):
                    return p[n]
        return default

    urls = raw.get("urls") if isinstance(raw.get("urls"), dict) else {}
    return {
        "camera_id": str(pick("id", "camera_id", "cameraId", "name", default="")),
        "name": pick("name", "title", "label"),
        "department": pick("department", "dept", "owner", "agency"),
        "district": pick("district", "zone", "region", "city"),
        "lat": pick("lat", "latitude"),
        "lon": pick("lon", "lng", "longitude"),
        "codec": pick("codec", "video_codec"),
        "width": pick("width", "w"),
        "height": pick("height", "h"),
        "declared_fps": pick("declared_fps", "fps", "framerate", "frame_rate"),
        "rtsp_url": urls.get("rtsp") or pick("rtsp", "rtsp_url", "stream", "url"),
        "hls_url": urls.get("hls") or pick("hls", "hls_url", "m3u8"),
        "whep_url": urls.get("whep") or pick("whep", "webrtc"),
        "quality_note": pick("quality_note", "note", "description"),
        "_raw": raw,
    }


def validate(entries: list[dict]) -> tuple[list[dict], list[str]]:
    """Structural checks. Nothing bad is skipped silently."""
    problems: list[str] = []
    seen: dict[str, int] = {}
    ok: list[dict] = []

    for i, e in enumerate(entries):
        cid = e["camera_id"]
        if not cid:
            problems.append(f"entry {i}: no usable camera identifier")
            continue
        if cid in seen:
            problems.append(f"duplicate camera id {cid!r} "
                            f"(entries {seen[cid]} and {i})")
            continue
        seen[cid] = i

        if not (e["rtsp_url"] or e["hls_url"]):
            problems.append(f"{cid}: no RTSP or HLS source")
        if e["lat"] is None or e["lon"] is None:
            problems.append(f"{cid}: no coordinates — excluded from GIS seeding "
                            f"and from distance-based graph priors")
        for dim in ("width", "height"):
            v = e[dim]
            if v is not None and (not isinstance(v, (int, float)) or v <= 0 or v > 16384):
                problems.append(f"{cid}: implausible {dim}={v!r}")
        if e["codec"] and str(e["codec"]).lower() not in SUPPORTED_CODECS:
            problems.append(f"{cid}: codec {e['codec']!r} is not in the supported "
                            f"set {sorted(SUPPORTED_CODECS)}")
        ok.append(e)
    return ok, problems


def probe(entry: dict, *, samples: int, timeout: float = 20.0) -> CameraProfile:
    """Decode a few frames and characterise the source. No analytics models."""
    import av

    cid = entry["camera_id"]
    url = entry["rtsp_url"] or entry["hls_url"]
    p = CameraProfile(camera_id=cid, source=url or "")
    if not url:
        p.error = "no stream URL"
        return p

    opts = {"rtsp_transport": "tcp", "stimeout": str(int(timeout * 1_000_000))}
    try:
        container = av.open(url, options=opts, timeout=(timeout, timeout))
    except Exception as exc:
        p.error = f"{type(exc).__name__}: {exc}"[:200]
        return p

    try:
        vs = next((s for s in container.streams if s.type == "video"), None)
        if vs is None:
            p.error = "no video stream"
            return p
        p.codec = getattr(vs.codec_context, "name", None)
        with contextlib.suppress(TypeError, ValueError):
            p.declared_fps = float(vs.average_rate) if vs.average_rate else None
        p.bitrate_kbps = (container.bit_rate / 1000.0) if container.bit_rate else None

        tb = float(vs.time_base) if vs.time_base else 1 / 90000.0
        intervals: list[float] = []
        lums: list[float] = []
        sharps: list[float] = []
        prev_small: np.ndarray | None = None
        activity: list[float] = []
        last_pts: float | None = None
        t0 = time.perf_counter()

        for frame in container.decode(vs):
            if frame.pts is None:
                continue
            pts = float(frame.pts) * tb
            if p.first_pts_s is None:
                p.first_pts_s = pts
            if last_pts is not None:
                d = pts - last_pts
                if d < 0:
                    p.pts_monotonic = False
                elif d > 2.0:
                    p.pts_gaps += 1
                elif d > 0:
                    intervals.append(d)
            last_pts = pts

            img = frame.to_ndarray(format="bgr24")
            p.width, p.height = img.shape[1], img.shape[0]
            q = assess(img)
            lums.append(q.luminance)
            sharps.append(q.sharpness)

            small = img[::16, ::16].astype(np.float32).mean(axis=2)
            if prev_small is not None and prev_small.shape == small.shape:
                activity.append(float(np.abs(small - prev_small).mean()))
            prev_small = small

            p.frames_sampled += 1
            if p.frames_sampled >= samples or time.perf_counter() - t0 > timeout:
                break

        p.last_pts_s = last_pts
        p.reachable = p.frames_sampled > 0
        if intervals:
            med = float(np.median(intervals))
            p.measured_fps = round(1.0 / med, 2) if med > 0 else None
        if lums:
            p.mean_luminance = round(float(np.mean(lums)), 3)
            p.mean_sharpness = round(float(np.mean(sharps)), 3)
        if activity:
            p.scene_activity = round(float(np.mean(activity)), 3)
    except Exception as exc:
        p.error = f"decode: {type(exc).__name__}: {exc}"[:200]
    finally:
        with contextlib.suppress(Exception):
            container.close()

    _characterise(p, entry)
    return p


def _characterise(p: CameraProfile, entry: dict) -> None:
    """Warnings and a *hint* — never a grade. Grades need sustained measurement."""
    if p.declared_fps and p.measured_fps:
        if abs(p.declared_fps - p.measured_fps) > max(1.0, 0.25 * p.declared_fps):
            p.warnings.append(
                f"declared fps {p.declared_fps:.1f} disagrees with measured "
                f"{p.measured_fps:.1f} — do not trust the declared value")
    if not p.pts_monotonic:
        p.warnings.append("PTS moved backwards during sampling — timing on this "
                          "camera needs a segment-aware consumer")
    if p.pts_gaps:
        p.warnings.append(f"{p.pts_gaps} inter-frame gap(s) over 2s")
    if p.mean_luminance is not None and p.mean_luminance < 0.25:
        p.warnings.append("very low luminance — ANPR unlikely to be viable")
    if p.mean_sharpness is not None and p.mean_sharpness < 0.15:
        p.warnings.append("very soft image — ANPR unlikely to be viable")
    if p.scene_activity is not None and p.scene_activity < 0.5:
        p.estimated_scene = "static / low traffic"
    elif p.scene_activity is not None:
        p.estimated_scene = "active"

    if not p.reachable:
        p.initial_tier_hint = "UNREACHABLE"
        return
    # A hint only, and only from things a short sample can actually support.
    small = (p.width or 0) * (p.height or 0) < 640 * 480
    dim = (p.mean_luminance or 1.0) < 0.3
    soft = (p.mean_sharpness or 1.0) < 0.2
    if small or dim or soft:
        p.initial_tier_hint = "C_PRESENCE_LIKELY"
    elif (p.width or 0) >= 1280 and not soft:
        p.initial_tier_hint = "A_OR_B_PENDING_MEASUREMENT"
    else:
        p.initial_tier_hint = "B_PENDING_MEASUREMENT"


def write_report(profiles: list[CameraProfile], problems: list[str],
                 catalogue_source: str, out: Path) -> None:
    reachable = [p for p in profiles if p.reachable]
    unreachable = [p for p in profiles if not p.reachable]
    codecs = sorted({p.codec for p in reachable if p.codec})
    resolutions = sorted({f"{p.width}x{p.height}" for p in reachable if p.width})

    lines = [
        "# Real Data Readiness Report", "",
        f"**Generated:** {datetime.now(UTC).isoformat(timespec='seconds')}  ",
        f"**Catalogue:** `{catalogue_source}`  ",
        "**Dataset label:** GOVERNMENT (characterisation only — no accuracy "
        "claim is made in this document)", "",
        "## Summary", "",
        f"- cameras in catalogue: **{len(profiles)}**",
        f"- reachable and decoded: **{len(reachable)}**",
        f"- unreachable: **{len(unreachable)}**",
        f"- distinct codecs: {', '.join(codecs) or 'none'}",
        f"- distinct resolutions: {', '.join(resolutions) or 'none'}",
        f"- structural problems: **{len(problems)}**", "",
    ]

    if problems:
        lines += ["## Structural problems", "",
                  "Reported, not skipped. Each needs a decision before evaluation.", ""]
        lines += [f"- {p}" for p in problems] + [""]

    lines += ["## Per-camera profile", "",
              "| Camera | Codec | Resolution | Declared fps | Measured fps | "
              "Lum | Sharp | Activity | Tier hint | Warnings |",
              "|---|---|---|---:|---:|---:|---:|---:|---|---|"]
    for p in sorted(profiles, key=lambda x: x.camera_id):
        if not p.reachable:
            lines.append(f"| `{p.camera_id}` | — | — | — | — | — | — | — | "
                         f"**UNREACHABLE** | {p.error or ''} |")
            continue
        lines.append(
            f"| `{p.camera_id}` | {p.codec or '?'} | {p.width}x{p.height} | "
            f"{p.declared_fps or 0:.1f} | {p.measured_fps or 0:.1f} | "
            f"{p.mean_luminance or 0:.2f} | {p.mean_sharpness or 0:.2f} | "
            f"{p.scene_activity or 0:.2f} | {p.initial_tier_hint} | "
            f"{'; '.join(p.warnings) or '—'} |")

    lines += ["", "## What this report does and does not say", "",
              "**Does:** describes what was received — reachability, codecs, "
              "resolutions, measured frame rate against declared, timing "
              "behaviour, and coarse image statistics.", "",
              "**Does not:** state accuracy, or assign capability grades. A tier "
              "*hint* from a dozen frames is a starting point for compute "
              "allocation, not a measurement. Real grades require sustained "
              "observation across a diurnal cycle, and until then a camera's "
              "capability is `INSUFFICIENT_DATA`.", "",
              "## Next steps", "",
              "1. Resolve every structural problem above.",
              "2. Import the catalogue into the registry (`make government-import`).",
              "3. Run the pipeline for a sustained period to accumulate capability "
              "evidence and bootstrap the camera transition graph.",
              "4. Only then benchmark models, and report per-camera yield rather "
              "than a single headline number.", ""]
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", required=True,
                    help="URL (e.g. http://<host>/api/ingest) or local JSON file")
    ap.add_argument("--sample", type=int, default=12,
                    help="frames to decode per camera")
    ap.add_argument("--token", default=None, help="bearer token, if the API needs one")
    ap.add_argument("--offline", action="store_true",
                    help="validate the catalogue only; do not connect to streams")
    ap.add_argument("--report", default="docs/REAL_DATA_READINESS_REPORT.md")
    args = ap.parse_args()

    print(f"catalogue: {args.catalogue}")
    try:
        raw = load_catalogue(args.catalogue, token=args.token)
    except Exception as exc:
        print(f"FAILED to load catalogue: {type(exc).__name__}: {exc}")
        return 2

    entries = [normalise_entry(e) for e in raw]
    entries, problems = validate(entries)
    print(f"entries: {len(entries)}   structural problems: {len(problems)}")
    for p in problems[:10]:
        print(f"  ! {p}")

    profiles: list[CameraProfile] = []
    if args.offline:
        print("offline mode: catalogue validated, streams not probed")
        profiles = [CameraProfile(camera_id=e["camera_id"],
                                  source=e["rtsp_url"] or e["hls_url"] or "",
                                  error="not probed (offline mode)")
                    for e in entries]
    else:
        for i, e in enumerate(entries, 1):
            print(f"  [{i}/{len(entries)}] probing {e['camera_id']} …",
                  end=" ", flush=True)
            p = probe(e, samples=args.sample)
            profiles.append(p)
            print("ok" if p.reachable else f"UNREACHABLE ({p.error})")

    out_json = ROOT / "var" / "reports" / "camera_profiles.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(
        {"catalogue": args.catalogue,
         "generated": datetime.now(UTC).isoformat(),
         "dataset_label": "GOVERNMENT",
         "problems": problems,
         "profiles": [p.to_dict() for p in profiles]}, indent=2))

    report = ROOT / args.report
    write_report(profiles, problems, args.catalogue, report)
    print(f"\nreport   : {display(report, ROOT)}")
    print(f"profiles : {display(out_json, ROOT)}")

    reachable = sum(1 for p in profiles if p.reachable)
    if not args.offline and reachable == 0:
        print("\nNO CAMERA WAS REACHABLE — check credentials, network path and "
              "whether RTSP/8554 is permitted from this host.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
