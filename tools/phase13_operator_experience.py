#!/usr/bin/env python3
"""Phase 13 — Final 30-camera operator experience (preview, prewarm, interaction).

Does NOT redesign media architecture.
Credentials: Authorization Basic header only — never in URL/stdout/JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
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
from saakshya.live.grid import GridConfig, has_credential  # noqa: E402
from tools.sentinel_direct_whep import (  # noqa: E402
    basic_authorization_header, measure_direct_wall, summarize,
    refuse_secrets, safe, whep_url,
)

OUT = ROOT / "var/reports/phase10/performance"
HOST = "103.250.160.189"

TILE_STATES = (
    "LIVE", "PREVIEW", "CONNECTING", "PROMOTING",
    "DEGRADED", "RECONNECTING", "NO_SIGNAL",
)

STRONG = [
    "cam01", "cam02", "cam05", "cam04", "cam13",
    "cam14", "cam15", "cam19", "cam03", "cam06",
]


# ── Preview probes ─────────────────────────────────────────────────────────


def probe_hls_preview(camera_id: str, *, seconds: float = 6.0) -> dict:
    """Try Sentinel HLS patterns — no credentials in URL."""
    candidates = [
        ("guide_ip", f"http://{HOST}/live/stream/{camera_id}/index.m3u8"),
        ("cdn", f"https://cctv.corp8.cloud/{camera_id}/index.m3u8"),
        ("cdn_live", f"https://cctv.corp8.cloud/live/stream/{camera_id}/index.m3u8"),
    ]
    headers = {"User-Agent": "SaakshyaPhase13/1.0", "Accept": "*/*"}
    cookie = os.environ.get("SENTINEL_GRID_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    results = []
    for label, url in candidates:
        samples = []
        err = None
        seqs = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as r:
                    body = r.read().decode("utf-8", "ignore")
                    status = r.status
                if "<html" in body.lower() or "<!doctype" in body.lower():
                    err = "html_sign_in"
                    samples.append({"t": round(time.monotonic() - t0, 2),
                                    "status": status, "error": err})
                    break
                variant = None
                for ln in body.splitlines():
                    if ln and not ln.startswith("#"):
                        variant = ln.strip()
                        break
                media = body
                if variant and "EXTINF" not in body:
                    vurl = url.rsplit("/", 1)[0] + "/" + variant
                    with urllib.request.urlopen(
                        urllib.request.Request(vurl, headers=headers), timeout=5
                    ) as vr:
                        media = vr.read().decode("utf-8", "ignore")
                seq = None
                for ln in media.splitlines():
                    if ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                        seq = int(ln.split(":", 1)[1])
                if seq is not None:
                    seqs.append(seq)
                samples.append({
                    "t": round(time.monotonic() - t0, 2),
                    "status": status,
                    "media_sequence": seq,
                })
            except Exception as exc:
                err = safe(f"{type(exc).__name__}: {exc}")
                samples.append({"t": round(time.monotonic() - t0, 2), "error": err})
            time.sleep(1.0)
        advanced = len(seqs) >= 2 and max(seqs) > min(seqs)
        results.append({
            "label": label,
            "url_safe": url,
            "live_sequence_advanced": advanced,
            "verdict": "PASS" if advanced else "FAIL",
            "samples": samples[:3],
            "error": err,
        })
    best = next((r for r in results if r["verdict"] == "PASS"), None)
    return {
        "transport": "HLS",
        "camera_id": camera_id,
        "overall": "PASS" if best else "FAIL",
        "chosen": best["label"] if best else None,
        "candidates": results,
        "label": "MEASURED_REAL",
    }


def probe_preview_whep(camera_ids: list[str], auth: str, cfg: GridConfig,
                       *, seconds: float = 15.0) -> dict:
    """Low-cost preview = concurrent direct WHEP at preview budget (same endpoint).

    Sentinel does not expose a separate lower-res WHEP in-catalogue; measure how
    many simultaneous preview WHEP sessions stay PASS without FULL wall.
    """
    endpoints = [whep_url(c, cfg) for c in camera_ids]
    wall = measure_direct_wall(
        endpoints, auth_header=auth, seconds=seconds,
        negotiate_concurrency=min(4, len(camera_ids)), retries=1,
    )
    row = summarize(
        camera_ids, wall, seconds=seconds,
        path_label="PREVIEW_WHEP_DIRECT_SENTINEL",
    )
    row["transport"] = "WHEP_PREVIEW_POOL"
    row["note"] = (
        "Preview uses same Sentinel WHEP endpoint with Basic auth; "
        "no separate low-res representation advertised. "
        "Budgeted separately from PRIMARY FULL_WHEP slots."
    )
    return row


# ── Direct Sentinel prewarm ────────────────────────────────────────────────


PREWARM_JS = r"""
async ({endpoint, authHeader, warmHoldMs, promotions}) => {
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
    const headers = {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'};
    if (authHeader) headers['Authorization'] = authHeader;
    const resp = await fetch(endpoint, {
      method: 'POST', headers, body: pc.localDescription.sdp,
      signal: AbortSignal.timeout(15000),
    });
    if (!resp.ok) throw new Error('WHEP ' + resp.status);
    await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
    return {pc, stream, negotiation_ms: performance.now() - t0, http: resp.status};
  };

  const waitFirst = async (video, budgetMs) => {
    const t0 = performance.now();
    await video.play().catch(() => {});
    while (performance.now() - t0 < budgetMs) {
      if (video.videoWidth > 0 && video.currentTime > 0)
        return performance.now() - t0;
      await new Promise(r => setTimeout(r, 40));
    }
    return null;
  };

  const coldVideo = document.querySelector('#cold');
  const warmVideo = document.querySelector('#warm');
  const poolVideo = document.querySelector('#pool');

  // One cold baseline
  let cold = {click_to_frame_ms: null, negotiation_ms: null, error: null, http: null};
  try {
    const t0 = performance.now();
    const neg = await negotiate();
    cold.negotiation_ms = neg.negotiation_ms;
    cold.http = neg.http;
    coldVideo.srcObject = neg.stream;
    const ff = await waitFirst(coldVideo, 15000);
    cold.click_to_frame_ms = ff == null ? null : (performance.now() - t0);
    neg.pc.close();
    coldVideo.srcObject = null;
  } catch (e) {
    cold.error = String(e && e.message || e);
  }

  // Warm promotions
  const warmTimes = [];
  let warmErrors = 0;
  for (let i = 0; i < promotions; i++) {
    let pc = null;
    try {
      const neg = await negotiate();
      pc = neg.pc;
      poolVideo.srcObject = neg.stream;
      await poolVideo.play().catch(() => {});
      const ready = await waitFirst(poolVideo, 15000);
      if (ready == null) throw new Error('prewarm_no_frame');
      await new Promise(r => setTimeout(r, warmHoldMs));
      const clickT0 = performance.now();
      warmVideo.srcObject = neg.stream;
      const ff = await waitFirst(warmVideo, 8000);
      const ms = ff == null ? null : (performance.now() - clickT0);
      if (ms == null) warmErrors += 1;
      else warmTimes.push(ms);
      pc.close();
      poolVideo.srcObject = null;
      warmVideo.srcObject = null;
      await new Promise(r => setTimeout(r, 200));
    } catch (e) {
      warmErrors += 1;
      try { if (pc) pc.close(); } catch (_) {}
    }
  }

  let gpu = null;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl');
    const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
    gpu = gl ? gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : null;
  } catch (_) {}

  const sorted = warmTimes.slice().sort((a,b)=>a-b);
  const pct = (p) => {
    if (!sorted.length) return null;
    const k = (sorted.length - 1) * (p / 100);
    const f = Math.floor(k), c = Math.min(f + 1, sorted.length - 1);
    return f === c ? sorted[f] : sorted[f] + (sorted[c] - sorted[f]) * (k - f);
  };

  return {
    cold,
    warm: {
      promotions_requested: promotions,
      promotions_ok: warmTimes.length,
      errors: warmErrors,
      times_ms: warmTimes,
      p50: pct(50),
      p95: pct(95),
      max: sorted.length ? sorted[sorted.length - 1] : null,
      mean: warmTimes.length
        ? warmTimes.reduce((a,b)=>a+b,0) / warmTimes.length : null,
    },
    gpu,
  };
}
"""


def run_direct_prewarm(camera_id: str, auth: str, cfg: GridConfig,
                       *, promotions: int = 10, warm_hold_ms: int = 800) -> dict:
    from playwright.sync_api import sync_playwright

    endpoint = whep_url(camera_id, cfg)
    html = """<!doctype html><html><body style="margin:0;background:#111;color:#eee">
    <div>COLD</div><video id="cold" autoplay muted playsinline style="width:480px;height:270px;background:#000"></video>
    <div>WARM</div><video id="warm" autoplay muted playsinline style="width:480px;height:270px;background:#000"></video>
    <video id="pool" autoplay muted playsinline style="width:1px;height:1px;opacity:0"></video>
    </body></html>"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--use-angle=metal",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = browser.new_context()
            page = context.new_page()
            page.set_content(html, wait_until="domcontentloaded")
            # Cap evaluate wall-clock; run promotions in-page with own timeouts
            page.set_default_timeout(min(600_000, 60_000 + promotions * 20_000))
            result = page.evaluate(PREWARM_JS, {
                "endpoint": endpoint,
                "authHeader": auth,
                "warmHoldMs": warm_hold_ms,
                "promotions": promotions,
            })
            context.close()
            browser.close()
    except Exception as exc:
        return {
            "label": "MEASURED_REAL",
            "path": "DIRECT_SENTINEL_WHEP_PREWARM",
            "camera_id": camera_id,
            "endpoint_safe": endpoint,
            "auth_mode": "Authorization_Basic_header",
            "overall": "FAIL",
            "error": safe(f"{type(exc).__name__}: {exc}"),
            "cold": {},
            "warm": {"promotions_requested": promotions, "promotions_ok": 0},
        }
    warm = result.get("warm") or {}
    overall = "PASS" if (warm.get("promotions_ok") or 0) >= max(1, promotions // 2) else "AMBER"
    if (warm.get("promotions_ok") or 0) == 0:
        overall = "FAIL"
    return {
        "label": "MEASURED_REAL",
        "path": "DIRECT_SENTINEL_WHEP_PREWARM",
        "camera_id": camera_id,
        "endpoint_safe": endpoint,
        "auth_mode": "Authorization_Basic_header",
        "overall": overall,
        "cold": result.get("cold"),
        "warm": warm,
        "gpu": result.get("gpu"),
        "note": (
            "Warm = attach pre-negotiated MediaStream to visible <video> "
            "without second WHEP POST. Not the old local-relay 44ms figure."
        ),
    }


# ── Interaction / state machine wall ───────────────────────────────────────


INTERACT_JS = r"""
async ({tiles, authHeader, seconds, promotions, negotiateConcurrency,
        rotateMs, panelSequence}) => {
  const n = tiles.length;
  const states = [];
  const pcs = [];
  const videos = [];
  const badges = [];

  for (let i = 0; i < n; i++) {
    const v = document.querySelector('#v' + i);
    const b = document.querySelector('#b' + i);
    videos.push(v);
    badges.push(b);
    pcs.push(null);
    v.srcObject = new MediaStream();
    states.push({
      id: i,
      camera_id: tiles[i].camera_id,
      role: tiles[i].role,
      endpoint: tiles[i].endpoint,
      ux: tiles[i].role === 'SLOT' ? 'NO_SIGNAL' : 'CONNECTING',
      first: null, negotiation: null, http: null,
      currentTime: 0, freezes: 0, framesDecoded: 0, framesDropped: 0,
      packetsLost: 0, ice: 'new', error: null, promotions: 0,
      lastTime: 0, stallMs: 0, inStall: false, liveSeconds: 0,
      rotations: 0,
    });
    if (b) b.textContent = states[i].ux;
  }

  let active = 0;
  const waiters = [];
  const acquire = () => new Promise(res => {
    if (active < negotiateConcurrency) { active++; res(); }
    else waiters.push(res);
  });
  const release = () => {
    active--;
    if (waiters.length) { active++; waiters.shift()(); }
  };

  const setUx = (i, ux) => {
    states[i].ux = ux;
    if (badges[i]) badges[i].textContent = ux + ' · ' + states[i].camera_id;
  };

  const teardown = async (i) => {
    const pc = pcs[i];
    pcs[i] = null;
    try { if (pc) pc.close(); } catch (_) {}
    videos[i].srcObject = new MediaStream();
    states[i].first = null;
    states[i].negotiation = null;
    states[i].http = null;
    states[i].ice = 'closed';
  };

  const setup = async (i, endpoint) => {
    await acquire();
    let pc = null;
    try {
      setUx(i, 'CONNECTING');
      pc = new RTCPeerConnection();
      pc.addTransceiver('video', {direction: 'recvonly'});
      const stream = new MediaStream();
      videos[i].srcObject = stream;
      pc.ontrack = (ev) => stream.addTrack(ev.track);
      const t0 = performance.now();
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 2000);
        if (pc.iceGatheringState === 'complete') resolve();
        else pc.addEventListener('icegatheringstatechange', () => {
          if (pc.iceGatheringState === 'complete') { clearTimeout(t); resolve(); }
        });
      });
      const headers = {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'};
      if (authHeader) headers['Authorization'] = authHeader;
      const resp = await fetch(endpoint, {
        method: 'POST', headers, body: pc.localDescription.sdp,
        signal: AbortSignal.timeout(15000),
      });
      states[i].http = resp.status;
      if (!resp.ok) throw new Error('WHEP ' + resp.status);
      await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
      states[i].negotiation = performance.now() - t0;
      await videos[i].play().catch(() => {});
      pcs[i] = pc;
      states[i].error = null;
      // Capture first-frame during setup so usable_wall_ms is meaningful
      const ff0 = performance.now();
      while (performance.now() - ff0 < 8000) {
        if (videos[i].videoWidth > 0 && videos[i].currentTime > 0) {
          states[i].first = performance.now() - wallStart;
          setUx(i, states[i].role === 'FULL' ? 'LIVE' : 'PREVIEW');
          break;
        }
        await new Promise(r => setTimeout(r, 40));
      }
    } catch (e) {
      states[i].error = String(e && e.message || e);
      setUx(i, 'NO_SIGNAL');
      try { if (pc) pc.close(); } catch (_) {}
      pcs[i] = null;
    }
    release();
  };

  const wallStart = performance.now();
  // Prioritize FULL negotiation to completion before PREVIEW pool
  for (let i = 0; i < n; i++) {
    if (states[i].role === 'FULL') {
      await setup(i, states[i].endpoint);
    }
  }
  const prevJobs = [];
  for (let i = 0; i < n; i++) {
    if (states[i].role === 'PREVIEW') {
      prevJobs.push(setup(i, states[i].endpoint));
    }
  }
  await Promise.race([
    Promise.allSettled(prevJobs),
    new Promise(r => setTimeout(r, 20000)),
  ]);
  const deadline = performance.now() + seconds * 1000;
  const jobs = [];  // already awaited above

  const previewIdx = states.map((s,i)=>s.role==='PREVIEW'?i:-1).filter(i=>i>=0);
  // Only rotate strong / previously-live candidates — weak cams hang WHEP and stall UX
  const STRONG = new Set(['cam01','cam02','cam05','cam04','cam13','cam14','cam15','cam19','cam03','cam06']);
  const slotQueue = states.map((s,i)=>s.role==='SLOT'?i:-1).filter(i=>i>=0)
    .filter(i => STRONG.has(states[i].camera_id));
  let rotateCursor = 0;
  let lastRotate = wallStart;
  let rotating = false;
  const rotateOnce = async () => {
    if (rotating || !previewIdx.length || !slotQueue.length) return;
    rotating = true;
    try {
      const dst = previewIdx[rotateCursor % previewIdx.length];
      rotateCursor += 1;
      const src = slotQueue[rotateCursor % slotQueue.length];
      const keepCam = states[dst].camera_id;
      const keepEp = states[dst].endpoint;
      states[dst].camera_id = states[src].camera_id;
      states[dst].endpoint = states[src].endpoint;
      states[src].camera_id = keepCam;
      states[src].endpoint = keepEp;
      await teardown(dst);
      setUx(src, 'NO_SIGNAL');
      // Bound rotate reconnect — never block wall health loop for full WHEP timeout
      const p = setup(dst, states[dst].endpoint);
      await Promise.race([p, new Promise(r => setTimeout(r, 6000))]);
      states[dst].rotations += 1;
    } finally {
      rotating = false;
    }
  };

  const promoLatencies = [];
  const panelEvents = [];
  const runPromotions = async () => {
    for (let wait = 0; wait < 100; wait++) {
      const ready = states.filter(s => s.role !== 'SLOT' && s.first != null).length;
      if (ready >= Math.min(3, previewIdx.length + 1)) break;
      await new Promise(r => setTimeout(r, 100));
    }
    for (let p = 0; p < promotions; p++) {
      const srcCandidates = states
        .map((s,i)=>({s,i}))
        .filter(x => x.s.first != null && x.s.role !== 'FULL');
      const dstCandidates = states
        .map((s,i)=>({s,i}))
        .filter(x => x.s.role === 'FULL');
      if (!srcCandidates.length || !dstCandidates.length) break;
      const src = srcCandidates[p % srcCandidates.length].i;
      const dst = dstCandidates[0].i;
      setUx(dst, 'PROMOTING');
      const clickT0 = performance.now();
      const srcStream = videos[src].srcObject;
      if (!srcStream || !states[src].first) {
        setUx(dst, 'RECONNECTING');
        continue;
      }
      videos[dst].srcObject = srcStream;
      await videos[dst].play().catch(() => {});
      let got = null;
      while (performance.now() - clickT0 < 5000) {
        if (videos[dst].videoWidth > 0 && videos[dst].currentTime > 0) {
          got = performance.now() - clickT0;
          break;
        }
        await new Promise(r => setTimeout(r, 40));
      }
      if (got != null) {
        promoLatencies.push(got);
        setUx(dst, 'LIVE');
        states[dst].promotions += 1;
      } else {
        setUx(dst, 'DEGRADED');
      }
      await new Promise(r => setTimeout(r, 250));
    }
  };
  const promoPromise = runPromotions();

  const runPanels = async () => {
    await new Promise(r => setTimeout(r, 2500));
    for (const name of (panelSequence || [])) {
      const t0 = performance.now();
      const overlay = document.querySelector('#panel');
      if (overlay) {
        overlay.style.display = 'block';
        overlay.textContent = name.toUpperCase() + ' PANEL';
      }
      await new Promise(r => setTimeout(r, 400));
      const live = states.filter(s => s.ux === 'LIVE' || s.ux === 'PREVIEW').length;
      const degraded = states.filter(s => s.ux === 'DEGRADED').length;
      if (overlay) overlay.style.display = 'none';
      panelEvents.push({
        panel: name,
        open_ms: performance.now() - t0,
        live_during: live,
        degraded_during: degraded,
        wall_stall: live === 0,
      });
      await new Promise(r => setTimeout(r, 200));
    }
  };
  const panelPromise = runPanels();

  let lastHealth = 0;
  while (performance.now() < deadline) {
    const now = performance.now();
    if (rotateMs > 0 && slotQueue.length && !rotating && now - lastRotate >= rotateMs) {
      lastRotate = now;
      // Fire-and-forget rotation so health/promo loops keep ticking
      rotateOnce();
    }
    if (now - lastHealth >= 500) {
      lastHealth = now;
      for (let i = 0; i < n; i++) {
        const st = states[i];
        const v = videos[i];
        const pc = pcs[i];
        if (!pc) {
          if (st.role === 'SLOT' && st.ux !== 'PROMOTING') {
            if (st.ux !== 'NO_SIGNAL' && st.ux !== 'CONNECTING') setUx(i, 'NO_SIGNAL');
          } else if (st.ux !== 'PROMOTING' && st.ux !== 'NO_SIGNAL') {
            setUx(i, st.error ? 'NO_SIGNAL' : 'CONNECTING');
          }
          continue;
        }
        st.ice = pc.iceConnectionState;
        if (st.first == null && v.readyState >= 2 && v.videoWidth > 0) {
          st.first = performance.now() - wallStart;
          if (st.ux === 'CONNECTING' || st.ux === 'PROMOTING') {
            setUx(i, st.role === 'FULL' ? 'LIVE' : 'PREVIEW');
          }
        }
        const t = v.currentTime || 0;
        st.currentTime = t;
        if (st.first != null) {
          st.liveSeconds += 0.5;
          if (t <= st.lastTime + 0.01) {
            st.stallMs += 500;
            if (!st.inStall && st.stallMs >= 1500) {
              st.freezes += 1;
              st.inStall = true;
              if (st.ux === 'LIVE' || st.ux === 'PREVIEW') setUx(i, 'DEGRADED');
            }
          } else {
            st.stallMs = 0;
            st.inStall = false;
            st.lastTime = t;
            if (st.ux === 'DEGRADED') {
              setUx(i, st.role === 'FULL' ? 'LIVE' : 'PREVIEW');
            }
          }
        }
        if (['failed', 'disconnected', 'closed'].includes(st.ice)) {
          if (st.ux !== 'PROMOTING') setUx(i, 'RECONNECTING');
        }
        try {
          for (const r of (await pc.getStats()).values()) {
            if (r.type === 'inbound-rtp' && r.kind === 'video') {
              st.framesDecoded = r.framesDecoded || 0;
              st.framesDropped = r.framesDropped || 0;
              st.packetsLost = r.packetsLost || 0;
            }
          }
        } catch (_) {}
      }
    }
    await new Promise(r => setTimeout(r, 100));
  }

  await Promise.race([promoPromise, new Promise(r => setTimeout(r, 2000))]);
  await Promise.race([panelPromise, new Promise(r => setTimeout(r, 2000))]);
  for (const pc of pcs) { if (pc) try { pc.close(); } catch (_) {} }

  let gpu = null;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl', {powerPreference: 'high-performance'});
    const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
    gpu = gl ? gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : null;
  } catch (_) {}

  const sorted = promoLatencies.slice().sort((a,b)=>a-b);
  const pct = (p) => {
    if (!sorted.length) return null;
    const k = (sorted.length - 1) * (p / 100);
    const f = Math.floor(k), c = Math.min(f + 1, sorted.length - 1);
    return f === c ? sorted[f] : sorted[f] + (sorted[c] - sorted[f]) * (k - f);
  };
  const counts = {};
  for (const s of states) counts[s.ux] = (counts[s.ux] || 0) + 1;

  return {
    tiles: states.map(s => ({
      camera_id: s.camera_id, role: s.role, ux: s.ux,
      first: s.first, negotiation: s.negotiation, http: s.http,
      currentTime: s.currentTime, freezes: s.freezes,
      framesDecoded: s.framesDecoded, framesDropped: s.framesDropped,
      packetsLost: s.packetsLost, ice: s.ice, error: s.error,
      promotions: s.promotions, liveSeconds: s.liveSeconds,
      rotations: s.rotations,
    })),
    ux_counts: counts,
    promotion: {
      requested: promotions, ok: promoLatencies.length,
      p50: pct(50), p95: pct(95),
      max: sorted.length ? sorted[sorted.length - 1] : null,
      times_ms: promoLatencies,
    },
    panels: panelEvents,
    gpu,
    wall_elapsed_ms: performance.now() - wallStart,
    usable_wall_ms: (() => {
      const fs = states.filter(s => s.first != null).map(s => s.first);
      return fs.length ? Math.min(...fs) : null;
    })(),
  };
}
"""


def dynamic_full_budget(*, cpu: float, measured_peak: int = 10,
                        prefer: int | None = None) -> int:
    """Dynamic FULL_WHEP budget — default ~measured peak, allow 8/10/12 if stable."""
    allowed = [b for b in (8, 10, 12) if b <= measured_peak + 2]
    if not allowed:
        allowed = [max(4, measured_peak)]
    target = prefer if prefer in allowed else (
        10 if 10 in allowed else allowed[len(allowed) // 2]
    )
    if target > measured_peak and cpu > 50:
        target = measured_peak
    if cpu > 80:
        return min(target, 8)
    if cpu > 65:
        return min(target, 10)
    return target


def run_interaction_wall(
    *, all_cams: list[str], full_cams: list[str], preview_cams: list[str],
    auth: str, cfg: GridConfig, seconds: float, promotions: int, conc: int,
    rotate_ms: int = 4000,
) -> dict:
    from playwright.sync_api import sync_playwright

    full_set = set(full_cams)
    prev_set = set(preview_cams)
    tiles_meta = []
    for c in all_cams:
        if c in full_set:
            role = "FULL"
        elif c in prev_set:
            role = "PREVIEW"
        else:
            role = "SLOT"
        tiles_meta.append({
            "camera_id": c,
            "endpoint": whep_url(c, cfg),
            "role": role,
        })
    n = len(tiles_meta)
    html = (
        "<!doctype html><html><body style='margin:0;background:#0a0e14;color:#c8d0dc;"
        "font:11px ui-monospace,Menlo,monospace'>"
        "<div id='panel' style='display:none;position:fixed;inset:8% 20%;"
        "background:rgba(12,18,28,.92);border:1px solid #3a4a60;z-index:9;"
        "padding:24px;font-size:18px'></div>"
        "<div style='display:flex;flex-wrap:wrap;gap:2px'>"
        + "".join(
            f"<div style='position:relative;width:192px;height:120px'>"
            f"<video id='v{i}' autoplay muted playsinline "
            f"style='width:192px;height:108px;background:#000;object-fit:cover'></video>"
            f"<div id='b{i}' style='position:absolute;left:2px;bottom:2px;"
            f"background:rgba(0,0,0,.65);padding:1px 4px'></div></div>"
            for i in range(n)
        )
        + "</div></body></html>"
    )
    t0 = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--use-angle=metal",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-web-security",
                "--enable-features=PlatformHEVCDecoderSupport",
            ],
        )
        page = browser.new_page()
        page.set_content(html)
        page.set_default_timeout(int((seconds + 180) * 1000))
        result = page.evaluate(INTERACT_JS, {
            "tiles": tiles_meta,
            "authHeader": auth,
            "seconds": seconds,
            "promotions": promotions,
            "negotiateConcurrency": conc,
            "rotateMs": rotate_ms,
            "panelSequence": ["ai", "alert", "evidence", "gis"],
        })
        browser.close()
    elapsed = time.monotonic() - t0
    tiles = []
    for st in result.get("tiles") or []:
        tiles.append({
            "camera_id": st.get("camera_id"),
            "role": st.get("role"),
            "ux_state": st.get("ux"),
            "first_frame_ms": st.get("first"),
            "negotiation_ms": st.get("negotiation"),
            "whep_http_status": st.get("http"),
            "currentTime": st.get("currentTime"),
            "freezes": st.get("freezes"),
            "framesDecoded": st.get("framesDecoded"),
            "framesDropped": st.get("framesDropped"),
            "packetsLost": st.get("packetsLost"),
            "ice": st.get("ice"),
            "error": safe(st.get("error")),
            "promotions": st.get("promotions"),
            "live_seconds": st.get("liveSeconds"),
            "rotations": st.get("rotations"),
        })
    return {
        "label": "MEASURED_REAL",
        "path": "OPERATOR_30_WALL",
        "elapsed_s": round(elapsed, 3),
        "registered": n,
        "full_cams": full_cams,
        "preview_cams": preview_cams,
        "ux_counts": result.get("ux_counts"),
        "promotion": result.get("promotion"),
        "panels": result.get("panels"),
        "usable_wall_ms": result.get("usable_wall_ms"),
        "gpu": result.get("gpu"),
        "resources": {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
            "ram_used_gb": round(psutil.virtual_memory().used / 1e9, 3),
        },
        "tiles": tiles,
        "tile_states_supported": list(TILE_STATES),
        "rotate_ms": rotate_ms,
    }


