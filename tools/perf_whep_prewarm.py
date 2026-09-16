#!/usr/bin/env python3
"""Phase 10B — WHEP prewarm / session pool experiment.

Measures cold vs warm promotion latency on headed Chromium (ANGLE Metal):

  COLD:  click → negotiate WHEP from zero → first frame
  WARM:  pre-negotiated PeerConnection held off-DOM → attach to visible
         <video> (no renegotiation) → first frame

Does not redesign MediaMTX. Credentials env-only.
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

from saakshya.live.credentials import configured  # noqa: E402
from tools.perf_whep_session_scheduler import (  # noqa: E402
    child_env, start_publishers, stop_all,
)

OUT = ROOT / "var/reports/phase10/performance"

PREWARM_JS = r"""
async ({endpoint, warmHoldMs}) => {
  const withTimeout = (p, ms, label) => Promise.race([
    p,
    new Promise((_, rej) => setTimeout(() => rej(new Error('timeout:' + label)), ms)),
  ]);

  const negotiate = async () => {
    const t0 = performance.now();
    const pc = new RTCPeerConnection();
    const stream = new MediaStream();
    pc.addTransceiver('video', {direction: 'recvonly'});
    pc.ontrack = (ev) => stream.addTrack(ev.track);
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
      signal: AbortSignal.timeout(12000),
    });
    if (!resp.ok) throw new Error('WHEP ' + resp.status);
    await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
    return {pc, stream, negotiation_ms: performance.now() - t0};
  };

  const waitFirstFrame = async (video, budgetMs) => {
    const t0 = performance.now();
    await video.play().catch(() => {});
    while (performance.now() - t0 < budgetMs) {
      if (video.videoWidth > 0 && video.currentTime > 0) {
        return performance.now() - t0;
      }
      await new Promise(r => setTimeout(r, 50));
    }
    return null;
  };

  // --- COLD: negotiate into visible video ---
  const coldVideo = document.querySelector('#cold');
  const coldT0 = performance.now();
  let cold = {error: null, first_frame_ms: null, negotiation_ms: null, click_to_frame_ms: null};
  try {
    const neg = await withTimeout(negotiate(), 20000, 'cold-neg');
    cold.negotiation_ms = neg.negotiation_ms;
    coldVideo.srcObject = neg.stream;
    cold.first_frame_ms = await waitFirstFrame(coldVideo, 15000);
    cold.click_to_frame_ms = cold.first_frame_ms == null
      ? null : (performance.now() - coldT0);
    // tear down cold for fairness on warm path resources
    neg.pc.close();
    coldVideo.srcObject = null;
  } catch (e) {
    cold.error = String(e && e.message || e);
  }

  // --- WARM: negotiate into pool (hidden), hold, then attach ---
  const warmVideo = document.querySelector('#warm');
  let warm = {error: null, first_frame_ms: null, negotiation_ms: null,
              click_to_frame_ms: null, hold_ms: warmHoldMs, prewarm_ok: false};
  try {
    const neg = await withTimeout(negotiate(), 20000, 'warm-neg');
    warm.negotiation_ms = neg.negotiation_ms;
    warm.prewarm_ok = true;
    // hold in pool without attaching to visible primary tile
    const poolVideo = document.querySelector('#pool');
    poolVideo.srcObject = neg.stream;
    await poolVideo.play().catch(() => {});
    // wait until pool has a frame (session truly warm)
    const poolReady = await waitFirstFrame(poolVideo, 15000);
    if (poolReady == null) throw new Error('prewarm never got frame');
    await new Promise(r => setTimeout(r, warmHoldMs));

    // PROMOTION: attach already-live stream to visible tile (no renegotiation)
    const clickT0 = performance.now();
    warmVideo.srcObject = neg.stream;
    warm.first_frame_ms = await waitFirstFrame(warmVideo, 8000);
    warm.click_to_frame_ms = warm.first_frame_ms == null
      ? null : (performance.now() - clickT0);
    neg.pc.close();
  } catch (e) {
    warm.error = String(e && e.message || e);
  }

  let gpu = null;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (gl) {
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      gpu = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'webgl';
    }
  } catch (_) {}

  return {
    status: 'ok',
    gpu,
    cold,
    warm,
    speedup: (cold.click_to_frame_ms && warm.click_to_frame_ms)
      ? +(cold.click_to_frame_ms / warm.click_to_frame_ms).toFixed(2) : null,
  };
}
"""


def find_chrome() -> str:
    for p in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "google-chrome",
        "chromium",
    ):
        if Path(p).exists() or p in {"google-chrome", "chromium"}:
            return p
    raise SystemExit("Chrome/Chromium not found")


def run_prewarm(endpoint: str, *, warm_hold_ms: int = 1500) -> dict:
    from playwright.sync_api import sync_playwright

    html = """<!doctype html><html><body style="margin:0;background:#111;color:#eee;font:14px sans-serif">
    <div>COLD</div><video id="cold" autoplay playsinline muted style="width:480px;height:270px;background:#000"></video>
    <div>WARM</div><video id="warm" autoplay playsinline muted style="width:480px;height:270px;background:#000"></video>
    <video id="pool" autoplay playsinline muted style="width:1px;height:1px;opacity:0"></video>
    </body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=find_chrome(),
            headless=False,
            args=[
                "--use-gl=angle",
                "--use-angle=metal",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--enable-features=PlatformHEVCDecoderSupport",
            ],
        )
        page = browser.new_page()
        page.set_content(html)
        result = page.evaluate(PREWARM_JS, {
            "endpoint": endpoint,
            "warmHoldMs": warm_hold_ms,
        })
        browser.close()
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", default="cam01")
    parser.add_argument("--synthetic", action="store_true",
                        help="Use local file→MediaMTX path (no gov credentials)")
    parser.add_argument("--warm-hold-ms", type=int, default=1500)
    parser.add_argument("--out", type=Path,
                        default=OUT / "prewarm_cold_vs_warm.json")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.synthetic:
        # Local publish via synthetic helper (single stream)
        from tools.perf_synthetic_whep_scale import start_synthetic
        cams, mtx, pubs = start_synthetic(1, 90)
        cam = cams[0]
        try:
            endpoint = f"http://127.0.0.1:8889/stream/gov-{cam}/whep"
            wall = run_prewarm(endpoint, warm_hold_ms=args.warm_hold_ms)
        finally:
            stop_all(mtx, pubs)
            for p in pubs:
                if p.poll() is None:
                    p.kill()
        source = "SYNTHETIC"
    else:
        if not configured():
            print("credentials not configured", file=sys.stderr)
            return 2
        cam = args.camera
        mtx, pubs = start_publishers([cam], seconds=90, transcode=set())
        try:
            endpoint = f"http://127.0.0.1:8889/stream/gov-{cam}/whep"
            wall = run_prewarm(endpoint, warm_hold_ms=args.warm_hold_ms)
        finally:
            stop_all(mtx, pubs)
        source = "GOVERNMENT"

    cold_ms = (wall.get("cold") or {}).get("click_to_frame_ms")
    warm_ms = (wall.get("warm") or {}).get("click_to_frame_ms")
    verdict = "FAIL"
    if cold_ms and warm_ms and warm_ms < cold_ms * 0.75:
        verdict = "PASS"
    elif cold_ms and warm_ms:
        verdict = "AMBER"
    elif warm_ms:
        verdict = "AMBER"

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED" if source == "GOVERNMENT" else "MEASURED_SYNTHETIC",
        "source": source,
        "camera_id": cam,
        "endpoint_safe": f"/stream/gov-{cam}/whep",
        "gpu": wall.get("gpu"),
        "cold": wall.get("cold"),
        "warm": wall.get("warm"),
        "speedup": wall.get("speedup"),
        "overall": verdict,
        "note": (
            "Warm path attaches a pre-negotiated MediaStream to a visible "
            "<video> without a second WHEP POST."
        ),
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "overall": verdict,
        "source": source,
        "cold_ms": cold_ms,
        "warm_ms": warm_ms,
        "speedup": wall.get("speedup"),
        "gpu": wall.get("gpu"),
    }))
    return 0 if verdict != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
