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
from saakshya.command.domain import (
    AI_CADENCE,
    ARCHITECTURE_CLAIM,
    GOLDEN_IDS,
    architecture_diagram,
    product_modes,
    wall_composition,
)
from saakshya.command.investigate import (
    enrich_tracking,
    entity_tracking,
    event_search,
    jump_payload,
    recent_plates,
    subject_label,
)
from saakshya.command.summary import command_summary, live_object_counts, scene_dashboard
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
    {"id": "overview-50", "label": "50-CAMERA WALL", "wall": 50, "mode": "video",
     "domain": "all"},
    {"id": "government", "label": "GOVERNMENT MODE", "wall": 30, "mode": "video",
     "domain": "GOVERNMENT"},
    {"id": "intelligence-demo", "label": "INTELLIGENCE DEMO", "wall": 2,
     "mode": "full", "domain": "OWN_FEED", "opens": "intelligence"},
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
    # SQLite aggregation must not block health, media signaling, or alert APIs.
    # The summary functions carry their own short-lived caches; the worker
    # thread keeps a cold refresh off the FastAPI event loop.
    from fastapi.concurrency import run_in_threadpool

    def _read_summary() -> tuple[dict[str, Any], dict[str, Any]]:
        return (command_summary(state.store),
                state.investigation.operational_summary(ctx, include_marks=False))

    kpis, ops = await run_in_threadpool(_read_summary)
    alerts = ops.get("alerts") or {}
    kpis["operational"] = {
        "cameras": ops.get("cameras"),
        "alerts_open": alerts.get("open"),
        "alerts_withheld": bool(alerts.get("withheld")),
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
        "label": "DEMO / TEST",
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
    wall = wall_composition(state.store)
    return {
        "target": 50,
        "real_evaluation_feeds_available": 30,
        "government": wall["government"],
        "own_feeds": 2,
        "golden_own_feeds": list(GOLDEN_IDS),
        "synthetic_control": wall["synthetic_control"],
        "onboarded_in_this_store": n,
        "wall": wall,
        "note": ("50-camera evaluation = 30 government probe IDs + 2 own feeds "
                 "+ labelled SYNTHETIC_CONTROL fill. Not 50 government streams."),
        "label": "DESIGNED composition; government count is MEASURED_REAL probe IDs",
        "architecture": ARCHITECTURE_CLAIM,
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
    try:
        from saakshya.analytics.worker import read_boxes
        from saakshya.live.hub import get_hub
        from saakshya.live.relay import get_relay
        live: list[dict[str, Any]] = []
        source = ""
        relay = get_relay()
        if relay is not None:
            live = relay.boxes(camera_id)
            source = "ai_worker"
        if not live:
            live = read_boxes(camera_id)
            if live:
                source = "ai_worker"
        hub = get_hub()
        if not live and hub is not None:
            live = hub.boxes(camera_id)
            source = "hub_live"
        if live:
            payload["boxes"] = live
            payload["people"] = sum(1 for b in live
                                    if (b.get("object_type") or "").lower() == "person")
            payload["vehicles"] = sum(1 for b in live
                                      if (b.get("object_type") or "").lower() != "person")
            payload["tracked"] = len({b.get("track_id") for b in live if b.get("track_id")})
            payload["source"] = source or "live"
            payload["note"] = ("Boxes from the isolated AI worker on the "
                                "current frame. Not invented.")
            payload["label"] = "MEASURED"
    except Exception:
        pass
    payload["counts"] = live_object_counts(state.store, camera_id)
    payload["scene"] = scene_dashboard(state.store, camera_id)
    # Plate text over a live picture goes to roles that act on vehicles; an
    # estate administrator checking a stream sees the boxes without the marks.
    from saakshya.api.plate_access import redact_boxes
    return redact_boxes(ctx, payload)


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


@router.get("/cameras/{camera_id}/scene", summary="CURRENT SCENE dashboard")
async def scene(state: StateDep, ctx: AuthDep, camera_id: str
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
    return scene_dashboard(state.store, camera_id)


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
    # A list of recent reads with camera and time answers "where was this
    # vehicle" for every vehicle at once: it needs what the search needs,
    # is cut to the caller's jurisdiction, and is recorded.
    from saakshya.api.plate_access import audit_plate_read, in_scope, require_plate_read
    require_plate_read(ctx)
    out = recent_plates(state.store, limit)
    for key in ("plates", "reads", "marks", "items"):
        if isinstance(out.get(key), list):
            out[key] = in_scope(ctx, out[key], state.store)
            audit_plate_read(ctx, state.store, "marks_read", target="command/plates",
                             rows=len(out[key]))
            break
    return out


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
    # The jump still works - camera and time are what playback needs - but the
    # stored plate is a search result, and needs what the search needs.
    from saakshya.security import may_read_plates
    if not may_read_plates(ctx.principal):
        payload = {**payload, "plate": None, "plate_raw": None,
                   "plate_withheld": True}
    else:
        payload = {**payload, "plate_withheld": False}
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
    return enrich_tracking(state.store, card)


@router.get("/product", summary="Final product modes, domains, M4 architecture")
async def product(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    wall = wall_composition(state.store)
    return {
        "modes": product_modes(),
        "domains": ["GOVERNMENT", "OWN_FEED", "SYNTHETIC_CONTROL"],
        "golden_own_feeds": [
            {"camera_id": "OWN-PEOPLE", "name": "Own Feed A", "analytics": "FULL"},
            {"camera_id": "OWN-TRAFFIC", "name": "Own Feed B", "analytics": "FULL"},
        ],
        "wall": wall,
        "architecture": architecture_diagram(),
        "analytics_modes": [
            {"id": "off", "label": "OFF"},
            {"id": "vehicles", "label": "VEHICLES"},
            {"id": "people", "label": "PEOPLE"},
            {"id": "both", "label": "VEHICLES + PEOPLE"},
            {"id": "anpr", "label": "ANPR"},
            {"id": "full", "label": "FULL INTELLIGENCE"},
            {"id": "incident", "label": "INCIDENT"},
        ],
        "ai_cadence": AI_CADENCE,
        "claim": ARCHITECTURE_CLAIM,
    }


@router.post("/cameras/{camera_id}/seek", summary="Seek own-feed replay to event PTS")
async def seek_replay(state: StateDep, ctx: AuthDep, camera_id: str,
                      pts_s: Annotated[float, Query(ge=0)]) -> dict[str, Any]:
    from saakshya.live.snapshot import local_media_url

    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc
    if not local_media_url(camera_id):
        return {
            "ok": False,
            "seekable": False,
            "camera_id": camera_id,
            "note": ("Live WHEP cannot seek. EVENT TIMESTAMP is distinct from "
                     "CURRENT LIVE POSITION."),
        }
    selected = getattr(state.snapshots, "selected", None) if state.snapshots else None
    if selected is None or selected.camera_id != camera_id:
        return {
            "ok": False,
            "seekable": True,
            "camera_id": camera_id,
            "pts_s": pts_s,
            "note": "Open the own-feed live view first, then jump again to seek.",
        }
    ok = selected.seek_file(pts_s)
    return {"ok": ok, "seekable": True, "camera_id": camera_id, "pts_s": pts_s}