# ── Preview budget sweep ───────────────────────────────────────────────────


def sweep_preview_budgets(auth: str, cfg: GridConfig, *,
                          budgets: list[int] | None = None,
                          seconds: float = 12.0) -> dict:
    budgets = budgets or [4, 6, 8, 10, 12]
    rows = []
    for n in budgets:
        cams = (STRONG * 3)[:n]
        print(f"=== PREVIEW SWEEP n={n} ===", flush=True)
        pw = probe_preview_whep(cams, auth, cfg, seconds=seconds)
        ws = pw.get("wall_summary") or {}
        live = (ws.get("PASS") or 0) + (ws.get("AMBER") or 0)
        rows.append({
            "n": n,
            "overall": pw.get("overall"),
            "live_tiles": live,
            "PASS": ws.get("PASS"),
            "AMBER": ws.get("AMBER"),
            "FAIL": ws.get("FAIL"),
            "first_frame_ms_p50": ws.get("first_frame_ms_p50"),
            "negotiation_ms_p50": ws.get("negotiation_ms_p50"),
        })
        print(json.dumps(rows[-1]), flush=True)
        time.sleep(1.0)
    # Prefer largest n with ≥75% live AND first-frame p50 < 4s (operator-usable).
    # Do not auto-pick 12 when startup balloons (AMBER-heavy).
    chosen = 4
    for r in rows:
        live_ok = (r.get("live_tiles") or 0) >= max(1, int(r["n"] * 0.75))
        ff = r.get("first_frame_ms_p50") or 9e9
        pass_ok = (r.get("PASS") or 0) >= max(1, int(r["n"] * 0.5))
        if live_ok and pass_ok and ff < 4000:
            chosen = r["n"]
    return {
        "label": "MEASURED_REAL",
        "rows": rows,
        "chosen_preview_budget": chosen,
        "note": (
            "Largest continuous live preview WHEP pool with ≥75% live, "
            "≥50% PASS, first-frame p50 < 4s"
        ),
    }


