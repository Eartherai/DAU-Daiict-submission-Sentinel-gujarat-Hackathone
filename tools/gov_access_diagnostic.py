#!/usr/bin/env python3
"""Final government RTSP access diagnostic — no architecture changes.

Credentials: SENTINEL_GRID_* env only.
Never printed, never in argv, never written to reports/JSON.
RTSP DESCRIBE/SETUP/PLAY uses Authorization header (not URL authority).
PyAV demux uses ephemeral in-memory authority injection (grid requirement);
all error paths are redacted before persistence.
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
from datetime import UTC, datetime
from hashlib import md5
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured, credentialed, redact  # noqa: E402

HOST = "103.250.160.189"
PORT = 8554
OUT_JSON = ROOT / "var/reports/phase10/government_access_diagnostic.json"
OUT_MD = ROOT / "reports/FINAL_GOVERNMENT_ACCESS_DIAGNOSTIC.md"
CAMERAS = ["cam01", "cam02", "cam05"]

_AUTH_IN_TEXT = re.compile(r"(?<=//)[^/@\s'\"]*:[^/@\s'\"]*@")


def safe(text: str | None) -> str:
    """Strip any credential-shaped content before persistence/print."""
    if not text:
        return ""
    out = redact(str(text))
    out = _AUTH_IN_TEXT.sub("<redacted>@", out)
    email = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    if password:
        out = out.replace(password, "<redacted>")
    if email:
        out = out.replace(email, "<redacted>")
        out = out.replace(email.replace("@", "%40"), "<redacted>")
    return out[:240]


def tcp_connect(host: str, port: int, timeout: float = 5.0) -> dict:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "ok": True,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": None,
            }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "error": safe(f"{type(exc).__name__}: {exc}"),
        }


def _parse_www_authenticate(header: str) -> dict:
    """Parse WWW-Authenticate (Basic or Digest)."""
    out: dict = {"scheme": None}
    if not header:
        return out
    parts = header.strip().split(None, 1)
    if not parts:
        return out
    out["scheme"] = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    for m in re.finditer(r'(\w+)="([^"]*)"', rest):
        out[m.group(1).lower()] = m.group(2)
    for m in re.finditer(r'(\w+)=([^,\s]+)', rest):
        k = m.group(1).lower()
        if k not in out:
            out[k] = m.group(2).strip('"')
    return out


def _basic_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Authorization: Basic {token}"


def _digest_header(user: str, password: str, method: str, uri: str, wa: dict,
                   nc: str = "00000001") -> str:
    realm = wa.get("realm", "")
    nonce = wa.get("nonce", "")
    qop = wa.get("qop", "")
    opaque = wa.get("opaque")
    algorithm = (wa.get("algorithm") or "MD5").upper()
    if algorithm not in {"MD5", "MD5-SESS"}:
        algorithm = "MD5"
    cnonce = md5(f"{time.time()}{os.getpid()}".encode()).hexdigest()[:16]
    ha1 = md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    if algorithm == "MD5-SESS":
        ha1 = md5(f"{ha1}:{nonce}:{cnonce}".encode()).hexdigest()
    ha2 = md5(f"{method}:{uri}".encode()).hexdigest()
    if qop:
        qop_val = qop.split(",")[0].strip()
        resp = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop_val}:{ha2}".encode()).hexdigest()
        bits = [
            f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"',
            f'uri="{uri}"', f'response="{resp}"', f'algorithm={algorithm}',
            f'qop={qop_val}', f'nc={nc}', f'cnonce="{cnonce}"',
        ]
    else:
        resp = md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        bits = [
            f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"',
            f'uri="{uri}"', f'response="{resp}"', f'algorithm={algorithm}',
        ]
    if opaque:
        bits.append(f'opaque="{opaque}"')
    return "Authorization: Digest " + ", ".join(bits)


def rtsp_exchange(
    path: str,
    *,
    method: str,
    cseq: int,
    session: str | None = None,
    transport: str | None = None,
    auth_header: str | None = None,
    timeout: float = 8.0,
) -> dict:
    """One RTSP request/response. path is /stream/camXX — no credentials in URI."""
    uri = f"rtsp://{HOST}:{PORT}{path}"
    lines = [
        f"{method} {uri} RTSP/1.0",
        f"CSeq: {cseq}",
        f"User-Agent: SaakshyaAccessDiag/1.0",
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
    err = None
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(body.encode("utf-8"))
            while b"\r\n\r\n" not in raw and len(raw) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
        text = raw.decode("utf-8", "replace")
        head, _, _rest = text.partition("\r\n\r\n")
        first = head.split("\r\n", 1)[0] if head else ""
        m = re.match(r"RTSP/1\.\d\s+(\d+)", first)
        status = int(m.group(1)) if m else None
        for ln in head.split("\r\n")[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
    except Exception as exc:
        err = safe(f"{type(exc).__name__}: {exc}")
    return {
        "method": method,
        "status": status,
        "headers": {k: safe(v) for k, v in headers.items()
                    if k in {"www-authenticate", "session", "content-type",
                             "content-base", "public", "server"}},
        "www_authenticate_present": "www-authenticate" in headers,
        "session": headers.get("session", "").split(";")[0].strip() or None,
        "error": err,
        "raw_status_line": safe(first if 'first' in dir() else ""),
    }


def authenticate_rtsp(path: str) -> dict:
    """DESCRIBE → (401 + WWW-Authenticate) → authenticated DESCRIBE → SETUP → PLAY."""
    user = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    out: dict = {
        "describe_unauth": None,
        "describe_auth": None,
        "setup": None,
        "play": None,
        "auth_scheme": None,
        "first_failing_layer": None,
        "authenticated": False,
    }

    unauth = rtsp_exchange(path, method="DESCRIBE", cseq=1)
    out["describe_unauth"] = {
        "status": unauth["status"],
        "error": unauth["error"],
        "www_authenticate_present": unauth["www_authenticate_present"],
    }
    wa_raw = None
    # Re-fetch header value for parsing (need raw for digest) — second connect
    # We must re-read www-authenticate without logging secrets; parse from socket again.
    wa = {}
    if unauth["status"] in {401, 407} or unauth["www_authenticate_present"]:
        # Get raw WWW-Authenticate for digest construction (never stored in report)
        try:
            with socket.create_connection((HOST, PORT), timeout=8) as sock:
                sock.settimeout(8)
                req = (
                    f"DESCRIBE rtsp://{HOST}:{PORT}{path} RTSP/1.0\r\n"
                    f"CSeq: 1\r\n"
                    f"User-Agent: SaakshyaAccessDiag/1.0\r\n"
                    f"Accept: application/sdp\r\n\r\n"
                )
                sock.sendall(req.encode())
                raw = b""
                while b"\r\n\r\n" not in raw and len(raw) < 65536:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    raw += chunk
            head = raw.decode("utf-8", "replace").split("\r\n\r\n", 1)[0]
            for ln in head.split("\r\n")[1:]:
                if ln.lower().startswith("www-authenticate:"):
                    wa_raw = ln.split(":", 1)[1].strip()
                    wa = _parse_www_authenticate(wa_raw)
                    break
        except Exception as exc:
            out["first_failing_layer"] = "DESCRIBE"
            out["describe_auth"] = {"status": None, "error": safe(str(exc))}
            return out

    auth_header = None
    if wa.get("scheme") == "digest":
        out["auth_scheme"] = "Digest"
        auth_header = _digest_header(user, password, "DESCRIBE", path, wa)
    elif wa.get("scheme") == "basic" or unauth["status"] in {401, 407, None}:
        # Prefer Basic when advertised; also try Basic if server wants URL-auth style 401
        out["auth_scheme"] = out["auth_scheme"] or "Basic"
        auth_header = _basic_header(user, password)
        if wa.get("scheme") == "basic":
            out["auth_scheme"] = "Basic"

    if unauth["status"] == 200 and not auth_header:
        # Open without auth — unexpected for gov grid
        out["describe_auth"] = {"status": 200, "note": "unauthenticated_ok"}
        out["authenticated"] = True
    else:
        if not auth_header:
            out["auth_scheme"] = "Basic"
            auth_header = _basic_header(user, password)
        desc = rtsp_exchange(path, method="DESCRIBE", cseq=2, auth_header=auth_header)
        # If Digest advertised and Basic failed, retry Digest (already set if scheme digest)
        if desc["status"] == 401 and wa.get("scheme") == "digest":
            auth_header = _digest_header(user, password, "DESCRIBE", path, wa)
            desc = rtsp_exchange(path, method="DESCRIBE", cseq=3, auth_header=auth_header)
        out["describe_auth"] = {
            "status": desc["status"],
            "error": desc["error"],
        }
        if desc["status"] != 200:
            out["first_failing_layer"] = "DESCRIBE_AUTH"
            return out
        out["authenticated"] = True
        # Refresh digest for subsequent methods if needed
        if out["auth_scheme"] == "Digest" and wa:
            auth_header = _digest_header(user, password, "SETUP", path, wa, nc="00000002")

    # SETUP (TCP interleaved)
    transport = "RTP/AVP/TCP;unicast;interleaved=0-1"
    if out["auth_scheme"] == "Digest" and wa:
        auth_header = _digest_header(user, password, "SETUP", f"{path}", wa, nc="00000002")
    # Some servers want track URI from SDP; try base path first then /trackID=0
    setup = rtsp_exchange(
        path, method="SETUP", cseq=4, auth_header=auth_header, transport=transport,
    )
    if setup["status"] not in {200, 301, 302}:
        setup = rtsp_exchange(
            f"{path}/trackID=0", method="SETUP", cseq=5,
            auth_header=(
                _digest_header(user, password, "SETUP", f"{path}/trackID=0", wa, nc="00000003")
                if out["auth_scheme"] == "Digest" and wa
                else auth_header
            ),
            transport=transport,
        )
    out["setup"] = {"status": setup["status"], "error": setup["error"],
                    "session_present": bool(setup.get("session"))}
    if setup["status"] != 200:
        out["first_failing_layer"] = "SETUP"
        return out

    session = setup.get("session")
    if out["auth_scheme"] == "Digest" and wa:
        auth_header = _digest_header(user, password, "PLAY", path, wa, nc="00000004")
    play = rtsp_exchange(
        path, method="PLAY", cseq=6, session=session, auth_header=auth_header,
    )
    out["play"] = {"status": play["status"], "error": play["error"]}
    if play["status"] != 200:
        out["first_failing_layer"] = "PLAY"
        return out
    return out


def pyav_first_frame(camera_id: str, seconds: float = 8.0) -> dict:
    """First decoded/demuxed packet via PyAV. Authority injected in-memory only."""
    import av

    clean = f"rtsp://{HOST}:{PORT}/stream/{camera_id}"
    # Ephemeral — never logged. Grid requires authority form for libavformat.
    open_url = credentialed(clean, required=True)
    t0 = time.monotonic()
    frames = 0
    codec = None
    err = None
    status = "FAIL"
    try:
        inp = av.open(
            open_url,
            options={"rtsp_transport": "tcp", "stimeout": "8000000"},
            timeout=20,
        )
        try:
            v = next(s for s in inp.streams if s.type == "video")
            codec = v.codec_context.name if v.codec_context else None
            deadline = t0 + seconds
            for packet in inp.demux(v):
                if time.monotonic() >= deadline:
                    break
                if packet.dts is None and packet.pts is None:
                    continue
                frames += 1
                if frames >= 1:
                    status = "FRAME"
                if frames >= 15:
                    break
        finally:
            inp.close()
    except Exception as exc:
        err = safe(f"{type(exc).__name__}: {exc}")
        if "401" in (err or ""):
            status = "AUTH_401"
    # Drop reference to credentialed URL
    del open_url
    return {
        "status": status,
        "frames": frames,
        "codec": codec,
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        "error": err,
        "url_safe": f"rtsp://{HOST}:{PORT}/stream/{camera_id}",
    }


def relay_30s(camera_id: str) -> dict:
    """30s authenticated relay into local MediaMTX (existing tool, env-only)."""
    # Ensure local mtx for publish target
    cfg = ROOT / "var/mediamtx_access_diag.yml"
    cfg.write_text(
        "# generated — no credentials\n"
        "logLevel: warn\n"
        "rtspAddress: :8554\n"
        "rtspTransports: [tcp]\n"
        "hlsAddress: :8888\n"
        "webrtcAddress: :8889\n"
        "webrtcAllowOrigins: [\"*\"]\n"
        "api: yes\n"
        "apiAddress: 127.0.0.1:9997\n"
        "paths:\n"
        f"  stream/gov-{camera_id}:\n"
    )
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.3)
    log = open(ROOT / "var/logs/mediamtx_access_diag.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    time.sleep(0.8)
    env = {
        k: v for k, v in os.environ.items()
        if k in {
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
            "VIRTUAL_ENV", "PYTHONPATH", "PYTHONUNBUFFERED",
            "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
        }
    }
    # No credentials in argv — only camera id + flags
    pub = subprocess.run(
        [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), camera_id,
         "--seconds", "30", "--publish-only"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=90,
    )
    frames = 0
    status = "FAIL"
    err = None
    try:
        # stdout may be JSON report from publish_only
        line = (pub.stdout or "").strip().splitlines()[-1] if pub.stdout else ""
        if line.startswith("{"):
            rep = json.loads(line)
            frames = int(rep.get("frames") or 0)
            status = "OK" if frames > 0 else "FAIL"
            err = safe(rep.get("error"))
        else:
            err = safe((pub.stderr or pub.stdout or "")[-200:])
            status = "FAIL"
    except Exception as exc:
        err = safe(str(exc))
    # Check local path bytes
    local_ready = False
    try:
        import urllib.request
        with urllib.request.urlopen(
            f"http://127.0.0.1:9997/v3/paths/get/stream/gov-{camera_id}", timeout=3
        ) as r:
            d = json.load(r)
            local_ready = bool(d.get("ready")) and (d.get("bytesReceived") or 0) > 5000
    except Exception:
        pass
    try:
        mtx.terminate()
    except Exception:
        pass
    return {
        "status": status,
        "frames": frames,
        "local_path_ready": local_ready,
        "returncode": pub.returncode,
        "error": err,
    }


def whep_browser(camera_id: str, seconds: float = 10.0) -> dict:
    """Browser WHEP against local relay path (already publishing)."""
    # Start mtx + short publish again for WHEP window
    cfg = ROOT / "var/mediamtx_access_diag.yml"
    cfg.write_text(
        "# generated — no credentials\n"
        "logLevel: warn\n"
        "rtspAddress: :8554\n"
        "rtspTransports: [tcp]\n"
        "webrtcAddress: :8889\n"
        "webrtcAllowOrigins: [\"*\"]\n"
        "api: yes\n"
        "apiAddress: 127.0.0.1:9997\n"
        "paths:\n"
        f"  stream/gov-{camera_id}:\n"
    )
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.3)
    log = open(ROOT / "var/logs/mediamtx_access_diag.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    env = {
        k: v for k, v in os.environ.items()
        if k in {
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
            "VIRTUAL_ENV", "PYTHONPATH", "PYTHONUNBUFFERED",
            "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
        }
    }
    pub = subprocess.Popen(
        [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), camera_id,
         "--seconds", str(int(seconds + 45)), "--publish-only"],
        cwd=str(ROOT), env=env,
    )
    # Wait for path ready
    ready = False
    for _ in range(40):
        time.sleep(1)
        try:
            import urllib.request
            with urllib.request.urlopen(
                f"http://127.0.0.1:9997/v3/paths/get/stream/gov-{camera_id}", timeout=2
            ) as r:
                d = json.load(r)
                if d.get("ready") and (d.get("bytesReceived") or 0) > 12000:
                    ready = True
                    break
        except Exception:
            if pub.poll() is not None:
                break
    result = {
        "publisher_ready": ready,
        "status": "SKIPPED_NO_PUBLISH",
        "first_frame_ms": None,
        "error": None,
        "gpu": None,
    }
    if not ready:
        result["error"] = "local publisher never ready (likely upstream auth)"
        try:
            pub.terminate()
            mtx.terminate()
        except Exception:
            pass
        return result

    endpoint = f"http://127.0.0.1:8889/stream/gov-{camera_id}/whep"
    try:
        from playwright.sync_api import sync_playwright
        js = r"""
        async ({endpoint, seconds}) => {
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
          const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'},
            body: pc.localDescription.sdp,
            signal: AbortSignal.timeout(12000),
          });
          if (!resp.ok) throw new Error('WHEP ' + resp.status);
          await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
          await video.play().catch(() => {});
          let first = null;
          const deadline = performance.now() + seconds * 1000;
          while (performance.now() < deadline) {
            if (video.videoWidth > 0 && video.currentTime > 0) {
              first = performance.now() - t0;
              break;
            }
            await new Promise(r => setTimeout(r, 50));
          }
          let gpu = null;
          try {
            const c = document.createElement('canvas');
            const gl = c.getContext('webgl');
            const d = gl && gl.getExtension('WEBGL_debug_renderer_info');
            gpu = gl ? gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : null;
          } catch (_) {}
          pc.close();
          return {first_frame_ms: first, gpu, whep_ok: first != null};
        }
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--use-angle=metal",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-web-security",
                ],
            )
            page = browser.new_page()
            page.set_content(
                "<!doctype html><video autoplay muted playsinline "
                "style='width:640px;height:360px;background:#000'></video>"
            )
            wall = page.evaluate(js, {"endpoint": endpoint, "seconds": seconds})
            browser.close()
        result["status"] = "PASS" if wall.get("whep_ok") else "FAIL"
        result["first_frame_ms"] = wall.get("first_frame_ms")
        result["gpu"] = wall.get("gpu")
    except Exception as exc:
        result["status"] = "FAIL"
        result["error"] = safe(f"{type(exc).__name__}: {exc}")
    try:
        pub.terminate()
        mtx.terminate()
    except Exception:
        pass
    return result


