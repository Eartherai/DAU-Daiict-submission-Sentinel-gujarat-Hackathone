"""Model loading: the class a record maps to, and what happens when it breaks.

These are cheap tests guarding an expensive failure. A detection checkpoint
loaded into a bare backbone initialises most of its weights at random, produces
an output object with no detection head, and raises on every frame — while the
caller, catching broadly, reports "no vehicles". Nothing is red. The road just
looks empty.

That is exactly what happened on the live Gujarat grid, and no amount of testing
against a corpus where motion and plate detection carried the work would have
found it.
"""
from __future__ import annotations

import pytest

from saakshya.models.registry import DETECTION_TASKS, REGISTRY, Task


def test_every_detection_task_is_declared_as_one():
    """The set is the single source of truth for which records need a detection
    head. A task added to the enumeration and forgotten here loads the wrong
    class silently."""
    assert Task.VEHICLE_DETECT in DETECTION_TASKS
    assert Task.PLATE_DETECT in DETECTION_TASKS
    assert Task.EMBED not in DETECTION_TASKS
    assert Task.VLM not in DETECTION_TASKS
    assert Task.OCR not in DETECTION_TASKS


def test_no_registered_detector_falls_outside_the_detection_set():
    """Regression: the backend compared `record.task == "detect"`, a string that
    matches no task in the registry. Every vehicle and plate detector therefore
    loaded through `AutoModel` instead of `AutoModelForObjectDetection`."""
    detectors = [r for r in REGISTRY.values()
                 if "detect" in str(r.task) and str(r.task) != "plate_detect_ocr"]
    assert detectors, "no detection models are registered at all"
    for rec in detectors:
        assert rec.task in DETECTION_TASKS, (
            f"{rec.key} has task {rec.task!r}, which is not in DETECTION_TASKS — "
            "it will be loaded as a bare backbone and raise on every frame")


def test_the_backend_chooses_its_loader_from_the_declared_set():
    """Pins the mapping without downloading a model."""
    import inspect

    from saakshya.runtime import backend

    src = inspect.getsource(backend.TransformersBackend.load)
    assert "DETECTION_TASKS" in src, (
        "the loader choice is not driven by DETECTION_TASKS; a literal "
        "comparison here is what broke every detector in the registry")
    assert '== "detect"' not in src, (
        "the literal task comparison is back")


def test_vehicle_detector_is_enabled_by_default():
    """It was off, so the whole T1 tier was dead code.

    On the synthetic corpus motion and plate detection covered for it and
    nothing failed. On real night footage, where plates are unreadable, the
    vehicle detector *is* the tier — turning it off produces a system that
    reports an empty road.
    """
    from saakshya.analytics.pipeline import PipelineConfig

    assert PipelineConfig().enable_vehicle_detector is True


def test_a_broken_detector_raises_rather_than_reporting_an_empty_road(monkeypatch):
    """A programming or model-loading error must not be indistinguishable from
    a quiet junction. Bad input for one frame is counted; a broken detector is
    not survivable and must say so."""
    import numpy as np

    from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
    from saakshya.ingest.frame import Frame

    class Broken:
        def detect(self, image):
            raise AttributeError("'ModelOutput' object has no attribute 'logits'")

    class BadInput:
        def detect(self, image):
            raise ValueError("unsupported frame")

    from datetime import UTC, datetime
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = Frame(camera_id="C-X", segment_id="S", pts_s=0.0,
                  t_norm=datetime.now(UTC), t_ingest=datetime.now(UTC),
                  image=img, width=160, height=120, codec="h264")

    p = CameraPipeline("C-X", PipelineConfig())
    p._vehicle_backend = Broken()
    with pytest.raises(AttributeError):
        p._vehicle_detections(frame)

    p2 = CameraPipeline("C-X", PipelineConfig())
    p2._vehicle_backend = BadInput()
    assert p2._vehicle_detections(frame) == []
    assert p2.stats.vehicle_detector_errors == 1
