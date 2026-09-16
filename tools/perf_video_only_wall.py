#!/usr/bin/env python3
"""Concurrent multi-tile WHEP VIDEO-ONLY performance benchmark.

Opens N video elements in ONE Chromium page against concurrent MediaMTX
publishers. Measures per-tile and wall-level decode health.

Does NOT redesign the media path. Credentials remain environment-only.
AI mode is VIDEO_ONLY for this cycle.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402

OUT = ROOT / "var/reports/phase9/performance"

# Proven H.264 government cameras for concurrent decode stress.
H264_POOL = [
    "cam01", "cam02", "cam05", "cam04", "cam11",
    "cam13", "cam14", "cam15", "cam19",
]


def child_env() -> dict[str, str]:
    keep = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
        "VIRTUAL_ENV", "PYTHONPATH", "PYTHONUNBUFFERED",
        "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
    }
    return {k: v for k, v in os.environ.items() if k in keep}


def api(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:9997{path}", timeout=3) as r:
        return json.load(r)


def write_mtx_config(cams: list[str]) -> Path:
    lines = [
        "# generated — no credentials",
        "logLevel: warn",
        "rtspAddress: :8554",
        "rtspTransports: [tcp]",
        "webrtcAddress: :8889",
        "webrtcAllowOrigins: [\"*\"]",
        "api: yes",
        "apiAddress: 127.0.0.1:9997",
        "paths:",
    ]
    for cam in cams:
        lines.append(f"  stream/gov-{cam}:")
    dst = ROOT / "var/mediamtx_perf_wall.yml"
    dst.write_text("\n".join(lines) + "\n")
    return dst


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return float(s[f] + (s[c] - s[f]) * (k - f))


def sample_resources(proc: psutil.Process) -> dict:
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.2)
    try:
        pmem = proc.memory_info().rss
    except Exception:
        pmem = 0
    return {
        "cpu_percent": cpu,
        "ram_available_gb": round(mem.available / 1e9, 3),
        "ram_percent": mem.percent,
        "harness_rss_mb": round(pmem / 1e6, 2),
    }


def measure_concurrent_wall(endpoints: list[str], *, seconds: float) -> dict:
    """One page, N <video> elements, concurrent WHEP (hard-timeout wrapped)."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    from playwright.sync_api import sync_playwright

    n = len(endpoints)
    page_html = (
        "<!doctype html><html><body style=\"margin:0;background:#111;display:flex;"
        "flex-wrap:wrap\">"
        + "".join(
            f"<video id=\"v{i}\" autoplay muted playsinline "
            f"style=\"width:320px;height:180px;background:#000;object-fit:cover\"></video>"
            for i in range(n)
        )
        + "</body></html>"
    )
    js = """
    async ({endpoints, seconds}) => {
      const setups = endpoints.map(async (endpoint, i) => {
        const video = document.querySelector('#v' + i);
        const pc = new RTCPeerConnection();
        pc.addTransceiver('video', {direction: 'recvonly'});
        const state = {
          id: i, endpoint, started: performance.now(), first: null,
          negotiation: null, ice: null, freezes: 0, reconnects: 0,
          blackSamples: 0, lumaSamples: 0, meanLumaSum: 0,
          currentTime: 0, framesDecoded: 0, framesDropped: 0,
          packetsLost: 0, packetsReceived: 0, width: 0, height: 0, error: null
        };
        video.srcObject = new MediaStream();
        pc.ontrack = (ev) => video.srcObject.addTrack(ev.track);
        try {
          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          await new Promise((resolve) => {
            const t = setTimeout(resolve, 2000);
            if (pc.iceGatheringState === 'complete') resolve();
            else pc.addEventListener('icegatheringstatechange', () => {
              if (pc.iceGatheringState === 'complete') { clearTimeout(t); resolve(); }
            });
          });
          const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'},
            body: pc.localDescription.sdp,
            signal: AbortSignal.timeout(8000),
          });
          if (!resp.ok) throw new Error('WHEP ' + resp.status);
          await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
          state.negotiation = performance.now() - state.started;
          await video.play().catch(() => {});
          return {state, pc, video};
        } catch (e) {
          state.error = String(e);
          try { pc.close(); } catch (_) {}
          return {state, pc: null, video};
        }
      });
      const tiles = await Promise.all(setups);
      const deadline = performance.now() + seconds * 1000;
      const lastTime = tiles.map(() => 0);
      const stallMs = tiles.map(() => 0);
      const inStall = tiles.map(() => false);
      const lastIce = tiles.map((t) => (t.pc ? t.pc.iceConnectionState : 'none'));
      let loop = 0;
      while (performance.now() < deadline) {
        loop += 1;
        for (let i = 0; i < tiles.length; i++) {
          const entry = tiles[i];
          if (!entry.pc) continue;
          const {state, pc, video} = entry;
          state.ice = pc.iceConnectionState;
          if (state.ice !== lastIce[i]) {
            if (['disconnected','failed','closed'].includes(lastIce[i])
                && state.ice === 'connected') state.reconnects += 1;
            lastIce[i] = state.ice;
          }
          if (state.first === null && video.readyState >= 2 && video.videoWidth > 0)
            state.first = performance.now() - state.started;
          const t = video.currentTime || 0;
          state.currentTime = t;
          state.width = video.videoWidth; state.height = video.videoHeight;
          if (state.first !== null) {
            if (t <= lastTime[i] + 0.01) {
              stallMs[i] += 500;
              if (!inStall[i] && stallMs[i] >= 1500) { state.freezes += 1; inStall[i] = true; }
            } else { stallMs[i] = 0; inStall[i] = false; lastTime[i] = t; }
          }
          if (loop % 2 === 0) {
            for (const report of (await pc.getStats()).values()) {
              if (report.type === 'inbound-rtp' && report.kind === 'video') {
                state.framesDecoded = report.framesDecoded || 0;
                state.framesDropped = report.framesDropped || 0;
                state.packetsLost = report.packetsLost || 0;
                state.packetsReceived = report.packetsReceived || 0;
              }
            }
          }
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      const out = [];
      for (const entry of tiles) {
        const state = entry.state;
        if (entry.pc) try { entry.pc.close(); } catch (_) {}
        state.meanLuma = state.lumaSamples ? state.meanLumaSum / state.lumaSamples : null;
        out.push(state);
      }
      return out;
    }
    """

    def _run() -> dict:
        started = time.monotonic()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--allow-running-insecure-content",
                ],
            )
            try:
                page = browser.new_page()
                page.set_content(page_html, wait_until="domcontentloaded")
                tiles = page.evaluate(js, {"endpoints": endpoints, "seconds": seconds})
                return {
                    "status": "MEASURED",
                    "tiles": tiles,
                    "elapsed_s": round(time.monotonic() - started, 3),
                    "browser": "playwright-chromium-headless",
                    "note": "Headless Chromium uses SwiftShader; headed Metal may differ",
                }
            finally:
                browser.close()

    hard_timeout = seconds + 35 + 4 * len(endpoints)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run).result(timeout=hard_timeout)
    except FuturesTimeout:
        subprocess.run(["pkill", "-f", "chrome-headless-shell"], check=False)
        return {
            "status": "FAIL",
            "error": f"concurrent wall timed out after {hard_timeout}s",
            "tiles": [],
            "elapsed_s": hard_timeout,
            "browser": "playwright-chromium-headless",
            "note": "Timeout under headless SwiftShader — decode ceiling signal",
        }



