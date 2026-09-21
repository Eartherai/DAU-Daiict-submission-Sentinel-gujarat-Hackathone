#!/usr/bin/env python3
"""Experiment: 15/30 Direct WHEP — sequential vs grouped vs staggered.

Does not brute-force reconnect. One headed Chromium. Credentials stay in
SENTINEL_GRID_* env / Authorization header. Never in URLs or JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured
from saakshya.live.grid import GridConfig
from tools.sentinel_direct_whep import (
    basic_authorization_header,
    measure_direct_wall,
    refuse_secrets,
    whep_url,
)

OUT = ROOT / "var/reports/final/live"
DIRECT_WHEP = [
    "cam01", "cam02", "cam03", "cam04", "cam05", "cam06",
    "cam12", "cam13", "cam14", "cam16", "cam18", "cam19",
    "cam20", "cam23", "cam26",
]
ALL30 = [f"cam{i:02d}" for i in range(1, 31)]

SEQ_JS = r"""
async ({endpoints, authHeader, perCameraMs, pauseMs, setupTimeoutMs}) => {
  const results = [];
  for (let i = 0; i < endpoints.length; i++) {
    const started = performance.now();
    const video = document.querySelector('#v0');
    video.srcObject = new MediaStream();
    let pc = null;
    const row = {i, httpStatus: null, first: null, error: null, ice: 'new'};
    try {
      pc = new RTCPeerConnection();
      pc.addEventListener('iceconnectionstatechange', () => {
        row.ice = pc.iceConnectionState;
      });
      pc.addTransceiver('video', {direction: 'recvonly'});
      pc.ontrack = (ev) => video.srcObject.addTrack(ev.track);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 1500);
        if (pc.iceGatheringState === 'complete') { clearTimeout(t); resolve(); }
        else pc.addEventListener('icegatheringstatechange', () => {
          if (pc.iceGatheringState === 'complete') { clearTimeout(t); resolve(); }
        });
      });
      const headers = {
        'Content-Type': 'application/sdp',
        'Accept': 'application/sdp',
      };
      if (authHeader) headers['Authorization'] = authHeader;
      const resp = await fetch(endpoints[i], {
        method: 'POST', headers, body: pc.localDescription.sdp,
        signal: AbortSignal.timeout(setupTimeoutMs),
      });
      row.httpStatus = resp.status;
      if (!resp.ok) throw new Error('WHEP ' + resp.status);
      await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
      await video.play().catch(() => {});
      const deadline = performance.now() + perCameraMs;
      while (performance.now() < deadline) {
        if (video.readyState >= 2 && video.videoWidth > 0 && row.first == null)
          row.first = performance.now() - started;
        await new Promise((r) => setTimeout(r, 120));
      }
      row.width = video.videoWidth;
      row.height = video.videoHeight;
      row.currentTime = video.currentTime || 0;
    } catch (e) {
      row.error = String(e && e.message || e);
    }
    try { if (pc) pc.close(); } catch (_) {}
    video.srcObject = null;
    results.push(row);
    await new Promise((r) => setTimeout(r, pauseMs));
  }
  return results;
}
"""


def inherit_from_pid(pid: int) -> None:
    try:
        raw = subprocess.check_output(["ps", "eww", "-p", str(pid)], text=True)
    except (OSError, subprocess.CalledProcessError):
        return
    for key in ("SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
                "SENTINEL_GRID_COOKIE", "GOOGLE_MAPS_API_KEY"):
        if os.environ.get(key):
            continue
        marker = key + "="
        i = raw.find(marker)
        if i < 0:
            continue
        val = raw[i + len(marker):].split(" ", 1)[0].strip()
        if val:
            os.environ[key] = val


def dump(name: str, payload: dict) -> Path:
    text = json.dumps(payload, indent=2, default=str)
    refuse_secrets(text)
    if "AIzaSy" in text:
        raise SystemExit("refusing maps-key-shaped token")
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def classify_tile(row: dict) -> str:
    if row.get("first") is not None:
        return "LIVE" if (row.get("currentTime") or 0) >= 0.4 else "PREVIEW"
    status = row.get("httpStatus")
    err = str(row.get("error") or "")
    if status in (401, 403) or "WHEP 401" in err or "WHEP 403" in err:
        return "SOURCE_AUTH_FAILURE"
    if status in (404, 405) or "WHEP 404" in err:
        return "WHEP_UNAVAILABLE"
    if "timeout" in err.lower():
        return "UPSTREAM_TIMEOUT"
    if status and int(status) >= 500:
        return "UPSTREAM_TIMEOUT"
    return "WHEP_UNAVAILABLE"


def measure_sequential(ids: list[str], *, per_s: float, pause_s: float) -> dict:
    from playwright.sync_api import sync_playwright

    cfg = GridConfig.from_env()
    endpoints = [whep_url(c, cfg) for c in ids]
    auth = basic_authorization_header()
    html = (
        "<!doctype html><html><body style='margin:0;background:#111'>"
        "<video id='v0' autoplay muted playsinline "
        "style='width:640px;height:360px;background:#000'></video>"
        "</body></html>"
    )
    t0 = time.monotonic()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--use-angle=metal",
                  "--autoplay-policy=no-user-gesture-required",
                  "--disable-web-security"])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="domcontentloaded")
            rows = page.evaluate(
                SEQ_JS,
                {
                    "endpoints": endpoints,
                    "authHeader": auth,
                    "perCameraMs": int(per_s * 1000),
                    "pauseMs": int(pause_s * 1000),
                    "setupTimeoutMs": 12000,
                },
            )
        finally:
            browser.close()
    cams = []
    classes: dict[str, int] = {}
    for cid, row in zip(ids, rows, strict=True):
        klass = classify_tile(row)
        classes[klass] = classes.get(klass, 0) + 1
        cams.append({
            "camera_id": cid,
            "httpStatus": row.get("httpStatus"),
            "first_frame_ms": row.get("first"),
            "ice": row.get("ice"),
            "error": row.get("error"),
            "width": row.get("width"),
            "height": row.get("height"),
            "class": klass,
            "group": "DIRECT_WHEP_HISTORICAL" if cid in DIRECT_WHEP else "OTHER",
        })
    return {
        "mode": "sequential",
        "seconds_per_camera": per_s,
        "pause_s": pause_s,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "visible": sum(1 for c in cams if c["first_frame_ms"] is not None),
        "classes": classes,
        "cameras": cams,
        "label": "MEASURED_REAL",
        "note": "One session at a time. Closes before the next. Not a 30-wide wall.",
    }


def wall_pass(ids: list[str], *, seconds: float, conc: int, label: str) -> dict:
    cfg = GridConfig.from_env()
    endpoints = [whep_url(c, cfg) for c in ids]
    auth = basic_authorization_header()
    t0 = time.monotonic()
    wall = measure_direct_wall(
        endpoints, auth_header=auth, seconds=seconds,
        negotiate_concurrency=conc, retries=0)
    tiles = wall.get("tiles") or []
    cams = []
    classes: dict[str, int] = {}
    visible = 0
    for cid, tile in zip(ids, tiles, strict=False):
        row = {
            "first": tile.get("first") or tile.get("first_frame_ms"),
            "httpStatus": tile.get("httpStatus"),
            "error": tile.get("error"),
            "currentTime": tile.get("currentTime"),
        }
        klass = classify_tile(row)
        classes[klass] = classes.get(klass, 0) + 1
        if row["first"] is not None:
            visible += 1
        cams.append({
            "camera_id": cid,
            "class": klass,
            "first_frame_ms": row["first"],
            "httpStatus": row["httpStatus"],
            "ice": tile.get("ice"),
            "error": tile.get("error"),
        })
    return {
        "mode": label,
        "n": len(ids),
        "seconds": seconds,
        "negotiate_concurrency": conc,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "visible": visible,
        "classes": classes,
        "cameras": cams,
        "label": "MEASURED_REAL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inherit-pid", type=int, default=0)
    parser.add_argument("--skip-sequential", action="store_true")
    parser.add_argument("--per-s", type=float, default=4.0)
    parser.add_argument("--pause-s", type=float, default=0.8)
    args = parser.parse_args()
    if args.inherit_pid:
        inherit_from_pid(args.inherit_pid)
    if not configured():
        dump("coverage_blocked.json", {
            "status": "BLOCKED_EXTERNAL",
            "reason": "SENTINEL_GRID credentials missing",
            "timestamp_utc": datetime.now(UTC).isoformat(),
        })
        print("BLOCKED_EXTERNAL")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    pack: dict = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "direct_whep_historical": DIRECT_WHEP,
        "passes": [],
    }
    if not args.skip_sequential:
        print("=== PASS sequential 30 ===", flush=True)
        seq = measure_sequential(ALL30, per_s=args.per_s, pause_s=args.pause_s)
        dump("coverage_sequential.json", seq)
        pack["passes"].append({"name": "sequential_30", **{
            k: seq[k] for k in ("visible", "classes", "elapsed_s")}})
        print(f"  visible {seq['visible']}/30 {seq['classes']}", flush=True)

    print("=== PASS groups of 10 ===", flush=True)
    group_rows = []
    for start in (0, 10, 20):
        ids = ALL30[start:start + 10]
        row = wall_pass(ids, seconds=12.0, conc=3, label=f"group10_{start+1}-{start+10}")
        group_rows.append(row)
        print(f"  {row['mode']} visible {row['visible']}/10 {row['classes']}", flush=True)
        time.sleep(1.5)
    dump("coverage_groups10.json", {"rows": group_rows, "label": "MEASURED_REAL"})
    pack["passes"].append({
        "name": "groups_of_10",
        "visible": [r["visible"] for r in group_rows],
    })

    print("=== PASS 15 historical Direct WHEP conc=4 ===", flush=True)
    d15 = wall_pass(DIRECT_WHEP, seconds=20.0, conc=4, label="direct15_simultaneous")
    dump("coverage_direct15.json", d15)
    pack["passes"].append({"name": "direct15", "visible": d15["visible"],
                           "classes": d15["classes"]})
    print(f"  visible {d15['visible']}/15 {d15['classes']}", flush=True)
    time.sleep(2)

    print("=== PASS 15 Direct WHEP staggered conc=1 ===", flush=True)
    d15s = wall_pass(DIRECT_WHEP, seconds=25.0, conc=1, label="direct15_staggered")
    dump("coverage_direct15_stagger.json", d15s)
    pack["passes"].append({"name": "direct15_stagger", "visible": d15s["visible"],
                           "classes": d15s["classes"]})
    print(f"  visible {d15s['visible']}/15 {d15s['classes']}", flush=True)

    dump("coverage_matrix.json", pack)
    print("wrote", OUT / "coverage_matrix.json", flush=True)
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