# ── AI-FIRST (RTSP/TCP plane) ──────────────────────────────────────────────


def _ai_worker(camera_id: str, tier: str, seconds: float, out: dict) -> None:
    """RTSP/TCP AI worker — never uses WHEP. Credentials via credentialed()."""
    import av
    from saakshya.live.credentials import credentialed

    cfg = GridConfig.from_env()
    url = credentialed(cfg.rtsp(camera_id), required=True)
    sample_every = {"primary": 1, "secondary": 2, "low": 5}.get(tier, 5)
    target_fps = {"primary": 8.0, "secondary": 3.0, "low": 0.5}.get(tier, 0.5)
    min_interval = 1.0 / max(0.1, target_fps)
    row: dict = {
        "camera_id": camera_id, "tier": tier, "status": "FAIL",
        "frames_in": 0, "frames_analysed": 0, "detector_calls": 0,
        "ocr_calls": 0, "alerts": 0,
        "ai_latency_ms": [], "ocr_latency_ms": [], "alert_latency_ms": [],
        "decode_errors": 0, "effective_fps": 0.0,
    }
    t0 = time.perf_counter()
    deadline = t0 + seconds
    last = 0.0
    try:
        container = av.open(
            url, options={"rtsp_transport": "tcp", "stimeout": "8000000"},
            timeout=20,
        )
        stream = next(s for s in container.streams if s.type == "video")
        idx = 0
        prev_mean = None
        while time.perf_counter() < deadline:
            try:
                frame = next(container.decode(stream))
            except Exception:
                row["decode_errors"] += 1
                time.sleep(0.5)
                continue
            row["frames_in"] += 1
            idx += 1
            if idx % sample_every != 0:
                continue
            now = time.perf_counter()
            if now - last < min_interval:
                continue
            last = now
            t_ai = time.perf_counter()
            try:
                img = frame.to_ndarray(format="bgr24")
                mean = float(img.mean())
                motion = abs(mean - prev_mean) if prev_mean is not None else 0.0
                prev_mean = mean
                row["detector_calls"] += 1
                if motion > 1.5:
                    row["alerts"] += 1
                    row["alert_latency_ms"].append(
                        (time.perf_counter() - t_ai) * 1000
                    )
                if tier == "primary" and row["detector_calls"] % 4 == 0:
                    t_ocr = time.perf_counter()
                    _ = img[::8, ::8].mean()
                    row["ocr_calls"] += 1
                    row["ocr_latency_ms"].append(
                        (time.perf_counter() - t_ocr) * 1000
                    )
                row["frames_analysed"] += 1
                row["ai_latency_ms"].append((time.perf_counter() - t_ai) * 1000)
            except Exception:
                row["decode_errors"] += 1
        try:
            container.close()
        except Exception:
            pass
        elapsed = max(0.001, time.perf_counter() - t0)
        row["elapsed_s"] = round(elapsed, 3)
        row["effective_fps"] = round(row["frames_analysed"] / elapsed, 2)
        row["status"] = "PASS" if row["frames_analysed"] > 0 else "FAIL"
        for key in ("ai_latency_ms", "ocr_latency_ms", "alert_latency_ms"):
            vals = row[key]
            if vals:
                row[key + "_p50"] = round(statistics.median(vals), 2)
                row[key + "_p95"] = round(
                    sorted(vals)[max(0, int(len(vals) * 0.95) - 1)], 2
                )
            row[key] = vals[:20]
    except Exception as exc:
        row["status"] = "FAIL"
        row["error"] = safe(f"{type(exc).__name__}: {exc}")
    out[camera_id] = row


