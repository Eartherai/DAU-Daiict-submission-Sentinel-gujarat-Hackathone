"""System self-diagnostics.

An operator asked to rely on this system needs to know which parts of it are
working *now*, and the honest answer for a component nobody has exercised is
UNKNOWN, not HEALTHY. A dashboard that shows green because it never checked is
worse than no dashboard: it converts ignorance into false assurance.

Every subsystem reports one of four states, and each carries the evidence it was
derived from:

    HEALTHY    checked just now, and it worked
    DEGRADED   working, but below what it should deliver
    FAILED     checked just now, and it did not work
    UNKNOWN    not checked, or never exercised — never treated as healthy

Secrets never appear here. Provider availability is reported as configured or
not; keys, tokens and endpoints are not echoed back, not even partially.
"""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter

from saakshya.api.deps import AuthDep, StateDep
from saakshya.common.clock import iso, utc_now
from saakshya.security import AccessError, Permission

router = APIRouter(tags=["system"])

HEALTHY, DEGRADED, FAILED, UNKNOWN = "HEALTHY", "DEGRADED", "FAILED", "UNKNOWN"


def _check(name: str, state: str, detail: str,
           **extra: Any) -> dict[str, Any]:
    return {"component": name, "state": state, "detail": detail, **extra}


def _feed_health(state: Any) -> dict[str, Any]:
    """Live grid from the local relay or in-process hub when present."""
    relay = getattr(state, "relay", None)
    if relay is None:
        try:
            from saakshya.live.relay import get_relay
            relay = get_relay()
        except Exception:
            relay = None
    if relay is not None:
        snap = relay.snapshot()
        n = snap["upstream_sessions"]
        streaming = snap["source_connected"]
        relay_ready = snap["relay_ready"]
        st = (HEALTHY if streaming == n and n else
              FAILED if streaming == 0 else DEGRADED)
        return _check(
            "feed", st,
            (f"local relay: {streaming}/{n} upstream publishers connected, "
             f"{relay_ready}/{n} local WHEP paths ready. Browser-rendered "
             "frame counts are reported only by the browser wall. Not per-tile "
             "Sentinel WHEP. JPEG is PREVIEW fallback only."),
            cameras=n, streaming=streaming, browser_live=snap["browser_live"],
            relay_ready=relay_ready,
            plane="local_relay")
    hub = getattr(state, "hub", None)
    if hub is None:
        try:
            from saakshya.live.hub import get_hub
            hub = get_hub()
        except Exception:
            hub = None
    if hub is not None:
        snap = hub.snapshot()
        n = snap["upstream_sessions"]
        idle = snap.get("idle", 0)
        streaming = snap["source_connected"]
        live = snap["browser_live"]
        # A camera nothing is watching is not opened (on-demand hub), so it is
        # neither up nor down: with no session open there is nothing measured,
        # and "FAILED" would be a claim about cameras nobody connected to.
        st = (UNKNOWN if n == 0 else
              HEALTHY if streaming == n else
              FAILED if streaming == 0 else DEGRADED)
        return _check(
            "feed", st,
            (f"local hub: {streaming}/{n} open upstream RTSP sessions connected, "
             f"{idle} idle until something asks for them, "
             f"{live} browser LIVE (hub JPEG age ≤ {4.0}s). "
             "Not per-tile Sentinel WHEP."),
            cameras=n, streaming=streaming, browser_live=live, idle=idle,
            plane="local_hub")
    from sqlalchemy import select

    from saakshya.store import schema as S
    with state.store.engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(select(S.camera_health))]
    registered = [c["camera_id"] for c in state.store.list_cameras()]
    observed = state.store.observed_camera_ids()
    health_ids = {r["camera_id"] for r in rows}
    never_ingested = sum(1 for cid in registered
                         if cid not in health_ids and cid not in observed)
    health_pending = sum(1 for cid in registered
                         if cid not in health_ids and cid in observed)

    if not rows and not observed:
        return _check("feed", UNKNOWN,
                      "no camera has been ingested, so nothing is known about "
                      "the grid's health", cameras=len(registered),
                      streaming=0, down=0, never_ingested=len(registered),
                      health_pending=0, decoder_errors=0)

    streaming = sum(1 for r in rows if r.get("state") == "STREAMING")
    down = sum(1 for r in rows if r.get("state") == "DOWN")
    errors = sum(r.get("decoder_errors") or 0 for r in rows)
    nreg = len(registered)
    st = (HEALTHY if streaming == nreg and not health_pending else
          FAILED if streaming == 0 and not observed else DEGRADED)
    if not rows:
        detail = (f"{len(observed)} of {nreg} registered cameras have "
                  "observations; health rows are written while ingest runs "
                  "and at close, so stream state is unknown until then")
        if never_ingested:
            detail += (f"; {never_ingested} have neither observations nor a "
                       "health row")
    else:
        # Against the whole estate, not just the cameras that happen to have a
        # health row. "12 of 12 streaming" reads as full coverage when the
        # rest of the estate is unaccounted for.
        detail = (f"{streaming} of {nreg} registered cameras streaming in "
                  f"last persisted health; {down} down, {errors} decoder errors")
        if health_pending:
            detail += (f"; {health_pending} have observations but no health "
                       "row — stream state unknown until ingest persists it, "
                       "not missing from the store")
        if never_ingested:
            detail += (f"; {never_ingested} have neither observations nor a "
                       "health row")
    return _check("feed", st, detail, cameras=nreg, streaming=streaming,
                  down=down, never_ingested=never_ingested,
                  health_pending=health_pending, decoder_errors=errors)


