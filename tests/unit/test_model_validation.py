"""Model activation.

These tests exist because of one failure and are shaped entirely by it. A
vehicle detector sat in the registry, behind a feature flag that defaulted to
off, loaded through a bare backbone instead of a detection class, raising on
every frame, with a broad exception handler reporting the result as "no
vehicles". Every test in the suite passed. It had never produced a detection.

The lesson was not "write a test for that detector". It was that **a registry
entry is a claim, not evidence**, and the system was treating the two as the
same thing. So activation is a gate, and these tests pin the gate.

They deliberately do not download anything: every case uses a stub backend, so
the wiring is tested without testing the internet.
"""
from __future__ import annotations

import numpy as np
import pytest

from saakshya.models.validation import (
    Activation,
    ModelNotActive,
    active_or_raise,
    synthetic_frame,
    validate,
)


def test_the_synthetic_frame_has_structure_not_noise():
    """Pure noise gives a detector nothing to latch onto, so zero detections
    would be ambiguous — broken model, or genuinely nothing there? Shapes on a
    background make "returned a well-formed output" checkable without asserting
    what the output should contain, which would be testing the model rather than
    the wiring."""
    img = synthetic_frame()
    assert img.shape[2] == 3
    assert img.dtype == np.uint8
    # More than one distinct colour region, and it is not noise.
    assert len(np.unique(img.reshape(-1, 3), axis=0)) > 3
    assert float(img.std()) < 90, "the frame should be structured, not noise"


def test_an_unknown_key_fails_at_resolution():
    rep = validate("no-such-model@9.9.9")
    assert rep.status is Activation.FAILED
    assert rep.first_failure().name == "RESOLVED"


def test_a_rejected_model_can_never_report_active():
    """The DINOv2 rejection came from a measurement — a -0.541 margin against a
    decoy. A validator that overrode it with "it loaded fine" would undo that
    work, so REJECTED short-circuits before any smoke test runs."""
    rep = validate("embed-dinov2-base@0.1.0", run_inference=False)
    assert rep.status is Activation.FAILED
    assert rep.first_failure().name == "STATUS"
    assert "REJECTED" in rep.first_failure().detail


def test_a_detection_model_loaded_as_a_backbone_fails_the_task_check(monkeypatch):
    """THE regression. A detection checkpoint in a bare backbone has no
    detection head: most weights initialise at random, the output has no
    `logits`, and `detect()` raises on every frame."""
    from saakshya.runtime import backend as backend_mod

    class BareBackbone:
        loaded = True
        _device = "cpu"
        _model = type("RTDetrV2Model", (), {})()      # no detection head

        def detect(self, image):
            raise AttributeError("'ModelOutput' object has no attribute 'logits'")

    monkeypatch.setattr(backend_mod.BACKENDS, "get", lambda rec: BareBackbone())
    rep = validate("vehicle-rtdetrv2-r18@0.1.0")
    assert rep.status is Activation.FAILED
    assert rep.first_failure().name == "TASK"
    assert "no detection head" in rep.first_failure().detail


def test_a_model_that_raises_on_inference_fails_rather_than_returning_nothing(
        monkeypatch):
    """The failure must be reported as a failure. Returning an empty list here
    is what made a broken detector look like an empty road."""
    from saakshya.runtime import backend as backend_mod

    class Exploding:
        loaded = True
        _device = "cpu"
        _model = type("RTDetrV2ForObjectDetection", (), {})()

        def detect(self, image):
            raise RuntimeError("kernel failed")

    monkeypatch.setattr(backend_mod.BACKENDS, "get", lambda rec: Exploding())
    rep = validate("vehicle-rtdetrv2-r18@0.1.0")
    assert rep.status is Activation.FAILED
    assert rep.first_failure().name == "INFERENCE"
    assert "kernel failed" in rep.first_failure().detail


def test_malformed_output_fails_the_output_check(monkeypatch):
    """A model that returns something of the wrong shape is broken even though
    it did not raise."""
    from saakshya.runtime import backend as backend_mod

    class WrongShape:
        loaded = True
        _device = "cpu"
        _model = type("RTDetrV2ForObjectDetection", (), {})()

        def detect(self, image):
            return {"boxes": [[0, 0, 1, 1]]}          # not a list of Detection

    monkeypatch.setattr(backend_mod.BACKENDS, "get", lambda rec: WrongShape())
    rep = validate("vehicle-rtdetrv2-r18@0.1.0")
    assert rep.status is Activation.FAILED
    assert rep.first_failure().name == "OUTPUT"


def test_a_well_wired_detector_reports_active(monkeypatch):
    """The positive control. Without it, every assertion above could be passing
    because the fixture is broken rather than because the gate works."""
    from dataclasses import dataclass

    from saakshya.runtime import backend as backend_mod

    @dataclass
    class Det:
        box: tuple
        score: float
        label: str

    class Working:
        loaded = True
        _device = "cpu"
        _model = type("RTDetrV2ForObjectDetection", (), {})()

        def detect(self, image):
            return [Det((10, 10, 90, 70), 0.82, "car")]

    monkeypatch.setattr(backend_mod.BACKENDS, "get", lambda rec: Working())
    rep = validate("vehicle-rtdetrv2-r18@0.1.0")
    assert rep.status is Activation.ACTIVE, rep.to_dict()
    # The order is asserted, not just membership: each check is a precondition
    # for the next, and a gate that ran INFERENCE before LOADED would report a
    # meaningless result. WEIGHTS sits after TASK — there is no point comparing
    # a task head before knowing the model was loaded through the right class.
    assert [c.name for c in rep.checks] == [
        "RESOLVED", "STATUS", "LICENCE", "LOADED", "TASK", "WEIGHTS",
        "INFERENCE", "OUTPUT"]


def test_active_or_raise_refuses_a_broken_model(monkeypatch):
    """Used at pipeline construction. A model that fails here is a fault to
    surface, not a reason to quietly produce no detections."""
    from saakshya.runtime import backend as backend_mod

    class Exploding:
        loaded = True
        _device = "cpu"
        _model = type("RTDetrV2ForObjectDetection", (), {})()

        def detect(self, image):
            raise RuntimeError("boom")

    monkeypatch.setattr(backend_mod.BACKENDS, "get", lambda rec: Exploding())
    with pytest.raises(ModelNotActive, match="INFERENCE"):
        active_or_raise("vehicle-rtdetrv2-r18@0.1.0")
