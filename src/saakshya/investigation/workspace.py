"""The investigation facade.

Every capability the product offers is reachable through exactly one object.
The HTTP API calls it, the copilot calls it, the tests call it, and the offline
edge node calls the same code. That is not tidiness for its own sake: it is the
reason the copilot cannot do anything the UI cannot, cannot skip an
authorisation check, and cannot produce a number the deterministic path would
not have produced. The language model gets no privileged route into the data.

The other job of this layer is to make the *search strategy* legible. A system
that answers "not found" without saying where it looked is unusable in an
investigation — the officer cannot tell whether the vehicle was absent or the
question was badly asked. So every result here carries which cameras were
searched, which were excluded, and the specific reason each one was excluded.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from saakshya.analytics.anpr import plate_status
from saakshya.analytics.pipeline import PipelineConfig
from saakshya.analytics.plates import lookalikes
from saakshya.capability.grader import Grade, TimeBand
from saakshya.evidence import EvidenceService
from saakshya.intelligence import CameraGraph, Candidate, TrajectorySolver, VehicleSearch
from saakshya.security import AuthContext, OutOfScope, Permission
from saakshya.store import SearchFilter, Store, VehicleObservation
from saakshya.watchlist import AlertEngine, WatchlistService


class ExclusionReason:
    """The vocabulary of "why wasn't this camera searched".

    Fixed strings rather than free text so the UI can group them and the copilot
    cannot paraphrase one into something subtly different.
    """

    TEMPORAL = "OUTSIDE_TIME_WINDOW"
    UNREACHABLE = "UNREACHABLE_IN_GRAPH"
    UNAVAILABLE = "CAMERA_UNAVAILABLE"
    CAPABILITY = "CAPABILITY_INSUFFICIENT"
    SCOPE = "OUTSIDE_JURISDICTION"
    NO_DATA = "NO_OBSERVATIONS_STORED"

    TEXT: ClassVar[dict[str, str]] = {
        TEMPORAL: "outside the temporal feasibility window for this query",
        UNREACHABLE: "not reachable from the observed cameras within the window",
        UNAVAILABLE: "camera was not delivering frames for this period",
        CAPABILITY: "measured capability is insufficient for this analytic",
        SCOPE: "outside the requesting officer's jurisdiction",
        NO_DATA: "no observations stored for this camera in the window",
    }


@dataclass
class NextCamera:
    """One ranked suggestion. The fields are the decomposition, not a summary."""

    camera_id: str
    name: str | None
    lat: float | None
    lon: float | None
    transition_probability: float
    travel_time_fit: float
    camera_quality: float
    availability: str
    priority_score: float
    expected_arrival: datetime | None
    explanation: str
    capability: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id, "name": self.name,
            "lat": self.lat, "lon": self.lon,
            "transition_probability": round(self.transition_probability, 3),
            "travel_time_fit": round(self.travel_time_fit, 3),
            "camera_quality": round(self.camera_quality, 3),
            "availability": self.availability,
            "priority_score": round(self.priority_score, 3),
            "expected_arrival": (self.expected_arrival.isoformat()
                                 if self.expected_arrival else None),
            "capability": self.capability,
            "explanation": self.explanation,
        }


#: Weighting for the suggestion ranking. Transition evidence dominates because
#: it is the only term derived from the estate's own measured behaviour rather
#: than from a model or a declared property.
W_TRANSITION, W_FIT, W_QUALITY, W_AVAILABLE = 0.40, 0.25, 0.20, 0.15

_GRADE_SCORE = {"GOOD": 1.0, "DEGRADED": 0.5, "UNSUITABLE": 0.0, "UNKNOWN": 0.4}


class InvestigationService:
    """One entry point for target → observations → trajectory → evidence."""

    #: Hard ceiling on any single retrieval. An unbounded query against a
    #: statewide store is a denial of service with a search box in front of it.
    MAX_RESULTS = 2000

    def __init__(self, store: Store, graph: CameraGraph | None = None,
                 evidence: EvidenceService | None = None) -> None:
        self.store = store
        self.graph = graph or CameraGraph(store).load()
        self.search = VehicleSearch(store, self.graph)
        self.solver = TrajectorySolver(self.graph)
        self.watchlist = WatchlistService(store)
        self.alerts = AlertEngine(store)
        self.evidence = evidence or EvidenceService(store)
        self._cams = {c["camera_id"]: c for c in store.list_cameras()}

    def refresh(self) -> None:
        self._cams = {c["camera_id"]: c for c in self.store.list_cameras()}
        self.graph = self.graph.load()
        self.search = VehicleSearch(self.store, self.graph)
        self.solver = TrajectorySolver(self.graph)

    # -- scope helpers ------------------------------------------------------ #
    def _scoped_cameras(self, ctx: AuthContext) -> list[str]:
        scope = ctx.principal.scope_filter()
        if scope is None:
            return list(self._cams)
        return [cid for cid, c in self._cams.items() if c.get("district") in scope]

    def _out_of_scope_cameras(self, ctx: AuthContext) -> list[str]:
        scope = ctx.principal.scope_filter()
        if scope is None:
            return []
        return [cid for cid, c in self._cams.items() if c.get("district") not in scope]

    # -- target search ------------------------------------------------------ #
    def search_target(self, ctx: AuthContext, *, plate: str | None = None,
                      fuzzy: bool = False, colours: tuple[str, ...] | None = None,
                      object_types: tuple[str, ...] | None = None,
                      districts: tuple[str, ...] | None = None,
                      cameras: tuple[str, ...] | None = None,
                      t_from: datetime | None = None, t_to: datetime | None = None,
                      min_quality: float | None = None,
                      watchlist_only: bool = False,
                      limit: int = 200) -> dict[str, Any]:
        """The primary query. Plate, attributes, time, place — any combination.

        Ordering is deliberate: plate is an identifier and everything else is a
        filter. A result that matched on colour alone is never presented beside
        a plate match as though the two were the same kind of fact.
        """
        perm = Permission.SEARCH_PLATE if plate else Permission.SEARCH_APPEARANCE
        ctx.authorise(perm)
        limit = max(1, min(int(limit), self.MAX_RESULTS))

        if districts:
            for d in districts:
                ctx.principal.require_scope(d)
        scope = ctx.principal.scope_filter()
        eff_districts = tuple(districts) if districts else (scope or ())

        allowed = set(self._scoped_cameras(ctx))
        if cameras:
            bad = [c for c in cameras if c not in allowed]
            if bad:
                raise OutOfScope(f"cameras outside jurisdiction: {sorted(bad)}")

        searched = sorted(set(cameras) & allowed) if cameras else sorted(allowed)
        exclusions = self._exclusions(ctx, searched, t_from, t_to)

        if plate:
            res = self.search.search_plate(
                plate, t_from=t_from, t_to=t_to, fuzzy=fuzzy,
                actor=ctx.principal.user_id, role=str(ctx.principal.role),
                case_id=ctx.case_id, purpose=ctx.purpose)
            # Out-of-jurisdiction matches are withheld, and **saying so is
            # part of withholding them**. Dropping them silently returned
            # "0 results" for a registration mark this system had actually
            # seen — while `stage_counts` still reported the match — and an
            # investigator reading that would conclude the vehicle was never
            # observed. That is the most dangerous wrong answer this platform
            # can give: not a refusal, but a confident denial.
            #
            # The count and the districts are disclosed; the observations are
            # not. That is what an investigator needs in order to ask the right
            # force for access, and no more.
            cands: list[Candidate] = []
            withheld: list[Candidate] = []
            for c in res.candidates:
                (cands if c.observation.camera_id in allowed
                 else withheld).append(c)
            cands = cands[:limit]
            payload = res.to_dict()
            payload["candidates"] = [self._candidate_view(c) for c in cands]
            payload["result_count"] = len(cands)
            if withheld:
                where = sorted({
                    (self.store.get_camera(c.observation.camera_id) or {})
                    .get("district") or "district not recorded"
                    for c in withheld})
                payload["withheld"] = {
                    "count": len(withheld),
                    "reason": "OUT_OF_JURISDICTION",
                    "districts": where,
                    "message": (
                        f"{len(withheld)} further match(es) for this "
                        f"registration mark were found on cameras outside your "
                        f"jurisdiction ({', '.join(where)}) and are not shown. "
                        f"This is a restriction on you, not an absence of "
                        f"evidence."),
                }
                ctx.audit(self.store, "search_withheld",
                          target=plate, result_count=len(withheld))
        else:
            f = SearchFilter(
                cameras=searched or None,
                districts=list(eff_districts) or None,
                colours=list(colours) if colours else None,
                object_types=list(object_types) if object_types else None,
                t_from=t_from, t_to=t_to,
                min_observation_quality=min_quality, limit=limit)
            obs = self.store.search(f)
            ctx.audit(self.store, "search_attributes",
                      target=f"colours={colours} types={object_types}",
                      result_count=len(obs))
            payload = {
                "query": {"type": "attributes", "colours": list(colours or ()),
                          "object_types": list(object_types or ()),
                          "districts": list(eff_districts),
                          "t_from": t_from.isoformat() if t_from else None,
                          "t_to": t_to.isoformat() if t_to else None},
                "candidates": [self._observation_view(o, status="ATTRIBUTE_FILTER")
                               for o in obs],
                "result_count": len(obs),
                # An attribute filter is not a match. Saying so here means the UI
                # cannot accidentally present "white hatchback" — or a person
                # standing in frame — as an identification.
                "caveat": _attribute_caveat(object_types),
            }

        if watchlist_only:
            keep = []
            for c in payload["candidates"]:
                if c.get("plate") and self.watchlist.active_entries(c["plate"]):
                    keep.append(c)
            payload["candidates"] = keep
            payload["result_count"] = len(keep)

        payload["search_strategy"] = {
            "cameras_searched": searched,
            "cameras_searched_count": len(searched),
            "cameras_excluded": exclusions,
            "jurisdiction": ("STATE" if ctx.principal.statewide
                             else list(ctx.principal.districts)),
            "limit_applied": limit,
        }
        return payload

    def _exclusions(self, ctx: AuthContext, searched: list[str],
                    t_from: datetime | None, t_to: datetime | None
                    ) -> list[dict[str, Any]]:
        """Why each unsearched camera was left out. §26.

        Reported per camera rather than as a count, because "we excluded 400
        cameras" and "we excluded the four cameras on the route you care about"
        look the same in a summary and are not remotely the same thing.
        """
        out: list[dict[str, Any]] = []
        for cid in self._out_of_scope_cameras(ctx):
            out.append({"camera_id": cid, "reason": ExclusionReason.SCOPE,
                        "detail": ExclusionReason.TEXT[ExclusionReason.SCOPE]})
        health = self.store.list_health(searched)
        for cid in searched:
            h = health.get(cid, {})
            if h.get("state") in ("DOWN", "OPEN_FAILED"):
                out.append({
                    "camera_id": cid, "reason": ExclusionReason.UNAVAILABLE,
                    "detail": (f"{ExclusionReason.TEXT[ExclusionReason.UNAVAILABLE]}"
                               f" (state {h['state']})"),
                    # The distinction the whole system turns on.
                    "note": ("No result from this camera is absence of evidence, "
                             "not evidence of absence."),
                })
        return out

    # -- views -------------------------------------------------------------- #
    def _candidate_view(self, c: Any) -> dict[str, Any]:
        o = c.observation
        v = self._observation_view(o, status=c.status)
        v["score"] = round(c.score, 3)
        v["band"] = c.band
        v["why"] = c.explain()
        v["warnings"] = list(getattr(c, "warnings", []) or [])
        return v

    def _observation_view(self, o: VehicleObservation, *, status: str) -> dict[str, Any]:
        cam = self._cams.get(o.camera_id, {})
        return {
            "observation_id": o.observation_id,
            "camera_id": o.camera_id,
            "camera_name": cam.get("name"),
            "district": o.district or cam.get("district"),
            "department": o.department or cam.get("department"),
            "lat": o.lat if o.lat is not None else cam.get("lat"),
            "lon": o.lon if o.lon is not None else cam.get("lon"),
            "t_norm": o.t_norm.isoformat() if o.t_norm else None,
            "pts_s": o.pts_s,
            "track_id": o.track_id,
            "status": status,
            "plate": o.plate, "plate_raw": o.plate_raw,
            "plate_repairs": lookalikes(o.plate_raw or o.plate, exclude=o.plate),
            "plate_confidence": _r(o.plate_confidence), "plate_votes": o.plate_votes,
            "colour": o.colour, "colour_confidence": _r(o.colour_confidence),
            "object_type": o.object_type,
            "observation_quality": _r(o.observation_quality),
            "source_grade": o.source_grade,
            "sharpness": _r(o.sharpness), "luminance": _r(o.luminance),
            "plate_pixel_width": _r(o.plate_pixel_width, 1),
            "bbox": list(o.bbox) if o.bbox else None,
            "model_versions": o.model_versions,
            "evidence_id": o.evidence_ref,
            "evidence_available": o.evidence_ref is not None,
        }

    # -- trajectory --------------------------------------------------------- #
    def build_trajectory(self, ctx: AuthContext, *, plate: str,
                         t_from: datetime | None = None, t_to: datetime | None = None,
                         include_gap_candidates: bool = True) -> dict[str, Any]:
        ctx.authorise(Permission.TRAJECTORY_BUILD)
        res = self.search.search_plate(plate, t_from=t_from, t_to=t_to,
                                       actor=ctx.principal.user_id,
                                       role=str(ctx.principal.role),
                                       case_id=ctx.case_id, purpose=ctx.purpose)
        allowed = set(self._scoped_cameras(ctx))
        obs = [c.observation for c in res.candidates
               if c.observation.camera_id in allowed]
        if not obs:
            return {"target": plate, "hypotheses": [], "observations": [],
                    "reason": "no observations of this registration mark in scope",
                    "search_strategy": {"cameras_searched": sorted(allowed)}}

        gap_candidates: list[dict[str, Any]] = []
        if include_gap_candidates and len(obs) >= 2:
            gap = self.search.find_gap_candidates(
                obs, actor=ctx.principal.user_id, role=str(ctx.principal.role),
                case_id=ctx.case_id, purpose=ctx.purpose)
            gap_candidates = [self._candidate_view(c) for c in gap.candidates]

        hyps = self.solver.solve(obs, target=plate)
        ctx.audit(self.store, "trajectory_build", target=plate,
                  result_count=len(hyps))

        # A route is only as sound as the timebase underneath it. On a grid
        # where some cameras replay different weeks, joining two of them
        # produces a journey that never happened — so the verdict travels with
        # every hypothesis rather than being left for the reader to infer.
        timebase = self._timebase_verdict([o.camera_id for o in obs])

        return {
            "target": plate,
            "observations": [self._observation_view(
                o, status=plate_status(votes=o.plate_votes)) for o in obs],
            "hypotheses": [h.to_dict() for h in hyps],
            "gap_candidates": gap_candidates,
            "anomalies": res.anomalies,
            "timebase": timebase,
            # §27. The number is an engineering score. Nothing here has been
            # calibrated against a labelled held-out set, so calling it a
            # probability would be a claim we cannot support.
            "score_semantics": {
                "name": "TRAJECTORY SCORE",
                "is_probability": False,
                "note": ("An ordering score over hypotheses, not a calibrated "
                         "probability. Calibration requires labelled ground "
                         "truth, which this deployment does not yet have."),
            },
        }

    def follow_vehicle(self, ctx: AuthContext, *, plate: str,
                       t_from: datetime | None = None,
                       t_to: datetime | None = None,
                       limit: int = 20) -> dict[str, Any]:
        """Follow a plate while keeping unplated results as explicit leads."""
        ctx.authorise(Permission.TRAJECTORY_BUILD)
        result = self.search.follow_vehicle(
            plate, t_from=t_from, t_to=t_to, limit=max(1, min(limit, 100)),
            actor=ctx.principal.user_id, role=str(ctx.principal.role),
            case_id=ctx.case_id, purpose=ctx.purpose)
        allowed = set(self._scoped_cameras(ctx))
        # Do not disclose observations, route nodes, or evidence references
        # outside the requester's jurisdiction.
        result["route"] = [r for r in result["route"]
                           if r["camera_id"] in allowed]
        result["candidates"] = [c for c in result["candidates"]
                                if c["camera_id"] in allowed
                                and c["from_camera"] in allowed]
        result["contradictions"] = [c for c in result["contradictions"]
                                    if c["from_camera"] in allowed
                                    and c["to_camera"] in allowed]
        result["timeline"] = sorted(
            result["route"] + result["candidates"],
            key=lambda item: item.get("t_norm", ""))
        result["evidence_refs"] = sorted({
            r["evidence_ref"] for r in result["route"] + result["candidates"]
            if r.get("evidence_ref")
        })
        result["route_confidence"] = {
            "confirmed_sightings": len(result["route"]),
            "ranked_follow_ups": len(result["candidates"]),
            "contradictions": len(result["contradictions"]),
            "meaning": ("engineering ordering score; candidates require "
                        "operator verification, and are not identity claims"),
        }
        return result

    # -- next best camera (§25) ---------------------------------------------- #
    def next_best_cameras(self, ctx: AuthContext, *, camera_id: str,
                          seen_at: datetime, horizon_s: float = 900.0,
                          limit: int = 8) -> dict[str, Any]:
        """Where to look next, and why.

        This is the query that turns a statewide search from a scan into a plan.
        Capability is part of the ranking rather than a post-filter, so a camera
        that is physically next but measured UNSUITABLE for plate reading sinks
        below one that is further away and can actually answer the question.
        """
        ctx.principal.require(Permission.CAMERA_READ)
        allowed = set(self._scoped_cameras(ctx))
        caps = self._capability_map()
        quality = {cid: _GRADE_SCORE.get(c.get("anpr_grade") or "UNKNOWN", 0.4)
                   for cid, c in caps.items()}
        health = self.store.list_health(list(allowed))

        ranked = self.graph.next_best_cameras(
            camera_id, seen_at, horizon_s=horizon_s, limit=limit * 3,
            capability=quality)

        out: list[NextCamera] = []
        for cid, _score, why in ranked:
            if cid not in allowed:
                continue
            edge = self.graph.edge(camera_id, cid)
            if edge is None:
                continue
            cam = self._cams.get(cid, {})
            state = (health.get(cid, {}) or {}).get("state") or "UNKNOWN"
            avail = {"STREAMING": 1.0, "OK": 1.0, "RECONNECTING": 0.5,
                     "DEGRADED": 0.5, "UNKNOWN": 0.4}.get(state, 0.0)
            fit = edge.plausibility(min(horizon_s, edge.travel_p50_s or horizon_s))
            cap = caps.get(cid, {})
            q = quality.get(cid, 0.4)
            score = (W_TRANSITION * edge.confidence + W_FIT * fit
                     + W_QUALITY * q + W_AVAILABLE * avail)
            eta = (seen_at + timedelta(seconds=edge.travel_p50_s)
                   if edge.travel_p50_s else None)
            grades = {
                "anpr": cap.get("anpr_grade") or "UNKNOWN",
                "vehicle": cap.get("vehicle_reid_grade") or "UNKNOWN",
                "presence": cap.get("presence_grade") or "UNKNOWN",
            }
            note = why
            if grades["anpr"] == Grade.UNSUITABLE:
                note += ("; measured UNSUITABLE for plate reading — check for "
                         "presence, not identification")
            if state in ("DOWN", "OPEN_FAILED"):
                note += f"; camera is {state}, so silence here proves nothing"
            out.append(NextCamera(
                camera_id=cid, name=cam.get("name"),
                lat=cam.get("lat"), lon=cam.get("lon"),
                transition_probability=edge.confidence, travel_time_fit=fit,
                camera_quality=q, availability=state, priority_score=score,
                expected_arrival=eta, explanation=note, capability=grades))

        out.sort(key=lambda n: -n.priority_score)
        return {
            "origin": camera_id, "seen_at": seen_at.isoformat(),
            "horizon_s": horizon_s,
            "suggestions": [n.to_dict() for n in out[:limit]],
            "weights": {"transition": W_TRANSITION, "travel_time_fit": W_FIT,
                        "camera_quality": W_QUALITY, "availability": W_AVAILABLE},
            "note": ("Ranked by learned transition behaviour, not by road "
                     "distance. An empty list means the graph has no evidenced "
                     "link from this camera — not that the vehicle stopped."),
        }

    def _timebase_verdict(self, cameras: list[str]) -> dict[str, Any]:
        """Whether these cameras may be placed on one timeline, and why.

        Returns a verdict even when nothing has been measured — the honest
        default is RESTRICTED, and saying so is more useful than silence.
        """
        from saakshya.live.timebase import Correlation, TimebaseRegistry

        registry = TimebaseRegistry(self.store)
        distinct = sorted(set(cameras))
        partition = registry.correlatable_set(distinct)

        worst = Correlation.ALLOWED
        reasons: list[str] = []
        for i, a in enumerate(distinct):
            for b in distinct[i + 1:]:
                verdict, why = registry.may_correlate(a, b)
                if verdict is Correlation.REFUSED:
                    worst = Correlation.REFUSED
                    reasons.append(f"{a} + {b}: {why}")
                elif (verdict is Correlation.RESTRICTED
                      and worst is Correlation.ALLOWED):
                    worst = Correlation.RESTRICTED
                    reasons.append(f"{a} + {b}: {why}")

        # A route of one camera makes no cross-camera claim, and the pair loop
        # above never ran. Leaving the verdict at its ALLOWED default made the
        # system report "All cameras on this route share an established
        # timebase" for a single sighting on a camera belonging to no cluster —
        # true only vacuously, and read by anyone as a positive finding.
        if len(distinct) < 2:
            only = distinct[0] if distinct else None
            health = registry.get(only) if only else None
            sound = bool(health and health.usable_for_correlation)
            return {
                "verdict": str(Correlation.ALLOWED if sound
                               else Correlation.RESTRICTED),
                "message": (
                    "A single camera. There is no interval between sightings "
                    "to reason about, so no shared timebase is needed or "
                    "claimed."
                    + ("" if sound else " This camera's own timing has not been "
                       "established, so even its position on a timeline is "
                       "provisional.")),
                "detail": [],
                "partition": partition,
                "single_camera": True,
            }

        message = {
            Correlation.ALLOWED:
                "All cameras on this route share an established timebase. "
                "Travel times between them are meaningful.",
            Correlation.RESTRICTED:
                "A shared timebase has not been established for every pair on "
                "this route. The observations are real; the intervals between "
                "them may not be. Treat travel-time reasoning with caution.",
            Correlation.REFUSED:
                "At least one pair on this route cannot share a timeline — "
                "either a camera's own timing is unreliable, or the two replay "
                "different windows. This is not a journey.",
        }[worst]

        return {
            "verdict": str(worst),
            "message": message,
            "detail": reasons[:8],
            "partition": partition,
        }

    def _capability_map(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for r in self.store.list_capability(time_band=str(TimeBand.ALL)):
            out[r["camera_id"]] = r
        if out:
            return out
        for r in self.store.list_capability():
            cur = out.get(r["camera_id"])
            if cur is None or (r.get("samples") or 0) > (cur.get("samples") or 0):
                out[r["camera_id"]] = r
        return out

    # -- multi-observation retrieval (§24) ----------------------------------- #
    def observation_set(self, ctx: AuthContext, *, plate: str,
                        min_quality: float = 0.25,
                        max_observations: int = 12) -> dict[str, Any]:
        """Assemble the usable observation set for one vehicle.

        Multiple sightings of the same vehicle should strengthen a search, but
        only if the poor ones are excluded first. Averaging a crisp daylight crop
        with a blurred night one produces a profile that matches neither, so this
        selects rather than averages, and records exactly which observations
        contributed and which were set aside.
        """
        ctx.authorise(Permission.SEARCH_PLATE)
        allowed = set(self._scoped_cameras(ctx))
        obs = [o for o in self.store.search_plate(plate) if o.camera_id in allowed]
        if not obs:
            return {"plate": plate, "contributing": [], "excluded": [],
                    "reason": "no observations in scope"}

        contributing: list[VehicleObservation] = []
        excluded: list[dict[str, Any]] = []
        for o in sorted(obs, key=lambda x: -(x.observation_quality or 0.0)):
            q = o.observation_quality or 0.0
            if q < min_quality:
                excluded.append({"observation_id": o.observation_id,
                                 "camera_id": o.camera_id,
                                 "observation_quality": _r(q),
                                 "reason": f"quality {q:.2f} below {min_quality:.2f}"})
            elif len(contributing) >= max_observations:
                excluded.append({"observation_id": o.observation_id,
                                 "camera_id": o.camera_id,
                                 "observation_quality": _r(q),
                                 "reason": f"beyond the top {max_observations} by quality"})
            else:
                contributing.append(o)

        colours = Counter(o.colour for o in contributing if o.colour)
        types = Counter(o.object_type for o in contributing if o.object_type)
        agreement = (colours.most_common(1)[0][1] / len(contributing)
                     if contributing and colours else 0.0)
        return {
            "plate": plate,
            "contributing": [self._observation_view(o, status="CONTRIBUTING")
                             for o in contributing],
            "excluded": excluded,
            "consensus": {
                "colour": colours.most_common(1)[0][0] if colours else None,
                "colour_agreement": round(agreement, 3),
                "object_type": types.most_common(1)[0][0] if types else None,
                "cameras": sorted({o.camera_id for o in contributing}),
                "span_s": round((max(o.t_norm for o in contributing)
                                 - min(o.t_norm for o in contributing)).total_seconds(), 1)
                if len(contributing) > 1 else 0.0,
            },
            "method": ("Quality-filtered selection, not averaging. Observations "
                       "below the quality floor are listed rather than discarded "
                       "silently."),
        }

    # -- evidence ------------------------------------------------------------ #
    def evidence_panel(self, ctx: AuthContext, observation_id: str) -> dict[str, Any]:
        ctx.principal.require(Permission.EVIDENCE_READ)
        obs = self.store.search(SearchFilter(limit=1, plate=None))
        found = self._observation_by_id(observation_id)
        if found is None:
            return {"error": "no such observation", "observation_id": observation_id}
        ctx.principal.require_scope(found.district)
        cam = self._cams.get(found.camera_id, {})
        panel = {
            "observation": self._observation_view(found, status="STORED"),
            "camera": {
                "camera_id": found.camera_id, "name": cam.get("name"),
                "district": cam.get("district"), "department": cam.get("department"),
                "lat": cam.get("lat"), "lon": cam.get("lon"),
                "codec": cam.get("codec"), "width": cam.get("width"),
                "height": cam.get("height"), "declared_fps": cam.get("declared_fps"),
            },
            "timing": {
                "pts_s": found.pts_s,
                "t_norm": found.t_norm.isoformat() if found.t_norm else None,
                "t_ingest": found.t_ingest.isoformat() if found.t_ingest else None,
                "note": ("pts_s is the decoder's presentation timestamp; t_norm is "
                         "the normalised time derived from it. Ordering always "
                         "uses PTS, never arrival order."),
                "caveat": ("t_norm is when this system observed the vehicle. "
                           "A clock burned into the image is the scene's time "
                           "and may differ — on a replayed feed, by hours or by "
                           "weeks. The two are never reconciled silently, and "
                           "no ordering decision reads the overlay."),
            },
            "evidence": None,
        }
        del obs
        if found.evidence_ref:
            m = self.evidence.load(found.evidence_ref)
            if m:
                panel["evidence"] = m.to_dict()
        return panel

    def verify_evidence(self, ctx: AuthContext, evidence_id: str) -> dict[str, Any]:
        """Runs the real cryptographic verification. There is no stub path."""
        ctx.principal.require(Permission.EVIDENCE_READ)
        v = self.evidence.verify(evidence_id)
        ctx.audit(self.store, "evidence_verify", target=evidence_id,
                  result_count=1 if v.ok else 0)
        return v.to_dict()

    def _observation_by_id(self, observation_id: str) -> VehicleObservation | None:
        from sqlalchemy import select

        from saakshya.store import schema as S
        with self.store.engine.connect() as c:
            r = c.execute(select(S.observations).where(
                S.observations.c.observation_id == observation_id)).first()
        return VehicleObservation.from_row(r) if r else None

    # -- home screen (§42) ---------------------------------------------------- #
    def operational_summary(self, ctx: AuthContext) -> dict[str, Any]:
        ctx.principal.require(Permission.CAMERA_READ)
        allowed = {
            cid for cid in self._scoped_cameras(ctx)
            if (self.store.get_camera(cid) or {}).get("enabled", True)
        }
        health = self.store.list_health(list(allowed))
        observed = self.store.observed_camera_ids()
        states: Counter[str] = Counter()
        for cid in allowed:
            st = (health.get(cid, {}) or {}).get("state")
            if not st:
                # A missing health row is not UNKNOWN-as-unseen when the
                # store already holds observations from that camera.
                st = "OBSERVED" if cid in observed else "UNKNOWN"
            states[st] += 1
        alerts = (self.alerts.list_alerts() if ctx.principal.may(Permission.ALERT_READ)
                  else [])
        alerts = [a for a in alerts if a.get("camera_id") in allowed]
        caps = self._capability_map()
        cap_tally: Counter[str] = Counter()
        for cid in allowed:
            cap_tally[(caps.get(cid, {}) or {}).get("anpr_grade") or "UNKNOWN"] += 1
        st = self.store.stats()
        try:
            from saakshya.live.preview import count_stills
            n_still = count_stills()
        except Exception:
            n_still = 0
        return {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "jurisdiction": ("STATE" if ctx.principal.statewide
                             else list(ctx.principal.districts)),
            "cameras": {
                "total": len(allowed),
                "by_state": dict(states),
                "with_still": n_still,
                "published_marks": st.get("cameras_with_plate", 0),
            },
            "capability_anpr": dict(cap_tally),
            "alerts": {
                "open": sum(1 for a in alerts if a.get("status") == "OPEN"),
                "total": len(alerts),
                "recent": alerts[:10],
            },
            "observations": {
                "total": st.get("observations", 0),
                "with_plate": st.get("observations_with_plate", 0),
                "plate_confirmed": st.get("observations_plate_confirmed", 0),
                "plate_leads": st.get("observations_plate_leads", 0),
                "persons": st.get("observations_person", 0),
                "person_long_stay": st.get("observations_person_long_stay", 0),
                "person_long_stay_cameras": st.get(
                    "cameras_person_long_stay", 0),
                "person_dwell_s": PipelineConfig().person_dwell_s,
                "cameras_with_plate": st.get("cameras_with_plate", 0),
                "distinct_plates": st.get("distinct_plates", 0),
                "raw_ocr_attempts": st.get("raw_ocr_read_records", 0),
                "by_object_type": st.get("observations_by_object_type", {}),
                "recent_plates": self.store.distinct_plates()[:80],
                "recent_marks": self.store.recent_marks(36),
                "marks_last_hour": self.store.marks_in_latest_hour(),
            },
            "graph": self.graph.stats(),
        }


def _attribute_caveat(object_types: tuple[str, ...] | None) -> str:
    types = {t.lower() for t in (object_types or ())}
    if types == {"person"}:
        return ("These are person observations matching the filter. "
                "Position, time and dwell are reported; identity is not.")
    return ("These are observations matching the stated attributes. "
            "Attributes narrow a search; they do not identify a vehicle.")


def _r(v: Any, places: int = 3) -> float | None:
    return None if v is None else round(float(v), places)
