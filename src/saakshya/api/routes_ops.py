"""Operations: watchlist, alerts, evidence, audit, capability and admin.

Split from the investigation routes because the access rules genuinely differ. A
control-room operator acknowledges alerts and watches health but never runs a
vehicle search; an auditor reads the audit log and nothing else. Keeping those
surfaces apart in the code makes the separation reviewable instead of implicit.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from saakshya.api.deps import (
    AuthDep,
    ConcurrencyGuard,
    StateDep,
    access_error,
    parse_time,
)
from saakshya.common.clock import iso
from saakshya.obs import METRICS
from saakshya.security import AccessError, Permission
from saakshya.store.provenance import refuses_live_writes, store_name
from saakshya.watchlist import AlertStatus, Category, Priority, VehicleOfInterest, parse_alert_status

router = APIRouter(tags=["operations"])


# --------------------------------------------------------------------------- #
# Watchlist
# --------------------------------------------------------------------------- #
class WatchlistCreate(BaseModel):
    plate: str = Field(min_length=4, max_length=24)
    category: str
    authority: str = Field(min_length=4, max_length=200)
    reason: str = Field(min_length=8, max_length=2000)
    priority: str = "MEDIUM"
    jurisdiction: str | None = Field(default=None, max_length=120)
    valid_until: str | None = None


@router.get("/watchlist", summary="Active watchlist entries")
async def watchlist_list(state: StateDep, ctx: AuthDep,
                         plate: str | None = None) -> dict[str, Any]:
    try:
        ctx.authorise(Permission.WATCHLIST_READ)
        rows = state.investigation.watchlist.active_entries(plate)
        ctx.audit(state.store, "watchlist_read", target=plate,
                  result_count=len(rows))
    except AccessError as exc:
        raise access_error(exc) from exc
    return {
        "entries": [
            {"watchlist_id": e.watchlist_id, "plate": e.plate,
             "category": str(e.category), "priority": str(e.priority),
             "authority": e.authority, "reason": e.reason,
             "jurisdiction": e.jurisdiction, "version": e.version,
             "status": str(e.status), "source_system": e.source_system}
            for e in rows],
        "count": len(rows),
        # Never left implicit. A judge, an auditor or an officer must be able to
        # tell at a glance that these entries are ours and not a government feed.
        "provenance": ("All entries are REPRESENTATIVE unless a source_system "
                       "states otherwise. No government watchlist is integrated."),
    }


@router.post("/watchlist", status_code=201, summary="Add a vehicle of interest")
async def watchlist_add(state: StateDep, ctx: AuthDep,
                        body: WatchlistCreate) -> dict[str, Any]:
    try:
        ctx.authorise(Permission.WATCHLIST_WRITE, district=body.jurisdiction)
        voi = VehicleOfInterest(
            plate=body.plate, category=Category(body.category),
            authority=body.authority, reason=body.reason,
            priority=Priority(body.priority), jurisdiction=body.jurisdiction,
            valid_until=parse_time(body.valid_until, "valid_until"),
            created_by=ctx.principal.user_id)
        saved = state.investigation.watchlist.add(voi, actor=ctx.principal.user_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_REQUEST", "message": str(exc)}) from exc
    return {"watchlist_id": saved.watchlist_id, "plate": saved.plate,
            "version": saved.version, "status": str(saved.status)}


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
#: Microsecond integers are how time is *stored*; they are not how it is
#: published. Every other list endpoint returns ISO-8601, and this one returned
#: `t_norm_us: 1788312382336128` — which no client can read, and which the UI
#: rendered as an em dash rather than failing, so an alert with a perfectly good
#: timestamp displayed as having none.
_US_FIELDS = ("t_norm_us", "created_at_us", "acknowledged_at_us",
              "updated_at_us", "cleared_at_us")


def _with_iso_times(row: dict[str, Any]) -> dict[str, Any]:
    """Add the ISO form of every stored microsecond timestamp.

    The `_us` values are kept alongside, so a client that wants exact integer
    microseconds still has them and nothing that reads them breaks.
    """
    out = dict(row)
    for field in _US_FIELDS:
        raw = row.get(field)
        if isinstance(raw, int):
            out[field[:-3]] = iso(datetime.fromtimestamp(raw / 1e6, tz=UTC))
    return out


def _map_public_config(state: Any) -> dict[str, Any]:
    """What the workspace may load as a basemap. Never a stream credential.

    A Google Maps browser key has to reach the page — the JS API runs in the
    browser. It is still not a secret of the same class as the grid password:
    it is referrer-restricted in Cloud Console, and it is absent unless set.
    """
    gkey = getattr(state, "google_maps_key", "") or ""
    tiles = bool(state.tile_template) and not gkey
    if gkey:
        note = ("Google Maps is the basemap. Camera markers, uncertainty and "
                "trajectories are still drawn by this workspace.")
    elif tiles:
        note = ("Raster street map enabled. Tiles are an enhancement; the map "
                "works without them.")
    else:
        note = ("No basemap is configured. The map draws a measured graticule "
                "and scale instead, and every marker is still where it belongs "
                "— this deployment can run with no route to the internet.")
    return {
        "tiles": tiles,
        "template": state.tile_template if tiles else None,
        "attribution": (state.tile_attribution if tiles else
                        ("© Google" if gkey else None)),
        "google": {"enabled": bool(gkey), "key": gkey or None},
        "note": note,
    }


def _whep_proxy_ready(state: Any) -> bool:
    """Signaling proxy is usable when this process holds the grid credential
    and at least one camera has a WHEP URL. The password never goes in /config."""
    from saakshya.live.credentials import configured
    if not configured():
        return False
    return any(c.get("whep_url") for c in state.store.list_cameras())


def _live_note(state: Any) -> str:
    if state.whep_base:
        return ("Live video over WebRTC (WHEP). The browser negotiates "
                "directly with the media server; this platform does not "
                "proxy or transcode video.")
    if _whep_proxy_ready(state):
        return ("Live video over WebRTC. Signaling is proxied so the grid "
                "password never reaches the browser. Click one camera. "
                "The wall itself stays as ingest stills — thirty extra "
                "stream copies would be thirty extra clients on the grid.")
    return ("Click one camera for a live view (one extra stream copy, "
            "RTSP over TCP, paced from PTS). The wall itself stays as "
            "ingest stills. WebRTC is used when the grid answers WHEP.")


def _copilot_public_config() -> dict[str, Any]:
    """Whether the assistant can run, and whether Gemini is in this process.

    Rules always answer when the copilot is not switched off. Gemini is
    optional and is never inferred as available from a lazily-built object
    that has not been asked a question yet.
    """
    import os

    from saakshya.copilot.backends import gemini_configured
    off = os.environ.get("SAAKSHYA_COPILOT", "").lower() in ("off", "0", "false")
    return {
        "available": not off,
        "gemini": (not off) and gemini_configured(),
    }


@router.get("/alerts", summary="Alerts, newest first")
async def alerts(state: StateDep, ctx: AuthDep, status: str | None = "OPEN",
                 limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ALERT_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
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
    return {"alerts": [_with_iso_times(r) for r in rows[:limit]],
            "count": len(rows[:limit]),
            "stats": state.investigation.alerts.stats()}


@router.post("/alerts/{alert_id}/acknowledge", summary="Acknowledge an alert")
async def alert_ack(state: StateDep, ctx: AuthDep, alert_id: str) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ALERT_ACK)
        state.investigation.alerts.acknowledge(alert_id, actor=ctx.principal.user_id)
        ctx.audit(state.store, "alert_acknowledge", target=alert_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {"alert_id": alert_id, "status": "ACKNOWLEDGED",
            "operator_status": "Acknowledged",
            "acknowledged_by": ctx.principal.user_id}


@router.post("/alerts/{alert_id}/investigate", summary="Mark an alert under investigation")
async def alert_investigate(state: StateDep, ctx: AuthDep, alert_id: str
                            ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ALERT_ACK)
        state.investigation.alerts.investigate(alert_id, actor=ctx.principal.user_id)
        ctx.audit(state.store, "alert_investigate", target=alert_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {"alert_id": alert_id, "status": "INVESTIGATING",
            "operator_status": "Investigating",
            "acknowledged_by": ctx.principal.user_id}


class AlertClear(BaseModel):
    reason: str = Field(min_length=4, max_length=1000)
    false_positive: bool = False


@router.post("/alerts/{alert_id}/clear", summary="Clear an alert with a reason")
async def alert_clear(state: StateDep, ctx: AuthDep, alert_id: str,
                      body: AlertClear) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ALERT_ACK)
        state.investigation.alerts.clear(
            alert_id, actor=ctx.principal.user_id, reason=body.reason,
            false_positive=body.false_positive)
        ctx.audit(state.store, "alert_clear", target=alert_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {"alert_id": alert_id, "status": "CLEARED"}


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
@router.post("/evidence/from-observation/{observation_id}", status_code=201,
             summary="Create a sealed evidence record for an observation")
async def evidence_create(state: StateDep, ctx: AuthDep,
                          observation_id: str) -> dict[str, Any]:
    try:
        ctx.authorise(Permission.EVIDENCE_CREATE)
        obs = state.investigation._observation_by_id(observation_id)
        if obs is None:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": "no such observation"})
        ctx.principal.require_scope(obs.district)
        existing = state.evidence.find_by_observation(observation_id)
        if existing is not None:
            ctx.audit(state.store, "evidence_create_noop",
                      target=existing.evidence_id)
            return {**existing.to_dict(), "already_sealed": True,
                    "note": ("this observation was already sealed; the existing "
                             "record is returned unchanged. Re-sealing would add "
                             "a second manifest for one sighting.")}
        m = state.evidence.create(obs, device=f"api:{ctx.principal.user_id}")
        ctx.audit(state.store, "evidence_create", target=m.evidence_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    return m.to_dict()


@router.get("/evidence/{evidence_id}", summary="One evidence manifest")
async def evidence_get(state: StateDep, ctx: AuthDep, evidence_id: str
                       ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.EVIDENCE_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    m = state.evidence.load(evidence_id)
    if m is None:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": f"no such evidence: {evidence_id}"})
    return m.to_dict()


@router.post("/evidence/{evidence_id}/verify",
             summary="Run cryptographic verification")
async def evidence_verify(state: StateDep, ctx: AuthDep, evidence_id: str
                          ) -> dict[str, Any]:
    """There is no simulated path here. This recomputes the file digests and the
    manifest hash and re-walks the chain; a tampered record fails."""
    try:
        return state.investigation.verify_evidence(ctx, evidence_id)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/evidence/{evidence_id}/export",
            summary="Export package with the draft s.63 certificate")
async def evidence_export(state: StateDep, ctx: AuthDep, evidence_id: str
                          ) -> dict[str, Any]:
    try:
        ctx.authorise(Permission.EVIDENCE_EXPORT)
        async with ConcurrencyGuard(state.export_sem, what="exports"):
            pkg = state.evidence.export(evidence_id)
        ctx.audit(state.store, "evidence_export", target=evidence_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": str(exc)}) from exc
    return pkg


@router.get("/evidence/chain/verify", summary="Verify the whole evidence chain")
async def evidence_chain(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.EVIDENCE_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return state.evidence.verify_chain().to_dict()


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
@router.get("/audit", summary="The audit log, with chain verification")
async def audit(state: StateDep, ctx: AuthDep, case_id: str | None = None,
                actor: str | None = None, action: str | None = None,
                limit: Annotated[int, Query(ge=1, le=1000)] = 200
                ) -> dict[str, Any]:
    """Records are never synthesised. If nothing was recorded, this returns
    nothing — an audit view that invents plausible entries is worse than none."""
    try:
        ctx.principal.require(Permission.AUDIT_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    from sqlalchemy import select

    from saakshya.store import schema as S
    from saakshya.store.repository import from_us
    q = select(S.audit_log)
    if case_id:
        q = q.where(S.audit_log.c.case_id == case_id)
    if actor:
        q = q.where(S.audit_log.c.actor == actor)
    if action:
        q = q.where(S.audit_log.c.action == action)
    with state.store.engine.connect() as c:
        rows = [dict(r._mapping) for r in
                c.execute(q.order_by(S.audit_log.c.id.desc()).limit(limit))]
    for r in rows:
        # `t_us` is NOT NULL in the schema, so this should never be None. If it
        # ever is, the row is corrupt — and crashing while *reading the audit
        # log* is the worst possible response to discovering that.
        t = from_us(r.pop("t_us"))
        r["t"] = t.isoformat() if t else None
    ok, err = state.store.verify_audit_chain()
    return {"entries": rows, "count": len(rows),
            "chain_verified": ok, "chain_error": err}


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #
@router.get("/capability/summary", summary="Estate-wide measured capability")
async def capability_summary(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.CAPABILITY_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    return state.capability.summary()


@router.post("/capability/grade", summary="Re-grade cameras from stored observations")
async def capability_grade(state: StateDep, ctx: AuthDep,
                           camera_id: str | None = None) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
    except AccessError as exc:
        raise access_error(exc) from exc
    from saakshya.capability import TimeBand
    if camera_id:
        a = state.capability.grade_camera(camera_id, band=TimeBand.ALL)
        state.store.upsert_capability(camera_id, str(TimeBand.ALL), a.row())
        results = [a.to_dict()]
    else:
        results = [a.to_dict() for a in state.capability.grade_all(
            bands=(TimeBand.ALL, TimeBand.DAY, TimeBand.NIGHT, TimeBand.LOW_LIGHT))]
    ctx.audit(state.store, "capability_grade", target=camera_id or "ALL",
              result_count=len(results))
    return {"graded": len(results), "assessments": results}


# --------------------------------------------------------------------------- #
# Home screen, health, metrics
# --------------------------------------------------------------------------- #
@router.get("/overview", summary="Operational home screen")
async def overview(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        return state.investigation.operational_summary(ctx)
    except AccessError as exc:
        raise access_error(exc) from exc


@router.get("/marks", summary="Latest distinct registration marks with location")
async def marks(state: StateDep, ctx: AuthDep,
                camera_id: str | None = None) -> dict[str, Any]:
    """Cheap plate strip for Overview and Live. Not a search."""
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    if camera_id:
        cam = state.store.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": f"no such camera: {camera_id}"})
        try:
            ctx.principal.require_scope(cam.get("district"))
        except AccessError as exc:
            raise access_error(exc) from exc
        return {"marks": state.store.marks_for_camera(camera_id, 24),
                "camera_id": camera_id}
    return {"marks": state.store.recent_marks(48)}


@router.get("/config", summary="What this deployment has been configured with")
async def config(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """Deployment configuration the interface needs, and nothing sensitive.

    No credential, endpoint or secret appears here — only whether optional
    capabilities are switched on, so the interface can render honestly instead
    of showing a feature that will not work.
    """
    return {
        "live": {
            # Live viewing is optional. When the grid credential is in this
            # process, the browser can open one WHEP session through a
            # signaling proxy so the password never reaches the page.
            "whep": bool(state.whep_base) or _whep_proxy_ready(state),
            "view": True,
            "base": state.whep_base or None,
            "proxy": (not state.whep_base) and _whep_proxy_ready(state),
            "note": (_live_note(state)),
        },
        "map": _map_public_config(state),
        # Which store is open, and whether it holds live capture or
        # demonstration state. The interface prints this in the handling strip
        # because mistaking demonstration state for live government data is the
        # single easiest misreading during an evaluation, and the person most
        # likely to make it is the one being shown the screen.
        "data": {
            "store": store_name(state.db_url),
            "holds": ("DEMONSTRATION" if refuses_live_writes(state.db_url)
                      else "LIVE CAPTURE"),
        },
        "copilot": _copilot_public_config(),
        "auth_required": state.require_auth,
    }


@router.get("/me", summary="Who am I, and what may I do")
async def me(ctx: AuthDep) -> dict[str, Any]:
    return {"principal": ctx.principal.to_dict(),
            "case_id": ctx.case_id, "purpose_supplied": bool(ctx.purpose)}


@router.get("/healthz", summary="Liveness", include_in_schema=False)
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "time": datetime.now(UTC).isoformat(timespec="seconds")}


@router.get("/readyz", summary="Readiness", include_in_schema=False)
async def readyz(state: StateDep) -> dict[str, Any]:
    """Ready means the store answers and the schema is present. It deliberately
    does not check camera reachability: an estate with cameras down is degraded,
    not unready, and failing readiness would take the whole system out of
    rotation exactly when operators need it most."""
    checks: dict[str, Any] = {}
    try:
        st = state.store.stats()
        checks["database"] = {"ok": True, "observations": st.get("observations", 0)}
    except Exception as exc:  # readiness must report a failure, never raise one
        checks["database"] = {"ok": False, "error": str(exc)}
    checks["evidence_root"] = {"ok": state.evidence.root.exists(),
                               "path": str(state.evidence.root)}
    checks["graph"] = {"ok": True, **state.graph.stats()}
    ok = all(c.get("ok", True) for c in checks.values())
    if not ok:
        raise HTTPException(status_code=503, detail={"code": "NOT_READY",
                                                     "checks": checks})
    return {"status": "ready", "checks": checks}


@router.get("/metrics", response_class=PlainTextResponse,
            summary="Prometheus metrics", include_in_schema=False)
async def metrics() -> str:
    return METRICS.prometheus()


@router.get("/metrics.json", summary="Metrics as JSON", include_in_schema=False)
async def metrics_json() -> dict[str, Any]:
    return METRICS.snapshot()
