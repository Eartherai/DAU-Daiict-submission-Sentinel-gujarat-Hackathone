"""One upstream ingest per camera, local fan-out to wall / AI / snapshots.

Browser tiles must not open independent Sentinel WHEP sessions. Each government
camera gets one RTSP/TCP worker. Decoded frames are:

* JPEG-encoded in memory (latest-frame-wins) for every browser subscriber
* optionally analysed by a bounded AI consumer
* never written to SQLite on the media path

LIVE means a hub frame younger than LIVE_AGE_S from a streaming ingest.
A still older than that is PREVIEW. A still is never stamped LIVE.
"""
from __future__ import annotations

import io
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from saakshya.ingest.frame import Frame
from saakshya.ingest.stream import StreamConfig, StreamManager
from saakshya.live.snapshot import Snapshot, local_media_url

log = logging.getLogger("saakshya.live.hub")

LIVE_AGE_S = 4.0
PREVIEW_AGE_S = 12.0
#: Open a government camera's upstream session only while something needs it.
#: The hub used to hold one RTSP session to every government camera from start
#: to shutdown, watched or not. The organisers' guidance for the shared sandbox
#: is the opposite: keep open only the streams actively required, open them
#: according to actual processing needs, stagger connections, and design for a
#: camera count that is not fixed. A camera's session now opens when a still of
#: it is asked for (a visible tile, a focused view) or when it is assigned to
#: the AI worker, and closes after HUB_IDLE_S with no request. Own-feed files
#: are local and cost the grid nothing, so they stay open.
#: SAAKSHYA_HUB_ON_DEMAND=0 restores the always-open behaviour.
HUB_ON_DEMAND = os.environ.get("SAAKSHYA_HUB_ON_DEMAND", "1").strip().lower() not in {
    "0", "false", "off", "no"}
HUB_IDLE_S = float(os.environ.get("SAAKSHYA_HUB_IDLE_S", "90"))
JPEG_MIN_INTERVAL_S = 0.09  # ~11 fps ceiling per camera; latest-frame-wins
AI_QUEUE = 2
HEALTH_FLUSH_S = 5.0

_HUB: MediaHub | None = None
_HUB_LOCK = threading.Lock()


def get_hub() -> MediaHub | None:
    return _HUB


def set_hub(hub: MediaHub | None) -> None:
    global _HUB
    with _HUB_LOCK:
        _HUB = hub


def hub_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    from saakshya.live.relay import relay_enabled
    if relay_enabled():
        return False
    flag = os.environ.get("SAAKSHYA_MEDIA_HUB", "1").strip().lower()
    return flag not in {"0", "false", "off", "no"}


@dataclass
class HubSlot:
    camera_id: str
    domain: str
    url: str
    jpeg: bytes | None = None
    captured_at: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = "h264"
    pts_s: float | None = None
    jpeg_fps: float | None = None
    last_jpeg_at: float = 0.0
    first_frame_at: float | None = None
    started_at: float = field(default_factory=time.monotonic)
    ai: str = "OFF"
    boxes: list[dict[str, Any]] = field(default_factory=list)
    dropped_ai: int = 0
    jpeg_count: int = 0
    last_error: str | None = None
    #: Whether an upstream worker is running for this camera now.
    running: bool = False
    #: When a still of this camera was last asked for (monotonic seconds).
    last_demand: float = 0.0
    _fps_times: list[float] = field(default_factory=list)


