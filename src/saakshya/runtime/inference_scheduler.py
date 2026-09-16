"""Adaptive, bounded scheduling for per-frame analytics.

The scheduler is deliberately independent of model implementations.  It
returns a small immutable plan that callers can use to gate sampling, detector
inference, OCR and re-identification without changing their existing APIs.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum


class InferenceMode(StrEnum):
    NORMAL = "NORMAL"
    HIGH_PRIORITY = "HIGH_PRIORITY"
    ALERT = "ALERT"
    FORENSIC = "FORENSIC"


@dataclass(frozen=True)
class SchedulerPolicy:
    """Cadences are expressed as source frames, not wall-clock guesses."""

    sample_every: int
    infer_every: int
    ocr_every: int
    reid_every: int


POLICIES: dict[InferenceMode, SchedulerPolicy] = {
    InferenceMode.NORMAL: SchedulerPolicy(4, 4, 8, 12),
    InferenceMode.HIGH_PRIORITY: SchedulerPolicy(2, 2, 4, 6),
    InferenceMode.ALERT: SchedulerPolicy(1, 1, 2, 3),
    InferenceMode.FORENSIC: SchedulerPolicy(1, 1, 1, 1),
}


@dataclass(frozen=True)
class InferencePlan:
    frame_index: int
    mode: InferenceMode
    sample: bool
    infer: bool
    ocr: bool
    reid: bool
    queue_depth: int


class AdaptiveInferenceScheduler:
    """Deterministic cadence control with bounded, priority-aware admission."""

    def __init__(
        self,
        mode: InferenceMode = InferenceMode.NORMAL,
        *,
        max_queue_depth: int = 128,
        policy: dict[InferenceMode, SchedulerPolicy] | None = None,
    ) -> None:
        if max_queue_depth < 1:
            raise ValueError("max_queue_depth must be positive")
        self.mode = InferenceMode(mode)
        self.max_queue_depth = max_queue_depth
        self.policies = dict(POLICIES)
        if policy:
            self.policies.update(policy)
        self._queue: deque[InferenceMode] = deque()

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    def set_mode(self, mode: InferenceMode) -> None:
        self.mode = InferenceMode(mode)

    def plan(self, frame_index: int) -> InferencePlan:
        if frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        p = self.policies[self.mode]
        return InferencePlan(
            frame_index=frame_index,
            mode=self.mode,
            sample=frame_index % p.sample_every == 0,
            infer=frame_index % p.infer_every == 0,
            ocr=frame_index % p.ocr_every == 0,
            reid=frame_index % p.reid_every == 0,
            queue_depth=self.queue_depth,
        )

    def admit(self, mode: InferenceMode | None = None) -> bool:
        """Reserve one queue slot.

        Normal work is shed when saturated.  Higher-priority work evicts the
        oldest lower-priority item, but never evicts forensic or alert work.
        This makes backpressure explicit without silently discarding evidence.
        """
        incoming = InferenceMode(mode or self.mode)
        if len(self._queue) < self.max_queue_depth:
            self._queue.append(incoming)
            return True
        if incoming in (InferenceMode.ALERT, InferenceMode.FORENSIC):
            for i, queued in enumerate(self._queue):
                if queued in (InferenceMode.NORMAL, InferenceMode.HIGH_PRIORITY):
                    del self._queue[i]
                    self._queue.append(incoming)
                    return True
        return False

    def complete(self) -> InferenceMode | None:
        """Release the oldest reserved slot."""
        return self._queue.popleft() if self._queue else None

