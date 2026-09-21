"""Stream manager — the reliability layer.

This module exists because of one observation: on the organiser's sandbox, four
of the seven scoring areas depend on our software surviving *their* feeds, and
the published Integrator's Guide enumerates exactly how client pipelines fail on
it. Every rule below maps to one of those documented failure modes.

Implementation notes
--------------------
PyAV is used rather than ``cv2.VideoCapture``. This is deliberate and is the
most important single choice in the ingest layer: ``VideoCapture`` exposes only
``CAP_PROP_POS_MSEC`` (documented by the organisers as unreliable) and
``CAP_PROP_FPS`` (documented as *wrong*), whereas PyAV surfaces real packet and
frame ``pts`` with the stream's ``time_base``. Correct timing is not achievable
through the OpenCV capture API on these streams.

Threading: one decode thread per camera. PyAV releases the GIL inside the C
decode call, so threads are the right primitive here and avoid dragging a whole
event loop through blocking libav calls.
"""
from __future__ import annotations

import contextlib
import logging
import queue
import random
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import av
import av.error

from saakshya.common.clock import CameraClock, utc_now
from saakshya.common.ids import new_id
from saakshya.ingest.discontinuity import SceneCutDetector
from saakshya.ingest.frame import Frame
from saakshya.live.credentials import credentialed, redact

log = logging.getLogger(__name__)

# libav is chatty on mid-stream joins ("Could not find ref with POC", "Error
# constructing the frame RPS"). The organisers explicitly warn that pipelines
# aborting on these will bounce on H.265 streams. We silence the logger and
# count the errors instead.
av.logging.set_level(av.logging.FATAL)


# --------------------------------------------------------------------------- #
# Tunables. Every one of these is a documented behaviour of the sandbox.
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class StreamConfig:
    #: RTSP over TCP. UDP is accepted by the gateway but fails across NAT and
    #: corporate firewalls, and partial UDP delivery produces corrupt frames
    #: that look exactly like model bugs.
    rtsp_transport: str = "tcp"
    open_timeout_s: float = 15.0
    read_timeout_s: float = 20.0

    #: Reconnect backoff. Guide says start ~2s, cap ~30s, never tight-loop.
    backoff_initial_s: float = 2.0
    backoff_max_s: float = 30.0
    backoff_factor: float = 1.8
    backoff_jitter: float = 0.3

    #: A PTS that moves backwards, or jumps forward by more than this, is a
    #: discontinuity — the feed looped, or the encoder restarted.
    pts_regression_eps_s: float = 0.001
    pts_forward_jump_s: float = 10.0

    #: Warm-up. On connect the gateway replays its buffered GOP, so stream time
    #: advances faster than wall time. We hold frames as `warmup` until the
    #: advance rate settles, or the ceiling elapses.
    warmup_max_s: float = 4.0
    warmup_settle_rate: float = 1.25
    warmup_min_frames: int = 3

    #: Per-consumer queue depth. Slow consumers drop frames; they never stall
    #: the decoder, and never block another consumer.
    consumer_queue_depth: int = 8

    #: Rolling window for measured fps.
    fps_window: int = 60