class MediaHub:
    """Authoritative local media plane for the API process."""

    def __init__(self, store: Any | None = None, *,
                 jpeg_quality: int = 70, max_width: int = 720,
                 on_demand: bool | None = None, idle_s: float | None = None) -> None:
        self.store = store
        self.on_demand = HUB_ON_DEMAND if on_demand is None else on_demand
        self.idle_s = HUB_IDLE_S if idle_s is None else idle_s
        self._stagger_s = 0.18
        self._next_start = 0.0
        self.jpeg_quality = jpeg_quality
        self.max_width = max_width
        self.mgr = StreamManager(StreamConfig(
            consumer_queue_depth=4,
            open_timeout_s=12.0,
            read_timeout_s=15.0,
        ))
        self._slots: dict[str, HubSlot] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._ai_q: queue.Queue[tuple[str, Frame] | None] = queue.Queue(
            maxsize=AI_QUEUE * 8)
        self._threads: list[threading.Thread] = []
        self.ai_cameras: set[str] = set()
        self.started_at = time.monotonic()
        self.stats = {
            "upstream": 0,
            "streaming": 0,
            "jpeg_published": 0,
            "ai_frames": 0,
            "ai_error": None,
        }

    def owns(self, camera_id: str) -> bool:
        """Whether this hub is the camera's one upstream session (open or idle)."""
        return camera_id in self._slots

    def demand(self, camera_id: str) -> None:
        """Something needs this camera now: open its session if it is idle.

        Starts are staggered, as at boot, so thirty tiles scrolling into view
        together do not become thirty simultaneous handshakes at the gateway.
        """
        now = time.monotonic()
        with self._lock:
            slot = self._slots.get(camera_id)
            if slot is None or self._stop.is_set():
                return
            slot.last_demand = now
            if slot.running:
                return
            slot.running = True
            delay = max(0.0, self._next_start - now)
            self._next_start = max(now, self._next_start) + self._stagger_s
        t = threading.Thread(target=self._run_camera, args=(camera_id, slot.url, delay),
                             name=f"hub:{camera_id}", daemon=True)
        t.start()
        self._threads.append(t)

    def _always_open(self, slot: HubSlot) -> bool:
        return (not self.on_demand or slot.domain != "GOVERNMENT"
                or slot.camera_id in self.ai_cameras)

    def reap_idle(self, now: float | None = None) -> list[str]:
        """Close the sessions nothing has asked for in `idle_s`. Returns them."""
        now = time.monotonic() if now is None else now
        closed = []
        with self._lock:
            for cid, slot in self._slots.items():
                if (slot.running and not self._always_open(slot)
                        and now - slot.last_demand > self.idle_s):
                    closed.append(cid)
        for cid in closed:
            self.mgr.remove(cid)
        if closed:
            log.info("media hub closed idle upstream sessions: %s", ", ".join(closed))
        return closed

    def as_snapshot(self, camera_id: str) -> Snapshot | None:
        slot = self._slots.get(camera_id)
        if slot is not None:
            self.demand(camera_id)
        if slot is None or not slot.jpeg:
            return None
        age = time.time() - slot.captured_at if slot.captured_at else 999
        kind = "ingest" if age <= LIVE_AGE_S else "ingest-stale"
        return Snapshot(
            camera_id=camera_id, jpeg=slot.jpeg, captured_at=slot.captured_at,
            width=slot.width, height=slot.height, codec=slot.codec or "jpeg",
            pts_s=slot.pts_s, source=kind)

    def media_state(self, camera_id: str) -> dict[str, Any]:
        with self._lock:
            slot = self._slots.get(camera_id)
            worker = self.mgr.get(camera_id)
        if slot is not None and not slot.running and not self._always_open(slot):
            return {
                "camera_id": camera_id,
                "source": "IDLE",
                "video": "IDLE",
                "ai": slot.ai,
                "age_s": None if not slot.jpeg else round(time.time() - slot.captured_at, 3),
                "domain": slot.domain,
                "label": "NOT_OPENED",
                "live_means": ("no upstream session is held for a camera nothing is "
                               "watching; it opens when a still of it is asked for"),
            }
        if slot is None:
            return {
                "camera_id": camera_id,
                "source": "NO_SIGNAL",
                "video": "NO_SIGNAL",
                "ai": "OFF",
                "age_s": None,
                "label": "NOT_MEASURED",
            }
        wstate = (worker.stats.state if worker else "init")
        source = _source_from_worker(wstate, slot)
        age = (time.time() - slot.captured_at) if slot.jpeg else None
        video = _video_from_age(source, age, slot.domain)
        fps = worker.stats.measured_fps if worker else None
        first_ms = None
        if slot.first_frame_at is not None:
            first_ms = round((slot.first_frame_at - slot.started_at) * 1000, 1)
        domain = slot.domain
        label = ("MEASURED_OWN_FEED" if domain == "OWN_FEED"
                 else "MEASURED_REAL" if domain == "GOVERNMENT"
                 else "MEASURED_SYNTHETIC")
        return {
            "camera_id": camera_id,
            "source": source,
            "video": video,
            "ai": slot.ai,
            "age_s": None if age is None else round(age, 3),
            "fps": fps,
            "jpeg_fps": slot.jpeg_fps,
            "codec": (worker.stats.codec if worker else None) or slot.codec,
            "width": slot.width or (worker.stats.width if worker else None),
            "height": slot.height or (worker.stats.height if worker else None),
            "reconnects": worker.stats.reconnects if worker else 0,
            "frames": worker.stats.frames if worker else 0,
            "dropped_ai": slot.dropped_ai,
            "first_frame_ms": first_ms,
            "last_error": slot.last_error or (
                worker.stats.last_error if worker else None),
            "domain": domain,
            "label": label,
            "live_means": f"hub JPEG age ≤ {LIVE_AGE_S}s from streaming ingest",
        }

    def boxes(self, camera_id: str) -> list[dict[str, Any]]:
        with self._lock:
            slot = self._slots.get(camera_id)
            return list(slot.boxes) if slot else []

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ids = list(self._slots)
        states = [self.media_state(cid) for cid in ids]
        live = sum(1 for s in states if s["video"] == "LIVE")
        preview = sum(1 for s in states if s["video"] == "PREVIEW")
        replay = sum(1 for s in states if s["video"] == "REPLAY")
        streaming = sum(1 for s in states if s["source"] == "CONNECTED")
        gov = [s for s in states if s.get("domain") == "GOVERNMENT"]
        return {
            "plane": "local_hub",
            "on_demand": self.on_demand,
            "upstream_sessions": sum(1 for s in states if s["source"] != "IDLE"),
            "idle": sum(1 for s in states if s["source"] == "IDLE"),
            "source_connected": streaming,
            "government_live": sum(1 for s in gov if s["video"] == "LIVE"),
            "government_connected": sum(1 for s in gov if s["source"] == "CONNECTED"),
            "browser_live": live,
            "browser_preview": preview,
            "browser_replay": replay,
            "ai_cameras": sorted(self.ai_cameras),
            "elapsed_s": round(time.monotonic() - self.started_at, 2),
            "cameras": states,
            "label": "MEASURED from this process; LIVE is hub-frame age, not Sentinel WHEP",
        }

    def start(self, cameras: list[dict[str, Any]], *,
              ai_ids: list[str] | None = None,
              stagger_s: float = 0.18) -> None:
        """Register every camera; open the ones that must be open now.

        Own-feed files, AI-assigned cameras, and every camera when on-demand is
        off, open at once, staggered. The rest open on first `demand`.
        """
        self.ai_cameras = set(ai_ids or [])
        self._stagger_s = stagger_s
        stagger = 0.0
        for cam in cameras:
            cid = cam.get("camera_id") or ""
            if not cid or str(cid).startswith("CTL-SLOT"):
                continue
            domain = (cam.get("source_domain") or "").upper()
            if domain == "SYNTHETIC_CONTROL" and not local_media_url(cid):
                continue
            url = local_media_url(cid) or (cam.get("rtsp_url") or "")
            if not url:
                continue
            slot = HubSlot(camera_id=cid, domain=domain or "GOVERNMENT", url=url)
            with self._lock:
                self._slots[cid] = slot
            if not self._always_open(slot):
                continue
            slot.running = True
            t = threading.Thread(
                target=self._run_camera, args=(cid, url, stagger),
                name=f"hub:{cid}", daemon=True)
            t.start()
            self._threads.append(t)
            stagger += stagger_s
        self._next_start = time.monotonic() + stagger
        if self.ai_cameras:
            ai = threading.Thread(target=self._ai_loop, name="hub-ai", daemon=True)
            ai.start()
            self._threads.append(ai)
        flush = threading.Thread(target=self._health_loop, name="hub-health",
                                 daemon=True)
        flush.start()
        self._threads.append(flush)
        log.info("media hub started cameras=%s ai=%s",
                 len(self._slots), sorted(self.ai_cameras))

    def stop(self) -> None:
        self._stop.set()
        self.mgr.stop_all()
        try:
            self._ai_q.put_nowait(None)
        except queue.Full:
            pass

    def _run_camera(self, camera_id: str, url: str, delay: float) -> None:
        try:
            if delay and self._stop.wait(delay):
                return
            worker = self.mgr.add(camera_id, url)
            q = worker.subscribe("hub-jpeg")
            while not self._stop.is_set():
                try:
                    frame = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if frame is None:
                    return
                self._on_frame(camera_id, frame)
        finally:
            with self._lock:
                slot = self._slots.get(camera_id)
                if slot is not None:
                    slot.running = False

    def _on_frame(self, camera_id: str, frame: Frame) -> None:
        now = time.monotonic()
        with self._lock:
            slot = self._slots.get(camera_id)
            if slot is None:
                return
            if slot.first_frame_at is None:
                slot.first_frame_at = now
            due = (now - slot.last_jpeg_at) >= JPEG_MIN_INTERVAL_S
            if frame.warmup and slot.jpeg is not None:
                due = False
        if due:
            jpeg, w, h = _encode_jpeg(frame.image, self.max_width, self.jpeg_quality)
            if jpeg:
                with self._lock:
                    slot = self._slots[camera_id]
                    slot.jpeg = jpeg
                    slot.captured_at = time.time()
                    slot.width, slot.height = w, h
                    slot.codec = frame.codec or slot.codec
                    slot.pts_s = frame.pts_s
                    slot.last_jpeg_at = now
                    slot.jpeg_count += 1
                    slot._fps_times.append(now)
                    slot._fps_times = [t for t in slot._fps_times if now - t <= 2.0]
                    if len(slot._fps_times) >= 2:
                        dt = slot._fps_times[-1] - slot._fps_times[0]
                        slot.jpeg_fps = round((len(slot._fps_times) - 1) / dt, 2) if dt > 0 else None
                    self.stats["jpeg_published"] += 1
        if camera_id in self.ai_cameras:
            try:
                self._ai_q.put_nowait((camera_id, frame))
            except queue.Full:
                try:
                    self._ai_q.get_nowait()
                    self._ai_q.put_nowait((camera_id, frame))
                except (queue.Empty, queue.Full):
                    pass
                with self._lock:
                    self._slots[camera_id].dropped_ai += 1

    def _ai_loop(self) -> None:
        if self._stop.wait(8.0):
            return
        # The detector runs on the Apple GPU (MPS) when there is one. It was pinned
        # to CPU here with no recorded reason; measured on this M5 at 2560x1440 the
        # whole per-frame pipeline is 2.0x faster on MPS (598 -> 293 ms median) with
        # identical observations and plates, and the detector alone 3.4x with every
        # box matched at IoU >= 0.9 (tools/bench/detector_device.py). Set
        # SAAKSHYA_FORCE_CPU=1 to pin it to CPU.
        pipes: dict[str, Any] = {}
        try:
            from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
            from saakshya.runtime.backend import quiet_transformers
            quiet_transformers()
            cfg = PipelineConfig(validate_models=False)
        except Exception as exc:
            self.stats["ai_error"] = f"{type(exc).__name__}: {exc}"[:240]
            log.warning("hub AI unavailable: %s", self.stats["ai_error"])
            with self._lock:
                for cid in self.ai_cameras:
                    if cid in self._slots:
                        self._slots[cid].ai = "OFF"
            return
        pending: list[Any] = []
        last_flush = time.monotonic()
        last_ai: dict[str, float] = {}
        while not self._stop.is_set():
            try:
                item = self._ai_q.get(timeout=0.4)
            except queue.Empty:
                item = None
            if item is None and not pending:
                continue
            if item is None:
                continue
            cid, frame = item
            now_ai = time.monotonic()
            if now_ai - last_ai.get(cid, 0.0) < 0.40:
                continue
            last_ai[cid] = now_ai
            pipe = pipes.get(cid)
            if pipe is None:
                pipe = CameraPipeline(cid, cfg)
                pipes[cid] = pipe
                with self._lock:
                    if cid in self._slots:
                        self._slots[cid].ai = "ACTIVE"
            try:
                obs = pipe.process(frame)
                self.stats["ai_frames"] += 1
                boxes = _boxes_from_pipe(pipe, cid, frame)
                with self._lock:
                    if cid in self._slots:
                        self._slots[cid].boxes = boxes
                        self._slots[cid].ai = "ACTIVE"
                if obs:
                    pending.extend(obs)
            except Exception as exc:
                log.warning("hub AI frame failed %s: %s", cid, type(exc).__name__)
                with self._lock:
                    if cid in self._slots:
                        self._slots[cid].ai = "DEGRADED"
            if pending and (len(pending) >= 8 or time.monotonic() - last_flush > 1.5):
                self._flush_obs(pending)
                pending = []
                last_flush = time.monotonic()
        if pending:
            self._flush_obs(pending)

    def _flush_obs(self, rows: list[Any]) -> None:
        if not self.store or not rows:
            return
        try:
            self.store.add_observations(rows)
        except Exception:
            log.exception("hub observation flush failed")

    def _health_loop(self) -> None:
        while not self._stop.wait(HEALTH_FLUSH_S):
            try:
                self.reap_idle()
            except Exception:
                log.exception("hub idle reaping failed")
            if self.store is None:
                continue
            try:
                snap = self.snapshot()
                for row in snap["cameras"]:
                    if row["source"] == "IDLE":
                        # Not opened, so not measured: keep the last health.
                        continue
                    st = "STREAMING" if row["source"] in {"CONNECTED", "RECONNECTING"} else (
                        "DOWN" if row["source"] in {"UPSTREAM_ERROR", "NO_SIGNAL"} else "UNKNOWN")
                    self.store.upsert_health(row["camera_id"], {
                        "state": st,
                        "reachable": row["source"] == "CONNECTED",
                        "reconnects": row.get("reconnects") or 0,
                        "frames": row.get("frames") or 0,
                        "measured_fps": row.get("fps"),
                        "last_error": row.get("last_error"),
                    })
            except Exception:
                log.exception("hub health flush failed")


