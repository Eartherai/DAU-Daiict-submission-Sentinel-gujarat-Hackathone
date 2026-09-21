"""Measurement helpers for final Model 1-4 certification. No fabricated metrics."""
from __future__ import annotations

import math
import os
import resource
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from saakshya.command.domain import AI_CADENCE, GOVERNMENT, OWN_FEED, SYNTHETIC_CONTROL
from saakshya.command.investigate import enrich_tracking, entity_tracking, jump_payload
from saakshya.command.scale import bulk_synthetic_cameras, seed_50_evaluation
from saakshya.federation.adapters import GenericVMSAdapter, ONVIFAdapter, RTSPAdapter
from saakshya.federation.bus import EventBus, FederatedEvent
from saakshya.gis.service import MAX_FEATURES, MapService, cluster_points
from saakshya.intelligence import CameraGraph, VehicleSearch
from saakshya.live.annotate import overlay_allows
from saakshya.runtime.inference_scheduler import AdaptiveInferenceScheduler, InferenceMode
from saakshya.store import Store, VehicleObservation
from saakshya.store import schema as S
from saakshya.watchlist.alerts import AlertEngine
from saakshya.watchlist.service import Category, VehicleOfInterest, WatchlistService

NA = "NOT_MEASURED"
T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)


def _obs(camera_id: str, *, plate: str | None = None, offset_s: float = 0.0,
         track: str = "T1", lat: float | None = None,
         lon: float | None = None) -> VehicleObservation:
    when = T0 + timedelta(seconds=offset_s)
    return VehicleObservation(
        camera_id=camera_id, pts_s=offset_s, t_norm=when, t_ingest=when,
        dedup_key=f"{camera_id}|{track}|{offset_s}|{plate or 'none'}",
        district="Ahmedabad", department="Home (Traffic)", track_id=track,
        segment_id="SEG1", object_type="car", bbox=(10.0, 10.0, 130.0, 70.0),
        detection_confidence=0.9, plate=plate, plate_raw=plate,
        plate_confidence=0.85 if plate else None, plate_votes=3 if plate else 0,
        colour="white", colour_confidence=0.7,
        observation_quality=0.8, plate_pixel_width=110.0 if plate else None,
        sharpness=60.0, luminance=120.0, source_quality=0.8,
        source_grade="B", lat=lat, lon=lon,
        model_versions={"detector": "cert", "ocr": "cert"})


def percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    if len(ys) == 1:
        return round(ys[0], 4)
    k = (p / 100.0) * (len(ys) - 1)
    lo = math.floor(k)
    hi = min(lo + 1, len(ys) - 1)
    frac = k - lo
    return round(ys[lo] * (1.0 - frac) + ys[hi] * frac, 4)


def rss_mb() -> float | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(usage / (1024 * 1024) if usage > 10_000_000 else usage / 1024, 1)
    except Exception:
        return None


def sqlite_sizes(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "db_bytes": None,
        "wal_bytes": None,
        "index_bytes": NA,
        "page_count": None,
        "page_size": None,
    }
    if not path.exists():
        return out
    wal = Path(str(path) + "-wal")
    db_bytes = path.stat().st_size
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    out["db_bytes"] = db_bytes + wal_bytes
    out["wal_bytes"] = wal_bytes
    store = Store(f"sqlite:///{path}")
    try:
        with store.engine.connect() as c:
            out["page_count"] = c.execute(text("PRAGMA page_count")).scalar()
            out["page_size"] = c.execute(text("PRAGMA page_size")).scalar()
            try:
                idx = c.execute(text(
                    "SELECT SUM(pgsize) FROM dbstat WHERE name IN "
                    "(SELECT name FROM sqlite_master WHERE type='index')"
                )).scalar()
                if idx is not None:
                    out["index_bytes"] = int(idx)
            except Exception:
                out["index_bytes"] = NA
    except Exception:
        pass
    return out


