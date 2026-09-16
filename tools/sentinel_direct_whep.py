#!/usr/bin/env python3
"""Phase 11 — Direct Sentinel WHEP browser path (official browser plane).

Architecture preference (when MEASURED better/equal to local relay):

  Sentinel WHEP + Authorization: Basic  →  Chromium Metal  →  <video>
  Sentinel RTSP/TCP                     →  AI plane (unchanged)

Security:
  - Credentials from SENTINEL_GRID_EMAIL/PASSWORD env only
  - Authorization header only — NEVER in WHEP URL
  - Never print/write credentials to stdout/JSON/logs/argv
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured, redact  # noqa: E402
from saakshya.live.grid import GridConfig  # noqa: E402

OUT = ROOT / "var/reports/phase10/performance"
_AUTH = re.compile(r"(?<=//)[^/@\s'\"]*:[^/@\s'\"]*@")


def safe(text: object) -> str:
    s = redact(str(text or ""))
    s = _AUTH.sub("<redacted>@", s)
    email = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    if password:
        s = s.replace(password, "<redacted>")
    if email:
        s = s.replace(email, "<redacted>").replace(email.replace("@", "%40"), "<redacted>")
    return s[:300]


def refuse_secrets(blob: str) -> None:
    if _AUTH.search(blob):
        raise SystemExit("refusing credential-like authority in artifact")
    email = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    if (password and password in blob) or (email and email in blob):
        raise SystemExit("refusing credential plaintext in artifact")


def basic_authorization_header() -> str:
    """Build Authorization: Basic … in memory. Never log the value."""
    email = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    if not (email and password):
        raise SystemExit("SENTINEL_GRID_EMAIL/PASSWORD not configured")
    token = base64.b64encode(f"{email}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def whep_url(camera_id: str, cfg: GridConfig | None = None) -> str:
    cfg = cfg or GridConfig.from_env()
    return cfg.whep(camera_id)  # clean URL — no credentials


# Independent tiles + Basic Authorization on WHEP POST (never in URL).
DIRECT_WALL_JS = r"""
async ({endpoints, authHeader, seconds, telemetryHz, healthHz,
        negotiateConcurrency, setupTimeoutMs, retries}) => {
  const withTimeout = (p, ms, label) => Promise.race([
    p,
    new Promise((_, rej) => setTimeout(() => rej(new Error('timeout:' + label)), ms)),
  ]);

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
      id: i, cameraHint: endpoints[i], started: performance.now(),
      first: null, negotiation: null, httpStatus: null,
      iceConnectedAt: null, ice: 'new', freezes: 0, reconnects: 0,
      currentTime: 0, framesDecoded: 0, framesDropped: 0,
      packetsLost: 0, packetsReceived: 0, width: 0, height: 0,
      error: null, attempts: 0, readyAt: null,
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
          let iceConnectedAt = null;
          pc.addEventListener('iceconnectionstatechange', () => {
            if ((pc.iceConnectionState === 'connected' ||
                 pc.iceConnectionState === 'completed') && iceConnectedAt == null) {
              iceConnectedAt = performance.now() - state.started;
              state.iceConnectedAt = iceConnectedAt;
            }
            state.ice = pc.iceConnectionState;
          });
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
          const headers = {
            'Content-Type': 'application/sdp',
            'Accept': 'application/sdp',
          };
          if (authHeader) headers['Authorization'] = authHeader;
          const resp = await fetch(endpoint, {
            method: 'POST',
            headers,
            body: pc.localDescription.sdp,
            signal: AbortSignal.timeout(Math.min(15000, setupTimeoutMs)),
          });
          state.httpStatus = resp.status;
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
        state.error = String(e && e.message || e);
        try { if (pc) pc.close(); } catch (_) {}
        pcs[i] = null;
        release();
        if (attempt < retries) {
          await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
          continue;
        }
      }
    }
  };

  const wallStart = performance.now();
  const setups = [];
  for (let i = 0; i < n; i++) setups.push(setupOne(i));
  // Do not await all — soak starts immediately; late join OK
  const deadline = wallStart + seconds * 1000;
  let lastHealth = 0, lastTelemetry = 0;
  const healthInterval = 1000 / Math.max(0.5, healthHz);
  const telemetryInterval = 1000 / Math.max(0.5, telemetryHz);
  const lastTime = new Array(n).fill(0);
  const stallMs = new Array(n).fill(0);
  const inStall = new Array(n).fill(false);
  const lastIce = new Array(n).fill('new');

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
    gpu = gl ? {
      renderer: gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER),
    } : null;
  } catch (_) {}

  return {
    tiles: states,
    gpu,
    negotiateConcurrency,
    wallElapsedMs: performance.now() - wallStart,
    authMode: authHeader ? 'Authorization_Basic_header' : 'none',
  };
}
"""


def measure_direct_wall(
    endpoints: list[str],
    *,
    auth_header: str | None,
    seconds: float,
    negotiate_concurrency: int = 4,
    setup_timeout_ms: int = 20000,
    retries: int = 1,
) -> dict:
    from playwright.sync_api import sync_playwright

    n = len(endpoints)
    page_html = (
        "<!doctype html><html><body style='margin:0;background:#111;display:flex;"
        "flex-wrap:wrap;gap:2px'>"
        + "".join(
            f"<video id='v{i}' autoplay muted playsinline "
            f"style='width:320px;height:180px;background:#000;object-fit:cover'></video>"
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
            page.set_default_timeout(int((seconds + 90 + 5 * n) * 1000))
            result = page.evaluate(
                DIRECT_WALL_JS,
                {
                    "endpoints": endpoints,
                    "authHeader": auth_header,
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
                "error": safe(f"{type(exc).__name__}: {exc}"),
                "tiles": [],
                "elapsed_s": round(time.monotonic() - started, 3),
            }
        browser.close()
    return {
        "status": "MEASURED",
        "tiles": result.get("tiles") or [],
        "gpu": result.get("gpu"),
        "negotiate_concurrency": result.get("negotiateConcurrency"),
        "auth_mode": result.get("authMode"),
        "wall_elapsed_ms": result.get("wallElapsedMs"),
        "elapsed_s": round(time.monotonic() - started, 3),
        "browser": "headed-metal",
        "resources": {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
        },
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
    if ct < target_s * 0.45:
        return "AMBER"
    if freezes > 3 or lost > 10:
        return "AMBER"
    if ice not in {"connected", "completed"}:
        return "AMBER"
    return "PASS"


def summarize(camera_ids: list[str], wall: dict, *, seconds: float,
              path_label: str) -> dict:
    tiles_out = []
    raw = wall.get("tiles") or []
    for i, cam in enumerate(camera_ids):
        tile = raw[i] if i < len(raw) else {}
        verdict = classify(tile, target_s=seconds)
        ct = float(tile.get("currentTime") or 0)
        fd = int(tile.get("framesDecoded") or 0)
        tiles_out.append({
            "camera_id": cam,
            "verdict": verdict,
            "whep_http_status": tile.get("httpStatus"),
            "first_frame_ms": tile.get("first"),
            "negotiation_ms": tile.get("negotiation"),
            "ice_connected_ms": tile.get("iceConnectedAt"),
            "currentTime": ct,
            "framesDecoded": fd,
            "framesDropped": tile.get("framesDropped"),
            "packetsLost": tile.get("packetsLost"),
            "freezes": tile.get("freezes"),
            "ice": tile.get("ice"),
            "width": tile.get("width"),
            "height": tile.get("height"),
            "effective_fps": round(fd / ct, 2) if ct > 0.5 else None,
            "error": safe(tile.get("error")),
            "endpoint_safe": (tile.get("cameraHint") or "")[:120],
        })
    passes = sum(1 for t in tiles_out if t["verdict"] == "PASS")
    ambers = sum(1 for t in tiles_out if t["verdict"] == "AMBER")
    fails = sum(1 for t in tiles_out if t["verdict"] in {"FAIL", "NO_FRAME"})
    firsts = [t["first_frame_ms"] for t in tiles_out if t.get("first_frame_ms") is not None]
    negs = [t["negotiation_ms"] for t in tiles_out if t.get("negotiation_ms") is not None]

    def pct(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        k = (len(s) - 1) * (p / 100.0)
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return float(s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f))

    if fails == 0 and ambers == 0 and passes == len(camera_ids):
        overall = "PASS"
    elif passes > 0:
        overall = "AMBER"
    else:
        overall = "FAIL"
    return {
        "path": path_label,
        "n_cameras": len(camera_ids),
        "seconds": seconds,
        "overall": overall,
        "label": "MEASURED",
        "wall_summary": {
            "PASS": passes, "AMBER": ambers, "FAIL": fails,
            "first_frame_ms_p50": pct(firsts, 50),
            "first_frame_ms_p95": pct(firsts, 95),
            "negotiation_ms_p50": pct(negs, 50),
            "negotiation_ms_p95": pct(negs, 95),
        },
        "tiles": tiles_out,
        "browser_wall": {
            "status": wall.get("status"),
            "gpu": wall.get("gpu"),
            "auth_mode": wall.get("auth_mode"),
            "elapsed_s": wall.get("elapsed_s"),
            "resources": wall.get("resources"),
            "error": wall.get("error"),
        },
    }


def run_local_relay_compare(camera_ids: list[str], seconds: float) -> dict:
    """Existing local relay WHEP for comparison (fallback path)."""
    from tools.perf_whep_session_scheduler import (
        start_publishers, stop_all, measure_wall, camera_pool,
    )
    # Only use requested cams that are in known pools
    cams = list(camera_ids)
    transcode = set()
    # HEVC cams need transcode on relay path
    for c in ("cam06", "cam12", "cam17"):
        if c in cams:
            transcode.add(c)
    mtx, pubs = start_publishers(cams, seconds=seconds + 90, transcode=transcode)
    try:
        endpoints = [f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in cams]
        wall = measure_wall(
            endpoints, seconds=seconds, negotiate_concurrency=4, retries=1,
        )
        # strip any accidental secrets from tile errors
        for t in wall.get("tiles") or []:
            if t.get("error"):
                t["error"] = safe(t["error"])
        return summarize(cams, wall, seconds=seconds, path_label="LOCAL_RELAY_WHEP")
    finally:
        stop_all(mtx, pubs)


def write_report(payload: dict, md_path: Path) -> None:
    lines = [
        "# Phase 11 — Direct Sentinel WHEP",
        "",
        f"Timestamp UTC: `{payload.get('timestamp_utc')}`",
        "",
        "## Decision",
        "",
        f"**Primary browser path recommendation:** `{payload.get('recommendation')}`",
        "",
        payload.get("decision_note", ""),
        "",
    ]
    for key in ("cam01_30s", "cam01_60s", "compare", "wall_n4", "wall_n8"):
        row = payload.get(key)
        if not row:
            continue
        ws = row.get("wall_summary") or {}
        lines += [
            f"## {key}",
            "",
            f"Path: `{row.get('path')}`  Overall: **{row.get('overall')}**",
            "",
            f"- PASS/AMBER/FAIL: {ws.get('PASS')}/{ws.get('AMBER')}/{ws.get('FAIL')}",
            f"- first-frame p50/p95: {ws.get('first_frame_ms_p50')} / {ws.get('first_frame_ms_p95')} ms",
            f"- negotiation p50: {ws.get('negotiation_ms_p50')} ms",
            "",
        ]
    lines += [
        "## Security",
        "",
        "Credentials: Authorization Basic header only. Never in URL/stdout/JSON.",
        "",
        "Catalogue: `/api/ingest` still EXTERNAL session dependency "
        "(see SENTINEL_CONTRACT_PROBE).",
        "",
    ]
    md = "\n".join(lines) + "\n"
    refuse_secrets(md)
    md_path.write_text(md)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["soak", "wall", "compare", "all"],
                        default="all")
    parser.add_argument("--cameras", nargs="+", default=["cam01"])
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--also-60", action="store_true",
                        help="If 30s PASS, also run 60s on cam01")
    parser.add_argument("--n", type=int, default=4, help="wall camera count")
    parser.add_argument("--negotiate-concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path,
                        default=OUT / "phase11_direct_whep.json")
    args = parser.parse_args()

    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = GridConfig.from_env()
    auth = basic_authorization_header()
    payload: dict = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED",
        "auth_transport": "Authorization_Basic_header",
        "credentials_in_artifact": False,
        "catalogue_authoritative": False,
        "catalogue_note": (
            "GET /api/ingest not JSON-reachable without CDN session cookie; "
            "camera URLs from configured templates."
        ),
    }

    def soak(cams: list[str], seconds: float, key: str) -> dict:
        endpoints = [whep_url(c, cfg) for c in cams]
        print(f"=== DIRECT WHEP soak {cams} {seconds}s ===", flush=True)
        wall = measure_direct_wall(
            endpoints, auth_header=auth, seconds=seconds,
            negotiate_concurrency=min(args.negotiate_concurrency, len(cams)),
            retries=1,
        )
        row = summarize(cams, wall, seconds=seconds, path_label="DIRECT_SENTINEL_WHEP")
        payload[key] = row
        print(json.dumps({
            "key": key, "overall": row["overall"],
            "summary": row["wall_summary"],
            "gpu": (row.get("browser_wall") or {}).get("gpu"),
        }), flush=True)
        return row

    if args.mode in {"soak", "all"}:
        r30 = soak(["cam01"], args.seconds, "cam01_30s")
        if args.also_60 or (args.mode == "all" and r30.get("overall") == "PASS"):
            soak(["cam01"], 60.0, "cam01_60s")

    if args.mode in {"compare", "all"}:
        print("=== COMPARE direct vs local relay (cam01) ===", flush=True)
        direct = soak(["cam01"], min(args.seconds, 30.0), "compare_direct")
        try:
            local = run_local_relay_compare(["cam01"], min(args.seconds, 30.0))
            payload["compare_local_relay"] = local
            print(json.dumps({
                "local_overall": local["overall"],
                "local_summary": local["wall_summary"],
            }), flush=True)
        except Exception as exc:
            payload["compare_local_relay"] = {
                "overall": "FAIL", "error": safe(exc), "path": "LOCAL_RELAY_WHEP",
            }
        d_ff = (direct.get("wall_summary") or {}).get("first_frame_ms_p50")
        l_ff = ((payload.get("compare_local_relay") or {}).get("wall_summary") or {}).get(
            "first_frame_ms_p50")
        payload["compare"] = {
            "direct_overall": direct.get("overall"),
            "local_overall": (payload.get("compare_local_relay") or {}).get("overall"),
            "direct_first_frame_p50_ms": d_ff,
            "local_first_frame_p50_ms": l_ff,
        }

    if args.mode in {"wall", "all"}:
        # Strong H.264 first; skip known-flaky until proven
        pool = ["cam01", "cam02", "cam05", "cam04", "cam13", "cam14", "cam19", "cam15"]
        cams = []
        for c in pool:
            if c not in cams:
                cams.append(c)
            if len(cams) >= args.n:
                break
        print(f"=== DIRECT WHEP wall n={len(cams)} ===", flush=True)
        endpoints = [whep_url(c, cfg) for c in cams]
        wall = measure_direct_wall(
            endpoints, auth_header=auth, seconds=args.seconds,
            negotiate_concurrency=args.negotiate_concurrency, retries=1,
        )
        row = summarize(cams, wall, seconds=args.seconds,
                        path_label="DIRECT_SENTINEL_WHEP")
        payload[f"wall_n{len(cams)}"] = row
        print(json.dumps({
            "wall_n": len(cams), "overall": row["overall"],
            "summary": row["wall_summary"],
        }), flush=True)

    # Recommendation
    d30 = payload.get("cam01_30s") or payload.get("compare_direct")
    local = payload.get("compare_local_relay")
    wall4 = payload.get("wall_n4") or payload.get(f"wall_n{args.n}")
    if d30 and d30.get("overall") == "PASS":
        if wall4 and (wall4.get("wall_summary") or {}).get("PASS", 0) >= max(1, args.n // 2):
            rec = "DIRECT_SENTINEL_WHEP_PRIMARY"
            note = (
                "Direct Sentinel WHEP with Authorization Basic works for browser "
                "plane. Prefer direct WHEP for PRIMARY/SECONDARY; keep local relay "
                "as fallback. AI remains on RTSP/TCP."
            )
        else:
            rec = "DIRECT_SENTINEL_WHEP_PRIMARY_LIMITED_CONCURRENCY"
            note = (
                "cam01 direct WHEP PASS; multi-cam still limited — use direct for "
                "focus tiles; measure further before 16."
            )
    elif d30 and d30.get("overall") in {"PASS", "AMBER"} and local and local.get("overall") == "PASS":
        rec = "KEEP_LOCAL_RELAY_FALLBACK"
        note = "Direct partial; local relay still viable fallback."
    else:
        rec = "DIAGNOSE"
        note = "Direct WHEP did not clear cam01 soak — inspect HTTP/ICE layer."

    # Prefer direct if first-frame comparable or better
    cmp = payload.get("compare") or {}
    if (
        rec.startswith("DIRECT")
        and cmp.get("direct_first_frame_p50_ms")
        and cmp.get("local_first_frame_p50_ms")
        and cmp["direct_first_frame_p50_ms"] > cmp["local_first_frame_p50_ms"] * 2
        and (local or {}).get("overall") == "PASS"
    ):
        note += (
            " Direct first-frame slower than local relay — keep relay as "
            "optional low-latency fallback for demos."
        )

    payload["recommendation"] = rec
    payload["decision_note"] = note

    blob = json.dumps(payload, indent=2) + "\n"
    refuse_secrets(blob)
    args.out.write_text(blob)
    write_report(payload, ROOT / "reports/PHASE11_DIRECT_WHEP.md")
    print(json.dumps({
        "recommendation": rec,
        "out": str(args.out),
    }), flush=True)
    return 0 if (d30 or {}).get("overall") != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
