from __future__ import annotations

from pathlib import Path

from tools.benchmark_detectors import _pct
from tools.profile_pipeline import percentile, run


def test_percentiles_are_defined_for_single_sample():
    assert percentile([4.25], 99) == 4.25
    assert _pct([8.5], 95) == 8.5


def test_profile_empty_media_is_honest(tmp_path: Path):
    result = run(tmp_path, max_seconds=1, max_cameras=2)
    assert result["measurement_class"] == "MEASURED"
    assert result["clips"] == []
    assert result["counters"]["frames_received"] == 0
    assert result["throughput_fps"] == 0.0
    assert all(item["p50_ms"] is None for item in result["stages"].values())
