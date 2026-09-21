"""Catalog and port config for the archival-replay demo simulation.

The catalog reuses four repeated four-minute archival clips (C-014, C-033,
C-052, C-061) across the 30-camera demo fleet; it is not unique 12-hour
footage per camera. No network services are started by this module.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

log = logging.getLogger("saakshya.live.simulation")

ROOT = Path(__file__).resolve().parents[3]
VAR = ROOT / "var"
LOGS = VAR / "logs"

SOURCE_DOMAIN = "ARCHIVAL_REPLAY"
MEDIA_MODE = "LIVE_SIMULATION_LOOPED"
DEMO_LABEL = "LIVE SIMULATION / ARCHIVAL REPLAY"
MEDIA_STATUS = "LOOPED_4M_ASSET_NOT_12H_UNIQUE"

#: Explicit "we have not measured this" marker. The catalog is an archival
#: replay definition, not a claim that analytics/ANPR ran against any of
#: these cameras — that only becomes true once a real worker attaches.
NOT_MEASURED = "NOT_MEASURED"

#: The catalog defines a fixed 12-hour VIRTUAL replay window; the underlying
#: asset is a 240s clip looped for that window, not 12 hours of unique footage.
REPLAY_WINDOW_S = 12 * 60 * 60
ASSET_DURATION_S = 240
LOOP_PERIOD_S = 240

_ASSETS = ["C-014.mp4", "C-033.mp4", "C-052.mp4", "C-061.mp4"]

# Per-asset technical metadata for the repeated four-minute demo segments.
# These are looped archival clips, not unique 12-hour live footage.
_ASSET_METADATA = {
    "C-014.mp4": {"width": 1280, "height": 720, "fps": 15},
    "C-033.mp4": {"width": 640, "height": 480, "fps": 10},
    "C-052.mp4": {"width": 960, "height": 540, "fps": 8},
    "C-061.mp4": {"width": 1280, "height": 720, "fps": 15},
}

_DEPARTMENTS = ["Health", "Police", "GSRTC", "Panchayat", "Municipal"]
_CITIES = ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar", "Bhavnagar"]


def catalog() -> list[dict]:
    """Return the 30-camera CAM-001..CAM-030 demo catalog."""
    cameras = []
    for i in range(1, 31):
        camera_id = f"CAM-{i:03d}"
        asset = _ASSETS[(i - 1) % len(_ASSETS)]
        city = _CITIES[(i - 1) % len(_CITIES)]
        department = _DEPARTMENTS[(i - 1) % len(_DEPARTMENTS)]
        meta = _ASSET_METADATA[asset]
        cameras.append({
            "camera_id": camera_id,
            "display_name": f"{city} Junction {i:02d}",
            "department": department,
            "city": city,
            "location": f"{city} Junction {i:02d}",
            "latitude": 23.0 + i * 0.01,
            "longitude": 72.5 + i * 0.01,
            "source_domain": SOURCE_DOMAIN,
            "media_mode": MEDIA_MODE,
            "codec": "h264",
            "width": meta["width"],
            "height": meta["height"],
            "source_fps": meta["fps"],
            # Catalog is inactive (no publisher running); no measured fps exists.
            "current_fps": None,
            "replay_start": 0,
            "replay_end": REPLAY_WINDOW_S,
            "asset_duration_s": ASSET_DURATION_S,
            "loop_period_s": LOOP_PERIOD_S,
            "loop_enabled": True,
            # Archival replay channel: no analytics/ANPR worker has measured
            # these cameras yet, so capability is explicitly unmeasured
            # rather than assumed True/False.
            "analytics_capability": NOT_MEASURED,
            "anpr_capability": NOT_MEASURED,
            "ai_enabled": False,
            "priority": "HIGH" if i <= 10 else "STANDARD",
            "media_status": MEDIA_STATUS,
            "media_path": f"var/media/{asset}",
            "demo_label": DEMO_LABEL,
        })
    return cameras


def validate_catalog(rows: list[dict[str, Any]]) -> None:
    """Validate rows before any process is spawned. Pure/testable, no IO side effects.

    Requires exactly 30 unique CAM-001..CAM-030 rows, each declared as an
    archival-replay looped-simulation source whose media file is an approved
    baseline asset that actually exists under the workspace. Raises
    ``RuntimeError`` with a clear message on the first violation found.
    """
    if len(rows) != 30:
        raise RuntimeError(
            f"simulation catalog must have exactly 30 cameras, got {len(rows)}")
    ids = [row.get("camera_id") for row in rows]
    if len(set(ids)) != len(ids):
        raise RuntimeError("simulation catalog has duplicate camera_id values")
    expected_ids = {f"CAM-{i:03d}" for i in range(1, 31)}
    if set(ids) != expected_ids:
        raise RuntimeError(
            "simulation catalog camera_id set must be exactly "
            f"CAM-001..CAM-030, got {sorted(set(ids))}")
    for row in rows:
        cid = row.get("camera_id")
        if row.get("source_domain") != SOURCE_DOMAIN:
            raise RuntimeError(
                f"{cid}: source_domain must be {SOURCE_DOMAIN!r}, "
                f"got {row.get('source_domain')!r}")
        if row.get("media_mode") != MEDIA_MODE:
            raise RuntimeError(
                f"{cid}: media_mode must be {MEDIA_MODE!r}, "
                f"got {row.get('media_mode')!r}")
        media_path = row.get("media_path") or ""
        asset_name = media_path.rsplit("/", 1)[-1]
        if asset_name not in _ASSETS:
            raise RuntimeError(
                f"{cid}: media asset {asset_name!r} is not an approved "
                f"baseline asset ({sorted(_ASSETS)})")
        resolved = (ROOT / media_path).resolve()
        root_resolved = ROOT.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise RuntimeError(
                f"{cid}: media path {media_path!r} resolves outside the workspace root")
        if not resolved.is_file():
            raise RuntimeError(
                f"{cid}: media file not found under workspace at {media_path!r}")


@dataclass(frozen=True)
class SimulationPorts:
    rtsp_port: int = 28554
    whep_port: int = 28889
    api_port: int = 29997
    webrtc_udp_port: int = 28890
    webrtc_tcp_port: int = 28891

    def __post_init__(self) -> None:
        ports = (
            self.rtsp_port, self.whep_port, self.api_port,
            self.webrtc_udp_port, self.webrtc_tcp_port,
        )
        if any(p <= 0 for p in ports):
            raise ValueError(f"simulation ports must be positive, got {ports}")
        if len(set(ports)) != len(ports):
            raise ValueError(f"simulation ports must be distinct, got {ports}")

    @classmethod
    def from_env(cls) -> "SimulationPorts":
        return cls(
            rtsp_port=int(os.environ.get("SAAKSHYA_SIMULATION_RTSP_PORT", "28554")),
            whep_port=int(os.environ.get("SAAKSHYA_SIMULATION_WHEP_PORT", "28889")),
            api_port=int(os.environ.get("SAAKSHYA_SIMULATION_API_PORT", "29997")),
            webrtc_udp_port=int(
                os.environ.get("SAAKSHYA_SIMULATION_WEBRTC_UDP_PORT", "28890")),
            webrtc_tcp_port=int(
                os.environ.get("SAAKSHYA_SIMULATION_WEBRTC_TCP_PORT", "28891")),
        )


def simulation_ffmpeg_bin() -> str:
    local = VAR / "bin" / "ffmpeg"
    if local.is_file():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    return ""


def simulation_mediamtx_bin() -> str:
    local = VAR / "bin" / "mediamtx"
    if local.is_file():
        return str(local)
    return shutil.which("mediamtx") or ""


def simulation_binaries_ok() -> bool:
    return bool(simulation_ffmpeg_bin()) and bool(simulation_mediamtx_bin())


@dataclass
class _SimulationSlot:
    camera_id: str
    media_path: str
    proc: subprocess.Popen | None = None
    ready: bool = False


class SimulationRelay:
    """Opt-in dedicated demo media plane: one ffmpeg publisher per catalog row.

    Import-safe: nothing here runs at import time. Only ``start()`` spawns
    MediaMTX or ffmpeg processes, and only processes this instance itself
    spawned are ever terminated by ``stop()``.
    """

    def __init__(self, ports: SimulationPorts | None = None) -> None:
        self.ports = ports or SimulationPorts.from_env()
        self._slots: dict[str, _SimulationSlot] = {}
        self._lock = threading.RLock()
        self._mtx: subprocess.Popen | None = None
        self.started_at: float | None = None
        self._started = False

    # -- pure helpers (import-safe, no process/IO side effects) ------------- #
    def publisher_command(self, row: dict[str, Any]) -> list[str]:
        """Build the ffmpeg command for a single catalog row. Pure/testable."""
        camera_id = row["camera_id"]
        media_path = row["media_path"]
        ff = simulation_ffmpeg_bin() or "ffmpeg"
        dst = self.local_rtsp(camera_id)
        return [
            ff, "-hide_banner", "-loglevel", "warning",
            "-re", "-stream_loop", "-1", "-i", media_path,
            "-an", "-c:v", "copy",
            "-f", "rtsp", "-rtsp_transport", "tcp", dst,
        ]

    def local_rtsp(self, camera_id: str) -> str:
        return f"rtsp://127.0.0.1:{self.ports.rtsp_port}/{camera_id}"

    def local_whep(self, camera_id: str) -> str:
        return f"http://127.0.0.1:{self.ports.whep_port}/{camera_id}/whep"

    def ready(self, camera_id: str) -> bool:
        with self._lock:
            slot = self._slots.get(camera_id)
        return bool(slot and slot.ready)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            slots = dict(self._slots)
        ready_count = sum(1 for s in slots.values() if s.ready)
        # publisher_count reflects only ffmpeg subprocesses this relay owns
        # that are still alive; stopped/never-started slots do not count.
        publisher_count = sum(
            1 for s in slots.values() if s.proc is not None and s.proc.poll() is None)
        cameras = []
        for row in catalog():
            cid = row["camera_id"]
            slot = slots.get(cid)
            if slot is not None:
                cameras.append({
                    "camera_id": cid,
                    "ready": slot.ready,
                    # No frame-rate probe/measurement exists; never fabricate
                    # current_fps from the declared source_fps.
                    "current_fps": None,
                    "media_path": slot.media_path,
                    "media_status": MEDIA_STATUS,
                })
            else:
                cameras.append({
                    "camera_id": cid,
                    "ready": False,
                    "current_fps": None,
                    "media_path": row["media_path"],
                    "media_status": MEDIA_STATUS,
                })
        return {
            "label": DEMO_LABEL,
            "source_domain": SOURCE_DOMAIN,
            "media_mode": MEDIA_MODE,
            "media_status": MEDIA_STATUS,
            "replay_start": 0,
            "replay_end": REPLAY_WINDOW_S,
            "asset_duration_s": ASSET_DURATION_S,
            "loop_period_s": LOOP_PERIOD_S,
            "started": self._started,
            "browser_live": None,
            "publisher_count": publisher_count,
            "configured_channel_count": len(slots),
            "ready_count": ready_count,
            "catalog_count": len(cameras),
            "elapsed_s": (
                round(time.monotonic() - self.started_at, 2)
                if self.started_at is not None else None
            ),
            "cameras": cameras,
        }

    # -- lifecycle (only entered when start() is explicitly called) --------- #
    def start(self, rows: list[dict[str, Any]] | None = None) -> None:
        if self._started:
            return
        if not simulation_binaries_ok():
            raise RuntimeError(
                "simulation binaries unavailable: need var/bin/ffmpeg and "
                "var/bin/mediamtx (or on PATH)")
        rows = rows if rows is not None else catalog()
        validate_catalog(rows)
        VAR.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for row in rows:
                cid = row["camera_id"]
                self._slots[cid] = _SimulationSlot(
                    camera_id=cid, media_path=row["media_path"])
        try:
            self._start_mediamtx(list(self._slots))
            for cid, slot in list(self._slots.items()):
                row = next(r for r in rows if r["camera_id"] == cid)
                cmd = self.publisher_command(row)
                log_path = LOGS / f"simulation_{cid}.log"
                with open(log_path, "w") as logf:
                    slot.proc = subprocess.Popen(
                        cmd, stdout=logf, stderr=subprocess.STDOUT)
            self.started_at = time.monotonic()
            self._started = True
            self._wait_ready(timeout=20.0)
        except Exception:
            self._teardown_failed_start()
            raise

    def _teardown_failed_start(self) -> None:
        """Undo a start() attempt that raised partway through.

        Stops only the Popen instances this relay itself spawned, leaves
        ``_started`` false, and keeps the catalog queryable via snapshot().
        """
        with self._lock:
            slots = list(self._slots.values())
            self._slots = {}
        for slot in slots:
            self._kill(slot)
        self._stop_mtx()
        self._started = False
        self.started_at = None

    def stop(self) -> None:
        with self._lock:
            slots = list(self._slots.values())
        for slot in slots:
            self._kill(slot)
        self._stop_mtx()
        self._started = False
        if get_simulation() is self:
            set_simulation(None)

    def _stop_mtx(self) -> None:
        if self._mtx is not None and self._mtx.poll() is None:
            try:
                self._mtx.terminate()
                self._mtx.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self._mtx.kill()
        self._mtx = None

    def _kill(self, slot: _SimulationSlot) -> None:
        proc = slot.proc
        slot.proc = None
        slot.ready = False
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    def config_text(self, camera_ids: list[str]) -> str:
        """Build the MediaMTX YAML config text for this relay. Pure/testable."""
        paths = "\n".join(f"  {cid}:" for cid in camera_ids)
        return (
            "# dedicated simulation media plane — CAM-001..CAM-030 only\n"
            "logLevel: warn\n"
            f"rtspAddress: :{self.ports.rtsp_port}\n"
            "rtspTransports: [tcp]\n"
            "rtmp: no\n"
            "hls: no\n"
            "srt: no\n"
            "moq: no\n"
            "playback: no\n"
            "metrics: no\n"
            "pprof: no\n"
            f"webrtcAddress: :{self.ports.whep_port}\n"
            "webrtcAllowOrigins: [\"*\"]\n"
            f"webrtcLocalUDPAddress: :{self.ports.webrtc_udp_port}\n"
            f"webrtcLocalTCPAddress: :{self.ports.webrtc_tcp_port}\n"
            "api: yes\n"
            f"apiAddress: 127.0.0.1:{self.ports.api_port}\n"
            "apiAllowOrigins: [\"*\"]\n"
            "paths:\n"
            f"{paths}\n"
        )

    def _start_mediamtx(self, camera_ids: list[str]) -> None:
        cfg = VAR / "mediamtx_simulation.yml"
        cfg.write_text(self.config_text(camera_ids))
        mtx = simulation_mediamtx_bin()
        if not mtx:
            raise RuntimeError("simulation MediaMTX binary unavailable")
        with open(LOGS / "mediamtx_simulation.log", "ab") as logf:
            self._mtx = subprocess.Popen(
                [mtx, str(cfg)], cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 10.0:
            try:
                self._mtx_api("/v3/paths/list")
                return
            except Exception as exc:
                if self._mtx.poll() is not None:
                    raise RuntimeError("simulation MediaMTX exited") from exc
                time.sleep(0.2)
        raise RuntimeError("simulation MediaMTX API not ready")

    def _mtx_api(self, path: str, timeout: float = 2.0) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.ports.api_port}{path}"
        with urlopen(url, timeout=timeout) as resp:
            return json.load(resp)

    def _wait_ready(self, *, timeout: float) -> None:
        t0 = time.monotonic()
        with self._lock:
            pending = list(self._slots.values())
        while time.monotonic() - t0 < timeout and pending:
            still_pending = []
            for slot in pending:
                try:
                    d = self._mtx_api(f"/v3/paths/get/{slot.camera_id}")
                except Exception:
                    still_pending.append(slot)
                    continue
                if d.get("ready") and self._has_inbound_bytes(d):
                    slot.ready = True
                else:
                    still_pending.append(slot)
            pending = still_pending
            if pending:
                time.sleep(0.3)

    @staticmethod
    def _has_inbound_bytes(path_info: dict[str, Any]) -> bool:
        """True only once MediaMTX reports both readiness and real inbound
        bytes — configuration-path existence alone is not readiness."""
        for key in ("bytesReceived", "inboundBytes"):
            value = path_info.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return True
        source = path_info.get("source")
        if isinstance(source, dict):
            for key in ("bytesReceived", "inboundBytes"):
                value = source.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    return True
        return False


_SIMULATION: SimulationRelay | None = None
_SIMULATION_LOCK = threading.Lock()


def get_simulation() -> SimulationRelay | None:
    return _SIMULATION


def set_simulation(simulation: SimulationRelay | None) -> None:
    global _SIMULATION
    with _SIMULATION_LOCK:
        _SIMULATION = simulation


def simulation_enabled() -> bool:
    """Opt-in only. Never runs under pytest and never auto-starts on import."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    flag = os.environ.get("SAAKSHYA_DEMO_SIMULATION", "0").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def boot_simulation() -> SimulationRelay | None:
    """Start the isolated 30-channel archival replay plane, opt-in only.

    Never touches the primary store, the government relay or the media hub —
    this is a dedicated demo plane on its own ports. Returns None whenever the
    feature is disabled, already running, or fails to start; failures clean up
    only the instance this call itself created.
    """
    if not simulation_enabled():
        return None
    existing = get_simulation()
    if existing is not None:
        return existing
    relay = SimulationRelay()
    try:
        relay.start()
    except Exception:
        log.exception("demo simulation failed to start")
        with contextlib.suppress(Exception):
            relay.stop()
        return None
    set_simulation(relay)
    return relay
