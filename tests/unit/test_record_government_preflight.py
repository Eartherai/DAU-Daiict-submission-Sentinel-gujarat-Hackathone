"""Offline readiness, report and capture-clock regressions; no browser needed."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/demo'))
import hq_screencast as hq
import record_government_feed as gov


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('unit tests must not contact any host')
    monkeypatch.setattr(gov.urllib.request, 'urlopen', forbidden)


def tile(camera='cam06', **updates):
    return {'camera': camera, 'sample_ms': 1000, 'video_id': 1, 'width': 1920,
            'ready': 3, 'time': 10, 'vfc': 100, 'pc': 'connected', 'visible': True, **updates}


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


@pytest.mark.parametrize(('passed', 'preflight_only'), [(True, True), (False, True), (False, False)])
def test_failed_or_preflight_only_run_never_captures(tmp_path, monkeypatch, passed, preflight_only):
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
    monkeypatch.setattr(gov, 'preflight', lambda *a, **k: {
        'passed': passed, 'gates': {'VIDEO_ADVANCING': {'passed': passed}}})
    monkeypatch.setattr(gov, 'fetch_report', lambda *a: pytest.fail('preflight-only must not fetch report'))
    monkeypatch.setattr(gov, 'Screencast', lambda *a, **k: pytest.fail('must not start recording'))
    if passed:
        assert gov.record('http://unused', 'test-placeholder', 'X', tmp_path,
                       admin_token='admin-placeholder', preflight_only=preflight_only) == []
    else:
        with pytest.raises(SystemExit, match='preflight failed: 0 advancing'):
            gov.record('http://unused', 'test-placeholder', 'X', tmp_path,
                       admin_token='admin-placeholder', preflight_only=preflight_only)
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


def test_offscreen_motion_is_reported_separately():
    measured = gov.evaluate_tiles([tile()], [advancing(visible=False)], 1)
    assert measured['live'] == 1
    assert measured['visible_live'] == 0
    assert measured['visible_live_ids'] == []


class ActionPage:
    """Small browser protocol fake: records the actual actions/response use."""
    url = 'http://unused/ui/#live'

    def __init__(self, rows=()):
        self.fields = {}
        self.actions = []
        self.rows = list(rows)

    def goto(self, url, **kwargs):
        self.actions.append(('goto', url))
        self.url = url

    def evaluate(self, script, *args):
        self.actions.append(('evaluate', script))

    def fill(self, selector, value):
        self.fields[selector] = value

    def uncheck(self, selector):
        self.fields[selector] = False

    def expect_response(self, predicate):
        from types import SimpleNamespace
        response = SimpleNamespace(url='http://unused/search?object_type=person',
                                   request=SimpleNamespace(method='GET'), status=200,
                                   json=lambda: {'candidates': self.rows})
        assert predicate(response)
        class Pending:
            value = response
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return Pending()

    def press(self, *args):
        self.actions.append(('press', args))

    def wait_for_selector(self, selector, **kwargs):
        self.actions.append(('wait', selector))

    def wait_for_function(self, *args, **kwargs):
        pass


def test_person_search_and_plate_search_clear_each_others_filters(monkeypatch):
    page = ActionPage([{'camera_id': 'cam12', 'object_type': 'person'}])
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: None)
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)
    beats = gov.build(page, 'GJ11S7924', government=['cam12', 'cam06'])
    person = next(b for b in beats if 'person detections' in b.title)
    assert person.action()['returned_observations'] == 1
    assert page.fields['#q-type'] == 'person'
    assert page.fields['#q-camera'] == 'cam12'
    assert page.fields['#q-plate'] == ''
    page.rows = [{'camera_id': 'cam06'}]
    search = next(b for b in beats if 'Designated plate' in b.title)
    assert search.action()['single_camera']
    assert page.fields['#q-type'] == page.fields['#q-camera'] == ''
    assert page.fields['#q-plate'] == 'GJ11S7924'
    assert search.title.startswith('SINGLE-CAMERA GOVERNMENT')


@pytest.mark.parametrize('rows', [[], [{'camera_id': 'OWN-1', 'object_type': 'person'}],
                                 [{'camera_id': 'cam12', 'object_type': 'car'}]])
def test_person_beat_cannot_claim_missing_or_wrong_detections(monkeypatch, rows):
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: None)
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)
    beats = gov.build(ActionPage(rows), 'X', government=['cam12'])
    with pytest.raises(gov.RecorderFailure, match='person detections'):
        next(b for b in beats if 'person detections' in b.title).action()


def test_cam12_rule_is_verified_then_waited_and_scrolled_into_view(monkeypatch):
    calls = []
    name = 'No pedestrians on the toll-lane carriageway'
    class Zone:
        def filter(self, **kwargs):
            assert kwargs == {'has_text': name}
            return self
        def locator(self, selector):
            assert selector == '.zone-count'
            return self
        def wait_for(self, **kwargs):
            calls.append('wait')
        def scroll_into_view_if_needed(self):
            calls.append('scroll')
        def inner_text(self):
            return '0 entries in the zone during its hours, of 3 sightings on this camera'
    class Page:
        def locator(self, selector):
            assert selector == '#analytics .zone-rule'
            return Zone()
    monkeypatch.setattr(gov, 'api_read', lambda *a: (200, {'rules': [{
        'camera_id': 'cam12', 'classes': ['person'], 'name': name, 'rule_id': 'rule-fixture'}]}))
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: calls.append('navigate'))
    beat = next(b for b in gov.build(Page(), 'X') if 'restricted zone' in b.title)
    detail = beat.action()
    assert detail['camera'] == 'cam12' and detail['label'] == 'DEMONSTRATION RULE'
    assert calls == ['navigate', 'wait', 'scroll']
    assert detail['rendered_entries'].startswith('0 entries')  # Zero is never an intrusion claim.


def test_role_handoff_uses_one_document_navigation_per_role(monkeypatch):
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)
    page = ActionPage()
    beats = gov.build(page, 'X', 'admin-placeholder', 'officer-placeholder', base='http://unused')
    next(b for b in beats if 'Model 1' in b.title).action()
    beats[-1].action()
    assert [a for a in page.actions if a[0] == 'goto'] == [
        ('goto', 'http://unused/ui/?recorder-role=administrator#cameras'),
        ('goto', 'http://unused/ui/?recorder-role=officer#cameras')]


def test_gallery_consumes_producer_fields_without_inventing_source_domain(tmp_path):
    (tmp_path / 'gallery.html').write_text('<html><img></html>')
    selected = {'image': 'retained.jpg#xywh=0,0,20,10', 'original_image': 'originals/retained.jpg',
                'original_sha256': 'fixture', 'display_image': 'display/01.png', 'display_scale': 4,
                'camera': 'cam06', 'timestamp': '2026-09-24T16:10:00+05:30',
                'plate_text': 'X', 'confidence': '0.9', 'agreeing_reads': '2',
                'provenance': 'retained evidence; verify read-frame correspondence'}
    (tmp_path / 'selected.json').write_text(json.dumps([selected]))
    stats = {'total_reads': 10, 'distinct_plates': 4, 'confirmed_registrations': 2,
             'confirmed_reads': 5, 'cameras_with_reads': 1, 'government_cameras_in_registry': 30,
             'window_start': 'fixture', 'window_end': 'fixture', 'source': 'fixture.db',
             'generated_at': 'fixture', 'definitions': {}, 'note': 'all reads, not selection'}
    (tmp_path / 'stats.json').write_text(json.dumps(stats))
    page = ActionPage()
    beat = next(b for b in gov.build(page, 'X', government=['cam06'],
                gallery=tmp_path / 'gallery.html') if 'crops from' in b.title)
    detail = beat.action()
    assert detail['crops'] == 1
    assert detail['store_stats']['total_reads'] == 10
    assert detail['store_stats']['confirmed_registrations'] == 2
    assert page.url.startswith('file:')
    del stats['confirmed_registrations']
    (tmp_path / 'stats.json').write_text(json.dumps(stats))
    with pytest.raises(gov.SkipBeat, match='stats.json contract'):
        beat.action()


def test_final_static_screen_keeps_held_duration(tmp_path, monkeypatch):
    from types import SimpleNamespace
    cast = hq.Screencast(None, tmp_path)
    cast._frames = [(100.0, tmp_path / 'f_000000.jpg')]
    cast._ended_at = 112.0
    monkeypatch.setattr(hq.shutil, 'which', lambda *a: '/fixture/ffmpeg')
    def encode(*args, **kwargs):
        (tmp_path / 'out.mp4').write_bytes(b'fixture')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(hq.subprocess, 'run', encode)
    assert cast.write(tmp_path / 'out.mp4')['ok']
    assert (tmp_path / 'frames.txt').read_text().splitlines() == [
        "file 'f_000000.jpg'", 'duration 12.000000', "file 'f_000000.jpg'"]


def test_scroll_wait_requires_visible_motion_and_never_reopens(monkeypatch):
    page = PreflightPage()
    offscreen = gov.evaluate_tiles([tile()], [advancing(visible=False)], 1)
    visible = gov.evaluate_tiles([tile()], [advancing()], 1)
    queue = iter([offscreen, visible])
    monkeypatch.setattr(gov, 'sample_video', lambda *a: next(queue))
    samples = []
    result = gov.wait_wall_motion(page, ['cam06'], 1, samples)
    assert result is visible and samples == [offscreen, visible]
    assert not page.actions


def test_opening_recheck_aborts_capture_if_wall_freezes(tmp_path, monkeypatch):
    from types import ModuleType, SimpleNamespace
    calls = []
    ui = {'shell': True, 'fatal': 0, 'loading': 0, 'loadingText': False}
    page = SimpleNamespace(set_default_timeout=lambda *a: None, evaluate=lambda *a: ui)
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
    monkeypatch.setattr(gov, 'preflight', lambda *a, **k: {'passed': True, 'government_ids': ['cam06']})
    monkeypatch.setattr(gov, 'fetch_report', lambda *a: {'ok': True})
    monkeypatch.setattr(gov, 'OPENING_WAIT_S', 0)
    monkeypatch.setattr(gov, 'wall_ids', lambda *a: ['cam06'])
    monkeypatch.setattr(gov, 'sample_video', lambda *a: gov.evaluate_tiles(
        [tile()], [tile(sample_ms=2100)], 1))
    monkeypatch.setattr(gov, 'Screencast', lambda *a, **k: pytest.fail('must not start recording'))
    with pytest.raises(SystemExit, match='no recording started'):
        gov.record('http://unused', 'test-placeholder', 'X', tmp_path,
                   admin_token='admin-placeholder', voice=None)
    assert not json.loads((tmp_path / 'opening.json').read_text())['passed']
    assert calls == ['closed']


def _opening(layout):
    return gov.opening_beats(object(), layout, lambda fraction: (lambda: None))


def test_dense_opening_is_the_control_room_wall():
    beats = _opening("dense")
    assert beats[0].title == "Government live viewing — CONTROL ROOM"
    assert [b.title for b in beats[1:]] == [
        "Government wall — top", "Government wall — middle", "Government wall — bottom"]
    assert all(b.wall for b in beats)


def test_grid_opening_still_shows_all_thirty_in_the_control_room():
    """A sandbox that cannot stream thirty at once opens on the optimized view,
    but the control room with every camera still appears, measured, not skipped."""
    beats = _opening("grid")
    assert beats[0].title == "Government live viewing — OPTIMIZED VIEW"
    assert "twelve" in beats[0].say
    assert beats[-1].title == "All thirty government cameras — CONTROL ROOM"
    assert beats[-1].wall and not beats[-1].optional
    assert "measured now" in beats[-1].say
    assert len(beats) == 5


def test_each_opening_layout_names_its_media_policy():
    assert gov.OPENING_POLICY == {"dense": "control-room", "grid": "optimized"}
    assert gov.GRID_SESSION_BUDGET == 12


def test_one_paused_sample_does_not_end_a_hold():
    """cam01 on 28 Sep: steady play, one 1.3 s pause, steady play."""
    assert not gov.hold_stalled([True, True, True, True, True, False])
    assert not gov.hold_stalled([True, False, True, False, True])
    assert not gov.hold_stalled([False])


def test_a_visible_freeze_ends_a_hold():
    assert gov.hold_stalled([True, True, False, False])
    assert gov.hold_stalled([False, False])
    assert gov.STALL_SAMPLES == 2


def test_focus_prefers_the_designated_camera_then_the_others_measured_advancing():
    assert gov.focus_order(["cam13", "cam06", "cam05"]) == ["cam06", "cam13", "cam05"]
    assert gov.focus_order(["cam13", "cam05", "cam13"]) == ["cam13", "cam05"]
    assert gov.focus_order([]) == []


def test_a_stalled_focus_is_handed_over_a_bounded_number_of_times():
    """cam06 played 28 s in one take and froze after 6 s in the next."""
    assert gov.FOCUS_SWITCHES == 2
    assert 5 <= gov.FOCUS_START_S <= 30
    src = (Path(gov.__file__)).read_text(encoding="utf-8")
    assert "visible_motion=True, retry=focus" in src
    assert "switches >= FOCUS_SWITCHES" in src
    assert "until += time.monotonic() - paused_at" in src


def test_the_opening_gate_is_the_preflight_gate():
    ok = {'passed': True, 'visible_live': 3, 'connected': 6}
    clean = {'shell': True, 'fatal': 0, 'loading': 0, 'loadingText': False}
    assert gov.opening_ready(ok, clean, 5)
    assert not gov.opening_ready({**ok, 'passed': False}, clean, 5)
    assert not gov.opening_ready({**ok, 'visible_live': 0}, clean, 5)
    assert not gov.opening_ready({**ok, 'connected': 4}, clean, 5)
    assert not gov.opening_ready(ok, {**clean, 'loadingText': True}, 5)
    assert not gov.opening_ready(ok, {**clean, 'fatal': 1}, 5)
    assert 30 <= gov.OPENING_WAIT_S <= 180