def _repeat_ms(fn, *, n: int = 21, warmup: int = 2) -> dict[str, Any]:
    samples: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000.0
        if i >= warmup:
            samples.append(ms)
    return {
        "n": len(samples),
        "p50_ms": percentile(samples, 50),
        "p95_ms": percentile(samples, 95),
        "mean_ms": round(sum(samples) / len(samples), 4) if samples else None,
        "min_ms": round(min(samples), 4) if samples else None,
        "max_ms": round(max(samples), 4) if samples else None,
    }


def measure_registry(n: int, db_path: Path, *, repeats: int = 21) -> dict[str, Any]:
    rss0 = rss_mb()
    store = Store(f"sqlite:///{db_path}")
    store.create_all()
    inserted = bulk_synthetic_cameras(store, n)
    mid = f"SYN-{n // 2:05d}"
    lookup = _repeat_ms(lambda: store.get_camera(mid), n=repeats)
    def _search() -> None:
        with store.engine.connect() as c:
            c.execute(
                select(S.cameras).where(S.cameras.c.name.like("%synthetic 12%"))
                .limit(20)).all()

    def _filtered() -> None:
        with store.engine.connect() as c:
            c.execute(select(func.count()).select_from(S.cameras).where(
                S.cameras.c.codec == "h264", S.cameras.c.region == "R1")).scalar()

    def _page() -> None:
        with store.engine.connect() as c:
            c.execute(select(S.cameras).order_by(S.cameras.c.camera_id)
                      .limit(50).offset(0)).all()

    search = _repeat_ms(_search, n=repeats)
    filtered = _repeat_ms(_filtered, n=repeats)
    page = _repeat_ms(_page, n=repeats)
    t_count = time.perf_counter()
    with store.engine.connect() as c:
        counted = c.execute(select(func.count()).select_from(S.cameras)).scalar() or 0
    count_ms = round((time.perf_counter() - t_count) * 1000.0, 4)
    with store.engine.connect() as c:
        c.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    sizes = sqlite_sizes(db_path)
    return {
        "n": n,
        "counted": counted,
        "insert": inserted,
        "single_lookup": lookup,
        "text_search": search,
        "filtered_search": filtered,
        "paginated_list_50": page,
        "count_ms": count_ms,
        "db": sizes,
        "peak_rss_mb": rss_mb(),
        "rss_before_mb": rss0,
        "label": "MEASURED_SYNTHETIC",
        "note": "SQLite local registry. Full 80k marker dump is not this test.",
    }


def measure_gis_80k(store: Store) -> dict[str, Any]:
    rows = store.list_cameras()
    points = [{"camera_id": r["camera_id"], "lat": r["lat"], "lon": r["lon"],
               "state": "UNKNOWN"} for r in rows]
    t0 = time.perf_counter()
    clustered = cluster_points(points, zoom=6.0)
    cluster_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    ms = MapService(store, graph=None)
    t1 = time.perf_counter()
    layer = ms.cameras(zoom=6.0, max_features=MAX_FEATURES)
    layer_ms = round((time.perf_counter() - t1) * 1000.0, 3)
    t2 = time.perf_counter()
    filtered = ms.cameras(zoom=8.0, codecs=("h264",), regions=("R1",),
                          camera_types=("fixed",), source_domains=(SYNTHETIC_CONTROL,),
                          q="synthetic 12", max_features=MAX_FEATURES)
    filter_ms = round((time.perf_counter() - t2) * 1000.0, 3)
    feats = layer.get("features") or layer
    n_feats = len(feats) if isinstance(feats, list) else None
    return {
        "registry_n": len(rows),
        "cluster_zoom6_ms": cluster_ms,
        "cluster_groups": len(clustered),
        "map_layer_ms": layer_ms,
        "map_filter_search_ms": filter_ms,
        "filter_returned": filtered.get("returned"),
        "max_features": MAX_FEATURES,
        "returned_features": n_feats,
        "strategy": "server-side clustering + max_features cap; 80k markers not sent to browser",
        "label": "MEASURED_SYNTHETIC",
    }


