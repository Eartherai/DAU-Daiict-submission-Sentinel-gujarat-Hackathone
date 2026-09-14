"""Administration — deliberately small, and deliberately read-only.

§43 asks for users, roles, departments, policies, the camera registry and
watchlists, and asks explicitly not to build a giant IAM product. So this
module shows what is configured and does not let it be configured over HTTP.

Two reasons that is the right shape here rather than laziness:

**Creating a user creates a credential.** A mint endpoint is a credential
factory reachable from the network; the same operation over a CLI on the host
requires shell access to the machine, which is a materially higher bar. User
management lives in `tools/admin/users.py`.

**An ADMIN cannot search.** The permission table gives ADMIN no access to
vehicle movement at all, so this router must not become a side door to it. The
camera registry here includes stream URLs — which investigators never see — and
that is exactly why it sits behind ADMIN rather than beside the investigation
routes.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from saakshya.api.deps import AuthDep, StateDep, access_error
from saakshya.security import ROLE_PERMISSIONS, AccessError, Permission, Role

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/users", summary="Users, roles and jurisdictions")
async def users(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """No token material is returned, ever — not even a prefix or a hint."""
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
    except AccessError as exc:
        raise access_error(exc) from exc
    rows = state.tokens.list_users()
    return {
        "users": [{
            "user_id": u["user_id"], "display_name": u["display_name"],
            "role": u["role"], "department": u["department"],
            "districts": u["districts"],
            "jurisdiction": "STATE" if not u["districts"] else ", ".join(u["districts"]),
            "badge_no": u["badge_no"], "enabled": bool(u["enabled"]),
        } for u in rows],
        "count": len(rows),
        "note": ("Users are created and tokens minted with tools/admin/users.py "
                 "on the host. There is no credential-issuing endpoint."),
    }


@router.get("/roles", summary="The role → permission table in force")
async def roles(ctx: AuthDep) -> dict[str, Any]:
    """The separation-of-duty argument, served as data.

    Published so it can be checked rather than taken on trust: an ADMIN holds no
    search permission, and an AUDITOR holds no evidence permission.
    """
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
    except AccessError as exc:
        raise access_error(exc) from exc
    return {
        "roles": {str(r): sorted(str(p) for p in perms)
                  for r, perms in ROLE_PERMISSIONS.items()},
        "separation_of_duty": {
            "admin_may_search": Permission.SEARCH_PLATE in ROLE_PERMISSIONS[Role.ADMIN],
            "auditor_may_read_evidence":
                Permission.EVIDENCE_READ in ROLE_PERMISSIONS[Role.AUDITOR],
            "note": ("Running the estate and investigating people are different "
                     "jobs. Both flags above must be false, and the module "
                     "asserts it at import time."),
        },
    }


@router.get("/cameras", summary="Full camera registry, including stream URLs")
async def cameras(state: StateDep, ctx: AuthDep,
                  district: str | None = None) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
        ctx.audit(state.store, "admin_registry_read", target=district or "ALL")
    except AccessError as exc:
        raise access_error(exc) from exc
    rows = state.store.list_cameras(district=district)
    return {"cameras": rows, "count": len(rows),
            "caveat": ("Stream URLs may carry credentials and are never returned "
                       "to investigator-facing endpoints.")}


@router.get("/policy", summary="Every threshold currently in force")
async def policy(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """Thresholds are configuration, and configuration an operator cannot read
    is configuration nobody can dispute. Everything that changes a decision is
    listed here with its value."""
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
    except AccessError as exc:
        raise access_error(exc) from exc

    from saakshya.gis.service import GAP_THRESHOLD_M, MAX_FEATURES
    from saakshya.intelligence.trajectory import TrajectorySolver
    from saakshya.security.access import PURPOSE_BOUND

    return {
        "capability_grading": asdict(state.capability.policy),
        "alerting": asdict(state.investigation.alerts.policy),
        "trajectory": {
            "coalesce_window_s": TrajectorySolver.COALESCE_WINDOW_S,
            "max_hypotheses": state.investigation.solver.max_hypotheses,
            "score_is_probability": False,
        },
        "gis": {"gap_threshold_m": GAP_THRESHOLD_M,
                "cluster_above_features": MAX_FEATURES},
        "limits": asdict(state.limits),
        "purpose_bound_operations": sorted(str(p) for p in PURPOSE_BOUND),
        "runtime": state.investigation.store.url.split("://")[0],
    }


@router.get("/departments", summary="Departments present in the registry")
async def departments(state: StateDep, ctx: AuthDep) -> dict[str, Any]:
    """Derived from the registry rather than maintained separately, so it cannot
    drift from the estate it describes."""
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc
    counts: dict[str, dict[str, int]] = {}
    for c in state.store.list_cameras():
        dept = c.get("department") or "UNRECORDED"
        d = counts.setdefault(dept, {"cameras": 0, "districts": 0})
        d["cameras"] += 1
    districts: dict[str, set] = {}
    for c in state.store.list_cameras():
        districts.setdefault(c.get("department") or "UNRECORDED",
                             set()).add(c.get("district"))
    for dept, d in counts.items():
        d["districts"] = len(districts.get(dept, set()))
    return {"departments": counts, "count": len(counts)}
