"""Sealed evidence shows the vehicle whose plate was read.

The worker used to seal the frame in hand when a track *closed*. A plate is
read mid-crossing and the track closes later, often after the vehicle has left,
so the still beside a record's plate showed whatever was in frame by then:
26 stills sealed for one plate on cam06 showed a different car. The evidence
frame is now the frame of the track's best plate read.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from saakshya.analytics.anpr import AnprConfig, PlateVoter, RawRead
from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
from saakshya.analytics.tracker import Track

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _pipeline_with_confident_read(track_id: str = "t1") -> CameraPipeline:
    p = CameraPipeline("cam06", PipelineConfig())
    v = PlateVoter(AnprConfig())
    v.add(track_id, [RawRead(text="GJ11S7924", confidence=0.95, pts_s=1.0,
                             det_confidence=0.9, box=(0, 0, 100, 40))])
    p._voters[track_id] = v
    return p


def _track(track_id: str = "t1", hits: int = 3) -> Track:
    return Track(track_id=track_id, box=(0, 0, 200, 120), score=0.9, label="car",
                 first_pts_s=1.0, last_pts_s=2.0, first_t_norm=NOW,
                 last_t_norm=NOW, hits=hits)


def _frame(tag: int) -> np.ndarray:
    return np.full((4, 4, 3), tag, dtype=np.uint8)


def test_the_sealed_frame_is_the_best_read_not_the_closing_frame():
    p = _pipeline_with_confident_read()
    weak, best, later = _frame(1), _frame(2), _frame(3)
    p._keep_evidence_frame("t1", 0.40, weak)
    p._keep_evidence_frame("t1", 0.90, best)
    p._keep_evidence_frame("t1", 0.60, later)   # a worse read does not replace it
    [obs] = p._emit(_track(), None)
    assert obs.plate == "GJ11S7924"
    assert p.evidence_frame(obs) is best


def test_the_frame_is_released_by_the_next_call():
    p = _pipeline_with_confident_read()
    p._keep_evidence_frame("t1", 0.9, _frame(2))
    [obs] = p._emit(_track(), None)
    assert p._evidence_frames == {}
    p.flush()
    assert p.evidence_frame(obs) is None, "a sealed-or-not frame outlived its call"


def test_a_track_that_publishes_no_plate_holds_no_frame():
    p = CameraPipeline("cam06", PipelineConfig())
    p._keep_evidence_frame("t1", 0.9, _frame(2))
    assert p._emit(_track(hits=1), None) == []
    assert p._evidence_frames == {}
    assert p._evidence_out == {}


def test_held_frames_are_bounded():
    p = CameraPipeline("cam06", PipelineConfig())
    for i in range(3 * CameraPipeline.MAX_EVIDENCE_FRAMES):
        p._keep_evidence_frame(f"t{i}", 0.5, _frame(i % 255))
    assert len(p._evidence_frames) == CameraPipeline.MAX_EVIDENCE_FRAMES


def test_the_read_path_keeps_the_frame_and_the_worker_seals_it():
    """Source pins, as for per-track resolve: the read path runs real models,
    and the worker is the one place a frame is sealed."""
    root = Path(__file__).resolve().parents[2] / "src" / "saakshya" / "analytics"
    pipeline = (root / "pipeline.py").read_text()
    assert "self._keep_evidence_frame(t.track_id, q.score, frame.image)" in pipeline
    worker = (root / "worker.py").read_text()
    assert "pipe.evidence_frame(o)" in worker
    assert "append((o, frame.image))" not in worker