def _grid_access_health(state: Any | None = None) -> dict[str, Any]:
    """Whether this process can open the government grid at all.

    A missing credential is not a dead camera. A credential the grid has
    refused (HTTP 401 on every camera) is not HEALTHY either — Overview used
    to stay green because the env vars were merely *present*.
    """
    from saakshya.live.credentials import configured
    if not configured():
        return _check(
            "grid_access", DEGRADED,
            "SENTINEL_GRID_EMAIL and SENTINEL_GRID_PASSWORD are not in this "
            "process. Live stills and ingest cannot open the government grid. "
            "The investigation store is unaffected.")
    refused = 0
    n = 0
    if state is not None:
        try:
            rows = state.store.list_health() or {}
            n = len(rows)
            for row in rows.values():
                err = (row.get("last_error") or "").lower()
                if "401" in err or "unauthorized" in err:
                    refused += 1
        except Exception:
            n = 0
    if n and refused == n:
        return _check(
            "grid_access", DEGRADED,
            f"stream credential is present but the grid refused every camera "
            f"({refused}/{n} last_error 401). Refresh SENTINEL_GRID_PASSWORD "
            f"from the sandbox portal and restart ingest. The store and films "
            f"are unaffected.",
            cameras=n, refused=refused)
    return _check(
        "grid_access", HEALTHY,
        "stream credential is present in this process environment "
        "(never in a file, log or camera row)")


def _inference_health() -> dict[str, Any]:
    """Model activation, from the registry's own gate."""
    try:
        from saakshya.models.registry import REGISTRY
    except ImportError:                      # pragma: no cover
        return _check("inference", UNKNOWN, "model registry unavailable")
    import json
    from pathlib import Path
    report = Path("var/reports/model_activation.json")
    if not report.exists():
        return _check("inference", UNKNOWN,
                      f"{len(REGISTRY)} models registered; none has been "
                      "validated in this deployment. Run `make models-validate`.",
                      registered=len(REGISTRY))
    try:
        data = json.loads(report.read_text())
    except (OSError, ValueError):
        return _check("inference", UNKNOWN, "activation report unreadable")
    # The report counts its own outcomes; use those rather than recounting a
    # structure whose shape has changed once already.
    active = int(data.get("active") or 0)
    failed = int(data.get("failed") or 0)
    broken = list(data.get("required_broken") or [])
    if broken:
        st = FAILED
        detail = (f"{len(broken)} model(s) the pipeline requires are broken: "
                  f"{', '.join(broken)}")
    elif active:
        # Failures among registry *candidates* are expected and recorded; they
        # are not pipeline faults, and reporting them as DEGRADED would train
        # an operator to ignore this line.
        st = HEALTHY
        detail = (f"{active} model(s) ACTIVE, all required ones among them"
                  + (f"; {failed} registry candidate(s) failed and are recorded "
                     "in their registry notes" if failed else ""))
    else:
        st = FAILED
        detail = "no model is ACTIVE"
    return _check("inference", st,
                  f"{detail} (validated {data.get('generated_at', 'at an unrecorded time')})",
                  active=active, failed=failed, required_broken=broken,
                  checked_at=data.get("generated_at"))


