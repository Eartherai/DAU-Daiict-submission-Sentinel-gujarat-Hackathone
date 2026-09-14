"""Runtime profiles, analytics budget, and model routing.

These tests encode the rules the system must not break regardless of hardware:
capability is a ceiling, the absence of a GPU is never fatal, and a model is
never selected that the licence policy forbids.
"""
from __future__ import annotations

import pytest

from saakshya.models.registry import (
    LicenceClass,
    Status,
    Task,
    audit,
    by_task,
    rejected,
)
from saakshya.models.router import ModelRouter
from saakshya.registry.models import Analytic, Grade
from saakshya.runtime.budget import AnalyticsBudget, Priority, Tier
from saakshya.runtime.hardware import Hardware
from saakshya.runtime.profile import Profile, RuntimeContext, resolve


def _ctx(profile: Profile, *, cuda: bool = False, vram: int = 0) -> RuntimeContext:
    from saakshya.runtime.hardware import GpuInfo

    gpus = (GpuInfo(0, "synthetic", vram),) if cuda else ()
    hw = Hardware(os_name="Linux", arch="x86_64", cpu_count=16,
                  total_memory_mb=65536, has_cuda=cuda, gpus=gpus,
                  onnx_providers=("CUDAExecutionProvider", "CPUExecutionProvider")
                  if cuda else ("CPUExecutionProvider",))
    return RuntimeContext(
        profile=profile, hardware=hw,
        providers=("CUDAExecutionProvider", "CPUExecutionProvider") if cuda
        else ("CPUExecutionProvider",),
        allow_heavy_models=profile is not Profile.DEV_CPU,
        allow_remote_inference=False, reason="synthetic test context",
    )


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def test_gpu_profile_is_refused_without_a_gpu(monkeypatch):
    """Asking for a GPU profile on a CPU host must not silently pretend."""
    monkeypatch.setenv("SAAKSHYA_PROFILE", "TARGET_GPU")
    ctx = resolve()
    if not ctx.hardware.has_cuda:
        assert ctx.profile is Profile.DEV_CPU
        assert "no CUDA GPU" in ctx.reason


def test_dev_cpu_excludes_coreml_by_default():
    ctx = resolve(Profile.DEV_CPU)
    assert "CoreMLExecutionProvider" not in ctx.providers


# --------------------------------------------------------------------------- #
# Registry governance
# --------------------------------------------------------------------------- #
def test_registry_audit_is_clean():
    assert audit() == []


def test_no_copyleft_model_is_approved():
    from saakshya.models.registry import REGISTRY

    for m in REGISTRY.values():
        if m.licence_class is LicenceClass.COPYLEFT_STRONG:
            assert not m.approved_for_demo, f"{m.key} is AGPL/GPL but approved"
            assert m.status is Status.REJECTED


def test_rejected_models_keep_their_reason():
    for m in rejected():
        assert m.notes.strip(), f"{m.key} rejected without a recorded reason"


def test_by_task_excludes_rejected():
    keys = {m.key for m in by_task(Task.PLATE_DETECT_OCR)}
    assert "anpr-onnx-fastalpr-default@0.0.0" not in keys


# --------------------------------------------------------------------------- #
# Budget — capability is a ceiling
# --------------------------------------------------------------------------- #
def test_unmeasured_camera_gets_cheap_analytics_not_a_guess():
    b = AnalyticsBudget(ctx=_ctx(Profile.DEV_CPU))
    d = b.decide("C-1", Grade.UNKNOWN, Grade.UNKNOWN, (), sufficient_evidence=False)
    assert d.tier is Tier.T1_VEHICLE
    assert not d.expensive_inference
    assert Analytic.ANPR not in d.permitted


def test_urgent_priority_cannot_raise_an_incapable_camera():
    b = AnalyticsBudget(ctx=_ctx(Profile.DEV_CPU))
    d = b.decide("C-33", Grade.D, Grade.C, (Analytic.VEHICLE_DETECT,),
                 priority=Priority.URGENT)
    assert Analytic.ANPR not in d.permitted
    assert d.tier <= Tier.T1_VEHICLE


def test_capable_camera_gets_identity_tier():
    b = AnalyticsBudget(ctx=_ctx(Profile.DEV_CPU))
    d = b.decide("C-14", Grade.A, Grade.A,
                 (Analytic.VEHICLE_DETECT, Analytic.VEHICLE_REID, Analytic.ANPR))
    assert d.tier is Tier.T2_IDENTITY
    assert Analytic.ANPR in d.permitted
    assert d.sampling_fps > 0


