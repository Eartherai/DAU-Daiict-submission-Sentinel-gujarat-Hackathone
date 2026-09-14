"""Runtime profiles — one codebase, three execution environments.

    DEV_CPU      Apple Silicon / any CPU-only host. Correctness and development.
    CLOUD_GPU    Rented CUDA host. Benchmarking and accuracy measurement only.
    TARGET_GPU   Deployment profile: regional GPU node, TensorRT/DeepStream.

The profile changes **which model tier is selected and how inference is
executed**. It must never change business logic, event semantics, confidence
maths, or what the system is willing to assert. A trajectory computed on
DEV_CPU and on TARGET_GPU must differ only in latency and in which models were
available — and the event record says which, so the difference is auditable.

Selection order: explicit ``SAAKSHYA_PROFILE`` env var, then detection.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import StrEnum

from saakshya.runtime.hardware import Hardware, probe

log = logging.getLogger(__name__)


class Profile(StrEnum):
    DEV_CPU = "DEV_CPU"
    CLOUD_GPU = "CLOUD_GPU"
    TARGET_GPU = "TARGET_GPU"


@dataclass(frozen=True)
class RuntimeContext:
    """Everything the router needs to choose a model, resolved once at start-up."""

    profile: Profile
    hardware: Hardware
    #: Preferred ONNX Runtime providers, most specific first.
    providers: tuple[str, ...]
    #: Whether models above the "small" tier may be loaded at all.
    allow_heavy_models: bool
    #: Whether remote inference may be used (never for the core test case).
    allow_remote_inference: bool
    reason: str

    @property
    def is_gpu(self) -> bool:
        return self.profile in (Profile.CLOUD_GPU, Profile.TARGET_GPU)

    def describe(self) -> str:
        return (f"profile={self.profile} providers={list(self.providers)} "
                f"heavy_models={self.allow_heavy_models} "
                f"remote={self.allow_remote_inference}\n  {self.hardware.summary}\n"
                f"  reason: {self.reason}")


def _providers_for(hw: Hardware, profile: Profile) -> tuple[str, ...]:
    if profile is Profile.DEV_CPU:
        # CoreML is deliberately excluded: it is present on this hardware but
        # fails on zero-element dynamic shapes. Opt in explicitly if a specific
        # graph is known to be safe.
        if os.getenv("SAAKSHYA_ENABLE_COREML") == "1" and hw.has_coreml:
            return ("CoreMLExecutionProvider", "CPUExecutionProvider")
        return ("CPUExecutionProvider",)

    chain: list[str] = []
    if hw.has_tensorrt and "TensorrtExecutionProvider" in hw.onnx_providers:
        chain.append("TensorrtExecutionProvider")
    if hw.has_cuda and "CUDAExecutionProvider" in hw.onnx_providers:
        chain.append("CUDAExecutionProvider")
    chain.append("CPUExecutionProvider")
    return tuple(chain)


def resolve(profile: Profile | str | None = None) -> RuntimeContext:
    """Resolve the runtime context. Explicit argument > env var > detection."""
    hw = probe()

    requested = profile or os.getenv("SAAKSHYA_PROFILE")
    if requested:
        try:
            chosen = Profile(str(requested).upper())
            reason = f"explicitly requested ({'argument' if profile else 'SAAKSHYA_PROFILE'})"
        except ValueError:
            chosen = Profile.DEV_CPU
            reason = f"unknown profile {requested!r}; fell back to DEV_CPU"
            log.warning(reason)
        else:
            # Refuse to pretend. Asking for a GPU profile on a host with no GPU
            # would silently produce numbers we could not defend.
            if chosen in (Profile.CLOUD_GPU, Profile.TARGET_GPU) and not hw.has_cuda:
                log.warning(
                    "Profile %s requested but no CUDA GPU detected — running "
                    "DEV_CPU. Any timing recorded here is CPU timing.", chosen)
                chosen = Profile.DEV_CPU
                reason = f"{requested} requested but no CUDA GPU present; forced DEV_CPU"
    elif hw.has_cuda:
        chosen = Profile.TARGET_GPU if hw.has_deepstream else Profile.CLOUD_GPU
        reason = ("CUDA GPU detected with DeepStream" if hw.has_deepstream
                  else "CUDA GPU detected, no DeepStream")
    else:
        chosen = Profile.DEV_CPU
        reason = "no CUDA GPU detected"

    return RuntimeContext(
        profile=chosen,
        hardware=hw,
        providers=_providers_for(hw, chosen),
        allow_heavy_models=chosen is not Profile.DEV_CPU,
        allow_remote_inference=os.getenv("SAAKSHYA_ALLOW_REMOTE") == "1",
        reason=reason,
    )


_CONTEXT: RuntimeContext | None = None


def context() -> RuntimeContext:
    """Process-wide runtime context, resolved on first use."""
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = resolve()
        log.info("runtime: %s", _CONTEXT.describe())
    return _CONTEXT


def override(ctx: RuntimeContext) -> None:
    """Replace the context. Tests only — production resolves once."""
    global _CONTEXT
    _CONTEXT = ctx
