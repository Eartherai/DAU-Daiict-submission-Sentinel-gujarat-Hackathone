"""Graph-first hybrid vehicle search.

Stage order is the design, and it is the single most important decision in the
intelligence layer:

    1. STRUCTURED PRUNE   plate / time / district / camera / class      SQL
    2. GRAPH PRUNE        physically reachable cameras                  CTE
    3. CANDIDATE SCORING  attributes, quality, temporal fit             in-process
    4. RERANK + EXPLAIN   decomposed score, never a bare number

Why not ANN first, which is the conventional shape? Because we measured the
appearance signal on our own corpus and it was worse than useless for identity:
DINOv2 scored the decoy vehicle at 0.941 against the target while scoring the
target against its own other observation at 0.412. An architecture that retrieves
by appearance and filters afterwards would rank by that signal. Stages 1 and 2
use structure and physics, which do not suffer domain shift, so the fragile
signal only ever *orders an already-plausible set*.

Nothing here asserts identity. The output of a gap search is a ranked candidate
list marked as requiring operator verification, with every contributing term
visible so an investigator can disagree with a specific claim rather than with a
number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from saakshya.analytics.anpr import plate_status
from saakshya.analytics.attributes import colour_agreement, size_agreement
from saakshya.analytics.plates import agreement as plate_agreement
from saakshya.analytics.plates import parse, repair_candidates
from saakshya.intelligence.graph import CameraGraph, haversine_m
from saakshya.store import SearchFilter, Store, VehicleObservation

log = logging.getLogger(__name__)


@dataclass
class ScoreTerm:
    name: str
    value: float           # 0..1 contribution before weighting
    weight: float
    detail: str

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass
class Candidate:
    """One possible match, with its reasoning attached."""

    observation: VehicleObservation
    score: float
    terms: list[ScoreTerm] = field(default_factory=list)
    #: Never "MATCH". The system proposes; a human disposes.
    status: str = "REQUIRES_VERIFICATION"
    warnings: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        if self.score >= 0.75:
            return "STRONG"
        if self.score >= 0.5:
            return "MODERATE"
        if self.score >= 0.3:
            return "WEAK"
        return "VERY_WEAK"

    def explain(self) -> dict:
        """The 'Why this match?' payload. Every term, weighted, plus the weakest."""
        weakest = min(self.terms, key=lambda t: t.value, default=None)
        return {
            "score": round(self.score, 3),
            "band": self.band,
            "status": self.status,
            "camera_id": self.observation.camera_id,
            "observation_id": self.observation.observation_id,
            "time": self.observation.t_norm.isoformat() if self.observation.t_norm else None,
            "terms": [
                {"name": t.name, "value": round(t.value, 3), "weight": t.weight,
                 "contribution": round(t.contribution, 3), "detail": t.detail}
                for t in self.terms
            ],
            "primary_weakness": (
                f"{weakest.name}: {weakest.detail}" if weakest else None),
            "warnings": self.warnings,
        }


@dataclass
class SearchResult:
    query: dict
    candidates: list[Candidate]
    #: Which cameras were actually searched, and why the rest were not. This is
    #: the honesty counterpart to "we searched the whole state".
    cameras_considered: list[str] = field(default_factory=list)
    cameras_pruned: list[str] = field(default_factory=list)
    prune_reason: str = ""
    stage_counts: dict[str, int] = field(default_factory=dict)
    anomalies: list[dict] = field(default_factory=list)
    #: How the hits sit on the estate. A dozen reads of one mark on one camera
    #: is looping footage or repeated passes, not a fleet and not a route.
    sighting: dict | None = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "cameras_considered": self.cameras_considered,
            "cameras_pruned": self.cameras_pruned,
            "prune_reason": self.prune_reason,
            "stage_counts": self.stage_counts,
            "anomalies": self.anomalies,
            "sighting": self.sighting,
            "candidates": [c.explain() for c in self.candidates],
        }


def sighting_pattern(candidates: list[Candidate]) -> dict | None:
    """Describe where a plate was seen, without claiming a journey.

    On this grid a looping publisher re-presents the same vehicle on the same
    camera. Counting those as a fleet, or drawing a route from them, is the
    wrong answer. Two cameras is the only pattern that *could* be a movement,
    and even then only if they share a timebase.
    """
    obs = [c.observation for c in candidates if c.observation.plate]
    if len(obs) < 2:
        return None
    cams = sorted({o.camera_id for o in obs})
    times = sorted(o.t_norm for o in obs if o.t_norm)
    span_s = (times[-1] - times[0]).total_seconds() if len(times) >= 2 else 0.0
    if len(cams) == 1:
        return {
            "type": "SINGLE_CAMERA",
            "camera_id": cams[0],
            "cameras": cams,
            "hits": len(obs),
            "span_s": round(span_s, 1),
            "cross_camera": False,
            "message": (
                f"{len(obs)} reads of this mark, all on {cams[0]}. That is one "
                "camera — looping footage or repeated passes — not a "
                "multi-camera route. Cross-camera identity is not claimed."),
        }
    return {
        "type": "MULTI_CAMERA",
        "cameras": cams,
        "hits": len(obs),
        "span_s": round(span_s, 1),
        "cross_camera": True,
        "message": (
            f"{len(obs)} reads across {len(cams)} cameras ({', '.join(cams)}). "
            "A trajectory is possible only if those cameras share a timebase."),
    }


#: Weights. Deliberately conservative and *stated*, not learned: we have no
#: labelled held-out set, so calling the output a calibrated probability would be
#: an overclaim. The UI calls this an engineering score.
W_PLATE = 0.45
W_COLOUR = 0.20
W_SIZE = 0.10
W_GRAPH = 0.15
W_QUALITY = 0.10


class VehicleSearch:
    """Hybrid retrieval over observations, constrained by the camera graph."""

    def __init__(self, store: Store, graph: CameraGraph | None = None) -> None:
        self.store = store
        self.graph = graph or CameraGraph(store).load()

    def follow_vehicle(self, plate: str, *, t_from: datetime | None = None,
                       t_to: datetime | None = None, limit: int = 20,
                       actor: str = "system", role: str | None = None,
                       case_id: str | None = None,
                       purpose: str | None = None) -> dict:
        """Find subsequent, physically feasible sightings of a plate.

        This is intentionally a follow-up search, not an identity assertion:
        unplated observations are ranked leads and remain outside the route.
        Geometry is checked before scoring so a learned graph cannot make an
        impossible transition look plausible.
        """
        found = self.search_plate(plate, t_from=t_from, t_to=t_to,
                                  actor=actor, role=role, case_id=case_id,
                                  purpose=purpose)
        origins = [c.observation for c in found.candidates]
        contradictions: list[dict] = []
        candidates: list[dict] = []
        all_obs = self.store.search(SearchFilter(t_from=t_from, t_to=t_to,
                                                 limit=20_000))
        target = (parse(plate).canonical or plate.upper())
        seen_pairs: set[tuple[str, str, str]] = set()
        for origin in sorted(origins, key=lambda o: o.t_norm):
            for candidate in all_obs:
                if candidate.t_norm <= origin.t_norm or candidate.camera_id == origin.camera_id:
                    continue
                dt = (candidate.t_norm - origin.t_norm).total_seconds()
                if dt <= 0 or dt > 3600:
                    continue
                pair = (origin.observation_id, candidate.observation_id,
                        candidate.camera_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                cam_a = self.graph.cameras.get(origin.camera_id) or {}
                cam_b = self.graph.cameras.get(candidate.camera_id) or {}
                distance = None
                speed = None
                if None not in (cam_a.get("lat"), cam_a.get("lon"),
                                cam_b.get("lat"), cam_b.get("lon")):
                    distance = haversine_m(cam_a["lat"], cam_a["lon"],
                                           cam_b["lat"], cam_b["lon"])
                    if dt >= 1:
                        speed = distance / dt * 3.6
                if speed is not None and speed > 200.0:
                    contradictions.append({
                        "code": "ROUTE_CONTRADICTION",
                        "from_camera": origin.camera_id,
                        "to_camera": candidate.camera_id,
                        "from_observation_id": origin.observation_id,
                        "to_observation_id": candidate.observation_id,
                        "distance_m": round(distance or 0, 1),
                        "elapsed_s": round(dt, 1),
                        "implied_speed_kmh": round(speed, 1),
                        "reason": (
                            f"{distance / 1000:.2f} km in {dt:.1f} s implies "
                            f"{speed:,.0f} km/h, above the 200 km/h road ceiling"),
                    })
                    continue
                edge = self.graph.edge(origin.camera_id, candidate.camera_id)
                if edge is not None and edge.trusted and not edge.feasible(dt):
                    contradictions.append({
                        "code": "ROUTE_CONTRADICTION",
                        "from_camera": origin.camera_id,
                        "to_camera": candidate.camera_id,
                        "from_observation_id": origin.observation_id,
                        "to_observation_id": candidate.observation_id,
                        "distance_m": round(distance, 1)
                        if distance is not None else None,
                        "elapsed_s": round(dt, 1),
                        "implied_speed_kmh": round(speed, 1)
                        if speed is not None else None,
                        "reason": edge.explain(dt),
                    })
                    continue
                graph_score = edge.plausibility(dt) if edge else (
                    max(0.0, 1.0 - (speed or 0.0) / 200.0)
                    if speed is not None else 0.35)
                plate_score = plate_agreement(target, candidate.plate) \
                    if candidate.plate else 0.0
                colour_score = colour_agreement(origin.colour, candidate.colour)
                class_score = size_agreement(origin.object_type,
                                              candidate.object_type)
                quality = candidate.observation_quality or 0.0
                score = (0.40 * plate_score + 0.15 * colour_score
                         + 0.10 * class_score + 0.25 * graph_score
                         + 0.10 * quality)
                candidates.append({
                    "observation_id": candidate.observation_id,
                    "camera_id": candidate.camera_id,
                    "t_norm": candidate.t_norm.isoformat(),
                    "plate": candidate.plate,
                    "colour": candidate.colour,
                    "object_type": candidate.object_type,
                    "evidence_ref": candidate.evidence_ref,
                    "from_camera": origin.camera_id,
                    "from_observation_id": origin.observation_id,
                    "elapsed_s": round(dt, 1),
                    "distance_m": round(distance, 1) if distance is not None else None,
                    "implied_speed_kmh": round(speed, 1) if speed is not None else None,
                    "score": round(score, 3),
                    "status": "REQUIRES_VERIFICATION",
                    "terms": {
                        "plate": round(plate_score, 3),
                        "appearance_colour": round(colour_score, 3),
                        "vehicle_class": round(class_score, 3),
                        "time_route": round(graph_score, 3),
                        "source_quality": round(quality, 3),
                    },
                    "reason": ("same plate" if plate_score >= 0.99 else
                               "appearance/class/colour lead; plate unreadable"),
                })
        candidates.sort(key=lambda c: (-c["score"], c["t_norm"]))
        self.store.audit(actor, "follow_vehicle", role=role, case_id=case_id,
                         purpose=purpose, target=target,
                         result_count=len(candidates))
        rejected_ids = {c["to_observation_id"] for c in contradictions}
        route = [{
            "observation_id": o.observation_id, "camera_id": o.camera_id,
            "t_norm": o.t_norm.isoformat(), "plate": o.plate,
            "evidence_ref": o.evidence_ref,
        } for o in sorted(origins, key=lambda o: o.t_norm)
          if o.observation_id not in rejected_ids]
        return {
            "query": {"type": "follow_vehicle", "plate": target,
                      "t_from": t_from.isoformat() if t_from else None,
                      "t_to": t_to.isoformat() if t_to else None},
            "route": route,
            "timeline": sorted(route + candidates[:limit],
                               key=lambda item: item.get("t_norm", "")),
            "candidates": candidates[:limit],
            "contradictions": contradictions,
            "evidence_refs": sorted({o.evidence_ref for o in origins
                                     if o.evidence_ref}),
            "note": ("Candidates are ranked leads, not cross-camera identity. "
                     "Impossible transitions are excluded and listed explicitly."),
        }

    # -- stage 1: exact / fuzzy plate --------------------------------------- #
    def search_plate(self, plate: str, *, t_from: datetime | None = None,
                     t_to: datetime | None = None, fuzzy: bool = False,
                     actor: str = "system", role: str | None = None,
                     case_id: str | None = None,
                     purpose: str | None = None) -> SearchResult:
        """The mandatory query. Exact by default; fuzzy is opt-in and marked."""
        canon = parse(plate)
        target = canon.canonical if canon.valid else plate.upper()

        hits = self.store.search_plate(target, t_from=t_from, t_to=t_to)
        stage = {"exact": len(hits)}

        # A plate read on a single frame is a LEAD, not a confirmation: the
        # registration mark is exact but uncorroborated, and it must never wear
        # the same badge as one voted across frames. The distinction is carried
        # by the stored vote count, so it survives into search without a schema
        # change and cannot be lost by a caller who forgets it.
        candidates = []
        for o in hits:
            corroborated = (o.plate_votes or 0) >= 2
            frames_term = (f"{o.plate_votes} agreeing frames" if corroborated
                           else "a single frame — uncorroborated lead")
            candidates.append(Candidate(
                observation=o, score=1.0 if corroborated else 0.85,
                terms=[ScoreTerm("plate", 1.0 if corroborated else 0.85, W_PLATE,
                                 f"exact match on {target}, {frames_term}"),
                       ScoreTerm("source_quality", o.observation_quality or 0.0,
                                 W_QUALITY,
                                 f"observation quality {o.observation_quality:.2f}"
                                 if o.observation_quality is not None
                                 else "quality not measured")],
                status=plate_status(votes=o.plate_votes),
                warnings=[] if corroborated else
                    ["registration mark read on a single frame — an exact match "
                     "but not corroborated across frames; verify before acting"],
            ))

        if not hits:
            # One OCR-confusion away, and format-valid. Hard plates on this
            # estate produce O/0 and B/8 substitutions; treating those as "not
            # found" is how a designated vehicle vanishes. The stored mark is
            # not edited — the hit is labelled as a lookalike of the query.
            seen: set[str] = set()
            for pr in repair_candidates(plate):
                if pr.canonical == target:
                    continue
                for o in self.store.search_plate(
                        pr.canonical, t_from=t_from, t_to=t_to):
                    oid = o.observation_id or o.dedup_key
                    if oid in seen:
                        continue
                    seen.add(oid)
                    candidates.append(Candidate(
                        observation=o, score=0.7,
                        terms=[ScoreTerm(
                            "plate", 0.7, W_PLATE,
                            f"stored mark {o.plate} is one OCR confusion from "
                            f"queried {target} ({pr.reason}); the stored read "
                            f"was not edited")],
                        status="REQUIRES_VERIFICATION",
                        warnings=[
                            "matched via a known OCR confusion (O/0, B/8, …), "
                            "not an exact registration mark — verify before acting",
                        ],
                    ))
            stage["ocr_repair"] = len(candidates)

        if fuzzy and not candidates:
            # Only when exact and OCR-repair return nothing, and every result is labelled.
            everything = self.store.search(SearchFilter(t_from=t_from, t_to=t_to,
                                                        limit=20_000))
            for o in everything:
                if not o.plate:
                    continue
                a = plate_agreement(target, o.plate)
                if a >= 0.7:
                    candidates.append(Candidate(
                        observation=o, score=a * W_PLATE / (W_PLATE or 1),
                        terms=[ScoreTerm("plate", a, W_PLATE,
                                         f"fuzzy: {o.plate} vs {target} "
                                         f"({a:.0%} character agreement)")],
                        status="REQUIRES_VERIFICATION",
                        warnings=["fuzzy plate match — not an exact registration mark"],
                    ))
            stage["fuzzy"] = len(candidates)

        candidates.sort(key=lambda c: (-c.score, c.observation.t_norm))
        anomalies = self.graph.anomalies([c.observation for c in candidates])

        self.store.audit(actor, "search_plate", role=role,
                         case_id=case_id, purpose=purpose,
                         target=target, result_count=len(candidates))

        return SearchResult(
            query={"type": "plate", "plate": target, "fuzzy": fuzzy,
                   "t_from": t_from.isoformat() if t_from else None,
                   "t_to": t_to.isoformat() if t_to else None},
            candidates=candidates,
            cameras_considered=sorted({c.observation.camera_id for c in candidates}),
            prune_reason="indexed plate lookup; no graph prune required",
            stage_counts=stage, anomalies=anomalies,
            sighting=sighting_pattern(candidates),
        )

    # -- the hard case ------------------------------------------------------ #
    def find_gap_candidates(
        self, confirmed: list[VehicleObservation], *,
        reference: VehicleObservation | None = None,
        max_candidates: int = 10, actor: str = "system",
        role: str | None = None,
        case_id: str | None = None, purpose: str | None = None,
    ) -> SearchResult:
        """Find plate-less observations that could fill a gap in a known route.

        This is the unreadable-plate case. The vehicle passed a camera that could
        not read its plate, so plate search shows a hole. We look for what *could*
        have been there, constrained first by physics.

        ``reference`` supplies the attribute profile — normally the best-quality
        confirmed observation, because attributes read off a poor crop are the
        least reliable input available.
        """
        if len(confirmed) < 2:
            return SearchResult(
                query={"type": "gap", "error": "need at least two confirmed observations"},
                candidates=[], prune_reason="insufficient confirmed observations")

        ordered = sorted(confirmed, key=lambda o: o.t_norm)
        ref = reference or max(
            ordered, key=lambda o: (o.observation_quality or 0.0))

        gaps: list[tuple[VehicleObservation, VehicleObservation]] = []
        for i in range(len(ordered) - 1):
            a, b = ordered[i], ordered[i + 1]
            e = self.graph.edge(a.camera_id, b.camera_id)
            dt = (b.t_norm - a.t_norm).total_seconds()
            # A gap is a leg with no direct evidenced edge, or one that took far
            # longer than the edge's typical time — both suggest an unobserved
            # intermediate camera.
            if e is None or not e.trusted or (
                    e.travel_p95_s is not None and dt > e.travel_p95_s * 1.2):
                gaps.append((a, b))

        if not gaps:
            return SearchResult(
                query={"type": "gap", "target": ref.plate},
                candidates=[],
                prune_reason="no unexplained gap in the confirmed route",
                stage_counts={"gaps": 0})

        all_cams = {c["camera_id"] for c in self.store.list_cameras()}
        considered: set[str] = set()
        candidates: list[Candidate] = []
        stage = {"gaps": len(gaps)}

        for a, b in gaps:
            # STAGE 2 — graph prune. Cameras reachable from a, that also reach b.
            fwd = self.graph.reachable(a.camera_id, a.t_norm, b.t_norm)
            mids = {
                cam for cam in fwd
                if cam not in (a.camera_id, b.camera_id)
                and self.graph.edge(cam, b.camera_id) is not None
            }
            considered |= mids
            if not mids:
                continue

            # STAGE 1 — structured prune within the surviving cameras and window.
            window = self.store.search(SearchFilter(
                cameras=sorted(mids), t_from=a.t_norm, t_to=b.t_norm, limit=5000))
            stage["structured"] = stage.get("structured", 0) + len(window)

            # STAGE 3/4 — score what survived.
            for o in window:
                if o.plate:
                    continue          # already identified; not a gap candidate
                c = self._score_gap_candidate(o, ref, a, b)
                if c.score > 0:
                    candidates.append(c)

        candidates.sort(key=lambda c: -c.score)
        candidates = candidates[:max_candidates]
        stage["scored"] = len(candidates)

        self.store.audit(actor, "search_gap_candidates", role=role, case_id=case_id,
                         purpose=purpose, target=ref.plate,
                         result_count=len(candidates))

        return SearchResult(
            query={"type": "gap", "target": ref.plate,
                   "reference_observation": ref.observation_id,
                   "gaps": [{"from": a.camera_id, "to": b.camera_id,
                             "window_s": round((b.t_norm - a.t_norm).total_seconds(), 1)}
                            for a, b in gaps]},
            candidates=candidates,
            cameras_considered=sorted(considered),
            cameras_pruned=sorted(all_cams - considered),
            prune_reason=(
                f"graph prune: {len(considered)} of {len(all_cams)} cameras are "
                f"physically reachable within the gap window; the rest were not "
                f"searched"),
            stage_counts=stage,
        )

    def _score_gap_candidate(self, o: VehicleObservation,
                             ref: VehicleObservation,
                             a: VehicleObservation,
                             b: VehicleObservation) -> Candidate:
        terms: list[ScoreTerm] = []
        warnings: list[str] = []

        # No plate: the strongest term is absent, and that is stated rather than
        # silently redistributed into the others.
        terms.append(ScoreTerm(
            "plate", 0.0, W_PLATE,
            "no readable plate at this observation — this camera could not "
            "support ANPR here"))
        warnings.append("identity is not established by plate")

        col = colour_agreement(ref.colour, o.colour)
        terms.append(ScoreTerm(
            "colour", col, W_COLOUR,
            f"reference {ref.colour or 'unknown'} vs observed {o.colour or 'unknown'}"
            + (" (expected confusion on a degraded camera)" if col == 0.5 else "")))

        size = size_agreement(ref.object_type, o.object_type)
        terms.append(ScoreTerm(
            "size_class", size, W_SIZE,
            f"reference {ref.object_type} vs observed {o.object_type}"))

        # Temporal / graph plausibility across both legs of the gap.
        e_in = self.graph.edge(a.camera_id, o.camera_id)
        e_out = self.graph.edge(o.camera_id, b.camera_id)
        dt_in = (o.t_norm - a.t_norm).total_seconds()
        dt_out = (b.t_norm - o.t_norm).total_seconds()
        p_in = e_in.plausibility(dt_in) if e_in else 0.0
        p_out = e_out.plausibility(dt_out) if e_out else 0.0
        g = (p_in + p_out) / 2.0
        terms.append(ScoreTerm(
            "route_plausibility", g, W_GRAPH,
            f"{a.camera_id}→{o.camera_id} in {dt_in:.0f}s "
            f"({p_in:.2f}), {o.camera_id}→{b.camera_id} in {dt_out:.0f}s ({p_out:.2f})"))

        q = o.observation_quality or 0.0
        terms.append(ScoreTerm(
            "source_quality", q, W_QUALITY,
            f"observation quality {q:.2f}"
            + (" — LOW, treat with caution" if q < 0.4 else "")))
        if q < 0.4:
            warnings.append("low source quality — verify against the clip before acting")

        raw = sum(t.contribution for t in terms)
        # Renormalise over the terms that could contribute at all. Without this a
        # plate-less candidate is capped at 0.55 and never reads as plausible
        # even when every available signal agrees.
        available = sum(t.weight for t in terms if t.name != "plate")
        score = raw / available if available else 0.0
        # Quality gates the whole thing: a strong-looking match on an unusable
        # frame is exactly the false confidence this system exists to avoid.
        score *= (0.4 + 0.6 * q)

        return Candidate(observation=o, score=float(min(1.0, score)), terms=terms,
                         status="REQUIRES_VERIFICATION", warnings=warnings)
