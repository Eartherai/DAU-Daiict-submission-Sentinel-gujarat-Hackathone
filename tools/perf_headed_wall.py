#!/usr/bin/env python3
"""Headed Metal concurrent WHEP wall benchmark — no per-frame canvas/getStats spam.

VIDEO PATH:  <video> → browser compositor (Metal)
TELEMETRY:   1 Hz getStats
HEALTH:      2 Hz currentTime / freeze
NEGOTIATION: waves of 4 with per-session timeout
FAILURE:     one tile FAIL must not block others
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402

OUT = ROOT / "var/reports/phase9/performance"

H264_POOL = [
    "cam01", "cam02", "cam05", "cam04", "cam11",
    "cam13", "cam14", "cam15", "cam19",
]
HEVC_POOL = ["cam06", "cam12", "cam17"]


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
    dst = ROOT / "var/mediamtx_perf_headed.yml"
    dst.write_text("\n".join(lines) + "\n")
    return dst


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return float(s[f] + (s[c] - s[f]) * (k - f))


WALL_JS = r"""
async ({endpoints, seconds, telemetryHz, healthHz}) => {
  const withTimeout = (p, ms, label) => Promise.race([
    p,
    new Promise((_, rej) => setTimeout(() => rej(new Error('timeout:' + label)), ms)),
  ]);

  const setupOne = async (endpoint, i) => {
    const video = document.querySelector('#v' + i);
    const pc = new RTCPeerConnection();
    pc.addTransceiver('video', {direction: 'recvonly'});
    const state = {
      id: i, cameraHint: endpoint, started: performance.now(),
      first: null, negotiation: null, ice: 'new',
      freezes: 0, reconnects: 0, currentTime: 0,
      framesDecoded: 0, framesDropped: 0, packetsLost: 0,
      packetsReceived: 0, width: 0, height: 0, error: null,
      jitterBufferDelay: null,
    };
    video.srcObject = new MediaStream();
    pc.ontrack = (ev) => video.srcObject.addTrack(ev.track);
    try {
      await withTimeout((async () => {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await new Promise((resolve) => {
          const t = setTimeout(resolve, 2500);
          if (pc.iceGatheringState === 'complete') resolve();
          else pc.addEventListener('icegatheringstatechange', () => {
            if (pc.iceGatheringState === 'complete') { clearTimeout(t); resolve(); }
          });
        });
        const resp = await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'},
          body: pc.localDescription.sdp,
          signal: AbortSignal.timeout(12000),
        });
        if (!resp.ok) throw new Error('WHEP ' + resp.status);
        await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
        state.negotiation = performance.now() - state.started;
        await video.play().catch(() => {});
      })(), 20000, 'setup-' + i);
      return {ok: true, state, pc, video};
    } catch (e) {
      state.error = String(e);
      try { pc.close(); } catch (_) {}
      return {ok: false, state, pc: null, video};
    }
  };

  const wave = 4;
  const settled = [];
  for (let start = 0; start < endpoints.length; start += wave) {
    const slice = endpoints.slice(start, start + wave);
    const part = await Promise.all(slice.map((ep, j) => setupOne(ep, start + j)));
    settled.push(...part);
  }

  const deadline = performance.now() + seconds * 1000;
  const lastTime = settled.map(() => 0);
  const stallMs = settled.map(() => 0);
  const inStall = settled.map(() => false);
  const lastIce = settled.map((t) => (t.pc ? t.pc.iceConnectionState : 'none'));
  let lastTelemetry = 0;
  let lastHealth = 0;
  const telemetryInterval = 1000 / Math.max(0.5, telemetryHz);
  const healthInterval = 1000 / Math.max(0.5, healthHz);

  while (performance.now() < deadline) {
    const now = performance.now();
    const doHealth = (now - lastHealth) >= healthInterval;
    const doTelemetry = (now - lastTelemetry) >= telemetryInterval;
    if (doHealth) lastHealth = now;
    if (doTelemetry) lastTelemetry = now;

    for (let i = 0; i < settled.length; i++) {
      const entry = settled[i];
      if (!entry.pc) continue;
      const {state, pc, video} = entry;
      if (doHealth) {
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
        state.width = video.videoWidth;
        state.height = video.videoHeight;
        if (state.first !== null) {
          if (t <= lastTime[i] + 0.01) {
            stallMs[i] += healthInterval;
            if (!inStall[i] && stallMs[i] >= 1500) {
              state.freezes += 1; inStall[i] = true;
            }
          } else {
            stallMs[i] = 0; inStall[i] = false; lastTime[i] = t;
          }
        }
      }
      if (doTelemetry) {
        try {
          for (const report of (await pc.getStats()).values()) {
            if (report.type === 'inbound-rtp' && report.kind === 'video') {
              state.framesDecoded = report.framesDecoded || 0;
              state.framesDropped = report.framesDropped || 0;
              state.packetsLost = report.packetsLost || 0;
              state.packetsReceived = report.packetsReceived || 0;
              if (report.jitterBufferDelay != null)
                state.jitterBufferDelay = report.jitterBufferDelay;
            }
          }
        } catch (_) {}
      }
    }
    await new Promise((r) => setTimeout(r, 100));
  }

  const out = [];
  for (const entry of settled) {
    if (entry.pc) try { entry.pc.close(); } catch (_) {}
    out.push(entry.state);
  }
  let gpu = null;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl', {powerPreference: 'high-performance'});
    const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
    gpu = gl ? {renderer: gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER)} : null;
  } catch (_) {}
  return {tiles: out, gpu};
}
"""


def measure_headed_wall(endpoints: list[str], *, seconds: float,
                        telemetry_hz: float = 1.0,
                        health_hz: float = 2.0) -> dict:
    from playwright.sync_api import sync_playwright

    n = len(endpoints)
    page_html = (
        "<!doctype html><html><body style='margin:0;background:#111;display:flex;"
        "flex-wrap:wrap;gap:2px'>"
        + "".join(
            f"<video id='v{i}' autoplay muted playsinline "
            f"style='width:240px;height:135px;background:#000;object-fit:cover'></video>"
            for i in range(n)
        )
        + "</body></html>"
    )
    started = time.monotonic()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                "--use-angle=metal",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-web-security",
                "--enable-features=PlatformHEVCDecoderSupport",
            ],
        )
        try:
            page = browser.new_page()
            page.set_content(page_html, wait_until="domcontentloaded")
            page.set_default_timeout(int((seconds + 50 + 5 * n) * 1000))
            result = page.evaluate(
                WALL_JS,
                {
                    "endpoints": endpoints,
                    "seconds": seconds,
                    "telemetryHz": telemetry_hz,
                    "healthHz": health_hz,
                },
            )
        except Exception as exc:
            browser.close()
            return {
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}"[:400],
                "tiles": [],
                "elapsed_s": round(time.monotonic() - started, 3),
            }
        browser.close()
    return {
        "status": "MEASURED",
        "tiles": result.get("tiles") or [],
        "gpu": result.get("gpu"),
        "elapsed_s": round(time.monotonic() - started, 3),
        "browser": "playwright-chromium-headed-metal",
    }


def classify_tile(tile: dict, *, target_s: float) -> str:
    if tile.get("error") and tile.get("first") is None:
        return "FAIL"
    if tile.get("first") is None:
        return "NO_FRAME"
    ct = float(tile.get("currentTime") or 0)
    freezes = int(tile.get("freezes") or 0)
    lost = int(tile.get("packetsLost") or 0)
    ice = tile.get("ice")
    if ct < target_s * 0.55:
        return "AMBER"
    if freezes > 2:
        return "AMBER"
    if lost > 5:
        return "AMBER"
    if ice not in {"connected", "completed"}:
        return "AMBER"
    return "PASS"


def sample_resources() -> dict:
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "ram_available_gb": round(mem.available / 1e9, 3),
        "ram_percent": mem.percent,
    }


def run_level(n: int, *, seconds: float, cameras: list[str] | None = None,
              transcode: set[str] | None = None) -> dict:
    transcode = set(transcode or [])
    pool = list(cameras) if cameras else list(H264_POOL)
    cams = pool[:n]
    if len(cams) < n:
        raise SystemExit(f"Only {len(cams)} cameras in pool; need {n}")

    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.5)
    cfg = write_mtx_config(cams)
    log = open(ROOT / "var/logs/mediamtx_perf_headed.log", "ab")
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

    pub_seconds = max(240.0, seconds + 90 + 15 * n)
    pubs: list[subprocess.Popen] = []
    before = sample_resources()
    try:
        for cam in cams:
            cmd = [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), cam,
                   "--seconds", str(pub_seconds), "--publish-only"]
            if cam in transcode:
                cmd.append("--transcode")
            pubs.append(subprocess.Popen(cmd, cwd=str(ROOT), env=child_env()))

        pending = set(cams)
        for i in range(int(seconds) + 50):
            time.sleep(1)
            for cam in list(pending):
                try:
                    d = api(f"/v3/paths/get/stream/gov-{cam}")
                    if d.get("ready") and (d.get("bytesReceived") or 0) > 15000:
                        pending.discard(cam)
                        print(f"ready {cam} t={i+1}", flush=True)
                except Exception:
                    pass
            if not pending:
                break
        if pending:
            print("still waiting", sorted(pending), flush=True)

        endpoints = [f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in cams]
        mid = sample_resources()
        print(f"headed wall n={n} soak={seconds}s ...", flush=True)
        wall = measure_headed_wall(endpoints, seconds=seconds)
        after = sample_resources()

        tiles_out = []
        raw_tiles = wall.get("tiles") or []
        for i, cam in enumerate(cams):
            tile = raw_tiles[i] if i < len(raw_tiles) else {}
            verdict = classify_tile(tile, target_s=seconds)
            ct = float(tile.get("currentTime") or 0)
            fd = int(tile.get("framesDecoded") or 0)
            tiles_out.append({
                "camera_id": cam,
                "verdict": verdict,
                "first_frame_ms": tile.get("first"),
                "negotiation_ms": tile.get("negotiation"),
                "currentTime": ct,
                "framesDecoded": fd,
                "framesDropped": tile.get("framesDropped"),
                "packetsLost": tile.get("packetsLost"),
                "freezes": tile.get("freezes"),
                "reconnects": tile.get("reconnects"),
                "ice": tile.get("ice"),
                "resolution": (
                    f"{tile.get('width')}x{tile.get('height')}"
                    if tile.get("width") else None
                ),
                "effective_fps": round(fd / ct, 2) if ct > 0.5 else None,
                "error": tile.get("error"),
                "transcode": cam in transcode,
            })

        firsts = [float(t["first_frame_ms"]) for t in tiles_out
                  if t["first_frame_ms"] is not None]
        cts = [t["currentTime"] for t in tiles_out]
        fpss = [float(t["effective_fps"]) for t in tiles_out if t["effective_fps"]]
        passes = sum(1 for t in tiles_out if t["verdict"] == "PASS")
        ambers = sum(1 for t in tiles_out if t["verdict"] == "AMBER")
        fails = sum(1 for t in tiles_out if t["verdict"] in {"FAIL", "NO_FRAME"})

        if wall.get("status") != "MEASURED":
            overall = "FAIL"
        elif fails == 0 and ambers == 0 and passes == n:
            overall = "PASS"
        elif fails == 0 and passes >= max(1, int(0.7 * n)):
            overall = "AMBER"
        elif passes > 0:
            overall = "AMBER"
        else:
            overall = "FAIL"

        publishing_ok = len(pending) == 0
        bottleneck = None
        if not publishing_ok and fails:
            bottleneck = "source_or_relay"
        elif publishing_ok and wall.get("status") != "MEASURED":
            bottleneck = "browser_js_or_negotiation"
        elif publishing_ok and fails:
            bottleneck = "browser_decode_or_ice"
        elif ambers:
            bottleneck = "session_stability_under_load"

        return {
            "n_cameras": n,
            "mode": "VIDEO_ONLY",
            "browser_mode": "headed_metal",
            "architecture": "A_concurrent_independent_WHEP_batched_setup",
            "seconds": seconds,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "label": "MEASURED",
            "cameras": cams,
            "not_ready": sorted(pending),
            "tiles": tiles_out,
            "wall_summary": {
                "PASS": passes, "AMBER": ambers, "FAIL": fails,
                "first_frame_ms_p50": pct(firsts, 50),
                "first_frame_ms_p95": pct(firsts, 95),
                "currentTime_p50": pct(cts, 50),
                "currentTime_p95": pct(cts, 95),
                "effective_fps_p50": pct(fpss, 50),
                "effective_fps_p95": pct(fpss, 95),
            },
            "resources": {"before": before, "mid": mid, "after": after},
            "browser_wall": {
                "status": wall.get("status"),
                "elapsed_s": wall.get("elapsed_s"),
                "gpu": wall.get("gpu"),
                "error": wall.get("error"),
            },
            "bottleneck_hint": bottleneck,
            "overall": overall,
        }
    finally:
        for p in pubs:
            if p.poll() is None:
                p.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass
        time.sleep(0.4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="+", type=int, default=[4, 6, 8, 9])
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--cameras", nargs="*", default=None)
    parser.add_argument("--transcode", nargs="*", default=[])
    parser.add_argument("--out", type=Path,
                        default=OUT / "headed_concurrent_matrix.json")
    args = parser.parse_args()
    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    max_pass = 0
    max_amber = 0
    for n in args.levels:
        print(f"\n=== HEADED METAL VIDEO_ONLY n={n} ===", flush=True)
        try:
            r = run_level(
                n, seconds=args.seconds, cameras=args.cameras,
                transcode=set(args.transcode),
            )
        except Exception as exc:
            r = {
                "n_cameras": n, "overall": "FAIL", "label": "MEASURED",
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "browser_mode": "headed_metal",
            }
        results.append(r)
        (OUT / f"headed_video_only_n{n}.json").write_text(
            json.dumps(r, indent=2) + "\n")
        print(
            f"n={n} overall={r.get('overall')} summary={r.get('wall_summary')} "
            f"bottleneck={r.get('bottleneck_hint')}",
            flush=True,
        )
        if r.get("overall") == "PASS":
            max_pass = max(max_pass, n)
        if r.get("overall") in {"PASS", "AMBER"}:
            max_amber = max(max_amber, n)

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": (
            f"python tools/perf_headed_wall.py --levels "
            f"{' '.join(map(str, args.levels))} --seconds {args.seconds}"
        ),
        "browser_mode": "headed_metal",
        "levels": results,
        "max_smooth_PASS": max_pass,
        "max_operable_PASS_or_AMBER": max_amber,
        "note": (
            "Headed Metal Chromium. Telemetry 1 Hz, health 2 Hz, batched WHEP "
            "setup (wave=4). SwiftShader 4-stream ceiling superseded."
        ),
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print("wrote", args.out)
    print("max_smooth_PASS", max_pass, "max_operable", max_amber)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