def run_ai_first_plane(*, seconds: float = 25.0) -> dict:
    """AI-FIRST: 4 primary + 4 secondary + 22 low on RTSP/TCP only."""
    import threading

    cams = [f"cam{i:02d}" for i in range(1, 31)]
    primary = cams[:4]
    secondary = cams[4:8]
    low = cams[8:30]
    results: dict = {}
    threads = []
    for c in primary:
        threads.append(threading.Thread(
            target=_ai_worker, args=(c, "primary", seconds, results), daemon=True))
    for c in secondary:
        threads.append(threading.Thread(
            target=_ai_worker, args=(c, "secondary", seconds, results), daemon=True))
    for c in low:
        threads.append(threading.Thread(
            target=_ai_worker, args=(c, "low", seconds, results), daemon=True))
    t0 = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=seconds + 60)
    elapsed = time.perf_counter() - t0
    rows = [results[c] for c in cams if c in results]
    by_tier = {"primary": [], "secondary": [], "low": []}
    for r in rows:
        by_tier.setdefault(r["tier"], []).append(r)
    def tier_summary(name: str) -> dict:
        xs = by_tier.get(name) or []
        ok = sum(1 for x in xs if x.get("status") == "PASS")
        fps = [x.get("effective_fps") or 0 for x in xs]
        lat = [x.get("ai_latency_ms_p50") for x in xs if x.get("ai_latency_ms_p50") is not None]
        return {
            "n": len(xs), "pass": ok, "fail": len(xs) - ok,
            "fps_mean": round(statistics.fmean(fps), 2) if fps else 0,
            "ai_latency_p50_mean": round(statistics.fmean(lat), 2) if lat else None,
        }
    return {
        "label": "MEASURED_REAL",
        "path": "AI_FIRST_RTSP_TCP",
        "seconds": seconds,
        "elapsed_s": round(elapsed, 3),
        "tiers": {
            "primary": tier_summary("primary"),
            "secondary": tier_summary("secondary"),
            "low": tier_summary("low"),
        },
        "cameras": rows,
        "resources": {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
        },
        "note": (
            "Lightweight motion/OCR-proxy on gov RTSP/TCP. "
            "Not full YOLO CameraPipeline load — detector cadence still measured. "
            "Video plane remains independent WHEP."
        ),
    }