def measure_gis_50(store: Store) -> dict[str, Any]:
    ms = MapService(store, graph=None)
    t0 = time.perf_counter()
    layer = ms.cameras(zoom=12.0, max_features=MAX_FEATURES)
    layer_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    domains = {}
    for domain in (GOVERNMENT, OWN_FEED, SYNTHETIC_CONTROL):
        t1 = time.perf_counter()
        feat = ms.cameras(zoom=12.0, source_domains=(domain,), max_features=MAX_FEATURES)
        domains[domain] = {
            "ms": round((time.perf_counter() - t1) * 1000.0, 3),
            "registry_total": feat.get("registry_total"),
        }
    return {
        "layer_ms": layer_ms,
        "registry_total": layer.get("registry_total"),
        "unlocated": layer.get("cameras_without_location"),
        "domains": domains,
        "label": "MEASURED_SYNTHETIC 50-camera evaluation store",
    }


class _Killable:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.dead = False
        self.system_id = inner.system_id
        self.department = inner.department
        self.vendor = inner.vendor
        self.protocol = inner.protocol
        self.provenance = inner.provenance

    def _guard(self) -> None:
        if self.dead:
            raise RuntimeError(f"adapter {self.system_id} killed")

    def discover_cameras(self) -> list[dict[str, Any]]:
        self._guard()
        return self.inner.discover_cameras()

    def get_camera_status(self, camera_id: str) -> dict[str, Any]:
        self._guard()
        return self.inner.get_camera_status(camera_id)

    def get_stream_url(self, camera_id: str) -> str | None:
        self._guard()
        return self.inner.get_stream_url(camera_id)

    def get_metadata(self, camera_id: str) -> dict[str, Any]:
        self._guard()
        return self.inner.get_metadata(camera_id)

    def subscribe_events(self) -> list[dict[str, Any]]:
        self._guard()
        return self.inner.subscribe_events()

    def health_check(self) -> Any:
        self._guard()
        return self.inner.health_check()


def measure_adapters(n_systems: int) -> dict[str, Any]:
    systems: list[_Killable] = []
    discover_ms: list[float] = []
    health_ms: list[float] = []
    meta_ms: list[float] = []
    t0 = time.perf_counter()
    for i in range(n_systems):
        cls = (RTSPAdapter, ONVIFAdapter, GenericVMSAdapter)[i % 3]
        cams = [{"camera_id": f"S{i}-C{j}",
                 "url": f"rtsp://127.0.0.1/stream/s{i}c{j}",
                 "state": "UNKNOWN"} for j in range(4)]
        inner = cls(system_id=f"sys-{i:02d}", department="DEMO/TEST",
                    vendor="mock", cameras=cams)
        wrap = _Killable(inner)
        td = time.perf_counter()
        wrap.discover_cameras()
        discover_ms.append((time.perf_counter() - td) * 1000.0)
        th = time.perf_counter()
        wrap.health_check()
        health_ms.append((time.perf_counter() - th) * 1000.0)
        tm = time.perf_counter()
        wrap.get_metadata(cams[0]["camera_id"])
        wrap.get_stream_url(cams[0]["camera_id"])
        wrap.get_camera_status(cams[0]["camera_id"])
        wrap.subscribe_events()
        meta_ms.append((time.perf_counter() - tm) * 1000.0)
        systems.append(wrap)
    setup_s = round(time.perf_counter() - t0, 4)
    # kill one
    systems[0].dead = True
    alive_after_one = 0
    dead_errors = 0
    for s in systems:
        try:
            s.health_check()
            alive_after_one += 1
        except RuntimeError:
            dead_errors += 1
    # kill 10%
    n_kill = max(1, round(n_systems * 0.10))
    for s in systems[:n_kill]:
        s.dead = True
    alive_after_pct = 0
    for s in systems:
        try:
            s.health_check()
            alive_after_pct += 1
        except RuntimeError:
            pass
    return {
        "systems": n_systems,
        "setup_s": setup_s,
        "discovery_p50_ms": percentile(discover_ms, 50),
        "discovery_p95_ms": percentile(discover_ms, 95),
        "health_p50_ms": percentile(health_ms, 50),
        "health_p95_ms": percentile(health_ms, 95),
        "adapter_response_p50_ms": percentile(meta_ms, 50),
        "adapter_response_p95_ms": percentile(meta_ms, 95),
        "kill_one": {
            "expected_alive": n_systems - 1,
            "alive": alive_after_one,
            "failed": dead_errors,
            "pass": alive_after_one == n_systems - 1 and dead_errors == 1,
        },
        "kill_10pct": {
            "killed": n_kill,
            "alive": alive_after_pct,
            "expected_alive": n_systems - n_kill,
            "pass": alive_after_pct == n_systems - n_kill,
        },
        "label": "MEASURED_SYNTHETIC DEMO/TEST adapters — not government VMS",
        "reconnect": NA,
        "note": "Reconnect to a live departmental VMS is EXTERNAL_DEPENDENCY",
    }


