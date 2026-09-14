"""Application state, authentication wiring and resource limits.

Three things live here that the route modules deliberately do not own.

**One composition root.** Services are built once, at startup, and handed to
routes. A route that constructs its own `Store` would quietly open a second
connection pool and a second camera cache, and the divergence would surface as
an intermittent staleness bug months later.

**Authentication as a dependency, not a decorator.** Every sensitive route takes
an `AuthContext` parameter, so a route that forgot to authenticate does not
compile into something that silently serves data — it has no context to pass to
the service layer, and the service layer refuses to act without one.

**Limits that are enforced, not documented.** Concurrency, result size and export
size are bounded here. An unbounded search endpoint on a statewide store is a
denial-of-service vector that looks like a feature.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Query, Request

from saakshya.capability.grader import CapabilityGrader
from saakshya.evidence import EvidenceService
from saakshya.gis import MapService
from saakshya.intelligence import CameraGraph
from saakshya.investigation import CaseService, InvestigationService
from saakshya.obs import METRICS
from saakshya.security import (
    AccessError,
    AuthContext,
    NotAuthenticated,
    Principal,
    TokenService,
)
from saakshya.store import Store


@dataclass
class Limits:
    """Resource ceilings. Every one of these has a defined behaviour at the
    limit — refuse with a specific error — rather than an undefined one."""

    #: Concurrent *searches*, not concurrent requests. Map reads are cheap and
    #: must stay responsive while a heavy investigation query is running.
    max_concurrent_searches: int = 8
    max_concurrent_exports: int = 2
    max_results: int = 2000
    max_export_items: int = 500
    #: Rejects an absurd time range before it reaches the database.
    max_time_span_days: int = 400
    request_timeout_s: float = 30.0


class AppState:
    def __init__(self, db_url: str | None = None, *,
                 evidence_root: Path | None = None,
                 limits: Limits | None = None) -> None:
        self.db_url = db_url or os.environ.get(
            "SAAKSHYA_DB", "sqlite:///var/saakshya.db")
        self.store = Store(self.db_url)
        self.store.create_all()
        self.limits = limits or Limits()
        self.tokens = TokenService(self.store)
        self.graph = CameraGraph(self.store).load()
        self.evidence = EvidenceService(
            self.store, root=evidence_root or Path(
                os.environ.get("SAAKSHYA_EVIDENCE", "var/evidence")))
        self.investigation = InvestigationService(
            self.store, self.graph, evidence=self.evidence)
        self.cases = CaseService(self.store)
        self.maps = MapService(self.store, self.graph)
        self.capability = CapabilityGrader(self.store)
        #: Built on first use — constructing it eagerly would import the
        #: language-model backend into every process that only serves the API.
        self.copilot: Any = None
        #: One shared capture per camera for interface previews. The grid gives
        #: every client its own stream copy, so a browser tile must never open
        #: one of its own.
        self.snapshots: Any = None
        self.search_sem = asyncio.Semaphore(self.limits.max_concurrent_searches)
        self.export_sem = asyncio.Semaphore(self.limits.max_concurrent_exports)
        #: Optional raster basemap. Off unless configured, because the system
        #: must run on a network with no route to the internet — a basemap is an
        #: enhancement, never a dependency. When it is set, the CSP is widened
        #: for exactly that host and nothing else.
        self.tile_template = os.environ.get("SAAKSHYA_MAP_TILES", "").strip()
        #: Official Google Maps JavaScript API. Off unless a key is in the
        #: process environment — never a file in the repository. When set it
        #: is the basemap; raster tiles are the air-gapped / no-key fallback.
        self.google_maps_key = os.environ.get(
            "SAAKSHYA_GOOGLE_MAPS_KEY", "").strip()
        #: Optional WebRTC (WHEP) base for live viewing, e.g.
        #: http://host:8889/stream — the camera id and `/whep` are appended.
        #: Off unless configured: live video is a viewing convenience, and the
        #: platform must work without it. When it is set, the CSP is widened
        #: for exactly that origin and nothing else.
        self.whep_base = os.environ.get("SAAKSHYA_WHEP_BASE", "").strip()
        self.tile_attribution = os.environ.get(
            "SAAKSHYA_MAP_ATTRIBUTION", "© OpenStreetMap contributors")
        #: Set false by a deployment that has authenticated every caller some
        #: other way (a service mesh, an authenticating proxy). Never a way to
        #: skip authorisation — the principal is still required downstream.
        self.require_auth = os.environ.get("SAAKSHYA_REQUIRE_AUTH", "1") != "0"

    def refresh(self) -> None:
        self.graph = self.graph.load()
        self.investigation.refresh()
        self.maps = MapService(self.store, self.graph)


def get_state(request: Request) -> AppState:
    return request.app.state.saakshya


StateDep = Annotated[AppState, Depends(get_state)]


# --------------------------------------------------------------------------- #
# Authentication and purpose binding
# --------------------------------------------------------------------------- #
def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def auth_context(
    request: Request,
    state: StateDep,
    authorization: Annotated[str | None, Header()] = None,
    x_case_id: Annotated[str | None, Header(alias="X-Case-Id")] = None,
    x_purpose: Annotated[str | None, Header(alias="X-Purpose")] = None,
) -> AuthContext:
    """Authenticate, and carry the purpose binding into the service layer.

    The case id and purpose are *headers* rather than body fields because they
    apply uniformly to every request, including GETs, and because a header
    cannot be forgotten in one endpoint's request model and present in another's.
    """
    token = _bearer(authorization)
    try:
        if not state.require_auth and not token:
            # Local development only. It is a named identity with a real role,
            # so nothing downstream has to handle "no principal", and every
            # audit entry still attributes the action to someone.
            from saakshya.security import Role
            principal = Principal(user_id="local.dev", role=Role.SUPERVISOR,
                                  display_name="local development")
        else:
            principal = state.tokens.authenticate(token)
    except NotAuthenticated as exc:
        raise HTTPException(status_code=401, detail={
            "code": "NOT_AUTHENTICATED", "message": str(exc)}) from exc

    ctx = AuthContext(principal=principal, case_id=x_case_id, purpose=x_purpose,
                      request_id=getattr(request.state, "request_id", None))
    request.state.actor = principal.user_id
    return ctx


AuthDep = Annotated[AuthContext, Depends(auth_context)]


def access_error(exc: AccessError) -> HTTPException:
    return HTTPException(status_code=exc.status,
                         detail={"code": exc.code, "message": str(exc)})


# --------------------------------------------------------------------------- #
# Shared query validation
# --------------------------------------------------------------------------- #
def parse_time(value: str | None, field: str) -> datetime | None:
    """ISO-8601 only, and rejected loudly.

    Accepting several formats here would mean a mistyped timestamp silently
    selects a different window, which in an investigation is worse than an error.
    """
    if not value:
        return None
    value = value.strip()
    # An unencoded "+" in a query string arrives as a space. The value is
    # unambiguous, so this is repaired rather than rejected — it is a transport
    # artefact, not a mistyped timestamp, and rejecting it produces a baffling
    # error for a correct client. Everything else stays strict.
    if len(value) >= 6 and value[-6] == " " and value[-3] == ":":
        value = value[:-6] + "+" + value[-5:]
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_TIME", "message":
            f"{field} must be ISO-8601 (e.g. 2026-09-01T08:00:00Z); got {value!r}",
        }) from exc
    if dt.tzinfo is None:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_TIME", "message":
            f"{field} must carry a timezone offset; a naive timestamp is ambiguous",
        })
    return dt


def check_span(state: AppState, t_from: datetime | None, t_to: datetime | None) -> None:
    if t_from and t_to:
        if t_to < t_from:
            raise HTTPException(status_code=400, detail={
                "code": "BAD_RANGE", "message": "t_to is before t_from"})
        days = (t_to - t_from).days
        if days > state.limits.max_time_span_days:
            raise HTTPException(status_code=400, detail={
                "code": "RANGE_TOO_LARGE",
                "message": (f"requested {days} days; the limit is "
                            f"{state.limits.max_time_span_days}. Narrow the "
                            "window or run several queries.")})


def csv_list(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    items = tuple(v.strip() for v in value.split(",") if v.strip())
    return items or None


LimitQuery = Annotated[int, Query(ge=1, le=2000)]


def as_error(exc: Exception) -> dict[str, Any]:
    return {"code": type(exc).__name__, "message": str(exc)}


class ConcurrencyGuard:
    """Bounded admission. Refuses rather than queueing without limit.

    A request that waits five minutes for a semaphore is indistinguishable from
    a hung system to the person waiting on it, so the wait is bounded and the
    refusal says what to do next.
    """

    def __init__(self, sem: asyncio.Semaphore, *, what: str,
                 wait_s: float = 5.0) -> None:
        self.sem, self.what, self.wait_s = sem, what, wait_s

    async def __aenter__(self) -> None:
        try:
            await asyncio.wait_for(self.sem.acquire(), timeout=self.wait_s)
        except TimeoutError as exc:
            METRICS.incr("admission_rejected_total", what=self.what)
            raise HTTPException(status_code=503, detail={
                "code": "BUSY",
                "message": (f"too many concurrent {self.what}. This request was "
                            "refused rather than queued; retry shortly."),
            }) from exc

    async def __aexit__(self, *exc: Any) -> None:
        self.sem.release()
