"""The durable event queue that makes an offline district node safe.

Connectivity to a district headquarters is not reliable, and the failure is
usually not a clean disconnect — it is a link that works, then does not, then
works again, while frames keep arriving the whole time. A design that assumes
the uplink is up loses exactly the events that matter, because outages and
incidents correlate.

The contract this queue implements:

* **Nothing is lost.** Events are written to local durable storage before any
  attempt to send. A power cut between detection and transmission costs at most
  the event currently in flight.
* **Nothing is duplicated on arrival.** Every event carries the same `dedup_key`
  as the observation it describes, and the central store's unique index collapses
  replays onto one row. Delivery is at-least-once; *application* is idempotent.
  Exactly-once delivery over an unreliable link does not exist, and pretending
  otherwise is how systems lose data quietly.
* **Acknowledgement, not deletion.** A sent event stays in the queue until the
  centre confirms it. A lost acknowledgement therefore causes a harmless replay
  rather than a silent loss, which is the correct way round.
* **Order is by source semantics.** Reconciliation orders by `(node, sequence)`
  and never by arrival time. A batch that arrives late is still placed by when
  it was *observed*, and observation time comes from PTS, not from the clock of
  whichever machine happened to handle it.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select, update

from saakshya.common.ids import new_id
from saakshya.store import schema as S
from saakshya.store.repository import Store, from_us, now_us

log = logging.getLogger("saakshya.edge.queue")


class QueueState:
    PENDING = "PENDING"
    ACKED = "ACKED"
    FAILED = "FAILED"


@dataclass
class QueuedEvent:
    node_id: str
    sequence: int
    event_type: str
    dedup_key: str
    payload: dict[str, Any]
    camera_id: str | None = None
    pts_s: float | None = None
    event_id: str = field(default_factory=lambda: new_id("EV"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: str = QueueState.PENDING
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "node_id": self.node_id,
            "sequence": self.sequence, "event_type": self.event_type,
            "camera_id": self.camera_id, "pts_s": self.pts_s,
            "dedup_key": self.dedup_key,
            "created_at": self.created_at.isoformat(),
            "payload": self.payload, "state": self.state,
            "attempts": self.attempts,
        }


class DurableQueue:
    """Local, crash-safe, append-only. One instance per edge node.

    Backed by the same SQLite file the node uses for everything else, so a
    single fsync boundary covers the observation and the queue entry — writing
    them to two stores would create a window where one exists and the other
    does not.
    """

    #: Refuses to grow without limit. When the queue reaches this size the node
    #: has been offline long enough that an operator needs to know; the
    #: behaviour at the limit is defined below and is *not* silent overwrite.
    MAX_PENDING = 250_000

    def __init__(self, store: Store, node_id: str) -> None:
        self.store = store
        self.node_id = node_id
        self._seq = self._last_sequence()

    def _last_sequence(self) -> int:
        with self.store.engine.connect() as c:
            v = c.execute(select(func.max(S.edge_queue.c.sequence)).where(
                S.edge_queue.c.node_id == self.node_id)).scalar()
        return int(v or 0)

    # -- write ------------------------------------------------------------- #
    def enqueue(self, event_type: str, *, dedup_key: str,
                payload: dict[str, Any], camera_id: str | None = None,
                pts_s: float | None = None) -> QueuedEvent:
        if self.depth() >= self.MAX_PENDING:
            # Deliberately an exception, not a silent drop. The caller decides
            # whether to shed load; the queue never decides to forget.
            raise QueueFull(
                f"{self.node_id} has {self.depth():,} unacknowledged events "
                f"(limit {self.MAX_PENDING:,}). The uplink has been down long "
                "enough to need attention; events are NOT being discarded.")
        self._seq += 1
        ev = QueuedEvent(node_id=self.node_id, sequence=self._seq,
                         event_type=event_type, dedup_key=dedup_key,
                         payload=payload, camera_id=camera_id, pts_s=pts_s)
        with self.store.engine.begin() as c:
            c.execute(insert(S.edge_queue).values(
                event_id=ev.event_id, node_id=ev.node_id, sequence=ev.sequence,
                event_type=ev.event_type, camera_id=ev.camera_id, pts_s=ev.pts_s,
                dedup_key=ev.dedup_key,
                payload=json.dumps(ev.payload, default=str),
                created_at_us=now_us(), state=QueueState.PENDING, attempts=0))
        return ev

    def enqueue_observations(self, observations: Iterable[Any]) -> list[QueuedEvent]:
        out = []
        for o in observations:
            out.append(self.enqueue(
                "observation", dedup_key=o.dedup_key, camera_id=o.camera_id,
                pts_s=o.pts_s, payload=o.to_public()))
        return out

    # -- read -------------------------------------------------------------- #
    def pending(self, limit: int = 500) -> list[QueuedEvent]:
        """Oldest first, by sequence. Never by created_at — two events written
        in the same microsecond must still have a total order."""
        with self.store.engine.connect() as c:
            rows = list(c.execute(
                select(S.edge_queue)
                .where(S.edge_queue.c.node_id == self.node_id,
                       S.edge_queue.c.state != QueueState.ACKED)
                .order_by(S.edge_queue.c.sequence).limit(limit)))
        return [_from_row(r._mapping) for r in rows]

    def depth(self) -> int:
        with self.store.engine.connect() as c:
            return int(c.execute(
                select(func.count()).select_from(S.edge_queue)
                .where(S.edge_queue.c.node_id == self.node_id,
                       S.edge_queue.c.state != QueueState.ACKED)).scalar() or 0)

    def stats(self) -> dict[str, Any]:
        with self.store.engine.connect() as c:
            rows = list(c.execute(
                select(S.edge_queue.c.state, func.count())
                .where(S.edge_queue.c.node_id == self.node_id)
                .group_by(S.edge_queue.c.state)))
            oldest = c.execute(
                select(func.min(S.edge_queue.c.created_at_us))
                .where(S.edge_queue.c.node_id == self.node_id,
                       S.edge_queue.c.state != QueueState.ACKED)).scalar()
        by_state = {r[0]: int(r[1]) for r in rows}
        lag = None
        if oldest:
            lag = round((now_us() - int(oldest)) / 1e6, 1)
        return {"node_id": self.node_id, "by_state": by_state,
                "pending": self.depth(), "next_sequence": self._seq + 1,
                "oldest_pending_age_s": lag}

    # -- acknowledge -------------------------------------------------------- #
    def acknowledge(self, event_ids: Sequence[str]) -> int:
        if not event_ids:
            return 0
        with self.store.engine.begin() as c:
            r = c.execute(update(S.edge_queue)
                          .where(S.edge_queue.c.node_id == self.node_id,
                                 S.edge_queue.c.event_id.in_(list(event_ids)))
                          .values(state=QueueState.ACKED, acked_at_us=now_us()))
        return int(r.rowcount or 0)

    def mark_failed(self, event_ids: Sequence[str], error: str) -> None:
        if not event_ids:
            return
        with self.store.engine.begin() as c:
            for eid in event_ids:
                c.execute(update(S.edge_queue)
                          .where(S.edge_queue.c.event_id == eid)
                          .values(state=QueueState.PENDING,
                                  attempts=S.edge_queue.c.attempts + 1,
                                  last_error=error[:500]))

    def purge_acked(self, older_than_s: float = 86_400.0) -> int:
        """Housekeeping only, and only for events the centre has confirmed.

        Nothing unacknowledged is ever removed by this method, whatever its age.
        """
        from sqlalchemy import delete
        cutoff = now_us() - int(older_than_s * 1e6)
        with self.store.engine.begin() as c:
            r = c.execute(delete(S.edge_queue).where(
                S.edge_queue.c.node_id == self.node_id,
                S.edge_queue.c.state == QueueState.ACKED,
                S.edge_queue.c.acked_at_us < cutoff))
        return int(r.rowcount or 0)


class QueueFull(RuntimeError):
    """Raised rather than dropping. Backpressure is the caller's decision."""


