"""Command-home KPIs derived from the store. No invented detections."""
from __future__ import annotations

import copy
import threading
import time
import weakref
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select

from saakshya.command.domain import RANK_EQUIVALENCE
from saakshya.live.annotate import live_boxes
from saakshya.store import Store, from_us, to_us
from saakshya.store import schema as S

NA = "NOT_MEASURED"
SUMMARY_TTL_S = 2.0
_SUMMARY_CACHE: weakref.WeakKeyDictionary[Store, tuple[float, dict[str, Any]]] = (
    weakref.WeakKeyDictionary()
)
_SUMMARY_LOCK = threading.RLock()


def live_object_counts(store: Store, camera_id: str, *, window_s: float = 12.0
                       ) -> dict[str, Any]:
    boxes = live_boxes(store, camera_id, overlay="full")
    return {
        "camera_id": camera_id,
        "people": boxes["people"],
        "vehicles": boxes["vehicles"],
        "tracked": boxes["tracked"],
        "plates": boxes["plates"],
        "classes": boxes.get("classes") or {},
        "window_s": window_s,
        "note": "Counts are recent store observations, not a live detector HUD.",
        "source": "store observations in the overlay window",
        "label": "MEASURED from this store",
    }


def scene_dashboard(store: Store, camera_id: str) -> dict[str, Any]:
    """CURRENT SCENE panel: people/vehicles/tracked/plates/watchlist/alerts."""
    counts = live_object_counts(store, camera_id)
    with store.engine.connect() as c:
        open_alerts = c.execute(
            select(func.count()).select_from(S.alerts).where(
                S.alerts.c.camera_id == camera_id,
                S.alerts.c.status.in_(("OPEN", "ACKNOWLEDGED", "INVESTIGATING")),
            )).scalar() or 0
        wl_hits = c.execute(
            select(func.count()).select_from(S.alerts).where(
                S.alerts.c.camera_id == camera_id)).scalar() or 0
    counts["watchlist"] = wl_hits
    counts["alerts"] = open_alerts
    return counts


def _kpi(value: Any, *, source: str, label: str,
         display: Any | None = None) -> dict[str, Any]:
    if value is None and display is None:
        display = NA
    elif display is None:
        display = value
    return {
        "value": value,
        "display": display,
        "source": source,
        "label": label,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "scope": "this API process / this store",
    }


def _api_rss_mb() -> float | None:
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(usage / (1024 * 1024) if usage > 10_000_000 else usage / 1024, 1)
    except Exception:
        return None


def _api_cpu_percent() -> float | None:
    try:
        import psutil  # type: ignore
        return float(psutil.Process().cpu_percent(interval=0.05))
    except Exception:
        return None