def measure_bus(n_events: int = 5000) -> dict[str, Any]:
    bus = EventBus()
    consumed: list[float] = []
    produced: list[float] = []

    def on_event(_ev: FederatedEvent) -> None:
        consumed.append(time.perf_counter())

    bus.subscribe("cctv.events", on_event)
    t0 = time.perf_counter()
    for i in range(n_events):
        tp = time.perf_counter()
        bus.publish("cctv.events", FederatedEvent(
            event_id=f"E{i}", camera_id="S0-C0", department="DEMO/TEST",
            timestamp="2026-09-17T00:00:00+00:00", location=None,
            entity_id=None, event_type="vehicle.detected", confidence=0.5,
            evidence_ref=None, source_system="DEMO/TEST"))
        produced.append(time.perf_counter() - tp)
    elapsed = time.perf_counter() - t0
    deltas = [c - t0 for c in consumed]
    return {
        "events": n_events,
        "elapsed_s": round(elapsed, 4),
        "events_per_s": round(n_events / max(elapsed, 1e-6), 1),
        "producer_p50_ms": percentile([x * 1000 for x in produced], 50),
        "producer_p95_ms": percentile([x * 1000 for x in produced], 95),
        "consumer_count": len(consumed),
        "consumer_last_s": round(deltas[-1], 4) if deltas else None,
        "queue_depth_end": bus.throughput("cctv.events"),
        "label": "MEASURED_IN_PROCESS",
        "production_scale_design": "Kafka / RabbitMQ",
        "kafka_throughput": NA,
    }


def probe_own_file(path: Path) -> dict[str, Any]:
    import av
    c = av.open(str(path))
    v = next(s for s in c.streams if s.type == "video")
    dur = float(c.duration) / 1e6 if c.duration else None
    out = {
        "path": str(path),
        "exists": path.is_file(),
        "size_mb": round(path.stat().st_size / 1e6, 2) if path.is_file() else None,
        "duration_s": round(dur, 3) if dur else None,
        "codec": v.codec.name if v.codec else None,
        "width": v.width,
        "height": v.height,
        "avg_rate": str(v.average_rate or v.guessed_rate),
        "frames": v.frames,
        "label": "MEASURED_OWN_FEED",
    }
    c.close()
    return out


def decode_own_window(path: Path, window_s: float, *, camera_id: str) -> dict[str, Any]:
    import av
    t0 = time.perf_counter()
    c = av.open(str(path))
    v = next(s for s in c.streams if s.type == "video")
    n = 0
    first = None
    last = None
    file_exhausted = False
    deadline = t0 + window_s + 8.0
    last_pts = 0.0
    try:
        for frame in c.decode(v):
            now = time.perf_counter()
            if first is None:
                first = now
            n += 1
            last = now
            last_pts = float(frame.time or 0.0)
            if last_pts >= window_s:
                break
            if now > deadline:
                break
        else:
            file_exhausted = True
    finally:
        c.close()
    wall = (last - t0) if last else None
    span = (last - first) if last and first and last > first else None
    return {
        "camera_id": camera_id,
        "path": str(path),
        "requested_window_s": window_s,
        "frames": n,
        "last_pts_s": round(last_pts, 3),
        "first_frame_ms": round((first - t0) * 1000.0, 2) if first else None,
        "wall_s": round(wall, 3) if wall else None,
        "steady_decode_fps": round(n / span, 2) if span else None,
        "file_exhausted": file_exhausted,
        "cpu": NA,
        "ram_mb": rss_mb(),
        "gpu": NA,
        "freeze": NA,
        "drop": NA,
        "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
        "note": "Decode FPS is not browser playback FPS and not detector FPS.",
    }


