#!/usr/bin/env python3
"""Live PREVIEW representation probe — HLS from MediaMTX (not static stills).

Requires publishers already feeding MediaMTX.
Measures whether the variant playlist MEDIA-SEQUENCE advances (live motion).

MediaMTX binds HLS to a session query string. Stripping `?session=` yields 401.
This probe opens the master once, then polls the same sessioned variant URL.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/phase10/performance"


def resolve_variant(master_url: str) -> tuple[str, str]:
    """Return (variant_url_with_session, master_body)."""
    with urllib.request.urlopen(master_url, timeout=3) as r:
        body = r.read().decode("utf-8", "ignore")
    variant = None
    for ln in body.splitlines():
        if ln and not ln.startswith("#"):
            variant = ln.strip()  # keep ?session=
            break
    if not variant:
        raise RuntimeError("no variant in master playlist")
    base = master_url.rsplit("/", 1)[0]
    return f"{base}/{variant}", body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", nargs="+", default=["cam01", "cam02", "cam05"])
    parser.add_argument("--seconds", type=float, default=8)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    results = []
    for cam in args.cameras:
        master_url = f"http://127.0.0.1:8888/stream/gov-{cam}/index.m3u8"
        samples = []
        err = None
        variant_url = None
        t0 = time.monotonic()
        try:
            variant_url, _ = resolve_variant(master_url)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"[:160]
        while time.monotonic() - t0 < args.seconds:
            try:
                if variant_url is None:
                    variant_url, _ = resolve_variant(master_url)
                with urllib.request.urlopen(variant_url, timeout=3) as vr:
                    vb = vr.read().decode("utf-8", "ignore")
                segs = sum(1 for ln in vb.splitlines() if ln and not ln.startswith("#"))
                media_seq = None
                for ln in vb.splitlines():
                    if ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                        media_seq = int(ln.split(":", 1)[1])
                samples.append({
                    "t": round(time.monotonic() - t0, 2),
                    "segments": segs,
                    "media_sequence": media_seq,
                    "bytes": len(vb),
                    "session_kept": True,
                })
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"[:160]
                samples.append({"t": round(time.monotonic() - t0, 2), "error": err})
                # Re-resolve session on failure (expired / 401)
                variant_url = None
            time.sleep(1.0)
        seqs = [s.get("media_sequence") for s in samples if s.get("media_sequence") is not None]
        advanced = len(seqs) >= 2 and max(seqs) > min(seqs)
        results.append({
            "camera_id": cam,
            "transport": "HLS",
            "url_safe": f"/stream/gov-{cam}/index.m3u8",
            "live_sequence_advanced": advanced,
            "samples": samples,
            "verdict": "PASS" if advanced else ("FAIL" if err and not seqs else "AMBER"),
            "label": "MEASURED",
            "note": "HLS preview is live playlist advancement — not a static screenshot",
        })

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "results": results,
        "overall": (
            "PASS" if all(r["verdict"] == "PASS" for r in results)
            else ("AMBER" if any(r["verdict"] == "PASS" for r in results) else "FAIL")
        ),
    }
    out = OUT / "live_preview_hls.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "overall": payload["overall"],
        "cams": [(r["camera_id"], r["verdict"], r["live_sequence_advanced"])
                 for r in results],
    }))
    return 0 if payload["overall"] != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
