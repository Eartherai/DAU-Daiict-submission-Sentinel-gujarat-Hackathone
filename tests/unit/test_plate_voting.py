"""How a plate is published: confirmed, a lead, or not at all.

The estate cannot afford a high per-camera frame rate at scale, so a vehicle
often crosses a camera in a single analysed frame. Refusing to publish anything
from one read turned a real crossing into a blank screen. Publishing it as a
confirmation would let one uncorroborated read stop the wrong vehicle. The
answer is a third state — a lead — and these tests pin the boundary.
"""
from __future__ import annotations

from saakshya.analytics.anpr import AnprConfig, PlateVoter, RawRead


def read(text: str, conf: float, pts: float, det: float = 0.9) -> RawRead:
    return RawRead(text=text, confidence=conf, pts_s=pts, det_confidence=det,
                   box=(0, 0, 100, 40))


def voter() -> PlateVoter:
    return PlateVoter(AnprConfig())


def test_two_agreeing_reads_are_confirmed():
    v = voter()
    v.add("t1", [read("GJ05AB1234", 0.70, 1.0)])
    v.add("t1", [read("GJ05AB1234", 0.72, 1.4)])
    r = v.resolve("t1")
    assert r is not None
    assert r.votes == 2 and not r.provisional


def test_one_confident_read_is_a_lead_not_a_confirmation():
    v = voter()
    v.add("t1", [read("GJ05AB1234", 0.90, 1.0)])
    r = v.resolve("t1")
    assert r is not None, "a single confident read must not be discarded"
    assert r.votes == 1 and r.provisional
    assert "LEAD" in r.explain() and "verification" in r.explain()


def test_one_weak_read_is_still_discarded():
    """A lead needs a higher bar than a voted read, because nothing corroborates
    it. Below the single-read bar there is no publication at all."""
    v = voter()
    v.add("t1", [read("GJ05AB1234", 0.60, 1.0)])   # ok for voting, not for a lead
    assert v.resolve("t1") is None


def test_two_disagreeing_reads_do_not_become_a_lead():
    """When two valid reads disagree, neither is a dominant single read — so no
    lead is manufactured from the more confident of two competing answers."""
    v = voter()
    v.add("t1", [read("GJ05AB1234", 0.90, 1.0)])
    v.add("t1", [read("GJ05AB9999", 0.88, 1.4)])
    assert v.resolve("t1") is None


def test_leads_can_be_switched_off():
    v = PlateVoter(AnprConfig(enable_single_read_leads=False))
    v.add("t1", [read("GJ05AB1234", 0.95, 1.0)])
    assert v.resolve("t1") is None


def test_resolve_all_does_not_publish_a_single_read():
    """Camera-level eval buckets many vehicles. A single confident OCR in that
    bucket is not a lead — it is noise among other vehicles. Leads are a
    per-track decision (resolve), which is what the live pipeline uses."""
    v = voter()
    v.add("cam", [read("GJ05AB1234", 0.90, 1.0)])
    assert v.resolve_all("cam") == []
    lead = v.resolve("cam")
    assert lead is not None and lead.provisional
    assert lead.status() == "REQUIRES_VERIFICATION"


def test_resolve_all_still_publishes_corroborated_plates():
    v = voter()
    v.add("cam", [read("GJ05AB1234", 0.70, 1.0),
                  read("GJ05AB1234", 0.72, 1.4)])
    allv = v.resolve_all("cam")
    assert len(allv) == 1 and allv[0].votes == 2 and not allv[0].provisional
    assert allv[0].status() == "CONFIRMED_BY_PLATE"


def test_pipeline_emits_from_per_track_resolve():
    """A source-level pin: using resolve_all here would silently drop every
    lead, which is how the first lead implementation never reached ingest."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2]
           / "src" / "saakshya" / "analytics" / "pipeline.py").read_text()
    assert "voter.resolve(" in src
    assert "voter.resolve_all" not in src


def test_forensic_rows_keep_rejected_ocr():
    v = voter()
    v.add("t1", [read("NOT-A-PLATE", 0.99, 1.0)])
    v.add("t1", [read("GJ05AB1234", 0.90, 1.4)])
    rows = v.forensic_rows("t1")
    assert len(rows) == 2
    by_text = {r["raw_text"]: r for r in rows}
    assert by_text["NOT-A-PLATE"]["valid"] is False
    assert by_text["NOT-A-PLATE"]["reject_reason"]
    assert by_text["GJ05AB1234"]["valid"] is True
    assert by_text["GJ05AB1234"]["canonical"] == "GJ05AB1234"
    assert by_text["GJ05AB1234"]["plate_pixel_width"] == 100.0


def test_pipeline_records_rejected_ocr_even_when_no_observation():
    """A one-hit track with garbage OCR must still land in plate_reads."""
    from datetime import UTC, datetime

    from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
    from saakshya.analytics.tracker import Track

    p = CameraPipeline("cam01", PipelineConfig())
    v = voter()
    v.add("t1", [read("XXXX", 0.95, 1.0)])
    p._voters["t1"] = v
    now = datetime(2026, 9, 1, tzinfo=UTC)
    track = Track(
        track_id="t1", box=(0, 0, 100, 50), score=0.9, label="car",
        first_pts_s=1.0, last_pts_s=1.0, first_t_norm=now, last_t_norm=now,
        hits=1)
    assert p._emit(track, None) == []
    rows = p.drain_plate_reads()
    assert len(rows) == 1
    assert rows[0]["camera_id"] == "cam01"
    assert rows[0]["raw_text"] == "XXXX"
    assert rows[0]["valid"] is False
    assert rows[0]["t_norm_us"]