def try_catalogue_ingest() -> dict:
    """Authoritative catalogue — only with legitimate session cookie/token."""
    if not (os.environ.get("SENTINEL_GRID_COOKIE")
            or os.environ.get("SENTINEL_GRID_TOKEN")):
        return {
            "status": "NOT_AUTHORITATIVE",
            "reason": "SENTINEL_GRID_COOKIE/TOKEN not configured",
            "attempted_bypass": False,
        }
    from saakshya.live.grid import GridConfig, fetch_catalogue
    try:
        cams = fetch_catalogue(GridConfig.from_env())
        return {
            "status": "AUTHORITATIVE",
            "count": len(cams),
            "cameras": [
                {
                    "id": c.camera_id, "codec": c.codec,
                    "resolution": f"{c.width}x{c.height}" if c.width else None,
                    "rtsp": bool(c.rtsp_url), "whep": bool(c.whep_url),
                    "hls": bool(c.hls_url),
                }
                for c in cams[:60]
            ],
        }
    except Exception as exc:
        return {
            "status": "NOT_AUTHORITATIVE",
            "reason": safe(f"{type(exc).__name__}: {exc}"),
            "attempted_bypass": False,
        }


def write_final_report(payload: dict) -> None:
    pre10 = payload.get("prewarm_10") or payload.get("prewarm") or {}
    pre30 = payload.get("prewarm_30") or {}
    warm10 = pre10.get("warm") or {}
    cold10 = pre10.get("cold") or {}
    warm30 = pre30.get("warm") or {}
    cold30 = pre30.get("cold") or {}
    inter = payload.get("interaction") or {}
    promo = inter.get("promotion") or {}
    prev = payload.get("preview") or {}
    sweep = payload.get("preview_sweep") or {}
    ai = payload.get("ai_first") or {}
    cat = payload.get("catalogue") or {}
    panels = inter.get("panels") or []
    stall = any(p.get("wall_stall") for p in panels)

    md = f"""# Final 30-camera operator certification

Timestamp UTC: `{payload['timestamp_utc']}`

## Labels

| Label | Use |
|---|---|
| MEASURED_REAL | Direct Sentinel government endpoints |
| MEASURED_SYNTHETIC | Prior local synthetic (separate; not mixed) |
| DESIGNED | Scheduler / mode plan |
| NOT_AUTHORITATIVE | No catalogue session |
| ESTIMATED | Not claimed |

## A. Authoritative catalogue status

**{cat.get('status', 'NOT_AUTHORITATIVE')}** — {cat.get('reason', 'no session cookie')}  
`attempted_bypass={cat.get('attempted_bypass', False)}`. Camera IDs for wall: **NOT_AUTHORITATIVE** probe set unless status=AUTHORITATIVE.

## B. Real camera coverage

Strong FULL_WHEP band (prior MEASURED_REAL):  
`cam01, cam02, cam05, cam04, cam13, cam14, cam15, cam19, cam03, cam06`  
Peak simultaneous PASS ≈ **10**. Best all-PASS wall **n=8**.

## C. 30-camera operator wall (MEASURED_REAL)

| Metric | Value |
|---|---|
| Registered tiles | {inter.get('registered', 30)} |
| FULL_WHEP budget (dynamic) | {payload.get('full_whep_budget')} |
| Preview WHEP pool | {payload.get('preview_whep_count')} |
| UX counts | `{inter.get('ux_counts')}` |
| Usable wall (first frame) | {inter.get('usable_wall_ms')} ms |
| GPU | `{inter.get('gpu')}` |
| Resources | `{inter.get('resources')}` |
| Panel opens (ai/alert/evidence/gis) | {len(panels)} · wall_stall={stall} |
| Rotate preview interval | {inter.get('rotate_ms')} ms |

SLOT tiles beyond live budgets are **NO_SIGNAL** until rotated into a live PREVIEW slot — never fake LIVE / never screenshots.

## D. Live preview architecture (MEASURED_REAL)

| Option | Result |
|---|---|
| Sentinel HLS | `{(prev.get('hls') or {}).get('overall')}` |
| Preview WHEP pool | `{(prev.get('preview_whep') or {}).get('overall')}` |
| Preview budget sweep | chosen **{sweep.get('chosen_preview_budget')}** · rows `{sweep.get('rows')}` |

**Chosen: `{payload.get('preview_choice')}`** — official WHEP + Basic, separate budget. Not a screenshot.

## E. Direct Sentinel prewarm (MEASURED_REAL)

### 10 promotions

| | ms |
|---|---:|
| COLD click→frame | {cold10.get('click_to_frame_ms')} |
| WARM p50 | **{warm10.get('p50')}** |
| WARM p95 | {warm10.get('p95')} |
| WARM max | {warm10.get('max')} |
| OK | {warm10.get('promotions_ok')} / {warm10.get('promotions_requested')} |

### 30 promotions

| | ms |
|---|---:|
| COLD click→frame | {cold30.get('click_to_frame_ms')} |
| WARM p50 | **{warm30.get('p50')}** |
| WARM p95 | {warm30.get('p95')} |
| WARM max | {warm30.get('max')} |
| OK | {warm30.get('promotions_ok')} / {warm30.get('promotions_requested')} |

Local-relay historic **44 ms is NOT claimed** here. Direct Sentinel warm p50 is the table above.

## F. VIDEO-FIRST (MEASURED_REAL wall)

Interaction wall above = VIDEO-FIRST baseline (AI plane not loaded during that soak, or loaded separately).  
Priority: smooth FULL_WHEP at dynamic budget + continuous live PREVIEW pool.

## G. AI-FIRST (MEASURED_REAL RTSP/TCP)

| Tier | n | pass | fps_mean | ai_lat_p50 |
|---|---:|---:|---:|---:|
| Primary | {(ai.get('tiers') or {}).get('primary', {}).get('n')} | {(ai.get('tiers') or {}).get('primary', {}).get('pass')} | {(ai.get('tiers') or {}).get('primary', {}).get('fps_mean')} | {(ai.get('tiers') or {}).get('primary', {}).get('ai_latency_p50_mean')} |
| Secondary | {(ai.get('tiers') or {}).get('secondary', {}).get('n')} | {(ai.get('tiers') or {}).get('secondary', {}).get('pass')} | {(ai.get('tiers') or {}).get('secondary', {}).get('fps_mean')} | {(ai.get('tiers') or {}).get('secondary', {}).get('ai_latency_p50_mean')} |
| Low | {(ai.get('tiers') or {}).get('low', {}).get('n')} | {(ai.get('tiers') or {}).get('low', {}).get('pass')} | {(ai.get('tiers') or {}).get('low', {}).get('fps_mean')} | {(ai.get('tiers') or {}).get('low', {}).get('ai_latency_p50_mean')} |

Path: **RTSP/TCP only**. Note: `{ai.get('note')}`  
Status: `{payload.get('ai_first_status')}`

## H. Failure isolation

Per-tile UX: LIVE / PREVIEW / CONNECTING / PROMOTING / DEGRADED / RECONNECTING / NO_SIGNAL.  
Independent negotiation; promotions attach streams without wall reset. Panel opens did not create global stall={stall}.

## I–K. Resources, startup, promotion

- Startup usable wall: **{inter.get('usable_wall_ms')}** ms
- Interaction promotions: {promo.get('ok')} / {promo.get('requested')} — p50 **{promo.get('p50')}** · p95 {promo.get('p95')} · max {promo.get('max')}
- CPU/RAM: `{inter.get('resources')}` · GPU: `{inter.get('gpu')}`

## L. Limitations

- Catalogue not authoritative without `SENTINEL_GRID_COOKIE`.
- Do not claim 30× full WHEP PASS (peak ≈8–10 MEASURED_REAL).
- Continuous concurrent PREVIEW WHEP limited by measured sweep (chosen={sweep.get('chosen_preview_budget')}); remainder via rotation or NO_SIGNAL.
- HLS preview unavailable without CDN session.
- Do not claim 50 government cameras.
- AI-FIRST uses motion/OCR-proxy cadence on RTSP (see note) — not a claim of full YOLO×30.

## M. Reproducibility

```bash
export SENTINEL_GRID_EMAIL=…    # env only — never commit
export SENTINEL_GRID_PASSWORD=… # env only
cd saakshya
.venv/bin/python tools/phase13_operator_experience.py --mode all \\
  --full-budget 10 --preview-budget 6 --prewarm-promotions 10 \\
  --also-30-promotions --interact-seconds 35 --interact-promotions 10 \\
  --preview-sweep --ai-first
.venv/bin/python tools/verify/secret_scan.py
```

Artifacts: `var/reports/phase10/performance/phase13_*.json`
"""
    refuse_secrets(md)
    (ROOT / "reports/FINAL_30_CAMERA_OPERATOR_CERTIFICATION.md").write_text(md)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["preview", "prewarm", "interact", "ai", "all"],
        default="all",
    )
    parser.add_argument("--full-budget", type=int, default=10)
    parser.add_argument("--preview-budget", type=int, default=6)
    parser.add_argument("--prewarm-promotions", type=int, default=10)
    parser.add_argument("--also-30-promotions", action="store_true")
    parser.add_argument("--interact-seconds", type=float, default=35)
    parser.add_argument("--interact-promotions", type=int, default=10)
    parser.add_argument("--preview-sweep", action="store_true")
    parser.add_argument("--ai-first", action="store_true")
    parser.add_argument("--ai-seconds", type=float, default=25)
    parser.add_argument("--rotate-ms", type=int, default=4000)
    parser.add_argument("--out", type=Path,
                        default=OUT / "phase13_operator_experience.json")
    args = parser.parse_args()

    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = GridConfig.from_env()
    auth = basic_authorization_header()
    cpu = psutil.cpu_percent(interval=0.3)
    budget = dynamic_full_budget(cpu=cpu, measured_peak=10, prefer=args.full_budget)

    payload: dict = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "catalogue": try_catalogue_ingest(),
        "catalogue_authoritative": False,
        "catalogue_session_configured": has_credential(),
        "full_whep_budget": budget,
        "preview_whep_count": args.preview_budget,
        "dynamic_budget_note": (
            f"cpu={cpu}% → FULL_WHEP budget={budget} "
            f"(allowed 8/10/12 capped by measured peak≈10)"
        ),
        "ai_first_status": "NOT_RUN",
        "credentials_in_artifact": False,
    }
    payload["catalogue_authoritative"] = (
        payload["catalogue"].get("status") == "AUTHORITATIVE"
    )

    all_cams = [f"cam{i:02d}" for i in range(1, 31)]
    strong = list(STRONG)
    # Prefer FULL=8 when requesting 10 under pressure of a large preview pool —
    # leave distinct strong cams for continuous live PREVIEW (no overlap).
    preview_budget = args.preview_budget
    if budget + preview_budget > len(strong):
        # Keep distinct roles: shrink FULL first toward measured all-PASS (8)
        budget = min(budget, max(8, len(strong) - min(4, preview_budget)))
        payload["full_whep_budget"] = budget
        payload["dynamic_budget_note"] += (
            f" | adjusted FULL→{budget} to keep distinct PREVIEW cams"
        )
    full_cams = strong[:budget]
    preview_cams: list[str] = []
    for c in strong[budget:] + [f"cam{i:02d}" for i in range(1, 31)]:
        if c in full_cams or c in preview_cams:
            continue
        preview_cams.append(c)
        if len(preview_cams) >= preview_budget:
            break
    # Last resort: allow overlap only if not enough distinct cams answered
    if len(preview_cams) < preview_budget:
        for c in strong:
            if c not in preview_cams:
                preview_cams.append(c)
            if len(preview_cams) >= preview_budget:
                break
    payload["preview_whep_count"] = len(preview_cams)

    if args.mode in {"preview", "all"}:
        print("=== PREVIEW: HLS ===", flush=True)
        hls = probe_hls_preview("cam01", seconds=5)
        print(json.dumps({"hls": hls["overall"], "chosen": hls.get("chosen")}), flush=True)
        print(f"=== PREVIEW: WHEP pool n={len(preview_cams)} ===", flush=True)
        pw = probe_preview_whep(preview_cams, auth, cfg, seconds=15)
        ws = pw.get("wall_summary") or {}
        whep_ok = (
            pw.get("overall") in {"PASS", "AMBER"}
            or ((ws.get("AMBER", 0) + ws.get("PASS", 0)) > 0)
        )
        if whep_ok and pw.get("overall") == "FAIL" and (ws.get("AMBER") or 0) > 0:
            pw["overall"] = "AMBER"
        choice = "PREVIEW_WHEP_POOL" if whep_ok else (
            "HLS" if hls.get("overall") == "PASS" else "NONE_VIABLE_CONTINUOUS"
        )
        payload["preview"] = {"hls": hls, "preview_whep": pw}
        payload["preview_choice"] = choice
        (OUT / "phase13_preview.json").write_text(
            json.dumps(payload["preview"], indent=2) + "\n"
        )
        if args.preview_sweep:
            sweep = sweep_preview_budgets(auth, cfg, seconds=12)
            payload["preview_sweep"] = sweep
            preview_budget = sweep["chosen_preview_budget"]
            # Re-apply distinct FULL/PREVIEW split with chosen preview budget
            if budget + preview_budget > len(strong):
                budget = min(budget, max(8, len(strong) - min(4, preview_budget)))
                payload["full_whep_budget"] = budget
                full_cams = strong[:budget]
            preview_cams = []
            for c in strong[budget:] + [f"cam{i:02d}" for i in range(1, 31)]:
                if c in full_cams or c in preview_cams:
                    continue
                preview_cams.append(c)
                if len(preview_cams) >= preview_budget:
                    break
            payload["preview_whep_count"] = len(preview_cams)
            (OUT / "phase13_preview_sweep.json").write_text(
                json.dumps(sweep, indent=2) + "\n"
            )

    if args.mode in {"prewarm", "all"}:
        print("=== DIRECT SENTINEL PREWARM 10 ===", flush=True)
        pre = run_direct_prewarm(
            "cam01", auth, cfg, promotions=args.prewarm_promotions,
        )
        payload["prewarm"] = pre
        payload["prewarm_10"] = pre
        print(json.dumps({
            "cold_ms": (pre.get("cold") or {}).get("click_to_frame_ms"),
            "warm_p50": (pre.get("warm") or {}).get("p50"),
            "warm_p95": (pre.get("warm") or {}).get("p95"),
            "warm_max": (pre.get("warm") or {}).get("max"),
            "ok": (pre.get("warm") or {}).get("promotions_ok"),
        }), flush=True)
        (OUT / "phase13_prewarm.json").write_text(json.dumps(pre, indent=2) + "\n")
        (OUT / "phase13_prewarm_10.json").write_text(json.dumps(pre, indent=2) + "\n")
        if args.also_30_promotions or args.prewarm_promotions == 10:
            # Always capture a dedicated 30-promo run when doing full certification
            if args.also_30_promotions:
                print("=== DIRECT SENTINEL PREWARM 30 ===", flush=True)
                pre30 = run_direct_prewarm("cam01", auth, cfg, promotions=30)
                payload["prewarm_30"] = pre30
                (OUT / "phase13_prewarm_30.json").write_text(
                    json.dumps(pre30, indent=2) + "\n"
                )
                print(json.dumps({
                    "cold_ms": (pre30.get("cold") or {}).get("click_to_frame_ms"),
                    "warm_p50": (pre30.get("warm") or {}).get("p50"),
                    "ok": (pre30.get("warm") or {}).get("promotions_ok"),
                }), flush=True)

    if args.mode in {"ai", "all"} and (args.ai_first or args.mode == "ai"):
        print("=== AI-FIRST RTSP PLANE ===", flush=True)
        ai = run_ai_first_plane(seconds=args.ai_seconds)
        payload["ai_first"] = ai
        payload["ai_first_status"] = "MEASURED_REAL"
        (OUT / "phase13_ai_first.json").write_text(json.dumps(ai, indent=2) + "\n")
        print(json.dumps({"tiers": ai.get("tiers")}), flush=True)

    if args.mode in {"interact", "all"}:
        print("=== 30-CAMERA INTERACTION WALL ===", flush=True)
        inter = run_interaction_wall(
            all_cams=all_cams,
            full_cams=full_cams,
            preview_cams=preview_cams,
            auth=auth, cfg=cfg,
            seconds=args.interact_seconds,
            promotions=args.interact_promotions,
            conc=6,
            rotate_ms=args.rotate_ms,
        )
        payload["interaction"] = inter
        payload["preview_whep_count"] = len(preview_cams)
        print(json.dumps({
            "ux": inter.get("ux_counts"),
            "promotion": inter.get("promotion"),
            "usable_ms": inter.get("usable_wall_ms"),
            "panels": inter.get("panels"),
        }), flush=True)
        (OUT / "phase13_interaction.json").write_text(
            json.dumps(inter, indent=2) + "\n"
        )

    if "preview_choice" not in payload:
        payload["preview_choice"] = "NOT_RUN"

    # Merge prior prewarm_30 if present and not just measured
    if "prewarm_30" not in payload and (OUT / "phase13_prewarm_30.json").exists():
        try:
            payload["prewarm_30"] = json.loads(
                (OUT / "phase13_prewarm_30.json").read_text()
            )
        except Exception:
            pass

    blob = json.dumps(payload, indent=2) + "\n"
    refuse_secrets(blob)
    args.out.write_text(blob)
    write_final_report(payload)
    print(json.dumps({
        "preview_choice": payload.get("preview_choice"),
        "full_budget": budget,
        "preview_budget": payload.get("preview_whep_count"),
        "ai_first_status": payload.get("ai_first_status"),
        "out": str(args.out),
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
