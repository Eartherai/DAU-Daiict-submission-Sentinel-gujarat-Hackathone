"""Investigation endpoints: find → trace → verify → act.

Ordered as the work is actually done, not as the data model is shaped. The
investigator's first action is a search; everything else hangs off its results.

Every route here is thin. The logic lives in `InvestigationService`, which the
copilot also calls, so an answer produced through the chat surface and an answer
produced by clicking cannot disagree.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from saakshya.api.deps import (
    AuthDep,
    ConcurrencyGuard,
    StateDep,
    access_error,
    check_span,
    csv_list,
    parse_time,
)
from saakshya.intelligence.plate_pattern import PatternError
from saakshya.security import AccessError, Permission

router = APIRouter(tags=["investigation"])


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@router.get("/search", summary="Find a target by plate, attributes, time or place")
async def search(
    state: StateDep, ctx: AuthDep,
    plate: str | None = None,
    fuzzy: bool = False,
    colour: str | None = None,
    object_type: str | None = None,
    district: str | None = None,
    camera: str | None = None,
    t_from: str | None = None,
    t_to: str | None = None,
    min_quality: Annotated[float | None, Query(ge=0, le=1)] = None,
    watchlist_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict[str, Any]:
    """The primary query.

    `fuzzy` is opt-in and every fuzzy result is labelled REQUIRES_VERIFICATION.
    An OCR-similar plate is a lead, and presenting it as a match is how the
    wrong vehicle gets stopped.
    """
    tf, tt = parse_time(t_from, "t_from"), parse_time(t_to, "t_to")
    check_span(state, tf, tt)
    if not any((plate, colour, object_type, camera, district, tf)):
        raise HTTPException(status_code=400, detail={
            "code": "QUERY_TOO_BROAD",
            "message": ("supply at least one of: plate, colour, object_type, "
                        "camera, district or t_from. An unfiltered scan of the "
                        "whole estate is refused."),
        })
    try:
        async with ConcurrencyGuard(state.search_sem, what="searches"):
            return state.investigation.search_target(
                ctx, plate=plate, fuzzy=fuzzy, colours=csv_list(colour),
                object_types=csv_list(object_type), districts=csv_list(district),
                cameras=csv_list(camera), t_from=tf, t_to=tt,
                min_quality=min_quality, watchlist_only=watchlist_only, limit=limit)
    except AccessError as exc:
        raise access_error(exc) from exc
    except PatternError as exc:
        # A fragment too loose to search ("G*") is refused with the reason, so
        # the officer adds the characters they are sure of rather than
        # scrolling a list of every plate in the state.
        raise HTTPException(status_code=400, detail={
            "code": "BAD_PLATE_PATTERN", "message": str(exc)}) from exc


@router.get("/observations/{observation_id}",
            summary="One observation with its full evidence panel")
async def observation(state: StateDep, ctx: AuthDep,
                      observation_id: str) -> dict[str, Any]:
    try:
        panel = state.investigation.evidence_panel(ctx, observation_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    if panel.get("error"):
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": panel["error"]})
    return panel


@router.get("/targets/{plate}/observations",
            summary="Quality-filtered observation set for one vehicle")
async def observation_set(state: StateDep, ctx: AuthDep, plate: str,
                          min_quality: Annotated[float, Query(ge=0, le=1)] = 0.25,
                          max_observations: Annotated[int, Query(ge=1, le=100)] = 12
                          ) -> dict[str, Any]:
    try:
        return state.investigation.observation_set(
            ctx, plate=plate, min_quality=min_quality,
            max_observations=max_observations)
    except AccessError as exc:
        raise access_error(exc) from exc


# --------------------------------------------------------------------------- #
# Trajectory
# --------------------------------------------------------------------------- #
@router.get("/trajectory/{plate}", summary="Ranked route hypotheses")
async def trajectory(state: StateDep, ctx: AuthDep, plate: str,
                     t_from: str | None = None, t_to: str | None = None,
                     gap_candidates: bool = True) -> dict[str, Any]:
    tf, tt = parse_time(t_from, "t_from"), parse_time(t_to, "t_to")
    check_span(state, tf, tt)
    try:
        async with ConcurrencyGuard(state.search_sem, what="searches"):
            return state.investigation.build_trajectory(
                ctx, plate=plate, t_from=tf, t_to=tt,
                include_gap_candidates=gap_candidates)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/follow/{plate}", summary="Follow a vehicle through feasible cameras")
@router.get("/follow-vehicle/{plate}", include_in_schema=False)
async def follow_vehicle(state: StateDep, ctx: AuthDep, plate: str,
                         t_from: str | None = None, t_to: str | None = None,
                         limit: Annotated[int, Query(ge=1, le=100)] = 20
                         ) -> dict[str, Any]:
    """Return a plate route plus ranked, physically feasible follow-up leads."""
    tf, tt = parse_time(t_from, "t_from"), parse_time(t_to, "t_to")
    check_span(state, tf, tt)
    try:
        async with ConcurrencyGuard(state.search_sem, what="searches"):
            return state.investigation.follow_vehicle(
                ctx, plate=plate, t_from=tf, t_to=tt, limit=limit)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/cameras/{camera_id}/next", summary="Where to look next, and why")
async def next_cameras(state: StateDep, ctx: AuthDep, camera_id: str,
                       seen_at: str,
                       horizon_s: Annotated[float, Query(ge=30, le=21600)] = 900.0,
                       limit: Annotated[int, Query(ge=1, le=50)] = 8
                       ) -> dict[str, Any]:
    when = parse_time(seen_at, "seen_at")
    if when is None:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_TIME", "message": "seen_at is required"})
    if camera_id not in {c["camera_id"] for c in state.store.list_cameras()}:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
    try:
        return state.investigation.next_best_cameras(
            ctx, camera_id=camera_id, seen_at=when, horizon_s=horizon_s, limit=limit)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/cameras/{camera_id}/snapshot", include_in_schema=False)
async def camera_snapshot(state: StateDep, ctx: AuthDep, camera_id: str,
                          force: bool = False,
                          overlay: str = "full",
                          people: bool = True,
                          vehicles: bool = True,
                          anpr: bool = True):
    """A still preview for the interface.

    A still, deliberately, not a video proxy. Transcoding thirty live streams
    for a browser would be a second analytics workload serving no investigative
    purpose, and the organiser's guide asks us to open only what we process.

    Served from one shared, cached capture per camera. The response carries the
    frame's age, because a preview is not evidence and must never be presented
    as live video.
    """
    from fastapi.responses import Response

    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc

    url = cam.get("rtsp_url") or ""
    if not url:
        from saakshya.live.snapshot import local_media_url
        url = local_media_url(camera_id)

    # A local relay already owns one ingest for each active own-feed camera.
    # Opening another RTSP reader here races that publisher and intermittently
    # leaves the second Intelligence panel blank. Reuse the relay preview when
    # available; it is explicitly labelled as a preview, never as evidence or
    # browser-live video.
    relay = getattr(state, "relay", None)
    if relay is None:
        try:
            from saakshya.live.relay import get_relay
            relay = get_relay()
        except Exception:
            relay = None

    snap = relay.grab_jpeg(camera_id) if relay is not None else None
    if snap is None:
        if state.snapshots is None:
            from saakshya.live import SnapshotService
            state.snapshots = SnapshotService()
        import anyio
        snap = await anyio.to_thread.run_sync(
            lambda: state.snapshots.get(camera_id, url, force=force))
    if snap is None:
        # Say which of the three it was. An upstream refusal is a 502 — the
        # failure is between us and the grid, and retrying will not fix it —
        # while a busy or unreachable camera is a 503 worth trying again.
        # No RTSP in the registry is 404 unless ingest already published a
        # still — the own-feed corpus has cameras without streams.
        why = state.snapshots.last_error.get(camera_id)
        if not url:
            raise HTTPException(status_code=404, detail={
                "code": "NO_SOURCE",
                "message": why or (
                    "this camera has no RTSP source in the registry, and "
                    "ingest has not published a still")})
        refused = bool(why and "refused this connection" in why)
        raise HTTPException(status_code=502 if refused else 503, detail={
            "code": "UPSTREAM_REFUSED" if refused else "NO_FRAME",
            "message": why or ("could not capture a frame from this camera. It "
                               "may be down, or the grid may be refusing "
                               "another consumer.")})
    src = {
        "ingest": "ingest preview, already decoded, not a second stream",
        "ingest-stale": "ingest preview, older than the refresh window",
        "live-view": "selected camera, one extra stream copy, PTS-paced",
        "file-view": "selected own-feed recording, PTS-paced",
        "relay-preview": "local relay preview, not live video",
    }.get(snap.source, "shared cached capture, not live video")
    jpeg = snap.jpeg
    media = {}
    try:
        from saakshya.live.hub import get_hub
        hub = get_hub()
        if hub is not None:
            media = hub.media_state(camera_id)
    except Exception:
        media = {}
    try:
        from saakshya.live.annotate import annotate_jpeg
        # RTSP live-view is PTS from the grid, not store time — overlaying
        # store boxes would ghost detections. Own-feed file-view PTS matches
        # the observations written at ingest, so boxes belong on that frame.
        if snap.source == "live-view" or snap.source in {
                "ingest", "ingest-stale", "relay-preview"}:
            jpeg = snap.jpeg
        else:
            jpeg = annotate_jpeg(
                snap.jpeg, state.store, camera_id,
                preview_wh=(snap.width, snap.height),
                camera_wh=(cam.get("width"), cam.get("height")),
                pts_s=snap.pts_s if snap.source == "file-view" else None,
                overlay=overlay, people=people, vehicles=vehicles, anpr=anpr)
    except Exception:
        jpeg = snap.jpeg
    return Response(
        content=jpeg, media_type="image/jpeg",
        headers={"X-Frame-Age-Seconds": f"{snap.age_s:.1f}",
                 "X-Frame-Source": src,
                 "X-Frame-Kind": snap.source,
                 "X-Source-State": str(media.get("source") or ""),
                 "X-Video-State": str(media.get("video") or ""),
                 "X-Ai-State": str(media.get("ai") or ""),
                 "X-Hub-Fps": str(media.get("jpeg_fps") or media.get("fps") or ""),
                 "Cache-Control": "no-store"})


@router.get("/cameras/{camera_id}/plate.jpg", include_in_schema=False)
async def plate_crop(state: StateDep, ctx: AuthDep, camera_id: str,
                     plate: Annotated[str, Query(min_length=4, max_length=16)]):
    """Crop of one stored plate box on this camera's current still.

    The number comes from the observation store. The picture is the still,
    not a drawn-on registration plate.
    """
    from fastapi.responses import Response

    import re

    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc

    mark = (plate or "").replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z0-9]{4,16}", mark):
        raise HTTPException(status_code=400, detail={
            "code": "BAD_PLATE", "message": "not a registration mark"})
    rows = state.store.marks_for_camera(camera_id, 48)
    hit = next((m for m in rows if (m.get("plate") or "").upper() == mark), None)
    if not hit or not hit.get("bbox"):
        return Response(status_code=204, headers={"X-Plate-Crop": "NO_CROP"})

    jpeg = None
    try:
        from saakshya.live.hub import get_hub
        hub = get_hub()
        hs = hub.as_snapshot(camera_id) if hub is not None else None
        if hs is not None:
            jpeg = hs.jpeg
    except Exception:
        jpeg = None
    if jpeg is None and state.snapshots is not None:
        live = state.snapshots.selected.latest(camera_id)
        if live is not None:
            jpeg = live.jpeg
    if jpeg is None:
        from saakshya.live.preview import read_preview
        got = read_preview(camera_id, max_age_s=float("inf"))
        if got is not None:
            jpeg = got[0]
    if not jpeg:
        return Response(status_code=204, headers={"X-Plate-Crop": "NO_FRAME"})

    from saakshya.live.annotate import crop_plate_jpeg
    crop = crop_plate_jpeg(
        jpeg, hit["bbox"],
        camera_wh=(cam.get("width"), cam.get("height")))
    if not crop:
        return Response(status_code=204, headers={"X-Plate-Crop": "NO_CROP"})
    return Response(
        content=crop, media_type="image/jpeg",
        headers={"Cache-Control": "no-store",
                 "X-Plate": mark})


@router.post("/cameras/{camera_id}/view", include_in_schema=False)
async def camera_view(state: StateDep, ctx: AuthDep, camera_id: str):
    """Open exactly one extra decode session for the camera the officer clicked.

    The wall stays on ingest stills. This is Model 2: live video when asked,
    not thirty extra clients on the grid. Own-feed cameras fall back to the
    local MP4 when the registry has no RTSP URL.
    """
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

    url = (cam.get("rtsp_url") or "") or local_media_url(camera_id)
    local = local_media_url(camera_id)
    # Own-feed cameras in the demo store often still point at a local MediaMTX
    # replica. If that replica is down, the MP4 the pipeline actually decoded
    # is the honest live view for this camera.
    if local and (not url or "127.0.0.1" in url or "localhost" in url
                  or url.startswith("file:")):
        url = local
    if not url:
        raise HTTPException(status_code=404, detail={
            "code": "NO_SOURCE",
            "message": "this camera has no live source and no local recording"})

    from saakshya.live.relay import get_relay
    relay = getattr(state, "relay", None) or get_relay()
    if relay is not None:
        return {"camera_id": camera_id, "mode": "local-relay",
                "source": "local_whep", "ready": relay.ready(camera_id)}

    if state.snapshots is None:
        from saakshya.live import SnapshotService
        state.snapshots = SnapshotService()
    state.snapshots.selected.start(camera_id, url)
    source = "file" if local and url == local else "rtsp"
    return {"camera_id": camera_id, "mode": "selected-stream", "source": source}


@router.get("/cameras/{camera_id}/media-state", include_in_schema=False)
async def camera_media_state(state: StateDep, ctx: AuthDep, camera_id: str
                             ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    relay = getattr(state, "relay", None)
    if relay is None:
        from saakshya.live.relay import get_relay
        relay = get_relay()
    if relay is not None:
        return relay.media_state(camera_id)
    hub = getattr(state, "hub", None)
    if hub is None:
        from saakshya.live.hub import get_hub
        hub = get_hub()
    if hub is None:
        return {"camera_id": camera_id, "source": "NO_SIGNAL", "video": "NO_SIGNAL",
                "ai": "OFF", "label": "NOT_MEASURED", "plane": "none"}
    row = hub.media_state(camera_id)
    row["plane"] = "local_hub"
    return row


@router.get("/media/hub", include_in_schema=False)
async def media_hub(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.HEALTH_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    relay = getattr(state, "relay", None)
    if relay is None:
        from saakshya.live.relay import get_relay
        relay = get_relay()
    if relay is not None:
        return relay.snapshot()
    hub = getattr(state, "hub", None)
    if hub is None:
        from saakshya.live.hub import get_hub
        hub = get_hub()
    if hub is None:
        return {"plane": "none", "upstream_sessions": 0, "label": "NOT_MEASURED"}
    return hub.snapshot()


@router.get("/cameras/{camera_id}/hls/{asset_path:path}", include_in_schema=False)
def local_relay_hls(state: StateDep, ctx: AuthDep, camera_id: str,
                    asset_path: str, request: Request):
    """Same-origin, read-only proxy for a local MediaMTX HLS asset.

    The browser must not contact the local relay port directly: its CSP permits
    only this application origin.  This route never contacts Sentinel and never
    receives a grid credential; it forwards playlist and segment bytes from the
    loopback-only relay after normal camera authorization.  This deliberately
    remains a synchronous FastAPI handler: ``urlopen`` and segment reads are
    blocking I/O, and declaring it ``async`` pins the event loop behind a
    slow HLS client.  FastAPI dispatches regular handlers to its worker pool,
    allowing a 30-camera wall to progress concurrently.
    """
    from fastapi.responses import Response
    from urllib.parse import quote
    from urllib.request import urlopen

    from saakshya.live.relay import get_relay, local_hls

    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc
    if not asset_path or asset_path.startswith("/") or ".." in asset_path.split("/"):
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_REQUEST", "message": "invalid HLS asset path"})
    relay = getattr(state, "relay", None) or get_relay()
    if relay is None or not relay.ready(camera_id):
        raise HTTPException(status_code=503, detail={
            "code": "RELAY_NOT_READY", "message": "local video relay is still connecting this camera"})
    base = local_hls(camera_id).rsplit("/", 1)[0]
    upstream = f"{base}/{quote(asset_path, safe='/')}"
    if request.url.query:
        upstream += f"?{request.url.query}"
    elif asset_path == "index.m3u8":
        # MediaMTX protects the first HLS playlist request with a browser
        # cookie check.  This same-origin proxy deliberately does not forward
        # browser cookies to the loopback media process, so ask for the
        # documented post-check URL directly.  Child playlists carry their
        # own session query and must remain untouched.
        upstream += "?cookieCheck=1"
    try:
        with urlopen(upstream, timeout=8) as resp:
            body = resp.read()
            content_type = resp.headers.get_content_type()
    except Exception as exc:
        raise HTTPException(status_code=503, detail={
            "code": "HLS_RELAY_UNAVAILABLE",
            "message": f"local HLS relay unavailable ({type(exc).__name__})"}) from exc
    return Response(content=body, media_type=content_type,
                    headers={"Cache-Control": "no-store"})


@router.post("/cameras/{camera_id}/whep", include_in_schema=False)
async def camera_whep(state: StateDep, ctx: AuthDep, camera_id: str,
                      request: Request):
    """WebRTC signaling proxy. Credentials never leave this process.

    The browser POSTs an SDP offer here. This process forwards it to the
    grid's WHEP endpoint with the stream authority attached, and returns the
    answer. Media still flows peer-to-peer to the media server; this is not
    a video transcode.
    """
    from fastapi.responses import PlainTextResponse

    from saakshya.live.credentials import configured, redact

    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc

    from saakshya.live.relay import get_relay, local_whep

    offer = (await request.body()).decode("utf-8", errors="replace")
    if not offer.strip():
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_REQUEST", "message": "empty SDP offer"})

    import urllib.error
    import urllib.request

    relay = getattr(state, "relay", None) or get_relay()
    if relay is not None:
        # Browser → local MediaMTX. Never Sentinel. No grid password on this hop.
        if not relay.ready(camera_id):
            raise HTTPException(status_code=503, detail={
                "code": "RELAY_NOT_READY",
                "message": "local video relay is still connecting this camera"})
        whep = local_whep(camera_id)
        req = urllib.request.Request(
            whep, data=offer.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/sdp", "Accept": "application/sdp"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                answer = resp.read().decode("utf-8", errors="replace")
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            raise HTTPException(status_code=502, detail={
                "code": "WHEP_RELAY",
                "message": f"local WHEP refused ({exc.code})"}) from exc
        except Exception:
            raise HTTPException(status_code=503, detail={
                "code": "WHEP_RELAY_UNREACHABLE",
                "message": f"local WHEP unreachable at {redact(whep)}"})
        return PlainTextResponse(answer, status_code=201 if status == 201 else 200,
                                 media_type="application/sdp")

    whep = cam.get("whep_url")
    if not whep:
        raise HTTPException(status_code=404, detail={
            "code": "NO_SOURCE",
            "message": "this camera has no WHEP endpoint in the registry"})
    # Registry rows sometimes hold the MediaMTX stream URL without the WHEP
    # suffix. The integrator contract is /stream/<id>/whep.
    if not whep.rstrip("/").endswith("/whep"):
        whep = whep.rstrip("/") + "/whep"
    if not configured():
        raise HTTPException(status_code=503, detail={
            "code": "NO_CREDENTIAL",
            "message": "live video needs the grid credential in this process "
                       "environment. Stills still refresh."})

    import base64
    import os

    # Direct Sentinel WHEP is the legacy path. The local relay is the product
    # plane; this branch must not run when the relay is on.
    email = os.environ.get("SENTINEL_GRID_EMAIL", "")
    password = os.environ.get("SENTINEL_GRID_PASSWORD", "")
    token = base64.b64encode(f"{email}:{password}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        whep, data=offer.encode("utf-8"), method="POST",
        headers={
            "Content-Type": "application/sdp",
            "Accept": "application/sdp",
            "Authorization": f"Basic {token}",
        })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            answer = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail={
            "code": "WHEP_UPSTREAM",
            "message": f"grid WHEP refused ({exc.code}). The still is still "
                       "refreshing."}) from exc
    except Exception:
        raise HTTPException(status_code=503, detail={
            "code": "WHEP_UNREACHABLE",
            "message": f"grid WHEP unreachable at {redact(whep)}. "
                       "The still is still refreshing."})
    return PlainTextResponse(answer, status_code=201 if status == 201 else 200,
                             media_type="application/sdp")


@router.post("/demo-simulation/cameras/{camera_id}/whep", include_in_schema=False)
async def demo_simulation_whep(state: StateDep, ctx: AuthDep, camera_id: str,
                               request: Request):
    """WebRTC signaling for the isolated 30-channel archival replay plane.

    Never touches Sentinel or the government relay: the SDP offer is
    forwarded only to the local SimulationRelay's own MediaMTX WHEP endpoint,
    on its own dedicated ports.
    """
    from fastapi.responses import PlainTextResponse

    from saakshya.live.simulation import catalog, get_simulation

    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc

    known_ids = {row["camera_id"] for row in catalog()}
    if camera_id not in known_ids:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND",
            "message": f"no such demo simulation camera: {camera_id}"})

    sim = getattr(state, "simulation", None) or get_simulation()
    if sim is None:
        raise HTTPException(status_code=503, detail={
            "code": "SIMULATION_DISABLED",
            "message": "the demo simulation plane is not enabled on this process"})
    if not sim.ready(camera_id):
        raise HTTPException(status_code=503, detail={
            "code": "SIMULATION_NOT_READY",
            "message": "the demo simulation is still connecting this camera"})

    offer = (await request.body()).decode("utf-8", errors="replace")
    if not offer.strip():
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_REQUEST", "message": "empty SDP offer"})

    import urllib.error
    import urllib.request

    whep = sim.local_whep(camera_id)
    req = urllib.request.Request(
        whep, data=offer.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/sdp", "Accept": "application/sdp"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            answer = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail={
            "code": "WHEP_RELAY",
            "message": f"demo simulation WHEP refused ({exc.code})"}) from exc
    except Exception:
        raise HTTPException(status_code=503, detail={
            "code": "WHEP_RELAY_UNREACHABLE",
            "message": "demo simulation WHEP unreachable"})
    return PlainTextResponse(answer, status_code=201 if status == 201 else 200,
                             media_type="application/sdp")


@router.get("/cameras/{camera_id}/live-boxes", include_in_schema=False)
async def live_boxes_alias(state: StateDep, ctx: AuthDep, camera_id: str,
                           overlay: str = "full",
                           people: bool = True, vehicles: bool = True,
                           anpr: bool = True) -> dict[str, Any]:
    from saakshya.api.routes_command import boxes
    return await boxes(state, ctx, camera_id, overlay=overlay,
                       people=people, vehicles=vehicles, anpr=anpr)


@router.get("/cameras/{camera_id}", summary="Camera context: registry, health, capability")
async def camera_context(state: StateDep, ctx: AuthDep, camera_id: str
                         ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
        health = state.store.list_health([camera_id]).get(camera_id, {})
        caps = state.store.list_capability([camera_id])
        counts = state.store.observation_counts_by_camera().get(camera_id, {})
        neighbours = [
            {"to_camera": b, "support": t.support_count,
             "travel_p50_s": t.travel_p50_s, "confidence": round(t.confidence, 3),
             "trusted": t.trusted, "source": t.source}
            for (a, b), t in state.graph.edges.items() if a == camera_id]
        # A transition with no confidence sorts last rather than raising.
        neighbours.sort(key=lambda n: -float(n["confidence"] or 0.0))
        return {
            "camera": {k: v for k, v in cam.items()
                       if k not in ("rtsp_url", "hls_url", "whep_url")},
            # Stream URLs can carry credentials and are not investigation data.
            # They are available to ADMIN through the admin route, not here.
            "health": health, "capability": caps, "counts": counts,
            "neighbours": neighbours,
        }
    except AccessError as exc:
        raise access_error(exc) from exc


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #
class CaseCreate(BaseModel):
    #: Slashes are allowed because an Indian FIR number is NNN/YYYY — a case
    #: identifier containing one is the normal case, not an exotic input. The
    #: pattern still excludes everything that could confuse a path or a shell,
    #: and the routes below use a `path` converter so such an id is addressable.
    case_id: str = Field(min_length=3, max_length=60,
                         pattern=r"^[A-Za-z0-9][A-Za-z0-9/_.\-]{2,59}$")
    title: str = Field(min_length=3, max_length=200)
    purpose: str = Field(min_length=12, max_length=2000)
    fir_number: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=120)
    classification: str | None = Field(default=None, max_length=60)


class CaseAttach(BaseModel):
    item_type: str = Field(pattern=r"^(target|observation|trajectory|alert|evidence|camera)$")
    item_ref: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.post("/cases", status_code=201, summary="Open a case")
async def case_create(state: StateDep, ctx: AuthDep, body: CaseCreate) -> dict[str, Any]:
    try:
        return state.cases.create(
            ctx, case_id=body.case_id, title=body.title, purpose=body.purpose,
            fir_number=body.fir_number, district=body.district,
            classification=body.classification).to_dict()
    except AccessError as exc:
        raise access_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={
            "code": "CONFLICT", "message": str(exc)}) from exc


@router.get("/cases", summary="List cases in scope")
async def case_list(state: StateDep, ctx: AuthDep, status: str | None = None,
                    limit: Annotated[int, Query(ge=1, le=500)] = 100
                    ) -> dict[str, Any]:
    try:
        cases = state.cases.list_cases(ctx, status=status, limit=limit)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {"cases": [c.to_dict() for c in cases], "count": len(cases)}


@router.post("/cases/{case_id:path}/items",
             summary="Attach a finding to a case")
async def case_attach(state: StateDep, ctx: AuthDep, case_id: str,
                      body: CaseAttach) -> dict[str, Any]:
    try:
        return state.cases.attach(ctx, case_id, item_type=body.item_type,
                                  item_ref=body.item_ref, payload=body.payload,
                                  note=body.note)
    except AccessError as exc:
        raise access_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_REQUEST", "message": str(exc)}) from exc


@router.post("/cases/{case_id:path}/notes",
             summary="Add an investigator note")
async def case_note(state: StateDep, ctx: AuthDep, case_id: str,
                    body: Annotated[dict[str, str], Body()]) -> dict[str, Any]:
    try:
        return state.cases.note(ctx, case_id, body.get("body", ""))
    except AccessError as exc:
        raise access_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_REQUEST", "message": str(exc)}) from exc


@router.get("/cases/{case_id:path}/export",
            summary="Case file with its audit trail")
async def case_export(state: StateDep, ctx: AuthDep, case_id: str) -> dict[str, Any]:
    try:
        async with ConcurrencyGuard(state.export_sem, what="exports"):
            return state.cases.export(ctx, case_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": str(exc)}) from exc


@router.get("/cases/{case_id:path}",
            summary="One case with its attachments and notes")
async def case_get(state: StateDep, ctx: AuthDep, case_id: str) -> dict[str, Any]:
    try:
        case = state.cases.get(ctx, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such case: {case_id}"})
        return {"case": case.to_dict(),
                "items": state.cases.items(ctx, case_id),
                "notes": state.cases.notes(ctx, case_id)}
    except AccessError as exc:
        raise access_error(exc) from exc


# --------------------------------------------------------------------------- #
# Recorded own-feed files, played natively, with the pipeline's frame track.
# --------------------------------------------------------------------------- #
#
# The Intelligence view showed an own feed as a JPEG swapped every 450 ms from
# a one-second snapshot cache, over boxes polled from a CPU-bound worker at
# about 1.4 frames a second. On a recorded file that is a slideshow, and it is
# what an assessor saw while being told "AI-powered detection and analytics".
#
# A recorded file does not have to be sampled like a live camera. These two
# routes let the browser play the MP4 at its own rate and draw the production
# pipeline's per-frame output against `currentTime`. Government cameras are
# never served this way: they are live streams, and there is no file.

_TRACK_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def _own_media_path(state: Any, ctx: Any, camera_id: str):
    """Resolve a camera to its recorded file, or refuse, under the usual gates."""
    from pathlib import Path

    from saakshya.command.domain import GOVERNMENT, classify_source_domain
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
    domain = classify_source_domain(camera_id, stored=cam.get("source_domain"),
                                    integration_model=cam.get("integration_model"))
    if domain == GOVERNMENT:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_A_RECORDING",
            "message": ("government cameras are live streams; there is no "
                        "recorded file to serve")})
    path = local_media_url(camera_id)
    if not path:
        raise HTTPException(status_code=404, detail={
            "code": "NO_FILE", "message": f"no recorded file for {camera_id}"})
    return Path(path)


def _file_sha256(path: Any) -> str:
    """Hash once per (path, size, mtime): footage can be tens of megabytes."""
    import hashlib

    st = path.stat()
    key = (str(path), st.st_size, int(st.st_mtime))
    hit = _TRACK_HASH_CACHE.get(key)
    if hit:
        return hit
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _TRACK_HASH_CACHE[key] = h.hexdigest()
    return _TRACK_HASH_CACHE[key]


@router.get("/media/own/{camera_id}/file", include_in_schema=False)
def own_feed_file(state: StateDep, ctx: AuthDep, camera_id: str):
    """The recorded MP4 itself. Range requests are honoured, so it seeks."""
    from fastapi.responses import FileResponse

    path = _own_media_path(state, ctx, camera_id)
    return FileResponse(str(path), media_type="video/mp4",
                        headers={"Cache-Control": "private, max-age=300"})


@router.get("/media/own/{camera_id}/tracks",
            summary="Per-frame detections the pipeline produced over a recording")
def own_feed_tracks(state: StateDep, ctx: AuthDep, camera_id: str) -> Any:
    """The production pipeline's output for every frame of the file.

    Produced offline by tools/demo/analyse_own_feed.py and bound to the file by
    SHA-256. A sidecar whose file has since changed is refused rather than
    drawn: boxes computed over one picture and painted over another would be
    the most convincing kind of fabrication this platform could produce.
    """
    import json

    from fastapi.responses import JSONResponse

    path = _own_media_path(state, ctx, camera_id)
    side = path.with_name(f"{camera_id}.tracks.json")
    if not side.is_file():
        raise HTTPException(status_code=404, detail={
            "code": "NOT_ANALYSED",
            "message": (f"{camera_id} has not been analysed frame by frame; run "
                        "tools/demo/analyse_own_feed.py")})
    data = json.loads(side.read_text(encoding="utf-8"))
    if data.get("sha256") != _file_sha256(path):
        raise HTTPException(status_code=409, detail={
            "code": "STALE_ANALYSIS",
            "message": (f"the analysis of {camera_id} was made over different "
                        "bytes than the file now on disk; re-run the analysis "
                        "rather than draw boxes over a picture they do not "
                        "belong to")})
    return JSONResponse(data, headers={"Cache-Control": "private, max-age=300"})