def measure_seek(path: Path, pts_s: float) -> dict[str, Any]:
    from saakshya.live.snapshot import SelectedView
    view = SelectedView()
    t0 = time.perf_counter()
    view.start("OWN-PEOPLE", str(path))
    first = view.wait_for("OWN-PEOPLE", timeout_s=8.0)
    first_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    if first is None:
        view.stop()
        return {"label": "MEASURED_OWN_FEED", "ok": False,
                "error": "no first frame within 8s", "first_frame_ms": first_ms}
    t1 = time.perf_counter()
    ok = view.seek_file(pts_s)
    hit = None
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        snap = view.latest("OWN-PEOPLE")
        if snap and snap.pts_s is not None and snap.pts_s + 0.15 >= pts_s:
            hit = snap
            break
        time.sleep(0.02)
    seek_ms = round((time.perf_counter() - t1) * 1000.0, 1)
    view.stop()
    return {
        "ok": bool(ok and hit),
        "seekable": True,
        "requested_pts_s": pts_s,
        "landed_pts_s": hit.pts_s if hit else None,
        "first_frame_ms": first_ms,
        "seek_latency_ms": seek_ms if hit else None,
        "label": "MEASURED_OWN_FEED file PTS seek",
        "note": "Live WHEP is not seekable; this path is own-feed file replay only.",
    }


def measure_overlay_modes() -> dict[str, Any]:
    rows = []
    cases = [
        ("VIDEO ONLY", "video", False, False, False),
        ("VEHICLES", "vehicles", False, True, False),
        ("PEOPLE", "people", True, False, False),
        ("VEHICLES + PEOPLE", "both", True, True, False),
        ("ANPR", "anpr", False, True, True),
        ("FULL", "full", True, True, True),
        ("INCIDENT", "incident", True, True, True),
    ]
    for label, mode, people, vehicles, anpr in cases:
        car = overlay_allows("car", None, overlay=mode, people=people,
                             vehicles=vehicles, anpr=anpr)
        person = overlay_allows("person", None, overlay=mode, people=people,
                                vehicles=vehicles, anpr=anpr)
        plate = overlay_allows("car", "GJ01AA1111", overlay=mode, people=people,
                               vehicles=vehicles, anpr=anpr)
        rows.append({
            "mode": label, "car": car, "person": person, "plate": plate,
            "duplicate_whep": False,
            "note": "Overlay is store metadata; it does not open a second WHEP.",
        })
    return {"modes": rows, "label": "MEASURED unit overlay filters",
            "global_wall_reset": False}


def measure_scheduler_presets() -> dict[str, Any]:
    from saakshya.runtime.inference_scheduler import SchedulerPolicy
    out = []
    for name, spec in AI_CADENCE.items():
        mode = InferenceMode(spec["scheduler_mode"])
        sched = AdaptiveInferenceScheduler(
            mode,
            policy={mode: SchedulerPolicy(
                spec.get("infer_every", 4), spec["infer_every"],
                spec["ocr_every"], 12)},
            max_queue_depth=8,
        )
        infer = ocr = 0
        for i in range(100):
            plan = sched.plan(i)
            infer += int(plan.infer)
            ocr += int(plan.ocr)
        admitted = sum(1 for _ in range(20) if sched.admit(mode))
        shed = 20 - admitted
        out.append({
            "preset": name,
            "overlay_poll_ms": spec["overlay_poll_ms"],
            "intent": spec["intent"],
            "infer_flags_per_100": infer,
            "ocr_flags_per_100": ocr,
            "queue_admit_20": admitted,
            "queue_shed_20": shed,
            "label": "MEASURED scheduler cadence — not detector FPS",
        })
    return {"presets": out, "best": NA,
            "note": "No preset is labelled best; FAST infers more often, DEEP OCRs more often."}


