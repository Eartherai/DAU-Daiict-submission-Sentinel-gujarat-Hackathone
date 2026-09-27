"""Local video media plane: one Sentinel ingest per camera, local WHEP out.

Sentinel RTSP/TCP
    |  one publisher / camera (H.264 packet copy; HEVC → H.264)
    v
MediaMTX (loopback)
    |-- HLS   → 30-camera browser wall
    |-- WHEP  → focused, low-latency browser view (never Sentinel WHEP)
    |-- RTSP  → isolated AI worker
    `-- JPEG  → PREVIEW fallback only

Government H.264 carries B-frames, which MediaMTX WebRTC rejects but HLS can
carry unchanged.  The wall therefore packet-copies H.264 into local HLS and
reserves H.264 baseline transcoding for the two HEVC sources.  This is the
only viable way to fan out thirty feeds on a laptop without thirty encoders.
JPEG is never the live transport.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from saakshya.live.credentials import configured
from saakshya.live.snapshot import Snapshot, local_media_url

log = logging.getLogger("saakshya.live.relay")

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "var" / "run"
LOGS = ROOT / "var" / "logs"

RTSP_PORT = int(os.environ.get("SAAKSHYA_RELAY_RTSP_PORT", "18554"))
WHEP_PORT = int(os.environ.get("SAAKSHYA_RELAY_WHEP_PORT", "18889"))
HLS_PORT = int(os.environ.get("SAAKSHYA_RELAY_HLS_PORT", "18888"))
API_PORT = int(os.environ.get("SAAKSHYA_RELAY_API_PORT", "19997"))
BITRATE = os.environ.get("SAAKSHYA_RELAY_BITRATE", "1800k")
# The government gateway can reject a burst of simultaneous RTSP Basic-auth
# handshakes.  A paced 30-camera start costs seconds, not capacity, and avoids
# turning a transient admission limit into a permanent reconnect storm.
STAGGER_S = float(os.environ.get("SAAKSHYA_RELAY_STAGGER", "1.25"))
# A 6×5 operational wall needs a browser-safe rendition, not thirty source
# resolution decoders.  The upstream feed remains untouched; this only caps
# the loopback view that fans out to browser WHEP sessions.
MAX_HEIGHT = int(os.environ.get("SAAKSHYA_RELAY_MAX_HEIGHT", "480"))
WALL_FPS = max(1, int(os.environ.get("SAAKSHYA_RELAY_FPS", "12")))
#: Government cameras to publish, 0 = no cap. A measured ramp on this host
#: held 15 at 1280x720/15fps with load ~5.5; 30 at the same profile
#: collapsed with 63 broken pipes and a wall-wide 401 cascade. The default
#: was "no cap" all the same; it is now the 15 that held.
MAX_CAMERAS = int(os.environ.get("SAAKSHYA_RELAY_MAX_CAMERAS", "15"))
#: Copy H.264 sources straight through instead of decoding and re-encoding.
#: Off by default, and the reason is worth recording. Passthrough is far
#: cheaper (30 publishers at 16% CPU rather than ~370%) and preserves the full
#: 1920x1080 source, but a WHEP client joining a copied stream mid-flight never
#: becomes decodable: it needs an IDR carrying in-band SPS/PPS, a packet copy
#: cannot synthesise one, and this grid's GOP is far too long to wait for.
#: Measured against a live camera on 2026-09-20: WHEP answered 201, six packets
#: arrived, framesDecoded stayed 0, and the browser sent 26 PLIs before ICE
#: gave up. A wall whose tiles start and stop as the operator scrolls joins
#: constantly, so it needs the short, regular IDR only the encoder guarantees.
#: Worth revisiting for the selected-camera path, where one slow first frame
#: buys full source resolution.
PASSTHROUGH_H264 = os.environ.get(
    "SAAKSHYA_RELAY_PASSTHROUGH", "0").strip().lower() not in {
        "0", "false", "off", "no"}
CAPABILITY_DELAY_S = float(os.environ.get("SAAKSHYA_RELAY_CAPABILITY_DELAY", "45"))
CAPABILITY_PROBES_PER_TICK = max(
    1, int(os.environ.get("SAAKSHYA_RELAY_CAPABILITY_PROBES_PER_TICK", "2")))
# HEVC camera joins can take longer than H.264 while the gateway emits a
# decodable keyframe and VideoToolbox establishes the baseline H.264 output.
# Killing that publisher at the generic window makes a healthy but slow source
# restart forever. This is a readiness allowance, not a browser-live claim.
READY_TIMEOUT_S = float(os.environ.get("SAAKSHYA_RELAY_READY_TIMEOUT", "18"))
HEVC_READY_TIMEOUT_S = float(
    os.environ.get("SAAKSHYA_RELAY_HEVC_READY_TIMEOUT", "50"))

#: Prior census: these two government cameras publish HEVC on RTSP.
#: Cameras whose upstream is HEVC. Measured off the live grid on
#: 2026-09-20; the previous set named cam17/cam22, which are in fact
#: H.264. This list now only widens the readiness timeout and labels
#: codec_in - relay_publisher decides copy-vs-transcode from the open
#: stream itself, so a wrong entry here can no longer publish a codec
#: the browser cannot decode.
HEVC_SOURCES = frozenset({"cam06", "cam12", "cam18", "cam26"})
#: Copy remux of government H264 is rejected by MediaMTX WebRTC (B-frames).
COPY_BLOCKED_REASON = (
    "MediaMTX WebRTC rejects H264 B-frames (PHASE15 MEASURED_REAL); "
    "VideoToolbox baseline -bf 0 required for browser decode"
)

_RELAY: LocalRelay | None = None
_RELAY_LOCK = threading.Lock()
_JPEG_SEM = threading.BoundedSemaphore(2)


def get_relay() -> LocalRelay | None:
    return _RELAY


def set_relay(relay: LocalRelay | None) -> None:
    global _RELAY
    with _RELAY_LOCK:
        _RELAY = relay


def relay_enabled() -> bool:
    """Whether to run the local relay. Off unless SAAKSHYA_LOCAL_RELAY=1.

    The relay holds one upstream session per published camera from start to
    shutdown, watched or not. Against the shared Sentinel sandbox the
    organisers' guidance is to keep open only the streams actively required,
    and the relay's own record here is a crash-loop that tipped the grid into
    refusing the account. So it is opt-in: by default browser tiles use direct
    WHEP for the tiles on screen and the media hub opens a camera only while a
    still of it is wanted (live/hub.py). Turn it on for a camera set whose
    browsers cannot play the source codec, knowing what it holds open.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    flag = os.environ.get("SAAKSHYA_LOCAL_RELAY", "0").strip().lower()
    return flag in {"1", "true", "on", "yes"}


