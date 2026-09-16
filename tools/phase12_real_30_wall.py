#!/usr/bin/env python3
"""Phase 12 — Real 30-camera Sentinel direct WHEP wall progression.

Catalogue session (SENTINEL_GRID_COOKIE) not required for WHEP probes, but
without it camera list is NOT authoritative — marked probe_not_catalogue.

Credentials: Authorization Basic header only. Never in URL/stdout/JSON.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402
from saakshya.live.grid import GridConfig, has_credential  # noqa: E402
from tools.sentinel_direct_whep import (  # noqa: E402
    basic_authorization_header, measure_direct_wall, summarize,
    refuse_secrets, safe, whep_url,
)

OUT = ROOT / "var/reports/phase10/performance"
HOST = "103.250.160.189"

# Estate probe range used only when catalogue unavailable (documented sandbox ids).
PROBE_IDS = [f"cam{i:02d}" for i in range(1, 31)]

# Prefer previously strong H.264 first for walls
H264_PRIORITY = [
    "cam01", "cam02", "cam05", "cam04", "cam13",
    "cam14", "cam19", "cam15", "cam11", "cam03",
]
HEVC_CANDIDATES = ["cam06", "cam12", "cam17"]


def enumerate_whep(ids: list[str], auth: str, *, timeout: float = 8.0) -> list[dict]:
    """Lightweight WHEP POST probe — classify reachable endpoints. No MediaMTX."""
    # Minimal but browser-like enough SDP
    sdp = (
        "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
        "a=group:BUNDLE 0\r\na=msid-semantic: WMS\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96 97\r\nc=IN IP4 0.0.0.0\r\n"
        "a=rtcp:9 IN IP4 0.0.0.0\r\n"
        "a=ice-ufrag:saak\r\na=ice-pwd:saaksaaksaaksaaksaaksaak\r\n"
        "a=fingerprint:sha-256 "
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:"
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00\r\n"
        "a=setup:actpass\r\na=mid:0\r\na=recvonly\r\na=rtcp-mux\r\n"
        "a=rtpmap:96 H264/90000\r\na=rtpmap:97 H265/90000\r\n"
    )
    rows = []
    for cid in ids:
        url = f"http://{HOST}:8889/stream/{cid}/whep"
        tcp_ok = False
        try:
            with socket.create_connection((HOST, 8889), timeout=3):
                tcp_ok = True
        except Exception as exc:
            rows.append({
                "camera_id": cid, "tcp_8889": False,
                "whep_status": None, "whep_available": False,
                "error": safe(f"{type(exc).__name__}"),
                "endpoint_safe": url, "source": "probe_not_catalogue",
            })
            continue
        status = None
        sdp_ok = False
        err = None
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(
                url, data=sdp.encode(), method="POST",
                headers={
                    "Content-Type": "application/sdp",
                    "Accept": "application/sdp",
                    "Authorization": auth,
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status = r.status
                body = r.read(40)
                sdp_ok = body.startswith(b"v=")
        except urllib.error.HTTPError as e:
            status = e.code
            err = f"HTTP {e.code}"
        except Exception as exc:
            err = safe(f"{type(exc).__name__}: {exc}")
        rows.append({
            "camera_id": cid,
            "tcp_8889": tcp_ok,
            "whep_status": status,
            "whep_available": status in {200, 201} and sdp_ok,
            "sdp_answer": sdp_ok,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "error": err,
            "endpoint_safe": url,
            "codec_hint": "hevc_candidate" if cid in HEVC_CANDIDATES else "h264_priority_or_unknown",
            "source": "probe_not_catalogue",
        })
        print(
            f"  probe {cid} status={status} available={rows[-1]['whep_available']}",
            flush=True,
        )
    return rows


def pick_cameras(enum_rows: list[dict], n: int) -> list[str]:
    avail = {r["camera_id"] for r in enum_rows if r.get("whep_available")}
    ordered: list[str] = []

    def add(cid: str) -> None:
        if cid not in ordered:
            ordered.append(cid)

    # Prefer known-strong H.264 that are available (or all strong if no enum)
    for c in H264_PRIORITY:
        if not avail or c in avail:
            add(c)
        if len(ordered) >= n:
            return ordered[:n]
    for c in PROBE_IDS:
        if not avail or c in avail:
            add(c)
        if len(ordered) >= n:
            return ordered[:n]
    # Last resort: unique fill from priority+probe
    for c in H264_PRIORITY + PROBE_IDS:
        add(c)
        if len(ordered) >= n:
            break
    return ordered[:n]


def unique_cameras(n: int) -> list[str]:
    """Deterministic unique cam list without catalogue."""
    return pick_cameras([], n)


def run_level(cams: list[str], auth: str, cfg: GridConfig, *,
              seconds: float, conc: int) -> dict:
    endpoints = [whep_url(c, cfg) for c in cams]
    print(f"\n=== REAL DIRECT WHEP n={len(cams)} conc={conc} {seconds}s ===", flush=True)
    print("cameras", cams, flush=True)
    wall = measure_direct_wall(
        endpoints, auth_header=auth, seconds=seconds,
        negotiate_concurrency=conc, retries=1, setup_timeout_ms=22000,
    )
    row = summarize(cams, wall, seconds=seconds, path_label="DIRECT_SENTINEL_WHEP_REAL")
    row["camera_ids"] = cams
    row["negotiate_concurrency"] = conc
    row["source_label"] = "MEASURED_REAL"
    print(json.dumps({
        "n": len(cams), "overall": row["overall"],
        "summary": row["wall_summary"],
        "verdicts": {t["camera_id"]: t["verdict"] for t in row["tiles"]},
    }), flush=True)
    return row


def write_cert(payload: dict) -> None:
    levels = payload.get("levels") or []
    lines = [
        "# Real 30-camera WHEP certification",
        "",
        f"Timestamp UTC: `{payload['timestamp_utc']}`",
        "",
        "## Labels",
        "",
        "- **MEASURED_REAL** — direct Sentinel WHEP on government endpoints",
        "- **MEASURED_SYNTHETIC** — prior local synthetic browser ceiling (not mixed below)",
        "- **DESIGNED** — scheduler / UX states",
        "- **NOT_AUTHORITATIVE** — camera list from WHEP probe (catalogue session unavailable)",
        "",
        "## Catalogue",
        "",
        f"Authoritative `/api/ingest`: **{payload.get('catalogue_authoritative')}**  ",
        f"Session material configured: **{payload.get('catalogue_session_configured')}**  ",
        "",
        payload.get("catalogue_note", ""),
        "",
        "## Enumerated WHEP-available cameras (probe)",
        "",
        f"Count available: **{payload.get('whep_available_count')}**  ",
        f"IDs: `{', '.join(payload.get('whep_available_ids') or [])}`",
        "",
        "## Progression (MEASURED_REAL)",
        "",
        "| N | Overall | PASS | AMBER | FAIL | first p50 | first p95 | neg p50 | Cameras |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for lv in levels:
        ws = lv.get("wall_summary") or {}
        lines.append(
            f"| {lv.get('n_cameras')} | **{lv.get('overall')}** | "
            f"{ws.get('PASS')} | {ws.get('AMBER')} | {ws.get('FAIL')} | "
            f"{ws.get('first_frame_ms_p50')} | {ws.get('first_frame_ms_p95')} | "
            f"{ws.get('negotiation_ms_p50')} | "
            f"{','.join(lv.get('camera_ids') or [])} |"
        )
    lines += [
        "",
        "## Per-level tile detail",
        "",
    ]
    for lv in levels:
        lines.append(f"### n={lv.get('n_cameras')} — {lv.get('overall')}")
        lines.append("")
        lines.append(
            "| Cam | Verdict | HTTP | First ms | Neg ms | CT | FPS | Freezes | Drop | Lost | Res |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for t in lv.get("tiles") or []:
            lines.append(
                f"| {t.get('camera_id')} | {t.get('verdict')} | "
                f"{t.get('whep_http_status')} | {t.get('first_frame_ms')} | "
                f"{t.get('negotiation_ms')} | {t.get('currentTime')} | "
                f"{t.get('effective_fps')} | {t.get('freezes')} | "
                f"{t.get('framesDropped')} | {t.get('packetsLost')} | "
                f"{t.get('width')}x{t.get('height')} |"
            )
        gpu = ((lv.get("browser_wall") or {}).get("gpu") or {}).get("renderer")
        res = (lv.get("browser_wall") or {}).get("resources")
        lines.append("")
        lines.append(f"GPU: `{gpu}`  Resources: `{res}`")
        lines.append("")

    peak = payload.get("peak_pass_tiles")
    max_n = payload.get("max_operable_n")
    lines += [
        "## Interpretation",
        "",
        f"- Peak simultaneous PASS tiles: **{peak}**",
        f"- Max operable wall size (PASS or AMBER overall): **{max_n}**",
        "",
        payload.get("recommendation", ""),
        "",
        "## Scheduler (DESIGNED)",
        "",
        "Tiers: PRIMARY (full WHEP) / SECONDARY (full WHEP up to measured band) / "
        "PREVIEW (live lower-cost when WHEP unsustainable). "
        "States: LIVE, PREVIEW, CONNECTING, DEGRADED, RECONNECTING, NO SIGNAL.",
        "",
        "## Synthetic ceiling (separate — MEASURED_SYNTHETIC)",
        "",
        "Prior headed Metal synthetic: 16/16 PASS; 20=19P; 24=19P; 30=18P. "
        "Not mixed into real tables above.",
        "",
        "## 50-camera story (DESIGNED)",
        "",
        "30 real Sentinel + 20 synthetic/control registry entries. "
        "Do **not** claim 50 government feeds.",
        "",
        "## Security",
        "",
        "No credentials in artifacts. Authorization Basic header only.",
        "",
        f"Machine-readable: `{payload.get('artifact')}`",
        "",
    ]
    md = "\n".join(lines) + "\n"
    refuse_secrets(md)
    (ROOT / "reports/REAL_30_CAMERA_WHEP_CERTIFICATION.md").write_text(md)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="+", type=int,
                        default=[1, 4, 8, 12, 16, 20, 24, 30])
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--negotiate-concurrency", type=int, default=4)
    parser.add_argument("--skip-enum", action="store_true")
    parser.add_argument("--out", type=Path,
                        default=OUT / "phase12_real_30_progression.json")
    args = parser.parse_args()

    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = GridConfig.from_env()
    auth = basic_authorization_header()

    print("=== catalogue / session ===", flush=True)
    cat_session = has_credential()
    print(f"catalogue_session_configured={cat_session}", flush=True)

    enum_rows: list[dict] = []
    if not args.skip_enum:
        print("=== WHEP enumerate cam01–cam30 (NOT authoritative catalogue) ===", flush=True)
        enum_rows = enumerate_whep(PROBE_IDS, auth)
    avail = [r["camera_id"] for r in enum_rows if r.get("whep_available")]

    levels_out = []
    peak_pass = 0
    operable = []
    for n in args.levels:
        cams = pick_cameras(enum_rows, n) if enum_rows else unique_cameras(n)
        # Enforce uniqueness (defence in depth)
        seen = set()
        cams = [c for c in cams if not (c in seen or seen.add(c))]
        if len(cams) < n:
            print(f"only {len(cams)} unique cams for requested n={n}", flush=True)
        row = run_level(
            cams, auth, cfg, seconds=args.seconds,
            conc=args.negotiate_concurrency,
        )
        levels_out.append(row)
        (OUT / f"phase12_real_n{len(cams)}.json").write_text(
            json.dumps(row, indent=2) + "\n"
        )
        ws = row.get("wall_summary") or {}
        peak_pass = max(peak_pass, int(ws.get("PASS") or 0))
        if row.get("overall") in {"PASS", "AMBER"}:
            operable.append(len(cams))

    # Recommendation
    if peak_pass >= 16:
        rec = (
            f"Real direct WHEP sustains ≥{peak_pass} PASS tiles. "
            "PRIMARY/SECONDARY use direct WHEP up to measured band; "
            "remaining tiles use adaptive live preview / reconnect."
        )
    elif peak_pass >= 8:
        rec = (
            f"Real direct WHEP peak PASS={peak_pass}. "
            "Use adaptive scheduler: full WHEP for focus band; "
            "PREVIEW for remainder — do not hardcode 8 forever."
        )
    else:
        rec = f"Real peak PASS={peak_pass}; isolate source failures and retry."

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED_REAL",
        "catalogue_authoritative": False,
        "catalogue_session_configured": cat_session,
        "catalogue_note": (
            "SENTINEL_GRID_COOKIE/TOKEN not configured. "
            "Camera IDs from WHEP probe of documented cam01–cam30 pattern — "
            "NOT authoritative catalogue."
        ),
        "enumeration": enum_rows,
        "whep_available_count": len(avail),
        "whep_available_ids": avail,
        "levels": levels_out,
        "peak_pass_tiles": peak_pass,
        "max_operable_n": max(operable) if operable else 0,
        "recommendation": rec,
        "artifact": str(args.out.resolve().relative_to(ROOT.resolve())),
        "credentials_in_artifact": False,
    }
    blob = json.dumps(payload, indent=2) + "\n"
    refuse_secrets(blob)
    args.out.write_text(blob)
    write_cert(payload)
    print(json.dumps({
        "peak_pass": peak_pass,
        "max_operable": payload["max_operable_n"],
        "available": len(avail),
        "out": str(args.out),
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