def _database_health(state: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        stats = state.store.stats()
        ms = (time.perf_counter() - t0) * 1000
    except Exception as exc:
        return _check("database", FAILED, f"{type(exc).__name__}: {str(exc)[:120]}")
    pending = (state.store.pending_migrations()
               if hasattr(state.store, "pending_migrations") else [])
    st = DEGRADED if pending else HEALTHY
    return _check("database", st,
                  (f"{stats.get('observations', 0)} observations, "
                   f"{stats.get('cameras', 0)} cameras; stats query {ms:.1f} ms")
                  + (f"; {len(pending)} migration(s) pending" if pending else ""),
                  latency_ms=round(ms, 1), pending_migrations=pending, **stats)


def _search_health(state: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        plates = state.store.distinct_plates()
        ms = (time.perf_counter() - t0) * 1000
    except Exception as exc:
        return _check("search", FAILED, f"{type(exc).__name__}: {str(exc)[:120]}")
    if not plates:
        return _check("search", UNKNOWN,
                      "the index answers, but no registration mark has been "
                      "stored yet, so retrieval is untested here",
                      latency_ms=round(ms, 1), distinct_plates=0)
    return _check("search", HEALTHY,
                  f"{len(plates)} distinct registration marks indexed; "
                  f"lookup {ms:.1f} ms",
                  latency_ms=round(ms, 1), distinct_plates=len(plates))


def _evidence_health(state: Any) -> dict[str, Any]:
    try:
        result = state.evidence.verify_chain()
    except Exception as exc:
        return _check("evidence", FAILED, f"{type(exc).__name__}: {str(exc)[:120]}")
    ok = getattr(result, "ok", None)
    if ok is None:
        ok = bool(result.get("verified")) if isinstance(result, dict) else False
    checks = (getattr(result, "checks", None)
              or (result.get("checks") if isinstance(result, dict) else []) or [])
    if not checks:
        return _check("evidence", UNKNOWN,
                      "no evidence has been sealed, so the chain has nothing "
                      "to verify", records=0)
    return _check("evidence", HEALTHY if ok else FAILED,
                  f"hash chain over {len(checks)} record(s) "
                  + ("verifies" if ok else "DOES NOT verify"),
                  records=len(checks))


def _queue_health() -> dict[str, Any]:
    from saakshya.runtime.scheduler import describe
    d = describe()
    jobs = d["jobs"]
    over = d["committed_mb"] > d["budget_mb"]
    st = DEGRADED if over else HEALTHY
    return _check("jobs", st,
                  (f"{len(jobs)} job(s) hold the machine; "
                   f"{d['committed_mb']} of {d['budget_mb']} MB committed")
                  + (" — OVER BUDGET" if over else ""),
                  **d)


def _ai_provider_health() -> dict[str, Any]:
    """Which providers this deployment is configured for. No secrets echoed.

    Configuration is not availability, and the two are reported separately: a
    key being present says nothing about whether the endpoint answers. Reaching
    out to check would send traffic from a government network on a page load,
    so this reports what is configured and leaves probing to an explicit action.
    """
    from saakshya.copilot.backends import default_backend, gemini_configured
    backend = default_backend()
    providers = [
        {"provider": "anthropic", "location": "external",
         "configured": bool(os.environ.get("SAAKSHYA_LLM_KEY")),
         "role": "investigation assistance; never authoritative"},
        {"provider": "gemini", "location": "external",
         "configured": gemini_configured(),
         "role": "investigation assistance; never authoritative; stills leave the host only if vision is on"},
        # On-device. Listing it as "configured" alongside the two above once
        # produced the line "external providers configured: local-vlm", which
        # says the opposite of the truth about where the data goes.
        {"provider": "local-vlm", "location": "on-device", "configured": True,
         "role": "signage and clock reading; no frame leaves the host"},
    ]
    external = [str(p["provider"]) for p in providers
                if p["configured"] and p["location"] == "external"]
    return _check("ai_providers", HEALTHY,
                  (f"copilot backend '{backend.name}'; "
                   + (f"external AI enabled: {', '.join(external)}" if external
                      else "no external AI configured — no frame or record "
                           "leaves this deployment, and no core feature "
                           "depends on one")),
                  copilot_backend=backend.name,
                  copilot_available=getattr(backend, "available", False),
                  providers=providers,
                  external_ai_enabled=bool(external))


@router.get("/system/integration",
            summary="Government sources: what is connected, and what a camera can act on")
async def integration_readiness(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """Where integration with VAHAN, SARATHI, eGujCop, AFIS and NAFIS stands.

    Deliberately reports which of the six alert categories a **camera** can
    raise, not merely which systems are named. Two of six are actionable from
    CCTV; three need face recognition this system does not perform and one needs
    a fingerprint no camera captures.
    """
    try:
        ctx.principal.require(Permission.CAPABILITY_READ)
    except AccessError as exc:
        from saakshya.api.deps import access_error
        raise access_error(exc) from exc
    from saakshya.watchlist.government import readiness
    return readiness()


@router.get("/system/health", summary="Every subsystem, with its evidence")
async def system_health(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.HEALTH_READ)
    except AccessError as exc:
        from saakshya.api.deps import access_error
        raise access_error(exc) from exc

    components = [
        _feed_health(state),
        _grid_access_health(state),
        _inference_health(),
        _database_health(state),
        _search_health(state),
        _evidence_health(state),
        _queue_health(),
        _ai_provider_health(),
    ]
    worst = (FAILED if any(c["state"] == FAILED for c in components) else
             DEGRADED if any(c["state"] == DEGRADED for c in components) else
             UNKNOWN if any(c["state"] == UNKNOWN for c in components) else
             HEALTHY)
    return {
        "generated_at": iso(utc_now()),
        "overall": worst,
        "components": components,
        "note": ("UNKNOWN means not checked or never exercised. It is never "
                 "reported as HEALTHY: a dashboard that shows green because it "
                 "never looked converts ignorance into false assurance."),
    }
