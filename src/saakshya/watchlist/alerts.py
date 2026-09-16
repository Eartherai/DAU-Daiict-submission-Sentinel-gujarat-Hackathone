"""Alert engine: EVENT → MATCH → CONTEXT → POLICY → ALERT.

The design goal is not to maximise alerts. It is to make every alert worth an
officer's attention, because an operator who learns to dismiss alerts has been
given a system that is worse than none.

Three mechanisms do that work:

**Context before policy.** A plate match is an input, not a verdict. Priority is
raised or lowered by observation quality, route consistency and repeat sightings
before anything is emitted.

**Deduplication.** One vehicle crossing four cameras is one investigation-worthy
event, not four alerts. Subsequent sightings *update* the open alert and can
escalate it; they do not repeat it.

**Explanation.** Every alert answers what matched, why, where, when, how
strongly, and on what evidence — because an alert an officer cannot interrogate
is an alert they cannot act on.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import insert, select, update

from saakshya.common.ids import new_id
from saakshya.store import Store, VehicleObservation, now_us, to_us
from saakshya.store import schema as S
from saakshya.watchlist.service import CATEGORY_WEIGHT, Priority, WatchlistMatch

log = logging.getLogger(__name__)


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    CLEARED = "CLEARED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


#: Operator labels (New / Acknowledged / Investigating / Resolved) map onto
#: stored statuses. The stored values remain the audit vocabulary.
OPERATOR_STATUS = {
    "NEW": AlertStatus.OPEN,
    "OPEN": AlertStatus.OPEN,
    "ACK": AlertStatus.ACKNOWLEDGED,
    "ACKNOWLEDGED": AlertStatus.ACKNOWLEDGED,
    "INVESTIGATING": AlertStatus.INVESTIGATING,
    "RESOLVED": AlertStatus.CLEARED,
    "CLEARED": AlertStatus.CLEARED,
    "FALSE_POSITIVE": AlertStatus.FALSE_POSITIVE,
}


def parse_alert_status(raw: str | None) -> AlertStatus | None:
    if not raw:
        return None
    key = raw.strip().upper().replace(" ", "_")
    if key not in OPERATOR_STATUS:
        raise ValueError(f"unknown alert status {raw!r}")
    return OPERATOR_STATUS[key]


@dataclass
class AlertPolicy:
    """Tunable, and every value is a policy decision rather than a constant."""

    #: Below this confidence nothing is emitted. A weak read on a degraded camera
    #: is a lead for a human search, not a push notification.
    min_confidence: float = 0.55
    #: Within this window, a further sighting updates the existing alert.
    cooldown_s: float = 900.0
    #: Sightings on distinct cameras that escalate priority one step.
    escalate_after_cameras: int = 3
    #: Quality below which an alert is emitted but explicitly marked low-trust.
    low_quality_floor: float = 0.45


@dataclass
class Alert:
    alert_id: str
    watchlist_id: str
    plate: str
    category: str
    priority: str
    confidence: float
    camera_id: str
    t_norm: datetime
    observation_ids: list[str] = field(default_factory=list)
    cameras: list[str] = field(default_factory=list)
    status: AlertStatus = AlertStatus.OPEN
    terms: dict = field(default_factory=dict)
    reason: str = ""
    authority: str = ""
    recommended_action: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def explain(self) -> dict:
        """Answers what / why / where / when / how strong / what evidence."""
        return {
            "alert_id": self.alert_id,
            "what_matched": f"registration mark {self.plate}",
            "why": self.reason,
            "authority": self.authority,
            "where": {"first_camera": self.camera_id, "all_cameras": self.cameras},
            "when": self.t_norm.isoformat(),
            "how_strong": {
                "confidence": round(self.confidence, 3),
                "terms": {k: round(v, 3) for k, v in self.terms.items()
                          if isinstance(v, (int, float))},
                "sightings": len(self.observation_ids),
            },
            "evidence": self.evidence_ids or ["not yet generated"],
            "priority": self.priority,
            "status": str(self.status),
            "operator_action": self.recommended_action,
            "notes": self.notes,
        }


class AlertEngine:
    def __init__(self, store: Store, policy: AlertPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or AlertPolicy()
        self.suppressed_low_confidence = 0
        self.deduplicated = 0

    # -- policy -------------------------------------------------------------- #
    @staticmethod
    def _alert_key(plate: str, watchlist_id: str) -> str:
        """One open alert per (vehicle, watchlist entry)."""
        return f"{plate}:{watchlist_id}"

    def _open_alert(self, key: str, when: datetime) -> dict | None:
        plate, wl = key.split(":", 1)
        cutoff = to_us(when - timedelta(seconds=self.policy.cooldown_s))
        with self.store.engine.connect() as c:
            r = c.execute(
                select(S.alerts)
                .where(S.alerts.c.plate == plate)
                .where(S.alerts.c.watchlist_id == wl)
                .where(S.alerts.c.status == str(AlertStatus.OPEN))
                .where(S.alerts.c.t_norm_us >= cutoff)
                .order_by(S.alerts.c.t_norm_us.desc()).limit(1)).first()
        return dict(r._mapping) if r else None

    @staticmethod
    def _escalate(priority: str) -> str:
        order = [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.CRITICAL]
        try:
            i = order.index(Priority(priority))
        except ValueError:
            return priority
        return str(order[min(i + 1, len(order) - 1)])

    # -- main entry point ---------------------------------------------------- #
    def process(self, match: WatchlistMatch, *,
                route_consistency: float | None = None) -> Alert | None:
        """Turn a watchlist match into an alert, or explain why it did not."""
        obs, entry = match.observation, match.entry
        quality = obs.observation_quality or 0.0
        cat_w = CATEGORY_WEIGHT.get(entry.category, 0.5)

        terms = {
            "plate_confidence": obs.plate_confidence or 0.0,
            "observation_quality": quality,
            "category_weight": cat_w,
        }
        confidence = match.confidence
        if route_consistency is not None:
            terms["route_consistency"] = route_consistency
            # Route agreement corroborates; it never manufactures confidence on
            # its own, so it can only move the result modestly.
            confidence = 0.85 * confidence + 0.15 * route_consistency

        if confidence < self.policy.min_confidence:
            self.suppressed_low_confidence += 1
            log.info("alert suppressed for %s: confidence %.2f below %.2f",
                     obs.plate, confidence, self.policy.min_confidence)
            return None

        if not obs.plate:
            # Watchlist matching is plate-only by design (attribute-only
            # matching would mean "a white car" raising a police alert), so this
            # should be unreachable. Refusing explicitly beats keying an alert
            # on None and deduplicating every plateless observation together.
            log.warning("alert refused: observation %s carries no registration "
                        "mark", obs.observation_id)
            return None
        key = self._alert_key(obs.plate, entry.watchlist_id)
        existing = self._open_alert(key, obs.t_norm)

        if existing:
            return self._update(existing, obs, confidence, terms)

        notes = []
        if quality < self.policy.low_quality_floor:
            notes.append(f"source quality {quality:.2f} is low — verify against "
                         f"the clip before acting")
        # A single-frame plate is still a watchlist hit — a stolen vehicle
        # seen once should not vanish — but it must not look as settled as a
        # voted confirmation. The alert fires; the officer is told to verify.
        if (obs.plate_votes or 0) < 2:
            notes.append("registration mark read on a single frame — an exact "
                         "match but not corroborated across frames; verify "
                         "before acting")
            terms["corroborated"] = False
            terms["plate_votes"] = obs.plate_votes or 0

        alert = Alert(
            alert_id=new_id("AL"), watchlist_id=entry.watchlist_id,
            plate=obs.plate, category=str(entry.category),
            priority=str(entry.priority), confidence=float(confidence),
            camera_id=obs.camera_id, t_norm=obs.t_norm,
            observation_ids=[obs.observation_id], cameras=[obs.camera_id],
            terms=terms, reason=entry.reason, authority=entry.authority,
            recommended_action=self._action(entry.priority, quality),
            notes=notes,
        )
        self._persist(alert, insert_new=True)
        return alert

    def _update(self, row: dict, obs: VehicleObservation,
                confidence: float, terms: dict) -> Alert:
        """Fold a repeat sighting into the open alert instead of raising another."""
        self.deduplicated += 1
        reason_blob = json.loads(row["match_reason"]) if row["match_reason"] else {}
        obs_ids = reason_blob.get("observation_ids", [])
        cams = reason_blob.get("cameras", [])
        if obs.observation_id not in obs_ids:
            obs_ids.append(obs.observation_id)
        if obs.camera_id not in cams:
            cams.append(obs.camera_id)

        priority = row["priority"]
        notes = reason_blob.get("notes", [])
        if len(cams) >= self.policy.escalate_after_cameras:
            new_priority = self._escalate(priority)
            if new_priority != priority:
                notes.append(f"escalated to {new_priority}: seen on {len(cams)} "
                             f"distinct cameras")
                priority = new_priority

        blob = {**reason_blob, "observation_ids": obs_ids, "cameras": cams,
                "terms": terms, "notes": notes}
        with self.store.engine.begin() as c:
            c.execute(update(S.alerts)
                      .where(S.alerts.c.alert_id == row["alert_id"])
                      .values(confidence=max(row["confidence"] or 0.0, confidence),
                              priority=priority,
                              match_reason=json.dumps(blob),
                              t_norm_us=to_us(obs.t_norm)))
        return Alert(
            alert_id=row["alert_id"], watchlist_id=row["watchlist_id"],
            plate=row["plate"], category=row["category"], priority=priority,
            confidence=max(row["confidence"] or 0.0, confidence),
            camera_id=row["camera_id"], t_norm=obs.t_norm,
            observation_ids=obs_ids, cameras=cams,
            status=AlertStatus.OPEN, terms=terms,
            reason=reason_blob.get("reason", ""),
            authority=reason_blob.get("authority", ""),
            recommended_action=row["recommended_action"] or "", notes=notes,
        )

    @staticmethod
    def _action(priority: Priority, quality: float) -> str:
        if quality < 0.45:
            return "VERIFY against the source clip before dispatching"
        if priority in (Priority.CRITICAL, Priority.HIGH):
            return "VERIFY and notify the district control room"
        return "ACKNOWLEDGE and add to the case file"

    def _persist(self, a: Alert, *, insert_new: bool) -> None:
        blob = {"terms": a.terms, "reason": a.reason, "authority": a.authority,
                "observation_ids": a.observation_ids, "cameras": a.cameras,
                "notes": a.notes}
        with self.store.engine.begin() as c:
            c.execute(insert(S.alerts).values(
                alert_id=a.alert_id, watchlist_id=a.watchlist_id,
                observation_id=a.observation_ids[0] if a.observation_ids else None,
                camera_id=a.camera_id, plate=a.plate, category=a.category,
                priority=a.priority, confidence=a.confidence,
                source_quality=a.terms.get("observation_quality"),
                match_reason=json.dumps(blob),
                recommended_action=a.recommended_action,
                status=str(a.status), t_norm_us=to_us(a.t_norm),
                created_at_us=now_us()))

    # -- operator actions ---------------------------------------------------- #
    def acknowledge(self, alert_id: str, *, actor: str) -> None:
        with self.store.engine.begin() as c:
            c.execute(update(S.alerts).where(S.alerts.c.alert_id == alert_id)
                      .values(status=str(AlertStatus.ACKNOWLEDGED),
                              acknowledged_by=actor, acknowledged_at_us=now_us()))
        self.store.audit(actor, "alert_acknowledge", target=alert_id)

    def investigate(self, alert_id: str, *, actor: str) -> None:
        with self.store.engine.begin() as c:
            c.execute(update(S.alerts).where(S.alerts.c.alert_id == alert_id)
                      .values(status=str(AlertStatus.INVESTIGATING),
                              acknowledged_by=actor, acknowledged_at_us=now_us()))
        self.store.audit(actor, "alert_investigate", target=alert_id)

    def clear(self, alert_id: str, *, actor: str, reason: str,
              false_positive: bool = False) -> None:
        """Close an alert. A cleared vehicle must not immediately re-alert on the
        same evidence — that is how operators learn to ignore the system."""
        status = AlertStatus.FALSE_POSITIVE if false_positive else AlertStatus.CLEARED
        with self.store.engine.begin() as c:
            c.execute(update(S.alerts).where(S.alerts.c.alert_id == alert_id)
                      .values(status=str(status), cleared_reason=reason,
                              acknowledged_by=actor, acknowledged_at_us=now_us()))
        self.store.audit(actor, "alert_clear", target=alert_id, purpose=reason)

    def list_alerts(self, status: AlertStatus | None = None) -> list[dict]:
        q = select(S.alerts).order_by(S.alerts.c.t_norm_us.desc())
        if status:
            q = q.where(S.alerts.c.status == str(status))
        with self.store.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)]

    def stats(self) -> dict:
        return {
            "suppressed_low_confidence": self.suppressed_low_confidence,
            "deduplicated_sightings": self.deduplicated,
            "open": len(self.list_alerts(AlertStatus.OPEN)),
        }