def _from_row(m: Any) -> QueuedEvent:
    return QueuedEvent(
        event_id=m["event_id"], node_id=m["node_id"], sequence=m["sequence"],
        event_type=m["event_type"], camera_id=m["camera_id"], pts_s=m["pts_s"],
        dedup_key=m["dedup_key"], payload=json.loads(m["payload"]),
        created_at=from_us(m["created_at_us"]) or datetime.now(UTC),
        state=m["state"], attempts=m["attempts"] or 0)


# --------------------------------------------------------------------------- #
# Central-side reconciliation
# --------------------------------------------------------------------------- #
@dataclass
class ReplayResult:
    received: int = 0
    applied: int = 0
    duplicates: int = 0
    rejected: int = 0
    acknowledged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"received": self.received, "applied": self.applied,
                "duplicates": self.duplicates, "rejected": self.rejected,
                "acknowledged": self.acknowledged, "errors": self.errors}


class CentralReceiver:
    """Applies a replayed batch centrally. Idempotent by construction.

    The duplicate count is reported rather than hidden: on a healthy reconnect
    it should be small, and a large one means acknowledgements are not getting
    back to the node — a real fault that a silently-idempotent receiver would
    conceal indefinitely.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def receive(self, node_id: str, events: list[dict[str, Any]]) -> ReplayResult:
        from saakshya.store import VehicleObservation

        res = ReplayResult(received=len(events))
        # Source-semantic ordering. Arrival order is not trusted.
        events = sorted(events, key=lambda e: (e.get("sequence") or 0))
        to_apply: list[VehicleObservation] = []
        for e in events:
            if e.get("event_type") != "observation":
                res.rejected += 1
                res.errors.append(f"unsupported event_type {e.get('event_type')!r}")
                continue
            try:
                to_apply.append(_observation_from_payload(e["payload"],
                                                          e["dedup_key"]))
                res.acknowledged.append(e["event_id"])
            except (KeyError, ValueError, TypeError) as exc:
                res.rejected += 1
                res.errors.append(f"{e.get('event_id')}: {exc}")

        if to_apply:
            written = self.store.add_observations(to_apply)
            res.applied = written
            res.duplicates = len(to_apply) - written

        with self.store.engine.begin() as c:
            row = c.execute(select(S.edge_nodes.c.node_id).where(
                S.edge_nodes.c.node_id == node_id)).first()
            last_seq = max((e.get("sequence") or 0) for e in events) if events else 0
            vals = {"last_sync_us": now_us(), "last_ack_sequence": last_seq,
                    "state": "SYNCED", "updated_at_us": now_us()}
            if row:
                c.execute(update(S.edge_nodes)
                          .where(S.edge_nodes.c.node_id == node_id).values(**vals))
            else:
                c.execute(insert(S.edge_nodes).values(node_id=node_id, **vals))

        self.store.audit("edge:" + node_id, "edge_replay",
                         target=node_id, result_count=res.applied)
        log.info("edge replay applied", extra={"extra_fields": res.to_dict()})
        return res


def _observation_from_payload(p: dict[str, Any], dedup_key: str) -> Any:
    from saakshya.store import VehicleObservation

    def dt(v: Any) -> datetime:
        return datetime.fromisoformat(v) if isinstance(v, str) else v

    return VehicleObservation(
        camera_id=p["camera_id"], pts_s=float(p["pts_s"]),
        t_norm=dt(p["t_norm"]), t_ingest=dt(p["t_ingest"]),
        dedup_key=dedup_key, observation_id=p.get("observation_id") or new_id("OB"),
        department=p.get("department"), district=p.get("district"),
        track_id=p.get("track_id"), segment_id=p.get("segment_id"),
        lat=p.get("lat"), lon=p.get("lon"),
        object_type=p.get("object_type") or "unknown",
        bbox=tuple(p["bbox"]) if p.get("bbox") else None,
        detection_confidence=p.get("detection_confidence"),
        plate=p.get("plate"), plate_raw=p.get("plate_raw"),
        plate_confidence=p.get("plate_confidence"),
        plate_votes=p.get("plate_votes") or 0,
        colour=p.get("colour"), colour_confidence=p.get("colour_confidence"),
        make=p.get("make"), model_name=p.get("model_name"),
        direction_deg=p.get("direction_deg"),
        observation_quality=p.get("observation_quality"),
        plate_pixel_width=p.get("plate_pixel_width"),
        sharpness=p.get("sharpness"), luminance=p.get("luminance"),
        source_quality=p.get("source_quality"), source_grade=p.get("source_grade"),
        model_versions=p.get("model_versions") or {},
        evidence_ref=p.get("evidence_ref"))
