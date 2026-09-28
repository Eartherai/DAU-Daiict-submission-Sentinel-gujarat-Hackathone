"""Offline readiness, report and capture-clock regressions; no browser needed."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/demo'))
import record_government_feed as gov
import hq_screencast as hq


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('unit tests must not contact any host')
    monkeypatch.setattr(gov.urllib.request, 'urlopen', forbidden)


def tile(camera='cam06', **updates):
    return {'camera': camera, 'sample_ms': 1000, 'video_id': 1, 'width': 1920,
            'ready': 3, 'time': 10, 'vfc': 100, 'pc': 'connected', **updates}


def advancing(camera='cam06', **updates):
    return tile(camera, sample_ms=2100, time=11.1, vfc=130, **updates)


def test_live_requires_rendered_motion_not_just_connected_peer():
    measured = gov.evaluate_tiles([tile()], [advancing()], 1)
    assert measured['passed'] and measured['live_ids'] == ['cam06']
    assert measured['connected'] == 1
    frozen = gov.evaluate_tiles([tile()], [tile(sample_ms=2100)], 1)
    assert frozen['connected'] == 1 and frozen['live'] == 0
    assert not frozen['passed']


@pytest.mark.parametrize('update', [
    {'width': 0}, {'width': 2}, {'ready': 1}, {'time': 10}, {'vfc': 100},
    {'sample_ms': 1999}, {'video_id': 2}, {'video_id': None},
])
def test_bad_or_replaced_video_never_counts_live(update):
    after = {**advancing(), **update}
    assert not gov.evaluate_tiles([tile()], [after], 1)['passed']


def test_new_tile_and_duplicate_filmstrip_do_not_inflate_counts():
    measured = gov.evaluate_tiles([tile()], [advancing(), advancing(), advancing('cam12')], 2)
    assert measured['live'] == 1 and not measured['passed']
    assert measured['connected'] == 2


def test_motion_and_connection_are_separate_measurements():
    measured = gov.evaluate_tiles([tile()], [{**advancing(), 'pc': 'disconnected'}], 1)
    assert measured['live'] == 1 and measured['connected'] == 0


def test_registry_counts_explicit_domains_and_deduplicates():
    body = {'features': [{'camera_id': 'cam06', 'source_domain': 'GOVERNMENT'},
                         {'camera_id': 'OWN-1', 'source_domain': 'OWN_FEED'},
                         {'camera_id': 'unknown'}],
            'unlocated': [{'camera_id': 'cam06', 'source_domain': 'GOVERNMENT'},
                          {'camera_id': 'CTL-1', 'source_domain': 'SYNTHETIC_CONTROL'}]}
    counts, ids = gov.registry_composition(body)
    assert counts == {'GOVERNMENT': 1, 'OWN_FEED': 1, 'SYNTHETIC_CONTROL': 1, 'UNKNOWN': 1}
    assert ids == ['cam06']


def test_measured_caption_and_single_camera_are_not_assertions():
    assert gov.live_caption(12) == '12 of 30 government cameras live in this recording'
    assert gov.live_caption(0).startswith('0 of 30')
    with pytest.raises(ValueError):
        gov.live_caption(31)
    assert not gov.single_camera([])
    assert not gov.single_camera([{}])
    assert not gov.single_camera([{'camera_id': 'cam06'}, {'camera_id': 'cam07'}])
    rows = [{'camera_id': 'cam06'}, {'camera_id': 'cam06'}]
    assert gov.single_camera(rows)
    assert gov.search_caption(rows, ['cam06']).startswith('SINGLE-CAMERA GOVERNMENT')
    assert 'GOVERNMENT' not in gov.search_caption(rows, ['cam07'])
    assert gov.search_caption([], ['cam06']).startswith('No designated-plate')


def test_target_duration_and_order_with_optional_evidence():
    beats = gov.build(None, 'GJ11S7924')
    assert beats[0].wall and beats[0].dwell_s >= 8
    assert all(b.dwell_s >= 5 for b in beats if b.wall)
    assert 240 <= gov.beat_plan_duration(beats) <= 360
    assert sum(b.dwell_s for b in beats if not b.optional) >= 240
    titles = [b.title for b in beats]
    assert titles.index('Government ANPR — measured observations (crops from the evidence store)') < titles.index('GIS — selected camera and recorded location')
    assert 'officer' in titles[-1]
    beats[0].say_s = 40
    beats[1].skipped = True
    assert gov.beat_plan_duration(beats) == pytest.approx(sum(
        max(b.dwell_s, b.say_s + .6) for b in beats if not b.skipped))


class PreflightPage:
    url = 'about:blank'

    def __init__(self):
        self.actions = []

    def goto(self, url, **kwargs):
        self.url = url
        self.actions.append(('goto', url))

    def wait_for_selector(self, *args, **kwargs):
        pass

    def wait_for_function(self, *args, **kwargs):
        pass

    def click(self, selector, **kwargs):
        self.actions.append(('click', selector))

    def evaluate(self, script):
        if script == gov.MAP_SAMPLE:
            return {'visible': True, 'markers': 30, 'tiles': 0}
        if script == gov.UI_SAMPLE:
            return {'shell': True, 'loading': 0, 'loadingText': False, 'fatal': 0, 'view': 'view-live'}
        raise AssertionError(script)

    def locator(self, *args):
        return self

    def evaluate_all(self, *args):
        return [f'cam{i:02}' for i in range(1, 31)]


def api_fixture(path, count=30):
    if path.startswith('/gis/'):
        return 200, {'features': [{'camera_id': f'cam{i:02}', 'source_domain': 'GOVERNMENT'}
                                  for i in range(1, count + 1)], 'unlocated': []}
    return 200, {}


def test_preflight_retries_without_reloading_then_rechecks_after_scroll(tmp_path, monkeypatch):
    page = PreflightPage()
    monkeypatch.setattr(gov, 'api_read', lambda base, token, path, timeout: api_fixture(path))
    low = gov.evaluate_tiles([tile()], [tile(sample_ms=2100)], 1)
    good = gov.evaluate_tiles([tile()], [advancing()], 1)
    samples = iter([low, good, good])
    monkeypatch.setattr(gov, 'sample_video', lambda *args: next(samples))
    scrolls = []
    monkeypatch.setattr(gov, 'scroll_wall', lambda p, f: scrolls.append(f))
    result = gov.preflight(page, 'http://unused', 'test-placeholder', tmp_path, 1, 300)
    assert result['passed']
    assert len(result['samples']) == 3
    assert scrolls == [0, .5, 1, 0]
    assert sum(a[0] == 'goto' for a in page.actions) == 1
    saved = json.loads((tmp_path / 'preflight.json').read_text())
    assert all(g['passed'] and g['measured'] is not None for g in saved['gates'].values())


def test_preflight_failure_writes_all_gates_without_opening_ui(tmp_path, monkeypatch):
    page = PreflightPage()
    monkeypatch.setattr(gov, 'api_read', lambda base, token, path, timeout: api_fixture(path, 29))
    result = gov.preflight(page, 'http://unused', 'test-placeholder', tmp_path, 12, 300)
    assert not result['passed'] and not page.actions
    assert result['gates']['DB_READY']['measured']['composition']['GOVERNMENT'] == 29
    assert set(json.loads((tmp_path / 'preflight.json').read_text())['gates']) == set(gov.GATES)


def test_preflight_sample_failure_still_persists_counts(tmp_path, monkeypatch):
    page = PreflightPage()
    monkeypatch.setattr(gov, 'api_read', lambda base, token, path, timeout: api_fixture(path))
    low = gov.evaluate_tiles([tile()], [tile(sample_ms=2100)], 1)
    calls = iter([low, None])
    def sample(*args):
        value = next(calls)
        if value is None:
            raise TimeoutError()
        return value
    monkeypatch.setattr(gov, 'sample_video', sample)
    result = gov.preflight(page, 'http://unused', 'test-placeholder', tmp_path, 1, 300)
    assert not result['passed']
    assert result['latest']['connected'] == 1 and result['latest']['live'] == 0
    assert result['error'] == 'TimeoutError'
    assert not result['gates']['VIDEO_ADVANCING']['passed']


def test_missing_gallery_skips_without_navigation(tmp_path):
    beats = gov.build(None, 'X', gallery=tmp_path / 'gallery.html')
    gallery = next(b for b in beats if 'crops from' in b.title)
    with pytest.raises(gov.SkipBeat, match='absent'):
        gallery.action()


def test_non_government_gallery_is_never_labelled_government(tmp_path):
    (tmp_path / 'gallery.html').write_text('<html></html>')
    (tmp_path / 'selected.json').write_text(json.dumps([{
        'image': 'a.jpg', 'camera': 'OWN-1', 'timestamp': 'now', 'plate_text': 'X',
        'confidence': .9, 'agreeing_reads': 1, 'provenance': 'own feed'}]))
    beats = gov.build(None, 'X', government=['cam06'], gallery=tmp_path / 'gallery.html')
    with pytest.raises(gov.SkipBeat, match='provenance'):
        next(b for b in beats if 'crops from' in b.title).action()


def test_screencast_pause_excludes_loading_frames_and_elapsed_gap(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(hq.time, 'time', lambda: now[0])
    class CDP:
        def __init__(self):
            self.commands = []
        def send(self, command, *args):
            self.commands.append(command)
    cast = hq.Screencast(None, tmp_path)
    cast._cdp = CDP()
    def frame(ts):
        cast._on_frame({'sessionId': 1, 'metadata': {'timestamp': ts},
                        'data': base64.b64encode(b'jpeg fixture').decode()})
    frame(100)
    now[0] = 102
    cast.pause()
    frame(104)  # Late CDP callback while the view is loading: ACK but discard.
    assert cast.frame_count() == 1
    now[0] = 132
    assert cast.timeline_time() == 102
    cast.resume()
    frame(132)
    assert [t for t, _ in cast._frames] == [100, 102]
    assert cast.timeline_time() == 102
    assert cast._cdp.commands.count('Page.screencastFrameAck') == 3


def test_recorder_observes_only_the_app_media_sessions():
    src = Path(gov.__file__).read_text()
    assert 'prewarm_stills' not in src
    assert '/snapshot' not in src
    assert 'new RTCPeerConnection(' not in src
    assert src.count('ctx.new_page()') == 1
    assert src.count('browser.new_context(') == 1


@pytest.mark.parametrize('passed', [True, False])
def test_preflight_only_returns_before_capture_or_report(tmp_path, monkeypatch, passed):
    """Exercise the entrypoint orchestration without importing a real browser."""
    from types import ModuleType, SimpleNamespace
    calls = []
    page = SimpleNamespace(set_default_timeout=lambda *a: None)
    ctx = SimpleNamespace(add_init_script=lambda *a: None, new_page=lambda: page)
    browser = SimpleNamespace(new_context=lambda **k: ctx, close=lambda: calls.append('closed'))
    class Playwright:
        chromium = SimpleNamespace(launch=lambda **k: browser)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
    module = ModuleType('playwright.sync_api')
    module.sync_playwright = Playwright
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', module)
    monkeypatch.setattr(gov, 'preflight', lambda *a: {
        'passed': passed, 'gates': {'VIDEO_ADVANCING': {'passed': passed}}})
    monkeypatch.setattr(gov, 'fetch_report', lambda *a: pytest.fail('preflight-only must not fetch report'))
    monkeypatch.setattr(gov, 'Screencast', lambda *a, **k: pytest.fail('must not start recording'))
    if passed:
        assert gov.record('http://unused', 'test-placeholder', 'X', tmp_path, preflight_only=True) == []
    else:
        with pytest.raises(SystemExit, match='preflight failed: 0 advancing'):
            gov.record('http://unused', 'test-placeholder', 'X', tmp_path, preflight_only=True)
    assert calls == ['closed']


def test_screencast_discards_old_frames_delivered_after_resume(tmp_path, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(hq.time, 'time', lambda: now[0])
    class CDP:
        def send(self, *args):
            pass
    cast = hq.Screencast(None, tmp_path)
    cast._cdp = CDP()
    cast.pause()
    now[0] = 30
    cast.resume()
    cast._on_frame({'sessionId': 1, 'metadata': {'timestamp': 11}, 'data': ''})
    assert cast.frame_count() == 0


def test_unstable_wall_stops_at_deadline_without_reopening(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(gov.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(gov, 'api_read', lambda base, token, path, timeout: api_fixture(path))
    def frozen(*args):
        now[0] += 2
        return gov.evaluate_tiles([tile()], [tile(sample_ms=2100)], 1)
    monkeypatch.setattr(gov, 'sample_video', frozen)
    page = PreflightPage()
    result = gov.preflight(page, 'http://unused', 'test-placeholder', tmp_path, 1, 5)
    assert not result['passed']
    assert len(result['samples']) == 2 and result['elapsed_s'] <= 5
    assert sum(a[0] == 'goto' for a in page.actions) == 1