def _source_from_worker(wstate: str, slot: HubSlot) -> str:
    if wstate in {"connecting", "init"}:
        return "CONNECTING"
    if wstate == "backoff":
        return "RECONNECTING"
    if wstate in {"error", "stopped"}:
        return "UPSTREAM_ERROR"
    if wstate == "streaming":
        return "CONNECTED"
    return "CONNECTING"


def _video_from_age(source: str, age: float | None, domain: str = "") -> str:
    if (domain or "").upper() == "OWN_FEED":
        if age is None:
            return "CONNECTING"
        if age <= PREVIEW_AGE_S:
            return "REPLAY"
        return "NO_SIGNAL"
    if age is None:
        return "CONNECTING" if source in {"CONNECTING", "CONNECTED", "RECONNECTING"} else "NO_SIGNAL"
    if source == "CONNECTED" and age <= LIVE_AGE_S:
        return "LIVE"
    if source == "CONNECTED" and age <= PREVIEW_AGE_S:
        return "PREVIEW"
    if age <= PREVIEW_AGE_S:
        return "PREVIEW"
    if source in {"RECONNECTING", "CONNECTING"}:
        return "RECONNECTING"
    if source == "UPSTREAM_ERROR":
        return "UPSTREAM ERROR"
    return "NO_SIGNAL"


