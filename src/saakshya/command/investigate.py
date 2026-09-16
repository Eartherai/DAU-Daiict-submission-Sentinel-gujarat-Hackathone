"""Operator-facing investigation helpers on top of follow/search.

Labels TARGET / SUBJECT / VEHICLE / PERSON OF INTEREST / WATCHLIST MATCH.
The word "criminal" is never used unless the watchlist category itself is
wanted/suspect/stolen.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from saakshya.events.schema import EventType
from saakshya.store import SearchFilter, Store, from_us
from saakshya.store import schema as S
from sqlalchemy import select


WATCHLIST_SUBJECT = {
    "stolen_vehicle": "WATCHLIST MATCH",
    "wanted_vehicle": "WATCHLIST MATCH",
    "wanted_person": "PERSON OF INTEREST",
    "missing_person": "PERSON OF INTEREST",
    "missing_person_associated": "PERSON OF INTEREST",
    "suspect_vehicle": "WATCHLIST MATCH",
    "blacklisted_vehicle": "WATCHLIST MATCH",
    "investigation_target": "TARGET",
    "custom": "TARGET",
}

EVENT_TYPE_ALIASES = {
    "vehicle_detected": EventType.VEHICLE_DETECTED.value,
    "person_detected": EventType.PERSON_DETECTED.value,
    "plate_read": EventType.PLATE_READ.value,
    "watchlist_match": EventType.WATCHLIST_HIT.value,
    "camera_fault": EventType.CAMERA_FAULT.value,
    "camera_reconnected": EventType.CAMERA_RECONNECTED.value,
    "vehicle_follow": EventType.VEHICLE_FOLLOW.value,
    "route_update": EventType.ROUTE_UPDATE.value,
}


def subject_label(*, plate: str | None, object_type: str | None,
                  category: str | None) -> str:
    if category:
        mapped = WATCHLIST_SUBJECT.get(str(category).lower())
        if mapped:
            return mapped
    kind = (object_type or "").lower()
    if kind == "person":
        return "PERSON OF INTEREST"
    if plate:
        return "VEHICLE"
    return "TARGET"


def entity_tracking(follow: dict[str, Any], *,
                    category: str | None = None) -> dict[str, Any]:
    """Command-center tracking card from follow-vehicle output."""
    route = list(follow.get("route") or [])
    hops: list[dict[str, Any]] = []
    for i, node in enumerate(route):
        role = "FIRST DETECTION" if i == 0 else (
            "CURRENT / LAST SEEN" if i == len(route) - 1 else "NEXT")
        hops.append({
            "role": role,
            "camera_id": node.get("camera_id"),
            "signal": node.get("site") or node.get("district") or node.get("camera_id"),
            "t": node.get("t_norm") or node.get("t"),
            "observation_id": node.get("observation_id"),
            "evidence_ref": node.get("evidence_ref"),
            "plate": node.get("plate"),
        })
    transitions = []
    for contra in follow.get("contradictions") or []:
        km = None
        if contra.get("distance_m") is not None:
            km = round(float(contra["distance_m"]) / 1000.0, 2)
        elapsed = contra.get("elapsed_s")
        est = contra.get("minimum_observed_s") or contra.get("estimated_minimum_s")
        if est is None and km:
            est = round((km / 200.0) * 3600.0, 1)
        transitions.append({
            "from_camera": contra.get("from_camera"),
            "to_camera": contra.get("to_camera"),
            "distance_km": km,
            "elapsed_s": elapsed,
            "expected_minimum_s": est,
            "implied_speed_kmh": contra.get("implied_speed_kmh"),
            "reason": contra.get("reason"),
            "result": "CONTRADICTION",
            "confidence": 0.0,
        })
    for cand in follow.get("candidates") or []:
        transitions.append({
            "from_camera": cand.get("from_camera"),
            "to_camera": cand.get("camera_id"),
            "distance_km": round(float(cand["distance_m"]) / 1000.0, 2)
            if cand.get("distance_m") is not None else None,
            "elapsed_s": cand.get("elapsed_s") or cand.get("dt_s"),
            "expected_minimum_s": cand.get("travel_p05_s"),
            "reason": cand.get("why") or cand.get("reason") or "feasible follow-up",
            "result": "CANDIDATE",
            "confidence": cand.get("score") or cand.get("confidence"),
        })
    plate = None
    if hops:
        plate = hops[0].get("plate")
    return {
        "target": subject_label(plate=plate, object_type=None, category=category),
        "identifier": plate or follow.get("plate"),
        "first": hops[0] if hops else None,
        "hops": hops,
        "current": hops[-1] if hops else None,
        "transitions": transitions,
        "jump": {
            "previous": hops[-2]["camera_id"] if len(hops) >= 2 else None,
            "current": hops[-1]["camera_id"] if hops else None,
            "next": None,
        },
        "follow": follow,
        "label": "MEASURED from store observations; contradictions are not dropped",
    }


def event_search(store: Store, *, camera: str | None = None,
                 department: str | None = None, location: str | None = None,
                 plate: str | None = None, person: bool = False,
                 vehicle: bool = False, event_type: str | None = None,
                 watchlist: bool = False, severity: str | None = None,
                 min_confidence: float | None = None,
                 t_from: datetime | None = None, t_to: datetime | None = None,
                 limit: int = 200) -> dict[str, Any]:
    """Searchable events over observations + alerts. No invented rows."""
    types = None
    et = EVENT_TYPE_ALIASES.get((event_type or "").lower(), event_type)
    if person:
        types = ("person",)
    elif vehicle:
        types = ("car", "truck", "bus", "motorcycle", "van", "autorickshaw")
    filt = SearchFilter(
        plate=plate, cameras=[camera] if camera else None,
        departments=[department] if department else None,
        districts=[location] if location else None,
        object_types=types, t_from=t_from, t_to=t_to,
        min_plate_confidence=min_confidence, limit=limit)
    obs = store.search(filt)
    events: list[dict[str, Any]] = []
    for o in obs:
        inferred = EventType.PLATE_READ.value if o.plate else (
            EventType.PERSON_DETECTED.value if (o.object_type or "").lower() == "person"
            else EventType.VEHICLE_DETECTED.value)
        if et and inferred != et and event_type not in (None, "", inferred):
            continue
        events.append({
            "event_id": o.observation_id,
            "timestamp": o.t_norm.isoformat() if o.t_norm else None,
            "camera_id": o.camera_id,
            "location": o.district,
            "entity": o.plate or o.track_id,
            "event": inferred,
            "object_type": o.object_type,
            "confidence": o.detection_confidence or o.plate_confidence,
            "thumbnail": bool(o.evidence_ref),
            "evidence_ref": o.evidence_ref,
            "observation_id": o.observation_id,
            "open_video": True,
        })
    if watchlist or (et == EventType.WATCHLIST_HIT.value) or severity:
        with store.engine.connect() as c:
            q = select(S.alerts).order_by(S.alerts.c.t_norm_us.desc()).limit(limit)
            if severity:
                q = q.where(S.alerts.c.priority == severity)
            rows = [dict(r._mapping) for r in c.execute(q)]
        for a in rows:
            if camera and a.get("camera_id") != camera:
                continue
            if plate and (a.get("plate") or "").upper() != plate.upper():
                continue
            events.append({
                "event_id": a.get("alert_id"),
                "timestamp": from_us(a["t_norm_us"]).isoformat()
                if a.get("t_norm_us") else None,
                "camera_id": a.get("camera_id"),
                "location": None,
                "entity": a.get("plate"),
                "event": EventType.WATCHLIST_HIT.value,
                "object_type": "vehicle",
                "confidence": a.get("confidence"),
                "thumbnail": False,
                "evidence_ref": a.get("observation_id"),
                "observation_id": a.get("observation_id"),
                "open_video": True,
                "severity": a.get("priority"),
                "status": a.get("status"),
            })
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return {"events": events[:limit], "count": min(len(events), limit),
            "provenance": "store observations and alerts — not a live detector log"}


def jump_payload(store: Store, observation_id: str) -> dict[str, Any]:
    with store.engine.connect() as c:
        r = c.execute(select(S.observations).where(
            S.observations.c.observation_id == observation_id)).first()
    if r is None:
        return {"error": "no such observation"}
    m = dict(r._mapping)
    cam = store.get_camera(m["camera_id"]) or {}
    return {
        "observation_id": observation_id,
        "camera_id": m["camera_id"],
        "signal": cam.get("site") or cam.get("road") or cam.get("district"),
        "event_time": from_us(m["t_norm_us"]).isoformat() if m.get("t_norm_us") else None,
        "pts_s": m.get("pts_s"),
        "plate": m.get("plate"),
        "object_type": m.get("object_type"),
        "location": {"lat": cam.get("lat"), "lon": cam.get("lon"),
                     "district": cam.get("district")},
        "open_video": True,
    }


def recent_plates(store: Store, limit: int = 48) -> dict[str, Any]:
    rows = store.recent_marks(limit)
    out = []
    for m in rows:
        cam = store.get_camera(m["camera_id"]) or {}
        out.append({
            **m,
            "location": m.get("district") or cam.get("site"),
            "lat": cam.get("lat"), "lon": cam.get("lon"),
            "confidence": m.get("votes"),
            "vehicle_class": m.get("object_type"),
            "crop_url": (f"/cameras/{m['camera_id']}/plate.jpg?plate={m['plate']}"
                         if m.get("plate") else None),
        })
    return {"plates": out, "count": len(out)}


__all__ = [
    "entity_tracking", "event_search", "jump_payload",
    "recent_plates", "subject_label",
]
