"""The copilot's tool surface.

Every tool is a thin, typed wrapper over `InvestigationService` — the same code
the UI calls. Three properties follow from that and are the reason the copilot
is safe enough to ship:

* **No privileged path.** The copilot cannot reach data the signed-in officer
  cannot. Each tool takes the caller's `AuthContext`, so scope, permission and
  purpose binding apply identically.
* **No mutation.** There is no tool here that writes. The model can look and
  explain; it cannot add a vehicle to a watchlist, clear an alert, seal
  evidence or open a case. A language model with write access to a police
  system is a category of risk with no matching benefit — the officer clicks
  those buttons.
* **No parallel implementation.** Any number the copilot states came from the
  deterministic engine, because there is nowhere else for it to come from.

Tool results are also the *only* factual source the orchestrator will accept.
The grounding check in `orchestrator.py` verifies that against the model's
output rather than trusting it.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from saakshya.common.ist import annotate_ist
from saakshya.investigation import InvestigationService
from saakshya.investigation.cases import CaseService
from saakshya.security import AccessError, AuthContext


#: Named specialists for the copilot UI. They are the same read-only tools,
#: grouped so an officer can see *which deterministic engine* answered — not
#: autonomous agents that invent claims.
TOOL_SPECIALIST = {
    "list_estate": "estate",
    "get_camera_context": "estate",
    "get_camera_neighbors": "estate",
    "get_camera_capability": "estate",
    "search_plate": "identity",
    "search_vehicle": "identity",
    "query_watchlist": "identity",
    "explain_match": "identity",
    "build_trajectory": "timebase",
    "validate_trajectory": "timebase",
    "list_timebase": "timebase",
    "check_timebase": "timebase",
    "get_evidence": "evidence",
    "verify_evidence": "evidence",
    "draft_report": "evidence",
    "refuse_imagery": "evidence",
}

SPECIALISTS = (
    {"id": "coordinator",
     "role": "Routes the question to specialists. Narrates. Invents nothing."},
    {"id": "estate",
     "role": "Registry, capability, infrared, location basis. Never invents coordinates."},
    {"id": "identity",
     "role": "Plate search, watchlist, match explanation. Leads stay leads."},
    {"id": "timebase",
     "role": "Whether two cameras may share a timeline. Default is restrict, not join."},
    {"id": "evidence",
     "role": "Sealed manifests and verification. Refuses image enhancement."},
)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    #: Recorded so a reviewer can confirm by inspection that the set is read-only.
    mutates: bool = False

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": self.parameters}


def _t(t: str | None) -> datetime | None:
    if not t:
        return None
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def _require_time(t: str | None) -> datetime:
    """For tools where the timestamp is not optional.

    A model that omits or mangles a required argument must produce a clear tool
    error the officer can see, not a `None` that travels into the service layer
    and surfaces as a 500 several frames later.
    """
    parsed = _t(t)
    if parsed is None:
        raise ValueError(
            "seen_at is required and must be an ISO-8601 timestamp, "
            "e.g. 2026-09-01T08:41:00Z")
    return parsed


class ToolRegistry:
    """Builds and dispatches the copilot's tools for one authenticated caller."""

    def __init__(self, service: InvestigationService, cases: CaseService) -> None:
        self.service = service
        self.cases = cases
        self.tools: dict[str, Tool] = {}
        self._register()

    def _add(self, name: str, description: str, parameters: dict[str, Any],
             handler: Callable[..., Any]) -> None:
        self.tools[name] = Tool(name, description, parameters, handler)

    # -- registration -------------------------------------------------------- #
    def _register(self) -> None:
        s = self.service

        self._add(
            "search_plate",
            "Find every stored observation of a registration mark. Exact match "
            "unless fuzzy is set; fuzzy results are labelled REQUIRES_VERIFICATION "
            "and are leads, not identifications.",
            {"type": "object", "properties": {
                "plate": {"type": "string", "description": "registration mark"},
                "fuzzy": {"type": "boolean", "default": False},
                "t_from": {"type": "string", "description": "ISO-8601 lower bound"},
                "t_to": {"type": "string", "description": "ISO-8601 upper bound"},
            }, "required": ["plate"]},
            lambda ctx, plate, fuzzy=False, t_from=None, t_to=None: s.search_target(
                ctx, plate=plate, fuzzy=fuzzy, t_from=_t(t_from), t_to=_t(t_to)))

        self._add(
            "search_vehicle",
            "Find observations by attributes — colour, vehicle type, district, "
            "time. Returns observations matching a description. This narrows a "
            "search; it never identifies a vehicle.",
            {"type": "object", "properties": {
                "colour": {"type": "string"},
                "object_type": {"type": "string"},
                "district": {"type": "string"},
                "t_from": {"type": "string"}, "t_to": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            }},
            lambda ctx, colour=None, object_type=None, district=None,
            t_from=None, t_to=None, limit=100: s.search_target(
                ctx, colours=(colour,) if colour else None,
                object_types=(object_type,) if object_type else None,
                districts=(district,) if district else None,
                t_from=_t(t_from), t_to=_t(t_to), limit=limit))

        self._add(
            "get_camera_context",
            "Registry entry, measured health and measured capability for one "
            "camera, plus its evidenced neighbours.",
            {"type": "object", "properties": {
                "camera_id": {"type": "string"}}, "required": ["camera_id"]},
            self._camera_context)

        self._add(
            "get_camera_neighbors",
            "Cameras reachable from this one, ranked by learned transition "
            "behaviour: where to look next and why.",
            {"type": "object", "properties": {
                "camera_id": {"type": "string"},
                "seen_at": {"type": "string", "description": "ISO-8601"},
                "horizon_s": {"type": "number", "default": 900},
            }, "required": ["camera_id", "seen_at"]},
            lambda ctx, camera_id, seen_at, horizon_s=900.0: s.next_best_cameras(
                ctx, camera_id=camera_id, seen_at=_require_time(seen_at),
                horizon_s=horizon_s))

        self._add(
            "get_camera_capability",
            "Measured ANPR, appearance and presence grades for a camera, with "
            "the sample counts and statistics behind them. UNKNOWN means not "
            "enough evidence, not poor quality.",
            {"type": "object", "properties": {
                "camera_id": {"type": "string"}}, "required": ["camera_id"]},
            self._capability)

        self._add(
            "build_trajectory",
            "Build ranked route hypotheses for a registration mark from its "
            "observations. Legs are typed OBSERVED, UNOBSERVED, COVERAGE_GAP or "
            "CONTRADICTION.",
            {"type": "object", "properties": {
                "plate": {"type": "string"},
                "t_from": {"type": "string"}, "t_to": {"type": "string"},
            }, "required": ["plate"]},
            lambda ctx, plate, t_from=None, t_to=None: s.build_trajectory(
                ctx, plate=plate, t_from=_t(t_from), t_to=_t(t_to)))

        self._add(
            "validate_trajectory",
            "Check a built trajectory for physical implausibility, contradictions "
            "and coverage gaps, and report what weakens it.",
            {"type": "object", "properties": {
                "plate": {"type": "string"}}, "required": ["plate"]},
            self._validate_trajectory)

        self._add(
            "query_watchlist",
            "Check whether a registration mark is on the watchlist, and on whose "
            "authority. Purpose-bound.",
            {"type": "object", "properties": {
                "plate": {"type": "string"}}, "required": ["plate"]},
            self._watchlist)

        self._add(
            "get_evidence",
            "Retrieve the sealed evidence manifest for an observation: hashes, "
            "model versions, capture method and certificate status.",
            {"type": "object", "properties": {
                "observation_id": {"type": "string"}}, "required": ["observation_id"]},
            lambda ctx, observation_id: s.evidence_panel(ctx, observation_id))

        self._add(
            "verify_evidence",
            "Run the real cryptographic verification over an evidence record: "
            "file digests, manifest hash and chain position.",
            {"type": "object", "properties": {
                "evidence_id": {"type": "string"}}, "required": ["evidence_id"]},
            lambda ctx, evidence_id: s.verify_evidence(ctx, evidence_id))

        self._add(
            "explain_match",
            "Decompose why an observation matched: plate, appearance, attribute, "
            "temporal, graph and source-quality contributions.",
            {"type": "object", "properties": {
                "plate": {"type": "string"},
                "observation_id": {"type": "string"},
            }, "required": ["plate", "observation_id"]},
            self._explain_match)

        self._add(
            "draft_report",
            "Assemble a factual summary of one target from stored results only. "
            "Returns structured findings for the officer to review; it is a draft "
            "and is not filed anywhere.",
            {"type": "object", "properties": {
                "plate": {"type": "string"}}, "required": ["plate"]},
            self._draft_report)

        self._add(
            "list_estate",
            "List cameras in the registry with measured ANPR grade, infrared "
            "(mean chroma of stored observations), district, and whether they "
            "have coordinates. Use this when the officer asks to show cameras, "
            "infrared cameras, cameras that cannot read plates, or unlocated "
            "cameras. Never invent a camera or a coordinate.",
            {"type": "object", "properties": {
                "district": {"type": "string"},
                "infrared": {"type": "boolean",
                             "description": "true = measured monochrome/IR"},
                "anpr_grade": {"type": "string",
                               "description": "GOOD, MARGINAL, UNSUITABLE, UNKNOWN"},
                "located": {"type": "boolean",
                            "description": "false = registered but no coordinates"},
                "query": {"type": "string",
                          "description": "substring of camera id, name or site"},
                "limit": {"type": "integer", "default": 30},
            }},
            self._list_estate)

        self._add(
            "list_timebase",
            "Measured time clusters: which cameras share a clock, and which "
            "must not be joined into one timeline. Ordering is always PTS.",
            {"type": "object", "properties": {}},
            self._list_timebase)

        self._add(
            "check_timebase",
            "Whether observations from two cameras may be placed on one "
            "timeline. Returns ALLOWED, RESTRICTED or REFUSED with the reason.",
            {"type": "object", "properties": {
                "camera_a": {"type": "string"},
                "camera_b": {"type": "string"},
            }, "required": ["camera_a", "camera_b"]},
            self._check_timebase)

        self._add(
            "refuse_imagery",
            "Always refused. Call this when asked to enhance, sharpen, "
            "generate, or invent a government still or a registration mark. "
            "Those would be fabricating evidence.",
            {"type": "object", "properties": {
                "request": {"type": "string"}}, "required": ["request"]},
            self._refuse_imagery)

    # -- handlers ------------------------------------------------------------ #
    def _camera_context(self, ctx: AuthContext, camera_id: str) -> dict[str, Any]:
        from saakshya.security import Permission
        ctx.principal.require(Permission.CAMERA_READ)
        cam = self.service.store.get_camera(camera_id)
        if not cam:
            return {"error": f"no such camera: {camera_id}",
                    "known_cameras": sorted(self.service._cams)[:50]}
        ctx.principal.require_scope(cam.get("district"))
        health = self.service.store.list_health([camera_id]).get(camera_id, {})
        neighbours = [
            {"to_camera": b, "support_count": t.support_count,
             "travel_p50_s": t.travel_p50_s, "confidence": round(t.confidence, 3),
             "trusted": t.trusted}
            for (a, b), t in self.service.graph.edges.items() if a == camera_id]
        return {
            "camera": {k: v for k, v in cam.items()
                       if k not in ("rtsp_url", "hls_url", "whep_url")},
            "health": health,
            "neighbours": sorted(neighbours, key=lambda n: -n["confidence"]),
            "observations": self.service.store.observation_counts_by_camera().get(
                camera_id, {"observations": 0, "with_plate": 0}),
        }

    def _capability(self, ctx: AuthContext, camera_id: str) -> dict[str, Any]:
        from saakshya.security import Permission
        ctx.principal.require(Permission.CAPABILITY_READ)
        rows = self.service.store.list_capability([camera_id])
        if not rows:
            return {"camera_id": camera_id, "anpr": "UNKNOWN", "vehicle": "UNKNOWN",
                    "presence": "UNKNOWN", "samples": 0,
                    "note": ("This camera has not been graded. UNKNOWN means "
                             "insufficient evidence, not poor quality.")}
        return {"camera_id": camera_id, "bands": rows}

    def _watchlist(self, ctx: AuthContext, plate: str) -> dict[str, Any]:
        from saakshya.security import Permission
        ctx.authorise(Permission.WATCHLIST_READ)
        entries = self.service.watchlist.active_entries(plate)
        ctx.audit(self.service.store, "watchlist_read", target=plate,
                  result_count=len(entries))
        return {
            "plate": plate, "on_watchlist": bool(entries),
            "entries": [{"watchlist_id": e.watchlist_id, "category": str(e.category),
                         "priority": str(e.priority), "authority": e.authority,
                         "reason": e.reason, "source_system": e.source_system}
                        for e in entries],
            "provenance": ("Entries marked REPRESENTATIVE are this system's own "
                           "test data. No government watchlist is integrated."),
        }

    def _validate_trajectory(self, ctx: AuthContext, plate: str) -> dict[str, Any]:
        r = self.service.build_trajectory(ctx, plate=plate)
        hyps = r.get("hypotheses", [])
        if not hyps:
            return {"plate": plate, "valid": None,
                    "reason": r.get("reason", "no hypothesis to validate")}
        h = hyps[0]
        return {
            "plate": plate, "status": h["status"], "score": h["score"],
            "is_probability": False,
            "contradictions": h.get("contradictions", []),
            "coverage_gaps": h.get("coverage_gaps", []),
            "weakest_leg": min(h.get("legs", []),
                               key=lambda x: x.get("plausibility", 1.0), default=None),
            "evidence": h.get("evidence", {}),
            "anomalies": r.get("anomalies", []),
        }

    def _explain_match(self, ctx: AuthContext, plate: str,
                       observation_id: str) -> dict[str, Any]:
        res = self.service.search_target(ctx, plate=plate)
        for c in res.get("candidates", []):
            if c.get("observation_id") == observation_id:
                return {"observation_id": observation_id, "plate": plate,
                        "status": c.get("status"), "score": c.get("score"),
                        "decomposition": c.get("why"),
                        "warnings": c.get("warnings", [])}
        return {"error": f"{observation_id} is not among the results for {plate}",
                "available": [c.get("observation_id")
                              for c in res.get("candidates", [])][:20]}

    def _draft_report(self, ctx: AuthContext, plate: str) -> dict[str, Any]:
        traj = self.service.build_trajectory(ctx, plate=plate)
        obs = traj.get("observations", [])
        wl = self._watchlist(ctx, plate)
        hyp = (traj.get("hypotheses") or [{}])[0]
        return {
            "target": plate,
            "observation_count": len(obs),
            "cameras": sorted({o["camera_id"] for o in obs}),
            "first_seen": obs[0]["t_norm"] if obs else None,
            "last_seen": obs[-1]["t_norm"] if obs else None,
            "route": hyp.get("camera_sequence", []),
            "route_status": hyp.get("status"),
            "route_score": hyp.get("score"),
            "coverage_gaps": len(hyp.get("coverage_gaps", [])),
            "contradictions": len(hyp.get("contradictions", [])),
            "on_watchlist": wl["on_watchlist"],
            "evidence_available": sum(1 for o in obs if o.get("evidence_available")),
            "limitations": [
                "Route score is an ordering score, not a calibrated probability.",
                "Coverage gaps mean the system could not observe; they are not "
                "evidence about where the vehicle was.",
                "Any observation marked REQUIRES_VERIFICATION has not been "
                "confirmed by plate.",
            ],
        }

    def _list_estate(self, ctx: AuthContext, district: str | None = None,
                     infrared: bool | None = None, anpr_grade: str | None = None,
                     located: bool | None = None, query: str | None = None,
                     limit: int = 30) -> dict[str, Any]:
        from saakshya.analytics.quality import MONOCHROME_CHROMA
        from saakshya.security import Permission
        ctx.principal.require(Permission.CAMERA_READ)
        cams = self.service.store.list_cameras(district=district or None)
        scope = ctx.principal.scope_filter()
        if scope is not None:
            cams = [c for c in cams if c.get("district") in scope]
        caps = self.service.store.list_capability()
        cap_by: dict[str, dict[str, Any]] = {}
        for row in caps:
            cid = row.get("camera_id")
            if not cid:
                continue
            prefer = {"ALL": 0, "NIGHT": 1, "DAY": 2, "LOW_LIGHT": 3}
            current = cap_by.get(cid)
            if current is None or prefer.get(row.get("time_band"), 9) < prefer.get(
                    current.get("time_band"), 9):
                cap_by[cid] = row
        chroma = self.service.store.mean_chroma_by_camera()
        counts = self.service.store.observation_counts_by_camera()
        q = (query or "").strip().lower()
        grade_want = (anpr_grade or "").strip().upper() or None
        rows: list[dict[str, Any]] = []
        for cam in cams:
            cid = cam["camera_id"]
            mean_c = chroma.get(cid)
            is_ir = mean_c is not None and mean_c < MONOCHROME_CHROMA
            cap = cap_by.get(cid) or {}
            rec = {
                "camera_id": cid,
                "name": cam.get("name"),
                "district": cam.get("district"),
                "department": cam.get("department"),
                "site": cam.get("site"),
                "located": cam.get("lat") is not None and cam.get("lon") is not None,
                "location_basis": cam.get("location_basis"),
                "anpr_grade": cap.get("anpr_grade") or "UNKNOWN",
                "appearance_grade": cap.get("vehicle_reid_grade") or "UNKNOWN",
                "presence_grade": cap.get("presence_grade") or "UNKNOWN",
                "infrared": is_ir,
                "mean_chroma": round(mean_c, 4) if mean_c is not None else None,
                "observations": (counts.get(cid) or {}).get("observations", 0),
                "plated_observations": (counts.get(cid) or {}).get("with_plate", 0),
            }
            if infrared is True and not rec["infrared"]:
                continue
            if infrared is False and rec["infrared"]:
                continue
            if located is True and not rec["located"]:
                continue
            if located is False and rec["located"]:
                continue
            if grade_want and str(rec["anpr_grade"]).upper() != grade_want:
                continue
            if q:
                hay = " ".join(str(rec.get(k) or "") for k in
                               ("camera_id", "name", "district", "site")).lower()
                if q not in hay:
                    continue
            rows.append(rec)
        limit = max(1, min(int(limit or 30), 30))
        ir_n = sum(1 for r in rows if r["infrared"])
        unlocated_n = sum(1 for r in rows if not r["located"])
        return {
            "cameras": rows[:limit],
            "count": len(rows[:limit]),
            "matched": len(rows),
            "infrared_matched": ir_n,
            "unlocated_matched": unlocated_n,
            "filters": {"district": district, "infrared": infrared,
                        "anpr_grade": grade_want, "located": located, "query": query},
            "note": ("Infrared is MEASURED from mean_chroma of stored "
                     "observations, not from a camera setting. ANPR grades are "
                     "MEASURED. Cameras without coordinates are listed, never "
                     "placed. This is not a second video wall — stills stay on "
                     "this host unless the officer asks to describe one."),
        }

    def _list_timebase(self, ctx: AuthContext) -> dict[str, Any]:
        from saakshya.live.timebase import TimebaseRegistry
        from saakshya.security import Permission
        ctx.principal.require(Permission.CAMERA_READ)
        registry = TimebaseRegistry(self.service.store)
        clusters = registry.clusters()
        health = registry.all()
        scope = ctx.principal.scope_filter()
        cams = [c for c in self.service.store.list_cameras()
                if scope is None or c.get("district") in scope]
        cameras = []
        for cam in cams:
            cid = cam["camera_id"]
            h = health.get(cid)
            cameras.append({
                "camera_id": cid,
                "time_cluster": h.time_cluster if h else None,
                "pts_health": str(h.pts_health) if h else "UNKNOWN",
                "usable_for_correlation": bool(h and h.usable_for_correlation),
            })
        return {
            "clusters": [
                {"cluster_id": c.get("cluster_id"), "label": c.get("label"),
                 "basis": c.get("basis"), "cameras": c.get("cameras") or [],
                 "member_count": c.get("member_count"),
                 "max_skew_s": c.get("max_skew_s")}
                for c in clusters
            ],
            "cameras": cameras,
            "note": ("Ordering always uses presentation timestamps. A shared "
                     "cluster means these cameras may be reasoned about "
                     "together; it is not a route."),
        }

    def _check_timebase(self, ctx: AuthContext, camera_a: str,
                        camera_b: str) -> dict[str, Any]:
        from saakshya.live.timebase import TimebaseRegistry
        from saakshya.security import Permission
        ctx.principal.require(Permission.CAMERA_READ)
        for cid in (camera_a, camera_b):
            cam = self.service.store.get_camera(cid)
            if cam:
                ctx.principal.require_scope(cam.get("district"))
        verdict, reason = TimebaseRegistry(self.service.store).may_correlate(
            camera_a, camera_b)
        return {
            "camera_a": camera_a, "camera_b": camera_b,
            "verdict": str(verdict), "reason": reason,
            "note": ("This is whether two cameras may share a timeline, not "
                     "whether a vehicle travelled between them."),
        }

    def _refuse_imagery(self, ctx: AuthContext, request: str) -> dict[str, Any]:
        return {
            "refused": True,
            "request": (request or "")[:200],
            "reason": (
                "Government stills are not enhanced, sharpened, generated or "
                "inpainted. A plate invented or 'restored' by a model would be "
                "fabricated evidence (BSA s.63). Detection and ANPR stay on "
                "this host. Ask list_estate to show the real cameras instead."),
        }

    # -- dispatch ------------------------------------------------------------ #
    def call(self, name: str, args: dict[str, Any], ctx: AuthContext) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"no such tool: {name}",
                    "available": sorted(self.tools)}
        try:
            result = tool.handler(ctx, **args)
        except AccessError as exc:
            # Surfaced as data, so the model can explain the refusal rather than
            # inventing a reason for the empty result.
            return {"error": exc.code, "message": str(exc), "refused": True}
        except TypeError as exc:
            return {"error": "BAD_ARGUMENTS", "message": str(exc),
                    "expected": tool.parameters}
        except Exception as exc:
            return {"error": type(exc).__name__, "message": str(exc)}
        # Every timestamp gains an IST twin (`t_norm_ist` beside `t_norm`). The
        # model quoted UTC to officers reading IST screens; it now has the IST
        # string to quote and never has to convert a time zone itself.
        return annotate_ist(result if isinstance(result, dict) else {"result": result})

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self.tools.values()]

    def assert_read_only(self) -> None:
        """Called at construction time by the orchestrator. A mutating tool
        reaching this registry is a programming error, and it fails loudly at
        startup rather than the first time a model tries to use it."""
        mutating = [t.name for t in self.tools.values() if t.mutates]
        if mutating:
            raise RuntimeError(
                f"copilot tool registry contains mutating tools: {mutating}. "
                "The copilot is read-only by design.")


def compact(value: Any, *, limit: int = 6000) -> str:
    """Serialise a tool result for the model, truncated with the truncation
    stated. Silently cutting a result would let the model reason from a
    fragment while believing it had the whole thing."""
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return (text[:limit]
            + f'... [TRUNCATED: {len(text) - limit} more characters. '
              'Ask for a narrower query rather than assuming the remainder.]')
