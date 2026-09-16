#!/usr/bin/env python3
"""Phase 10 — WHEP negotiation concurrency sweep + independent tile lifecycle.

Attacks the measured bottleneck: concurrent WHEP negotiation / late first frame.

Features:
  - configurable NEGOTIATION_CONCURRENCY (semaphore)
  - tiles negotiate independently; wall soak starts immediately
  - late joiners OK; failed tiles never block successes
  - hard per-tile timeout + optional one retry
  - headed Metal Chromium only
  - telemetry/health at 1–2 Hz; no per-frame canvas

Credentials: SENTINEL_GRID_* env only. Never printed.
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

OUT = ROOT / "var/reports/phase10/performance"

# Prefer previously strongest H.264 cams first
H264_STRONG = [
    "cam01", "cam02", "cam05", "cam04", "cam13",
    "cam14", "cam19", "cam15", "cam11",
]
HEVC = ["cam06", "cam12", "cam17"]
# Extended H.264 candidates from prior onboarding (may be flaky)
H264_EXTRA = [
    "cam03", "cam07", "cam08", "cam09", "cam10",
    "cam16", "cam18", "cam20", "cam21", "cam22",
    "cam23", "cam24", "cam25", "cam26", "cam27",
    "cam28", "cam29", "cam30",
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
        "hlsAddress: :8888",
        "hlsAlwaysRemux: yes",
        "hlsAllowOrigins: [\"*\"]",
        "webrtcAddress: :8889",
        "webrtcAllowOrigins: [\"*\"]",
        "api: yes",
        "apiAddress: 127.0.0.1:9997",
        "paths:",
    ]
    for cam in cams:
        lines.append(f"  stream/gov-{cam}:")
    dst = ROOT / "var/mediamtx_phase10.yml"
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


# Independent tile lifecycle: negotiate under semaphore while soak runs.
WALL_JS = r"""
async ({endpoints, seconds, telemetryHz, healthHz, negotiateConcurrency, setupTimeoutMs, retries}) => {
  const withTimeout = (p, ms, label) => Promise.race([
    p,
    new Promise((_, rej) => setTimeout(() => rej(new Error('timeout:' + label)), ms)),
  ]);

  // Simple async semaphore
  let active = 0;
  const waiters = [];
  const acquire = () => new Promise((resolve) => {
    if (active < negotiateConcurrency) { active += 1; resolve(); }
    else waiters.push(resolve);
  });
  const release = () => {
    active -= 1;
    if (waiters.length) { active += 1; waiters.shift()(); }
  };

  const n = endpoints.length;
  const videos = [];
  const pcs = [];
  const states = [];
  for (let i = 0; i < n; i++) {
    const video = document.querySelector('#v' + i);
    videos.push(video);
    pcs.push(null);
    states.push({
      id: i, started: performance.now(), first: null, negotiation: null,
      ice: 'new', freezes: 0, reconnects: 0, currentTime: 0,
      framesDecoded: 0, framesDropped: 0, packetsLost: 0, packetsReceived: 0,
      width: 0, height: 0, error: null, attempts: 0, readyAt: null,
    });
    video.srcObject = new MediaStream();
  }

  const setupOne = async (i) => {
    const endpoint = endpoints[i];
    const video = videos[i];
    const state = states[i];
    for (let attempt = 0; attempt <= retries; attempt++) {
      state.attempts = attempt + 1;
      await acquire();
      let pc = null;
      try {
        await withTimeout((async () => {
          pc = new RTCPeerConnection();
          pc.addTransceiver('video', {direction: 'recvonly'});
          pc.ontrack = (ev) => video.srcObject.addTrack(ev.track);
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
            signal: AbortSignal.timeout(Math.min(10000, setupTimeoutMs)),
          });
          if (!resp.ok) throw new Error('WHEP ' + resp.status);
          await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
          state.negotiation = performance.now() - state.started;
          await video.play().catch(() => {});
          pcs[i] = pc;
          state.error = null;
          state.readyAt = performance.now() - state.started;
        })(), setupTimeoutMs, 'setup-' + i);
        release();
        return;
      } catch (e) {
        state.error = String(e);
        try { if (pc) pc.close(); } catch (_) {}
        pcs[i] = null;
        release();
        if (attempt < retries) await new Promise((r) => setTimeout(r, 400 * (attempt + 1)));
      }
    }
  };

  // Fire all setups without awaiting the slowest before soak
  const setups = endpoints.map((_, i) => setupOne(i));

  const wallStart = performance.now();
  const deadline = wallStart + seconds * 1000;
  const lastTime = states.map(() => 0);
  const stallMs = states.map(() => 0);
  const inStall = states.map(() => false);
  const lastIce = states.map(() => 'new');
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

    for (let i = 0; i < n; i++) {
      const pc = pcs[i];
      const video = videos[i];
      const state = states[i];
      if (!pc) continue;
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
            }
          }
        } catch (_) {}
      }
    }
    await new Promise((r) => setTimeout(r, 100));
  }

  // Don't wait forever for stuck setups
  await Promise.race([
    Promise.allSettled(setups),
    new Promise((r) => setTimeout(r, 2000)),
  ]);

  for (const pc of pcs) {
    if (pc) try { pc.close(); } catch (_) {}
  }
  let gpu = null;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl', {powerPreference: 'high-performance'});
    const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
    gpu = gl ? {renderer: gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER)} : null;
  } catch (_) {}
  return {
    tiles: states,
    gpu,
    negotiateConcurrency,
    wallElapsedMs: performance.now() - wallStart,
  };
}
"""


def measure_wall(endpoints: list[str], *, seconds: float,
                 negotiate_concurrency: int,
                 setup_timeout_ms: int = 18000,
                 retries: int = 1) -> dict:
    from playwright.sync_api import sync_playwright

    n = len(endpoints)
    page_html = (
        "<!doctype html><html><body style='margin:0;background:#111;display:flex;"
        "flex-wrap:wrap;gap:2px'>"
        + "".join(
            f"<video id='v{i}' autoplay muted playsinline "
            f"style='width:200px;height:112px;background:#000;object-fit:cover'></video>"
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
            page.set_default_timeout(int((seconds + 60 + 4 * n) * 1000))
            result = page.evaluate(
                WALL_JS,
                {
                    "endpoints": endpoints,
                    "seconds": seconds,
                    "telemetryHz": 1.0,
                    "healthHz": 2.0,
                    "negotiateConcurrency": negotiate_concurrency,
                    "setupTimeoutMs": setup_timeout_ms,
                    "retries": retries,
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
        "negotiate_concurrency": result.get("negotiateConcurrency"),
        "wall_elapsed_ms": result.get("wallElapsedMs"),
        "elapsed_s": round(time.monotonic() - started, 3),
        "browser": "headed-metal",
    }


def classify(tile: dict, *, target_s: float) -> str:
    if tile.get("error") and tile.get("first") is None:
        return "FAIL"
    if tile.get("first") is None:
        return "NO_FRAME"
    ct = float(tile.get("currentTime") or 0)
    freezes = int(tile.get("freezes") or 0)
    lost = int(tile.get("packetsLost") or 0)
    ice = tile.get("ice")
    if ct < target_s * 0.45:  # late joiners get partial time
        return "AMBER"
    if freezes > 3:
        return "AMBER"
    if lost > 10:
        return "AMBER"
    if ice not in {"connected", "completed"}:
        return "AMBER"
    return "PASS"


def start_publishers(cams: list[str], *, seconds: float,
                     transcode: set[str]) -> tuple[subprocess.Popen, list]:
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.4)
    cfg = write_mtx_config(cams)
    log = open(ROOT / "var/logs/mediamtx_phase10.log", "ab")
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
    pubs = []
    for cam in cams:
        cmd = [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), cam,
               "--seconds", str(seconds), "--publish-only"]
        if cam in transcode:
            cmd.append("--transcode")
        pubs.append(subprocess.Popen(cmd, cwd=str(ROOT), env=child_env()))
    pending = set(cams)
    for i in range(90):
        time.sleep(1)
        for cam in list(pending):
            try:
                d = api(f"/v3/paths/get/stream/gov-{cam}")
                if d.get("ready") and (d.get("bytesReceived") or 0) > 12000:
                    pending.discard(cam)
                    print(f"ready {cam} t={i+1}", flush=True)
            except Exception:
                pass
        if not pending:
            break
    if pending:
        print("not_ready", sorted(pending), flush=True)
    return mtx, pubs


def stop_all(mtx, pubs) -> None:
    for p in pubs:
        if p.poll() is None:
            p.terminate()
    try:
        mtx.terminate()
    except Exception:
        pass


def summarize(cams: list[str], wall: dict, *, seconds: float,
              negotiate_concurrency: int) -> dict:
    tiles_out = []
    raw = wall.get("tiles") or []
    for i, cam in enumerate(cams):
        tile = raw[i] if i < len(raw) else {}
        verdict = classify(tile, target_s=seconds)
        ct = float(tile.get("currentTime") or 0)
        fd = int(tile.get("framesDecoded") or 0)
        tiles_out.append({
            "camera_id": cam,
            "verdict": verdict,
            "first_frame_ms": tile.get("first"),
            "negotiation_ms": tile.get("negotiation"),
            "ready_at_ms": tile.get("readyAt"),
            "attempts": tile.get("attempts"),
            "currentTime": ct,
            "framesDecoded": fd,
            "framesDropped": tile.get("framesDropped"),
            "packetsLost": tile.get("packetsLost"),
            "freezes": tile.get("freezes"),
            "ice": tile.get("ice"),
            "effective_fps": round(fd / ct, 2) if ct > 0.5 else None,
            "error": tile.get("error"),
        })
    negs = [float(t["negotiation_ms"]) for t in tiles_out if t.get("negotiation_ms")]
    firsts = [float(t["first_frame_ms"]) for t in tiles_out if t.get("first_frame_ms")]
    passes = sum(1 for t in tiles_out if t["verdict"] == "PASS")
    ambers = sum(1 for t in tiles_out if t["verdict"] == "AMBER")
    fails = sum(1 for t in tiles_out if t["verdict"] in {"FAIL", "NO_FRAME"})
    if wall.get("status") != "MEASURED":
        overall = "FAIL"
    elif fails == 0 and ambers == 0:
        overall = "PASS"
    elif passes >= max(1, int(0.6 * len(cams))):
        overall = "AMBER"
    elif passes > 0:
        overall = "AMBER"
    else:
        overall = "FAIL"
    return {
        "n_cameras": len(cams),
        "negotiate_concurrency": negotiate_concurrency,
        "seconds": seconds,
        "overall": overall,
        "label": "MEASURED",
        "wall_summary": {
            "PASS": passes, "AMBER": ambers, "FAIL": fails,
            "negotiation_ms_p50": pct(negs, 50),
            "negotiation_ms_p95": pct(negs, 95),
            "first_frame_ms_p50": pct(firsts, 50),
            "first_frame_ms_p95": pct(firsts, 95),
        },
        "tiles": tiles_out,
        "browser_wall": {
            "status": wall.get("status"),
            "gpu": wall.get("gpu"),
            "elapsed_s": wall.get("elapsed_s"),
            "error": wall.get("error"),
        },
        "resources": {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
        },
    }


def camera_pool(n: int) -> tuple[list[str], set[str]]:
    """Build n cameras: strong H.264, then HEVC tx, then extra H.264."""
    cams: list[str] = []
    transcode: set[str] = set()
    for c in H264_STRONG:
        if len(cams) >= n:
            break
        cams.append(c)
    for c in HEVC:
        if len(cams) >= n:
            break
        cams.append(c)
        transcode.add(c)
    for c in H264_EXTRA:
        if len(cams) >= n:
            break
        if c not in cams:
            cams.append(c)
    if len(cams) < n:
        raise SystemExit(f"only {len(cams)} known cameras; need {n}")
    return cams[:n], transcode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["sweep", "scale"], default="sweep")
    parser.add_argument("--n", type=int, default=12,
                        help="camera count for sweep/scale")
    parser.add_argument("--concurrencies", nargs="+", type=int,
                        default=[1, 2, 3, 4, 6, 8])
    parser.add_argument("--levels", nargs="+", type=int,
                        default=[12, 14, 16],
                        help="scale mode N values")
    parser.add_argument("--negotiate-concurrency", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)

    if args.mode == "sweep":
        cams, transcode = camera_pool(args.n)
        pub_life = 90 + args.seconds * len(args.concurrencies) + 30 * len(args.concurrencies)
        print(f"sweep n={args.n} concurrencies={args.concurrencies}", flush=True)
        mtx, pubs = start_publishers(cams, seconds=pub_life, transcode=transcode)
        results = []
        try:
            endpoints = [f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in cams]
            for conc in args.concurrencies:
                print(f"\n=== negotiate_concurrency={conc} ===", flush=True)
                wall = measure_wall(
                    endpoints, seconds=args.seconds,
                    negotiate_concurrency=conc, retries=1,
                )
                row = summarize(cams, wall, seconds=args.seconds,
                                negotiate_concurrency=conc)
                results.append(row)
                print(
                    f"conc={conc} overall={row['overall']} "
                    f"{row['wall_summary']}",
                    flush=True,
                )
                (OUT / f"whep_conc_{conc}_n{args.n}.json").write_text(
                    json.dumps(row, indent=2) + "\n")
        finally:
            stop_all(mtx, pubs)

        # Pick best: maximize PASS, then minimize negotiation p95
        def score(r):
            ws = r["wall_summary"]
            return (ws["PASS"], -fails_or_zero(ws),
                    -(ws.get("negotiation_ms_p95") or 1e9))

        def fails_or_zero(ws):
            return ws.get("FAIL") or 0

        best = max(results, key=score) if results else None
        payload = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "mode": "sweep",
            "n_cameras": args.n,
            "results": results,
            "best_concurrency": best["negotiate_concurrency"] if best else None,
            "best_summary": best["wall_summary"] if best else None,
            "label": "MEASURED",
        }
        out = args.out or (OUT / "whep_concurrency_sweep.json")
        out.write_text(json.dumps(payload, indent=2) + "\n")
        print("best_concurrency", payload["best_concurrency"], flush=True)
        print("wrote", out, flush=True)
        return 0

    # scale mode: push N with fixed concurrency
    results = []
    for n in args.levels:
        print(f"\n=== SCALE n={n} conc={args.negotiate_concurrency} ===", flush=True)
        cams, transcode = camera_pool(n)
        pub_life = max(180.0, args.seconds + 120 + 10 * n)
        mtx, pubs = start_publishers(cams, seconds=pub_life, transcode=transcode)
        try:
            endpoints = [f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in cams]
            wall = measure_wall(
                endpoints, seconds=args.seconds,
                negotiate_concurrency=args.negotiate_concurrency, retries=1,
            )
            row = summarize(cams, wall, seconds=args.seconds,
                            negotiate_concurrency=args.negotiate_concurrency)
            results.append(row)
            print(f"n={n} overall={row['overall']} {row['wall_summary']}", flush=True)
            (OUT / f"scale_n{n}.json").write_text(json.dumps(row, indent=2) + "\n")
        finally:
            stop_all(mtx, pubs)

    operable = [r["n_cameras"] for r in results
                if r["overall"] in {"PASS", "AMBER"}]
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "mode": "scale",
        "negotiate_concurrency": args.negotiate_concurrency,
        "results": results,
        "max_operable": max(operable) if operable else 0,
        "label": "MEASURED",
    }
    out = args.out or (OUT / "scale_progression.json")
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print("max_operable", payload["max_operable"], flush=True)
    print("wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
