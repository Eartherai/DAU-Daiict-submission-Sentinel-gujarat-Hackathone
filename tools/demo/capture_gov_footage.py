#!/usr/bin/env python3
"""Capture government RTSP sequentially; register separate, labelled recordings.

Credentials come only from the existing environment injection. No URL or raw
FFmpeg exception is logged. A 401 stops the entire batch without retrying.
Use --register-only to register already captured files without any network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import time
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from saakshya.live.credentials import credentialed  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
CAM_ID = re.compile(r"cam\d{2}\Z")


class CaptureFailure(RuntimeError):
    pass


class Unauthorized(CaptureFailure):
    pass


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture_one(cam: dict, media: Path, seconds: float, *, local_source: Path | None = None) -> dict:
    """One bounded attempt. local_source is an explicitly synthetic offline test."""
    import av

    cid = cam["camera_id"]
    if not CAM_ID.fullmatch(cid) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("expected camNN and a positive finite duration")
    media.mkdir(parents=True, exist_ok=True)
    target = media / f"GOVREC-{cid}.mp4"
    manifest_path = target.with_suffix(".manifest.json")
    if target.exists() or manifest_path.exists():
        raise CaptureFailure("recording already exists; choose a new media directory")
    tmp = target.with_suffix(".partial.mp4")
    start = datetime.now(IST)
    count = 0
    try:
        source = str(local_source) if local_source else credentialed(cam["rtsp_url"], required=True)
        # Capture FFmpeg logs in memory only. They can contain the authority.
        with av.logging.Capture(local=True):
            with av.open(source, options={} if local_source else {"rtsp_transport": "tcp"},
                         timeout=(15, 15)) as src:
                vs = src.streams.video[0]
                rate = vs.average_rate or vs.guessed_rate
                if not rate or not 0 < float(rate) <= 240:
                    raise CaptureFailure("source frame rate unavailable")
                with av.open(str(tmp), "w", options={"movflags": "+faststart"}) as out:
                    enc = out.add_stream("libx264", rate=rate)
                    enc.width = vs.codec_context.width
                    enc.height = vs.codec_context.height
                    enc.pix_fmt = "yuv420p"
                    enc.options = {"preset": "veryfast", "crf": "18"}
                    enc.time_base = Fraction(1, 90000)
                    first_pts = None
                    last_pts = -1.0
                    for frame in src.decode(video=0):
                        timestamp = float(frame.time) if frame.time is not None else count / float(rate)
                        if first_pts is None:
                            first_pts = timestamp
                        pts = timestamp - first_pts
                        if pts >= seconds:
                            break
                        if pts <= last_pts:
                            raise CaptureFailure("non-monotonic source timestamps")
                        picture = frame.reformat(format="yuv420p")
                        picture.pts = round(pts * 90000)
                        picture.time_base = enc.time_base
                        for packet in enc.encode(picture):
                            out.mux(packet)
                        last_pts = pts
                        count += 1
                        if time.time() - start.timestamp() > seconds + 45:
                            raise CaptureFailure("capture deadline exceeded")
                    for packet in enc.encode():
                        out.mux(packet)
        if count < 2:
            raise CaptureFailure("too few decoded frames")
        if not local_source and last_pts + 2 / float(rate) < seconds:
            raise CaptureFailure("stream ended before the requested capture duration")
        result = {
            "camera_id": f"GOVREC-{cid}", "source_camera_id": cid,
            "source_domain": "ARCHIVAL_REPLAY", "synthetic": local_source is not None,
            "label": "SYNTHETIC OFFLINE TEST" if local_source else "RECORDED GOVERNMENT FOOTAGE",
            "capture_start_ist": start.isoformat(), "capture_end_ist": datetime.now(IST).isoformat(),
            "timestamp_basis": "platform capture window; not the original scene date",
            "frames": count, "fps": float(rate), "fps_fraction": str(rate),
            "duration_s": last_pts + 1 / float(rate), "width": enc.width, "height": enc.height,
            "source_url": "<redacted>", "sha256": digest(tmp), "file": target.name,
        }
        tmp.replace(target)
        manifest_path.write_text(json.dumps(result, indent=2) + "\n")
        return result
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        # Never propagate the original exception: PyAV includes the open URL.
        if "401" in str(exc) or "unauthorized" in str(exc).lower():
            raise Unauthorized("credentials rejected (401); batch stopped") from None
        raise CaptureFailure("capture failed (details suppressed to protect credentials)") from None


def capture_batch(cams, media, seconds, *, retries=2, stagger=2.0, sleep=time.sleep):
    results = []
    for i, cam in enumerate(cams):
        if i:
            sleep(stagger)
        for attempt in range(retries + 1):
            try:
                results.append(capture_one(cam, media, seconds))
                print(f"{cam['camera_id']}: recorded", flush=True)
                break
            except Unauthorized:
                raise
            except CaptureFailure:
                if attempt == retries:
                    raise CaptureFailure(f"{cam['camera_id']}: capture failed after bounded retries") from None
                sleep(min(30, 2 ** (attempt + 1)))
    return results


def read_cameras(db: Path, ids: list[str]) -> list[dict]:
    """The source registry is always opened read-only, including the main tree."""
    with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = []
        for cid in ids:
            if not CAM_ID.fullmatch(cid):
                raise ValueError("camera ids must be camNN")
            row = conn.execute("SELECT * FROM cameras WHERE camera_id = ?", (cid,)).fetchone()
            if not row or row["source_domain"] != "GOVERNMENT" or not row["rtsp_url"]:
                raise ValueError(f"{cid}: requires a government RTSP registry row")
            rows.append(dict(row))
    return rows


def register(cam, media, store):
    cid = f"GOVREC-{cam['camera_id']}"
    clip = media / f"{cid}.mp4"
    manifest = json.loads(clip.with_suffix(".manifest.json").read_text())
    if (manifest["camera_id"] != cid or manifest["source_camera_id"] != cam["camera_id"]
            or manifest["sha256"] != digest(clip)):
        raise ValueError("recording manifest does not match file/source")
    fields = ("name", "district", "department", "site", "lat", "lon", "location_precision",
              "location_basis", "location_note", "owner", "region", "road")
    row = {k: cam[k] for k in fields if k in cam}
    row.update(camera_id=cid, source_domain="ARCHIVAL_REPLAY", integration_model="ARCHIVAL_REPLAY",
               enabled=True, codec="h264", width=manifest["width"], height=manifest["height"],
               rtsp_url=None, whep_url=None, hls_url=None,
               quality_note=f"{manifest['label']} · captured {manifest['capture_start_ist']} · source {cam['camera_id']}")
    store.upsert_camera(row)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cameras", nargs="+")
    ap.add_argument("--registry", type=Path, default=Path("var/live.db"))
    ap.add_argument("--minutes", type=float, default=2)
    ap.add_argument("--media", type=Path, default=Path("var/media"))
    ap.add_argument("--retries", type=int, choices=range(4), default=2)
    ap.add_argument("--stagger", type=float, default=2)
    ap.add_argument("--register-db", help="target SQLAlchemy database URL")
    ap.add_argument("--register-only", action="store_true")
    args = ap.parse_args()
    if not math.isfinite(args.minutes) or args.minutes <= 0 or not math.isfinite(args.stagger) or args.stagger < 1:
        ap.error("minutes must be positive and stagger at least one second")
    if args.register_only and not args.register_db:
        ap.error("--register-only requires --register-db")
    try:
        cams = read_cameras(args.registry, args.cameras)
        if not args.register_only:
            capture_batch(cams, args.media, args.minutes * 60, retries=args.retries, stagger=args.stagger)
        if args.register_db:
            from saakshya.store import Store
            store = Store(args.register_db)
            store.create_all()
            for cam in cams:
                register(cam, args.media, store)
                print(f"GOVREC-{cam['camera_id']}: registered ARCHIVAL_REPLAY")
    except Exception as exc:
        print("credentials rejected (401); batch stopped" if isinstance(exc, Unauthorized)
              else "capture/registration failed; check inputs and existing output files", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
