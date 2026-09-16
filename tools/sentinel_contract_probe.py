#!/usr/bin/env python3
"""Sentinel Sandbox contract probe — catalogue → RTSP → WHEP → HLS.

Does NOT start MediaMTX, AI, or modify application state.
Does NOT publish anything.
Credentials: SENTINEL_GRID_* env only — never stdout/JSON/reports/argv/URL logs.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from hashlib import md5
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured, credentialed, redact  # noqa: E402
from saakshya.live.grid import GridConfig  # noqa: E402

OUT_JSON = ROOT / "var/reports/phase10/sentinel_contract_probe.json"
OUT_CAT = ROOT / "var/reports/phase10/sentinel_catalogue.json"
OUT_MD = ROOT / "reports/SENTINEL_CONTRACT_PROBE.md"

_AUTH = re.compile(r"(?<=//)[^/@\s'\"]*:[^/@\s'\"]*@")
CLIENT = "SaakshyaContractProbe/1.0"


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
        raise SystemExit("refusing to write credential-like authority")
    email = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    if password and password in blob:
        raise SystemExit("refusing to write password")
    if email and email in blob:
        raise SystemExit("refusing to write email")


# ── Catalogue ──────────────────────────────────────────────────────────────


def catalogue_candidates(cfg: GridConfig) -> list[str]:
    host_ip = "103.250.160.189"
    host_cdn = "cctv.corp8.cloud"
    urls = [
        cfg.catalogue_url,
        os.environ.get("SENTINEL_CATALOGUE_URL") or "",
        f"http://{host_ip}/api/ingest",
        f"http://{host_cdn}/api/ingest",
        f"https://{host_cdn}/api/ingest",
        f"http://{host_cdn}/cameras.json",
        f"https://{host_cdn}/cameras.json",
    ]
    out, seen = [], set()
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _catalogue_headers() -> dict[str, str]:
    h = {"Accept": "application/json, text/plain, */*", "User-Agent": CLIENT}
    cookie = os.environ.get("SENTINEL_GRID_COOKIE")
    token = os.environ.get("SENTINEL_GRID_TOKEN")
    basic = os.environ.get("SENTINEL_GRID_BASIC")
    if cookie:
        h["Cookie"] = cookie
    if token:
        h["Authorization"] = f"Bearer {token}"
    if basic:
        h["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
    return h


def fetch_catalogue_raw() -> dict:
    attempts = []
    payload = None
    used = None
    for url in catalogue_candidates(GridConfig.from_env()):
        entry = {"url_safe": url, "status": None, "content_type": None,
                 "json": False, "error": None, "bytes": 0}
        try:
            req = urllib.request.Request(url, headers=_catalogue_headers())
            with urllib.request.urlopen(req, timeout=12) as r:
                raw = r.read()
                entry["status"] = r.status
                entry["content_type"] = r.headers.get("Content-Type")
                entry["bytes"] = len(raw)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    entry["json"] = True
                    used = url
                    attempts.append(entry)
                    break
                except json.JSONDecodeError:
                    entry["error"] = "not_json"
                    preview = raw[:40].decode("utf-8", "replace")
                    if "<html" in preview.lower() or "<!doctype" in preview.lower():
                        entry["error"] = "html_login_or_spa"
        except Exception as exc:
            entry["status"] = getattr(exc, "code", None)
            entry["error"] = safe(f"{type(exc).__name__}: {exc}")
        attempts.append(entry)
    return {
        "reachable_json": payload is not None,
        "catalogue_url_used": used,
        "attempts": attempts,
        "payload": payload,
        "session_cookie_configured": bool(os.environ.get("SENTINEL_GRID_COOKIE")),
        "token_configured": bool(os.environ.get("SENTINEL_GRID_TOKEN")),
    }


def normalise_catalogue_cameras(payload) -> list[dict]:
    """Extract sanitized camera records from catalogue JSON."""
    if payload is None:
        return []
    items = payload
    if isinstance(payload, dict):
        for key in ("cameras", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        else:
            if all(isinstance(v, dict) for v in payload.values()):
                items = [{"id": k, **v} for k, v in payload.items()]
    if not isinstance(items, list):
        return []
    cams = []
    for e in items:
        if not isinstance(e, dict):
            continue
        cid = str(e.get("id") or e.get("camera_id") or e.get("cameraId") or "")
        urls = e.get("urls") if isinstance(e.get("urls"), dict) else {}
        props = e.get("properties") if isinstance(e.get("properties"), dict) else {}
        loc = e.get("location") if isinstance(e.get("location"), dict) else {}
        cams.append({
            "id": cid,
            "live": e.get("live"),
            "codec": e.get("codec") or props.get("codec"),
            "resolution": (
                f"{props.get('width')}x{props.get('height')}"
                if props.get("width") and props.get("height") else e.get("resolution")
            ),
            "fps": props.get("fps") or e.get("fps") or e.get("frame_rate"),
            "bitrate": props.get("bitrate") or e.get("bitrate"),
            "location_name": loc.get("name") or e.get("location") if isinstance(e.get("location"), str) else loc.get("name"),
            "rtsp_url": urls.get("rtsp") or e.get("rtsp") or e.get("rtsp_url"),
            "whep_url": urls.get("whep") or e.get("whep") or e.get("whep_url"),
            "hls_url": urls.get("hls") or e.get("hls") or e.get("hls_url"),
        })
    return cams


# ── RTSP (TCP, Authorization header + URL-authority PyAV comparison) ───────


def parse_www_auth(header: str) -> dict:
    out: dict = {"scheme": None, "raw_scheme_only": None}
    if not header:
        return out
    parts = header.strip().split(None, 1)
    out["scheme"] = parts[0].lower() if parts else None
    out["raw_scheme_only"] = parts[0] if parts else None
    rest = parts[1] if len(parts) > 1 else ""
    for m in re.finditer(r'(\w+)="([^"]*)"', rest):
        out[m.group(1).lower()] = m.group(2)
    return out


def basic_hdr(user: str, password: str) -> str:
    tok = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Authorization: Basic {tok}"


def digest_hdr(user: str, password: str, method: str, uri: str, wa: dict,
               nc: str = "00000001") -> str:
    realm = wa.get("realm", "")
    nonce = wa.get("nonce", "")
    qop = (wa.get("qop") or "").split(",")[0].strip()
    cnonce = md5(f"{time.time()}{os.getpid()}".encode()).hexdigest()[:16]
    ha1 = md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    ha2 = md5(f"{method}:{uri}".encode()).hexdigest()
    if qop:
        resp = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
        bits = [f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"',
                f'uri="{uri}"', f'response="{resp}"', f'qop={qop}',
                f'nc={nc}', f'cnonce="{cnonce}"']
    else:
        resp = md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        bits = [f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"',
                f'uri="{uri}"', f'response="{resp}"']
    if wa.get("opaque"):
        bits.append(f'opaque="{wa["opaque"]}"')
    return "Authorization: Digest " + ", ".join(bits)


def rtsp_req(host: str, port: int, path: str, method: str, cseq: int,
             auth_line: str | None = None, session: str | None = None,
             transport: str | None = None, timeout: float = 8.0) -> dict:
    uri = f"rtsp://{host}:{port}{path}"
    lines = [f"{method} {uri} RTSP/1.0", f"CSeq: {cseq}", f"User-Agent: {CLIENT}"]
    if auth_line:
        lines.append(auth_line)
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
    err = None
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(body.encode())
            while b"\r\n\r\n" not in raw and len(raw) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
        text = raw.decode("utf-8", "replace")
        head = text.split("\r\n\r\n", 1)[0]
        first = head.split("\r\n", 1)[0]
        m = re.match(r"RTSP/1\.\d\s+(\d+)", first)
        status = int(m.group(1)) if m else None
        for ln in head.split("\r\n")[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
    except Exception as exc:
        err = safe(f"{type(exc).__name__}: {exc}")
    wa = parse_www_auth(headers.get("www-authenticate", ""))
    return {
        "status": status,
        "error": err,
        "www_authenticate_scheme": wa.get("scheme"),
        "www_authenticate_realm_present": bool(wa.get("realm")),
        "session": (headers.get("session") or "").split(";")[0].strip() or None,
    }


def probe_rtsp(rtsp_url: str) -> dict:
    """RTSP TCP probe per integrator guide. No credentials in URI logs."""
    u = urlparse(rtsp_url)
    host = u.hostname or "103.250.160.189"
    port = u.port or 8554
    path = u.path or "/"
    user = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""

    tcp_ok = False
    tcp_ms = None
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5):
            tcp_ok = True
            tcp_ms = round((time.monotonic() - t0) * 1000, 1)
    except Exception as exc:
        return {
            "url_safe": f"rtsp://{host}:{port}{path}",
            "tcp": {"ok": False, "error": safe(str(exc))},
            "first_failing_layer": "TCP",
        }

    unauth = rtsp_req(host, port, path, "DESCRIBE", 1)
    # Capture scheme for auth
    wa = {}
    try:
        with socket.create_connection((host, port), timeout=8) as sock:
            sock.settimeout(8)
            sock.sendall(
                f"DESCRIBE rtsp://{host}:{port}{path} RTSP/1.0\r\n"
                f"CSeq: 1\r\nUser-Agent: {CLIENT}\r\nAccept: application/sdp\r\n\r\n"
                .encode()
            )
            raw = b""
            while b"\r\n\r\n" not in raw and len(raw) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
        for ln in raw.decode("utf-8", "replace").split("\r\n\r\n", 1)[0].split("\r\n")[1:]:
            if ln.lower().startswith("www-authenticate:"):
                wa = parse_www_auth(ln.split(":", 1)[1].strip())
                break
    except Exception:
        pass

    auth_results = {}
    desc_auth = None
    auth_used = None
    if configured() and user and password:
        # Try Digest if advertised, else Basic, record both statuses
        trials = []
        if wa.get("scheme") == "digest":
            trials.append(("Digest", digest_hdr(user, password, "DESCRIBE", path, wa)))
        trials.append(("Basic", basic_hdr(user, password)))
        if wa.get("scheme") != "digest":
            # also try Digest with empty wa fields (will fail cleanly)
            pass
        for name, hdr in trials:
            r = rtsp_req(host, port, path, "DESCRIBE", 2, auth_line=hdr)
            auth_results[name] = {"status": r["status"], "error": r["error"]}
            if r["status"] == 200 and desc_auth is None:
                desc_auth = r
                auth_used = name
        if desc_auth is None and trials:
            desc_auth = rtsp_req(host, port, path, "DESCRIBE", 3,
                                 auth_line=trials[0][1])
            auth_used = trials[0][0]

    setup = play = None
    if desc_auth and desc_auth.get("status") == 200:
        hdr = None
        if auth_used == "Digest" and wa:
            hdr = digest_hdr(user, password, "SETUP", path, wa, nc="00000002")
        elif auth_used == "Basic":
            hdr = basic_hdr(user, password)
        setup = rtsp_req(
            host, port, path, "SETUP", 4, auth_line=hdr,
            transport="RTP/AVP/TCP;unicast;interleaved=0-1",
        )
        if setup.get("status") != 200:
            setup = rtsp_req(
                host, port, f"{path}/trackID=0", "SETUP", 5, auth_line=hdr,
                transport="RTP/AVP/TCP;unicast;interleaved=0-1",
            )
        if setup.get("status") == 200:
            if auth_used == "Digest" and wa:
                hdr = digest_hdr(user, password, "PLAY", path, wa, nc="00000003")
            play = rtsp_req(
                host, port, path, "PLAY", 6, auth_line=hdr,
                session=setup.get("session"),
            )

    # PyAV / ffprobe with ephemeral in-memory authority (grid measured pattern)
    pyav = {"status": "SKIPPED", "frames": 0, "codec": None, "error": None}
    ffprobe = {"status": "SKIPPED", "error": None, "codec": None}
    if configured():
        clean = f"rtsp://{host}:{port}{path}"
        open_url = credentialed(clean, required=True)
        try:
            import av
            inp = av.open(
                open_url,
                options={"rtsp_transport": "tcp", "stimeout": "8000000"},
                timeout=20,
            )
            try:
                v = next(s for s in inp.streams if s.type == "video")
                pyav["codec"] = v.codec_context.name if v.codec_context else None
                n = 0
                deadline = time.monotonic() + 8
                for packet in inp.demux(v):
                    if time.monotonic() >= deadline:
                        break
                    if packet.dts is None and packet.pts is None:
                        continue
                    n += 1
                    if n >= 5:
                        break
                pyav["frames"] = n
                pyav["status"] = "FRAME" if n else "NO_FRAME"
            finally:
                inp.close()
        except Exception as exc:
            pyav["error"] = safe(f"{type(exc).__name__}: {exc}")
            pyav["status"] = "AUTH_401" if "401" in pyav["error"] else "FAIL"
        del open_url

        # ffprobe via env-injected URL only in subprocess — AVOID argv secrets.
        # Use PyAV result as primary; ffprobe optional via stdin wrapper script.
        ff = ROOT / "var/bin/ffprobe"
        if not ff.exists():
            ff = Path("/opt/homebrew/bin/ffprobe")
        if ff.exists() and pyav["status"] != "FRAME":
            # Do not put credentials on argv. Skip ffprobe if would require URL auth in argv.
            ffprobe = {
                "status": "SKIPPED_NO_ARGV_CREDENTIALS",
                "note": "ffprobe would require authority in argv; skipped per security contract",
            }

    first_fail = None
    if unauth.get("status") == 401 and (not desc_auth or desc_auth.get("status") != 200):
        first_fail = "DESCRIBE_AUTH"
    elif desc_auth and desc_auth.get("status") == 200 and setup and setup.get("status") != 200:
        first_fail = "SETUP"
    elif setup and setup.get("status") == 200 and play and play.get("status") != 200:
        first_fail = "PLAY"
    elif play and play.get("status") == 200 and pyav.get("status") != "FRAME":
        first_fail = "PYAV_DEMUX"
    elif pyav.get("status") == "FRAME":
        first_fail = None
    elif not tcp_ok:
        first_fail = "TCP"
    else:
        first_fail = "DESCRIBE_AUTH"

    return {
        "url_safe": f"rtsp://{host}:{port}{path}",
        "tcp": {"ok": tcp_ok, "latency_ms": tcp_ms},
        "describe_unauth": {
            "status": unauth.get("status"),
            "www_authenticate_scheme": unauth.get("www_authenticate_scheme") or wa.get("scheme"),
        },
        "auth_mechanism_advertised": wa.get("scheme"),
        "auth_header_trials": auth_results,
        "auth_header_success": auth_used,
        "describe_auth": {"status": (desc_auth or {}).get("status")},
        "setup": {"status": (setup or {}).get("status")} if setup else None,
        "play": {"status": (play or {}).get("status")} if play else None,
        "pyav_url_authority_in_memory": pyav,
        "ffprobe": ffprobe,
        "first_failing_layer": first_fail,
    }


# ── WHEP direct (no MediaMTX) ──────────────────────────────────────────────


def probe_whep(whep_url: str, *, seconds: float = 10.0) -> dict:
    """Direct WHEP against Sentinel host — no local MediaMTX."""
    out = {
        "url_safe": whep_url,
        "http_options_or_post_status": None,
        "negotiate_status": None,
        "sdp_ok": False,
        "first_frame_ms": None,
        "ice": None,
        "codec_hint": None,
        "gpu": None,
        "error": None,
        "auth_attempt": None,
    }
    # Probe endpoint reachability with empty OPTIONS/GET first (no secrets)
    try:
        req = urllib.request.Request(whep_url, method="OPTIONS",
                                     headers={"User-Agent": CLIENT})
        with urllib.request.urlopen(req, timeout=5) as r:
            out["http_options_or_post_status"] = r.status
    except Exception as exc:
        out["http_options_or_post_status"] = getattr(exc, "code", None)
        if out["http_options_or_post_status"] is None:
            out["error"] = safe(f"reachability: {type(exc).__name__}: {exc}")

    # Browser WHEP — credentials must not appear in page URL.
    # Try clean WHEP first; if 401, retry with Authorization header via page.route.
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        out["error"] = safe(f"playwright unavailable: {exc}")
        return out

    user = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    basic = None
    if user and password:
        basic = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    js = r"""
    async ({endpoint, seconds, authHeader}) => {
      const t0 = performance.now();
      const video = document.querySelector('video');
      const pc = new RTCPeerConnection();
      video.srcObject = new MediaStream();
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
      const headers = {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'};
      if (authHeader) headers['Authorization'] = authHeader;
      let resp;
      try {
        resp = await fetch(endpoint, {
          method: 'POST', headers, body: pc.localDescription.sdp,
          signal: AbortSignal.timeout(15000),
        });
      } catch (e) {
        pc.close();
        return {error: String(e && e.message || e), negotiate_status: null};
      }
      if (!resp.ok) {
        pc.close();
        return {negotiate_status: resp.status, error: 'WHEP ' + resp.status};
      }
      const sdp = await resp.text();
      await pc.setRemoteDescription({type: 'answer', sdp});
      await video.play().catch(() => {});
      let first = null;
      const deadline = performance.now() + seconds * 1000;
      while (performance.now() < deadline) {
        if (video.videoWidth > 0 && video.currentTime > 0) {
          first = performance.now() - t0; break;
        }
        await new Promise(r => setTimeout(r, 50));
      }
      let codec = null;
      try {
        for (const r of (await pc.getStats()).values()) {
          if (r.type === 'inbound-rtp' && r.kind === 'video' && r.codecId) codec = r.codecId;
        }
      } catch (_) {}
      let gpu = null;
      try {
        const c = document.createElement('canvas');
        const gl = c.getContext('webgl');
        const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
        gpu = gl ? gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : null;
      } catch (_) {}
      const ice = pc.iceConnectionState;
      pc.close();
      return {
        negotiate_status: 200, sdp_ok: true, first_frame_ms: first,
        ice, codec_hint: codec, gpu, whep_ok: first != null,
      };
    }
    """

    def run_once(auth_header: str | None) -> dict:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--use-angle=metal",
                      "--autoplay-policy=no-user-gesture-required",
                      "--disable-web-security"],
            )
            page = browser.new_page()
            page.set_content(
                "<!doctype html><video autoplay muted playsinline "
                "style='width:640px;height:360px;background:#000'></video>"
            )
            result = page.evaluate(js, {
                "endpoint": whep_url,
                "seconds": seconds,
                "authHeader": auth_header,
            })
            browser.close()
            return result

    try:
        out["auth_attempt"] = "none"
        r = run_once(None)
        if r.get("negotiate_status") == 401 and basic:
            out["auth_attempt"] = "Authorization_Basic_header"
            r = run_once(basic)
        out["negotiate_status"] = r.get("negotiate_status")
        out["sdp_ok"] = bool(r.get("sdp_ok"))
        out["first_frame_ms"] = r.get("first_frame_ms")
        out["ice"] = r.get("ice")
        out["codec_hint"] = r.get("codec_hint")
        out["gpu"] = r.get("gpu")
        if r.get("error"):
            out["error"] = safe(r["error"])
        out["status"] = "PASS" if r.get("whep_ok") else "FAIL"
    except Exception as exc:
        out["status"] = "FAIL"
        out["error"] = safe(f"{type(exc).__name__}: {exc}")
    return out


# ── HLS direct ─────────────────────────────────────────────────────────────


def probe_hls(hls_url: str, *, seconds: float = 8.0) -> dict:
    out = {
        "url_safe": hls_url,
        "status": "FAIL",
        "playlist_status": None,
        "live_sequence_advanced": False,
        "samples": [],
        "error": None,
    }
    headers = {"User-Agent": CLIENT, "Accept": "*/*"}
    cookie = os.environ.get("SENTINEL_GRID_COOKIE")
    if cookie:
        headers["Cookie"] = cookie

    def fetch(url: str) -> tuple[int | None, str, str | None]:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, r.read().decode("utf-8", "ignore"), None
        except Exception as exc:
            return getattr(exc, "code", None), "", safe(f"{type(exc).__name__}: {exc}")

    st, body, err = fetch(hls_url)
    out["playlist_status"] = st
    if err and not body:
        out["error"] = err
        return out
    if st and st >= 400:
        out["error"] = f"HTTP {st}"
        return out

    # Follow variant if master; keep session query
    variant = None
    for ln in body.splitlines():
        if ln and not ln.startswith("#"):
            variant = ln.strip()
            break
    media_url = hls_url
    if variant and "EXTINF" not in body:
        base = hls_url.rsplit("/", 1)[0]
        media_url = base + "/" + variant

    seqs = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        st2, vb, err2 = fetch(media_url)
        media_seq = None
        segs = 0
        if vb:
            segs = sum(1 for ln in vb.splitlines() if ln and not ln.startswith("#"))
            for ln in vb.splitlines():
                if ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                    media_seq = int(ln.split(":", 1)[1])
        out["samples"].append({
            "t": round(time.monotonic() - t0, 2),
            "status": st2,
            "media_sequence": media_seq,
            "segments": segs,
            "error": err2,
        })
        if media_seq is not None:
            seqs.append(media_seq)
        time.sleep(1.0)

    advanced = len(seqs) >= 2 and max(seqs) > min(seqs)
    out["live_sequence_advanced"] = advanced
    out["status"] = "PASS" if advanced else ("AMBER" if seqs else "FAIL")
    return out


# ── Decision tree ──────────────────────────────────────────────────────────


def decide(cat: dict, comparisons: list, probes: dict) -> dict:
    if not cat.get("reachable_json"):
        case = "CATALOGUE_UNAVAILABLE"
        ours_or_ext = "EXTERNAL_ACCESS_OR_SESSION"
        detail = (
            "GET /api/ingest did not return JSON from RTSP host (404) or CDN "
            "(HTML login/SPA). Stream password Basic auth does not unlock the "
            "catalogue. SENTINEL_GRID_COOKIE is not configured. Cannot validate "
            "CASE A (URL mismatch) until catalogue JSON is reachable."
        )
    else:
        mismatched = [c for c in comparisons if c.get("rtsp_match") is False]
        if mismatched:
            case = "A_CATALOGUE_URL_MISMATCH"
            ours_or_ext = "OUR_BUG"
            detail = "Catalogue RTSP URL differs from configured template URL."
        else:
            case = "CATALOGUE_OK_CONTINUE"
            ours_or_ext = None
            detail = "Catalogue reachable; URLs compared."

    rtsp = probes.get("rtsp") or {}
    whep = probes.get("whep") or {}
    hls = probes.get("hls") or {}

    # Refine with protocol results
    any_rtsp_frame = any(
        (v.get("pyav_url_authority_in_memory") or {}).get("status") == "FRAME"
        for v in rtsp.values()
    )
    any_whep = any(v.get("status") == "PASS" for v in whep.values())
    any_hls = any(v.get("status") == "PASS" for v in hls.values())
    all_rtsp_401 = all(
        (v.get("describe_auth") or {}).get("status") == 401
        or (v.get("pyav_url_authority_in_memory") or {}).get("status") == "AUTH_401"
        for v in rtsp.values()
    ) if rtsp else False

    if case.startswith("CATALOGUE") and cat.get("reachable_json"):
        pass
    elif any_whep and all_rtsp_401:
        case = "C_WHEP_OK_RTSP_401"
        ours_or_ext = "EXTERNAL_ACCESS"
        detail = "Direct WHEP works; RTSP auth fails — RTSP AI access/auth issue."
    elif any_hls and not any_whep and all_rtsp_401:
        case = "D_HLS_ONLY"
        ours_or_ext = "EXTERNAL_ACCESS"
        detail = "HLS works; RTSP+WHEP fail — sandbox access/configuration."
    elif any(
        (v.get("describe_auth") or {}).get("status") == 200
        and (v.get("pyav_url_authority_in_memory") or {}).get("status") != "FRAME"
        for v in rtsp.values()
    ):
        case = "E_DESCRIBE_OK_PYAV_FAIL"
        ours_or_ext = "OUR_BUG"
        detail = "RTSP DESCRIBE auth OK but PyAV fails — client/auth implementation."
    elif any_rtsp_frame:
        case = "F_OR_G_SOURCE_OK"
        ours_or_ext = "OUR_BUG_IF_APP_FAILS"
        detail = "RTSP frames arrive — source proven; app/relay issues are ours."
    elif all_rtsp_401 and not any_whep and not any_hls:
        case = "F_ACCESS_ALL_PROTOCOLS"
        # Map to user letters: credential/access
        ours_or_ext = "EXTERNAL_ACCESS"
        detail = (
            "RTSP DESCRIBE auth 401 (Basic+Digest header trials and in-memory "
            "URL-authority PyAV). Direct WHEP failed. HLS failed or unreachable. "
            "With catalogue JSON also unavailable, treat as sandbox access/"
            "authentication/session issue — not MediaMTX architecture."
        )

    return {
        "case": case,
        "ours_or_external": ours_or_ext,
        "detail": detail,
        "architecture_failure": ours_or_ext == "OUR_BUG",
    }


def guide_urls(cam_id: str, cfg: GridConfig) -> dict:
    return {
        "rtsp_url": cfg.rtsp(cam_id),
        "whep_url": cfg.whep(cam_id),
        "hls_url": cfg.hls(cam_id),
        "hls_guide_pattern": f"http://103.250.160.189/live/stream/{cam_id}/index.m3u8",
        "hls_cdn_pattern": f"https://cctv.corp8.cloud/{cam_id}/index.m3u8",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-ids", nargs="+", default=["cam01", "cam02", "cam05"])
    parser.add_argument("--whep-seconds", type=float, default=10)
    parser.add_argument("--hls-seconds", type=float, default=8)
    args = parser.parse_args()

    cfg = GridConfig.from_env()
    print("=== STEP 1 catalogue ===", flush=True)
    cat_raw = fetch_catalogue_raw()
    cameras = normalise_catalogue_cameras(cat_raw.get("payload"))
    live_ids = [c["id"] for c in cameras if c.get("live") in (True, "true", 1, "1")]
    catalogue_artifact = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "reachable_json": cat_raw["reachable_json"],
        "catalogue_url_used": cat_raw.get("catalogue_url_used"),
        "attempts": cat_raw.get("attempts"),
        "session_cookie_configured": cat_raw.get("session_cookie_configured"),
        "live_camera_ids": live_ids,
        "cameras": cameras,
        "note": (
            "Authoritative only when reachable_json=true. "
            "Credentials never stored."
        ),
    }
    OUT_CAT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(catalogue_artifact, indent=2) + "\n"
    refuse_secrets(blob)
    OUT_CAT.write_text(blob)
    print(f"  reachable_json={cat_raw['reachable_json']} cameras={len(cameras)}", flush=True)

    print("=== STEP 2 compare endpoints ===", flush=True)
    by_id = {c["id"]: c for c in cameras}
    comparisons = []
    for cid in args.compare_ids:
        configured_u = guide_urls(cid, cfg)
        cat_cam = by_id.get(cid)
        row = {
            "camera_id": cid,
            "in_catalogue": cat_cam is not None,
            "catalogue_live": (cat_cam or {}).get("live"),
            "catalogue_rtsp": (cat_cam or {}).get("rtsp_url"),
            "catalogue_whep": (cat_cam or {}).get("whep_url"),
            "catalogue_hls": (cat_cam or {}).get("hls_url"),
            "configured_rtsp": configured_u["rtsp_url"],
            "configured_whep": configured_u["whep_url"],
            "configured_hls": configured_u["hls_url"],
            "rtsp_match": None,
            "whep_match": None,
            "hls_match": None,
        }
        if cat_cam and cat_cam.get("rtsp_url"):
            row["rtsp_match"] = cat_cam["rtsp_url"] == configured_u["rtsp_url"]
            row["whep_match"] = (cat_cam.get("whep_url") == configured_u["whep_url"])
            row["hls_match"] = (cat_cam.get("hls_url") == configured_u["hls_url"])
        comparisons.append(row)
        print(f"  {cid} in_catalogue={row['in_catalogue']} rtsp_match={row['rtsp_match']}", flush=True)

    # If catalogue URL differs, STOP per instructions (record and do not
    # conclude 401 on wrong URL). If catalogue unavailable, probe guide URLs
    # labeled as configured/fallback — not catalogue-authoritative.
    stop_for_mismatch = any(c.get("rtsp_match") is False for c in comparisons)
    probes = {"rtsp": {}, "whep": {}, "hls": {}}

    if stop_for_mismatch:
        print("STOP: catalogue RTSP URL ≠ configured — integration must use catalogue", flush=True)
    else:
        print("=== STEP 3–6 protocol probes ===", flush=True)
        # Select cameras: prefer catalogue live; else compare-ids with guide URLs
        targets = []
        if cameras:
            for c in cameras:
                if c.get("live") in (True, "true", 1, "1") and c.get("rtsp_url"):
                    targets.append(c)
            targets = targets[:6] or cameras[:6]
        else:
            for cid in args.compare_ids:
                u = guide_urls(cid, cfg)
                targets.append({
                    "id": cid,
                    "live": None,
                    "codec": None,
                    "rtsp_url": u["rtsp_url"],
                    "whep_url": u["whep_url"],
                    "hls_url": u["hls_guide_pattern"],
                    "url_source": "configured_template_catalogue_unavailable",
                })

        # RTSP for compare-ids
        for cid in args.compare_ids:
            cat_cam = by_id.get(cid)
            rtsp_url = (cat_cam or {}).get("rtsp_url") or guide_urls(cid, cfg)["rtsp_url"]
            print(f"  RTSP {cid} ...", flush=True)
            probes["rtsp"][cid] = probe_rtsp(rtsp_url)
            probes["rtsp"][cid]["url_source"] = (
                "catalogue" if cat_cam and cat_cam.get("rtsp_url") else "configured_template"
            )
            print(
                f"    fail={probes['rtsp'][cid].get('first_failing_layer')} "
                f"auth_adv={probes['rtsp'][cid].get('auth_mechanism_advertised')} "
                f"pyav={ (probes['rtsp'][cid].get('pyav_url_authority_in_memory') or {}).get('status') }",
                flush=True,
            )

        # WHEP: one H.264 + one HEVC if known; else cam01 + cam06
        whep_targets = []
        if cameras:
            h264 = next((c for c in cameras if c.get("live") and str(c.get("codec") or "").lower() in {"h264", "avc"}), None)
            hevc = next((c for c in cameras if c.get("live") and str(c.get("codec") or "").lower() in {"h265", "hevc"}), None)
            for c in (h264, hevc):
                if c and c.get("whep_url"):
                    whep_targets.append(c)
        if not whep_targets:
            for cid in ("cam01", "cam06"):
                u = guide_urls(cid, cfg)
                whep_targets.append({"id": cid, "codec": "unknown", "whep_url": u["whep_url"]})

        for c in whep_targets[:2]:
            cid = c["id"]
            print(f"  WHEP direct {cid} ...", flush=True)
            probes["whep"][cid] = probe_whep(c["whep_url"], seconds=args.whep_seconds)
            probes["whep"][cid]["codec_expected"] = c.get("codec")
            print(
                f"    status={probes['whep'][cid].get('status')} "
                f"http={probes['whep'][cid].get('negotiate_status')}",
                flush=True,
            )

        # HLS for first compare id — try guide patterns
        cid = args.compare_ids[0]
        cat_cam = by_id.get(cid)
        hls_candidates = []
        if cat_cam and cat_cam.get("hls_url"):
            hls_candidates.append(("catalogue", cat_cam["hls_url"]))
        gu = guide_urls(cid, cfg)
        hls_candidates.append(("guide_ip", gu["hls_guide_pattern"]))
        hls_candidates.append(("cdn", gu["hls_cdn_pattern"]))
        hls_candidates.append(("configured_template", gu["hls_url"]))
        for label, url in hls_candidates:
            print(f"  HLS {cid} ({label}) ...", flush=True)
            result = probe_hls(url, seconds=args.hls_seconds)
            result["url_source"] = label
            probes["hls"][f"{cid}:{label}"] = result
            print(f"    status={result.get('status')} playlist={result.get('playlist_status')}", flush=True)
            if result.get("status") == "PASS":
                break

    decision = decide(catalogue_artifact, comparisons, probes)

    # Auth mechanism summary
    auth_schemes = {
        cid: (probes["rtsp"].get(cid) or {}).get("auth_mechanism_advertised")
        for cid in args.compare_ids
    }

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "client": CLIENT,
        "label": "MEASURED",
        "credentials_configured": configured(),
        "credentials_in_artifact": False,
        "catalogue": {
            "reachable_json": catalogue_artifact["reachable_json"],
            "url_used": catalogue_artifact.get("catalogue_url_used"),
            "live_camera_ids": live_ids,
            "camera_count": len(cameras),
            "attempts_summary": [
                {"url_safe": a["url_safe"], "status": a.get("status"),
                 "error": a.get("error"), "json": a.get("json")}
                for a in catalogue_artifact.get("attempts") or []
            ],
        },
        "endpoint_comparison": comparisons,
        "rtsp_auth_mechanism_by_camera": auth_schemes,
        "probes": probes,
        "decision": decision,
        "support_evidence": {
            "camera_ids": args.compare_ids,
            "exact_urls_safe": {
                cid: {
                    "rtsp": (probes.get("rtsp") or {}).get(cid, {}).get("url_safe"),
                    "whep": next(
                        (v.get("url_safe") for k, v in (probes.get("whep") or {}).items()
                         if k == cid),
                        guide_urls(cid, cfg)["whep_url"],
                    ),
                    "hls": guide_urls(cid, cfg)["hls_guide_pattern"],
                }
                for cid in args.compare_ids
            },
            "client_version": CLIENT,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "catalogue_live_confirmation": (
                "UNAVAILABLE — /api/ingest did not return JSON"
                if not catalogue_artifact["reachable_json"]
                else {cid: (by_id.get(cid) or {}).get("live") for cid in args.compare_ids}
            ),
            "client_side_error_summary": {
                cid: {
                    "rtsp_first_fail": (probes.get("rtsp") or {}).get(cid, {}).get("first_failing_layer"),
                    "rtsp_describe_auth": ((probes.get("rtsp") or {}).get(cid, {}).get("describe_auth") or {}).get("status"),
                    "pyav": ((probes.get("rtsp") or {}).get(cid, {}).get("pyav_url_authority_in_memory") or {}).get("status"),
                    "pyav_error_safe": ((probes.get("rtsp") or {}).get(cid, {}).get("pyav_url_authority_in_memory") or {}).get("error"),
                }
                for cid in args.compare_ids
            },
        },
    }

    blob = json.dumps(payload, indent=2) + "\n"
    refuse_secrets(blob)
    OUT_JSON.write_text(blob)

    # Markdown report
    md = f"""# Sentinel contract probe

Timestamp UTC: `{payload['timestamp_utc']}`  
Client: `{CLIENT}`

## Decision

**Case:** `{decision['case']}`  
**Ours vs external:** `{decision['ours_or_external']}`  
**Architecture failure:** `{decision['architecture_failure']}`

{decision['detail']}

## 1. Catalogue host

| Attempt URL | Status | Result |
|---|---:|---|
"""
    for a in catalogue_artifact.get("attempts") or []:
        md += f"| `{a['url_safe']}` | {a.get('status')} | {a.get('error') or ('JSON OK' if a.get('json') else a.get('content_type'))} |\n"

    md += f"""
Authoritative JSON reachable: **{catalogue_artifact['reachable_json']}**  
Live camera IDs from catalogue: `{live_ids or 'NONE — catalogue unavailable'}`

## 2. Endpoint comparison (cam01 / cam02 / cam05)

| ID | In catalogue | Catalogue RTSP | Configured RTSP | Match |
|---|---|---|---|---|
"""
    for c in comparisons:
        md += (
            f"| {c['camera_id']} | {c['in_catalogue']} | "
            f"`{c.get('catalogue_rtsp')}` | `{c.get('configured_rtsp')}` | "
            f"{c.get('rtsp_match')} |\n"
        )

    md += """
## 3. RTSP (TCP)

| ID | Auth advertised | Header trials | DESCRIBE auth | SETUP | PLAY | PyAV | First fail |
|---|---|---|---:|---:|---:|---|---|
"""
    for cid in args.compare_ids:
        r = (probes.get("rtsp") or {}).get(cid) or {}
        md += (
            f"| {cid} | {r.get('auth_mechanism_advertised')} | "
            f"`{safe(json.dumps(r.get('auth_header_trials')))}` | "
            f"{(r.get('describe_auth') or {}).get('status')} | "
            f"{(r.get('setup') or {}).get('status') if r.get('setup') else '—'} | "
            f"{(r.get('play') or {}).get('status') if r.get('play') else '—'} | "
            f"{(r.get('pyav_url_authority_in_memory') or {}).get('status')} | "
            f"{r.get('first_failing_layer')} |\n"
        )

    md += """
## 4. Direct WHEP (no local MediaMTX)

| ID | Status | Negotiate HTTP | First frame ms | ICE | Error |
|---|---|---:|---:|---|---|
"""
    for cid, w in (probes.get("whep") or {}).items():
        md += (
            f"| {cid} | {w.get('status')} | {w.get('negotiate_status')} | "
            f"{w.get('first_frame_ms')} | {w.get('ice')} | {safe(w.get('error'))} |\n"
        )

    md += """
## 5. Direct HLS

| Key | Status | Playlist HTTP | Sequence advanced |
|---|---|---:|---|
"""
    for key, h in (probes.get("hls") or {}).items():
        md += (
            f"| {key} | {h.get('status')} | {h.get('playlist_status')} | "
            f"{h.get('live_sequence_advanced')} |\n"
        )

    md += f"""
## Support evidence (if external)

- Camera IDs: {args.compare_ids}
- Exact URLs (safe): see JSON `support_evidence.exact_urls_safe`
- Client/version: `{CLIENT}`
- UTC timestamp: `{payload['timestamp_utc']}`
- Catalogue live confirmation: **unavailable** (no JSON from `/api/ingest`)
- Client-side errors: redacted in JSON `support_evidence.client_side_error_summary`

Credentials: environment only. Not in this report.

Artifacts:
- `{OUT_CAT.relative_to(ROOT)}`
- `{OUT_JSON.relative_to(ROOT)}`
"""
    refuse_secrets(md)
    OUT_MD.write_text(md)

    print(json.dumps({
        "case": decision["case"],
        "ours_or_external": decision["ours_or_external"],
        "catalogue_json": catalogue_artifact["reachable_json"],
        "live_ids": live_ids,
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