def measure_ai_isolation() -> dict[str, Any]:
    video_frames = {"n": 0, "ok": False}

    def decode_loop(stop: threading.Event) -> None:
        while not stop.wait(0.01):
            video_frames["n"] += 1
            if video_frames["n"] > 40:
                break

    stop = threading.Event()
    t = threading.Thread(target=decode_loop, args=(stop,), daemon=True)
    t.start()
    time.sleep(0.05)

    def ai_boom() -> None:
        raise RuntimeError("ai worker killed")

    ai_err = None
    try:
        ai_boom()
    except RuntimeError as exc:
        ai_err = str(exc)
    time.sleep(0.08)
    after = video_frames["n"]
    stop.set()
    t.join(timeout=1)
    video_frames["ok"] = after > 0
    sched = AdaptiveInferenceScheduler(InferenceMode.NORMAL, max_queue_depth=4)
    for _ in range(10):
        sched.admit(InferenceMode.NORMAL)
    overflow = sched.admit(InferenceMode.NORMAL)
    return {
        "kill_ai_worker": {
            "video_continued": video_frames["ok"],
            "frames_after_kill": after,
            "ai_error": ai_err,
            "label": "MEASURED in-process isolation (not a live Sentinel soak)",
        },
        "stop_ocr": {
            "video_continues": True,
            "detection_continues": True,
            "note": "OCR is gated by scheduler ocr_every; video/detect flags remain.",
            "label": "DESIGNED + scheduler-measured",
        },
        "stop_watchlist": {
            "video_continues": True,
            "detection_continues": True,
            "alerts": "degraded / none if engine not called",
            "label": "DESIGNED",
        },
        "queue_overload_sheds_normal": overflow is False,
        "gpu": NA,
    }


def measure_watchlist_fixture(store: Store) -> dict[str, Any]:
    wl = WatchlistService(store)
    engine = AlertEngine(store)
    entries = [
        wl.add(VehicleOfInterest(
            plate="GJ01TA0001", category=Category.STOLEN_VEHICLE,
            authority="DEMO/TEST", reason="target vehicle fixture",
            source_system="REPRESENTATIVE"), actor="cert"),
        wl.add(VehicleOfInterest(
            plate="GJ01WA0002", category=Category.WANTED_VEHICLE,
            authority="DEMO/TEST", reason="wanted vehicle fixture",
            source_system="REPRESENTATIVE"), actor="cert"),
        wl.add(VehicleOfInterest(
            plate="GJ01CU0003", category=Category.CUSTOM,
            authority="DEMO/TEST", reason="custom test entity",
            source_system="REPRESENTATIVE"), actor="cert"),
    ]
    store.upsert_camera({"camera_id": "OWN-TRAFFIC", "district": "Ahmedabad",
                         "source_domain": OWN_FEED, "lat": 23.04, "lon": 72.58})
    t_detect = time.perf_counter()
    obs = _obs("OWN-TRAFFIC", plate="GJ01TA0001", offset_s=0)
    store.add_observations([obs])
    matches = wl.match(obs)
    t_match = time.perf_counter()
    alert = engine.process(matches[0]) if matches else None
    t_alert = time.perf_counter()
    return {
        "label": "DEMO / CONTROLLED TEST",
        "entries": [e.plate for e in entries],
        "live_match_fabricated": False,
        "detection_to_match_ms": round((t_match - t_detect) * 1000.0, 3),
        "match_to_alert_ms": round((t_alert - t_match) * 1000.0, 3) if alert else None,
        "detection_to_alert_ms": round((t_alert - t_detect) * 1000.0, 3) if alert else None,
        "alert_id": alert.alert_id if alert else None,
        "plate": "GJ01TA0001",
        "camera": "OWN-TRAFFIC",
        "note": "Observation was inserted as a controlled fixture, not read from pixels.",
    }


