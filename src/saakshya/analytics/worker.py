"""Isolated AI worker process.

Consumes local MediaMTX RTSP (never Sentinel). Latest-frame-wins per camera.
A crash here must not take down the API or the video plane.

    MEDIA PROCESS (API + relay)
        |
        | rtsp://127.0.0.1:18554/{id}
        v
    AI WORKER
        detector → tracker → ANPR → store → watchlist → alerts

Heartbeat: var/run/ai_worker.json
Live boxes:  var/run/ai_boxes/{id}.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "var" / "run"
BOX_DIR = RUN / "ai_boxes"

log = logging.getLogger("saakshya.analytics.worker")

QUEUE_DEPTH = int(os.environ.get("SAAKSHYA_AI_QUEUE", "2"))
SAMPLE_MIN_S = float(os.environ.get("SAAKSHYA_AI_SAMPLE_S", "0.20"))


def read_heartbeat() -> dict[str, Any]:
    path = RUN / "ai_worker.json"
    try:
        if not path.is_file():
            return {}
        if time.time() - path.stat().st_mtime > 8.0:
            return {"stale": True, "pid": None}
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_boxes(camera_id: str) -> list[dict[str, Any]]:
    path = BOX_DIR / f"{camera_id}.json"
    try:
        if not path.is_file():
            return []
        if time.time() - path.stat().st_mtime > 8.0:
            return []
        data = json.loads(path.read_text())
        return list(data.get("boxes") or [])
    except Exception:
        return []


def ai_state(camera_id: str) -> str:
    hb = read_heartbeat()
    if hb.get("stale"):
        return "OFF"
    row = (hb.get("cameras") or {}).get(camera_id) or {}
    return str(row.get("ai") or "OFF")


def _boxes_from_pipe(pipe: Any, camera_id: str, frame: Any) -> list[dict[str, Any]]:
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
            "pts_s": float(getattr(t, "last_pts_s", 0) or 0),
            "source": "ai_worker",
            "label": "MEASURED",
        })
        if len(out) >= 32:
            break
    return out


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload) + "\n")
    tmp.replace(path)


class Worker:
    def __init__(self, db_url: str, camera_ids: list[str]) -> None:
        self.db_url = db_url
        self.camera_ids = [c.strip() for c in camera_ids if c.strip()]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stats: dict[str, dict[str, Any]] = {
            cid: {
                "ai": "CONNECTING",
                "frames": 0,
                "dropped": 0,
                "detector_fps": None,
                "queue_depth": 0,
                "last_ms": None,
                # Real percentiles over a rolling window. A single latest
                # sample cannot answer "P50", and the command panel should
                # report a measured percentile or nothing at all.
                "inference_p50_ms": None,
                "inference_p95_ms": None,
                "anpr": "UNKNOWN",
            } for cid in self.camera_ids
        }
        self.pid = os.getpid()

    def run(self) -> int:
        # The detector runs on the Apple GPU (MPS) when there is one. It was pinned
        # to CPU here with no recorded reason; measured on this M5 at 2560x1440 the
        # whole per-frame pipeline is 2.0x faster on MPS (598 -> 293 ms median) with
        # identical observations and plates, and the detector alone 3.4x with every
        # box matched at IoU >= 0.9 (tools/bench/detector_device.py). Set
        # SAAKSHYA_FORCE_CPU=1 to pin it to CPU.
        from saakshya.analytics.pipeline import (
            CameraPipeline,
            PipelineConfig,
            persist_pipeline,
        )
        from saakshya.evidence.manifest import EvidenceService
        from saakshya.ingest.stream import StreamConfig, StreamManager
        from saakshya.live.credentials import (
            credentialed,
            needs_grid_credential,
            redact,
        )
        from saakshya.live.relay import get_relay, local_rtsp
        from saakshya.runtime.backend import quiet_transformers
        from saakshya.store import Store
        from saakshya.watchlist import AlertEngine, WatchlistService

        quiet_transformers()
        BOX_DIR.mkdir(parents=True, exist_ok=True)
        store = Store(self.db_url)
        store.create_all()
        watch = WatchlistService(store)
        alerts = AlertEngine(store)
        # An alert names a sighting; without the frame it rests on, the sighting
        # cannot be shown to anyone. Seal at the moment of the match, while the
        # frame that produced it is still in hand - afterwards it is gone, and a
        # manifest with no frame is a record of an assertion rather than of
        # evidence.
        try:
            evidence = EvidenceService(store)
        except Exception:
            log.exception("evidence service unavailable; alerts will not be sealed")
            evidence = None
        cfg = PipelineConfig(validate_models=False)
        mgr = StreamManager(StreamConfig(
            consumer_queue_depth=QUEUE_DEPTH,
            open_timeout_s=8.0,
            read_timeout_s=12.0,
        ))
        pipes: dict[str, CameraPipeline] = {}
        queues: dict[str, Any] = {}
        last_sample: dict[str, float] = {}
        fps_times: dict[str, list[float]] = {cid: [] for cid in self.camera_ids}
        # Inference durations, newest last, capped so the window stays bounded.
        lat_ms: dict[str, list[float]] = {cid: [] for cid in self.camera_ids}

        # RTSP is the grid's AI plane by contract, and the browser wall is on
        # WHEP, so the two planes no longer share a local relay. Prefer the
        # relay when one is actually running (it exists for the own-feed and
        # for deployments that keep it), and otherwise attach straight to the
        # camera's registered source with the credential added at connect time.
        relay = get_relay()
        for cid in self.camera_ids:
            url = ""
            if relay is not None and relay.ready(cid):
                url = local_rtsp(cid)
            else:
                cam = store.get_camera(cid) or {}
                src = (cam.get("rtsp_url") or "").strip()
                if src:
                    url = credentialed(src, required=needs_grid_credential(src))
            if not url:
                log.warning("ai worker has no source for %s", cid)
                continue
            worker = mgr.add(cid, url)
            queues[cid] = worker.subscribe("ai")
            pipes[cid] = CameraPipeline(cid, cfg)
            # redact(): this URL now carries the grid credential in its
            # authority, and a log line is exactly where a credential must not
            # end up.
            log.info("ai worker attached %s -> %s", cid, redact(url))

        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb_thread.start()

        def _handle(*_a: object) -> None:
            self._stop.set()

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)

        pending: dict[str, list[Any]] = {cid: [] for cid in self.camera_ids}
        #: Alerting observations awaiting their frame, sealed once the
        #: observation itself is in the store.
        to_seal: dict[str, list[Any]] = {}
        last_flush = time.monotonic()
        while not self._stop.is_set():
            progressed = False
            for cid, q in queues.items():
                try:
                    frame = q.get(timeout=0.05)
                except Exception:
                    continue
                if frame is None:
                    continue
                progressed = True
                now = time.monotonic()
                if now - last_sample.get(cid, 0.0) < SAMPLE_MIN_S:
                    with self._lock:
                        self._stats[cid]["dropped"] += 1
                    continue
                last_sample[cid] = now
                t0 = time.perf_counter()
                try:
                    pipe = pipes[cid]
                    obs = pipe.process(frame)
                    boxes = _boxes_from_pipe(pipe, cid, frame)
                    _write_json(BOX_DIR / f"{cid}.json", {
                        "camera_id": cid,
                        "ts": time.time(),
                        "boxes": boxes,
                    })
                    plates_now = sum(1 for o in obs or [] if getattr(o, "plate", None))
                    if obs:
                        pending[cid].extend(obs)
                        for o in obs:
                            for match in watch.match(o):
                                alerts.process(match)
                                # Hold the frame for sealing *after* the
                                # observation is persisted. Observations are
                                # batched and flushed up to 0.8s later, so
                                # sealing here would write the manifest against
                                # a row that does not exist yet: the back-link
                                # update matches nothing and the subsequent
                                # insert then stores evidence_ref = NULL. The
                                # frame is sealed, and the sighting still
                                # reports "no evidence available".
                                if evidence is not None:
                                    to_seal.setdefault(
                                        cid, []).append((o, frame.image))
                    dt_ms = (time.perf_counter() - t0) * 1000
                    times = fps_times[cid]
                    times.append(now)
                    times[:] = [t for t in times if now - t <= 2.0]
                    det_fps = None
                    if len(times) >= 2:
                        span = times[-1] - times[0]
                        if span > 0:
                            det_fps = round((len(times) - 1) / span, 2)
                    lats = lat_ms[cid]
                    lats.append(dt_ms)
                    if len(lats) > 300:
                        del lats[:len(lats) - 300]
                    ordered = sorted(lats)
                    def _pct(pc: float) -> float | None:
                        if not ordered:
                            return None
                        k = min(len(ordered) - 1,
                                max(0, int(round((pc / 100.0) * (len(ordered) - 1)))))
                        return round(ordered[k], 1)
                    with self._lock:
                        row = self._stats[cid]
                        row["ai"] = "ACTIVE"
                        row["frames"] += 1
                        row["last_ms"] = round(dt_ms, 1)
                        row["detector_fps"] = det_fps
                        row["queue_depth"] = q.qsize()
                        row["inference_p50_ms"] = _pct(50)
                        row["inference_p95_ms"] = _pct(95)
                        # Sticky for the session. Set per frame it flipped to
                        # UNAVAILABLE on every frame without a plate - most of
                        # them - so a worker reading plates reported that it
                        # was not, nine samples in ten.
                        row["plates_read"] = row.get("plates_read", 0) + plates_now
                        row["anpr"] = "MEASURED" if row["plates_read"] else "RUNNING"
                except Exception:
                    log.exception("ai worker frame failed camera=%s", cid)
                    with self._lock:
                        self._stats[cid]["ai"] = "DEGRADED"
            if time.monotonic() - last_flush > 0.8:
                for cid, rows in pending.items():
                    if not rows:
                        continue
                    try:
                        persist_pipeline(store, rows, pipes[cid])
                    except Exception:
                        log.exception("ai worker persist failed camera=%s", cid)
                        to_seal.pop(cid, None)
                        continue
                    # The observation now exists, so the manifest can name it
                    # and the back-link resolves.
                    for o, image in to_seal.pop(cid, []):
                        try:
                            # Idempotent per observation: two manifests for one
                            # sighting sit at different points in the hash chain
                            # and are indistinguishable in an export.
                            if evidence.find_by_observation(
                                    o.observation_id) is None:
                                evidence.create(o, frame=image,
                                                device=f"ai-worker:{cid}",
                                                actor="ai.worker")
                                log.info("sealed evidence for %s on %s",
                                         o.observation_id, cid)
                        except Exception:
                            # Evidence must never take down the alert that
                            # needed it.
                            log.exception("evidence seal failed for %s",
                                          o.observation_id)
                    rows.clear()
                last_flush = time.monotonic()
            if not progressed:
                time.sleep(0.02)
        mgr.stop_all()
        return 0

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(0.7):
            with self._lock:
                cameras = {cid: dict(row) for cid, row in self._stats.items()}
            _write_json(RUN / "ai_worker.json", {
                "pid": self.pid,
                "ts": time.time(),
                "cameras": cameras,
                "label": "MEASURED from isolated AI worker; video plane is separate",
            })


#: How many cameras one worker analyses concurrently. Inference is the real
#: constraint, not the roster: measured on this host, CPU-only, four cameras
#: run at roughly 1.4 fps each for about 5.6 fps aggregate. Raising this does
#: not buy coverage, it divides the same frames more thinly — so it is a
#: deployment decision, exposed rather than hardcoded.
AI_CAMERA_LIMIT = int(os.environ.get("SAAKSHYA_AI_CAMERA_LIMIT", "4") or 4)

#: Order in which a scarce analysis slot is worth spending, best first.
#: GOOD and DEGRADED can yield a registration mark. UNKNOWN has never been
#: graded and might — and analysing it is what produces the evidence either
#: way. UNSUITABLE has been *measured* unable to read a plate at this geometry,
#: so it is the worst use of a slot when anything else is waiting; it still
#: earns a place once the better bands are exhausted, because vehicle and
#: person detection work on a camera that cannot resolve a plate.
_ANPR_PRIORITY = {"GOOD": 0, "DEGRADED": 1, "UNKNOWN": 2, "": 2, "UNSUITABLE": 3}


def _default_ai_cameras(db_url: str, limit: int | None = None) -> list[str]:
    """Cameras that have a stream, ordered by what a slot can yield there.

    The default was the literal "OWN-TRAFFIC", which on this estate has no
    source at all: the worker started, logged `ai worker has no source for
    OWN-TRAFFIC`, and sat there. Every figure on the Model 4 panel read
    NOT_MEASURED and the masthead said AI DEGRADED — not because anything had
    failed, but because nothing had been asked to run. A default that cannot
    work is worse than no default, because it looks configured.

    Choosing real cameras fixed that and introduced a quieter fault: the
    replacement sorted by `camera_id` and took the first four. Measured against
    `var/live.db` on 22 Sep 2026 that selected cam01..cam04, **all four graded
    UNSUITABLE for ANPR**, while 21 cameras that had never been graded sat
    idle. Every scarce slot was spent on a camera already measured unable to
    read a plate. Alphabetical order is not a capability judgement, and this
    platform's whole argument is that capability is measured rather than
    assumed.

    Ordering by grade does not conjure throughput — on an estate where nothing
    grades GOOD it simply stops the worst allocation — and the tie inside a
    band stays alphabetical so the choice is reproducible.
    """
    limit = AI_CAMERA_LIMIT if limit is None else limit
    try:
        from saakshya.store.repository import Store

        store = Store(db_url)
        store.create_all()
        rows = [c for c in store.list_cameras()
                if (c.get("rtsp_url") or "").strip()
                and not str(c.get("camera_id", "")).startswith("CTL-")
                and c.get("enabled") is not False]
        if not rows:
            return []

        ids = [str(c["camera_id"]) for c in rows]
        best: dict[str, int] = {}
        try:
            for cap in store.list_capability(ids):
                cid = str(cap.get("camera_id"))
                grade = (cap.get("anpr_grade") or "UNKNOWN").upper()
                rank = _ANPR_PRIORITY.get(grade, 2)
                # A camera is graded per time band; keep its best showing.
                best[cid] = min(rank, best.get(cid, 99))
        except Exception:
            # An ungraded estate is the normal state on day one, and a
            # capability table that cannot be read is not a reason to analyse
            # nothing. Fall through with every camera equal.
            log.warning("could not read capability grades; "
                        "falling back to registry order", exc_info=True)

        rows.sort(key=lambda c: (best.get(str(c["camera_id"]), 2),
                                 str(c["camera_id"])))
        return [str(c["camera_id"]) for c in rows[:limit]]
    except Exception:
        log.exception("could not choose default AI cameras")
        return []


def boot_ai_worker(db_url: str, cameras: list[str] | None = None
                   ) -> Any:
    """Spawn the worker as a subprocess from the API process."""
    import subprocess

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    flag = os.environ.get("SAAKSHYA_AI_WORKER", "1").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return None
    raw = os.environ.get("SAAKSHYA_AI_CAMERAS", "").strip()
    if cameras is None:
        cameras = [c.strip() for c in raw.split(",") if c.strip()]
    if not cameras:
        cameras = _default_ai_cameras(db_url)
    if not cameras:
        return None
    RUN.mkdir(parents=True, exist_ok=True)
    LOGS = ROOT / "var" / "logs"
    LOGS.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Device: MPS when present, unless SAAKSHYA_FORCE_CPU=1 (see run()).
    logf = open(LOGS / "ai_worker.log", "ab")
    cmd = [
        sys.executable, "-m", "saakshya.analytics.worker",
        "--db", db_url,
        "--cameras", ",".join(cameras),
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env, stdout=logf, stderr=subprocess.STDOUT)
    log.info("ai worker spawned pid=%s cameras=%s", proc.pid, cameras)
    return proc


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Isolated Saakshya AI worker")
    parser.add_argument("--db", default=os.environ.get("SAAKSHYA_DB", "sqlite:///var/live.db"))
    parser.add_argument("--cameras", default=os.environ.get("SAAKSHYA_AI_CAMERAS", "OWN-TRAFFIC"))
    args = parser.parse_args(argv)
    cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]
    return Worker(args.db, cameras).run()


if __name__ == "__main__":
    raise SystemExit(main())
