#!/usr/bin/env python3
"""Ingest the live Sentinel Camera Grid through the production pipeline.

Staged by design. Every client gets its own copy of each stream, so opening
thirty heavy pipelines at once is load on the organiser's grid and on this
machine simultaneously — and if it falls over there is no way to tell which
gave way. So concurrency ramps, and each stage records what it cost.

**Capability-aware scheduling.** A camera measured UNSUITABLE for plate reading
does not get a plate reader pointed at it. Forcing analytics onto a camera that
cannot support them produces low-confidence noise, spends the compute that a
capable camera needed, and teaches operators to distrust every result.

**Provenance is never mixed.** Live observations are written to their own store
(`var/live.db` by default) and every record carries `GOVERNMENT_LIVE`. A figure
from the synthetic corpus and a figure from the government grid answer different
questions, and averaging them answers neither.

    python tools/live/ingest.py --cameras 5  --minutes 3
    python tools/live/ingest.py --stages 5,10,20,30 --minutes 2
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import queue
import resource
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import av

from saakshya.analytics.corruption import assess_corruption, stream_verdict
from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
from saakshya.common.paths import display
from saakshya.evidence.rolling import RollingEvidence
from saakshya.ingest.frame import Frame
from saakshya.intelligence import CameraGraph
from saakshya.live import (
    CatalogueUnavailable,
    GridConfig,
    LiveCamera,
    discover_by_probe,
    fetch_catalogue,
)
from saakshya.live.credentials import credentialed, redact
from saakshya.live.preview import write_preview
from saakshya.runtime.backend import quiet_transformers
from saakshya.store import Store
from saakshya.store.provenance import redacted, refuses_live_writes, store_name

av.logging.set_level(av.logging.FATAL)
log = logging.getLogger("saakshya.live.ingest")

PROVENANCE = "GOVERNMENT_LIVE"

#: Analytics sampling rate by tier, in frames per second of *video* (by PTS).
#: T2 costs roughly ten times T0 per frame on CPU, so the tier is the main lever
#: on whether thirty cameras fit at all.
#: One analysed frame in this many is checked for decoder concealment.
#:
#: Set from what a real run yields, not from what felt cheap. At one in twenty a
#: four-minute capture produced about twenty samples per camera — below the
#: twenty-five a rate needs to mean anything — so a genuinely corrupt stream
#: went unreported. At one in eight the same run yields sixty, and the cost is
#: about 3 ms per sample: under a fifth of a second across a four-minute run.
CORRUPTION_SAMPLE = 8

TIER_FPS = {"T0": 0.5, "T1": 1.0, "T2": 3.0, "T3": 5.0, "UNASSIGNED": 1.0}

#: Measured on the live grid, and the reason T2 is 3.0 rather than 2.0: at ten
#: concurrent T2 cameras this machine delivered 3,747 analysed frames in six
#: minutes — about **0.6 fps per camera**, not the 2.0 the tier asked for. A
#: registration mark is legible for a second or two as a vehicle passes, so at
#: 0.6 fps a plate gets one frame and per-track voting never accumulates.
#:
#: The lesson is not "raise the rate". It is that **a tier is a promise the
#: machine has to be able to keep**: asking for T2 on ten cameras when the host
#: can serve three is how a system produces zero plate reads and blames the
#: model. `--fps-budget` makes the constraint explicit.
DEFAULT_FPS_BUDGET = 12.0

#: Tiers that decode **keyframes only**.
#:
#: Measured on this grid: the five-camera stage decoded 22,121 frames to analyse
#: 711 of them — three per cent. Decoding is the cost, and the rest was thrown
#: away. Keyframes arrive at 0.56-0.57 fps on these cameras (a ~1.8 s GOP),
#: which is almost exactly the T0 sampling rate, so a T0 camera can be served at
#: roughly one twenty-fifth of the decode cost by never decoding an inter frame.
#:
#: T1 and above still decode everything: they need frames close enough together
#: to associate a vehicle across them, and a track that sees a vehicle twice
#: two seconds apart is not a track.
KEYFRAME_ONLY_TIERS = frozenset({"T0"})


@dataclass
class CameraStats:
    camera_id: str
    tier: str = "UNASSIGNED"
    connects: int = 0
    reconnects: int = 0
    frames: int = 0
    frames_analysed: int = 0
    decoder_warnings: int = 0
    #: Frames sampled for decoder concealment, and how many looked concealed.
    #: A stream can decode without a single warning and still deliver garbage:
    #: when reference frames go missing the decoder builds a plausible-shaped
    #: picture from stale data. cam21 did exactly that for 777 analysed frames
    #: and produced no observations, which is indistinguishable from an empty
    #: road unless something looks at the pixels.
    frames_checked_corrupt: int = 0
    frames_suspect_corrupt: int = 0
    pts_regressions: int = 0
    scene_cuts: int = 0
    observations: int = 0
    last_error: str | None = None
    first_frame_at: float | None = None
    last_frame_at: float | None = None
    measured_fps: float | None = None
    state: str = "STARTING"
    decode_mode: str = "full"
    #: Observations the consumer could not accept in time. Counted, never
    #: silent: a run that dropped observations and did not say so is a run
    #: whose numbers cannot be trusted.
    observations_dropped: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class LiveWorker(threading.Thread):
    """One camera: connect, decode, analyse at its tier, reconnect with backoff.

    Deliberately one thread per camera rather than an async pool. PyAV's decode
    call releases the GIL, so threads genuinely overlap on decode — which is
    where the time goes — and a per-camera thread makes a stuck camera visible
    as one stalled worker rather than a mysterious slowdown everywhere.
    """

    #: The guide asks for exponential backoff to a cap, never a tight loop.
    BACKOFF_INITIAL_S = 2.0
    BACKOFF_CAP_S = 30.0

    #: How long a worker waits for room in the queue before giving up on a
    #: batch. The queue is bounded, so a stalled consumer would otherwise block
    #: the decoder thread indefinitely — and the decoder holds an RTSP session
    #: on the organiser's grid. Measured saturation at 30 cameras makes this a
    #: real condition, not a theoretical one.
    QUEUE_PUT_TIMEOUT_S = 5.0

    def __init__(self, cam: LiveCamera, tier: str, out: queue.Queue,
                 cfg: GridConfig, *, stop: threading.Event,
                 rolling: RollingEvidence | None = None) -> None:
        super().__init__(name=f"live-{cam.camera_id}", daemon=True)
        #: Optional: a short window of recent frames, so an alert can seal what
        #: the camera saw. Optional because profiling and benchmark runs have no
        #: use for it and should not pay for the encoding.
        self.rolling = rolling
        self.cam = cam
        self.tier = tier
        self.out = out
        self.cfg = cfg
        self.stop = stop
        self.stats = CameraStats(camera_id=cam.camera_id, tier=tier)
        self.pipeline = CameraPipeline(
            cam.camera_id, PipelineConfig(),
            district=cam.district, department=cam.department,
            lat=cam.lat, lon=cam.lon)
        self._segment = 0
        self._preview_pts = float("-inf")
        self._preview_wall = 0.0

    def run(self) -> None:
        backoff = self.BACKOFF_INITIAL_S
        url = self.cam.rtsp_url or self.cfg.rtsp(self.cam.camera_id)
        while not self.stop.is_set():
            try:
                self._session(url)
                backoff = self.BACKOFF_INITIAL_S      # a clean session resets it
            except Exception as exc:
                # PyAV puts the URL it tried into the message, credential and
                # all, and this string is surfaced in health and reports.
                self.stats.last_error = (
                    f"{type(exc).__name__}: {redact(str(exc))[:160]}")
                self.stats.state = "RECONNECTING"
            if self.stop.is_set():
                break
            # Jitter so thirty cameras do not all retry on the same tick and
            # arrive at the grid as a thundering herd.
            import random
            wait = min(backoff, self.BACKOFF_CAP_S) * (0.7 + 0.6 * random.random())
            if self.stop.wait(wait):
                break
            backoff = min(backoff * 2, self.BACKOFF_CAP_S)
            self.stats.reconnects += 1
        self.stats.state = "STOPPED"
        # Flush whatever tracks were open when the stream ended.
        with contextlib.suppress(Exception):
            self._emit(self.pipeline.flush())

    def _emit(self, obs: list) -> None:
        """Hand observations (and forensic OCR rows) to the consumer.

        A bounded queue and an unbounded wait is a decoder thread held hostage
        by a slow consumer — and that decoder is holding an RTSP session on the
        organiser's grid. Waiting briefly and counting a failure is the honest
        trade; the count is reported per camera so a saturated run is visible
        rather than merely slow.

        Forensic reads are drained even when no observation was emitted: a
        one-hit track with invalid OCR still belongs in ``plate_reads``.
        """
        reads = self.pipeline.drain_plate_reads()
        if not obs and not reads:
            return
        try:
            self.out.put((self.cam.camera_id, list(obs or []), reads),
                         timeout=self.QUEUE_PUT_TIMEOUT_S)
            self.stats.observations += len(obs or [])
        except queue.Full:
            self.stats.observations_dropped += len(obs or [])
            if self.stats.observations_dropped <= max(1, len(obs or [])):
                log.warning("%s: consumer is not keeping up; observations are "
                            "being dropped and counted", self.cam.camera_id)

    def _session(self, url: str) -> None:
        # Credentialed here, at the socket. This opener is the ingest's own —
        # separate from the snapshot service and the stream worker — and it was
        # missed when the other two were wired, so every session opened
        # anonymously against a grid that authenticates. Three openers is two
        # too many; until they are one, each must be checked.
        container = av.open(
            credentialed(url), options={"rtsp_transport": "tcp",
                                        "stimeout": "15000000"},
            timeout=20.0)
        self.stats.connects += 1
        self._segment += 1
        segment_id = f"{self.cam.camera_id}-S{self._segment}"
        try:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise RuntimeError("no video stream")
            if self.tier in KEYFRAME_ONLY_TIERS:
                # The decoder still parses every packet; it just does not
                # reconstruct the inter frames. That is where the saving is.
                stream.codec_context.skip_frame = "NONKEY"
                self.stats.decode_mode = "keyframe-only"
            tb = float(stream.time_base)
            step = 1.0 / TIER_FPS.get(self.tier, 1.0)
            next_at = 0.0
            last_pts = None
            t_first = None
            n_pts = 0
            self.stats.state = "STREAMING"
            self.stats.last_error = None

            while not self.stop.is_set():
                try:
                    got = False
                    for frame in container.decode(stream):
                        got = True
                        if self.stop.is_set():
                            return
                        if frame.pts is None:
                            continue
                        t = float(frame.pts) * tb
                        if last_pts is not None:
                            d = t - last_pts
                            if d < -0.001:
                                # The loop point. A hard cut, and long-lived
                                # state must recover from it rather than carry
                                # tracks across a scene that changed entirely.
                                self.stats.pts_regressions += 1
                                self.stats.scene_cuts += 1
                                self._segment += 1
                                segment_id = f"{self.cam.camera_id}-S{self._segment}"
                                self._emit(self.pipeline.flush())
                                next_at = 0.0
                        last_pts = t
                        if t_first is None:
                            t_first = t
                            self.stats.first_frame_at = time.time()
                        self.stats.last_frame_at = time.time()
                        n_pts += 1
                        self.stats.frames += 1
                        if t_first is not None and t - t_first > 0:
                            self.stats.measured_fps = round(
                                n_pts / (t - t_first), 2)

                        # Wall clock, not PTS. Looping publishers and cameras
                        # whose PTS barely advances would otherwise skip the
                        # JPEG for tens of minutes while still counting frames.
                        need_preview = time.time() - self._preview_wall >= 1.0
                        if t < next_at and not need_preview:
                            continue
                        img = frame.to_ndarray(format="bgr24")
                        # One still per second for the live wall, even on
                        # frames this tier is not analysing, so every camera
                        # on the wall has a picture. Preview is not evidence.
                        if need_preview:
                            write_preview(self.cam.camera_id, img)
                            self._preview_pts = t
                            self._preview_wall = time.time()
                        if t < next_at:
                            continue
                        next_at = t + step
                        # Wall clock is recorded, and never used for ordering:
                        # normalised time is derived from PTS.
                        when = datetime.now(UTC)
                        fr = Frame(camera_id=self.cam.camera_id,
                                   segment_id=segment_id, pts_s=t,
                                   t_norm=when, t_ingest=when, image=img,
                                   width=img.shape[1], height=img.shape[0],
                                   codec=stream.codec_context.name)
                        self.stats.frames_analysed += 1
                        # Sampled, not every frame: the check costs ~3 ms and
                        # corruption persists across many frames, so a rate over
                        # a sample answers the question as well as a census and
                        # leaves the budget to the detector.
                        if self.stats.frames_analysed % CORRUPTION_SAMPLE == 0:
                            self.stats.frames_checked_corrupt += 1
                            if assess_corruption(img).suspect:
                                self.stats.frames_suspect_corrupt += 1
                        if self.rolling is not None:
                            self.rolling.observe(self.cam.camera_id, img, t, when)
                        self._emit(self.pipeline.process(fr))
                    if not got:
                        return
                except (av.FFmpegError, ValueError) as exc:
                    self.stats.decoder_warnings += 1
                    if self.stats.decoder_warnings > 500:
                        raise
                    if self.stats.decoder_warnings <= 3:
                        self.stats.last_error = (
                            f"decode: {type(exc).__name__}: {str(exc)[:100]}")
        finally:
            import contextlib
            with contextlib.suppress(Exception):
                container.close()


@dataclass
class StageResult:
    cameras: int
    minutes: float
    watchlist_matches: int = 0
    alerts_raised: int = 0
    write_failures: int = 0
    observations_unwritten: int = 0
    rolling: dict[str, Any] = field(default_factory=dict)
    stats: list[dict[str, Any]] = field(default_factory=list)
    observations: int = 0
    peak_rss_mb: float = 0.0
    events_per_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"cameras": self.cameras, "minutes": self.minutes,
                "observations": self.observations,
                "watchlist_matches": self.watchlist_matches,
                "write_failures": self.write_failures,
                "observations_unwritten": self.observations_unwritten,
                "rolling_evidence": self.rolling,
                "alerts_raised": self.alerts_raised,
                "peak_rss_mb": round(self.peak_rss_mb, 1),
                "events_per_s": round(self.events_per_s, 3),
                "per_camera": self.stats}


#: A probe that comes back empty is usually the grid refusing connections for a
#: moment, not an estate that has gone away. Observed directly: a probe returned
#: zero cameras while the same enumeration a minute later returned all thirty.
PROBE_ATTEMPTS = 3
PROBE_BACKOFF_S = 6.0


def from_registry(store: Store) -> list[LiveCamera]:
    """The cameras this deployment has already onboarded.

    Model 1 calls the registry the spine that every other plane reads from, and
    this is that promise being kept. The catalogue lives behind a CDN session
    cookie, so a host with valid *stream* credentials but no *browser* session
    could not ingest at all — the platform refused to run against an estate it
    had already onboarded and could reach. A registry that cannot be used when
    the catalogue is unreachable is not a spine.
    """
    out: list[LiveCamera] = []
    for c in store.list_cameras():
        if not c.get("rtsp_url"):
            continue
        out.append(LiveCamera(
            camera_id=c["camera_id"], name=c.get("name"),
            rtsp_url=c.get("rtsp_url"), hls_url=c.get("hls_url"),
            whep_url=c.get("whep_url"), lat=c.get("lat"), lon=c.get("lon"),
            district=c.get("district"), department=c.get("department")))
    return out


def load_cameras(cfg: GridConfig, store: Store | None = None,
                 prefer_registry: bool = False
                 ) -> tuple[list[LiveCamera], dict[str, Any]]:
    # Explicit operational mode: run against the estate already onboarded,
    # without asking the catalogue or re-probing. Discovery exists to find what
    # we do not have; when the answer is "the thirty we onboarded", spending
    # minutes rediscovering them is time the grid is not being watched.
    if prefer_registry and store is not None:
        known = from_registry(store)
        if known:
            return known, {"source": "registry (requested)",
                           "caveat": "discovery skipped by --from-registry; "
                                     "this run cannot detect a changed estate"}
    try:
        cams = fetch_catalogue(cfg)
        return cams, {"source": "catalogue", "url": cfg.catalogue_url}
    except CatalogueUnavailable as exc:
        for attempt in range(1, PROBE_ATTEMPTS + 1):
            cams = discover_by_probe(cfg)
            if cams:
                return cams, {
                    "source": "probe", "reason": str(exc), "attempts": attempt,
                    "caveat": "camera set discovered by probing the documented "
                              "id pattern; not the authoritative catalogue"}
            if attempt < PROBE_ATTEMPTS:
                print(f"probe returned no cameras (attempt {attempt} of "
                      f"{PROBE_ATTEMPTS}); retrying in "
                      f"{PROBE_BACKOFF_S:.0f}s", file=sys.stderr, flush=True)
                time.sleep(PROBE_BACKOFF_S)
        # Last resort, and the one that matters in practice: run against what
        # we have already onboarded. Recorded as such, because a run built from
        # the registry is not evidence that the catalogue agrees with it.
        if store is not None:
            known = from_registry(store)
            if known:
                return known, {
                    "source": "registry", "reason": str(exc),
                    "attempts": PROBE_ATTEMPTS,
                    "caveat": "camera set taken from the local registry; the "
                              "catalogue was unreachable, so this run cannot "
                              "confirm the estate has not changed"}
        return [], {"source": "probe", "reason": str(exc),
                    "attempts": PROBE_ATTEMPTS,
                    "caveat": "no camera answered on any attempt"}


def tier_for(camera_id: str, profile: dict[str, Any] | None) -> str:
    """Tier from the measured profile. Absent a profile, T1 — enough to see
    vehicles, not enough to spend plate-reading compute on a camera nobody has
    measured."""
    if not profile:
        return "T1"
    return profile.get(camera_id, {}).get("recommended_tier") or "T1"


def health_state_for(st: CameraStats) -> str:
    """Current session, not 'this camera has ever decoded a frame'.

    Health used to persist STREAMING whenever ``frames > 0``, so a camera that
    streamed for an hour and then dropped still looked STREAMING on Overview
    while the ingest log said 25/30.
    """
    if st.state == "STREAMING":
        return "STREAMING"
    if st.state == "STOPPED":
        return "STOPPED"
    err = (st.last_error or "")
    if "401" in err or "Unauthorized" in err:
        return "DOWN"
    if st.connects == 0 and st.frames == 0:
        return "DOWN"
    return "DEGRADED"


def persist_worker_health(store: Store, workers: list) -> None:
    """Write each worker's stream stats so Overview is not a shutdown artefact.

    Health used to land only when ingest closed. An unbounded run (`--minutes
    0`) never closes, so half the estate kept the previous run's rows and the
    rest were labelled never ingested while observations piled up.
    """
    for w in workers:
        st = w.stats
        store.upsert_health(st.camera_id, {
            "state": health_state_for(st),
            "reachable": st.state == "STREAMING",
            "connects": st.connects, "reconnects": st.reconnects,
            "frames": st.frames, "decoder_errors": st.decoder_warnings,
            "frames_checked_corrupt": st.frames_checked_corrupt,
            "frames_suspect_corrupt": st.frames_suspect_corrupt,
            "pts_regressions": st.pts_regressions,
            "scene_cuts": st.scene_cuts,
            "segment_breaks": st.scene_cuts,
            "measured_fps": st.measured_fps,
            "last_error": st.last_error,
            "last_seen_us": (int(st.last_frame_at * 1e6)
                             if st.last_frame_at else None),
        })


def _unpack_batch(item: tuple) -> tuple[str, list, list]:
    """Queue items are ``(camera_id, observations, plate_reads)``."""
    if len(item) == 2:
        return item[0], item[1], []
    return item[0], item[1], item[2]


def run_stage(cams: list[LiveCamera], tiers: dict[str, str], store: Store,
              cfg: GridConfig, *, minutes: float) -> StageResult:
    out: queue.Queue = queue.Queue(maxsize=2000)
    stop = threading.Event()
    # A short window of recent frames per camera, so an alert can seal what the
    # camera actually saw. The grid is live and not seekable: without it every
    # evidence record is metadata-only — honest, but thin.
    rolling = RollingEvidence(Path("var/live_evidence/rolling"))
    workers = [LiveWorker(c, tiers.get(c.camera_id, "T1"), out, cfg, stop=stop,
                          rolling=rolling)
               for c in cams]

    res = StageResult(cameras=len(cams), minutes=minutes)
    t_start = time.time()
    for w in workers:
        w.start()
        time.sleep(0.15)          # stagger the connects rather than bursting

    # `--minutes 0` runs until interrupted. The challenge asks for *continuous*
    # cross-referencing of live feeds against the watchlist with automated
    # alerts, and a tool that can only run for a fixed number of minutes does
    # not demonstrate that however long the number is.
    continuous = minutes <= 0
    t_end = float("inf") if continuous else time.time() + minutes * 60
    if continuous:
        print("    running continuously — stop with Ctrl-C")
    last_report = time.time()
    written = 0
    # Continuous cross-referencing. The challenge asks for live feeds to be
    # matched against a watchlist as events arrive, with automated alerts —
    # and until now the live path only *wrote* observations. Alerts were raised
    # afterwards, by hand or by the API, which is a batch forensic workflow
    # wearing the words of a real-time one.
    #
    # It runs on the consumer thread, next to the write that produced the
    # observation, so a match is evaluated in the same breath as the sighting.
    # Matching is an indexed lookup on a plate; the cost is nothing beside a
    # decode, and putting it on its own thread would buy latency we do not need
    # and a race we would have to think about.
    from saakshya.watchlist import AlertEngine, WatchlistService

    watchlist = WatchlistService(store)
    alerts = AlertEngine(store)
    # Distinct alert ids, not returns. `AlertEngine.process` folds a repeat
    # sighting into the open alert and returns it *updated*, so counting every
    # return would report two alerts where an operator sees one — and the
    # inflated number would be the one quoted.
    seen_alerts: set[str] = set()
    matched = 0
    #: Observations the store would not accept yet. A transient failure — the
    #: database locked by another writer, a full disk, a lock timeout — used to
    #: propagate straight out of this loop and end the run, taking every
    #: camera's work with it. That is the same shape of loss as the segfault:
    #: one fault, hours of government capture gone, nothing written down.
    #:
    #: Bounded, because an unbounded retry buffer in a process already holding
    #: thirty decoders is the next outage. When it is full the oldest are
    #: dropped and counted: losing the oldest few observations is recoverable,
    #: losing the run is not.
    captures: list[Any] = []
    pending: list[Any] = []
    pending_reads: list[Any] = []
    PENDING_MAX = 20_000
    write_failures = 0
    dropped_unwritable = 0

    try:
        while time.time() < t_end:
            try:
                item = out.get(timeout=0.5)
            except queue.Empty:
                pass
            else:
                _cam_id, obs, reads = _unpack_batch(item)
                pending.extend(obs)
                pending_reads.extend(reads)

            persisted = []
            if pending:
                try:
                    written += store.add_observations(pending)
                    persisted, pending = pending, []
                except Exception as exc:
                    write_failures += 1
                    persisted = []
                    if write_failures <= 3:
                        print(f"    store write failed ({type(exc).__name__}: "
                              f"{str(exc)[:80]}); {len(pending)} observation(s) "
                              f"held for retry", flush=True)
                    if len(pending) > PENDING_MAX:
                        over = len(pending) - PENDING_MAX
                        del pending[:over]
                        dropped_unwritable += over
            if pending_reads:
                try:
                    store.add_plate_reads(pending_reads)
                    pending_reads = []
                except Exception as exc:
                    write_failures += 1
                    if write_failures <= 3:
                        print(f"    plate_reads write failed "
                              f"({type(exc).__name__}: {str(exc)[:80]}); "
                              f"{len(pending_reads)} OCR row(s) held for retry",
                              flush=True)
                    if len(pending_reads) > PENDING_MAX:
                        over = len(pending_reads) - PENDING_MAX
                        del pending_reads[:over]
                        dropped_unwritable += over

            for o in persisted:
                if not o.plate:
                    continue
                # Alerting must not be able to stop ingestion. A fault here
                # loses one alert; a fault that propagates loses the capture.
                try:
                    for m in watchlist.match(o):
                        matched += 1
                        alert = alerts.process(m)
                        if alert is None:
                            continue
                        first_time = alert.alert_id not in seen_alerts
                        seen_alerts.add(alert.alert_id)
                        if first_time:
                            print(f"    ALERT  {o.plate} on {o.camera_id} — "
                                  f"{m.entry.category}, confidence "
                                  f"{alert.confidence:.3f}", flush=True)
                            captures.append(rolling.on_event(
                                o.camera_id, o.observation_id,
                                f"{m.entry.category} match on {o.plate}"))
                except Exception as exc:
                    log.warning("watchlist evaluation failed for %s: %s: %s",
                                o.observation_id, type(exc).__name__, exc)
            # Post-event frames arrive after the trigger; close a capture once
            # it has them rather than blocking the alert on them.
            for cap in [c for c in captures if c.complete]:
                man = rolling.close(cap)
                captures.remove(cap)
                if man:
                    print(f"    EVIDENCE {man['observation_id']}: "
                          f"{len(man['frames'])} frame(s) retained "
                          f"({man['pre_frames']} before, {man['post_frames']} "
                          f"after)", flush=True)

            if time.time() - last_report >= 30:
                streaming = sum(1 for w in workers if w.stats.state == "STREAMING")
                frames = sum(w.stats.frames for w in workers)
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)
                print(f"    streaming={streaming}/{len(workers)} "
                      f"frames={frames:,} observations={written} "
                      f"rss={rss:.0f}MB", flush=True)
                quiet = sorted(w.stats.camera_id for w in workers
                               if w.stats.state != "STREAMING")
                if quiet:
                    print(f"    not streaming ({len(quiet)}): {', '.join(quiet)}",
                          flush=True)
                last_report = time.time()
                try:
                    persist_worker_health(store, workers)
                except Exception as exc:
                    log.warning("health persist failed: %s: %s",
                                type(exc).__name__, exc)
    finally:
        stop.set()
        for w in workers:
            w.join(timeout=12)

    # Drain whatever the workers flushed on the way out.
    while True:
        try:
            item = out.get_nowait()
        except queue.Empty:
            break
        _cam, obs, reads = _unpack_batch(item)
        pending.extend(obs)
        pending_reads.extend(reads)
    for cap in captures:
        # A capture whose post-event frames never arrived still carries the
        # approach, which is worth more than nothing.
        man = rolling.close(cap)
        if man:
            print(f"    EVIDENCE {man['observation_id']}: "
                  f"{len(man['frames'])} frame(s) retained at shutdown",
                  flush=True)

    if pending:
        # One last attempt at whatever never landed, so a failure that has since
        # cleared does not cost the run its tail.
        try:
            written += store.add_observations(pending)
            pending = []
        except Exception as exc:
            print(f"    {len(pending)} observation(s) could not be written at "
                  f"shutdown ({type(exc).__name__})", flush=True)
    if pending_reads:
        try:
            store.add_plate_reads(pending_reads)
            pending_reads = []
        except Exception as exc:
            print(f"    {len(pending_reads)} OCR row(s) could not be written at "
                  f"shutdown ({type(exc).__name__})", flush=True)

    # Persist stream health. §30 makes the live grid the primary source for
    # ACTIVE / DEGRADED / OFFLINE / UNKNOWN, and health that only ever lives in
    # a worker's memory cannot be that — every camera graded UNKNOWN for
    # presence because nothing had written it down.
    persist_worker_health(store, workers)

    # Timebase health, from the same run. Only the separate profiling pass used
    # to write this, so a long ingest — the thing that actually exercises the
    # grid, over minutes rather than a sample — threw its PTS evidence away and
    # every camera stayed UNKNOWN for correlation no matter how much it ran. A
    # camera whose PTS never went backwards over five minutes has earned that
    # finding recorded.
    from saakshya.live.timebase import (
        OverlayClock,
        TimebaseHealth,
        TimebaseRegistry,
        assess_pts,
    )

    timebase = TimebaseRegistry(store)
    for w in workers:
        st = w.stats
        if not st.frames:
            continue                       # nothing was observed; assert nothing
        health, why = assess_pts(
            regressions=st.pts_regressions,
            forward_jumps=getattr(st, "pts_forward_jumps", 0),
            realtime_ratio=None,
            max_gap_s=getattr(st, "max_interframe_gap_s", None),
            frames=st.frames)
        # Cluster membership is evidence a stream sample cannot see. It is
        # carried forward, never overwritten by a run that did not measure it.
        prior = timebase.get(st.camera_id)
        timebase.record(TimebaseHealth(
            camera_id=st.camera_id, pts_health=health,
            pts_regressions=st.pts_regressions,
            pts_forward_jumps=getattr(st, "pts_forward_jumps", 0),
            realtime_ratio=None, measured_fps=st.measured_fps,
            mean_interframe_gap_s=getattr(st, "mean_interframe_gap_s", None),
            max_interframe_gap_s=getattr(st, "max_interframe_gap_s", None),
            overlay_clock=(prior.overlay_clock if prior else OverlayClock.UNKNOWN),
            overlay_reading=(prior.overlay_reading if prior else None),
            time_cluster=(prior.time_cluster if prior else None),
            cluster_confidence=(prior.cluster_confidence if prior else "UNKNOWN"),
            evidence={"why": why, "source": "live ingest",
                      "frames": st.frames, "scene_cuts": st.scene_cuts}))

    res.observations = written
    if write_failures or dropped_unwritable or pending:
        print(f"    store          : {write_failures} write failure(s), "
              f"{len(pending)} still unwritten, {dropped_unwritable} dropped "
              f"after the retry buffer filled", flush=True)
    res.write_failures = write_failures
    res.observations_unwritten = len(pending) + dropped_unwritable
    rstats = rolling.stats()
    if rstats["frames_held"] or rstats["captures_retained"]:
        print(f"    rolling buffer : {rstats['frames_held']} frame(s) held "
              f"({rstats['bytes_held'] / 1e6:.1f} MB across "
              f"{rstats['cameras']} camera(s)), "
              f"{rstats['captures_retained']} capture(s) retained", flush=True)
    res.rolling = rstats
    res.watchlist_matches = matched
    res.alerts_raised = len(seen_alerts)
    if seen_alerts or matched:
        print(f"    watchlist      : {matched} match(es) -> {len(seen_alerts)} "
              f"alert(s); "
              f"{alerts.suppressed_low_confidence} suppressed below the "
              f"confidence floor, {alerts.deduplicated} deduplicated", flush=True)
    res.stats = [w.stats.snapshot() for w in workers]
    res.peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)
    # Measured against the wall clock actually elapsed, not against the minutes
    # requested: a continuous run has no requested duration, and a run that was
    # interrupted early did not last as long as it asked for.
    elapsed = max(1e-6, time.time() - t_start)
    res.minutes = round(elapsed / 60.0, 2)
    res.events_per_s = written / elapsed
    return res



def main() -> int:
    quiet_transformers()
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///var/live.db",
                    help="live store; kept separate from synthetic and demo state")
    ap.add_argument("--stages", default=None,
                    help="comma-separated camera counts, e.g. 5,10,20,30")
    ap.add_argument("--cameras", type=int, default=5)
    ap.add_argument("--only", default=None,
                    help="comma-separated camera ids, instead of the first N")
    ap.add_argument("--tier", default=None,
                    help="override the measured tier for every selected camera")
    ap.add_argument("--fps-budget", type=float, default=DEFAULT_FPS_BUDGET,
                    help="total analysed frames per second this host can serve; "
                         "cameras are scheduled within it rather than each "
                         "being promised a rate the machine cannot keep")
    ap.add_argument("--minutes", type=float, default=3.0,
                    help="0 runs continuously until interrupted — live watch "
                         "mode, for continuous watchlist cross-referencing")
    ap.add_argument("--from-registry", action="store_true",
                    help="run against the cameras already onboarded in the "
                         "store, skipping catalogue and probe discovery")
    ap.add_argument("--profile", type=Path,
                    default=ROOT / "var" / "reports" / "live_camera_profile.json")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "var" / "reports" / "live_ingest.json")
    args = ap.parse_args()

    if refuses_live_writes(args.db):
        print(f"REFUSED: live observations must not be written into "
              f"{store_name(args.db)}, which holds demonstration or evaluation "
              f"state. Provenance is never mixed — use a store of your own.",
              file=sys.stderr)
        return 2

    cfg = GridConfig.from_env()
    # Opened before discovery: the registry is one of the places cameras can
    # come from, so it has to exist before we go looking.
    store = Store(args.db)
    store.create_all()
    cams, source = load_cameras(cfg, store, args.from_registry)
    print(f"cameras    : {len(cams)} ({source['source']})")

    profile = None
    if args.profile.is_file():
        data = json.loads(args.profile.read_text())
        profile = {c["camera_id"]: c for c in data.get("cameras", [])}
        print(f"profile    : {len(profile)} cameras from "
              f"{display(args.profile)}")
    else:
        print("profile    : none — every camera will run at T1. Run "
              "tools/live/profile_grid.py first for capability-aware scheduling.")

    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        selected = [c for c in cams if c.camera_id in wanted]
        missing = wanted - {c.camera_id for c in selected}
        if missing:
            print(f"not in the camera set: {sorted(missing)}", file=sys.stderr)
        cams_run = selected
    else:
        cams_run = cams

    # Refuse to "run" nothing. A stage of zero cameras used to sit for its full
    # duration reporting `streaming=0/0`, which reads as a system working on an
    # empty estate rather than as a run that never started.
    if not cams_run:
        print("\nNO CAMERAS TO RUN.", file=sys.stderr)
        if not cams:
            print(f"  The grid answered no camera on {PROBE_ATTEMPTS} probe "
                  f"attempts. Check the endpoint before reading anything into "
                  f"this.", file=sys.stderr)
        elif args.only:
            print(f"  {len(cams)} camera(s) are reachable, but none matches "
                  f"--only {args.only}.", file=sys.stderr)
        return 2

    tiers = {c.camera_id: (args.tier or tier_for(c.camera_id, profile))
             for c in cams}

    # A tier is a promise. If the sum of what the selected cameras are promised
    # exceeds what this host can deliver, every camera silently gets a fraction
    # and the highest-value analytic — plate reading, which needs consecutive
    # frames — is the first thing to fail. So the budget is checked and the
    # shortfall is stated rather than discovered later in a yield of zero.
    demanded = sum(TIER_FPS.get(tiers[c.camera_id], 1.0) for c in cams_run)
    if demanded > args.fps_budget:
        print(f"\nFPS BUDGET EXCEEDED: {len(cams_run)} cameras at these tiers "
              f"ask for {demanded:.1f} analysed fps; this host is configured for "
              f"{args.fps_budget:.1f}.")
        print("   Each camera will receive roughly "
              f"{args.fps_budget / max(1, len(cams_run)):.2f} fps, which is "
              "below what per-track plate voting needs.")
        print("   Reduce the camera count, lower the tier, or raise "
              "--fps-budget if the host can genuinely serve it.\n")
    by_tier: dict[str, int] = {}
    for t in tiers.values():
        by_tier[t] = by_tier.get(t, 0) + 1
    print(f"tiers      : {by_tier}")

    for c in cams:
        row = c.to_registry_row()
        p = (profile or {}).get(c.camera_id, {})
        if p.get("reachable"):
            row.update({"codec": p.get("codec"), "width": p.get("width"),
                        "height": p.get("height")})
        store.upsert_camera(row)
    print(f"registry   : {len(cams)} cameras in {args.db}")

    stages = ([int(x) for x in args.stages.split(",")] if args.stages
              else [len(cams_run) if args.only else args.cameras])
    stopping = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stopping.update(now=True))

    results = []
    for n in stages:
        if stopping["now"]:
            break
        subset = cams_run[:n]
        print(f"\n── stage: {len(subset)} cameras "
              + ("continuously ──" if args.minutes <= 0
                 else f"for {args.minutes:.0f} min ──"))
        t0 = time.perf_counter()
        res = run_stage(subset, tiers, store, cfg, minutes=args.minutes)
        dt = time.perf_counter() - t0
        streaming = sum(1 for s in res.stats if s["state"] in ("STREAMING", "STOPPED")
                        and s["frames"] > 0)
        frames = sum(s["frames"] for s in res.stats)
        analysed = sum(s["frames_analysed"] for s in res.stats)
        recon = sum(s["reconnects"] for s in res.stats)
        warns = sum(s["decoder_warnings"] for s in res.stats)
        cuts = sum(s["scene_cuts"] for s in res.stats)
        print(f"    delivered      : {frames:,} frames from {streaming}/{len(subset)}")
        print(f"    analysed       : {analysed:,} frames")
        print(f"    observations   : {res.observations}")
        dropped = sum(s["observations_dropped"] for s in res.stats)
        print(f"    reconnects     : {recon}   decoder warnings: {warns}   "
              f"scene cuts: {cuts}")
        if dropped:
            print(f"    DROPPED        : {dropped} observations — the consumer "
                  f"could not keep up at {len(subset)} cameras")
        print(f"    peak RSS       : {res.peak_rss_mb:.0f} MB")
        print(f"    wall           : {dt:.0f}s")

        # Per-camera yield, always. An aggregate hides the failure that
        # actually happens under load: the run does not slow down evenly, it
        # starves some cameras completely while others stay healthy. Eight
        # cameras where one produced 458 observations and seven produced none
        # printed exactly the same summary line as eight healthy cameras.
        print(f"\n    {'camera':<10} {'frames':>8} {'analysed':>9} "
              f"{'obs':>7} {'fps':>6}  {'state':<11} decode")
        for st in sorted(res.stats, key=lambda r: -r["observations"]):
            # Decode quality on every row, not only when it is bad. A reader
            # comparing two cameras' observation counts needs to know whether
            # both were actually seeing the road.
            decode, _ = stream_verdict(st.get("frames_checked_corrupt") or 0,
                                       st.get("frames_suspect_corrupt") or 0)
            print(f"    {st['camera_id']:<10} {st['frames']:>8,} "
                  f"{st['frames_analysed']:>9,} {st['observations']:>7,} "
                  f"{st.get('measured_fps') or 0:>6.1f}  {st['state']:<11} {decode}")

        # Name a corrupted stream before anyone reads its silence as an empty
        # road. These are opposite findings and only one of them is about
        # traffic. The verdict is a rate over many frames, never one frame: an
        # earlier version declared a camera corrupt on 10 of 15 samples and it
        # had produced 375 perfectly good observations in the same run.
        for st in sorted(res.stats, key=lambda r: r["camera_id"]):
            state, why = stream_verdict(st.get("frames_checked_corrupt") or 0,
                                        st.get("frames_suspect_corrupt") or 0)
            if state in ("CORRUPT", "DEGRADED"):
                print(f"\n    STREAM {state}: {st['camera_id']} — {why}",
                      flush=True)

        producing = [st for st in res.stats if st["observations"] > 0]
        silent = [st for st in res.stats
                  if st["observations"] == 0 and st["frames"] > 0]
        if silent and producing:
            names = ", ".join(st["camera_id"] for st in silent[:8])
            print(f"\n    UNEVEN YIELD: {len(silent)} of {len(subset)} cameras "
                  f"decoded frames but produced no observations ({names}).")
            print("      A camera with frames and no observations is either "
                  "genuinely empty or being starved of analysis time.")
            print("      Compare against a smaller stage before reading this "
                  "as a property of the scene.")
        results.append({**res.to_dict(), "wall_seconds": round(dt, 1),
                        "frames_delivered": frames, "frames_analysed": analysed,
                        "reconnects": recon, "decoder_warnings": warns,
                        "scene_cuts": cuts, "observations_dropped": dropped})

    # Grade from what was actually observed, per illumination band, so a grade
    # taken at night does not close the question for daylight.
    from saakshya.capability import CapabilityGrader, TimeBand
    grader = CapabilityGrader(store)
    assessments = grader.grade_all(
        bands=(TimeBand.ALL, TimeBand.DAY, TimeBand.NIGHT, TimeBand.LOW_LIGHT))

    graph = CameraGraph(store).load()
    graph.seed_from_gis()
    learned = graph.learn_from_observations()
    st = store.stats()

    report = {
        "provenance": PROVENANCE,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "database": redacted(args.db),
        "camera_source": source,
        "tiers": by_tier,
        "stages": results,
        "store": st,
        "graph": graph.stats(),
        "transitions_learned": learned,
        "capability": grader.summary(),
        "capability_assessments": len(assessments),
        "note": ("Live government feed. These figures are not comparable with "
                 "the local synthetic corpus and are never merged with it."),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"\nobservations : {st['observations']} "
          f"({st['observations_with_plate']} with a registration mark)")
    print(f"graph        : {json.dumps(graph.stats())}")
    print(f"written      : {display(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
