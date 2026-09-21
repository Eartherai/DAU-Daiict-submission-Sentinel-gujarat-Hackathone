#!/usr/bin/env python3
"""Fresh live government-feed acceptance. Does not redesign the media path.

Uses Direct Sentinel WHEP for the browser plane and RTSP/TCP for AI-plane
health. Never publishes to a local gateway. Never substitutes synthetic
cameras in GOVERNMENT mode. Credentials stay in SENTINEL_GRID_* env vars.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured
from saakshya.live.grid import (
    CatalogueUnavailable,
    GridConfig,
    fetch_catalogue,
)
from tools.phase14_source_census import (
    CAMERAS as FALLBACK_CAMERAS,
)
from tools.phase14_source_census import (
    probe_rtsp_layers,
    tcp_probe,
)
from tools.sentinel_direct_whep import (
    basic_authorization_header,
    measure_direct_wall,
    refuse_secrets,
    safe,
    summarize,
    whep_url,
)

OUT = ROOT / "var/reports/final/live"
HOST = "103.250.160.189"


def _maps_key() -> str:
    return (os.environ.get("GOOGLE_MAPS_API_KEY")
            or os.environ.get("SAAKSHYA_GOOGLE_MAPS_KEY") or "").strip()


def refuse_all(blob: str) -> None:
    refuse_secrets(blob)
    key = _maps_key()
    if key and key in blob:
        raise SystemExit("refusing maps key plaintext in artifact")
    if "AIzaSy" in blob:
        raise SystemExit("refusing maps-key-shaped token in artifact")


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return float(s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f))


def operator_class(rtsp: dict, tile: dict | None) -> str:
    rtsp_live = bool(rtsp.get("rtsp_live")) or (
        ((rtsp.get("pyav") or {}).get("frames") or 0) >= 1)
    tile = tile or {}
    whep_ok = tile.get("first") is not None or tile.get("first_frame_ms") is not None
    ice = tile.get("ice")
    reconnects = int(tile.get("reconnects") or tile.get("retries") or 0)
    freezes = int(tile.get("freezes") or 0)
    lost = int(tile.get("packetsLost") or 0)
    if reconnects and not whep_ok and not rtsp_live:
        return "RECONNECTING"
    if rtsp_live and not whep_ok:
        return "RTSP_ONLY_AI"
    if whep_ok:
        if freezes > 3 or lost > 10 or ice not in {None, "connected", "completed"}:
            return "DEGRADED"
        fps = tile.get("effective_fps") or tile.get("fps")
        if fps is not None and float(fps) < 8:
            return "PREVIEW"
        ct = float(tile.get("currentTime") or 0)
        if ct and ct < 0.45 * float(tile.get("target_s") or ct or 1):
            return "PREVIEW"
        return "LIVE"
    return "NO_SIGNAL"


def camera_ids() -> tuple[list[str], str]:
    try:
        cams = fetch_catalogue()
        ids = [c.camera_id for c in cams if c.camera_id]
        if ids:
            return ids[:30], "CATALOGUE"
    except CatalogueUnavailable:
        pass
    except Exception:
        pass
    return list(FALLBACK_CAMERAS), "DISCOVERED_NOT_CATALOGUE"


def write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, default=str)
    refuse_all(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-wall", action="store_true")
    parser.add_argument("--walls", default="12:30,16:30,25:30,30:30,30:60,30:120")
    parser.add_argument("--rtsp-workers", type=int, default=4)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if not configured():
        write_json(OUT / "blocked.json", {
            "status": "BLOCKED_EXTERNAL",
            "reason": "SENTINEL_GRID credentials are not configured in this process",
            "label": "EXTERNAL_DEPENDENCY",
            "timestamp_utc": datetime.now(UTC).isoformat(),
        })
        print("BLOCKED_EXTERNAL: sentinel credentials not configured")
        return 2

    cfg = GridConfig.from_env()
    ids, source = camera_ids()
    print(f"camera set: {len(ids)} from {source}", flush=True)

    tcp_rtsp = tcp_probe(HOST, 8554)
    tcp_whep = tcp_probe(HOST, 8889)
    print(f"tcp 8554={tcp_rtsp.get('ok')} 8889={tcp_whep.get('ok')}", flush=True)

    rtsp_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=args.rtsp_workers) as ex:
        futs = {ex.submit(probe_rtsp_layers, cam, attempts=1): cam for cam in ids}
        for fut in as_completed(futs):
            cam = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"camera_id": cam, "rtsp_live": False,
                       "first_fail": "CLIENT_ERROR",
                       "pyav": {"frames": 0, "error": safe(str(exc))}}
            rtsp_map[cam] = row
            print(f"  rtsp {cam} live={row.get('rtsp_live')} "
                  f"codec={row.get('codec')} fail={row.get('first_fail')}",
                  flush=True)

    auth = basic_authorization_header()
    walls: list[dict] = []
    if not args.skip_wall:
        for spec in args.walls.split(","):
            spec = spec.strip()
            if not spec:
                continue
            n_s, sec_s = spec.split(":", 1)
            n, seconds = int(n_s), float(sec_s)
            cams = ids[:n]
            endpoints = [whep_url(c, cfg) for c in cams]
            print(f"=== wall n={n} {seconds}s (no duplicate publishers) ===",
                  flush=True)
            t0 = time.monotonic()
            wall = measure_direct_wall(
                endpoints, auth_header=auth, seconds=seconds,
                negotiate_concurrency=4, retries=1)
            summary = summarize(
                cams, wall, seconds=seconds, path_label="DIRECT_SENTINEL_WHEP")
            tiles = summary.get("tiles") or []
            classes: dict[str, int] = {}
            per: list[dict] = []
            for i, cam in enumerate(cams):
                tile = tiles[i] if i < len(tiles) else {}
                tile = {**tile, "target_s": seconds}
                klass = operator_class(rtsp_map.get(cam) or {}, tile)
                classes[klass] = classes.get(klass, 0) + 1
                pyav = (rtsp_map.get(cam) or {}).get("pyav") or {}
                per.append({
                    "camera_id": cam,
                    "domain": "GOVERNMENT",
                    "codec": (rtsp_map.get(cam) or {}).get("codec") or pyav.get("codec"),
                    "resolution": (tile.get("width") and tile.get("height")
                    and f"{tile.get('width')}x{tile.get('height')}")
                    or pyav.get("wh"),
                    "rtsp_state": "LIVE" if (
                        (rtsp_map.get(cam) or {}).get("rtsp_live")
                        or (pyav.get("frames") or 0) >= 1) else "DOWN",
                    "whep_state": tile.get("ice") or tile.get("verdict"),
                    "browser_state": tile.get("verdict"),
                    "first_frame_ms": tile.get("first_frame_ms"),
                    "current_fps": tile.get("effective_fps"),
                    "frames_decoded": tile.get("framesDecoded"),
                    "frames_dropped": tile.get("framesDropped"),
                    "packet_loss": tile.get("packetsLost"),
                    "freeze_count": tile.get("freezes"),
                    "reconnect_count": tile.get("reconnects") or 0,
                    "last_pts": tile.get("currentTime"),
                    "health_state": klass,
                    "label": "MEASURED_REAL",
                })
            firsts = [t["first_frame_ms"] for t in per
                      if t.get("first_frame_ms") is not None]
            live_n = classes.get("LIVE", 0)
            preview_n = classes.get("PREVIEW", 0)
            row = {
                "layout": n,
                "seconds": seconds,
                "camera_source": source,
                "label": "MEASURED_REAL",
                "wall_startup_s": round(time.monotonic() - t0, 3),
                "browser_visible": live_n + preview_n,
                "FULL": live_n,
                "PREVIEW": preview_n,
                "RTSP_ONLY_AI": classes.get("RTSP_ONLY_AI", 0),
                "NO_SIGNAL": classes.get("NO_SIGNAL", 0),
                "DEGRADED": classes.get("DEGRADED", 0),
                "RECONNECTING": classes.get("RECONNECTING", 0),
                "classes": classes,
                "first_frame_p50_ms": pct(firsts, 50),
                "first_frame_p95_ms": pct(firsts, 95),
                "promotion_p50_ms": None,
                "promotion_p95_ms": None,
                "cpu_percent": psutil.cpu_percent(interval=0.2),
                "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
                "gpu": (wall.get("gpu") if isinstance(wall.get("gpu"), dict)
                        else "NOT_MEASURED"),
                "browser": wall.get("browser"),
                "overall": summary.get("overall"),
                "cameras": per,
                "note": ("Promotion percentiles are NOT_MEASURED: this wall "
                         "does not run the adaptive scheduler promotion clock."),
            }
            if row["gpu"] is None or row["gpu"] == {}:
                row["gpu"] = "NOT_MEASURED"
            walls.append(row)
            write_json(OUT / f"wall_{n}_{int(seconds)}s.json", row)
            print(f"  visible={row['browser_visible']} LIVE={live_n} "
                  f"PREVIEW={preview_n} RTSP_ONLY_AI={row['RTSP_ONLY_AI']} "
                  f"NO_SIGNAL={row['NO_SIGNAL']}", flush=True)

    census = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED_REAL",
        "camera_source": source,
        "tcp_rtsp": {"ok": tcp_rtsp.get("ok"), "ms": tcp_rtsp.get("ms")},
        "tcp_whep": {"ok": tcp_whep.get("ok"), "ms": tcp_whep.get("ms")},
        "n_cameras": len(ids),
        "rtsp_live": sum(
            1 for r in rtsp_map.values()
            if r.get("rtsp_live") or ((r.get("pyav") or {}).get("frames") or 0) >= 1),
        "cameras": [
            {
                "camera_id": cam,
                "domain": "GOVERNMENT",
                "codec": (rtsp_map.get(cam) or {}).get("codec"),
                "rtsp_live": bool((rtsp_map.get(cam) or {}).get("rtsp_live") or (
                    ((rtsp_map.get(cam) or {}).get("pyav") or {}).get("frames") or 0) >= 1),
                "first_fail": (rtsp_map.get(cam) or {}).get("first_fail"),
                "pyav_frames": ((rtsp_map.get(cam) or {}).get("pyav") or {}).get("frames"),
                "pyav_ms": ((rtsp_map.get(cam) or {}).get("pyav") or {}).get("ms"),
            }
            for cam in ids
        ],
        "walls": [
            {k: w[k] for k in (
                "layout", "seconds", "browser_visible", "FULL", "PREVIEW",
                "RTSP_ONLY_AI", "NO_SIGNAL", "DEGRADED", "first_frame_p50_ms",
                "first_frame_p95_ms", "cpu_percent", "overall")}
            for w in walls
        ],
    }
    write_json(OUT / "census.json", census)
    print("wrote", OUT / "census.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
