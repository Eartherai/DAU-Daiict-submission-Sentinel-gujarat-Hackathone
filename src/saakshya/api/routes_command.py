"""Command-center APIs: KPIs, federation, overlays, events, tracking."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from saakshya.api.deps import (
    AuthDep,
    ConcurrencyGuard,
    StateDep,
    access_error,
    parse_time,
)
from saakshya.command.investigate import (
    entity_tracking,
    event_search,
    jump_payload,
    recent_plates,
    subject_label,
)
from saakshya.command.summary import command_summary, live_object_counts
from saakshya.federation.adapters import demo_connected_systems
from saakshya.live.annotate import live_boxes
from saakshya.security import AccessError, Permission

router = APIRouter(prefix="/command", tags=["command"])

VIEW_MODES = (
    {"id": "video", "label": "VIDEO ONLY",
     "overlay": "off", "people": False, "vehicles": False, "anpr": False},
    {"id": "vehicles", "label": "VIDEO + VEHICLES",
     "overlay": "vehicles", "people": False, "vehicles": True, "anpr": False},
    {"id": "people", "label": "VIDEO + PEOPLE",
     "overlay": "people", "people": True, "vehicles": False, "anpr": False},
    {"id": "both", "label": "VIDEO + VEHICLES + PEOPLE",
     "overlay": "full", "people": True, "vehicles": True, "anpr": False},
    {"id": "anpr", "label": "VIDEO + ANPR",
     "overlay": "anpr", "people": False, "vehicles": True, "anpr": True},
    {"id": "full", "label": "FULL INTELLIGENCE",
     "overlay": "full", "people": True, "vehicles": True, "anpr": True},
    {"id": "incident", "label": "INCIDENT MODE",
     "overlay": "full", "people": True, "vehicles": True, "anpr": True},
)

PRESETS = (
    {"id": "control-room", "label": "CONTROL ROOM", "wall": 12, "mode": "video"},
    {"id": "overview-30", "label": "30-CAMERA OVERVIEW", "wall": 30, "mode": "video"},
    {"id": "traffic", "label": "TRAFFIC INTELLIGENCE", "wall": 12, "mode": "anpr"},
    {"id": "person-search", "label": "PERSON SEARCH", "wall": 9, "mode": "people"},
    {"id": "watchlist-incident", "label": "WATCHLIST INCIDENT",
     "wall": 4, "mode": "full", "opens": "alerts"},
    {"id": "designated-vehicle", "label": "DESIGNATED VEHICLE",
     "wall": 4, "mode": "anpr", "opens": "investigate"},
)

SCHEDULER_TIERS = (
    {"id": "PRIMARY", "ai": "full", "note": "selected / incident cameras"},
    {"id": "SECONDARY", "ai": "moderate", "note": "corridor neighbours"},
    {"id": "PREVIEW", "ai": "low cadence", "note": "wall density tiles"},
    {"id": "INACTIVE", "ai": "event-driven", "note": "idle until demanded"},
)


@router.get("/summary", summary="Command-center home KPIs from this store")
async def summary(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    kpis = command_summary(state.store)
    ops = state.investigation.operational_summary(ctx)
    kpis["operational"] = {
        "cameras": ops.get("cameras"),
        "alerts_open": (ops.get("alerts") or {}).get("open"),
        "distinct_plates": (ops.get("observations") or {}).get("distinct_plates"),
    }
    return kpis


@router.get("/modes", summary="Operator viewing modes (no stream restart)")
async def modes(ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {"modes": list(VIEW_MODES),
            "toggles": ["VIDEO", "VEHICLES", "PEOPLE", "ANPR", "TRACKING", "WATCHLIST"],
            "compare": True,
            "note": "Overlay is metadata on native video; toggling does not reconnect."}


@router.get("/presets", summary="Demo wall presets")
async def presets(ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {"presets": list(PRESETS)}


@router.get("/systems", summary="Connected VMS adapters (DEMO/TEST unless labelled)")
async def systems(ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {
        "systems": demo_connected_systems(),
        "provenance": "DEMO/TEST adapter rows — not government VMS integrations",
        "contract": ["discover_cameras", "get_camera_status", "get_stream_url",
                     "get_metadata", "subscribe_events", "health_check"],
    }


@router.get("/scheduler", summary="Selective analytics tiers")
async def scheduler(ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {
        "tiers": list(SCHEDULER_TIERS),
        "architecture": "regional ingest + selective central analytics",
        "label": "DESIGNED / WORKING locally — not a statewide GPU pool measurement",
    }


@router.get("/evaluation-mode", summary="50-camera evaluation composition")
async def evaluation_mode(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    n = len(state.store.list_cameras())
    return {
        "target": 50,
        "real_evaluation_feeds_available": 30,
        "synthetic_control": 20,
        "onboarded_in_this_store": n,
        "note": ("50-camera evaluation mode = 30 real Sentinel probe IDs + "
                 "20 labelled synthetic/control. Do not claim 50 government streams."),
        "label": "DESIGNED composition; real count is MEASURED_REAL = 30 probe IDs",
    }


@router.get("/cameras/{camera_id}/boxes", summary="Live metadata overlay (native video)")
async def boxes(state: StateDep, ctx: AuthDep, camera_id: str,
                overlay: str = "full",
                people: bool = True, vehicles: bool = True,
                anpr: bool = True) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc
    payload = live_boxes(state.store, camera_id, overlay=overlay,
                         people=people, vehicles=vehicles, anpr=anpr)
    payload["counts"] = live_object_counts(state.store, camera_id)
    return payload


@router.get("/cameras/{camera_id}/counts", summary="People / vehicles / tracked")
async def counts(state: StateDep, ctx: AuthDep, camera_id: str
                 ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc
    return live_object_counts(state.store, camera_id)


@router.get("/events", summary="Searchable events")
async def events(
    state: StateDep, ctx: AuthDep,
    camera: str | None = None,
    department: str | None = None,
    location: str | None = None,
    plate: str | None = None,
    person: bool = False,
    vehicle: bool = False,
    event_type: str | None = None,
    watchlist: bool = False,
    severity: str | None = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    t_from: str | None = None,
    t_to: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict[str, Any]:
    try:
        ctx.authorise(Permission.SEARCH_PLATE)
    except AccessError as exc:
        raise access_error(exc) from exc
    return event_search(
        state.store, camera=camera, department=department, location=location,
        plate=plate, person=person, vehicle=vehicle, event_type=event_type,
        watchlist=watchlist, severity=severity, min_confidence=min_confidence,
        t_from=parse_time(t_from, "t_from"), t_to=parse_time(t_to, "t_to"),
        limit=limit)


@router.get("/plates", summary="Recent ANPR reads")
async def plates(state: StateDep, ctx: AuthDep,
                 limit: Annotated[int, Query(ge=1, le=200)] = 48
                 ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return recent_plates(state.store, limit)


@router.get("/jump/{observation_id}", summary="Jump-to-event payload")
async def jump(state: StateDep, ctx: AuthDep, observation_id: str
               ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    payload = jump_payload(state.store, observation_id)
    if payload.get("error"):
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": payload["error"]})
    cam = state.store.get_camera(payload["camera_id"]) or {}
    try:
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc
    return payload


@router.get("/track/{plate}", summary="TRACK THIS ENTITY — hop card + GIS + video")
async def track(state: StateDep, ctx: AuthDep, plate: str,
                t_from: str | None = None, t_to: str | None = None
                ) -> dict[str, Any]:
    tf, tt = parse_time(t_from, "t_from"), parse_time(t_to, "t_to")
    try:
        async with ConcurrencyGuard(state.search_sem, what="searches"):
            follow = state.investigation.follow_vehicle(
                ctx, plate=plate, t_from=tf, t_to=tt, limit=40)
    except AccessError as exc:
        raise access_error(exc) from exc
    category = None
    try:
        entries = state.investigation.watchlist.active_entries(plate)
        if entries:
            category = str(entries[0].category)
    except Exception:
        category = None
    card = entity_tracking(follow, category=category)
    card["subject"] = subject_label(plate=plate, object_type=None, category=category)
    return card