@dataclass
class StreamStats:
    """Real counters. These drive the Grid Health screen — no synthetic values."""

    camera_id: str
    state: str = "init"
    connects: int = 0
    reconnects: int = 0
    frames: int = 0
    frames_dropped_consumer: int = 0
    decoder_errors: int = 0
    pts_regressions: int = 0
    pts_forward_jumps: int = 0
    segment_breaks: int = 0
    scene_cuts: int = 0
    warmup_frames_suppressed: int = 0
    open_failures: int = 0
    last_frame_wall: datetime | None = None
    last_error: str | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    declared_fps: float | None = None
    measured_fps: float | None = None
    clock_drift_s: float = 0.0
    connected_since: datetime | None = None
    _fps_samples: list[float] = field(default_factory=list, repr=False)

    def note_frame_interval(self, dt: float, window: int) -> None:
        if dt <= 0:
            return
        self._fps_samples.append(dt)
        if len(self._fps_samples) > window:
            self._fps_samples.pop(0)
        if len(self._fps_samples) >= 5:
            s = sorted(self._fps_samples)
            median = s[len(s) // 2]
            self.measured_fps = round(1.0 / median, 2) if median > 0 else None

    def snapshot(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        for k in ("last_frame_wall", "connected_since"):
            if isinstance(d.get(k), datetime):
                d[k] = d[k].isoformat()
        return d


class _Consumer:
    __slots__ = ("dropped", "name", "q")

    def __init__(self, name: str, depth: int) -> None:
        self.name = name
        self.q: queue.Queue[Frame | None] = queue.Queue(maxsize=depth)
        self.dropped = 0

    def offer(self, frame: Frame) -> bool:
        try:
            self.q.put_nowait(frame)
            return True
        except queue.Full:
            # Drop the *oldest* so a stalled consumer still gets recent frames
            # when it wakes up, rather than a stale backlog.
            try:
                self.q.get_nowait()
                self.q.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass
            self.dropped += 1
            return False


class StreamWorker(threading.Thread):
    """Owns exactly one capture for one camera and fans frames out internally.

    Requirement: *one capture per camera*. Each client connection to the gateway
    receives its own copy of the stream, so opening a camera twice doubles load
    on the evaluator's server. Consumers attach here instead.
    """

    def __init__(
        self,
        camera_id: str,
        url: str,
        config: StreamConfig | None = None,
        on_segment_break: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(name=f"stream:{camera_id}", daemon=True)
        self.camera_id = camera_id
        self.url = url
        self.cfg = config or StreamConfig()
        self.stats = StreamStats(camera_id=camera_id)
        self.clock = CameraClock(camera_id=camera_id)
        self._consumers: dict[str, _Consumer] = {}
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._segment_id = new_id("SG")
        self._on_segment_break = on_segment_break
        self._frame_index = 0
        self._cut = SceneCutDetector(camera_id=camera_id)
        #: Wall cameras can skip inter-frames. AI cameras must not.
        self.keyframes_only = False

    # -- consumer API ------------------------------------------------------- #
    def subscribe(self, name: str) -> queue.Queue[Frame | None]:
        with self._lock:
            c = _Consumer(name, self.cfg.consumer_queue_depth)
            self._consumers[name] = c
            return c.q

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            c = self._consumers.pop(name, None)
            if c is not None:
                with contextlib.suppress(queue.Full):
                    c.q.put_nowait(None)

    @property
    def segment_id(self) -> str:
        return self._segment_id

    def stop(self) -> None:
        """Graceful stop. Consumers receive a sentinel None."""
        self._stopping.set()
        with self._lock:
            for c in self._consumers.values():
                with contextlib.suppress(queue.Full):
                    c.q.put_nowait(None)

    # -- internals ---------------------------------------------------------- #
    def _publish(self, frame: Frame) -> None:
        with self._lock:
            consumers = list(self._consumers.values())
        for c in consumers:
            if not c.offer(frame):
                self.stats.frames_dropped_consumer += 1

    def _new_segment(self, reason: str) -> None:
        old = self._segment_id
        self._segment_id = new_id("SG")
        self._frame_index = 0
        self.stats.segment_breaks += 1
        self.clock.anchor_wall = None
        self.clock.anchor_pts_s = None
        self._cut.reset()
        log.info("segment_break camera=%s reason=%s %s->%s",
                 self.camera_id, reason, old, self._segment_id)
        if self._on_segment_break is not None:
            try:
                self._on_segment_break(self.camera_id, old, reason)
            except Exception:  # never let a callback kill the decoder
                log.exception("segment_break callback failed camera=%s", self.camera_id)

    def _open(self) -> av.container.InputContainer:
        opts = {
            "rtsp_transport": self.cfg.rtsp_transport,
            "stimeout": str(int(self.cfg.open_timeout_s * 1_000_000)),  # libav µs
            "max_delay": "500000",
            "reorder_queue_size": "0",
        }
        # Credentialed at the socket, not in the registry. `self.url` stays
        # clean so that every log line, stat and error below can quote it.
        return av.open(
            credentialed(self.url),
            options=opts,
            timeout=(self.cfg.open_timeout_s, self.cfg.read_timeout_s),
        )

    def run(self) -> None:
        backoff = self.cfg.backoff_initial_s
        while not self._stopping.is_set():
            container = None
            try:
                self.stats.state = "connecting"
                container = self._open()
                vstream = next((s for s in container.streams if s.type == "video"), None)
                if vstream is None:
                    raise av.error.InvalidDataError(0, "no video stream")
                # PyAV's stubs declare thread_type only on VideoStream, but the
                # attribute is set on the base Stream at runtime. Verified by
                # the live smoke test, which fails without threaded decode.
                vstream.thread_type = "AUTO"  # type: ignore[attr-defined]

                self.stats.connects += 1
                is_file = Path(self.url).is_file() or str(self.url).startswith("file:")
                if self.stats.connects > 1 and not is_file:
                    self.stats.reconnects += 1
                    self._new_segment("reconnect")
                elif self.stats.connects > 1 and is_file:
                    self._new_segment("file_loop")
                self.stats.connected_since = utc_now()
                self.stats.state = "streaming"
                self.stats.codec = getattr(vstream.codec_context, "name", None)
                try:
                    self.stats.declared_fps = (
                        float(vstream.average_rate) if vstream.average_rate else None
                    )
                except (TypeError, ValueError):
                    self.stats.declared_fps = None
                backoff = self.cfg.backoff_initial_s

                self._decode_loop(container, vstream)
                if Path(self.url).is_file() and not self._stopping.is_set():
                    # Loop local files immediately. This is replay, not an
                    # upstream drop — do not count it as a reconnect storm.
                    continue
                if not self._stopping.is_set():
                    raise ConnectionError("stream ended")

            except Exception as exc:
                self.stats.open_failures += 1
                self.stats.last_error = f"{type(exc).__name__}: {redact(str(exc))}"[:300]
                self.stats.state = "error"
                log.warning("stream error camera=%s %s", self.camera_id, self.stats.last_error)
            finally:
                if container is not None:
                    with contextlib.suppress(Exception):
                        container.close()

            if self._stopping.is_set():
                break
            # Exponential backoff with jitter. Never tight-loop on a dead feed.
            sleep = backoff * (1.0 + random.uniform(-self.cfg.backoff_jitter,
                                                     self.cfg.backoff_jitter))
            self.stats.state = "backoff"
            if self._stopping.wait(max(0.1, sleep)):
                break
            backoff = min(backoff * self.cfg.backoff_factor, self.cfg.backoff_max_s)

        self.stats.state = "stopped"
        with self._lock:
            for c in self._consumers.values():
                with contextlib.suppress(queue.Full):
                    c.q.put_nowait(None)

    def _decode_loop(self, container: Any, vstream: Any) -> None:
        time_base = float(vstream.time_base) if vstream.time_base else 1 / 90000.0
        last_pts: float | None = None
        connect_wall = time.monotonic()
        first_pts: float | None = None
        is_file = Path(self.url).is_file() or str(self.url).startswith("file:")
        warmup = not is_file
        warmup_frames = 0

        for packet in container.demux(vstream):
            if self._stopping.is_set():
                return
            if self.keyframes_only and not getattr(packet, "is_keyframe", True):
                continue
            try:
                frames = packet.decode()
            # `av.FFmpegError` is the base of every PyAV decode error —
            # InvalidDataError and the rest derive from it — and it in turn
            # derives from the builtin ValueError.
            #
            # This clause previously named `av.error.ValueError`, which does not
            # exist. Python evaluates an except tuple only when something is
            # raised inside the try, so the mistake was invisible until a packet
            # actually failed to decode — at which point the handler that exists
            # to survive a bad packet would itself raise AttributeError and take
            # the worker down. The corpus never produced a decoder error, so no
            # test reached it; mypy did.
            except (av.FFmpegError, ValueError) as exc:
                # Documented and expected when attaching mid-stream, before the
                # first IDR. Log, count, keep going.
                self.stats.decoder_errors += 1
                self.stats.last_error = f"decode: {type(exc).__name__}"
                continue

            for f in frames:
                if self._stopping.is_set():
                    return
                if f.pts is None:
                    continue
                pts_s = float(f.pts) * time_base
                now_wall = time.monotonic()
                t_ingest = utc_now()

                # -- discontinuity detection --------------------------------- #
                if last_pts is not None:
                    delta = pts_s - last_pts
                    if delta < -self.cfg.pts_regression_eps_s:
                        self.stats.pts_regressions += 1
                        self._new_segment("pts_regression")
                        first_pts = pts_s
                        connect_wall = now_wall
                        if not is_file:
                            warmup, warmup_frames = True, 0
                    elif delta > self.cfg.pts_forward_jump_s:
                        self.stats.pts_forward_jumps += 1
                        self._new_segment("pts_forward_jump")
                        first_pts = pts_s
                        connect_wall = now_wall
                        if not is_file:
                            warmup, warmup_frames = True, 0
                    else:
                        self.stats.note_frame_interval(delta, self.cfg.fps_window)

                if first_pts is None:
                    first_pts = pts_s

                # -- warm-up burst suppression -------------------------------- #
                if warmup:
                    warmup_frames += 1
                    wall_elapsed = max(1e-6, now_wall - connect_wall)
                    pts_elapsed = pts_s - first_pts
                    rate = pts_elapsed / wall_elapsed
                    settled = (
                        warmup_frames >= self.cfg.warmup_min_frames
                        and rate <= self.cfg.warmup_settle_rate
                    )
                    if settled or wall_elapsed > self.cfg.warmup_max_s:
                        warmup = False
                    else:
                        self.stats.warmup_frames_suppressed += 1

                t_norm = self.clock.project(pts_s, t_ingest)
                last_pts = pts_s

                try:
                    img = f.to_ndarray(format="bgr24")
                except Exception:
                    self.stats.decoder_errors += 1
                    continue

                h, w = img.shape[:2]

                # Second, independent discontinuity signal. Measurement on the
                # grid replica showed a looping publisher advances PTS straight
                # across the loop point, so timing evidence alone misses the cut
                # and long-lived state (tracks, galleries) would survive it.
                if not is_file and not warmup and self._cut.update(img):
                    self.stats.scene_cuts += 1
                    self._new_segment("scene_cut")

                # Resolution can change mid-stream; record it rather than assume.
                self.stats.width, self.stats.height = w, h
                self.stats.frames += 1
                self.stats.last_frame_wall = t_ingest
                self.stats.clock_drift_s = round(self.clock.drift_s, 4)
                self._frame_index += 1

                if is_file and first_pts is not None:
                    due = connect_wall + (pts_s - first_pts)
                    wait = due - time.monotonic()
                    if wait > 0.003 and self._stopping.wait(min(wait, 0.4)):
                        return

                self._publish(
                    Frame(
                        camera_id=self.camera_id,
                        segment_id=self._segment_id,
                        pts_s=pts_s,
                        t_norm=t_norm,
                        t_ingest=t_ingest,
                        image=img,
                        width=w,
                        height=h,
                        codec=self.stats.codec or "unknown",
                        warmup=warmup,
                        frame_index=self._frame_index,
                    )
                )
        # Demux ended. File workers return so the outer loop can reopen
        # immediately. RTSP workers raise and back off.




class StreamManager:
    """Supervises workers and reconciles against the camera catalogue.

    Adding or removing a camera never restarts the application.
    """

    def __init__(self, config: StreamConfig | None = None) -> None:
        self.cfg = config or StreamConfig()
        self._workers: dict[str, StreamWorker] = {}
        self._lock = threading.RLock()
        self.segment_breaks: list[tuple[str, str, str, datetime]] = []

    def _on_segment_break(self, camera_id: str, old_segment: str, reason: str) -> None:
        with self._lock:
            self.segment_breaks.append((camera_id, old_segment, reason, utc_now()))
            if len(self.segment_breaks) > 1000:
                self.segment_breaks.pop(0)

    def add(self, camera_id: str, url: str) -> StreamWorker:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing is not None:
                if existing.url == url and existing.is_alive():
                    return existing
                existing.stop()
            w = StreamWorker(camera_id, url, self.cfg, on_segment_break=self._on_segment_break)
            self._workers[camera_id] = w
            w.start()
            log.info("camera started %s -> %s", camera_id, redact(url))
            return w

    def remove(self, camera_id: str) -> None:
        """Stop cleanly. Historical events are untouched; camera is marked gone."""
        with self._lock:
            w = self._workers.pop(camera_id, None)
        if w is not None:
            w.stop()
            log.info("camera stopped %s", camera_id)

    def reconcile(self, catalogue: dict[str, str]) -> dict[str, list[str]]:
        """Converge running workers onto ``{camera_id: url}``.

        The catalogue is the contract; the URL pattern is not. Returns what
        changed so the caller can log/publish it.
        """
        with self._lock:
            current = set(self._workers)
        wanted = set(catalogue)
        added, removed, rebound = [], [], []

        for cid in wanted - current:
            self.add(cid, catalogue[cid])
            added.append(cid)
        for cid in current - wanted:
            self.remove(cid)
            removed.append(cid)
        for cid in wanted & current:
            w = self._workers.get(cid)
            if w is not None and (w.url != catalogue[cid] or not w.is_alive()):
                self.add(cid, catalogue[cid])
                rebound.append(cid)
        return {"added": added, "removed": removed, "rebound": rebound}

    def get(self, camera_id: str) -> StreamWorker | None:
        return self._workers.get(camera_id)

    def stats(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {cid: w.stats.snapshot() for cid, w in self._workers.items()}

    def aggregate(self) -> dict[str, Any]:
        with self._lock:
            ws = list(self._workers.values())
        streaming = sum(1 for w in ws if w.stats.state == "streaming")
        return {
            "cameras_total": len(ws),
            "cameras_streaming": streaming,
            "cameras_down": len(ws) - streaming,
            "reconnects": sum(w.stats.reconnects for w in ws),
            "decoder_errors": sum(w.stats.decoder_errors for w in ws),
            "pts_regressions": sum(w.stats.pts_regressions for w in ws),
            "pts_forward_jumps": sum(w.stats.pts_forward_jumps for w in ws),
            "segment_breaks": sum(w.stats.segment_breaks for w in ws),
            "scene_cuts": sum(w.stats.scene_cuts for w in ws),
            "warmup_frames_suppressed": sum(w.stats.warmup_frames_suppressed for w in ws),
            "frames": sum(w.stats.frames for w in ws),
            "frames_dropped_consumer": sum(w.stats.frames_dropped_consumer for w in ws),
            "open_failures": sum(w.stats.open_failures for w in ws),
        }

    def stop_all(self) -> None:
        with self._lock:
            ws = list(self._workers.values())
            self._workers.clear()
        for w in ws:
            w.stop()
        for w in ws:
            w.join(timeout=5.0)

    def frames(self, camera_id: str, consumer: str, timeout: float = 5.0) -> Iterator[Frame]:
        """Convenience iterator for a single consumer."""
        w = self.get(camera_id)
        if w is None:
            return
        q = w.subscribe(consumer)
        try:
            while True:
                try:
                    f = q.get(timeout=timeout)
                except queue.Empty:
                    continue
                if f is None:
                    return
                yield f
        finally:
            w.unsubscribe(consumer)
