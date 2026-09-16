#!/usr/bin/env python3
"""Phase 14 — Real 30-camera source census + hybrid wall from AVAILABLE_CAMERAS.

Does NOT redesign media architecture.
Does NOT fabricate missing cameras.
Does NOT bypass Sentinel authentication.
Credentials: SENTINEL_GRID_* env only — never URL/stdout/JSON/git.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured, credentialed  # noqa: E402
from saakshya.live.grid import GridConfig, has_credential  # noqa: E402
from tools.sentinel_direct_whep import (  # noqa: E402
    basic_authorization_header, measure_direct_wall, refuse_secrets, safe, whep_url,
)

OUT = ROOT / "var/reports/phase10/performance"
REPORTS = ROOT / "reports"
HOST = "103.250.160.189"
RTSP_PORT = 8554
WHEP_PORT = 8889

SOURCE_HEALTH = (
    "LIVE",
    "AUTH_REJECTED",
    "CONNECTION_REFUSED",
    "NO_FRAME",
    "WHEP_UNAVAILABLE",
    "HEVC_UNSUPPORTED",
    "CLIENT_ERROR",
    "UNKNOWN",
)

CAMERAS = [f"cam{i:02d}" for i in range(1, 31)]


def _basic_header() -> str:
    user = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Authorization: Basic {token}"


def tcp_probe(host: str, port: int, *, timeout: float = 3.0) -> dict:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "ok": True,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": None,
            }
    except ConnectionRefusedError as exc:
        return {"ok": False, "ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": "CONNECTION_REFUSED", "detail": safe(str(exc))}
    except Exception as exc:
        return {"ok": False, "ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": safe(f"{type(exc).__name__}: {exc}")}


def rtsp_exchange(path: str, *, method: str, cseq: int,
                  auth_header: str | None = None, session: str | None = None,
                  transport: str | None = None, timeout: float = 8.0) -> dict:
    uri = f"rtsp://{HOST}:{RTSP_PORT}{path}"
    lines = [
        f"{method} {uri} RTSP/1.0",
        f"CSeq: {cseq}",
        "User-Agent: SaakshyaPhase14Census/1.0",
    ]
    if auth_header:
        lines.append(auth_header)
    if session:
        lines.append(f"Session: {session}")
    if transport:
        lines.append(f"Transport: {transport}")
    if method == "DESCRIBE":
        lines.append("Accept: application/sdp")
    body = "\r\n".join(lines) + "\r\n\r\n"
    raw = b""
    status = None
    headers: dict[str, str] = {}
    sdp = ""
    err = None
    try:
        with socket.create_connection((HOST, RTSP_PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(body.encode("utf-8"))
            while len(raw) < 262144:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                raw += chunk
                if b"\r\n\r\n" in raw:
                    head, _, rest = raw.partition(b"\r\n\r\n")
                    # If Content-Length, try to read body
                    text_head = head.decode("utf-8", "replace")
                    cl = None
                    for ln in text_head.split("\r\n")[1:]:
                        if ln.lower().startswith("content-length:"):
                            try:
                                cl = int(ln.split(":", 1)[1].strip())
                            except ValueError:
                                cl = None
                    if cl is None or len(rest) >= cl:
                        break
        text = raw.decode("utf-8", "replace")
        head, _, rest = text.partition("\r\n\r\n")
        first = head.split("\r\n", 1)[0] if head else ""
        m = re.match(r"RTSP/1\.\d\s+(\d+)", first)
        status = int(m.group(1)) if m else None
        for ln in head.split("\r\n")[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        if method == "DESCRIBE" and rest:
            sdp = rest[:4000]
    except ConnectionRefusedError:
        err = "CONNECTION_REFUSED"
    except Exception as exc:
        err = safe(f"{type(exc).__name__}: {exc}")
    codec = None
    if sdp:
        for ln in sdp.splitlines():
            if ln.startswith("a=rtpmap:") and "H264" in ln.upper():
                codec = "h264"
                break
            if ln.startswith("a=rtpmap:") and ("H265" in ln.upper() or "HEVC" in ln.upper()):
                codec = "hevc"
                break
    return {
        "method": method,
        "status": status,
        "error": err,
        "session": (headers.get("session") or "").split(";")[0].strip() or None,
        "codec_hint": codec,
        "www_authenticate": "www-authenticate" in headers,
    }


def probe_rtsp_layers(camera_id: str, *, attempts: int = 3) -> dict:
    """A–E: TCP8554, DESCRIBE, SETUP, PLAY, first decoded frame. Bounded retries."""
    path = f"/stream/{camera_id}"
    auth = _basic_header()
    last: dict = {}
    for attempt in range(1, attempts + 1):
        row: dict = {
            "camera_id": camera_id,
            "attempt": attempt,
            "tcp_8554": None,
            "describe_unauth": None,
            "describe_auth": None,
            "setup": None,
            "play": None,
            "pyav": None,
            "codec": None,
            "first_fail": None,
            "rtsp_live": False,
        }
        tcp = tcp_probe(HOST, RTSP_PORT)
        row["tcp_8554"] = tcp
        if not tcp["ok"]:
            row["first_fail"] = "TCP_8554"
            last = row
            time.sleep(0.4 * attempt)
            continue

        unauth = rtsp_exchange(path, method="DESCRIBE", cseq=1)
        row["describe_unauth"] = {
            "status": unauth["status"], "error": unauth["error"],
            "www_authenticate": unauth["www_authenticate"],
        }
        desc = rtsp_exchange(path, method="DESCRIBE", cseq=2, auth_header=auth)
        row["describe_auth"] = {
            "status": desc["status"], "error": desc["error"],
            "codec_hint": desc["codec_hint"],
        }
        row["codec"] = desc.get("codec_hint")
        if desc["status"] in {401, 403}:
            row["first_fail"] = "DESCRIBE_AUTH"
            last = row
            time.sleep(0.4 * attempt)
            continue
        if desc["status"] != 200:
            row["first_fail"] = "DESCRIBE_AUTH" if desc["error"] else "DESCRIBE"
            last = row
            time.sleep(0.4 * attempt)
            continue

        transport = "RTP/AVP/TCP;unicast;interleaved=0-1"
        setup = rtsp_exchange(
            path, method="SETUP", cseq=3, auth_header=auth, transport=transport,
        )
        # Some servers want /trackID=0
        if setup["status"] not in {200, 201}:
            setup = rtsp_exchange(
                f"{path}/trackID=0", method="SETUP", cseq=4,
                auth_header=auth, transport=transport,
            )
        row["setup"] = {"status": setup["status"], "error": setup["error"],
                        "session": setup["session"]}
        session = setup["session"]
        play_status = None
        if setup["status"] in {200, 201} and session:
            play = rtsp_exchange(
                path, method="PLAY", cseq=5, auth_header=auth, session=session,
            )
            row["play"] = {"status": play["status"], "error": play["error"]}
            play_status = play["status"]
        else:
            row["play"] = {
                "status": None,
                "error": "skipped_incomplete_setup",
                "setup_status": setup["status"],
            }
            # Raw SETUP/PLAY often needs exact track URI on MediaMTX.
            # PyAV DESCRIBE+demux is the authoritative frame probe — continue.

        # PyAV first frames (authoritative) even if raw SETUP/PLAY handshake failed
        pyav = {"frames": 0, "ms": None, "codec": None, "error": None, "wh": None}
        t0 = time.perf_counter()
        try:
            import av
            url = credentialed(
                f"rtsp://{HOST}:{RTSP_PORT}/stream/{camera_id}", required=True,
            )
            container = av.open(
                url,
                options={"rtsp_transport": "tcp", "stimeout": "8000000"},
                timeout=15,
            )
            stream = next(s for s in container.streams if s.type == "video")
            pyav["codec"] = stream.codec_context.name
            row["codec"] = row["codec"] or pyav["codec"]
            n = 0
            for frame in container.decode(stream):
                n += 1
                if n == 1:
                    pyav["wh"] = f"{frame.width}x{frame.height}"
                if n >= 3:
                    break
            container.close()
            pyav["frames"] = n
            pyav["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception as exc:
            pyav["error"] = safe(f"{type(exc).__name__}: {exc}")
            pyav["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        row["pyav"] = pyav
        if pyav["frames"] < 1:
            if setup["status"] not in {200, 201}:
                row["first_fail"] = "SETUP"
            elif play_status not in {200, 201, None}:
                row["first_fail"] = "PLAY"
            else:
                row["first_fail"] = "PYAV_NO_FRAME"
            last = row
            time.sleep(0.5 * attempt)
            continue

        row["rtsp_live"] = True
        if play_status not in {200, 201, None}:
            row["handshake_note"] = "raw_PLAY_failed_but_pyav_frames_ok"
        row["first_fail"] = None
        return row
    return last


SINGLE_WHEP_JS = r"""
async ({endpoint, authHeader, budgetMs, retries}) => {
  const waitFirst = async (video, ms) => {
    const t0 = performance.now();
    await video.play().catch(() => {});
    while (performance.now() - t0 < ms) {
      if (video.videoWidth > 0 && video.currentTime > 0)
        return performance.now() - t0;
      await new Promise(r => setTimeout(r, 40));
    }
    return null;
  };
  const video = document.querySelector('#v0');
  const attempts = [];
  for (let a = 0; a < retries; a++) {
    const t0 = performance.now();
    let pc = null;
    try {
      pc = new RTCPeerConnection();
      const stream = new MediaStream();
      video.srcObject = stream;
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
      // Real browser SDP offer — never a fake minimal SDP
      const sdp = pc.localDescription && pc.localDescription.sdp;
      if (!sdp || sdp.length < 80 || !sdp.includes('m=video'))
        throw new Error('invalid_browser_sdp');
      const headers = {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'};
      if (authHeader) headers['Authorization'] = authHeader;
      const resp = await fetch(endpoint, {
        method: 'POST', headers, body: sdp,
        signal: AbortSignal.timeout(15000),
      });
      const http = resp.status;
      if (!resp.ok) throw new Error('WHEP ' + http);
      await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
      const ff = await waitFirst(video, budgetMs);
      let codec = null, frames = 0, ice = pc.iceConnectionState;
      try {
        for (const r of (await pc.getStats()).values()) {
          if (r.type === 'inbound-rtp' && r.kind === 'video') {
            frames = r.framesDecoded || 0;
            codec = r.mimeType || codec;
          }
        }
      } catch (_) {}
      pc.close();
      video.srcObject = null;
      attempts.push({
        attempt: a + 1, ok: ff != null, http, first_frame_ms: ff,
        negotiation_ms: performance.now() - t0, framesDecoded: frames,
        ice, codec, sdp_bytes: sdp.length, error: null,
      });
      if (ff != null) break;
    } catch (e) {
      try { if (pc) pc.close(); } catch (_) {}
      attempts.push({
        attempt: a + 1, ok: false, http: null, first_frame_ms: null,
        negotiation_ms: performance.now() - t0, framesDecoded: 0,
        ice: null, codec: null, error: String(e && e.message || e),
      });
      await new Promise(r => setTimeout(r, 400 * (a + 1)));
    }
  }
  let gpu = null;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl');
    const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
    gpu = gl ? gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : null;
  } catch (_) {}
  const best = attempts.find(x => x.ok) || attempts[attempts.length - 1] || null;
  return {attempts, best, gpu};
}
"""


def probe_whep_browser_all(camera_ids: list[str], auth: str, cfg: GridConfig,
                           *, budget_ms: int = 10000, retries: int = 2) -> dict:
    """Real-browser WHEP POST with real Chromium SDP offers (not fake/minimal SDP).

    Strategy: batch soak (independent tiles + real createOffer SDP), then
    individual retry for failures. Avoids single-camera Playwright hangs.
    """
    results: dict = {}
    endpoints = [whep_url(c, cfg) for c in camera_ids]
    print(f"  WHEP batch n={len(camera_ids)} (real browser SDP) …", flush=True)
    wall = measure_direct_wall(
        endpoints, auth_header=auth, seconds=max(12.0, budget_ms / 1000.0),
        negotiate_concurrency=3, retries=retries, setup_timeout_ms=18000,
    )
    tiles = wall.get("tiles") or []
    for i, cam in enumerate(camera_ids):
        t = tiles[i] if i < len(tiles) else {}
        tcp = tcp_probe(HOST, WHEP_PORT)
        ff = t.get("first")
        http = t.get("httpStatus")
        ok = ff is not None and (t.get("framesDecoded") or 0) > 0 or (
            ff is not None and (t.get("currentTime") or 0) > 0
        )
        # Also accept first-frame marker alone
        if ff is not None and http in {200, 201}:
            ok = True
        best = {
            "ok": ok,
            "http": http,
            "first_frame_ms": ff,
            "negotiation_ms": t.get("negotiation"),
            "framesDecoded": t.get("framesDecoded"),
            "ice": t.get("ice"),
            "error": safe(t.get("error")),
            "attempt": t.get("attempts") or 1,
        }
        results[cam] = {
            "camera_id": cam,
            "endpoint_safe": endpoints[i],
            "tcp_8889": tcp,
            "attempts": [best],
            "best": best,
            "whep_live": ok,
            "gpu": wall.get("gpu"),
            "mode": "batch_real_sdp",
        }
        print(json.dumps({
            "cam": cam, "whep_live": ok, "http": http, "ff_ms": ff,
            "err": best.get("error"),
        }), flush=True)

    # Individual retry for failures (fresh browser each, hard wall seconds)
    failed = [c for c in camera_ids if not results[c]["whep_live"]]
    for cam in failed:
        print(f"  WHEP retry solo {cam} …", flush=True)
        ep = whep_url(cam, cfg)
        t0 = time.perf_counter()
        try:
            solo = measure_direct_wall(
                [ep], auth_header=auth, seconds=10.0,
                negotiate_concurrency=1, retries=2, setup_timeout_ms=15000,
            )
            t = (solo.get("tiles") or [{}])[0]
            ff = t.get("first")
            http = t.get("httpStatus")
            ok = ff is not None and http in {200, 201}
            best = {
                "ok": ok, "http": http, "first_frame_ms": ff,
                "negotiation_ms": t.get("negotiation"),
                "framesDecoded": t.get("framesDecoded"),
                "ice": t.get("ice"), "error": safe(t.get("error")),
                "attempt": "solo_retry",
            }
        except Exception as exc:
            ok = False
            best = {"ok": False, "http": None, "first_frame_ms": None,
                    "error": safe(f"{type(exc).__name__}: {exc}")}
            solo = {}
        results[cam] = {
            "camera_id": cam,
            "endpoint_safe": ep,
            "tcp_8889": tcp_probe(HOST, WHEP_PORT),
            "attempts": (results[cam].get("attempts") or []) + [best],
            "best": best,
            "whep_live": ok,
            "gpu": solo.get("gpu"),
            "mode": "solo_retry_real_sdp",
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
        print(json.dumps({
            "cam": cam, "whep_live": ok, "http": best.get("http"),
            "ff_ms": best.get("first_frame_ms"), "err": best.get("error"),
        }), flush=True)
        time.sleep(0.3)
    return results


def classify_source(rtsp: dict, whep: dict) -> dict:
    """Produce SOURCE_HEALTH + evidence for scheduler."""
    cam = rtsp.get("camera_id")
    tcp_rtsp = (rtsp.get("tcp_8554") or {}).get("ok")
    desc = (rtsp.get("describe_auth") or {}).get("status")
    pyav_frames = (rtsp.get("pyav") or {}).get("frames") or 0
    codec = rtsp.get("codec") or (rtsp.get("pyav") or {}).get("codec")
    whep_live = bool((whep or {}).get("whep_live"))
    whep_best = (whep or {}).get("best") or {}
    tcp_whep = ((whep or {}).get("tcp_8889") or {}).get("ok")

    first_fail = rtsp.get("first_fail")
    health = "UNKNOWN"
    q = {
        "A_rtsp_frames": pyav_frames >= 1,
        "B_whep_frames": whep_live,
        "C_preview_capable": whep_live,  # same endpoint; refined in pool test
        "D_concurrency_pressure": None,  # filled later
        "E_catalogue_unavailable": not has_credential() and not (
            os.environ.get("SENTINEL_GRID_COOKIE") or os.environ.get("SENTINEL_GRID_TOKEN")
        ),
    }

    if not tcp_rtsp and not tcp_whep:
        health = "CONNECTION_REFUSED"
        first_fail = first_fail or "TCP"
    elif desc in {401, 403}:
        health = "AUTH_REJECTED"
        first_fail = first_fail or "DESCRIBE_AUTH"
    elif pyav_frames < 1 and not whep_live:
        if first_fail in {"PYAV_NO_FRAME", "PLAY", "SETUP", "DESCRIBE"}:
            health = "NO_FRAME"
        elif not tcp_whep or (whep_best.get("http") in {404, 405, 501}):
            health = "WHEP_UNAVAILABLE"
            first_fail = first_fail or "WHEP"
        else:
            health = "NO_FRAME"
            first_fail = first_fail or "NO_FRAME"
    elif whep_live or pyav_frames >= 1:
        # HEVC browser decode issues
        err = (whep_best.get("error") or "")
        if codec in {"hevc", "h265"} and not whep_live and pyav_frames >= 1:
            health = "HEVC_UNSUPPORTED"
            first_fail = "WHEP_HEVC_BROWSER"
        elif whep_live and pyav_frames >= 1:
            health = "LIVE"
            first_fail = None
        elif whep_live and pyav_frames < 1:
            health = "LIVE"  # browser plane works; RTSP flake
            first_fail = rtsp.get("first_fail") or "RTSP_FLAKE_WHEP_OK"
        elif pyav_frames >= 1 and not whep_live:
            health = "WHEP_UNAVAILABLE"
            first_fail = first_fail or "WHEP_NO_FRAME"
        else:
            health = "UNKNOWN"
    else:
        if "timeout" in str(whep_best.get("error") or "").lower():
            health = "CLIENT_ERROR"
            first_fail = "WHEP_TIMEOUT"
        else:
            health = "UNKNOWN"

    available = health == "LIVE" or (
        health in {"LIVE"} or (pyav_frames >= 1 and whep_live)
    )
    # Available for wall if either plane works with frames
    available = (pyav_frames >= 1) or whep_live
    if health == "AUTH_REJECTED":
        available = False

    return {
        "camera_id": cam,
        "source_health": health if health in SOURCE_HEALTH else "UNKNOWN",
        "available": available,
        "codec": codec,
        "rtsp_frames": pyav_frames,
        "whep_frames": whep_live,
        "whep_first_frame_ms": whep_best.get("first_frame_ms"),
        "whep_http": whep_best.get("http"),
        "first_fail": first_fail,
        "questions": q,
        "label": "NOT_AUTHORITATIVE",
    }


def write_census_report(payload: dict) -> Path:
    rows = payload.get("cameras") or []
    avail = [r for r in rows if r.get("available")]
    unavail = [r for r in rows if not r.get("available")]
    lines = [
        "# Phase 14 — Real camera source census",
        "",
        f"Timestamp UTC: `{payload['timestamp_utc']}`",
        "",
        "Label: **NOT_AUTHORITATIVE** (catalogue `/api/ingest` unavailable without session cookie).",
        "No authentication bypass. Credentials env-only.",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---:|",
        f"| Documented IDs probed | {len(rows)} |",
        f"| AVAILABLE_CAMERAS | **{len(avail)}** |",
        f"| UNAVAILABLE_CAMERAS | **{len(unavail)}** |",
        f"| RTSP frame OK | {sum(1 for r in rows if r.get('rtsp_frames'))} |",
        f"| WHEP browser decode OK | {sum(1 for r in rows if r.get('whep_frames'))} |",
        f"| Both RTSP+WHEP | {sum(1 for r in rows if r.get('rtsp_frames') and r.get('whep_frames'))} |",
        "",
        "## Camera matrix (source of truth for scheduler)",
        "",
        "| Camera | RTSP | WHEP | Preview | Codec | Frames | First fail | Classification |",
        "|--------|------|------|---------|-------|--------|------------|----------------|",
    ]
    for r in rows:
        rtsp = "OK" if r.get("rtsp_frames") else "FAIL"
        whep = "OK" if r.get("whep_frames") else "FAIL"
        prev = "OK" if r.get("whep_frames") else "FAIL"
        frames = []
        if r.get("rtsp_frames"):
            frames.append(f"rtsp={r.get('rtsp_frame_count', 'y')}")
        if r.get("whep_frames"):
            frames.append(f"whep={r.get('whep_first_frame_ms')}")
        lines.append(
            f"| {r['camera_id']} | {rtsp} | {whep} | {prev} | {r.get('codec') or '—'} | "
            f"{';'.join(frames) or '—'} | {r.get('first_fail') or '—'} | "
            f"**{r.get('source_health')}** |"
        )
    lines += [
        "",
        "## AVAILABLE_CAMERAS",
        "",
        ", ".join(r["camera_id"] for r in avail) or "_(none)_",
        "",
        "## UNAVAILABLE_CAMERAS",
        "",
        ", ".join(r["camera_id"] for r in unavail) or "_(none)_",
        "",
        "## Classification counts",
        "",
    ]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("source_health") or "UNKNOWN"] = counts.get(
            r.get("source_health") or "UNKNOWN", 0) + 1
    for k, v in sorted(counts.items()):
        lines.append(f"- `{k}`: {v}")
    lines += [
        "",
        "## Notes",
        "",
        "- NO_SIGNAL on the operator wall is only valid when source_health is not LIVE",
        "  after bounded retries (3 attempts with backoff) — not a short single timeout.",
        "- Preview uses the same official WHEP endpoint (PREVIEW_WHEP_POOL); capability",
        "  equals WHEP browser decode for that camera.",
        "- Concurrent session pressure is measured separately from this per-camera census.",
        "",
        f"Machine-readable: `{payload.get('artifact')}`",
        "",
    ]
    md = "\n".join(lines)
    refuse_secrets(md)
    path = REPORTS / "PHASE14_REAL_CAMERA_SOURCE_CENSUS.md"
    path.write_text(md)
    return path


def write_escalation(payload: dict) -> Path | None:
    rows = payload.get("cameras") or []
    avail = [r for r in rows if r.get("available")]
    if len(avail) >= 30:
        return None
    unavail = [r for r in rows if not r.get("available")]
    lines = [
        "# Sentinel 30-camera source availability escalation",
        "",
        f"Timestamp UTC: `{payload['timestamp_utc']}`",
        "",
        "## Statement",
        "",
        f"**{len(avail)}** of the documented camera IDs (`cam01`…`cam30`) were reachable "
        f"with usable live media during the measured window; **{len(unavail)}** were "
        "unavailable or did not produce frames after bounded retries.",
        "",
        "This is a measured sandbox/source availability report. It does not assert that "
        "the government system is broken.",
        "",
        "## Context",
        "",
        "- Client: Saakshya Phase 14 census (Chromium headed ANGLE Metal, PyAV RTSP/TCP)",
        "- Auth: `Authorization: Basic` from `SENTINEL_GRID_EMAIL` / `PASSWORD` (env only)",
        "- Catalogue `/api/ingest`: **NOT_AUTHORITATIVE** (no `SENTINEL_GRID_COOKIE`/`TOKEN`)",
        "- Endpoints: "
        f"`rtsp://{HOST}:{RTSP_PORT}/stream/{{id}}` · "
        f"`http://{HOST}:{WHEP_PORT}/stream/{{id}}/whep`",
        "",
        "## Available (evidence of working path)",
        "",
        "| Camera | RTSP frames | WHEP decode | Codec |",
        "|---|---:|---|---|",
    ]
    for r in avail:
        lines.append(
            f"| {r['camera_id']} | {r.get('rtsp_frame_count') or (1 if r.get('rtsp_frames') else 0)} | "
            f"{'OK' if r.get('whep_frames') else 'FAIL'} | {r.get('codec') or '—'} |"
        )
    lines += [
        "",
        "## Unavailable (first failure)",
        "",
        "| Camera | Classification | First fail | RTSP | WHEP HTTP | Error |",
        "|---|---|---|---|---|---|",
    ]
    detail = {c["camera_id"]: c for c in (payload.get("detail") or [])}
    for r in unavail:
        d = detail.get(r["camera_id"]) or {}
        whep = (d.get("whep") or {}).get("best") or {}
        rtsp = d.get("rtsp") or {}
        err = safe(
            ((rtsp.get("pyav") or {}).get("error"))
            or whep.get("error")
            or r.get("first_fail")
        )
        lines.append(
            f"| {r['camera_id']} | {r.get('source_health')} | {r.get('first_fail') or '—'} | "
            f"{'OK' if r.get('rtsp_frames') else 'FAIL'} | {whep.get('http') or '—'} | {err or '—'} |"
        )
    lines += [
        "",
        "## Request",
        "",
        "Please confirm which of `cam01`…`cam30` are expected to be live in the current "
        "sandbox window, and whether catalogue session access (`/api/ingest`) can be "
        "provided so camera metadata is authoritative rather than probe-derived.",
        "",
        f"Census artifact: `{payload.get('artifact')}`",
        "",
    ]
    md = "\n".join(lines)
    refuse_secrets(md)
    path = REPORTS / "SENTINEL_30_CAMERA_SOURCE_AVAILABILITY_ESCALATION.md"
    path.write_text(md)
    return path


def run_preview_push(available: list[str], auth: str, cfg: GridConfig,
                     *, sizes: list[int] | None = None) -> dict:
    sizes = sizes or [8, 10, 12, 16]
    rows = []
    for n in sizes:
        cams = available[:n]
        if len(cams) < n:
            rows.append({"n": n, "overall": "SKIP", "reason": f"only {len(cams)} available"})
            print(json.dumps(rows[-1]), flush=True)
            continue
        print(f"=== PREVIEW PUSH n={n} ===", flush=True)
        endpoints = [whep_url(c, cfg) for c in cams]
        wall = measure_direct_wall(
            endpoints, auth_header=auth, seconds=15,
            negotiate_concurrency=min(4, n), retries=2, setup_timeout_ms=20000,
        )
        tiles = wall.get("tiles") or []
        live = 0
        for t in tiles:
            ct = t.get("currentTime") or 0
            fd = t.get("framesDecoded") or 0
            if ct > 1 or fd > 5:
                live += 1
        # Use summarize-like counts
        from tools.sentinel_direct_whep import summarize
        summary = summarize(cams, wall, seconds=15, path_label="PREVIEW_PUSH")
        ws = summary.get("wall_summary") or {}
        live2 = (ws.get("PASS") or 0) + (ws.get("AMBER") or 0)
        rows.append({
            "n": n,
            "overall": summary.get("overall"),
            "live_tiles": max(live, live2),
            "PASS": ws.get("PASS"),
            "AMBER": ws.get("AMBER"),
            "FAIL": ws.get("FAIL"),
            "first_frame_ms_p50": ws.get("first_frame_ms_p50"),
            "resources": wall.get("resources"),
            "gpu": wall.get("gpu"),
        })
        print(json.dumps(rows[-1]), flush=True)
        time.sleep(1.5)
    # Choose largest with live >= 0.75n and first_frame p50 < 5000
    chosen = 0
    for r in rows:
        if r.get("overall") == "SKIP":
            continue
        ff = r.get("first_frame_ms_p50") or 9e9
        if (r.get("live_tiles") or 0) >= int(r["n"] * 0.75) and ff < 5000:
            chosen = r["n"]
    return {
        "label": "MEASURED_REAL",
        "rows": rows,
        "chosen_preview_budget": chosen,
        "available_n": len(available),
    }


def run_hybrid_wall(available: list[str], auth: str, cfg: GridConfig,
                    *, full_budget: int, preview_budget: int,
                    seconds: float) -> dict:
    full_cams = available[:full_budget]
    preview_cams = available[full_budget:full_budget + preview_budget]
    # Remaining available beyond budgets still registered — must not be false NO_SIGNAL
    remainder = available[full_budget + preview_budget:]
    unavailable_registered = [c for c in CAMERAS if c not in available]

    endpoints_full = [whep_url(c, cfg) for c in full_cams]
    endpoints_prev = [whep_url(c, cfg) for c in preview_cams]
    # Measure FULL+PREVIEW concurrent
    all_eps = endpoints_full + endpoints_prev
    all_ids = full_cams + preview_cams
    print(
        f"=== HYBRID WALL full={len(full_cams)} preview={len(preview_cams)} "
        f"avail={len(available)} unavail={len(unavailable_registered)} "
        f"seconds={seconds} ===",
        flush=True,
    )
    wall = measure_direct_wall(
        all_eps, auth_header=auth, seconds=seconds,
        negotiate_concurrency=4, retries=2, setup_timeout_ms=22000,
    )
    from tools.sentinel_direct_whep import classify, summarize
    summary = summarize(all_ids, wall, seconds=seconds, path_label="HYBRID_30")
    tiles_out = []
    live = preview = degraded = nosignal_false = 0
    for i, t in enumerate(wall.get("tiles") or []):
        cid = all_ids[i] if i < len(all_ids) else f"idx{i}"
        role = "FULL" if i < len(full_cams) else "PREVIEW"
        verdict = classify(t, target_s=seconds)
        ux = "LIVE" if role == "FULL" and verdict in {"PASS", "AMBER"} else (
            "PREVIEW" if role == "PREVIEW" and verdict in {"PASS", "AMBER"} else (
                "DEGRADED" if verdict == "AMBER" else "RECONNECTING"
            )
        )
        if verdict == "FAIL":
            # Available camera that failed this soak → not source NO_SIGNAL
            ux = "DEGRADED"
            nosignal_false += 0
        if ux == "LIVE":
            live += 1
        elif ux == "PREVIEW":
            preview += 1
        elif ux == "DEGRADED":
            degraded += 1
        tiles_out.append({
            "camera_id": cid, "role": role, "verdict": verdict, "ux": ux,
            "first_frame_ms": t.get("first"),
            "currentTime": t.get("currentTime"),
            "framesDecoded": t.get("framesDecoded"),
            "framesDropped": t.get("framesDropped"),
            "packetsLost": t.get("packetsLost"),
            "freezes": t.get("freezes"),
            "ice": t.get("ice"),
            "http": t.get("httpStatus"),
            "error": safe(t.get("error")),
        })

    # True NO_SIGNAL only for census-unavailable cameras
    true_nosignal = [
        {"camera_id": c, "ux": "NO_SIGNAL", "reason": "census_unavailable"}
        for c in unavailable_registered
    ]
    # Remainder available but over budget: mark AWAITING_SLOT (not NO_SIGNAL)
    awaiting = [
        {"camera_id": c, "ux": "AWAITING_SLOT",
         "reason": "healthy_but_over_whep_budget"}
        for c in remainder
    ]

    return {
        "label": "MEASURED_REAL",
        "seconds": seconds,
        "full_cams": full_cams,
        "preview_cams": preview_cams,
        "available_n": len(available),
        "unavailable_n": len(unavailable_registered),
        "ux_counts": {
            "LIVE": live,
            "PREVIEW": preview,
            "DEGRADED": degraded,
            "AWAITING_SLOT": len(awaiting),
            "NO_SIGNAL": len(true_nosignal),
        },
        "tiles": tiles_out,
        "awaiting_slot": awaiting,
        "true_no_signal": true_nosignal,
        "wall_summary": summary.get("wall_summary"),
        "overall": summary.get("overall"),
        "gpu": wall.get("gpu"),
        "resources": wall.get("resources"),
        "note": (
            "NO_SIGNAL reserved for census-unavailable sources only. "
            "Healthy cameras beyond FULL+PREVIEW budget are AWAITING_SLOT."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["census", "preview", "wall", "all"],
        default="all",
    )
    parser.add_argument("--rtsp-workers", type=int, default=4)
    parser.add_argument("--full-budget", type=int, default=8)
    parser.add_argument("--preview-budget", type=int, default=0,
                        help="0 = auto from preview push chosen")
    parser.add_argument("--wall-seconds", type=str, default="30,60",
                        help="comma list of soak durations")
    parser.add_argument("--skip-whep", action="store_true")
    args = parser.parse_args()

    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    cfg = GridConfig.from_env()
    auth = basic_authorization_header()
    ts = datetime.now(UTC).isoformat()

    census_path = OUT / "phase14_source_census.json"
    cameras_cls: list[dict] = []
    detail: list[dict] = []

    if args.mode in {"census", "all"}:
        print("=== PHASE 14 RTSP CENSUS cam01–cam30 ===", flush=True)
        rtsp_map: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=args.rtsp_workers) as ex:
            futs = {ex.submit(probe_rtsp_layers, c): c for c in CAMERAS}
            for fut in as_completed(futs):
                cam = futs[fut]
                try:
                    row = fut.result()
                except Exception as exc:
                    row = {
                        "camera_id": cam, "rtsp_live": False,
                        "first_fail": "CLIENT_ERROR",
                        "pyav": {"frames": 0, "error": safe(str(exc))},
                        "tcp_8554": {"ok": False},
                    }
                rtsp_map[cam] = row
                print(json.dumps({
                    "cam": cam,
                    "rtsp_live": row.get("rtsp_live"),
                    "codec": row.get("codec"),
                    "frames": (row.get("pyav") or {}).get("frames"),
                    "fail": row.get("first_fail"),
                }), flush=True)

        whep_map: dict[str, dict] = {}
        if not args.skip_whep:
            print("=== PHASE 14 WHEP BROWSER CENSUS (real SDP) ===", flush=True)
            whep_map = probe_whep_browser_all(
                CAMERAS, auth, cfg, budget_ms=9000, retries=2,
            )

        for cam in CAMERAS:
            rtsp = rtsp_map.get(cam) or {"camera_id": cam}
            whep = whep_map.get(cam) or {}
            cls = classify_source(rtsp, whep)
            cls["rtsp_frame_count"] = (rtsp.get("pyav") or {}).get("frames") or 0
            cameras_cls.append(cls)
            detail.append({"camera_id": cam, "rtsp": rtsp, "whep": whep, "class": cls})

        payload = {
            "timestamp_utc": ts,
            "label": "MEASURED_REAL",
            "catalogue_authoritative": False,
            "cameras": cameras_cls,
            "detail": detail,
            "available": [c["camera_id"] for c in cameras_cls if c["available"]],
            "unavailable": [c["camera_id"] for c in cameras_cls if not c["available"]],
            "artifact": str(census_path.relative_to(ROOT)),
        }
        blob = json.dumps(payload, indent=2) + "\n"
        refuse_secrets(blob)
        census_path.write_text(blob)
        write_census_report(payload)
        esc = write_escalation(payload)
        print(json.dumps({
            "available": len(payload["available"]),
            "unavailable": len(payload["unavailable"]),
            "escalation": str(esc) if esc else None,
        }), flush=True)
    else:
        if not census_path.exists():
            print("run census first", file=sys.stderr)
            return 2
        payload = json.loads(census_path.read_text())
        cameras_cls = payload["cameras"]

    available = [c["camera_id"] for c in cameras_cls if c.get("available")]
    # Prefer cams with both RTSP+WHEP, then WHEP-only, then RTSP-only
    def rank(cid: str) -> tuple:
        row = next(c for c in cameras_cls if c["camera_id"] == cid)
        return (
            0 if row.get("whep_frames") and row.get("rtsp_frames") else 1,
            0 if row.get("whep_frames") else 1,
            0 if row.get("rtsp_frames") else 1,
            cid,
        )
    available = sorted(available, key=rank)

    preview_result = None
    if args.mode in {"preview", "all"}:
        print("=== PREVIEW POOL PUSH on AVAILABLE ===", flush=True)
        preview_result = run_preview_push(available, auth, cfg)
        (OUT / "phase14_preview_push.json").write_text(
            json.dumps(preview_result, indent=2) + "\n"
        )

    if args.mode in {"wall", "all"}:
        chosen_prev = args.preview_budget
        if chosen_prev <= 0:
            chosen_prev = (preview_result or {}).get("chosen_preview_budget") or 0
            if chosen_prev <= 0 and available:
                # leave room for FULL
                chosen_prev = max(0, min(8, len(available) - args.full_budget))
        full_budget = min(args.full_budget, len(available))
        # Do not let preview starve FULL
        preview_budget = min(chosen_prev, max(0, len(available) - full_budget))
        wall_results = []
        for sec in [float(x) for x in args.wall_seconds.split(",") if x.strip()]:
            wall_results.append(
                run_hybrid_wall(
                    available, auth, cfg,
                    full_budget=full_budget,
                    preview_budget=preview_budget,
                    seconds=sec,
                )
            )
            (OUT / f"phase14_hybrid_wall_{int(sec)}s.json").write_text(
                json.dumps(wall_results[-1], indent=2) + "\n"
            )
            print(json.dumps({
                "seconds": sec,
                "ux": wall_results[-1]["ux_counts"],
                "overall": wall_results[-1].get("overall"),
            }), flush=True)
        (OUT / "phase14_hybrid_wall.json").write_text(
            json.dumps({"runs": wall_results, "available": available}, indent=2) + "\n"
        )

    print(json.dumps({
        "available_n": len(available),
        "available": available,
        "out": str(census_path),
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