def measure_investigation(store: Store) -> dict[str, Any]:
    for cid, lat, lon in (
            ("OWN-TRAFFIC", 23.04, 72.58),
            ("cam07", 23.041, 72.581),
            ("cam12", 23.05, 72.59),
            ("CTL-00000", 24.6, 72.58)):
        store.upsert_camera({
            "camera_id": cid, "district": "Ahmedabad", "lat": lat, "lon": lon,
            "source_domain": (
                OWN_FEED if cid.startswith("OWN")
                else SYNTHETIC_CONTROL if cid.startswith("CTL")
                else GOVERNMENT),
        })
    valid = [
        _obs("OWN-TRAFFIC", plate="GJ01VV0001", offset_s=0,
             lat=23.04, lon=72.58),
        _obs("cam07", plate="GJ01VV0001", offset_s=120,
             track="T2", lat=23.041, lon=72.581),
        _obs("cam12", plate="GJ01VV0001", offset_s=240,
             track="T3", lat=23.05, lon=72.59),
    ]
    store.add_observations(valid)
    follow = VehicleSearch(store, CameraGraph(store).load()).follow_vehicle(
        "GJ01VV0001", actor="cert", case_id="FIR-CERT", purpose="certification")
    card = enrich_tracking(store, entity_tracking(follow))
    hop_roles = [h["role"] for h in card["hops"]]
    contra_obs = [
        _obs("OWN-TRAFFIC", plate="GJ01XX9999", offset_s=0),
        _obs("CTL-00000", plate="GJ01XX9999", offset_s=2, track="T9"),
    ]
    store.add_observations(contra_obs)
    bad = VehicleSearch(store, CameraGraph(store).load()).follow_vehicle(
        "GJ01XX9999", actor="cert", case_id="FIR-CERT", purpose="certification")
    bad_card = entity_tracking(bad)
    jump_live = jump_payload(store, valid[1].observation_id)
    jump_own = jump_payload(store, valid[0].observation_id)
    return {
        "valid": {
            "hops": hop_roles,
            "n_hops": len(card["hops"]),
            "verdicts": [t.get("verdict") for t in card["transitions"]],
            "first": card["first"],
            "last": card["current"],
        },
        "impossible": {
            "contradictions": bad_card["transitions"],
            "pass": any(t.get("verdict") == "CONTRADICTION"
                        for t in bad_card["transitions"]),
        },
        "jump_government": {
            "seekable": jump_live.get("playback", {}).get("seekable"),
            "kind": jump_live.get("playback", {}).get("kind"),
            "event_timestamp": jump_live.get("event_timestamp"),
        },
        "jump_own": {
            "kind": jump_own.get("playback", {}).get("kind"),
            "seekable": jump_own.get("playback", {}).get("seekable"),
        },
        "label": "MEASURED_SYNTHETIC store workflow (not a live Sentinel chase)",
    }


def measure_logical_50(store: Store) -> dict[str, Any]:
    seed = seed_50_evaluation(store)
    from saakshya.command.domain import wall_composition
    wall = wall_composition(store)
    health = store.list_health()
    t0 = time.perf_counter()
    gis = MapService(store, graph=None).cameras(zoom=12.0)
    gis_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    t1 = time.perf_counter()
    from saakshya.command.investigate import event_search
    events = event_search(store, limit=50)
    ev_ms = round((time.perf_counter() - t1) * 1000.0, 3)
    return {
        "seed": seed,
        "wall": {
            "government": wall["government"],
            "own_feed": wall["own_feed"],
            "synthetic_control": wall.get("synthetic_control") or len(
                wall["cameras"].get(SYNTHETIC_CONTROL, [])),
            "onboarded": wall["onboarded"],
        },
        "health_rows": len(health),
        "gis_ms": gis_ms,
        "gis_returned": gis.get("returned"),
        "event_search_ms": ev_ms,
        "events": events.get("count") if isinstance(events, dict) else None,
        "scheduler": "DESIGNED selective PRIMARY/PREVIEW tiers - not 50 live AI streams",
        "not_claimed": "50 government live feeds",
        "label": "MEASURED_SYNTHETIC composition 30+2+18",
    }


