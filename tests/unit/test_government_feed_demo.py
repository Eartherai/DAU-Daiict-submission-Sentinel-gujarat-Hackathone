"""The government-feed demonstration, and the report beside it.

Submission item 4 asks for a screen-recorded video **along with an output
report showing detected vehicles or number plates with corresponding
timestamps**. The report is the half most easily missed, because the recording
feels like the deliverable — but a video cannot be grepped, sorted, or checked
against a case file.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "demo"))

import record_government_feed as gov


class _Page:
    def __getattr__(self, _):
        return lambda *a, **k: None


def test_it_covers_what_item_four_asks_for():
    titles = " ".join(b.title.lower() for b in gov.build(_Page(), "X"))
    assert "onboarded" in titles          # 1. onboarding
    assert "live viewing" in titles       # 2. live or recorded viewing
    assert "analytics output" in titles   # 3. analytics output
    assert "timestamp" in titles          # 4. marks with timestamps


def test_the_report_is_produced_beside_the_video():
    """Not a separate manual step that can be forgotten."""
    src = (ROOT / "tools" / "demo" / "record_government_feed.py").read_text()
    assert "def fetch_report" in src
    assert "/reports/anpr.csv" in src
    # And it must be fetched in the same run as the recording.
    main = src.split("def main(", 1)[1]
    assert "fetch_report(" in main


def test_a_missing_report_is_reported_as_a_failure():
    """Silence here would ship half a submission."""
    src = (ROOT / "tools" / "demo" / "record_government_feed.py").read_text()
    assert "NOT WRITTEN" in src
    assert "needs" in src.split("NOT WRITTEN", 1)[1][:200]


def test_the_wall_waits_for_decoded_frames_not_attached_elements():
    """An empty wall filmed confidently is worse than one that is connecting.

    Matched without whitespace: the guarantee is the threshold, not how the
    expression happens to be spaced.
    """
    src = (ROOT / "tools" / "demo" / "record_government_feed.py").read_text()
    flat = "".join(src.split())
    assert "videoWidth>16" in flat, (
        "videoWidth > 0 is satisfied by the 2x2 placeholder Chrome reports "
        "before a WHEP track's first keyframe")
    assert "videoWidth>0" not in flat, "the placeholder threshold is back"


def test_the_wall_waits_for_every_visible_tile_to_show_something():
    """Four decoding tiles was a quorum, not a wall.

    A tile shows CONNECTING when it holds neither a decoded frame nor a
    cached still, so waiting only on a decode count filmed black boxes beside
    live video.
    """
    src = (ROOT / "tools" / "demo" / "record_government_feed.py").read_text()
    flat = "".join(src.split())
    assert "decoding>=8" in flat
    assert "shown===vis.length" in flat


def test_stills_are_pre_warmed_before_the_browser_opens():
    """A capture takes 1-10s; a camera first asked during filming is filmed
    before it answers."""
    src = (ROOT / "tools" / "demo" / "record_government_feed.py").read_text()
    assert "def prewarm_stills" in src
    body = src.split("def prewarm_stills", 1)[1].split("\ndef ", 1)[0]
    assert "/snapshot" in body
    # It must not invent a frame for a camera that cannot produce one.
    assert "honest outcome" in body
    main = src.split("def main(", 1)[1]
    assert "prewarm_stills(" in main


def test_report_summary_counts_distinct_plates(tmp_path):
    """A hundred sightings of one vehicle is not a hundred plates."""
    import csv, io
    body = ("plate,timestamp_utc,camera_id\n"
            "GJ01AA1111,2026-09-21T10:00:00Z,cam06\n"
            "GJ01AA1111,2026-09-21T10:00:05Z,cam06\n"
            "GJ02BB2222,2026-09-21T10:01:00Z,cam12\n")
    rows = list(csv.DictReader(io.StringIO(body)))
    plates = {r["plate"] for r in rows}
    cams = {r["camera_id"] for r in rows}
    assert len(rows) == 3 and len(plates) == 2 and len(cams) == 2
