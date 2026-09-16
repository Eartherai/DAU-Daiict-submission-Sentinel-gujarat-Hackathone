import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).parents[2] / "tools" / "live_feed_diagnostics.py"
    spec = importlib.util.spec_from_file_location("live_feed_diagnostics", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_unavailable_source_does_not_fabricate_measurements():
    diagnostics = load_module()
    report = diagnostics.inspect_source("rtsp://example.invalid/cam", seconds=0)
    assert report["source"] == "rtsp://example.invalid/cam"
    assert report["availability"] in {"UNAVAILABLE", "METADATA_ONLY"}
    assert report["timing"]["observed_fps"] is None
    assert report["quality"]["black_ratio"] is None


def test_markdown_labels_null_as_unavailable():
    diagnostics = load_module()
    report = diagnostics.inspect_source("/does/not/exist.mp4", retries=0)
    markdown = diagnostics.to_markdown(report)
    assert "Availability" in markdown
    assert "unavailable" in markdown
    assert "declared_fps" in markdown
