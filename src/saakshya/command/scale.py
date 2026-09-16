"""Synthetic registry and federation load for labelled scale tests."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import insert, select, func

from saakshya.federation.adapters import GenericVMSAdapter, ONVIFAdapter, RTSPAdapter
from saakshya.federation.bus import EventBus, FederatedEvent
from saakshya.store import Store, now_us
from saakshya.store import schema as S


def bulk_synthetic_cameras(store: Store, n: int, *, prefix: str = "SYN"
                           ) -> dict[str, Any]:
    """Insert n labelled synthetic cameras. Not government streams."""
    t0 = time.perf_counter()
    ts = now_us()
    rows = []
    for i in range(n):
        lat = 20.0 + (i % 500) * 0.012
        lon = 68.5 + (i // 500) * 0.012
        rows.append({
            "camera_id": f"{prefix}-{i:05d}",
            "name": f"synthetic {i}",
            "department": "SYNTHETIC",
            "district": "Synthetic",
            "region": f"R{i % 8}",
            "road": f"corridor-{i % 40}",
            "lat": lat, "lon": lon,
            "vendor": "DEMO/TEST",
            "camera_type": "fixed",
            "codec": "h264" if i % 3 else "hevc",
            "width": 1920, "height": 1080,
            "tier": "C",
            "enabled": True,
            "integration_model": "SYNTHETIC",
            "maintenance_status": "demo",
            "access_state": "labelled-synthetic",
            "created_at_us": ts, "updated_at_us": ts,
        })
    chunk = 2000
    with store.engine.begin() as c:
        for off in range(0, len(rows), chunk):
            c.execute(insert(S.cameras), rows[off:off + chunk])
    return {
        "n": n, "elapsed_s": round(time.perf_counter() - t0, 4),
        "label": "SYNTHETIC",
    }


def measure_registry(store: Store) -> dict[str, Any]:
    t0 = time.perf_counter()
    n = store.list_cameras()
    list_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    one = store.get_camera(n[0]["camera_id"]) if n else None
    lookup_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    q = select(func.count()).select_from(S.cameras).where(
        S.cameras.c.codec == "h264")
    with store.engine.connect() as c:
        h264 = c.execute(q).scalar() or 0
    filter_ms = (time.perf_counter() - t2) * 1000
    t3 = time.perf_counter()
    with store.engine.connect() as c:
        hit = c.execute(
            select(S.cameras).where(S.cameras.c.name.like("%synthetic 12%"))
            .limit(20)).all()
    search_ms = (time.perf_counter() - t3) * 1000
    return {
        "cameras": len(n),
        "lookup_ms": round(lookup_ms, 3),
        "list_ms": round(list_ms, 3),
        "filter_ms": round(filter_ms, 3),
        "search_ms": round(search_ms, 3),
        "h264": h264,
        "search_hits": len(hit),
        "got": bool(one),
        "label": "SYNTHETIC" if n and (n[0].get("integration_model") == "SYNTHETIC"
                                       or str(n[0]["camera_id"]).startswith("SYN"))
        else "MIXED",
    }


def seed_50_evaluation(store: Store) -> dict[str, Any]:
    """30 real probe IDs (empty URLs) + 20 labelled synthetic/control."""
    ts = now_us()
    for i in range(1, 31):
        store.upsert_camera({
            "camera_id": f"cam{i:02d}",
            "name": f"probe {i}",
            "department": "Home (Police)",
            "district": "Ahmedabad",
            "region": "Ahmedabad",
            "lat": 23.0 + i * 0.002, "lon": 72.5 + i * 0.002,
            "codec": "h264", "enabled": True,
            "integration_model": "REAL_PROBE_ID",
            "access_state": "NOT_AUTHORITATIVE",
            "created_at_us": ts, "updated_at_us": ts,
        })
        store.upsert_health(f"cam{i:02d}", {"state": "UNKNOWN", "reachable": False})
    syn = bulk_synthetic_cameras(store, 20, prefix="CTL")
    return {
        "real_probe_ids": 30,
        "synthetic_control": syn["n"],
        "onboarded": 50,
        "label": "30 REAL_PROBE_ID + 20 SYNTHETIC/control — not 50 government streams",
    }


def adapter_load(n_systems: int) -> dict[str, Any]:
    systems = []
    t0 = time.perf_counter()
    discovered = 0
    for i in range(n_systems):
        cls = (RTSPAdapter, ONVIFAdapter, GenericVMSAdapter)[i % 3]
        cams = [{"camera_id": f"S{i}-C{j}",
                 "url": f"rtsp://127.0.0.1/stream/s{i}c{j}",
                 "state": "UNKNOWN"} for j in range(4)]
        sys = cls(system_id=f"sys-{i:02d}", department="DEMO/TEST",
                  vendor="mock", cameras=cams)
        discovered += len(sys.discover_cameras())
        sys.health_check()
        systems.append(sys)
    bus = EventBus()
    for i in range(n_systems * 10):
        bus.publish("cctv.events", FederatedEvent(
            event_id=f"E{i}", camera_id=f"S0-C0", department="DEMO/TEST",
            timestamp="2026-09-17T00:00:00+00:00", location=None,
            entity_id=None, event_type="camera.health", confidence=None,
            evidence_ref=None, source_system="DEMO/TEST"))
    return {
        "systems": n_systems,
        "discovered_cameras": discovered,
        "events": bus.throughput("cctv.events"),
        "elapsed_s": round(time.perf_counter() - t0, 4),
        "label": "SYNTHETIC DEMO/TEST adapters — not government VMS",
        "failures": 0,
    }


def analytics_logical_load(n_streams: int) -> dict[str, Any]:
    """In-process event throughput. Does not measure GPU."""
    bus = EventBus()
    t0 = time.perf_counter()
    for i in range(n_streams * 5):
        bus.publish("analytics", FederatedEvent(
            event_id=f"A{i}", camera_id=f"L-{i % max(1, n_streams):04d}",
            department="SYNTHETIC",
            timestamp="2026-09-17T00:00:00+00:00", location=None,
            entity_id=None, event_type="vehicle.detected", confidence=0.5,
            evidence_ref=None, source_system="synthetic-replay"))
    elapsed = time.perf_counter() - t0
    return {
        "logical_streams": n_streams,
        "events": bus.throughput("analytics"),
        "events_per_s": round(bus.throughput("analytics") / max(elapsed, 1e-6), 1),
        "elapsed_s": round(elapsed, 4),
        "gpu_utilization": "UNAVAILABLE",
        "inference_queue": "UNAVAILABLE — no GPU workload started",
        "p50_latency_ms": "UNAVAILABLE",
        "p95_latency_ms": "UNAVAILABLE",
        "label": "SYNTHETIC event-bus load; GPU numbers not fabricated",
    }
