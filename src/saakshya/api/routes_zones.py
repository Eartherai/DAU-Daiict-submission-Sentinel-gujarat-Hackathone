"""Department zone rules and the entries measured against them.

Writing a rule is registry configuration (admin:write), audited with the
authority it was made on. Reading entries is alert work (alert:read) inside the
caller's jurisdiction, and audited like any read of sightings.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from saakshya.api.deps import AuthDep, StateDep, access_error, parse_time
from saakshya.security import AccessError, Permission

router = APIRouter(prefix="/zones", tags=["zones"])


class ZoneRule(BaseModel):
    camera_id: str = Field(max_length=64)
    name: str = Field(min_length=3, max_length=120)
    polygon: list[list[float]] = Field(min_length=3, max_length=64)
    active_from: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    active_to: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    classes: list[str] = Field(default_factory=lambda: ["person"])
    reason: str = Field(min_length=8, max_length=500)
    authority: str = Field(min_length=3, max_length=200)


def _camera_or_404(state: Any, ctx: Any, camera_id: str) -> dict[str, Any]:
    cam = state.store.get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": f"no camera {camera_id} in the registry"})
    ctx.principal.require_scope(cam.get("district"))
    return cam


@router.post("", status_code=201, summary="A department's restricted-zone rule for a camera")
async def create_rule(state: StateDep, ctx: AuthDep, body: ZoneRule) -> dict[str, Any]:
    from saakshya.common.ids import new_id
    from saakshya.store import now_us
    from saakshya.store import schema as S
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
        _camera_or_404(state, ctx, body.camera_id)
    except AccessError as exc:
        raise access_error(exc) from exc
    if (body.active_from is None) != (body.active_to is None):
        raise HTTPException(status_code=422, detail={
            "code": "HOURS_INCOMPLETE",
            "message": "give both active_from and active_to, or neither for always"})
    bad = [c for c in body.classes if c not in ("person", "vehicle")]
    if bad:
        raise HTTPException(status_code=422, detail={
            "code": "BAD_CLASS", "message": f"classes are person or vehicle, not {bad}"})
    row = {"rule_id": new_id("ZR"), "camera_id": body.camera_id, "name": body.name,
           "polygon": json.dumps(body.polygon), "active_from": body.active_from,
           "active_to": body.active_to, "classes": json.dumps(body.classes),
           "reason": body.reason, "authority": body.authority, "status": "ACTIVE",
           "created_by": ctx.principal.user_id, "created_at_us": now_us()}
    with state.store.engine.begin() as c:
        c.execute(S.zone_rules.insert().values(**row))
    ctx.audit(state.store, "zone_rule_create", target=f"{body.camera_id}:{row['rule_id']}")
    from saakshya.analytics.zones import rule_view
    return rule_view(row)


@router.get("", summary="Zone rules in the caller's jurisdiction")
async def list_rules(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    from sqlalchemy import select

    from saakshya.analytics.zones import rule_view
    from saakshya.store import schema as S
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    with state.store.engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(
            select(S.zone_rules).where(S.zone_rules.c.status == "ACTIVE"))]
    out = []
    for r in rows:
        cam = state.store.get_camera(r["camera_id"]) or {}
        if ctx.principal.in_scope(cam.get("district")):
            out.append({**rule_view(r), "camera_name": cam.get("name")})
    return {"rules": out, "count": len(out)}


@router.get("/{rule_id}/entries", summary="Sightings inside a rule's zone during its hours")
async def rule_entries(state: StateDep, ctx: AuthDep, rule_id: str,
                       t_from: str | None = None, t_to: str | None = None,
                       limit: Annotated[int, Query(ge=1, le=1000)] = 200) -> dict[str, Any]:
    from sqlalchemy import select

    from saakshya.analytics.zones import entries
    from saakshya.store import schema as S
    with state.store.engine.connect() as c:
        row = c.execute(select(S.zone_rules).where(S.zone_rules.c.rule_id == rule_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "NOT_FOUND", "message": f"no zone rule {rule_id}"})
    rule = dict(row._mapping)
    try:
        ctx.principal.require(Permission.ALERT_READ)
        cam = _camera_or_404(state, ctx, rule["camera_id"])
    except AccessError as exc:
        raise access_error(exc) from exc
    out = entries(state.store, rule, t_from=parse_time(t_from, "t_from"),
                  t_to=parse_time(t_to, "t_to"), limit=limit)
    out["camera_name"] = cam.get("name")
    ctx.audit(state.store, "zone_entries_read", target=rule_id, result_count=out["count"])
    return out
