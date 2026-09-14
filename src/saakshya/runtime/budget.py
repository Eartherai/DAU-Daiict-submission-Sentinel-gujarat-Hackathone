"""Analytics budget — hardware-aware sampling and tier selection.

Two constraints meet here. The estate is heterogeneous, so cameras deserve
different amounts of compute; and the host is heterogeneous, so the same
deployment may have a GPU or may not. The budget resolves both into three
concrete decisions per camera: **sampling rate, model tier, and whether
expensive inference is permitted at all**.

The system stays fully functional with no GPU. It does less per second, and it
says so, but nothing in the mandatory chain depends on a GPU being present.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from saakshya.registry.models import Analytic, Grade
from saakshya.runtime.profile import Profile, RuntimeContext, context


class Tier(IntEnum):
    """Analytics tiers. Higher costs more and requires more from the camera."""

    T0_PRESENCE = 0     # motion / presence only
    T1_VEHICLE = 1      # vehicle detection + tracking + attributes
    T2_IDENTITY = 2     # + plate detection, OCR, appearance embedding
    T3_FORENSIC = 3     # + full-rate re-decode, multi-frame OCR, VLM


class Priority(IntEnum):
    ROUTINE = 0
    ELEVATED = 1        # investigator has this camera in an active search
    URGENT = 2          # watchlist hit, or an operator asked for deeper analysis


@dataclass(frozen=True)
class BudgetDecision:
    camera_id: str
    tier: Tier
    sampling_fps: float
    expensive_inference: bool
    reason: str
    #: Analytics the camera is permitted to run, after capability *and* budget.
    permitted: tuple[Analytic, ...] = ()

    def describe(self) -> str:
        return (f"{self.camera_id}: {self.tier.name} @ {self.sampling_fps:g} fps "
                f"({'expensive on' if self.expensive_inference else 'expensive off'}) "
                f"— {self.reason}")


@dataclass
class AnalyticsBudget:
    """Allocates finite compute across cameras.

    Deliberately simple and deterministic. A scheduler that is hard to predict
    is a scheduler nobody can debug at 2 a.m. during an evaluation.
    """

    #: Optional at construction so callers need not detect hardware themselves;
    #: `__post_init__` always resolves it, and `runtime` below is the accessor
    #: everything else uses so no method has to handle a None context.
    ctx: RuntimeContext | None = None
    camera_count: int = 1
    #: Backpressure signal from the event fabric, 0.0 (idle) .. 1.0 (saturated).
    queue_pressure: float = 0.0

    def __post_init__(self) -> None:
        self.ctx = self.ctx or context()

    @property
    def runtime(self) -> RuntimeContext:
        """The resolved context. `__post_init__` guarantees it, and this states
        the guarantee once rather than at every use site."""
        if self.ctx is None:                       # pragma: no cover - defensive
            self.ctx = context()
        return self.ctx

    # -- capacity ---------------------------------------------------------- #
    @property
    def concurrent_inference_slots(self) -> int:
        """How many cameras can run T2 simultaneously on this host."""
        hw = self.runtime.hardware
        if self.runtime.profile is Profile.DEV_CPU:
            # Measured: ~69 ms/frame for detect+OCR on this CPU. Leave two cores
            # for decode and the API, and do not oversubscribe.
            return max(1, (hw.cpu_count - 2) // 2)
        # GPU profiles: bounded by VRAM, roughly 1.5 GB per concurrent T2 model
        # set. Modelled, not measured — no GPU has been available to verify it.
        if hw.gpu_memory_mb:
            return max(1, int(hw.gpu_memory_mb / 1500))
        return max(2, hw.cpu_count // 2)

    @property
    def saturated(self) -> bool:
        return self.queue_pressure >= 0.8

    # -- per-camera decision ------------------------------------------------ #
    def decide(
        self,
        camera_id: str,
        anpr_grade: Grade,
        reid_grade: Grade,
        usable_for: tuple[Analytic, ...] | list[Analytic],
        priority: Priority = Priority.ROUTINE,
        sufficient_evidence: bool = True,
    ) -> BudgetDecision:
        usable = tuple(usable_for)

        # 1. A camera we have not measured cannot be assigned an expensive tier.
        #    Bootstrapping runs cheap analytics until evidence accumulates,
        #    rather than guessing a grade from a handful of frames.
        if not sufficient_evidence:
            return BudgetDecision(
                camera_id, Tier.T1_VEHICLE, 1.0, False,
                "insufficient capability evidence — running cheap analytics to "
                "accumulate measurements before committing compute",
                (Analytic.PRESENCE, Analytic.VEHICLE_DETECT),
            )

        # 2. Capability sets the ceiling. No budget raises a camera above what
        #    it can physically deliver — that is how you get confident garbage.
        if Analytic.ANPR in usable and anpr_grade in (Grade.A, Grade.B):
            ceiling, base_fps = Tier.T2_IDENTITY, 6.0 if anpr_grade is Grade.A else 3.0
        elif Analytic.VEHICLE_REID in usable and reid_grade in (Grade.A, Grade.B, Grade.C):
            ceiling, base_fps = Tier.T2_IDENTITY, 2.0
        elif Analytic.VEHICLE_DETECT in usable:
            ceiling, base_fps = Tier.T1_VEHICLE, 1.0
        else:
            ceiling, base_fps = Tier.T0_PRESENCE, 0.5

        reason_bits = [f"capability ceiling {ceiling.name}"]

        # 3. Priority may raise the tier, but only within capability. An urgent
        #    request on a camera that cannot read plates still cannot read them.
        tier = ceiling
        if priority is Priority.URGENT and ceiling >= Tier.T2_IDENTITY:
            tier = Tier.T3_FORENSIC
            base_fps = max(base_fps, 8.0)
            reason_bits.append("urgent priority -> forensic tier")
        elif priority is Priority.ELEVATED and ceiling >= Tier.T1_VEHICLE:
            base_fps *= 1.5
            reason_bits.append("elevated priority -> sampling raised")

        # 4. Host capacity and backpressure reduce it again.
        fps = base_fps
        expensive = tier >= Tier.T2_IDENTITY

        if self.runtime.profile is Profile.DEV_CPU:
            slots = self.concurrent_inference_slots
            if self.camera_count > slots and tier >= Tier.T2_IDENTITY:
                fps = min(fps, max(0.5, slots * 2.0 / self.camera_count))
                reason_bits.append(
                    f"CPU profile: {self.camera_count} cameras over {slots} slots, "
                    f"sampling reduced")
            if tier is Tier.T3_FORENSIC:
                # T3 stays available on CPU but is slow; it runs on demand only.
                reason_bits.append("T3 on CPU is on-demand only, not continuous")

        if self.saturated:
            # Shed cheapest-value work first: T0/T1 sampling before T2 identity.
            if tier <= Tier.T1_VEHICLE:
                fps = min(fps, 0.5)
                reason_bits.append("queue saturated -> presence sampling floor")
            else:
                fps = max(1.0, fps * 0.5)
                reason_bits.append("queue saturated -> identity sampling halved")
        elif self.queue_pressure > 0.5:
            fps *= 0.75
            reason_bits.append("queue pressure -> sampling trimmed")

        permitted: list[Analytic] = [Analytic.PRESENCE]
        if tier >= Tier.T1_VEHICLE:
            permitted.append(Analytic.VEHICLE_DETECT)
        if tier >= Tier.T2_IDENTITY:
            if Analytic.VEHICLE_REID in usable:
                permitted.append(Analytic.VEHICLE_REID)
            if Analytic.ANPR in usable:
                permitted.append(Analytic.ANPR)

        return BudgetDecision(
            camera_id=camera_id, tier=tier, sampling_fps=round(fps, 2),
            expensive_inference=expensive, reason="; ".join(reason_bits),
            permitted=tuple(permitted),
        )

    def plan(self, cameras: list[dict]) -> list[BudgetDecision]:
        """Decide for a whole estate. ``cameras`` carry grades and usable_for."""
        self.camera_count = len(cameras) or 1
        return [
            self.decide(
                camera_id=c["camera_id"],
                anpr_grade=c.get("anpr_grade", Grade.UNKNOWN),
                reid_grade=c.get("reid_grade", Grade.UNKNOWN),
                usable_for=c.get("usable_for", ()),
                priority=c.get("priority", Priority.ROUTINE),
                sufficient_evidence=c.get("sufficient_evidence", True),
            )
            for c in cameras
        ]

    def summary(self, decisions: list[BudgetDecision]) -> dict:
        by_tier: dict[str, int] = {}
        for d in decisions:
            by_tier[d.tier.name] = by_tier.get(d.tier.name, 0) + 1
        return {
            "profile": str(self.runtime.profile),
            "cameras": len(decisions),
            "concurrent_inference_slots": self.concurrent_inference_slots,
            "queue_pressure": self.queue_pressure,
            "by_tier": by_tier,
            "total_sampled_fps": round(sum(d.sampling_fps for d in decisions), 2),
            "expensive_enabled": sum(1 for d in decisions if d.expensive_inference),
        }