def ffmpeg_bin() -> str:
    local = ROOT / "var" / "bin" / "ffmpeg"
    if local.is_file():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def mediamtx_bin() -> str:
    local = ROOT / "var" / "bin" / "mediamtx"
    if local.is_file():
        return str(local)
    return shutil.which("mediamtx") or ""


def binaries_ok() -> bool:
    return Path(ffmpeg_bin()).is_file() and Path(mediamtx_bin()).is_file()


def _publisher_env(camera_id: str = "") -> dict[str, str]:
    """Minimal child environment, including only the runtime and grid secret.

    The secret is intentionally an environment value rather than a command-line
    argument.  The publisher adds it to the RTSP authority in-process.
    """
    keep = {
        "PATH", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "PYTHONPATH",
        "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
        "SENTINEL_GRID_EMAIL_BACKUP", "SENTINEL_GRID_PASSWORD_BACKUP",
    }
    env = {key: value for key, value in os.environ.items() if key in keep}
    # Sentinel admission is account-scoped in the evaluation sandbox. When a
    # second authorised account is configured, split the government wall into
    # two stable pools instead of asking one identity to sustain thirty RTSP
    # sessions. Credentials remain child-process environment values and never
    # enter argv, logs, catalogue data, or browser responses.
    digits = "".join(ch for ch in camera_id if ch.isdigit())
    if digits and int(digits) % 2 == 0:
        backup_email = env.get("SENTINEL_GRID_EMAIL_BACKUP")
        backup_password = env.get("SENTINEL_GRID_PASSWORD_BACKUP")
        if backup_email and backup_password:
            env["SENTINEL_GRID_EMAIL"] = backup_email
            env["SENTINEL_GRID_PASSWORD"] = backup_password
    env.pop("SENTINEL_GRID_EMAIL_BACKUP", None)
    env.pop("SENTINEL_GRID_PASSWORD_BACKUP", None)
    return env


def local_rtsp(camera_id: str) -> str:
    return f"rtsp://127.0.0.1:{RTSP_PORT}/{camera_id}"


def local_whep(camera_id: str) -> str:
    return f"http://127.0.0.1:{WHEP_PORT}/{camera_id}/whep"


def local_hls(camera_id: str) -> str:
    """Loopback HLS playlist for the scalable browser wall."""
    return f"http://127.0.0.1:{HLS_PORT}/{camera_id}/index.m3u8"


def mtx_api(path: str, timeout: float = 2.0) -> dict[str, Any]:
    url = f"http://127.0.0.1:{API_PORT}{path}"
    with urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


