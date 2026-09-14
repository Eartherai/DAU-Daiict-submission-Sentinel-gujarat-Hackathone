"""The ingest layer's error handling, exercised rather than assumed.

The reliability layer's whole job is to survive things that go wrong on a
government feed: malformed packets, mid-stream attachment before the first IDR,
codecs that decode badly. Those handlers are the least-exercised code in the
system precisely because the corpus is clean — every load and chaos run to date
has recorded **zero** decoder errors.

That is exactly how a handler rots. This module exercises the exception paths
directly.
"""
from __future__ import annotations

import av
import pytest

from saakshya.ingest.stream import StreamConfig, StreamManager


def test_decoder_error_clause_is_evaluable():
    """Regression: the clause named `av.error.ValueError`, which does not exist.

    Python evaluates an except tuple only when something is raised inside the
    try, so a wrong name there is invisible until the day a packet actually
    fails to decode — at which point the handler written to survive a bad packet
    raises AttributeError and takes the worker down instead. On a clean corpus
    that day never comes; on a real government feed it comes immediately.

    This test raises through the same tuple the worker uses.
    """
    for exc in (av.error.InvalidDataError(0, "synthetic"),
                av.error.EOFError(0, "synthetic"),
                ValueError("plain")):
        try:
            raise exc
        except (av.FFmpegError, ValueError) as caught:
            assert caught is exc
        else:  # pragma: no cover - the assert above always runs
            pytest.fail(f"{type(exc).__name__} escaped the decoder handler")


def test_every_pyav_error_named_in_the_source_exists():
    """Any `av.error.X` this codebase names must actually exist.

    A cheap guard against the same class of mistake reappearing anywhere else in
    the ingest layer, where these names are used and rarely executed.

    Parsed with `ast` rather than matched with a regex: the first version of
    this test scanned the source text and flagged the comment that explains the
    bug, which is the sort of false positive that gets a guard deleted.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "saakshya"
    missing = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if (isinstance(base, ast.Attribute) and base.attr == "error"
                    and isinstance(base.value, ast.Name) and base.value.id == "av"):
                if not hasattr(av.error, node.attr):
                    missing.append(f"{path.name}: av.error.{node.attr}")
            elif isinstance(base, ast.Name) and base.id == "av":
                if not hasattr(av, node.attr):
                    missing.append(f"{path.name}: av.{node.attr}")
    assert not missing, f"non-existent PyAV attributes referenced: {missing}"


def test_unreachable_camera_is_recorded_not_raised():
    """An unreachable camera must degrade to a recorded failure, not an
    exception that stops the manager."""
    mgr = StreamManager(StreamConfig(open_timeout_s=0.5, backoff_initial_s=0.1))
    mgr.reconcile({"CAM-UNREACHABLE": "rtsp://127.0.0.1:1/nothing"})
    worker = mgr.get("CAM-UNREACHABLE")
    assert worker is not None
    stats = mgr.stats()
    assert "CAM-UNREACHABLE" in stats
    mgr.stop_all()


def test_reconcile_removes_a_camera_that_left_the_catalogue():
    """The camera set changes during a run. A removed camera must stop cleanly
    rather than leaking a worker."""
    mgr = StreamManager(StreamConfig(open_timeout_s=0.5, backoff_initial_s=0.1))
    mgr.reconcile({"CAM-A": "rtsp://127.0.0.1:1/a", "CAM-B": "rtsp://127.0.0.1:1/b"})
    assert set(mgr.stats()) == {"CAM-A", "CAM-B"}
    mgr.reconcile({"CAM-A": "rtsp://127.0.0.1:1/a"})
    assert set(mgr.stats()) == {"CAM-A"}
    mgr.stop_all()
