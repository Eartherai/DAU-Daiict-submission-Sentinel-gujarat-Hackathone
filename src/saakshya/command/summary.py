"""Command-home KPIs derived from the store. No invented detections."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from saakshya.live.annotate import live_boxes
from saakshya.store import Store, from_us, to_us
from saakshya.store import schema as S


def live_object_counts(store: Store, camera_id: str, *, window_s: float = 12.0
                       ) -> dict[str, Any]:
    boxes = live_boxes(store, camera_id, overlay="full")
    return {
        "camera_id": camera_id,
        "people": boxes["people"],
        "vehicles": boxes["vehicles"],
        "tracked": boxes["tracked"],
        "plates": boxes["plates"],
        "window_s": window_s,
        "note": "Counts are recent store observations, not a live detector HUD.",
    }


def command_summary(store: Store) -> dict[str, Any]:
    cams = store.list_cameras()
    health = store.list_health()
    streaming = sum(1 for h in health.values() if h.get("state") == "STREAMING")
    down = sum(1 for h in health.values() if h.get("state") in {"DOWN", "FAILED"})
    minute_ago = to_us(datetime.now(UTC) - timedelta(minutes=1))
    with store.engine.connect() as c:
        n_obs = c.execute(select(func.count()).select_from(S.observations)).scalar() or 0
        n_person = c.execute(
            select(func.count()).select_from(S.observations).where(
                S.observations.c.object_type == "person")).scalar() or 0
        n_vehicle = c.execute(
            select(func.count()).select_from(S.observations).where(
                S.observations.c.object_type != "person")).scalar() or 0
        n_plate = c.execute(
            select(func.count()).select_from(S.observations).where(
                S.observations.c.plate.is_not(None))).scalar() or 0
        events_min = c.execute(
            select(func.count()).select_from(S.observations).where(
                S.observations.c.t_ingest_us >= minute_ago)).scalar() or 0
        anpr_min = c.execute(
            select(func.count()).select_from(S.observations).where(
                S.observations.c.t_ingest_us >= minute_ago,
                S.observations.c.plate.is_not(None))).scalar() or 0
        open_alerts = c.execute(
            select(func.count()).select_from(S.alerts).where(
                S.alerts.c.status == "OPEN")).scalar() or 0
        latest = c.execute(
            select(func.max(S.observations.c.t_ingest_us))).scalar()
    return {
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
    }
