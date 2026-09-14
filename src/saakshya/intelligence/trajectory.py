"""Trajectory reconstruction — ranked route hypotheses over observations.

Three commitments shape this module, and all three are about *not overclaiming*:

**Multiple hypotheses, not one answer.** When evidence is ambiguous the engine
returns several routes with scores, because forcing a single route hides the
ambiguity from the only party able to resolve it — the investigator.

**A coverage gap is not an absence.** If a vehicle is seen at C-021 and then at
C-047, and nothing lies between them that could have seen it, that is *absence
of evidence*. Reporting it as "the vehicle was not there" would be evidence of
absence, and the two are different claims. In a police investigation the
difference is the whole point.

**Contradictions are surfaced, never dropped.** A transition faster than the
observed envelope stays in the output with its alternative explanations
attached. Silently discarding it would make the route look cleaner than the
evidence supports.

Algorithm is deliberately the simplest one that works: order observations by
normalised time, enumerate paths consistent with the camera graph, score them,
rank. No learned ranker and no GNN — a k-shortest-path over a time-dependent
graph is explainable to a jury, runs in milliseconds at this scale, and is
replaceable behind :class:`TrajectorySolver` when labelled data exists.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from saakshya.common.ids import new_id
from saakshya.intelligence.graph import CameraGraph, haversine_m
from saakshya.store import VehicleObservation

log = logging.getLogger(__name__)


#: Above this implied straight-line speed a pair of sightings is not one
#: journey. Deliberately generous — well beyond any Indian road vehicle in
#: traffic, so a fast motorway run is never flagged — because the purpose is to
#: catch the impossible, not to police the brisk.
MAX_PLAUSIBLE_SPEED_KMH = 200.0

#: Below this separation, two sightings on different cameras are too close in
#: time for a speed to mean anything.
MIN_SEPARATION_S = 1.0


class LegKind(StrEnum):
    OBSERVED = "OBSERVED"           # both ends seen, transition evidenced
    COVERAGE_GAP = "COVERAGE_GAP"   # nothing between could have seen it
    UNOBSERVED = "UNOBSERVED"       # a capable camera saw nothing — weaker
    CONTRADICTION = "CONTRADICTION"  # physically implausible


class TrajectoryStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    REJECTED = "REJECTED"


@dataclass
class Leg:
    """One camera-to-camera step in a route."""

    from_camera: str
    to_camera: str
    from_time: datetime
    to_time: datetime
    dt_s: float
    kind: LegKind
    plausibility: float
    support_count: int
    explanation: str
    #: Cameras that lie between these two and could have seen the vehicle but
    #: produced no observation. Populated only for UNOBSERVED legs.
    silent_cameras: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "from_camera": self.from_camera, "to_camera": self.to_camera,
            "from_time": self.from_time.isoformat(),
            "to_time": self.to_time.isoformat(),
            "dt_s": round(self.dt_s, 1), "kind": str(self.kind),
            "plausibility": round(self.plausibility, 3),
            "support_count": self.support_count,
            "explanation": self.explanation,
            "silent_cameras": self.silent_cameras,
            "alternatives": self.alternatives,
        }


@dataclass
class TrajectoryHypothesis:
    trajectory_id: str
    target: str | None
    observation_ids: list[str]
    camera_sequence: list[str]
    timestamps: list[datetime]
    legs: list[Leg]
    score: float
    status: TrajectoryStatus
    #: Evidence strength, kept separate from score: a two-camera route on strong
    #: plate reads is more trustworthy than a five-camera route on weak ones.
    plate_confirmed_count: int = 0
    candidate_count: int = 0
    mean_observation_quality: float = 0.0
    coverage_gaps: list[Leg] = field(default_factory=list)
    contradictions: list[Leg] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        if len(self.timestamps) < 2:
            return 0.0
        return (self.timestamps[-1] - self.timestamps[0]).total_seconds()

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory_id,
            "target": self.target,
            "status": str(self.status),
            "score": round(self.score, 3),
            "camera_sequence": self.camera_sequence,
            "timestamps": [t.isoformat() for t in self.timestamps],
            "duration_s": round(self.duration_s, 1),
            "observation_ids": self.observation_ids,
            "legs": [x.to_dict() for x in self.legs],
            "evidence": {
                "plate_confirmed": self.plate_confirmed_count,
                "appearance_candidates": self.candidate_count,
                "mean_observation_quality": round(self.mean_observation_quality, 3),
            },
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "notes": self.notes,
        }


#: Scoring weights. Stated, not learned — see the calibration note in search.py.
W_TRANSITION = 0.45     # do the legs hold up physically
W_EVIDENCE = 0.35       # how much of the route is plate-confirmed
W_QUALITY = 0.20        # how good were the observations


class TrajectorySolver:
    """Builds ranked route hypotheses from a set of observations.

    Replaceable: the public surface is ``solve()``, so a learned ranker can be
    substituted without touching callers.
    """

    def __init__(self, graph: CameraGraph, *, max_hypotheses: int = 5) -> None:
        self.graph = graph
        self.max_hypotheses = max_hypotheses

    def _implied_speed_kmh(self, a: VehicleObservation, b: VehicleObservation,
                           dt: float) -> float | None:
        """Straight-line speed between two sightings, or None if unknowable.

        A straight line understates road distance, so this is the *most*
        generous reading of the pair: if even the direct line is impossible, the
        road route certainly is. Positions derived from a camera name are good
        to a few hundred metres, which does not matter at the scale this
        catches.
        """
        ca = self.graph.cameras.get(a.camera_id) or {}
        cb = self.graph.cameras.get(b.camera_id) or {}
        if None in (ca.get("lat"), ca.get("lon"), cb.get("lat"), cb.get("lon")):
            return None
        if dt <= MIN_SEPARATION_S:
            # Two sightings within a second of each other on different cameras
            # say nothing about speed; they say the timestamps are too close to
            # separate. Handled as a coalescing question, not a physics one.
            return None
        metres = haversine_m(ca["lat"], ca["lon"], cb["lat"], cb["lon"])
        return (metres / dt) * 3.6

    # -- leg analysis -------------------------------------------------------- #
    def _classify_leg(self, a: VehicleObservation, b: VehicleObservation) -> Leg:
        dt = (b.t_norm - a.t_norm).total_seconds()

        # A camera does not have a coverage gap with itself. Looping footage
        # (GJ32AG0028 ×38 on cam06) and a vehicle that lingers both produce
        # same-camera pairs; calling that "no camera could have observed the
        # vehicle" tells the investigator the opposite of what happened.
        if a.camera_id == b.camera_id:
            return Leg(
                a.camera_id, b.camera_id, a.t_norm, b.t_norm, dt,
                LegKind.OBSERVED, 1.0, 0,
                explanation=(
                    "same camera — looping footage or a later pass at this "
                    "mount, not a missing camera in between"),
            )

        edge = self.graph.edge(a.camera_id, b.camera_id)

        # Geometry first, before anything learned. The check below it requires a
        # *trusted* edge — three observed samples — so on a first sighting no
        # feasibility test ran at all, and a live demonstration produced a route
        # of 4.81 km in 4.2 seconds scored LIKELY at 0.685. That is 4,138 km/h.
        #
        # Physics does not need learning. Where both cameras have a position,
        # an implied speed above what any road vehicle can do is a contradiction
        # on the first sighting and every one after.
        speed = self._implied_speed_kmh(a, b, dt)
        if speed is not None and speed > MAX_PLAUSIBLE_SPEED_KMH:
            km = speed * dt / 3600.0
            return Leg(
                a.camera_id, b.camera_id, a.t_norm, b.t_norm, dt,
                LegKind.CONTRADICTION, 0.0,
                edge.support_count if edge is not None else 0,
                explanation=(
                    f"{km:.2f} km in {dt:.1f} s implies {speed:,.0f} km/h, "
                    f"above the {MAX_PLAUSIBLE_SPEED_KMH:,.0f} km/h ceiling for "
                    f"a road vehicle. These two sightings are not one journey."),
                alternatives=[
                    "OCR error on one of the two reads",
                    "cloned or duplicated registration mark",
                    "camera clock drift, or two cameras on different timebases",
                    "two distinct vehicles associated in error",
                    "an incorrect position on one of the two cameras",
                ],
            )

        if edge is not None and edge.trusted and not edge.feasible(dt):
            return Leg(
                a.camera_id, b.camera_id, a.t_norm, b.t_norm, dt,
                LegKind.CONTRADICTION, 0.0, edge.support_count,
                explanation=edge.explain(dt),
                alternatives=[
                    "OCR error on one of the two reads",
                    "cloned or duplicated registration mark",
                    "camera clock drift or incorrect timestamp",
                    "two distinct vehicles associated in error",
                ],
            )

        # Which cameras sit between these two, and could any of them have seen it?
        between = self._intermediate_cameras(a.camera_id, b.camera_id, dt)
        capable = [c for c in between if self._is_capable(c)]

        if edge is not None:
            plaus = edge.plausibility(dt)
            if capable:
                # A camera that could have seen it, did not. Weaker than a clean
                # direct transition, but not a contradiction — it may have been
                # offline, or the vehicle may have passed outside its view.
                return Leg(
                    a.camera_id, b.camera_id, a.t_norm, b.t_norm, dt,
                    LegKind.UNOBSERVED, plaus * 0.75, edge.support_count,
                    explanation=(f"{edge.explain(dt)}; {len(capable)} camera(s) on "
                                 f"this route produced no observation"),
                    silent_cameras=capable,
                )
            return Leg(a.camera_id, b.camera_id, a.t_norm, b.t_norm, dt,
                       LegKind.OBSERVED, plaus, edge.support_count,
                       explanation=edge.explain(dt))

        # No edge at all: nothing in the model connects these cameras.
        return Leg(
            a.camera_id, b.camera_id, a.t_norm, b.t_norm, dt,
            LegKind.COVERAGE_GAP, 0.3, 0,
            explanation=("no camera on record between these two, and no observed "
                         "transitions — this is absence of evidence, not evidence "
                         "that the vehicle was elsewhere"),
        )

    def _intermediate_cameras(self, a: str, b: str, dt_s: float) -> list[str]:
        """Cameras reachable from ``a`` that also reach ``b`` inside the window."""
        out = []
        for (fa, fb), _e in self.graph.edges.items():
            if fa != a or fb in (a, b):
                continue
            back = self.graph.edge(fb, b)
            if back is None:
                continue
            fwd = self.graph.edge(a, fb)
            if fwd is None:
                continue
            lo = (fwd.travel_p05_s or 0) + (back.travel_p05_s or 0)
            if lo <= dt_s * 1.5:
                out.append(fb)
        return sorted(set(out))

    def _is_capable(self, camera_id: str) -> bool:
        """Would this camera have been able to produce a usable observation?

        Conservative: a camera we have not measured is *not* counted as silent,
        because treating unmeasured cameras as capable would manufacture
        false negatives for the vehicle.
        """
        cam = self.graph.cameras.get(camera_id)
        if not cam:
            return False
        return bool(cam.get("enabled", True)) and cam.get("tier") in {"A", "B"}

    # -- solving ------------------------------------------------------------- #
    def solve(self, observations: list[VehicleObservation], *,
              target: str | None = None,
              candidates: list[VehicleObservation] | None = None
              ) -> list[TrajectoryHypothesis]:
        """Rank route hypotheses.

        ``observations`` are plate-confirmed. ``candidates`` are unconfirmed
        (typically appearance-derived) observations that *may* belong to the same
        vehicle; each produces an additional, lower-scoring hypothesis rather
        than being merged into the confirmed route.
        """
        confirmed, coalesced = self._coalesce(sorted(observations,
                                                     key=lambda o: o.t_norm))
        if not confirmed:
            return []

        hypotheses = [self._build(confirmed, target, [], coalesced=coalesced)]

        # Each candidate is offered as its own alternative route. We do not
        # combine them: an unverified observation should not silently become
        # part of the baseline answer.
        for c in (candidates or []):
            merged = sorted([*confirmed, c], key=lambda o: o.t_norm)
            if [o.camera_id for o in merged] == [o.camera_id for o in confirmed]:
                continue
            hypotheses.append(self._build(merged, target, [c.observation_id],
                                          coalesced=coalesced))

        hypotheses.sort(key=lambda h: -h.score)
        return hypotheses[:self.max_hypotheses]

    #: A vehicle passing one camera once is one sighting, however many track
    #: fragments the tracker produced. Occlusion by other traffic breaks a track
    #: and restarts it, so the same plate can be read three times in four
    #: seconds at the same camera. Left alone, those become "legs" from a camera
    #: to itself — and the leg classifier, correctly finding no camera between
    #: them, labels each one a COVERAGE GAP. That reads to an investigator as
    #: "the vehicle left the network here", which is the opposite of the truth.
    COALESCE_WINDOW_S = 120.0

    def _coalesce(self, ordered: list[VehicleObservation]
                  ) -> tuple[list[VehicleObservation], list[dict]]:
        """Merge track fragments: same camera, same plate, within the window.

        The highest-quality fragment survives, because it is the one an
        investigator should be shown and the one whose crop becomes evidence.
        What was merged is returned rather than discarded, so a route can always
        account for every observation that went into it.
        """
        if len(ordered) < 2:
            return ordered, []

        kept: list[VehicleObservation] = []
        merged: list[dict] = []
        group: list[VehicleObservation] = []

        def flush() -> None:
            if not group:
                return
            best = max(group, key=lambda o: (o.observation_quality or 0.0,
                                             o.plate_votes))
            kept.append(best)
            if len(group) > 1:
                merged.append({
                    "camera_id": best.camera_id,
                    "kept": best.observation_id,
                    "merged": [o.observation_id for o in group
                               if o.observation_id != best.observation_id],
                    "span_s": round((group[-1].t_norm
                                     - group[0].t_norm).total_seconds(), 1),
                    "reason": (f"{len(group)} track fragments of the same "
                               f"registration mark at {best.camera_id} within "
                               f"{self.COALESCE_WINDOW_S:.0f}s — one pass, not "
                               "several. Kept the highest-quality view."),
                })

        for o in ordered:
            if (group and o.camera_id == group[-1].camera_id
                    and o.plate and o.plate == group[-1].plate
                    and (o.t_norm - group[-1].t_norm).total_seconds()
                    <= self.COALESCE_WINDOW_S):
                group.append(o)
                continue
            flush()
            group = [o]
        flush()
        return kept, merged

    def _build(self, obs: list[VehicleObservation], target: str | None,
               candidate_ids: list[str], *,
               coalesced: list[dict] | None = None) -> TrajectoryHypothesis:
        notes: list[str] = []
        span_timestamps: list[datetime] | None = None
        # After fragment-coalesce, a looping publisher can still leave two
        # "passes" at the same camera because one gap exceeded 120 s. Those
        # are not two places. Collapse to one sighting; keep the span so
        # duration is the window of reads, not zero.
        if (len({o.camera_id for o in obs}) == 1 and len(obs) > 1
                and len({o.plate for o in obs if o.plate}) <= 1):
            first, last = obs[0], obs[-1]
            span_s = (last.t_norm - first.t_norm).total_seconds()
            cam = first.camera_id
            best = max(obs, key=lambda o: (o.observation_quality or 0.0,
                                           o.plate_votes or 0))
            n_reads = sum(1 + len(m.get("merged") or [])
                          for m in (coalesced or [])) or len(obs)
            notes.append(
                f"{n_reads} reads of this mark, all on {cam} over "
                f"{span_s:.0f}s. One camera — looping footage or repeated "
                "passes — not a route and not a coverage gap.")
            span_timestamps = [first.t_norm, last.t_norm]
            obs = [best]

        legs = [self._classify_leg(obs[i], obs[i + 1]) for i in range(len(obs) - 1)]

        gaps = [x for x in legs if x.kind is LegKind.COVERAGE_GAP]
        contras = [x for x in legs if x.kind is LegKind.CONTRADICTION]

        plate_n = sum(1 for o in obs if o.plate)
        qualities = [o.observation_quality for o in obs
                     if o.observation_quality is not None]
        mean_q = sum(qualities) / len(qualities) if qualities else 0.0

        transition = (sum(x.plausibility for x in legs) / len(legs)) if legs else 0.5
        evidence = plate_n / len(obs) if obs else 0.0
        score = W_TRANSITION * transition + W_EVIDENCE * evidence + W_QUALITY * mean_q

        for m in (coalesced or []):
            notes.append(m["reason"])
        if contras:
            # A contradiction caps the score regardless of everything else.
            score = min(score, 0.35)
            notes.append(f"{len(contras)} physically implausible transition(s) — "
                         f"route cannot be accepted without resolving them")
        if gaps:
            notes.append(f"{len(gaps)} coverage gap(s): no camera on record could "
                         f"have observed the vehicle on that leg")
        if candidate_ids:
            notes.append("includes unverified appearance candidate(s); identity on "
                         "those observations is not established")

        if contras or candidate_ids or evidence < 1.0:
            status = TrajectoryStatus.REQUIRES_VERIFICATION
        elif score >= 0.75:
            status = TrajectoryStatus.CONFIRMED
        elif score >= 0.5:
            status = TrajectoryStatus.LIKELY
        else:
            status = TrajectoryStatus.REQUIRES_VERIFICATION

        return TrajectoryHypothesis(
            trajectory_id=new_id("TJ"), target=target,
            observation_ids=[o.observation_id for o in obs],
            camera_sequence=[o.camera_id for o in obs],
            timestamps=span_timestamps or [o.t_norm for o in obs],
            legs=legs, score=float(max(0.0, min(1.0, score))), status=status,
            plate_confirmed_count=plate_n, candidate_count=len(candidate_ids),
            mean_observation_quality=mean_q,
            coverage_gaps=gaps, contradictions=contras, notes=notes,
        )