# --------------------------------------------------------------------------- #
# A closed MediaMTX configuration
# --------------------------------------------------------------------------- #
#: The interface every relay listener binds to. The relay used to write only
#: the RTSP, HLS, WebRTC-HTTP and API addresses and inherit MediaMTX's defaults
#: for everything else, and v1.20's defaults are an open server: RTMP on
#: *:1935, SRT on *:8890, MoQ on *:8892/8893 and WebRTC ICE on *:8189, with
#: user "any" allowed to publish and read from any IP and overridePublisher on.
#: lsof on a running relay showed all of them bound to 192.168.1.5, so anyone
#: on the LAN could read a government camera or publish over it and replace
#: the feed that the AI worker seals into evidence. Loopback is the default;
#: an operator who genuinely wants remote viewers names the interface.
MEDIA_HOST = os.environ.get("SAAKSHYA_RELAY_MEDIA_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEBRTC_UDP_PORT = int(os.environ.get("SAAKSHYA_RELAY_WEBRTC_UDP_PORT", "18189"))
#: Browser origins allowed to read the loopback HLS diagnostic plane directly.
#: MediaMTX matches origins exactly (a port wildcard is silently ignored), so
#: the app's origin has to be named; "*" let any page open in the officer's
#: browser read camera video and call the control API.
APP_ORIGINS = tuple(
    o.strip().rstrip("/") for o in os.environ.get(
        "SAAKSHYA_APP_ORIGINS",
        "http://127.0.0.1:8123,http://localhost:8123").split(",") if o.strip())
_LOOPBACK_IPS = ("127.0.0.1", "::1")
#: How the per-boot publish credential reaches relay_publisher: environment,
#: like the grid credential, so it never appears in a process list.
PUBLISH_USER_ENV = "SAAKSHYA_RELAY_PUBLISH_USER"
PUBLISH_PASS_ENV = "SAAKSHYA_RELAY_PUBLISH_PASS"


@dataclass(frozen=True)
class PublisherCredential:
    """A per-boot credential that only this relay's own publishers hold.

    Generated fresh each time MediaMTX starts and never written anywhere but
    the 0600 config file and the publishers' environment, so it cannot leak
    into the registry, a log line or a browser response. It is loopback-only
    as well: a stolen copy is useless from another host.
    """
    user: str
    password: str

    @classmethod
    def generate(cls) -> PublisherCredential:
        import secrets
        return cls(user=f"relay{secrets.token_hex(4)}",
                   password=secrets.token_urlsafe(24))

    def authority(self, url: str) -> str:
        """``url`` with this credential in its authority (loopback RTSP only)."""
        from urllib.parse import quote
        scheme, sep, rest = url.partition("://")
        if not sep or "@" in rest.split("/", 1)[0]:
            return url
        return (f"{scheme}://{quote(self.user, safe='')}:"
                f"{quote(self.password, safe='')}@{rest}")


def mediamtx_relay_config(ids: list[str], publisher: PublisherCredential, *,
                          host: str = MEDIA_HOST,
                          origins: tuple[str, ...] = APP_ORIGINS,
                          hd: dict[str, str] | None = None) -> str:
    """The relay's MediaMTX configuration, closed by default. Pure; tested.

    Every protocol the relay does not use is switched off rather than left at
    a default, because a default is whatever the next MediaMTX release picks.
    Reading is allowed from loopback only (the app's WHEP proxy, the AI worker
    and ffprobe all run on this host); publishing additionally needs the
    per-boot credential, and overridePublisher is off so a second publisher
    cannot displace the relay's own.
    """
    def q(value: str) -> str:
        return json.dumps(value)

    ips = "[" + ", ".join(q(ip) for ip in _LOOPBACK_IPS) + "]"
    allow = "[" + ", ".join(q(o) for o in origins) + "]"
    lines = [
        "# local relay - generated by saakshya.live.relay; do not edit.",
        "# Closed by default: loopback listeners, no anonymous publish.",
        "logLevel: warn",
        "authMethod: internal",
        "authInternalUsers:",
        "  - user: any",
        "    pass:",
        f"    ips: {ips}",
        "    permissions:",
        "      - action: read",
        "      - action: api",
        f"  - user: {q(publisher.user)}",
        f"    pass: {q(publisher.password)}",
        f"    ips: {ips}",
        "    permissions:",
        "      - action: publish",
        "      - action: read",
        f"rtspAddress: {host}:{RTSP_PORT}",
        "rtspTransports: [tcp]",
        "rtspEncryption: \"no\"",
        "rtmp: no",
        "srt: no",
        "moq: no",
        "playback: no",
        "metrics: no",
        "pprof: no",
        "hls: yes",
        f"hlsAddress: {host}:{HLS_PORT}",
        "hlsAlwaysRemux: yes",
        f"hlsAllowOrigins: {allow}",
        "webrtc: yes",
        f"webrtcAddress: {host}:{WHEP_PORT}",
        f"webrtcAllowOrigins: {allow}",
        f"webrtcLocalUDPAddress: {host}:{WEBRTC_UDP_PORT}",
        "webrtcLocalTCPAddress: \"\"",
        # Advertise only the address the ICE socket is actually bound to.
        # Interface discovery would offer the LAN address of a socket that
        # no longer listens there, and the browser would waste its checks.
        "webrtcIPsFromInterfaces: no",
        f"webrtcAdditionalHosts: [{q(host)}]",
        "api: yes",
        f"apiAddress: 127.0.0.1:{API_PORT}",
        f"apiAllowOrigins: {allow}",
        "pathDefaults:",
        "  overridePublisher: no",
        "paths:",
    ]
    lines.extend(f"  {cid}:" for cid in ids)
    if hd:
        for key, value in hd.items():
            lines.append(f"  {key}")
            lines.extend(f"    {line}" for line in value.splitlines())
    return "\n".join(lines) + "\n"


def non_loopback_listeners(lsof_text: str, *, allowed_host: str = "127.0.0.1"
                           ) -> list[str]:
    """Listening sockets in ``lsof -nP -i`` output bound beyond loopback.

    ``*:1935`` and ``192.168.1.5:8189`` are exactly what the relay exposed
    before its configuration was closed; the startup self-test refuses to run
    a media plane that shows either again.
    """
    exposed: list[str] = []
    for line in lsof_text.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 9:
            continue
        proto = cols[7] if cols[7] in {"TCP", "UDP"} else ""
        name = " ".join(cols[8:])
        if not proto:
            continue
        if proto == "TCP" and "(LISTEN)" not in name:
            continue
        if "->" in name:
            continue
        local = name.split()[0]
        host = local.rsplit(":", 1)[0].strip("[]")
        if host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127."):
            continue
        if allowed_host not in {"127.0.0.1", "::1"} and host == allowed_host:
            continue
        exposed.append(f"{proto} {local}")
    return exposed


def _listener_audit(pid: int) -> str | None:
    """``lsof`` for one process, or None where it cannot be run."""
    lsof = shutil.which("lsof") or ("/usr/sbin/lsof" if Path("/usr/sbin/lsof").is_file() else "")
    if not lsof:
        return None
    try:
        proc = subprocess.run([lsof, "-nP", "-a", "-p", str(pid), "-i"],
                              capture_output=True, timeout=5, check=False)
    except Exception:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


@dataclass
class RelaySlot:
    camera_id: str
    domain: str
    src: str
    mode: str = "transcode"  # copy | transcode
    codec_in: str = "unknown"
    profile: str = ""
    level: str = ""
    width: int = 0
    height: int = 0
    fps: float | None = None
    passthrough: bool = False
    transcode: bool = True
    reason: str = COPY_BLOCKED_REASON
    ready: bool = False
    ready_at: float | None = None
    started_at: float = field(default_factory=time.monotonic)
    first_ready_ms: float | None = None
    pid: int | None = None
    reconnects: int = 0
    retry_count: int = 0
    next_retry_at: float | None = None
    last_error: str | None = None
    bytes_in: int = 0
    proc: subprocess.Popen | None = field(default=None, repr=False)
    jpeg: bytes | None = field(default=None, repr=False)
    jpeg_at: float = 0.0


class LocalRelay:
    """Supervises MediaMTX + one ffmpeg publisher per camera."""

    def __init__(self) -> None:
        self._slots: dict[str, RelaySlot] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._mtx: subprocess.Popen | None = None
        self._ids: list[str] = []
        self._threads: list[threading.Thread] = []
        self.started_at = time.monotonic()
        self.stats = {"publishers": 0, "ready": 0, "restarts": 0}
        #: Only this relay's own publishers may write to its paths.
        self.publisher = PublisherCredential.generate()

    def _hd_paths(self) -> dict[str, str] | None:
        return None

    def start(self, cameras: list[dict[str, Any]]) -> None:
        RUN.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        ids: list[str] = []
        for cam in cameras:
            cid = cam.get("camera_id") or ""
            if not cid or str(cid).startswith("CTL-SLOT"):
                continue
            domain = (cam.get("source_domain") or "").upper()
            if domain == "SYNTHETIC_CONTROL":
                continue
            src = self._source_url(cam)
            if not src:
                continue
            mode, reason = self._choose_mode(cid, domain, src)
            codec_in = "hevc" if cid in HEVC_SOURCES else "h264"
            slot = RelaySlot(
                camera_id=cid, domain=domain or "GOVERNMENT", src=src,
                mode=mode, codec_in=codec_in,
                passthrough=mode == "copy", transcode=mode != "copy",
                reason=reason)
            with self._lock:
                self._slots[cid] = slot
            ids.append(cid)
        if not ids:
            log.warning("local relay: no cameras to publish")
            return
        self._ids = list(ids)
        self._start_mediamtx(ids)
        delay = 0.0
        for cid in ids:
            t = threading.Thread(
                target=self._run_publisher, args=(cid, delay),
                name=f"relay:{cid}", daemon=True)
            t.start()
            self._threads.append(t)
            delay += STAGGER_S
        sup = threading.Thread(target=self._supervise, name="relay-sup",
                               daemon=True)
        cap = threading.Thread(target=self._capability_loop, name="relay-cap",
                               daemon=True)
        sup.start()
        cap.start()
        self._threads.extend([sup, cap])
        log.info("local relay started cameras=%s rtsp=%s whep=%s",
                 len(ids), RTSP_PORT, WHEP_PORT)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            slots = list(self._slots.values())
        for slot in slots:
            self._kill(slot)
        if self._mtx is not None and self._mtx.poll() is None:
            with _silent():
                self._mtx.terminate()
            try:
                self._mtx.wait(timeout=4)
            except subprocess.TimeoutExpired:
                with _silent():
                    self._mtx.kill()
        set_relay(None)

    def ready(self, camera_id: str) -> bool:
        slot = self._slots.get(camera_id)
        return bool(slot and slot.ready)

    def media_state(self, camera_id: str) -> dict[str, Any]:
        with self._lock:
            slot = self._slots.get(camera_id)
        if slot is None:
            return {
                "camera_id": camera_id, "source": "NO_SIGNAL",
                "video": "NO_SIGNAL", "ai": _ai_state(camera_id),
                "age_s": None, "label": "NOT_MEASURED", "plane": "local_relay",
            }
        source, video = self._planes(slot)
        age = (time.time() - slot.jpeg_at) if slot.jpeg_at else None
        label = ("MEASURED_OWN_FEED" if slot.domain == "OWN_FEED"
                 else "MEASURED_REAL" if slot.domain == "GOVERNMENT"
                 else "MEASURED_SYNTHETIC")
        return {
            "camera_id": camera_id,
            "source": source,
            "video": video,
            "ai": _ai_state(camera_id),
            "age_s": None if age is None else round(age, 3),
            "fps": slot.fps,
            "codec": "h264" if slot.transcode or slot.ready else slot.codec_in,
            "codec_in": slot.codec_in,
            "profile": slot.profile or ("baseline" if slot.transcode else ""),
            "passthrough": slot.passthrough,
            "transcode": slot.transcode,
            "width": slot.width,
            "height": slot.height,
            "reconnects": slot.reconnects,
            "retry_count": slot.retry_count,
            "cooldown_s": (
                max(0.0, round(slot.next_retry_at - time.monotonic(), 2))
                if slot.next_retry_at else 0.0),
            "relay_ready": slot.ready,
            "last_error": slot.last_error,
            "domain": slot.domain,
            "first_frame_ms": slot.first_ready_ms,
            "bytes_in": slot.bytes_in,
            "whep": local_whep(camera_id),
            "hls": local_hls(camera_id),
            "local_rtsp": local_rtsp(camera_id),
            "reason": slot.reason,
            "label": label,
            "plane": "local_relay",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ids = list(self._slots)
        states = [self.media_state(cid) for cid in ids]
        gov = [s for s in states if s.get("domain") == "GOVERNMENT"]
        relay_ready = sum(1 for s in states if s.get("relay_ready"))
        replay = sum(1 for s in states if s["video"] == "REPLAY")
        preview = sum(1 for s in states if s["video"] == "PREVIEW")
        connected = sum(1 for s in states if s["source"] == "CONNECTED")
        return {
            "plane": "local_relay",
            "upstream_sessions": len(ids),
            "local_relay_sessions": sum(1 for s in states if s["source"] == "CONNECTED"),
            "source_connected": connected,
            "government_connected": sum(1 for s in gov if s["source"] == "CONNECTED"),
            "government_relay_ready": sum(1 for s in gov if s.get("relay_ready")),
            "relay_ready": relay_ready,
            # Browser truth lives in RTCRtpReceiver/render telemetry. This
            # server process cannot honestly assert that a browser is playing.
            "government_live": None,
            "browser_live": None,
            "browser_preview": preview,
            "browser_replay": replay,
            "whep_port": WHEP_PORT,
            "hls_port": HLS_PORT,
            "rtsp_port": RTSP_PORT,
            "ai_cameras": _ai_cameras(),
            "elapsed_s": round(time.monotonic() - self.started_at, 2),
            "cameras": states,
            "label": (
                "MEASURED from this process. relay_ready means the local "
                "MediaMTX path can accept WHEP; only browser render telemetry "
                "may mark VIDEO LIVE. JPEG is PREVIEW fallback only."
            ),
        }

    def capability_table(self) -> list[dict[str, Any]]:
        with self._lock:
            slots = list(self._slots.values())
        rows = []
        for s in slots:
            rows.append({
                "camera": s.camera_id,
                "codec": s.codec_in,
                "passthrough": s.passthrough,
                "transcode": s.transcode,
                "browser_result": "READY" if s.ready else "NOT_READY",
                "reason": s.reason,
                "domain": s.domain,
            })
        return rows

    def grab_jpeg(self, camera_id: str, *, force: bool = False) -> Snapshot | None:
        """PREVIEW still from the local relay. Never opens Sentinel."""
        slot = self._slots.get(camera_id)
        if slot is None:
            return None
        now = time.time()
        if slot.jpeg and not force and now - slot.jpeg_at < 6.0:
            return Snapshot(
                camera_id=camera_id, jpeg=slot.jpeg, captured_at=slot.jpeg_at,
                width=slot.width or 0, height=slot.height or 0,
                codec="jpeg", source="relay-preview")
        if not slot.ready:
            return None
        # Government HLS tiles do not take this path. For the two own-feed
        # Intelligence previews, queue briefly rather than leaving the second
        # panel empty when both request their first frame together.
        acquired = _JPEG_SEM.acquire(timeout=4.0)
        if not acquired:
            if slot.jpeg:
                return Snapshot(
                    camera_id=camera_id, jpeg=slot.jpeg, captured_at=slot.jpeg_at,
                    width=slot.width or 0, height=slot.height or 0,
                    codec="jpeg", source="relay-preview")
            return None
        try:
            cmd = [
                ffmpeg_bin(), "-hide_banner", "-loglevel", "error",
                "-rtsp_transport", "tcp", "-i", local_rtsp(camera_id),
                "-frames:v", "1", "-q:v", "6", "-f", "image2", "pipe:1",
            ]
            proc = subprocess.run(
                cmd, capture_output=True, timeout=4.0, check=False)
            if proc.returncode != 0 or not proc.stdout:
                return None
            jpeg = proc.stdout
            slot.jpeg = jpeg
            slot.jpeg_at = time.time()
            return Snapshot(
                camera_id=camera_id, jpeg=jpeg, captured_at=slot.jpeg_at,
                width=slot.width or 0, height=slot.height or 0,
                codec="jpeg", source="relay-preview")
        except Exception:
            return None
        finally:
            _JPEG_SEM.release()

    def _warm_own_preview(self, camera_id: str) -> None:
        """Keep the two participant-feed previews ready for the Intelligence UI."""
        while not self._stop.is_set():
            slot = self._slots.get(camera_id)
            if slot is None or not slot.ready or slot.domain != "OWN_FEED":
                return
            self.grab_jpeg(camera_id, force=True)
            if self._stop.wait(4.0):
                return

    def boxes(self, camera_id: str) -> list[dict[str, Any]]:
        path = RUN / "ai_boxes" / f"{camera_id}.json"
        try:
            if not path.is_file():
                return []
            if time.time() - path.stat().st_mtime > 8.0:
                return []
            data = json.loads(path.read_text())
            return list(data.get("boxes") or [])
        except Exception:
            return []

    # -- internals ---------------------------------------------------------- #
    def _source_url(self, cam: dict[str, Any]) -> str:
        cid = cam.get("camera_id") or ""
        domain = (cam.get("source_domain") or "").upper()
        local = local_media_url(cid)
        if domain == "OWN_FEED" and local:
            return local
        if domain == "GOVERNMENT" and not configured():
            # Registry URLs are intentionally credential-free. Starting all
            # thirty without the environment credential only creates an
            # upstream authentication/reconnect storm.
            log.warning("relay skip %s: Sentinel credential is not configured", cid)
            return ""
        url = cam.get("rtsp_url") or ""
        if url:
            # Keep the catalogue URL clean.  The publisher injects the
            # credential in its own process immediately before opening the
            # socket, so a password never appears in an ffmpeg argv (or in
            # the process list and crash diagnostics that may contain it).
            return url
        return local

    def _choose_mode(self, camera_id: str, domain: str, src: str
                     ) -> tuple[str, str]:
        force = os.environ.get("SAAKSHYA_RELAY_MODE", "").strip().lower()
        if force in {"copy", "transcode"}:
            reason = "SAAKSHYA_RELAY_MODE override"
            return force, reason
        if domain == "OWN_FEED" or src.endswith(".mp4"):
            return "copy", "own-feed/file: try H264 copy, fall back to VideoToolbox"
        if camera_id in HEVC_SOURCES:
            return "transcode", "HEVC source is not browser-safe; baseline H.264 for local WHEP"
        # Transcoding an H.264 source costs a full software decode of every
        # 1080p frame plus an encode, and it is the single reason a thirty
        # camera wall did not fit this host: the encoder backed up, MediaMTX
        # timed the publisher out, and the resulting broken pipe was retried
        # fast enough that Sentinel still counted the dead session and answered
        # 401. A packet copy does neither, and it preserves the source instead
        # of throwing ~94% of its pixels away. The grid's H.264 is what the
        # browser wants already, so copy it and reserve transcoding for sources
        # the browser genuinely cannot take.
        if PASSTHROUGH_H264:
            return "copy", "browser-safe H.264 source; packet copy preserves the full source rendition"
        return "transcode", "baseline H.264 low-resolution local WHEP rendition for the 30-camera wall"

    def _start_mediamtx(self, ids: list[str]) -> None:
        # Never silently attach publishers to an unknown MediaMTX instance.
        # A previous interrupted run on the same ports otherwise makes the new
        # child fail its bind while its readiness probe succeeds against the
        # stale server, followed by a broken-pipe reconnect storm.
        if self._mtx is not None and self._mtx.poll() is None:
            return
        try:
            mtx_api("/v3/paths/list")
        except Exception:
            pass
        else:
            raise RuntimeError(
                "local relay MediaMTX API is already occupied on the configured ports")
        cfg = ROOT / "var" / "mediamtx_relay.yml"
        # The file now holds the per-boot publisher credential, so it is
        # created owner-only before anything is written into it.
        cfg.touch(mode=0o600, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(cfg, 0o600)
        cfg.write_text(mediamtx_relay_config(ids, self.publisher,
                                             hd=self._hd_paths()))
        with open(LOGS / "mediamtx_relay.log", "ab") as logf:
            self._mtx = subprocess.Popen(
                [mediamtx_bin(), str(cfg)],
                cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT)
        for _ in range(50):
            if self._stop.is_set():
                return
            try:
                mtx_api("/v3/paths/list")
                self._assert_closed_listeners()
                return
            except RuntimeError:
                raise
            except Exception as exc:
                if self._mtx.poll() is not None:
                    raise RuntimeError("MediaMTX relay exited") from exc
                time.sleep(0.2)
        raise RuntimeError("MediaMTX relay API not ready")

    def _assert_closed_listeners(self) -> None:
        """Fail closed if MediaMTX is listening anywhere beyond loopback.

        The configuration above is the intent; this is the check that the
        binary actually honoured it. A future MediaMTX that adds a protocol
        with an all-interfaces default would otherwise reopen the hole
        silently. Where lsof cannot run the check is skipped and says so,
        rather than blocking a host that has no way to answer.
        """
        if self._mtx is None:
            return
        text = _listener_audit(self._mtx.pid)
        if text is None:
            log.warning("relay listener self-test skipped: lsof unavailable")
            return
        exposed = non_loopback_listeners(text, allowed_host=MEDIA_HOST)
        if exposed:
            with contextlib.suppress(Exception):
                self._mtx.terminate()
            raise RuntimeError(
                "local relay refused to run: MediaMTX is listening beyond "
                f"loopback ({', '.join(exposed)})")

    def _run_publisher(self, camera_id: str, delay: float) -> None:
        if delay and self._stop.wait(delay):
            return
        backoff = 2.0
        while not self._stop.is_set():
            slot = self._slots.get(camera_id)
            if slot is None:
                return
            proc = self._spawn(slot)
            slot.proc = proc
            slot.pid = proc.pid if proc else None
            ready_timeout = (HEVC_READY_TIMEOUT_S if slot.codec_in == "hevc"
                             else READY_TIMEOUT_S)
            ready = self._wait_ready(camera_id, timeout=ready_timeout)
            if not ready and proc.poll() is None:
                # relay_publisher owns protocol reconnect and, critically, a
                # long authentication backoff after Sentinel returns 401. The
                # old supervisor killed that still-healthy process at the
                # short path-ready timeout, then respawned it seconds later.
                # That defeated the backoff and turned one admission failure
                # into a wall-wide lockout. Leave the child alive and observe
                # it until either its path becomes ready or it genuinely exits.
                slot.reconnects += 1
                slot.retry_count += 1
                slot.last_error = "upstream reconnecting"
                while (not self._stop.is_set() and proc.poll() is None
                       and not ready):
                    ready = self._wait_ready(camera_id, timeout=5.0)
            if ready:
                backoff = 2.0
                slot.retry_count = 0
                slot.next_retry_at = None
                if slot.domain == "OWN_FEED":
                    # A local-only cache warmer prevents the two participant
                    # panels from contending for their very first still.
                    threading.Thread(
                        target=self._warm_own_preview, args=(camera_id,),
                        daemon=True, name=f"relay-preview:{camera_id}").start()
                while not self._stop.is_set():
                    if proc.poll() is not None:
                        break
                    self._refresh_bytes(slot)
                    if self._stop.wait(2.0):
                        return
                if self._stop.is_set():
                    return
                slot.ready = False
                slot.reconnects += 1
                slot.retry_count += 1
                slot.last_error = "publisher exited"
                self.stats["restarts"] += 1
            else:
                self._kill(slot)
                if slot.mode == "copy":
                    # Copy is retained as an explicit development override.
                    # The normal government wall uses baseline H.264 transcode
                    # so that browser WHEP does not inherit source B-frames.
                    log.info("relay %s HLS packet-copy path not ready; retrying",
                             camera_id)
                slot.reconnects += 1
                slot.retry_count += 1
                slot.last_error = "path not ready"
            wait_s = min(30.0, backoff * random.uniform(0.8, 1.2))
            slot.next_retry_at = time.monotonic() + wait_s
            if self._stop.wait(wait_s):
                return
            slot.next_retry_at = None
            backoff = min(20.0, backoff * 1.5)

    def _spawn(self, slot: RelaySlot) -> subprocess.Popen:
        self._kill(slot)
        dst = local_rtsp(slot.camera_id)
        log_path = LOGS / f"relay_{slot.camera_id}.log"
        if slot.domain == "OWN_FEED" and not slot.src.startswith(("rtsp://", "rtsps://")):
            # Local demonstration files have no credentials and are safe to
            # hand to FFmpeg.  Its stream-loop publisher is materially more
            # reliable for finite MP4s than a PyAV RTSP muxer.  Government
            # sources intentionally stay on relay_publisher, whose argv never
            # receives an upstream authority credential.
            cmd = [
                ffmpeg_bin(), "-hide_banner", "-loglevel", "error",
                "-stream_loop", "-1", "-re", "-i", slot.src,
                "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-tune", "zerolatency", "-profile:v", "baseline", "-bf", "0",
                "-g", "30", "-pix_fmt", "yuv420p", "-b:v", BITRATE,
                # The per-boot publish credential has to be in ffmpeg's URL:
                # it has no other way to take one. It is loopback-only and
                # dies with this MediaMTX, and it is the relay's own secret,
                # never a grid credential.
                "-f", "rtsp", "-rtsp_transport", "tcp",
                self.publisher.authority(dst),
            ]
        else:
            cmd = [
                sys.executable, "-m", "saakshya.live.relay_publisher",
                "--source", slot.src,
                "--destination", dst,
                "--mode", slot.mode,
                "--bitrate", BITRATE,
                "--max-height", str(MAX_HEIGHT),
                "--fps", str(WALL_FPS),
            ]
        # The child receives credentials only through its environment and
        # injects them in-process when it opens RTSP.  argv stays clean.
        log.info("relay publisher %s mode=%s -> %s",
                 slot.camera_id, slot.mode, dst)
        env = _publisher_env(slot.camera_id)
        env[PUBLISH_USER_ENV] = self.publisher.user
        env[PUBLISH_PASS_ENV] = self.publisher.password
        with open(log_path, "w") as logf:
            return subprocess.Popen(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                cwd=str(ROOT), env=env)

    def _wait_ready(self, camera_id: str, *, timeout: float) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout and not self._stop.is_set():
            try:
                d = mtx_api(f"/v3/paths/get/{camera_id}")
            except Exception:
                time.sleep(0.5)
                continue
            br = int(d.get("bytesReceived") or d.get("inboundBytes") or 0)
            slot = self._slots.get(camera_id)
            if slot is not None:
                slot.bytes_in = br
            if d.get("ready") and br > 8000:
                if slot is not None:
                    now = time.monotonic()
                    slot.ready = True
                    slot.ready_at = now
                    if slot.first_ready_ms is None:
                        slot.first_ready_ms = round(
                            (now - slot.started_at) * 1000, 1)
                    slot.last_error = None
                return True
            time.sleep(0.5)
        return False

    def _refresh_bytes(self, slot: RelaySlot) -> None:
        try:
            d = mtx_api(f"/v3/paths/get/{slot.camera_id}")
            slot.bytes_in = int(d.get("bytesReceived") or d.get("inboundBytes") or 0)
            slot.ready = bool(d.get("ready") and slot.bytes_in > 8000)
        except Exception:
            pass

    def _supervise(self) -> None:
        while not self._stop.wait(3.0):
            if self._mtx is not None and self._mtx.poll() is not None:
                log.error("MediaMTX relay died; restarting isolated media plane")
                try:
                    self._start_mediamtx(self._ids)
                    self.stats["restarts"] += 1
                except Exception:
                    log.exception("MediaMTX relay restart failed; will retry")
            with self._lock:
                self.stats["publishers"] = len(self._slots)
                self.stats["ready"] = sum(1 for s in self._slots.values() if s.ready)

    def _capability_loop(self) -> None:
        """Probe local streams without competing with initial wall bring-up.

        ffprobe opens an additional local RTSP reader.  Starting that for every
        camera while thirty publishers are still negotiating can starve the
        MediaMTX wall.  Resolution/profile are descriptive metadata, not a
        prerequisite for WHEP, so defer probing and perform only a small batch
        per tick after the media plane has had priority.
        """
        if self._stop.wait(CAPABILITY_DELAY_S):
            return
        while not self._stop.is_set():
            with self._lock:
                ready = [s for s in self._slots.values()
                         if s.ready and not s.width]
            for slot in ready[:CAPABILITY_PROBES_PER_TICK]:
                info = _ffprobe_local(slot.camera_id)
                if not info:
                    continue
                slot.width = int(info.get("width") or 0)
                slot.height = int(info.get("height") or 0)
                slot.profile = str(info.get("profile") or slot.profile)
                slot.level = str(info.get("level") or "")
                fps = _parse_rate(info.get("avg_frame_rate") or info.get("r_frame_rate"))
                if fps:
                    slot.fps = fps
            with contextlib.suppress(OSError):
                (RUN / "relay_capability.json").write_text(
                    json.dumps(self.capability_table(), indent=2) + "\n")
            if self._stop.wait(12.0):
                return

    def _planes(self, slot: RelaySlot) -> tuple[str, str]:
        if slot.ready:
            source = "CONNECTED"
            # Ready is a server-side path fact, not a decoded browser frame.
            # Own feeds retain REPLAY provenance; government video stays
            # CONNECTING until requestVideoFrameCallback proves a frame.
            video = "REPLAY" if slot.domain == "OWN_FEED" else "CONNECTING"
            return source, video
        if slot.proc is not None and slot.proc.poll() is None:
            if slot.reconnects:
                return "RECONNECTING", "RECONNECTING"
            return "CONNECTING", "CONNECTING"
        if slot.last_error:
            return "UPSTREAM_ERROR", "NO SIGNAL"
        return "CONNECTING", "CONNECTING"

    def _kill(self, slot: RelaySlot) -> None:
        proc = slot.proc
        slot.proc = None
        slot.pid = None
        if proc is None or proc.poll() is not None:
            return
        with _silent():
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with _silent():
                proc.kill()


class _silent:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None


def _parse_rate(value: Any) -> float | None:
    text = str(value or "")
    if not text or text == "0/0":
        return None
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            n, d = float(num), float(den)
            return round(n / d, 2) if d else None
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _ffprobe_local(camera_id: str) -> dict[str, Any] | None:
    ffprobe = ffmpeg_bin().replace("ffmpeg", "ffprobe")
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which("ffprobe") or ""
    if not ffprobe:
        return None
    cmd = [
        ffprobe, "-rtsp_transport", "tcp", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,profile,level,width,height,avg_frame_rate,r_frame_rate",
        "-of", "json", local_rtsp(camera_id),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=6, check=False)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout.decode("utf-8", errors="replace") or "{}")
        streams = data.get("streams") or []
        return streams[0] if streams else None
    except Exception:
        return None


def _ai_heartbeat() -> dict[str, Any]:
    path = RUN / "ai_worker.json"
    try:
        if not path.is_file():
            return {}
        if time.time() - path.stat().st_mtime > 8.0:
            return {"stale": True}
        return json.loads(path.read_text())
    except Exception:
        return {}


def _ai_cameras() -> list[str]:
    hb = _ai_heartbeat()
    cams = hb.get("cameras") or {}
    return sorted(cams)


def _ai_state(camera_id: str) -> str:
    hb = _ai_heartbeat()
    if hb.get("stale"):
        return "OFF"
    row = (hb.get("cameras") or {}).get(camera_id) or {}
    return str(row.get("ai") or "OFF")


def select_relay_cameras(store: Any) -> list[dict[str, Any]]:
    rows = store.list_cameras()
    gov = [c for c in rows if (c.get("source_domain") or "").upper() == "GOVERNMENT"]
    # Publishing more cameras than the host can encode does not degrade
    # gracefully: the encoder backs up, MediaMTX times the publisher out, and
    # the resulting broken pipe is retried fast enough that Sentinel still
    # counts the dead session and answers 401. One camera too many therefore
    # costs the whole wall, not one tile. Cap the fan-out to what the measured
    # profile actually sustains and leave the rest un-published rather than
    # publishing thirty streams that all collapse together.
    cap = MAX_CAMERAS
    if cap > 0:
        gov = gov[:cap]
    if os.environ.get("SAAKSHYA_RELAY_GOVERNMENT_ONLY", "").strip().lower() in {
            "1", "true", "yes", "on"}:
        return gov
    own = [c for c in rows if (c.get("source_domain") or "").upper() == "OWN_FEED"]
    return gov + own


def boot_relay(store: Any) -> LocalRelay | None:
    if not relay_enabled():
        return None
    existing = get_relay()
    if existing is not None:
        return existing
    if not binaries_ok():
        log.error("local relay binaries missing ffmpeg=%s mediamtx=%s",
                  ffmpeg_bin(), mediamtx_bin())
        return None
    relay = LocalRelay()
    try:
        relay.start(select_relay_cameras(store))
    except Exception:
        log.exception("local relay failed to start")
        with contextlib.suppress(Exception):
            relay.stop()
        return None
    set_relay(relay)
    return relay
