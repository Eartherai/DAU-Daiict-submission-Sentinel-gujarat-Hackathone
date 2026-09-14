"""Edge synchronisation endpoints.

Machine-to-machine only. A node authenticates with a SERVICE token, which holds
`edge:sync` and nothing else — an edge credential that leaked would let an
attacker replay observations, and would not let them search a plate, read the
watchlist or touch evidence.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from saakshya.api.deps import AuthDep, StateDep, access_error
from saakshya.edge import CentralReceiver
from saakshya.security import AccessError, Permission

router = APIRouter(prefix="/edge", tags=["edge"])


class EdgeEvent(BaseModel):
    event_id: str = Field(max_length=40)
    sequence: int = Field(ge=0)
    event_type: str = Field(max_length=32)
    dedup_key: str = Field(max_length=160)
    payload: dict[str, Any]
    camera_id: str | None = Field(default=None, max_length=64)
    pts_s: float | None = None
    created_at: str | None = None
    state: str | None = None
    attempts: int | None = None
    node_id: str | None = None


class EdgeBatch(BaseModel):
    #: Bounded so one node cannot post an unbounded body. A node with more than
    #: this outstanding sends several batches, which is what it does anyway.
    events: list[EdgeEvent] = Field(max_length=1000)


@router.post("/{node_id}/events", summary="Replay queued events from a node")
async def receive(state: StateDep, ctx: AuthDep, node_id: str,
                  batch: EdgeBatch) -> dict[str, Any]:
    """Apply a replayed batch. Idempotent: replaying is safe and expected."""
    try:
        ctx.principal.require(Permission.EDGE_SYNC)
    except AccessError as exc:
        raise access_error(exc) from exc
    receiver = CentralReceiver(state.store)
    result = receiver.receive(node_id, [e.model_dump() for e in batch.events])
    return result.to_dict()


@router.get("/nodes", summary="Known edge nodes and their sync state")
async def nodes(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.HEALTH_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    from sqlalchemy import select

    from saakshya.store import schema as S
    from saakshya.store.repository import from_us
    with state.store.engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(select(S.edge_nodes))]
    for r in rows:
        for k in ("last_sync_us", "updated_at_us"):
            v = r.pop(k, None)
            t = from_us(v) if v else None
            r[k.replace("_us", "")] = t.isoformat() if t else None
    return {"nodes": rows, "count": len(rows)}


@router.get("/watchlist/bundle", summary="Current watchlist bundle for distribution")
async def bundle(state: StateDep, ctx: AuthDep,
                 issuer: Annotated[str, Body(embed=True)] = "saakshya-central"
                 ) -> dict[str, Any]:
    """Build a bundle from the active watchlist.

    The response states its own verification method and limitation, so a node —
    or a person reading the JSON — cannot mistake a content hash for a signature.
    """
    try:
        ctx.authorise(Permission.WATCHLIST_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    from saakshya.watchlist import WatchlistBundle
    entries = state.investigation.watchlist.active_entries()
    if not entries:
        raise HTTPException(status_code=404, detail={
            "code": "EMPTY", "message": "no active watchlist entries to distribute"})
    b = WatchlistBundle.build(entries, issuer=issuer)
    ctx.audit(state.store, "watchlist_bundle_build", target=b.bundle_version,
              result_count=len(entries))
    return b.to_dict()
