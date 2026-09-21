"""In-process event bus with a Kafka/RabbitMQ-shaped interface.

The PoC uses an in-memory bus so a demo does not require a broker. The
publish/subscribe contract is the same one a later NATS/Kafka adapter would
implement.
"""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from saakshya.common.clock import utc_now
from saakshya.common.ids import new_id
from saakshya.events.schema import CanonicalEvent, EventType


@dataclass
class FederatedEvent:
    """Operator-facing event envelope used by search and the command bus."""

    event_id: str
    camera_id: str
    department: str | None
    timestamp: str
    location: str | None
    entity_id: str | None
    event_type: str
    confidence: float | None
    evidence_ref: str | None
    source_system: str
    extra: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Topic → FIFO of FederatedEvent. Thread-unsafe; API is sync on purpose."""

    def __init__(self, *, max_per_topic: int = 10_000) -> None:
        self.max_per_topic = max_per_topic
        self._topics: dict[str, deque[FederatedEvent]] = defaultdict(deque)
        self._subs: dict[str, list[Callable[[FederatedEvent], None]]] = defaultdict(list)

    def publish(self, topic: str, event: FederatedEvent) -> None:
        q = self._topics[topic]
        q.append(event)
        while len(q) > self.max_per_topic:
            q.popleft()
        for fn in self._subs[topic]:
            fn(event)

    def subscribe(self, topic: str, fn: Callable[[FederatedEvent], None]) -> None:
        self._subs[topic].append(fn)

    def drain(self, topic: str, limit: int = 200) -> list[FederatedEvent]:
        q = self._topics.get(topic)
        if not q:
            return []
        items = list(q)[-limit:]
        return items

    def throughput(self, topic: str) -> int:
        return len(self._topics.get(topic, ()))

    @staticmethod
    def from_canonical(ev: CanonicalEvent, *, source_system: str = "saakshya") -> FederatedEvent:
        loc = None
        if ev.location is not None:
            loc = f"{ev.location.lat:.5f},{ev.location.lon:.5f}"
        return FederatedEvent(
            event_id=ev.event_id,
            camera_id=ev.camera_id,
            department=ev.department_id,
            timestamp=ev.t_norm.isoformat(),
            location=loc,
            entity_id=ev.plate or ev.track_id,
            event_type=str(ev.event_type),
            confidence=ev.detection_confidence or ev.plate_confidence,
            evidence_ref=ev.evidence_ref,
            source_system=source_system,
        )

    @staticmethod
    def observation_event(*, camera_id: str, object_type: str, plate: str | None,
                          t_iso: str, confidence: float | None,
                          department: str | None = None,
                          observation_id: str | None = None,
                          evidence_ref: str | None = None,
                          district: str | None = None) -> FederatedEvent:
        if plate:
            et = EventType.PLATE_READ.value
        elif (object_type or "").lower() == "person":
            et = EventType.PERSON_DETECTED.value
        else:
            et = EventType.VEHICLE_DETECTED.value
        return FederatedEvent(
            event_id=observation_id or new_id("EV"),
            camera_id=camera_id,
            department=department,
            timestamp=t_iso,
            location=district,
            entity_id=plate,
            event_type=et,
            confidence=confidence,
            evidence_ref=evidence_ref,
            source_system="saakshya.store",
            extra={"object_type": object_type, "now": utc_now().isoformat()},
        )
