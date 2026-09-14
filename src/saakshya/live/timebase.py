"""Timebase health and cross-camera time clustering.

The question this module answers is narrow and load-bearing: **may these two
observations be placed on one timeline?**

On the live Gujarat grid the answer is not uniform. Twelve cameras replay a
common window; others are hours apart; four are on entirely different dates;
ten burn no clock at all. A system that assumes a global clock will happily
join a scene from 14 June to one from 4 August and call the result a journey.
A system that assumes no clock will refuse correlations that are perfectly
sound. Both are wrong, and the difference is measurable.

Three rules:

1. **Ordering is always PTS.** Nothing here is used to order anything. A clock
   burned into an image is the scene's time; the observation's time is when this
   system received it, and the two are never reconciled silently.
2. **Correlation is a property of a pair, not of the estate.** Two cameras may
   be correlated when there is evidence they share a timebase — and the default,
   absent evidence, is RESTRICTED rather than permitted.
3. **The basis is recorded.** A cluster established by reading overlay clocks
   and one declared by an operator carry different weight, and an investigator
   is entitled to know which they are relying on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import insert, select, update

from saakshya.store import schema as S
from saakshya.store.repository import Store, now_us


class PtsHealth(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNRELIABLE = "UNRELIABLE"
    UNKNOWN = "UNKNOWN"


class OverlayClock(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class ClusterBasis(StrEnum):
    #: Established by reading the cameras' own burned-in clocks. The strongest
    #: evidence available without a synchronisation protocol.
    MEASURED_OVERLAY = "MEASURED_OVERLAY"
    #: Asserted by an operator or a configuration file. Trusted, but recorded as
    #: an assertion rather than a measurement.
    DECLARED = "DECLARED"
    #: Derived from observed vehicle transitions. Circular for the purpose of
    #: validating those transitions, so it is never used to permit correlation —
    #: only to flag a discrepancy worth a human look.
    INFERRED = "INFERRED"


class Correlation(StrEnum):
    ALLOWED = "ALLOWED"
    RESTRICTED = "RESTRICTED"
    REFUSED = "REFUSED"


#: A live stream whose PTS advances at well under wall time is dropping periods
#: of itself. Measured on cam15: 0.396x.
MIN_REALTIME_RATIO = 0.80

#: Cameras within this skew are treated as one timebase for correlation. Chosen
#: against the measured spread of the synchronised twelve, which sat inside
#: three minutes — and most of that was the time taken to sample them.
CLUSTER_SKEW_TOLERANCE_S = 300.0


@dataclass
class TimebaseHealth:
    """What is known about one camera's sense of time."""

    camera_id: str
    pts_health: PtsHealth = PtsHealth.UNKNOWN
    pts_regressions: int = 0
    pts_forward_jumps: int = 0
    realtime_ratio: float | None = None
    measured_fps: float | None = None
    mean_interframe_gap_s: float | None = None
    max_interframe_gap_s: float | None = None
    overlay_clock: OverlayClock = OverlayClock.UNKNOWN
    overlay_reading: str | None = None
    scene_offset_s: float | None = None
    time_cluster: str | None = None
    cluster_confidence: str = "UNKNOWN"
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def usable_for_correlation(self) -> bool:
        """Whether this camera's own timing is sound enough to correlate at all.

        Separate from whether it shares a cluster with another: a camera whose
        PTS jumps backwards cannot be placed on any timeline, cluster or no.
        """
        return self.pts_health in (PtsHealth.OK, PtsHealth.DEGRADED)

    def row(self) -> dict[str, Any]:
        return {
            "pts_health": str(self.pts_health),
            "pts_regressions": self.pts_regressions,
            "pts_forward_jumps": self.pts_forward_jumps,
            "realtime_ratio": self.realtime_ratio,
            "measured_fps": self.measured_fps,
            "mean_interframe_gap_s": self.mean_interframe_gap_s,
            "max_interframe_gap_s": self.max_interframe_gap_s,
            "overlay_clock": str(self.overlay_clock),
            "overlay_reading": self.overlay_reading,
            "overlay_read_at_us": now_us() if self.overlay_reading else None,
            "scene_offset_s": self.scene_offset_s,
            "time_cluster": self.time_cluster,
            "cluster_confidence": self.cluster_confidence,
            "evidence": json.dumps(self.evidence) if self.evidence else None,
            "updated_at_us": now_us(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "pts_health": str(self.pts_health),
            "pts_regressions": self.pts_regressions,
            "realtime_ratio": self.realtime_ratio,
            "measured_fps": self.measured_fps,
            "max_interframe_gap_s": self.max_interframe_gap_s,
            "overlay_clock": str(self.overlay_clock),
            "overlay_reading": self.overlay_reading,
            "time_cluster": self.time_cluster,
            "cluster_confidence": self.cluster_confidence,
            "usable_for_correlation": self.usable_for_correlation,
            "evidence": self.evidence,
        }


def assess_pts(*, regressions: int, forward_jumps: int,
               realtime_ratio: float | None, max_gap_s: float | None,
               frames: int) -> tuple[PtsHealth, str]:
    """Grade a camera's timing from measured stream behaviour."""
    if frames < 40:
        return (PtsHealth.UNKNOWN,
                f"only {frames} frames observed; not enough to judge timing")
    if regressions > 5:
        return (PtsHealth.UNRELIABLE,
                f"{regressions} PTS regressions — this stream restarts often "
                "enough that ordering across a restart cannot be trusted")
    if regressions > 0:
        return (PtsHealth.DEGRADED,
                f"{regressions} PTS regression(s); each is a scene "
                "discontinuity that long-lived state must recover from")
    if realtime_ratio is not None and realtime_ratio < MIN_REALTIME_RATIO:
        return (PtsHealth.DEGRADED,
                f"PTS advances at {realtime_ratio:.2f}x wall time — periods of "
                "this stream are simply not delivered")
    if max_gap_s is not None and max_gap_s > 3.0:
        return (PtsHealth.DEGRADED,
                f"largest inter-frame gap {max_gap_s:.1f}s")
    return (PtsHealth.OK,
            f"monotonic PTS over {frames} frames"
            + (f" at {realtime_ratio:.2f}x wall time" if realtime_ratio else ""))


class TimebaseRegistry:
    """Stores timebase health and decides what may be correlated."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # -- health ------------------------------------------------------------ #
    def record(self, health: TimebaseHealth) -> None:
        row = {**health.row(), "camera_id": health.camera_id}
        with self.store.engine.begin() as c:
            exists = c.execute(select(S.camera_timebase.c.camera_id).where(
                S.camera_timebase.c.camera_id == health.camera_id)).first()
            if exists:
                c.execute(update(S.camera_timebase)
                          .where(S.camera_timebase.c.camera_id == health.camera_id)
                          .values(**{k: v for k, v in row.items()
                                     if k != "camera_id"}))
            else:
                c.execute(insert(S.camera_timebase).values(**row))

    def get(self, camera_id: str) -> TimebaseHealth | None:
        with self.store.engine.connect() as c:
            r = c.execute(select(S.camera_timebase).where(
                S.camera_timebase.c.camera_id == camera_id)).first()
        return _from_row(r._mapping) if r else None

    def all(self) -> dict[str, TimebaseHealth]:
        with self.store.engine.connect() as c:
            rows = list(c.execute(select(S.camera_timebase)))
        return {r._mapping["camera_id"]: _from_row(r._mapping) for r in rows}

    # -- clusters ----------------------------------------------------------- #
    def declare_cluster(self, cluster_id: str, cameras: list[str], *,
                        label: str = "", basis: ClusterBasis = ClusterBasis.DECLARED,
                        reference_time: str | None = None,
                        max_skew_s: float | None = None,
                        note: str = "") -> dict[str, Any]:
        """Record a set of cameras believed to share a timebase.

        The basis travels with the cluster into every response. A cluster read
        off the cameras' own clocks and one asserted in a configuration file are
        both usable; they are not equally strong, and the interface says which.
        """
        t = now_us()
        row = {
            "cluster_id": cluster_id, "label": label or cluster_id,
            "basis": str(basis), "reference_time": reference_time,
            "member_count": len(cameras), "max_skew_s": max_skew_s,
            "note": note, "updated_at_us": t,
        }
        with self.store.engine.begin() as c:
            exists = c.execute(select(S.time_clusters.c.cluster_id).where(
                S.time_clusters.c.cluster_id == cluster_id)).first()
            if exists:
                c.execute(update(S.time_clusters)
                          .where(S.time_clusters.c.cluster_id == cluster_id)
                          .values(**{k: v for k, v in row.items()
                                     if k != "cluster_id"}))
            else:
                c.execute(insert(S.time_clusters).values(created_at_us=t, **row))

        for cam in cameras:
            existing = self.get(cam) or TimebaseHealth(camera_id=cam)
            existing.time_cluster = cluster_id
            existing.cluster_confidence = (
                "MEASURED" if basis is ClusterBasis.MEASURED_OVERLAY else "DECLARED")
            self.record(existing)
        return {**row, "cameras": cameras}

    def clusters(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]]
        with self.store.engine.connect() as c:
            rows = [dict(r._mapping) for r in c.execute(select(S.time_clusters))]
            members: dict[str, list[str]] = {}
            # A distinct name: reusing `r` for both a Row and a dict makes the
            # type of the outer loop variable depend on the inner one.
            for member in c.execute(select(S.camera_timebase.c.camera_id,
                                           S.camera_timebase.c.time_cluster)):
                if member[1]:
                    members.setdefault(member[1], []).append(member[0])
        out: list[dict[str, Any]] = []
        for cluster in rows:
            cams = sorted(members.get(cluster["cluster_id"], []))
            out.append({**cluster, "cameras": cams, "member_count": len(cams)})
        return out

    # -- the decision -------------------------------------------------------- #
    def may_correlate(self, camera_a: str, camera_b: str
                      ) -> tuple[Correlation, str]:
        """Whether two cameras' observations may be placed on one timeline.

        The default without evidence is RESTRICTED, not ALLOWED. On this grid
        that is not caution for its own sake: joining cam01 to cam20 would span
        seven weeks.
        """
        if camera_a == camera_b:
            return Correlation.ALLOWED, "same camera"

        a, b = self.get(camera_a), self.get(camera_b)
        if a is None or b is None:
            return (Correlation.RESTRICTED,
                    "timebase health has not been measured for "
                    f"{camera_a if a is None else camera_b}; correlation is "
                    "restricted until it is")

        for h in (a, b):
            if not h.usable_for_correlation:
                return (Correlation.REFUSED,
                        f"{h.camera_id} has {h.pts_health} timing "
                        f"({h.pts_regressions} PTS regressions) — its "
                        "observations cannot be placed on any timeline")

        if a.time_cluster and a.time_cluster == b.time_cluster:
            return (Correlation.ALLOWED,
                    f"both cameras are in time cluster {a.time_cluster} "
                    f"({a.cluster_confidence.lower()})")

        if a.time_cluster and b.time_cluster:
            return (Correlation.REFUSED,
                    f"{camera_a} is in cluster {a.time_cluster} and "
                    f"{camera_b} is in {b.time_cluster}. These replay different "
                    "windows; joining them would produce a route across scenes "
                    "that never coexisted.")

        return (Correlation.RESTRICTED,
                "no shared timebase has been established for this pair. "
                "Observations are shown, and any route across them carries a "
                "timebase warning rather than a confidence score.")

    def correlatable_set(self, cameras: list[str]) -> dict[str, Any]:
        """Partition a camera set by what may be correlated with what."""
        health = self.all()
        groups: dict[str, list[str]] = {}
        unusable: list[dict[str, str]] = []
        unclustered: list[str] = []
        for cam in cameras:
            h = health.get(cam)
            if h is None:
                unclustered.append(cam)
            elif not h.usable_for_correlation:
                unusable.append({"camera_id": cam, "reason": str(h.pts_health)})
            elif h.time_cluster:
                groups.setdefault(h.time_cluster, []).append(cam)
            else:
                unclustered.append(cam)
        return {
            "clusters": {k: sorted(v) for k, v in groups.items()},
            "unclustered": sorted(unclustered),
            "unusable_timing": unusable,
            "note": ("Cross-camera reasoning is sound within a cluster. Across "
                     "clusters, or for a camera with no established timebase, "
                     "any route carries a timebase warning — the system does "
                     "not invent a shared clock."),
        }


def _from_row(m: Any) -> TimebaseHealth:
    return TimebaseHealth(
        camera_id=m["camera_id"],
        pts_health=PtsHealth(m["pts_health"] or "UNKNOWN"),
        pts_regressions=m["pts_regressions"] or 0,
        pts_forward_jumps=m["pts_forward_jumps"] or 0,
        realtime_ratio=m["realtime_ratio"],
        measured_fps=m["measured_fps"],
        mean_interframe_gap_s=m["mean_interframe_gap_s"],
        max_interframe_gap_s=m["max_interframe_gap_s"],
        overlay_clock=OverlayClock(m["overlay_clock"] or "UNKNOWN"),
        overlay_reading=m["overlay_reading"],
        scene_offset_s=m["scene_offset_s"],
        time_cluster=m["time_cluster"],
        cluster_confidence=m["cluster_confidence"] or "UNKNOWN",
        evidence=json.loads(m["evidence"]) if m["evidence"] else {})


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