def _encode_jpeg(bgr: np.ndarray, max_width: int, quality: int
                 ) -> tuple[bytes | None, int, int]:
    if bgr is None or bgr.size == 0:
        return None, 0, 0
    h, w = bgr.shape[:2]
    img = bgr
    if w > max_width:
        step = max(1, w // max_width)
        img = bgr[::step, ::step]
        h, w = img.shape[:2]
    try:
        rgb = np.ascontiguousarray(img[:, :, ::-1])
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format="JPEG", quality=quality)
        return buf.getvalue(), w, h
    except Exception:
        return None, w, h


def _boxes_from_pipe(pipe: Any, camera_id: str, frame: Frame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        vt = pipe.tracks.get(camera_id, frame.segment_id)
        pt = pipe.people.get(camera_id, frame.segment_id)
    except Exception:
        return out
    tracks = list(getattr(vt, "tracks", {}).values()) + list(
        getattr(pt, "tracks", {}).values())
    for t in tracks:
        box = getattr(t, "box", None)
        if not box or len(box) < 4:
            continue
        out.append({
            "track_id": t.track_id,
            "bbox": [float(x) for x in box],
            "object_type": t.label,
            "confidence": float(t.score or 0),
            "pts_s": float(t.last_pts_s or 0),
            "source": "hub_live",
            "label": "MEASURED",
        })
        if len(out) >= 32:
            break
    return out


def select_start_cameras(store: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Government + own-feeds. CONTROL files optional. AI: own + optional gov budget."""
    rows = store.list_cameras()
    gov = [c for c in rows if (c.get("source_domain") or "").upper() == "GOVERNMENT"]
    own = [c for c in rows if (c.get("source_domain") or "").upper() == "OWN_FEED"]
    if os.environ.get("SAAKSHYA_HUB_AI", "1").strip().lower() in {"0", "false", "off", "no"}:
        return gov + own, []
    budget = int(os.environ.get("SAAKSHYA_AI_GOV", "0"))
    ai = [c["camera_id"] for c in own]
    for c in gov[:max(0, budget)]:
        ai.append(c["camera_id"])
    return gov + own, ai


def boot_hub(store: Any) -> MediaHub | None:
    if not hub_enabled():
        return None
    existing = get_hub()
    if existing is not None:
        return existing
    hub = MediaHub(store)
    cams, ai = select_start_cameras(store)
    hub.start(cams, ai_ids=ai)
    set_hub(hub)
    return hub