def command_summary(store: Store) -> dict[str, Any]:
    now_mono = time.monotonic()
    with _SUMMARY_LOCK:
        hit = _SUMMARY_CACHE.get(store)
        if hit is not None and now_mono - hit[0] < SUMMARY_TTL_S:
            return copy.deepcopy(hit[1])
    cams = store.list_cameras()
    health = store.list_health()
    streaming = sum(1 for h in health.values() if h.get("state") == "STREAMING")
    down = sum(1 for h in health.values() if h.get("state") in {"DOWN", "FAILED"})
    minute_ago = to_us(datetime.now(UTC) - timedelta(minutes=1))
    with store.engine.connect() as c:
        # One table pass replaces four independent full scans. This matters on
        # the live SQLite store, where analytics can append while the command
        # wall is polling this endpoint.
        totals = c.execute(select(
            func.count(),
            func.sum(case((S.observations.c.object_type == "person", 1), else_=0)),
            func.sum(case((S.observations.c.object_type != "person", 1), else_=0)),
            func.sum(case((S.observations.c.plate.is_not(None), 1), else_=0)),
            func.max(S.observations.c.t_ingest_us),
        ).select_from(S.observations)).one()
        n_obs = int(totals[0] or 0)
        n_person = int(totals[1] or 0)
        n_vehicle = int(totals[2] or 0)
        n_plate = int(totals[3] or 0)
        latest = totals[4]
        recent = c.execute(select(
            func.count(),
            func.sum(case((S.observations.c.plate.is_not(None), 1), else_=0)),
        ).select_from(S.observations).where(
            S.observations.c.t_ingest_us >= minute_ago)).one()
        events_min = int(recent[0] or 0)
        anpr_min = int(recent[1] or 0)
        open_alerts = c.execute(
            select(func.count()).select_from(S.alerts).where(
                S.alerts.c.status == "OPEN")).scalar() or 0
    ram = _api_rss_mb()
    cpu = _api_cpu_percent()
    kpis = {
        "cameras_online": _kpi(
            streaming, source="camera_health.state == STREAMING",
            label="MEASURED from this store"),
        "cameras_degraded": _kpi(
            max(0, len(cams) - streaming - down),
            source="onboarded - STREAMING - DOWN/FAILED",
            label="MEASURED from this store"),
        "active_whep": _kpi(
            None, display=NA,
            source="browser WHEP sessions are not counted in the API process",
            label=NA),
        "preview": _kpi(
            None, display=NA,
            source="PREVIEW tiles are a browser wall classification",
            label=NA),
        "ai_streams": _kpi(
            None, display=NA,
            source="no live AI worker is attached to this API process",
            label=NA),
        "active_alerts": _kpi(
            open_alerts, source="alerts.status == OPEN",
            label="MEASURED from this store"),
        "anpr_reads_per_min": _kpi(
            anpr_min, source="observations with plate in the last 60s",
            label="MEASURED from this store"),
        "vehicles": _kpi(
            n_vehicle, source="observations.object_type != person (store total)",
            label="MEASURED from this store"),
        "people": _kpi(
            n_person, source="observations.object_type == person (store total)",
            label="MEASURED from this store"),
        "events_per_min": _kpi(
            events_min, source="observations ingested in the last 60s",
            label="MEASURED from this store"),
        "ai_latency_p50": _kpi(
            None, display=NA,
            source="inference latency is not sampled in the API process",
            label=NA),
        "ai_latency_p95": _kpi(
            None, display=NA,
            source="inference latency is not sampled in the API process",
            label=NA),
        "watchlist_alert_latency": _kpi(
            None, display=NA,
            source="DETECTION→ALERT latency requires a timed match run",
            label=NA),
    }
    # The AI worker is a separate process and publishes a heartbeat the API can
    # read. Reporting NOT_MEASURED while that file sits on disk, fresh, was the
    # API declining to look rather than the figure being unavailable. A stale
    # or absent heartbeat still reports NOT_MEASURED - an unknown number is
    # never rendered as a zero.
    try:
        from saakshya.analytics.worker import read_heartbeat
        _hb = read_heartbeat() or {}
    except Exception:
        _hb = {}
    _live_hb = bool(_hb.get("pid")) and not _hb.get("stale")
    _rows = [r for r in (_hb.get("cameras") or {}).values() if isinstance(r, dict)]
    _active = [r for r in _rows if str(r.get("ai")) == "ACTIVE"]
    #: Cameras that have something to analyse. The registry also holds
    #: capacity slots with no stream, and counting those would flatter
    #: the ratio in the wrong direction.
    _streamable = sum(1 for c in cams if (c.get("rtsp_url") or "").strip())

    def _sum(field: str) -> float | None:
        vals = [r.get(field) for r in _active if isinstance(r.get(field), (int, float))]
        return round(sum(vals), 2) if vals else None

    def _worst(field: str) -> float | None:
        """The slowest camera, not an average: a percentile averaged across
        cameras describes no camera that exists."""
        vals = [r.get(field) for r in _active if isinstance(r.get(field), (int, float))]
        return round(max(vals), 1) if vals else None

    _det = _sum("detector_fps") if _live_hb else None
    _q = _sum("queue_depth") if _live_hb else None
    _p50 = _worst("inference_p50_ms") if _live_hb else None
    _p95 = _worst("inference_p95_ms") if _live_hb else None
    _src = "AI worker heartbeat (var/run/ai_worker.json)"

    resources = {
        "ai_workers": _kpi(
            1 if _live_hb else None, display=("1" if _live_hb else NA),
            source=(f"{_src} — pid {_hb.get('pid')}" if _live_hb
                    else "no live AI worker heartbeat"),
            label="MEASURED" if _live_hb else NA),
        "detector_fps": _kpi(
            _det, display=(str(_det) if _det is not None else NA),
            source=(f"{_src} — summed over {len(_active)} active camera(s)"
                    if _det is not None else
                    "no active AI camera is reporting a detector rate"),
            label="MEASURED" if _det is not None else NA),
        "ocr_fps": _kpi(None, display=NA,
                        source="OCR runs inside the detector pass and is not "
                               "timed separately",
                        label=NA),
        "inference_p50": _kpi(
            _p50, display=(f"{_p50} ms" if _p50 is not None else NA),
            source=(f"{_src} — rolling window, slowest active camera"
                    if _p50 is not None else "no inference samples yet"),
            label="MEASURED" if _p50 is not None else NA),
        "inference_p95": _kpi(
            _p95, display=(f"{_p95} ms" if _p95 is not None else NA),
            source=(f"{_src} — rolling window, slowest active camera"
                    if _p95 is not None else "no inference samples yet"),
            label="MEASURED" if _p95 is not None else NA),
        "queue_depth": _kpi(
            _q, display=(str(_q) if _q is not None else NA),
            source=(f"{_src} — summed over {len(_active)} active camera(s)"
                    if _q is not None else "inference queue lives in the AI worker"),
            label="MEASURED" if _q is not None else NA),
        "cpu": _kpi(
            cpu, display=cpu if cpu is not None else NA,
            source="psutil of this API process (not the AI worker)",
            label="MEASURED" if cpu is not None else NA),
        "gpu": _kpi(
            None, display=NA,
            source="GPU utilization is not sampled; never reported as 0%",
            label=NA),
        "ram": _kpi(
            ram, display=ram if ram is not None else NA,
            source="peak RSS of this API process (MB)",
            label="MEASURED" if ram is not None else NA),
    }
    payload = {
        "live_cameras": len(cams),
        "healthy": streaming,
        "degraded": max(0, len(cams) - streaming - down),
        "down": down,
        "active_alerts": open_alerts,
        "watchlist_matches": open_alerts,
        "vehicles_tracked": n_vehicle,
        "persons_detected": n_person,
        "anpr_reads_per_min": anpr_min,
        "events_per_min": events_min,
        "observations": n_obs,
        "plates_total": n_plate,
        "last_observation": from_us(latest).isoformat() if latest else None,
        "label": "MEASURED from this store — not a statewide live count",
        "kpis": kpis,
        "resources": resources,
        "isolation": {
            # The chip reports what the heartbeat says, not a fixed verdict.
            # "AI DEGRADED" was displayed permanently, including while the
            # worker was running and detecting - the masthead contradicted the
            # detections drawn on the operator's own screen.
            "ai_worker": {
                "state": ("ACTIVE" if _active else
                          ("STARTING" if _live_hb else "UNAVAILABLE")),
                "chip": ("AI ACTIVE" if _active else
                         ("AI STARTING" if _live_hb else "AI DEGRADED")),
                "label": ("MEASURED" if _live_hb else NA),
                # State the denominator. One worker analyses a handful of
                # cameras concurrently - inference throughput, not roster size
                # - and "N active cameras" on an estate of thirty reads as
                # though the other twenty-six are covered. They are not, and an
                # operator deciding where to look needs to know that.
                "note": (
                    (f"AI worker pid {_hb.get('pid')} reporting "
                     f"{len(_active)} of {_streamable} camera(s) with a "
                     f"stream under analysis. Concurrency is bounded by "
                     f"inference throughput, not by the registry.")
                    if _active else
                    ("AI worker is up and connecting to its cameras."
                     if _live_hb else
                     "No AI worker heartbeat in this API process. "
                     "Video tiles continue.")),
            },
            "ocr": {
                "state": "UNAVAILABLE",
                "chip": "OCR DEGRADED",
                "label": NA,
                "note": "OCR is not sampled in this API process. Video continues.",
            },
            "watchlist": {
                "state": "AVAILABLE",
                "chip": None,
                "label": "MEASURED from this store",
                "note": "Watchlist matches are served from this store.",
            },
            "event_bus": {
                "state": "IN_PROCESS",
                "chip": None,
                "label": "MEASURED_IN_PROCESS",
                "note": "In-process bus in this API process — not Kafka.",
            },
        },
        "rank_equivalence": [dict(row) for row in RANK_EQUIVALENCE],
        "rank_note": (
            "Gujarat Police ranks map onto the six existing product roles. "
            "Fourteen ranks are not fourteen permission sets."),
    }
    with _SUMMARY_LOCK:
        _SUMMARY_CACHE[store] = (time.monotonic(), payload)
    return copy.deepcopy(payload)
