"""GIS endpoints — the stable data contract behind the investigation map.

Every endpoint here takes the same filter vocabulary (bbox, time, district,
status, capability) so a client can hold one filter state and apply it across
layers without translating between six different query languages.

All six are read-only, all six are viewport-bounded, and none of them will
return an unbounded feature list: past a threshold they aggregate. That is a
correctness property, not a performance nicety — a map that stops responding
during an incident is worse than one that shows clusters.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from saakshya.api.deps import AuthDep, StateDep, access_error, csv_list, parse_time
from saakshya.gis import BBox
from saakshya.security import AccessError, Permission

router = APIRouter(prefix="/gis", tags=["gis"])

BBoxQuery = Annotated[str | None, Query(
    description="west,south,east,north in WGS-84 degrees. Omit for everything.",
    examples=["72.4,22.9,72.9,23.3"])]
ZoomQuery = Annotated[float, Query(ge=0, le=22,
                                   description="Map zoom; drives clustering.")]


def _bbox(raw: str | None) -> BBox:
    try:
        return BBox.parse(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_BBOX", "message": str(exc)}) from exc


def _districts(ctx: AuthDep, raw: str | None) -> tuple[str, ...] | None:
    """Requested districts, intersected with the caller's jurisdiction.

    Asking for a district outside your scope is an error rather than a silently
    empty result: an officer who does not know they were filtered will read the
    empty map as "nothing there".
    """
    requested = csv_list(raw)
    if requested:
        for d in requested:
            ctx.principal.require_scope(d)
        return requested
    return ctx.principal.scope_filter()


@router.get("/gaps", summary="Registry gap analysis (Model 1)")
async def registry_gaps(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """What the registry does not yet know about its own estate."""
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        return state.maps.registry_gaps()
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/near", summary="Cameras within a radius of a point, nearest first")
async def near(state: StateDep, ctx: AuthDep,
               lat: Annotated[float, Query(ge=-90, le=90)],
               lon: Annotated[float, Query(ge=-180, le=180)],
               radius_m: Annotated[float, Query(gt=0, le=200_000)] = 2000.0,
               limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict[str, Any]:
    """Which cameras could have seen something at this point.

    Geodesic metres from PostGIS (ST_DWithin on geography, indexed) where the
    store is PostgreSQL, and a haversine otherwise; the answer names the
    engine. Scoped to the caller's jurisdiction like every camera list.
    """
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return state.store.cameras_near(lat, lon, radius_m, limit=limit,
                                    districts=ctx.principal.scope_filter())


@router.get("/cameras", summary="Camera locations, health and capability")
async def cameras(state: StateDep, ctx: AuthDep, bbox: BBoxQuery = None,
                  zoom: ZoomQuery = 11.0, district: str | None = None,
                  department: str | None = None, tier: str | None = None,
                  status: str | None = None, capability: str | None = None,
                  grade: str | None = None,
                  codec: str | None = None,
                  region: str | None = None,
                  camera_type: str | None = None,
                  ai_status: str | None = None,
                  q: str | None = None,
                  source_domain: str | None = None,
                  limit: Annotated[int, Query(ge=1, le=20000)] = 1500
                  ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        return state.maps.cameras(
            bbox=_bbox(bbox), zoom=zoom, districts=_districts(ctx, district),
            departments=csv_list(department), tiers=csv_list(tier),
            states=csv_list(status), capability=capability,
            capability_grades=csv_list(grade), max_features=limit,
            codecs=csv_list(codec), regions=csv_list(region),
            camera_types=csv_list(camera_type),
            ai_statuses=csv_list(ai_status), q=q,
            source_domains=csv_list(source_domain))
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/health", summary="Stream health per camera")
async def health(state: StateDep, ctx: AuthDep, bbox: BBoxQuery = None,
                 district: str | None = None) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.HEALTH_READ)
        return state.maps.health(bbox=_bbox(bbox),
                                 districts=_districts(ctx, district))
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/capability", summary="Measured capability per camera")
async def capability(state: StateDep, ctx: AuthDep, bbox: BBoxQuery = None,
                     district: str | None = None,
                     time_band: str | None = None) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAPABILITY_READ)
        return state.maps.capability(bbox=_bbox(bbox),
                                     districts=_districts(ctx, district),
                                     time_band=time_band)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/trajectory/{plate}", summary="Trajectory hypotheses as map geometry")
async def trajectory(state: StateDep, ctx: AuthDep, plate: str,
                     t_from: str | None = None, t_to: str | None = None,
                     hypothesis: Annotated[int, Query(ge=0, le=9)] = 0
                     ) -> dict[str, Any]:
    """Geometry for one hypothesis, with every leg kind preserved.

    The path parameter is a registration mark, so this endpoint is purpose-bound
    exactly like the search that produces it. It is not a "map layer" that
    escapes the access rules by virtue of being on the map.
    """
    try:
        result = state.investigation.build_trajectory(
            ctx, plate=plate, t_from=parse_time(t_from, "t_from"),
            t_to=parse_time(t_to, "t_to"))
        hyps = result.get("hypotheses", [])
        if not hyps:
            return {"target": plate, "geometry": None,
                    "reason": result.get("reason", "no hypothesis could be built"),
                    "observations": result.get("observations", [])}
        idx = min(hypothesis, len(hyps) - 1)
        geom = state.maps.trajectory_geometry(hyps[idx])
        return {
            "target": plate, "hypothesis_index": idx,
            "hypothesis_count": len(hyps),
            "geometry": geom,
            "score_semantics": result["score_semantics"],
            "observations": result.get("observations", []),
            "gap_candidates": result.get("gap_candidates", []),
        }
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/alerts", summary="Alert locations")
async def alerts(state: StateDep, ctx: AuthDep, bbox: BBoxQuery = None,
                 status: str | None = "OPEN") -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ALERT_READ)
        from saakshya.watchlist import parse_alert_status
        try:
            wanted = parse_alert_status(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={
                "code": "BAD_STATUS", "message": str(exc)}) from exc
        rows = state.investigation.alerts.list_alerts(wanted)
        scope = ctx.principal.scope_filter()
        if scope is not None:
            allowed = {c["camera_id"] for c in state.store.list_cameras()
                       if c.get("district") in scope}
            rows = [r for r in rows if r.get("camera_id") in allowed]
        return state.maps.alerts(rows, bbox=_bbox(bbox))
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/coverage", summary="Where the estate cannot observe, and why")
async def coverage(state: StateDep, ctx: AuthDep, bbox: BBoxQuery = None,
                   district: str | None = None,
                   threshold_m: Annotated[float, Query(ge=100, le=50000)] = 1500.0
                   ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        return state.maps.coverage(bbox=_bbox(bbox),
                                   districts=_districts(ctx, district),
                                   threshold_m=threshold_m)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/extent", summary="Bounding box of the located estate")
async def extent(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    ctx.principal.require(Permission.CAMERA_READ)
    scope = ctx.principal.scope_filter()
    box = state.store.camera_extent(list(scope) if scope else None)
    return {"extent": box,
            "cameras_without_location": state.store.cameras_without_location(
                list(scope) if scope else None)}


@router.get("/timebase", summary="Timing health and time clusters")
async def timebase(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """Which cameras may be reasoned about together, and why.

    Exposed as a first-class map layer because on a heterogeneous estate it is
    an operational fact, not an implementation detail: two cameras replaying
    different windows must never be joined into a route, and an investigator
    looking at a trajectory is entitled to see which of these it rests on.
    """
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc

    from saakshya.live.timebase import TimebaseRegistry
    registry = TimebaseRegistry(state.store)
    health = registry.all()
    scope = ctx.principal.scope_filter()
    cams = [c for c in state.store.list_cameras()
            if scope is None or c.get("district") in scope]
    ids = [c["camera_id"] for c in cams]

    return {
        "clusters": registry.clusters(),
        "cameras": [
            {"camera_id": cid, **(health[cid].to_dict() if cid in health
                                  else {"pts_health": "UNKNOWN",
                                        "usable_for_correlation": False,
                                        "time_cluster": None})}
            for cid in ids],
        "partition": registry.correlatable_set(ids),
        "measured": len(health),
        "note": ("Ordering always uses presentation timestamps. A clock burned "
                 "into an image is the scene's time and is never authoritative; "
                 "it is recorded because its absence or its disagreement is "
                 "itself operational information."),
    }


@router.get("/timebase/check", summary="May these cameras be correlated?")
async def timebase_check(state: StateDep, ctx: AuthDep,
                         cameras: str) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    ids = csv_list(cameras) or ()
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_REQUEST",
            "message": "name at least two cameras, comma-separated"})

    from saakshya.live.timebase import TimebaseRegistry
    registry = TimebaseRegistry(state.store)
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            verdict, why = registry.may_correlate(a, b)
            pairs.append({"a": a, "b": b, "verdict": str(verdict), "reason": why})
    return {"pairs": pairs, "partition": registry.correlatable_set(list(ids))}
