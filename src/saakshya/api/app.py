"""The application. OpenAPI is generated from these routes, not maintained beside
them, so the contract cannot drift from the implementation.

Middleware order is deliberate and reads outermost-first:

1. **Request id** — assigned before anything can fail, so even a rejected
   request is traceable.
2. **Metrics and access log** — records the outcome of everything inside it,
   including refusals, which are the interesting ones.
3. **Security headers** — applied on the way out regardless of the path taken.

Errors are mapped once, centrally. An access failure returns the same shaped
body whether it came from a route guard or from deep inside the service layer,
and it always names which gate closed — an officer told only "forbidden" cannot
tell a missing case id from a jurisdiction boundary.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from saakshya.api import (
    routes_gis,
    routes_investigation,
    routes_ops,
    routes_system,
)
from saakshya.api.deps import AppState, AuthDep, StateDep
from saakshya.obs import METRICS, actor_var, configure_logging, request_id_var
from saakshya.security import AccessError, Permission

log = logging.getLogger("saakshya.api")

TITLE = "SAAKSHYA — Federated CCTV Intelligence and Evidence Fabric"
DESCRIPTION = """
Investigation-first API over a heterogeneous camera estate.

**Authentication.** Bearer token: `Authorization: Bearer <token>`.

**Purpose binding.** Searches, watchlist access and evidence export additionally
require `X-Case-Id` and `X-Purpose` headers. Both are written into the
hash-chained audit log. A request without them is rejected with `400
PURPOSE_REQUIRED` — this is a deliberate design decision, not an oversight:
authentication establishes who is asking, and it does not by itself establish
entitlement to a person's movement history.

**Uncertainty.** Scores returned by this API are engineering scores, not
calibrated probabilities, and are labelled as such. Appearance matching returns
candidates requiring verification, never identifications.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    state: AppState = app.state.saakshya
    log.info("saakshya api starting", extra={"extra_fields": {
        "db": state.db_url, "auth_required": state.require_auth,
        "cameras": len(state.store.list_cameras())}})
    yield
    log.info("saakshya api stopping")