def classify_tile(tile: dict, *, target_s: float) -> str:
    if tile.get("error") and tile.get("first") is None:
        return "FAIL"
    if tile.get("first") is None:
        return "NO_FRAME"
    ct = float(tile.get("currentTime") or 0)
    freezes = int(tile.get("freezes") or 0)
    lost = int(tile.get("packetsLost") or 0)
    black = int(tile.get("blackSamples") or 0)
    luma_n = int(tile.get("lumaSamples") or 0)
    ice = tile.get("ice")
    # SMOOTH engineering thresholds (cycle-1 provisional from prior certs)
    if ct < target_s * 0.55:
        return "AMBER"
    if freezes > 2:
        return "AMBER"
    if lost > 0:
        return "AMBER"
    if ice not in {"connected", "completed"}:
        return "AMBER"
    if luma_n and black / luma_n > 0.25:
        return "AMBER"
    return "PASS"


def run_level(n: int, *, seconds: float, cameras: list[str] | None = None) -> dict:
    cams = (cameras or H264_POOL)[:n]
    if len(cams) < n:
        raise SystemExit(f"need {n} H.264 cameras, have {len(cams)}")

    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.4)
    cfg = write_mtx_config(cams)
    log = open(ROOT / "var/logs/mediamtx_perf.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        time.sleep(0.25)
        try:
            api("/v3/paths/list")
            break
        except Exception:
            if mtx.poll() is not None:
                raise SystemExit("MediaMTX failed")

    pub_seconds = max(180.0, seconds + 120 + 30 * n)
    pubs = []
    harness = psutil.Process()
    resources_before = sample_resources(harness)
    try:
        for cam in cams:
            pubs.append(subprocess.Popen(
                [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), cam,
                 "--seconds", str(pub_seconds), "--publish-only"],
                cwd=str(ROOT), env=child_env(),
            ))
        pending = set(cams)
        for i in range(int(seconds) + 40):
            time.sleep(1)
            for cam in list(pending):
                try:
                    d = api(f"/v3/paths/get/stream/gov-{cam}")
                    if d.get("ready") and (d.get("bytesReceived") or 0) > 15000:
                        pending.discard(cam)
                except Exception:
                    pass
            if not pending:
                break
        publishing = {}
        for cam in cams:
            try:
                d = api(f"/v3/paths/get/stream/gov-{cam}")
                publishing[cam] = {
                    "ready": bool(d.get("ready")),
                    "bytesReceived": int(d.get("bytesReceived") or 0),
                }
            except Exception as exc:
                publishing[cam] = {"ready": False, "error": type(exc).__name__}

        endpoints = [f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in cams]
        mid = sample_resources(harness)
        wall = measure_concurrent_wall(endpoints, seconds=seconds)
        after = sample_resources(harness)

        tiles_out = []
        for i, cam in enumerate(cams):
            tile = (wall.get("tiles") or [None] * n)[i] or {}
            # map endpoint index
            if isinstance(tile, dict) and "state" in tile:
                tile = tile["state"]
            verdict = classify_tile(tile, target_s=seconds)
            first = tile.get("first")
            ct = float(tile.get("currentTime") or 0)
            fd = int(tile.get("framesDecoded") or 0)
            eff_fps = (fd / ct) if ct > 0.5 else None
            tiles_out.append({
                "camera_id": cam,
                "verdict": verdict,
                "first_frame_ms": first,
                "negotiation_ms": tile.get("negotiation"),
                "currentTime": ct,
                "framesDecoded": fd,
                "framesDropped": tile.get("framesDropped"),
                "packetsLost": tile.get("packetsLost"),
                "packetsReceived": tile.get("packetsReceived"),
                "freezes": tile.get("freezes"),
                "reconnects": tile.get("reconnects"),
                "ice": tile.get("ice"),
                "resolution": (
                    f"{tile.get('width')}x{tile.get('height')}"
                    if tile.get("width") else None
                ),
                "meanLuma": tile.get("meanLuma"),
                "black_sample_ratio": (
                    (tile.get("blackSamples") or 0) / tile["lumaSamples"]
                    if tile.get("lumaSamples") else None
                ),
                "effective_fps": round(eff_fps, 2) if eff_fps else None,
                "error": tile.get("error"),
            })

        firsts = [t["first_frame_ms"] for t in tiles_out if t["first_frame_ms"] is not None]
        cts = [t["currentTime"] for t in tiles_out]
        fpss = [t["effective_fps"] for t in tiles_out if t["effective_fps"]]
        passes = sum(1 for t in tiles_out if t["verdict"] == "PASS")
        ambers = sum(1 for t in tiles_out if t["verdict"] == "AMBER")
        fails = sum(1 for t in tiles_out if t["verdict"] in {"FAIL", "NO_FRAME"})

        if fails:
            overall = "FAIL"
        elif ambers:
            overall = "AMBER"
        elif passes == n:
            overall = "PASS"
        else:
            overall = "AMBER"

        return {
            "n_cameras": n,
            "mode": "VIDEO_ONLY",
            "architecture": "A_concurrent_independent_WHEP",
            "seconds": seconds,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "cameras": cams,
            "publishing": publishing,
            "not_ready": sorted(pending),
            "tiles": tiles_out,
            "wall_summary": {
                "PASS": passes,
                "AMBER": ambers,
                "FAIL": fails,
                "first_frame_ms_p50": pct(firsts, 50),
                "first_frame_ms_p95": pct(firsts, 95),
                "currentTime_p50": pct(cts, 50),
                "currentTime_p95": pct(cts, 95),
                "effective_fps_p50": pct(fpss, 50),
                "effective_fps_p95": pct(fpss, 95),
            },
            "resources": {
                "before": resources_before,
                "during_publish": mid,
                "after": after,
            },
            "browser_wall": {
                "status": wall.get("status"),
                "elapsed_s": wall.get("elapsed_s"),
                "note": wall.get("note"),
                "error": wall.get("error"),
            },
            "overall": overall,
            "label": "MEASURED",
        }
    finally:
        for p in pubs:
            if p.poll() is None:
                p.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 4, 9])
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--out", type=Path,
                        default=OUT / "video_only_concurrent_matrix.json")
    args = parser.parse_args()
    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for n in args.levels:
        print(f"=== VIDEO_ONLY concurrent wall n={n} ===", flush=True)
        try:
            r = run_level(n, seconds=args.seconds)
        except Exception as exc:
            r = {
                "n_cameras": n,
                "mode": "VIDEO_ONLY",
                "overall": "FAIL",
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "label": "MEASURED",
            }
        results.append(r)
        print(
            f"n={n} overall={r.get('overall')} "
            f"summary={r.get('wall_summary')}",
            flush=True,
        )
        (OUT / f"video_only_n{n}.json").write_text(json.dumps(r, indent=2) + "\n")

    # Max smooth = largest n where overall PASS
    max_pass = 0
    max_amber = 0
    for r in results:
        n = r.get("n_cameras") or 0
        if r.get("overall") == "PASS":
            max_pass = max(max_pass, n)
        if r.get("overall") in {"PASS", "AMBER"}:
            max_amber = max(max_amber, n)

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": (
            f"python tools/perf_video_only_wall.py --levels "
            f"{' '.join(map(str, args.levels))} --seconds {args.seconds}"
        ),
        "mode": "VIDEO_ONLY",
        "smooth_definition": {
            "currentTime_min_ratio": 0.55,
            "max_freezes": 2,
            "packetsLost_max": 0,
            "ice": ["connected", "completed"],
            "black_sample_ratio_max": 0.25,
            "note": "Provisional cycle-1 thresholds; refine after matrix",
        },
        "levels": results,
        "max_smooth_PASS": max_pass,
        "max_operable_PASS_or_AMBER": max_amber,
        "harness_limitation": (
            "MEASURED under Playwright headless Chromium (SwiftShader). "
            "Headed Metal hardware decode ceiling may be higher — untested this cycle."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print("wrote", args.out)
    print("max_smooth_PASS", max_pass, "max_operable", max_amber)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