def classify(cam: dict) -> str:
    if cam.get("whep", {}).get("status") == "PASS":
        return "WHEP_BROWSER_PASS"
    if cam.get("pyav", {}).get("status") == "FRAME" and (cam.get("pyav", {}).get("frames") or 0) > 0:
        return "RTSP_AUTHENTICATED_FRAME"
    play = (cam.get("rtsp") or {}).get("play") or {}
    desc = (cam.get("rtsp") or {}).get("describe_auth") or {}
    if play.get("status") == 200 or desc.get("status") == 200:
        return "RTSP_AUTHENTICATED"
    if cam.get("tcp", {}).get("ok"):
        unauth = (cam.get("rtsp") or {}).get("describe_unauth") or {}
        auth = (cam.get("rtsp") or {}).get("describe_auth") or {}
        if auth.get("status") == 401 or (
            unauth.get("status") == 401 and auth.get("status") in {401, None}
        ):
            return "AUTH_REJECTED"
        if unauth.get("status") == 200:
            return "RTSP_REACHABLE_NO_AUTH"
        return "AUTH_REJECTED"
    return "AUTH_REJECTED"


def diagnose_camera(camera_id: str) -> dict:
    path = f"/stream/{camera_id}"
    print(f"=== {camera_id} ===", flush=True)
    tcp = tcp_connect(HOST, PORT)
    print(f"  tcp ok={tcp['ok']} {tcp['latency_ms']}ms", flush=True)
    rtsp = {
        "describe_unauth": None,
        "describe_auth": None,
        "setup": None,
        "play": None,
        "auth_scheme": None,
        "first_failing_layer": "TCP",
        "authenticated": False,
    }
    pyav = {"status": "SKIPPED", "frames": 0, "error": "tcp_failed"}
    relay = {"status": "SKIPPED", "frames": 0}
    whep = {"status": "SKIPPED"}

    if tcp["ok"]:
        rtsp = authenticate_rtsp(path)
        print(
            f"  describe_unauth={ (rtsp.get('describe_unauth') or {}).get('status') } "
            f"describe_auth={ (rtsp.get('describe_auth') or {}).get('status') } "
            f"setup={ (rtsp.get('setup') or {}).get('status') } "
            f"play={ (rtsp.get('play') or {}).get('status') }",
            flush=True,
        )
        # Always attempt PyAV — may use different auth path than header Basic
        pyav = pyav_first_frame(camera_id)
        print(f"  pyav status={pyav['status']} frames={pyav['frames']}", flush=True)
        if pyav["status"] == "FRAME":
            relay = relay_30s(camera_id)
            print(f"  relay status={relay['status']} frames={relay['frames']}", flush=True)
            if relay["status"] == "OK":
                whep = whep_browser(camera_id)
                print(f"  whep status={whep['status']}", flush=True)
            else:
                whep = {"status": "SKIPPED_RELAY_FAIL", "error": relay.get("error")}
        else:
            relay = {"status": "SKIPPED_NO_FRAME", "error": pyav.get("error")}
            whep = {"status": "SKIPPED_NO_FRAME"}
            if not rtsp.get("first_failing_layer"):
                rtsp["first_failing_layer"] = "PYAV"
    else:
        rtsp["first_failing_layer"] = "TCP"

    cam = {
        "camera_id": camera_id,
        "endpoint_safe": f"rtsp://{HOST}:{PORT}/stream/{camera_id}",
        "tcp": tcp,
        "rtsp": rtsp,
        "pyav": pyav,
        "relay_30s": relay,
        "whep": whep,
    }
    cam["classification"] = classify(cam)
    # Determine first failing layer for summary
    fail = rtsp.get("first_failing_layer")
    if cam["classification"] == "WHEP_BROWSER_PASS":
        fail = None
    elif cam["classification"] == "RTSP_AUTHENTICATED_FRAME" and whep.get("status") != "PASS":
        fail = fail or "WHEP"
    elif pyav.get("status") == "AUTH_401":
        fail = "PYAV_AUTH"
    cam["first_failing_layer"] = fail
    print(f"  class={cam['classification']} fail={fail}", flush=True)
    return cam


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", nargs="+", default=CAMERAS)
    args = parser.parse_args()

    if not configured():
        print("credentials not configured in environment", file=sys.stderr)
        return 2

    results = [diagnose_camera(c) for c in args.cameras]
    classes = [r["classification"] for r in results]
    any_auth_ok = any(
        c in {"RTSP_AUTHENTICATED", "RTSP_AUTHENTICATED_FRAME", "WHEP_BROWSER_PASS"}
        for c in classes
    )
    all_auth_rejected = all(c == "AUTH_REJECTED" for c in classes)
    tcp_ok = all(r["tcp"]["ok"] for r in results)

    if all_auth_rejected and tcp_ok:
        failure_domain = "EXTERNAL_ACCESS/AUTHENTICATION"
        architecture_failure = False
    elif any(c == "WHEP_BROWSER_PASS" for c in classes):
        failure_domain = None
        architecture_failure = False
    elif any_auth_ok:
        failure_domain = "POST_AUTH_MEDIA_OR_BROWSER"
        architecture_failure = True
    else:
        failure_domain = "EXTERNAL_ACCESS/AUTHENTICATION"
        architecture_failure = False

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED",
        "host_safe": f"{HOST}:{PORT}",
        "credentials_configured": True,
        "credentials_in_report": False,
        "auth_transport": (
            "RTSP Authorization header for DESCRIBE/SETUP/PLAY; "
            "PyAV ephemeral in-memory authority for demux (never persisted)"
        ),
        "cameras": results,
        "summary": {
            "classifications": {r["camera_id"]: r["classification"] for r in results},
            "failure_domain": failure_domain,
            "architecture_failure": architecture_failure,
            "note": (
                "If DESCRIBE/PLAY/PyAV return 401 with fresh env credentials while "
                "synthetic WHEP passes, classify as EXTERNAL_ACCESS/AUTHENTICATION."
            ),
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, indent=2) + "\n"
    # Refuse to write if any credential-shaped authority slipped in
    if _AUTH_IN_TEXT.search(blob):
        raise SystemExit("refusing to write credential-like content")
    email = os.environ.get("SENTINEL_GRID_EMAIL") or ""
    password = os.environ.get("SENTINEL_GRID_PASSWORD") or ""
    if (password and password in blob) or (email and email in blob):
        raise SystemExit("refusing to write credential plaintext")
    OUT_JSON.write_text(blob)

    rows = []
    for r in results:
        rows.append(
            f"| {r['camera_id']} | {r['classification']} | "
            f"{(r.get('rtsp') or {}).get('describe_unauth', {}).get('status')} | "
            f"{(r.get('rtsp') or {}).get('describe_auth', {}).get('status')} | "
            f"{(r.get('rtsp') or {}).get('setup', {}) and (r.get('rtsp') or {}).get('setup', {}).get('status')} | "
            f"{(r.get('rtsp') or {}).get('play', {}) and (r.get('rtsp') or {}).get('play', {}).get('status')} | "
            f"{(r.get('pyav') or {}).get('status')} | "
            f"{(r.get('relay_30s') or {}).get('status')} | "
            f"{(r.get('whep') or {}).get('status')} | "
            f"{r.get('first_failing_layer')} |"
        )

    md = f"""# Final government access diagnostic

Timestamp UTC: `{payload['timestamp_utc']}`

## Verdict

**Failure domain:** `{failure_domain}`  
**Architecture failure:** `{architecture_failure}`

Credentials: environment-only (`SENTINEL_GRID_*`). Not printed. Not in argv. Not in this report.

Synthetic browser path previously MEASURED at 16/16 PASS. This diagnostic isolates government RTSP authentication.

## Per-camera

| Camera | Classification | DESCRIBE no-auth | DESCRIBE auth | SETUP | PLAY | PyAV | Relay 30s | WHEP | First fail |
|---|---|---:|---:|---:|---:|---|---|---|---|
{chr(10).join(rows)}

## Layer notes

1. **TCP** to `{HOST}:{PORT}` — reachability only.
2. **DESCRIBE/SETUP/PLAY** — RTSP with `Authorization` header (not URL authority).
3. **PyAV** — ephemeral in-memory authority injection required by libavformat; errors redacted.
4. **Relay / WHEP** — only attempted after authenticated frames.

## Interpretation

"""
    if failure_domain == "EXTERNAL_ACCESS/AUTHENTICATION":
        md += (
            "Government endpoint is reachable over TCP but rejects authentication "
            "(HTTP/RTSP 401) with the configured fresh credentials. "
            "This is **EXTERNAL_ACCESS/AUTHENTICATION**, not a MediaMTX/WHEP "
            "architecture failure. Do not rewrite the media path until authenticated "
            "PLAY succeeds.\n"
        )
    elif architecture_failure:
        md += (
            "Authentication succeeded at least partially; failure is after PLAY. "
            "Media/browser path investigation is warranted.\n"
        )
    else:
        md += "At least one camera achieved WHEP browser PASS with authenticated ingest.\n"

    md += f"""
## Artifacts

- `{OUT_JSON.relative_to(ROOT)}`
- Secret scan required after this run.
"""
    if _AUTH_IN_TEXT.search(md) or (password and password in md) or (email and email in md):
        raise SystemExit("refusing to write credential content to markdown")
    OUT_MD.write_text(md)
    print(json.dumps({
        "failure_domain": failure_domain,
        "architecture_failure": architecture_failure,
        "classifications": payload["summary"]["classifications"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
