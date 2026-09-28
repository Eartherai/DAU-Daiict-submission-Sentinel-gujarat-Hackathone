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


def test_the_wall_rejects_placeholder_frames():
    before = {'camera': 'cam06', 'video_id': 1, 'sample_ms': 0,
              'time': 0, 'vfc': 0}
    after = {**before, 'sample_ms': 1100, 'time': 1.1, 'vfc': 30,
             'ready': 3, 'width': 2, 'pc': 'connected'}
    assert gov.evaluate_tiles([before], [after], 1)['live'] == 0
    assert gov.evaluate_tiles([before], [{**after, 'width': 1920}], 1)['live'] == 1


def test_live_threshold_is_measured_and_configurable():
    before = [{'camera': f'cam{i:02}', 'video_id': i, 'sample_ms': 0,
               'time': 0, 'vfc': 0} for i in range(1, 13)]
    after = [{**t, 'sample_ms': 1100, 'time': 1.1, 'vfc': 30,
              'ready': 3, 'width': 1920} for t in before]
    assert gov.evaluate_tiles(before, after, 12)['passed']
    assert not gov.evaluate_tiles(before, after[:-1], 12)['passed']


def test_recorder_never_prewarms_upstream_stills():
    src = Path(gov.__file__).read_text()
    assert '/snapshot' not in src
    assert 'prewarm_stills' not in src
    assert 'new RTCPeerConnection(' not in src


def test_report_summary_counts_downloaded_distinct_plates(tmp_path, monkeypatch):
    """Exercise the report exporter, including the file delivered to the judge."""
    import io
    body = ("plate,timestamp_utc,camera_id\n"
            "GJ01AA1111,2026-09-21T10:00:00Z,cam06\n"
            "GJ01AA1111,2026-09-21T10:00:05Z,cam06\n"
            "GJ02BB2222,2026-09-21T10:01:00Z,cam12\n")
    monkeypatch.setattr(gov.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(body.encode()))
    target = tmp_path / 'report.csv'
    assert gov.fetch_report('http://unused', 'fixture', target) == {
        'ok': True, 'rows': 3, 'plates': 2, 'cameras': 2}
    assert target.read_text() == body


def test_empty_or_invalid_download_is_not_a_submission_report(tmp_path, monkeypatch):
    import io
    for body in ('<html>Unavailable</html>', 'plate,timestamp_utc,camera_id\n',
                 'plate,timestamp_utc,camera_id\nX,,cam06\n'):
        monkeypatch.setattr(gov.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(body.encode()))
        target = tmp_path / 'report.csv'
        assert not gov.fetch_report('http://unused', 'fixture', target)['ok']
        assert not target.exists()
