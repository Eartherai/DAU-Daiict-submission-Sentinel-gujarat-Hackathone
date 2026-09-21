#!/usr/bin/env python3
"""Measure local-relay wall: upstream ffmpeg vs local WHEP vs browser tiles.

Does not open Sentinel WHEP. Does not claim 30/30 unless the browser decoded
that many video elements. JPEG tiles are counted separately as PREVIEW.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BASE = os.environ.get("SAAKSHYA_BASE", "http://127.0.0.1:8080")
TOKEN = Path("/tmp/saakshya-demo-token.raw")
OUT = ROOT / "reports/final_live_qa"
WALL = int(os.environ.get("SAAKSHYA_WALL", "30"))
SECONDS = float(os.environ.get("SAAKSHYA_MEASURE_S", "45"))


def _get(path: str, timeout: float = 8.0) -> dict:
    headers = {}
    if TOKEN.is_file() and path not in {"/healthz", "/readyz"}:
        headers["Authorization"] = f"Bearer {TOKEN.read_text().strip()}"
        headers["X-Case-Id"] = "FIR-214/2026"
        headers["X-Purpose"] = "local relay measurement"
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.headers.get_content_type() == "application/json":
            return json.load(r)
        return {"status": r.status}


def wait_relay(timeout: float = 90.0) -> dict:
    t0 = time.monotonic()
    last = {}
    while time.monotonic() - t0 < timeout:
        try:
            last = _get("/media/hub")
            if last.get("plane") == "local_relay" and last.get("source_connected", 0) >= 1:
                return last
        except Exception as exc:
            last = {"error": type(exc).__name__}
        time.sleep(1.5)
    return last


def measure_browser(n: int, seconds: float) -> dict:
    from playwright.sync_api import sync_playwright

    token = TOKEN.read_text().strip() if TOKEN.is_file() else ""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required",
                  "--use-angle=metal", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(
            "sessionStorage.setItem('saakshya.token'," + json.dumps(token) + ");"
            "sessionStorage.setItem('saakshya.case','FIR-214/2026');"
            "sessionStorage.setItem('saakshya.purpose','local relay measurement');"
        )
        page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        page.evaluate("""(n) => {
          const live = document.querySelector("nav button[data-view='live']");
          if (live) live.click();
          const gov = document.querySelector("#view-live [data-live-domain='government']");
          if (gov) gov.click();
          const grid = document.querySelector("#view-live [data-live-layout='grid']");
          if (grid) grid.click();
          const wall = document.querySelector(`#view-live [data-live-wall='${n}']`);
          if (wall) wall.click();
        }""", n)
        page.wait_for_timeout(800)
        t0 = time.monotonic()
        first = {}
        samples = []
        while time.monotonic() - t0 < seconds:
            row = page.evaluate("""() => {
              const videos = [...document.querySelectorAll('video.tile-whep')];
              const playing = videos.filter(v => v.readyState >= 2 && !v.paused && v.videoWidth > 0);
              const firsts = playing.map(v => ({
                id: v.closest('.live-tile')?.dataset.camera,
                w: v.videoWidth, h: v.videoHeight, t: v.currentTime
              }));
              const chips = [...document.querySelectorAll('.vid-chip')].map(c => c.textContent);
              return {
                video_els: videos.length,
                playing: playing.length,
                live_chips: chips.filter(t => t === 'LIVE').length,
                replay_chips: chips.filter(t => t === 'REPLAY').length,
                connecting: chips.filter(t => t === 'CONNECTING').length,
                firsts
              };
            }""")
            samples.append({"t": round(time.monotonic() - t0, 2), **row})
            for item in row.get("firsts") or []:
                cid = item.get("id")
                if cid and cid not in first:
                    first[cid] = round((time.monotonic() - t0) * 1000, 1)
            time.sleep(1.0)
        page.screenshot(path=str(OUT / f"relay_wall_{n}.png"), full_page=False)
        browser.close()
    times = sorted(first.values())
    peak = max((s.get("playing") or 0) for s in samples) if samples else 0
    last = samples[-1] if samples else {}
    return {
        "wall": n,
        "peak_playing": peak,
        "last_playing": last.get("playing"),
        "video_els": last.get("video_els"),
        "live_chips": last.get("live_chips"),
        "first_frame_count": len(first),
        "first_frame_ms": first,
        "first_p50_ms": times[len(times)//2] if times else None,
        "first_p95_ms": times[int(len(times)*0.95)] if times else None,
        "samples": samples[-8:],
        "label": "MEASURED_REAL browser video.tile-whep, not JPEG",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    health = {}
    try:
        health = _get("/healthz")
    except Exception as exc:
        blob = {"status": "API_DOWN", "error": type(exc).__name__}
        (OUT / "relay_wall_measure.json").write_text(json.dumps(blob, indent=2) + "\n")
        print(json.dumps(blob, indent=2))
        return 2
    snap = wait_relay()
    api_lat = []
    for _ in range(5):
        t0 = time.perf_counter()
        try:
            _get("/healthz")
            api_lat.append((time.perf_counter() - t0) * 1000)
        except Exception:
            pass
    browser = {"status": "SKIPPED"}
    try:
        browser = measure_browser(WALL, SECONDS)
    except Exception as exc:
        browser = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"[:240]}
    out = {
        "plane": snap.get("plane"),
        "upstream_sessions": snap.get("upstream_sessions"),
        "source_connected": snap.get("source_connected"),
        "government_connected": snap.get("government_connected"),
        "government_live_relay": snap.get("government_live"),
        "local_relay_sessions": snap.get("local_relay_sessions"),
        "ai_cameras": snap.get("ai_cameras"),
        "elapsed_s": snap.get("elapsed_s"),
        "healthz": health,
        "api_p50_ms": round(statistics.median(api_lat), 2) if api_lat else None,
        "browser": browser,
        "cameras": [
            {k: c.get(k) for k in (
                "camera_id", "source", "video", "ai", "passthrough", "transcode",
                "codec_in", "reconnects", "first_frame_ms", "domain", "label")}
            for c in (snap.get("cameras") or [])
        ],
        "label": "MEASURED_REAL local relay. Browser LIVE is video elements, not JPEG.",
    }
    (OUT / "relay_wall_measure.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in out if k != "cameras"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