def create_app(state: AppState | None = None, *,
               static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title=TITLE, description=DESCRIPTION, version="0.4.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "investigation", "description": "find → trace → verify → act"},
            {"name": "gis", "description": "map layers, viewport-bounded"},
            {"name": "operations", "description": "watchlist, alerts, evidence, audit"},
            {"name": "edge", "description": "offline node synchronisation"},
        ])
    app.state.saakshya = state or AppState()

    # -- middleware ---------------------------------------------------------- #
    @app.middleware("http")
    async def correlate(request: Request, call_next: Callable[..., Awaitable[Any]]):
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            dt = time.perf_counter() - t0
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            METRICS.observe("api_request_seconds", dt,
                            error=status >= 500, route=path,
                            method=request.method)
            METRICS.incr("api_requests_total", route=path, status=str(status))
            actor = getattr(request.state, "actor", None)
            actor_var.set(actor)
            log.info("request", extra={"extra_fields": {
                "method": request.method, "path": request.url.path,
                "route": path, "status": status,
                "duration_ms": round(dt * 1000, 2), "actor": actor}})
            request_id_var.reset(token)

    @app.middleware("http")
    async def headers(request: Request, call_next: Callable[..., Awaitable[Any]]):
        response = await call_next(request)
        rid = getattr(request.state, "request_id", None)
        if rid:
            response.headers["X-Request-Id"] = rid
        # The UI loads no third-party asset by default, so the policy can be
        # this tight — a stored-XSS attempt through a case note cannot call out.
        #
        # Two optional widenings, each for exactly the configured host:
        # raster tiles (`img-src` only) and Google Maps JS (script, img,
        # connect, font). With neither configured the policy is unchanged.
        img_src = "'self' data: blob:"
        tiles = getattr(request.app.state.saakshya, "tile_template", "")
        if tiles:
            host = _tile_origin(tiles)
            if host:
                img_src += f" {host}"
        connect_src = "'self'"
        script_src = "'self'"
        style_src = "'self' 'unsafe-inline'"
        font_src = "'self'"
        gkey = getattr(request.app.state.saakshya, "google_maps_key", "")
        if gkey:
            img_src += (" https://maps.gstatic.com https://maps.googleapis.com"
                        " https://*.googleapis.com https://*.gstatic.com"
                        " https://*.google.com https://*.ggpht.com")
            connect_src += (" https://maps.googleapis.com https://maps.gstatic.com"
                            " https://*.googleapis.com")
            script_src += " https://maps.googleapis.com https://maps.gstatic.com"
            style_src += " https://fonts.googleapis.com"
            font_src += " https://fonts.gstatic.com"
        # Live viewing over WebRTC needs the browser to POST an SDP offer to
        # the media server. Widened for exactly that origin, `connect-src`
        # only — the media itself arrives over the peer connection, not over a
        # URL the policy governs.
        whep = getattr(request.app.state.saakshya, "whep_base", "")
        if whep:
            origin = _origin_of(whep)
            if origin:
                connect_src += f" {origin}"
        response.headers.setdefault(
            "Content-Security-Policy",
            f"default-src 'self'; img-src {img_src}; "
            f"style-src {style_src}; script-src {script_src}; "
            f"font-src {font_src}; "
            f"connect-src {connect_src}; media-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'none'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # -- error mapping -------------------------------------------------------- #
    @app.exception_handler(AccessError)
    async def on_access_error(request: Request, exc: AccessError):
        METRICS.incr("access_denied_total", code=exc.code)
        log.warning("access denied", extra={"extra_fields": {
            "code": exc.code, "path": request.url.path, "message": str(exc)}})
        return JSONResponse(status_code=exc.status, content={
            "detail": {"code": exc.code, "message": str(exc)}})

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={
            "detail": {"code": "INVALID_REQUEST",
                       "message": "request failed validation",
                       "errors": _safe_errors(exc)}})

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception):
        # The message is logged in full and *not* returned. Internal paths,
        # SQL fragments and stack frames are useful to an attacker and useless
        # to an operator; the request id is what connects them to the log.
        rid = getattr(request.state, "request_id", None)
        log.exception("unhandled error", extra={"extra_fields": {
            "path": request.url.path, "request_id": rid}})
        METRICS.incr("unhandled_errors_total", route=request.url.path)
        return JSONResponse(status_code=500, content={
            "detail": {"code": "INTERNAL_ERROR",
                       "message": "the request failed; quote the request id",
                       "request_id": rid}})

    # -- routes --------------------------------------------------------------- #
    app.include_router(routes_investigation.router)
    app.include_router(routes_gis.router)
    app.include_router(routes_ops.router)
    app.include_router(routes_system.router)

    from saakshya.api import routes_admin, routes_copilot, routes_edge
    app.include_router(routes_edge.router)
    app.include_router(routes_copilot.router)
    app.include_router(routes_admin.router)

    @app.get("/evidence/{evidence_id}/frame", include_in_schema=False)
    async def evidence_frame(state: StateDep, ctx: AuthDep, evidence_id: str):
        """Serve a sealed frame image.

        Path traversal is prevented by construction rather than by sanitising
        the input: the filename comes from the database, and the resolved path
        must still sit inside the evidence root or it is refused. Both checks,
        because either alone has failed in real systems.
        """
        ctx.principal.require(Permission.EVIDENCE_READ)
        m = state.evidence.load(evidence_id)
        if m is None or not m.frame_path:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": "no frame for this evidence id"})
        root = state.evidence.root.resolve()
        path = Path(m.frame_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            log.error("evidence path escaped its root", extra={"extra_fields": {
                "evidence_id": evidence_id, "path": str(path)}})
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND", "message": "frame is not available"})
        return FileResponse(path, media_type="image/jpeg")

    # -- UI -------------------------------------------------------------------- #
    ui = static_dir or Path(__file__).resolve().parents[3] / "ui"
    if ui.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(ui / "index.html")

    return app


def _origin_of(url: str) -> str | None:
    """Scheme and authority only, so a policy never carries a path."""
    from urllib.parse import urlparse

    try:
        p = urlparse(url)
    except ValueError:
        return None
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else None


def _tile_origin(template: str) -> str | None:
    """The scheme and host of a tile template, with wildcards made explicit.

    Tile templates commonly use a `{s}` subdomain placeholder; a CSP cannot
    match a placeholder, so it becomes a wildcard over that host and nothing
    wider. A template we cannot parse widens nothing.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(template.replace("{s}", "a"))
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname
    if "{s}" in template:
        parts = host.split(".")
        if len(parts) > 2:
            host = "*." + ".".join(parts[1:])
    return f"{parsed.scheme}://{host}"


def _safe_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Field names and messages only. The submitted value is never echoed —
    validation errors are a classic way to reflect attacker-controlled content
    back into a client."""
    out = []
    for e in exc.errors()[:20]:
        out.append({"location": ".".join(str(p) for p in e.get("loc", ())),
                    "problem": e.get("msg", "invalid")})
    return out


# Deliberately NO module-level `app`. Importing this module must not touch the
# database, so the ASGI object is built by the `build` factory below.
#
# There is no `app = None` placeholder either: uvicorn treats a None attribute
# as an ASGI2 callable and dies with "'NoneType' object is not callable", which
# says nothing about the cause. With the name absent, the conventional
# `uvicorn saakshya.api.app:app` fails with "Attribute 'app' not found", which
# points straight at the fix. Correct invocation:
#
#     uvicorn saakshya.api.app:build --factory
#
# or simply `python -m saakshya.api.app`.


def main() -> None:
    import uvicorn
    configure_logging()
    uvicorn.run("saakshya.api.app:build", factory=True, host="127.0.0.1",
                port=8080, log_config=None)


def build() -> FastAPI:
    return create_app()


if __name__ == "__main__":
    main()
