import pytest

from saakshya.runtime.inference_scheduler import AdaptiveInferenceScheduler, InferenceMode
from tools.benchmark_pipeline import run


def test_modes_increase_cadence():
    scheduler = AdaptiveInferenceScheduler()
    assert sum(scheduler.plan(i).infer for i in range(12)) == 3
    scheduler.set_mode(InferenceMode.ALERT)
    assert sum(scheduler.plan(i).infer for i in range(12)) == 12
    scheduler.set_mode(InferenceMode.FORENSIC)
    assert all(scheduler.plan(i).ocr and scheduler.plan(i).reid for i in range(4))


def test_queue_is_bounded_and_priority_work_evicts_routine():
    scheduler = AdaptiveInferenceScheduler(max_queue_depth=2)
    assert scheduler.admit(InferenceMode.NORMAL)
    assert scheduler.admit(InferenceMode.HIGH_PRIORITY)
    assert not scheduler.admit(InferenceMode.NORMAL)
    assert scheduler.admit(InferenceMode.ALERT)
    assert scheduler.queue_depth == 2
    assert scheduler.complete() is InferenceMode.HIGH_PRIORITY


def test_forensic_cannot_be_evicted_and_invalid_inputs_are_rejected():
    scheduler = AdaptiveInferenceScheduler(max_queue_depth=1)
    assert scheduler.admit(InferenceMode.FORENSIC)
    assert not scheduler.admit(InferenceMode.ALERT)
    with pytest.raises(ValueError):
        AdaptiveInferenceScheduler(max_queue_depth=0)
    with pytest.raises(ValueError):
        scheduler.plan(-1)


def test_benchmark_reports_catalogue_and_processed_counts(tmp_path):
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text('{"cameras": [{"id": "missing-1"}, {"id": "missing-2"}]}')
    result = run(30, catalogue, tmp_path / "report.json", "government", 0.1)
    assert result["measurement_class"] == "GOVERNMENT CATALOGUE"
    assert result["catalogue_count"] == 2
    assert result["processed_camera_count"] == 0
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    assert "Frames Received" in (tmp_path / "report.md").read_text()