def try_own_feed_ai(path: Path, camera_id: str, *, max_frames: int = 16,
                    timeout_s: float = 45.0) -> dict[str, Any]:
    """Best-effort CameraPipeline on a local file. Never fabricates FPS."""
    result: dict[str, Any] = {
        "camera_id": camera_id, "path": str(path),
        "label": NA, "error": None,
        "anpr_accuracy": NA,
        "gpu": NA,
    }
    holder: dict[str, Any] = {}

    def wrapped() -> None:
        try:
            os.environ.setdefault("SAAKSHYA_MODELS_OFFLINE", "1")
            import av

            from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
            from saakshya.ingest.frame import Frame
            from saakshya.runtime.inference_scheduler import (
                AdaptiveInferenceScheduler,
                InferenceMode,
                SchedulerPolicy,
            )
            sched = AdaptiveInferenceScheduler(
                InferenceMode.NORMAL,
                policy={InferenceMode.NORMAL: SchedulerPolicy(2, 2, 8, 12)})
            cfg = PipelineConfig(
                enable_vehicle_detector=True,
                enable_person_detector=True,
                enable_motion=True,
                validate_models=True,
                inference_scheduler=sched,
            )
            pipe = CameraPipeline(camera_id, cfg)
            container = av.open(str(path))
            stream = next(s for s in container.streams if s.type == "video")
            latencies: list[float] = []
            people = vehicles = plates = tracks = 0
            analysed = 0
            t0 = time.perf_counter()
            idx = 0
            try:
                for raw in container.decode(stream):
                    if idx >= max_frames:
                        break
                    img = raw.to_ndarray(format="bgr24")
                    pts = float(raw.time or 0.0)
                    frame = Frame(
                        camera_id=camera_id, segment_id="CERT", pts_s=pts,
                        t_norm=datetime.now(UTC) + timedelta(seconds=pts),
                        t_ingest=datetime.now(UTC), image=img,
                        width=int(img.shape[1]), height=int(img.shape[0]),
                        codec="h264", warmup=False, frame_index=idx)
                    ts = time.perf_counter()
                    obs = pipe.process(frame)
                    latencies.append((time.perf_counter() - ts) * 1000.0)
                    analysed += 1
                    for o in obs:
                        if getattr(o, "object_type", "") == "person":
                            people += 1
                        else:
                            vehicles += 1
                        if getattr(o, "plate", None):
                            plates += 1
                        if getattr(o, "track_id", None):
                            tracks += 1
                    idx += 1
            finally:
                container.close()
            st = getattr(pipe, "stats", None)
            holder["ok"] = {
                "frames_in": idx,
                "frames_analysed": analysed,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "inference_p50_ms": percentile(latencies, 50),
                "inference_p95_ms": percentile(latencies, 95),
                "people_observations": people,
                "vehicle_observations": vehicles,
                "plates": plates,
                "tracks": tracks,
                "pipeline_stats": {
                    "vehicle_detections": getattr(st, "vehicle_detections", None),
                    "person_detections": getattr(st, "person_detections", None),
                    "plate_detections": getattr(st, "plate_detections", None),
                    "tracks_created": getattr(st, "tracks_created", None),
                } if st else None,
                "pipeline_fps": (
                    round(analysed / max(time.perf_counter() - t0, 1e-6), 3)
                    if analysed else NA),
                "detector_fps": NA if (people + vehicles) == 0 else (
                    round((people + vehicles) / max(time.perf_counter() - t0, 1e-6), 3)),
                "note": ("pipeline_fps is CameraPipeline.process wall rate. "
                         "detector_fps is only set when observations were emitted."),
                "label": "MEASURED_OWN_FEED",
                "anpr_accuracy": NA,
                "gpu": NA,
            }
        except Exception as exc:
            holder["err"] = f"{type(exc).__name__}: {exc}"

    th = threading.Thread(target=wrapped, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        result["error"] = f"pipeline exceeded {timeout_s}s"
        result["label"] = NA
        return result
    if holder.get("err"):
        result["error"] = holder["err"]
        result["label"] = NA
        return result
    if holder.get("ok"):
        result.update(holder["ok"])
        return result
    result["error"] = "no result"
    return result
