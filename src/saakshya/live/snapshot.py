"""Camera previews for the interface, without multiplying stream consumers.

The organiser's guide is explicit: **each client gets its own copy of the
stream**. A browser grid of thirty live tiles, each opening its own connection,
is thirty extra stream copies the government grid has to carry — for pictures
nobody is analysing.

So previews are served from **one shared capture per camera, cached**. The
browser gets a still image over the same origin it already talks to; the grid
sees at most one consumer per camera, refreshed no more often than the TTL, and
only for cameras somebody is actually looking at.

Three properties that matter:

* **Bounded.** A hard cap on concurrent captures and on cached bytes. A grid of
  thirty tiles cannot turn into thirty simultaneous decoder sessions.
* **Closed immediately.** Each capture takes a frame and shuts down. A snapshot
  that lingers is load carried for nothing.
* **Honest when stale.** Every response carries the age of the frame. A preview
  is not evidence and is never presented as live video.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from saakshya.live.credentials import configured, credentialed, needs_grid_credential, redact

log = logging.getLogger("saakshya.live.snapshot")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def file_view_rate() -> float:
    """How fast a looping own-feed file is presented.

    1.0 is the recording's own clock. Below 1.0 the detections linger;
    above 1.0 the clip races the boxes and nothing is seen.
    """
    try:
        return max(0.25, min(2.0, float(os.environ.get(
            "SAAKSHYA_FILE_VIEW_RATE", "0.85"))))
    except ValueError:
        return 0.85


def file_view_wait_s(pts: float, first_pts: float, origin: float,
                     rate: float, now: float) -> float:
    """Seconds to sleep before presenting this file-view frame."""
    if rate <= 0:
        rate = 1.0
    return origin + (pts - first_pts) / rate - now


def selected_wait_s() -> float:
    try:
        return max(0.0, min(15.0, float(os.environ.get(
            "SAAKSHYA_SELECTED_WAIT_S", "7"))))
    except ValueError:
        return 7.0


def local_media_url(camera_id: str) -> str:
    """Own-feed MP4 next to the demo corpus, if this camera has one."""
    from pathlib import Path

    if not camera_id or not _SAFE_ID.match(camera_id):
        return ""
    root = Path(os.environ.get("SAAKSHYA_MEDIA", "var/media")).resolve()
    path = (root / f"{camera_id}.mp4").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return ""
    return str(path) if path.is_file() else ""


class SelectedView:
    """Exactly one extra decode session — the camera the operator opened.

    The wall stays on ingest stills. Clicking a tile is the one extra stream
    copy the integrator guide permits. Files loop; RTSP follows PTS.
    """

    def __init__(self, *, quality: int = 88, max_width: int = 1280) -> None:
        self.quality = quality
        self.max_width = max_width
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.camera_id: str | None = None
        self._snap: Snapshot | None = None
        self._awaited: str | None = None
        self._seek_pts_s: float | None = None

    def latest(self, camera_id: str) -> Snapshot | None:
        with self._lock:
            if self.camera_id != camera_id:
                return None
            return self._snap

    def wait_for(self, camera_id: str, timeout_s: float | None = None
                 ) -> Snapshot | None:
        """Block until the extra decode has a frame, or the operator moved on."""
        limit = selected_wait_s() if timeout_s is None else timeout_s
        deadline = time.monotonic() + max(0.0, limit)
        while time.monotonic() < deadline:
            got = self.latest(camera_id)
            if got is not None:
                return got
            if self.camera_id != camera_id:
                return None
            time.sleep(0.12)
        return self.latest(camera_id)

    def start(self, camera_id: str, url: str) -> None:
        if not camera_id or not url:
            return
        self.stop()
        self._stop = threading.Event()
        self.camera_id = camera_id
        self._awaited = None
        self._seek_pts_s = None
        self._thread = threading.Thread(
            target=self._run, args=(camera_id, url),
            name=f"live-view-{camera_id}", daemon=True)
        self._thread.start()

    def seek_file(self, pts_s: float) -> bool:
        """Own-feed file replay: skip to this PTS on the next decode loop.

        Live RTSP/WHEP is not seekable. Callers must check local_media_url.
        """
        with self._lock:
            if self.camera_id is None:
                return False
            self._seek_pts_s = float(pts_s)
            return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.5)
        with self._lock:
            self._thread = None
            self.camera_id = None
            self._snap = None

    def _run(self, camera_id: str, url: str) -> None:
        import av
        import numpy as np
        from PIL import Image

        from saakshya.live.credentials import credentialed, redact

        av.logging.set_level(av.logging.FATAL)
        looping = not url.startswith(("rtsp://", "rtsps://", "http://", "https://"))
        open_url = url if looping else credentialed(url)
        backoff = 2.0
        while not self._stop.is_set():
            container = None
            try:
                opts = {}
                timeout = 8.0
                if not looping:
                    opts = {"rtsp_transport": "tcp", "stimeout": "8000000"}
                    timeout = 12.0
                container = av.open(open_url, options=opts, timeout=timeout)
                stream = next((s for s in container.streams if s.type == "video"),
                              None)
                if stream is None:
                    break
                tb = float(stream.time_base) if stream.time_base else 0.0
                rate = file_view_rate() if looping else 1.0
                first_pts: float | None = None
                loop_origin = 0.0
                for frame in container.decode(stream):
                    if self._stop.is_set():
                        break
                    if not hasattr(frame, "to_ndarray") or frame.width is None:
                        continue
                    pts = (float(frame.pts) * tb if frame.pts is not None
                           else None)
                    with self._lock:
                        seek_to = self._seek_pts_s
                    if looping and seek_to is not None and pts is not None:
                        if pts + 0.08 < seek_to:
                            continue
                        with self._lock:
                            if self._seek_pts_s == seek_to:
                                self._seek_pts_s = None
                        first_pts = pts
                        loop_origin = time.monotonic()
                    if looping and pts is not None:
                        if first_pts is None:
                            first_pts = pts
                            loop_origin = time.monotonic()
                        wait = file_view_wait_s(
                            pts, first_pts, loop_origin, rate, time.monotonic())
                        if wait < -0.25:
                            continue
                        if wait > 0.004 and self._stop.wait(wait):
                            break
                    img = frame.to_ndarray(format="bgr24")
                    h, w = img.shape[:2]
                    if w > self.max_width:
                        step = max(1, w // self.max_width)
                        img = img[::step, ::step]
                    pil = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]))
                    import io
                    buf = io.BytesIO()
                    pil.save(buf, format="JPEG", quality=self.quality)
                    snap = Snapshot(
                        camera_id=camera_id, jpeg=buf.getvalue(),
                        captured_at=time.time(), width=w, height=h,
                        codec=getattr(stream.codec_context, "name", "h264") or "h264",
                        pts_s=pts,
                        source="file-view" if looping else "live-view")
                    with self._lock:
                        if self.camera_id == camera_id:
                            self._snap = snap
                    backoff = 2.0
                if not looping:
                    if self._stop.wait(backoff):
                        break
                    backoff = min(30.0, backoff * 2)
            except Exception as exc:
                log.info("live view failed for %s: %s: %s", camera_id,
                         type(exc).__name__, redact(str(exc))[:160])
                if looping or self._stop.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2)
            finally:
                if container is not None:
                    with contextlib.suppress(Exception):
                        container.close()
            if looping and not self._stop.is_set():
                continue
            if not looping:
                continue
            break


@dataclass
class Snapshot:
    camera_id: str
    jpeg: bytes
    captured_at: float
    width: int
    height: int
    codec: str
    pts_s: float | None = None
    source: str = "rtsp"

    @property
    def age_s(self) -> float:
        return time.time() - self.captured_at


#: Upstream refusals, by the exception PyAV raises. These are answers *from the
#: grid*, not faults in this platform, and an operator who is told "camera may
#: be down" when the truth is "the grid revoked our access" will spend the
#: afternoon on the wrong problem.
_REFUSALS = {
    "HTTPUnauthorizedError": "the camera grid refused this connection "
                             "(401 unauthorised) — our access, not the camera",
    "HTTPForbiddenError": "the camera grid refused this connection "
                          "(403 forbidden) — our access, not the camera",
    "HTTPNotFoundError": "the grid has no stream at this address (404)",
}


def classify(exc: BaseException) -> str:
    """A failure in words, distinguishing refusal from unreachability."""
    name = type(exc).__name__
    if name in _REFUSALS:
        return _REFUSALS[name]
    if name in ("ConnectionRefusedError", "OSError", "ConnectionError"):
        return "no route to the camera"
    if "Timeout" in name or "timed out" in str(exc).lower():
        return "the camera did not answer in time"
    return f"capture failed ({name})"


class SnapshotService:
    """Cached, bounded still previews.

    Deliberately not a video proxy. Transcoding thirty live streams for a
    browser would be a second analytics workload serving no investigative
    purpose, and the guide asks us to open only what we process.
    """

    #: How long a still may be served before it is refetched. Ingest JPEGs are
    #: a file read, so one second keeps the wall moving. An RTSP capture is a
    #: real extra client — keep that result longer so a thirty-tile pan does
    #: not reopen the grid.
    DEFAULT_TTL_S = 1.0
    CAPTURE_TTL_S = 300.0

    #: Simultaneous captures across the whole service. The grid is a shared
    #: resource and this is our share of it.
    MAX_CONCURRENT = 4

    #: Cache ceiling. Stills are ~60-200 KB, so this is a few tens of frames.
    MAX_CACHE_BYTES = 24 * 1024 * 1024

    def __init__(self, *, ttl_s: float | None = None,
                 max_concurrent: int | None = None,
                 quality: int = 88, max_width: int = 1280) -> None:
        self.ttl_s = ttl_s if ttl_s is not None else self.DEFAULT_TTL_S
        self.quality = quality
        self.max_width = max_width
        self._sem = threading.BoundedSemaphore(
            max_concurrent or self.MAX_CONCURRENT)
        self._cache: dict[str, Snapshot] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.selected = SelectedView(quality=quality, max_width=max_width)
        self.stats = {"served_from_cache": 0, "served_from_ingest": 0,
                      "captured": 0, "failed": 0, "refused_busy": 0}
        #: Why the last capture for a camera failed, in words the interface can
        #: show. "Could not capture" covers a camera that is down, a network
        #: that is out, and an upstream that has revoked our access — three
        #: different situations needing three different responses. Reporting
        #: them identically sent an operator looking for a fault on a camera
        #: that was working perfectly and simply would not let us in.
        self.last_error: dict[str, str] = {}

    #: Prefer a still this old over opening a 31st RTSP session. Beyond this,
    #: if ingest is still publishing any camera, the last JPEG for this one
    #: is still served -- labelled stale, with its age. Hiding it made working
    #: cameras look down while their files sat on disk.
    STALE_PREVIEW_S = 600.0

    def _from_ingest(self, camera_id: str, *, max_age_s: float | None = None
                     ) -> Snapshot | None:
        """A still the ingest process already decoded, if it is still usable.

        Opening a second RTSP session while ingest holds thirty is how the
        live wall timed out against a grid that was working. Prefer the copy
        we are already paying for — even a slightly stale one, labelled as such.
        """
        from saakshya.live.preview import read_preview
        age_limit = self.ttl_s if max_age_s is None else max_age_s
        got = read_preview(camera_id, max_age_s=age_limit)
        if got is None:
            return None
        data, width, height, age = got
        return Snapshot(
            camera_id=camera_id, jpeg=data,
            captured_at=time.time() - age,
            width=width, height=height, codec="jpeg",
            source="ingest" if age <= self.ttl_s else "ingest-stale")

    def _lock_for(self, camera_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(camera_id, threading.Lock())

    def cached(self, camera_id: str) -> Snapshot | None:
        s = self._cache.get(camera_id)
        if not s:
            return None
        ttl = self.ttl_s
        if s.source == "rtsp":
            ttl = max(ttl, self.CAPTURE_TTL_S)
        return s if s.age_s <= ttl else None

    def get(self, camera_id: str, url: str, *,
            force: bool = False) -> Snapshot | None:
        """A still for one camera, from cache where possible."""
        try:
            from saakshya.live.relay import get_relay
            relay = get_relay()
            if relay is not None:
                rs = relay.grab_jpeg(camera_id)
                if rs is not None:
                    self.stats["served_from_ingest"] += 1
                    return rs
                # Relay owns the stream. Do not open a second Sentinel RTSP grab.
                if relay._slots.get(camera_id) is not None:
                    self.last_error[camera_id] = (
                        "local relay has this camera; a second Sentinel capture "
                        "is not opened. JPEG is PREVIEW fallback only.")
                    self.stats["failed"] += 1
                    return None
        except Exception:
            pass
        try:
            from saakshya.live.hub import get_hub
            hub = get_hub()
            if hub is not None:
                hs = hub.as_snapshot(camera_id)
                if hs is not None:
                    self.stats["served_from_ingest"] += 1
                    return hs
        except Exception:
            pass
        live = self.selected.latest(camera_id)
        if (live is None and self.selected.camera_id == camera_id
                and self.selected._awaited != camera_id):
            # Wait once for the extra decode. If it never produces a frame,
            # later requests must not block 7s each — serve ingest instead.
            self.selected._awaited = camera_id
            live = self.selected.wait_for(camera_id)
        if live is not None:
            self.stats["served_from_cache"] += 1
            return live

        if not force:
            fresh = self.cached(camera_id)
            if fresh is not None:
                self.stats["served_from_cache"] += 1
                return fresh

        from_ingest = self._from_ingest(camera_id)
        if from_ingest is None:
            from_ingest = self._from_ingest(
                camera_id, max_age_s=self.STALE_PREVIEW_S)
        from saakshya.live.preview import ingest_is_publishing
        publishing = ingest_is_publishing()
        ancient = self._from_ingest(camera_id, max_age_s=float("inf"))
        if from_ingest is None and publishing:
            # While ingest holds thirty sessions, never open a 31st just to
            # paint the wall. An older JPEG, labelled stale, is the wall.
            from_ingest = ancient
        if from_ingest is not None:
            self.stats["served_from_ingest"] += 1
            self._store(from_ingest)
            return from_ingest
        if publishing:
            self.last_error[camera_id] = (
                "ingest has not published a still for this camera yet. "
                "A second RTSP session is not opened while the grid is "
                "already being consumed.")
            self.stats["failed"] += 1
            return None

        if not (url or "").strip():
            self.last_error[camera_id] = (
                "this camera has no RTSP source in the registry, and "
                "ingest has not published a still")
            self.stats["failed"] += 1
            return None

        if needs_grid_credential(url) and not configured():
            self.last_error[camera_id] = (
                "This grid authenticates every stream connection, and no "
                "credential is configured in this process. Live stills cannot "
                "open until SENTINEL_GRID_EMAIL and SENTINEL_GRID_PASSWORD "
                "are set. They must not be written into any file.")
            return None

        # Per-camera lock: thirty browser tiles refreshing at once must produce
        # one capture per camera, not thirty.
        lock = self._lock_for(camera_id)
        with lock:
            fresh = self.cached(camera_id)
            if fresh is not None and not force:
                self.stats["served_from_cache"] += 1
                return fresh

            if not self._sem.acquire(timeout=6.0):
                self.stats["refused_busy"] += 1
                # A stale frame beats no frame, and its age is reported.
                return self._cache.get(camera_id)
            try:
                snap = self._capture(camera_id, url)
            finally:
                self._sem.release()

        if snap is None:
            self.stats["failed"] += 1
            # A capture attempt was made because the ingest still exceeded the
            # stale window. If the upstream is unavailable, preserve the last
            # frame and expose its age instead of turning a known camera black.
            fallback = self._cache.get(camera_id) or ancient
            if fallback is not None:
                return fallback
            return None

        self.stats["captured"] += 1
        self._store(snap)
        return snap

    def _store(self, snap: Snapshot) -> None:
        with self._guard:
            self._cache[snap.camera_id] = snap
            total = sum(len(s.jpeg) for s in self._cache.values())
            if total <= self.MAX_CACHE_BYTES:
                return
            # Evict oldest first. Bounded rather than clever: this cache exists
            # to avoid re-opening streams, not to be an image store.
            for cam, _ in sorted(self._cache.items(),
                                 key=lambda kv: kv[1].captured_at):
                del self._cache[cam]
                total = sum(len(s.jpeg) for s in self._cache.values())
                if total <= self.MAX_CACHE_BYTES:
                    break

    def _capture(self, camera_id: str, url: str) -> Snapshot | None:
        import av
        import numpy as np
        from PIL import Image

        av.logging.set_level(av.logging.FATAL)
        container = None
        try:
            # Credentials are added here and nowhere earlier: the registry
            # holds the clean URL, so no credential reaches the database, an
            # export, or a screenshot of a camera table.
            container = av.open(
                credentialed(url),
                options={"rtsp_transport": "tcp", "stimeout": "8000000"},
                timeout=12.0)
            stream = next((s for s in container.streams if s.type == "video"),
                          None)
            if stream is None:
                return None
            # Keyframes only: a still needs no inter frames, and skipping them
            # is a fraction of the decode cost.
            stream.codec_context.skip_frame = "NONKEY"
            # PyAV types `decode` as a union over video, audio and subtitle
            # frames; we selected a video stream above, so the video branch is
            # the only one reachable.
            tb = float(stream.time_base) if stream.time_base else 0.0
            deadline = time.perf_counter() + 12.0
            for frame in container.decode(stream):
                if time.perf_counter() > deadline:
                    break
                if not hasattr(frame, "to_ndarray") or frame.width is None:  # type: ignore[union-attr]
                    continue
                img = frame.to_ndarray(format="bgr24")  # type: ignore[union-attr,call-arg]
                h, w = img.shape[:2]
                if w > self.max_width:
                    step = max(1, w // self.max_width)
                    img = img[::step, ::step]
                pil = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]))
                import io
                buf = io.BytesIO()
                pil.save(buf, format="JPEG", quality=self.quality)
                return Snapshot(
                    camera_id=camera_id, jpeg=buf.getvalue(),
                    captured_at=time.time(), width=w, height=h,
                    codec=stream.codec_context.name,
                    pts_s=float(frame.pts) * tb if frame.pts is not None else None,
                    source="rtsp")
            return None
        except Exception as exc:
            # PyAV puts the URL it tried into the message, credentials and all.
            log.info("snapshot failed for %s: %s: %s", camera_id,
                     type(exc).__name__, redact(str(exc))[:160])
            self.last_error[camera_id] = classify(exc)
            return None
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.close()

    def snapshot_stats(self) -> dict[str, Any]:
        with self._guard:
            cached = len(self._cache)
            byts = sum(len(s.jpeg) for s in self._cache.values())
        return {**self.stats, "cached_cameras": cached,
                "cache_bytes": byts, "ttl_s": self.ttl_s,
                "max_concurrent": self.MAX_CONCURRENT,
                "note": ("One shared capture per camera, cached. The grid gives "
                         "every client its own stream copy, so a browser tile "
                         "must never open one of its own.")}