def test_queue_saturation_reduces_sampling():
    cap = (Analytic.VEHICLE_DETECT, Analytic.VEHICLE_REID, Analytic.ANPR)
    calm = AnalyticsBudget(ctx=_ctx(Profile.DEV_CPU), queue_pressure=0.0)
    busy = AnalyticsBudget(ctx=_ctx(Profile.DEV_CPU), queue_pressure=0.95)
    calm_fps = calm.decide("C", Grade.A, Grade.A, cap).sampling_fps
    busy_fps = busy.decide("C", Grade.A, Grade.A, cap).sampling_fps
    assert busy_fps < calm_fps


def test_many_cameras_on_cpu_reduce_per_camera_sampling():
    cap = (Analytic.VEHICLE_DETECT, Analytic.ANPR)
    b = AnalyticsBudget(ctx=_ctx(Profile.DEV_CPU))
    few = b.plan([{"camera_id": f"C{i}", "anpr_grade": Grade.A,
                   "reid_grade": Grade.A, "usable_for": cap} for i in range(2)])
    many = b.plan([{"camera_id": f"C{i}", "anpr_grade": Grade.A,
                    "reid_grade": Grade.A, "usable_for": cap} for i in range(50)])
    assert many[0].sampling_fps < few[0].sampling_fps


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def test_router_declines_anpr_on_incapable_camera():
    r = ModelRouter(ctx=_ctx(Profile.DEV_CPU))
    sel = r.select(Task.PLATE_DETECT_OCR, tier=Tier.T2_IDENTITY,
                   anpr_grade=Grade.D, usable_for=(Analytic.VEHICLE_DETECT,))
    assert sel.declined and sel.model is None
    assert "not ANPR-capable" in sel.reason


def test_router_declines_when_capability_unmeasured():
    r = ModelRouter(ctx=_ctx(Profile.DEV_CPU))
    sel = r.select(Task.PLATE_DETECT_OCR, tier=Tier.T2_IDENTITY,
                   anpr_grade=Grade.A, usable_for=(Analytic.ANPR,),
                   sufficient_evidence=False)
    assert sel.declined


def test_router_selects_the_measured_anpr_model_on_cpu():
    r = ModelRouter(ctx=_ctx(Profile.DEV_CPU))
    sel = r.select(Task.PLATE_DETECT_OCR, tier=Tier.T2_IDENTITY,
                   anpr_grade=Grade.A, usable_for=(Analytic.ANPR,))
    assert not sel.declined
    assert sel.model is not None
    assert sel.model.name == "anpr-onnx-cpu"
    assert sel.model.licence_class is LicenceClass.PERMISSIVE


def test_vlm_unavailable_without_gpu_but_core_unaffected():
    r = ModelRouter(ctx=_ctx(Profile.DEV_CPU))
    vlm = r.select(Task.VLM, tier=Tier.T3_FORENSIC)
    assert vlm.declined
    assert "no GPU" in vlm.reason
    # The mandatory path must still resolve on the same host.
    anpr = r.select(Task.PLATE_DETECT_OCR, tier=Tier.T2_IDENTITY,
                    anpr_grade=Grade.A, usable_for=(Analytic.ANPR,))
    assert not anpr.declined


def test_router_never_returns_a_copyleft_model():
    for profile in (Profile.DEV_CPU, Profile.TARGET_GPU):
        r = ModelRouter(ctx=_ctx(profile, cuda=profile is Profile.TARGET_GPU, vram=24000),
                        allow_unapproved=True)
        for task in Task:
            sel = r.select(task, tier=Tier.T3_FORENSIC, anpr_grade=Grade.A,
                           usable_for=(Analytic.ANPR, Analytic.VEHICLE_REID))
            if sel.model is not None:
                assert sel.model.licence_class is LicenceClass.PERMISSIVE, \
                    f"{sel.model.key} has licence {sel.model.licence}"


def test_selection_carries_provenance():
    r = ModelRouter(ctx=_ctx(Profile.DEV_CPU))
    sel = r.select(Task.PLATE_DETECT_OCR, tier=Tier.T2_IDENTITY,
                   anpr_grade=Grade.A, usable_for=(Analytic.ANPR,))
    prov = sel.provenance()
    assert prov["model"] and prov["runtime"]


@pytest.mark.parametrize("profile", [Profile.DEV_CPU, Profile.CLOUD_GPU, Profile.TARGET_GPU])
def test_every_profile_can_run_the_mandatory_chain(profile):
    """No profile may make plate reading impossible — that is the mandatory test case."""
    ctx = _ctx(profile, cuda=profile is not Profile.DEV_CPU, vram=24000)
    r = ModelRouter(ctx=ctx)
    sel = r.select(Task.PLATE_DETECT_OCR, tier=Tier.T2_IDENTITY,
                   anpr_grade=Grade.A, usable_for=(Analytic.ANPR,))
    assert not sel.declined, f"{profile} cannot run ANPR: {sel.reason}"
