"""Model router — chooses which model runs, and says why.

The router is the single place where "what should we run here?" is decided. It
takes camera capability, task, hardware, latency budget and event priority, and
returns a selection with an explicit fallback and a human-readable reason.

Two rules it will not break:

* **A model is never selected above what the camera can support.** An urgent
  request on a camera that cannot read plates still does not get an OCR budget;
  raising effort on unusable input produces confident garbage, which is worse
  than no answer.
* **A model is never swapped silently.** Every selection carries the record's
  name, version and revision into event provenance, so a result can always be
  traced to what produced it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from saakshya.models.registry import (
    LicenceClass,
    ModelRecord,
    Status,
    Task,
    by_task,
)
from saakshya.registry.models import Analytic, Grade
from saakshya.runtime.budget import Priority, Tier
from saakshya.runtime.profile import Profile, RuntimeContext, context

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    task: Task
    model: ModelRecord | None
    fallback: ModelRecord | None
    tier: Tier
    reason: str
    #: True when the router deliberately declined to run anything.
    declined: bool = False

    def describe(self) -> str:
        if self.declined or self.model is None:
            return f"{self.task}: DECLINED — {self.reason}"
        fb = f" (fallback {self.fallback.key})" if self.fallback else ""
        return f"{self.task}: {self.model.key}{fb} @ {self.tier.name} — {self.reason}"

    def provenance(self) -> dict:
        return self.model.provenance() if self.model else {"model": None}


class ModelRouter:
    """Selects models for a camera and task under the current runtime."""

    def __init__(self, ctx: RuntimeContext | None = None,
                 allow_unapproved: bool = False) -> None:
        self.ctx = ctx or context()
        #: Benchmarking needs to load candidates; the running system does not.
        self.allow_unapproved = allow_unapproved

    # -- candidate filtering ------------------------------------------------ #
    def _candidates(self, task: Task) -> list[ModelRecord]:
        out = []
        for m in by_task(task):
            if m.status is Status.REJECTED:
                continue
            if m.licence_class is not LicenceClass.PERMISSIVE:
                continue                      # never load copyleft/unclear weights
            if not self.allow_unapproved and not m.approved_for_demo:
                continue
            if m.requires_gpu and not self.ctx.is_gpu:
                continue
            if m.min_vram_mb and self.ctx.hardware.gpu_memory_mb < m.min_vram_mb:
                continue
            if not self.ctx.allow_heavy_models and (m.size_mb or 0) > 500:
                continue                      # keep DEV_CPU responsive
            out.append(m)
        return out

    def _within_budget(self, m: ModelRecord, budget_ms: float | None) -> bool:
        if budget_ms is None:
            return True
        cost = m.measured_latency_ms or m.latency_budget_ms
        return cost is None or cost <= budget_ms

    # -- the decision ------------------------------------------------------- #
    def select(
        self,
        task: Task,
        *,
        tier: Tier = Tier.T2_IDENTITY,
        anpr_grade: Grade = Grade.UNKNOWN,
        usable_for: tuple[Analytic, ...] = (),
        priority: Priority = Priority.ROUTINE,
        latency_budget_ms: float | None = None,
        sufficient_evidence: bool = True,
    ) -> Selection:
        # --- capability gates, before any model is considered --------------- #
        if task is Task.PLATE_DETECT_OCR or task is Task.OCR:
            if tier < Tier.T2_IDENTITY:
                return Selection(task, None, None, tier, declined=True,
                                 reason=f"tier {tier.name} does not include identity analytics")
            if not sufficient_evidence:
                return Selection(task, None, None, tier, declined=True,
                                 reason="camera capability not yet measured; "
                                        "declining ANPR until evidence exists")
            if Analytic.ANPR not in usable_for:
                return Selection(
                    task, None, None, tier, declined=True,
                    reason=(f"camera is not ANPR-capable (grade {anpr_grade}); "
                            "running ANPR here would produce unreliable reads"))

        if task is Task.EMBED and tier < Tier.T2_IDENTITY:
            return Selection(task, None, None, tier, declined=True,
                             reason=f"tier {tier.name} does not include appearance embedding")

        if task is Task.VLM:
            if tier < Tier.T3_FORENSIC:
                return Selection(task, None, None, tier, declined=True,
                                 reason="VLM description is tier-3 only")
            if not self.ctx.is_gpu:
                return Selection(task, None, None, tier, declined=True,
                                 reason="no GPU: forensic VLM unavailable on this host. "
                                        "Core analytics are unaffected.")

        # --- pick from what is left ----------------------------------------- #
        cands = self._candidates(task)
        if not cands:
            return Selection(task, None, None, tier, declined=True,
                             reason=f"no approved, licence-clean model for {task} "
                                    f"on profile {self.ctx.profile}")

        affordable = [m for m in cands if self._within_budget(m, latency_budget_ms)]
        pool = affordable or cands
        note = "" if affordable else (
            f"; no model fits the {latency_budget_ms:.0f} ms budget — "
            "selected the cheapest available and flagged it")

        # Prefer the strongest model the profile allows. On CPU that means the
        # fastest; on GPU it means the most capable within budget.
        if self.ctx.profile is Profile.DEV_CPU:
            pool = sorted(pool, key=lambda m: (m.measured_latency_ms
                                               or m.latency_budget_ms or 1e9))
        else:
            pool = sorted(pool, key=lambda m: -(m.size_mb or 0))

        chosen = pool[0]
        fallback = next((m for m in pool[1:] if not m.requires_gpu), None)

        reason = (f"profile {self.ctx.profile}, tier {tier.name}, "
                  f"{len(cands)} candidate(s), licence {chosen.licence}{note}")
        if priority is Priority.URGENT:
            reason += "; urgent priority"

        return Selection(task, chosen, fallback, tier, reason)

    # -- convenience -------------------------------------------------------- #
    def for_camera(self, camera_decision, anpr_grade: Grade,
                   usable_for: tuple[Analytic, ...],
                   sufficient_evidence: bool = True) -> dict[Task, Selection]:
        """Every task selection for one camera, given its budget decision."""
        common = {
            "tier": camera_decision.tier,
            "anpr_grade": anpr_grade,
            "usable_for": usable_for,
            "sufficient_evidence": sufficient_evidence,
        }
        return {
            Task.VEHICLE_DETECT: self.select(Task.VEHICLE_DETECT, **common),
            Task.PLATE_DETECT_OCR: self.select(Task.PLATE_DETECT_OCR, **common),
            Task.EMBED: self.select(Task.EMBED, **common),
        }
