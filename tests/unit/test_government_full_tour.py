"""Offline plan and browser-protocol checks: no server or media connections."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/demo'))
import record_government_feed as gov


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline tour tests must not contact a host')
    monkeypatch.setattr(gov.urllib.request, 'urlopen', forbidden)


def plan(page=None, **kwargs):
    return gov.build_full(page, 'GJ11S7924', 'administrator-placeholder',
                          'officer-placeholder', government=['cam06', 'cam12'], **kwargs)


def beat(beats, prefix):
    return next(b for b in beats if b.title.startswith(prefix))


@pytest.mark.parametrize('layout', ['grid', 'dense'])
def test_full_story_duration_order_and_selector_citations(layout):
    beats = plan(opening_layout=layout)
    assert beats[0].gate and not beats[0].optional
    assert beats[1].title.startswith('Overview')
    assert 600 <= gov.beat_plan_duration(beats) <= 900
    assert beats[-2].title.endswith('administrator search refused')
    assert beats[-1].title == 'Handing back to the investigating officer'
    assert all(b.sources for b in beats)
    assert all(b.selectors or b.dwell_s == 0 for b in beats)
    prefixes = ['Watchlist matches', 'Alerts — queue', 'Open the representative',
                'Representative alert — acknowledge', 'Representative alert — investigate',
                'Representative alert — resolve', 'Representative plate', 'Investigate — partial',
                'Investigate — fuzzy', 'Investigate — attribute', 'Trajectory', 'GIS —',
                'Evidence — integrity', 'Evidence — fresh', 'The trace report', 'Cases —',
                'Evidence export', 'Gemini', 'Audit log', 'Model 1 — cameras',
                'Model 1 — measured', 'Model 1 — registry', 'Model 1 — manual',
                'Bulk onboarding', 'Model 1 — GIS', 'Model 3', 'Model 4', 'System status']
    positions = [beats.index(beat(beats, p)) for p in prefixes]
    assert positions == sorted(positions)
    assert all(b.wall for b in beats[2:6])
    assert beat(beats, 'Analytics output').visible_motion
    assert beat(beats, 'Analytics output').retry


def test_standard_plan_retains_wall_opening_and_short_duration():
    beats = gov.build(None, 'X')
    assert beats[0].wall and not beats[0].gate
    assert 240 <= gov.beat_plan_duration(beats) <= 360


def test_unimplemented_ui_features_are_explicit_skips():
    beats = plan()
    for prefix, reason in [('Watchlist entry creation', 'No watchlist add form'),
                           ('Watchlist revocation', 'no entry'),
                           ('GIS camera text filter', 'no handler')]:
        b = beat(beats, prefix)
        assert b.optional
        with pytest.raises(gov.SkipBeat, match=reason):
            b.action()


def registry(**updates):
    row = {'camera_id': 'GOVREC-cam06', 'source_domain': 'ARCHIVAL_REPLAY',
           'source_camera_id': 'cam06', 'recorded_file': True, 'synthetic': False,
           'capture_start_ist': '2026-09-28T12:00:00+05:30', **updates}
    return {'features': [{'camera_id': 'cam06', 'source_domain': 'GOVERNMENT'}, row]}


@pytest.mark.parametrize('updates', [
    {'source_domain': 'GOVERNMENT'}, {'source_camera_id': 'OWN-1'},
    {'capture_start_ist': ''}, {'capture_start_ist': '2026-02-31'},
    {'synthetic': True}, {'synthetic': None}, {'recorded_file': False},
    {'camera_id': 'bad"selector'},
])
def test_replay_rejects_missing_or_non_government_provenance(updates):
    assert not gov.replay_catalog(registry(**updates))


def test_replay_matches_replay_lane_public_metadata_and_never_calls_it_live():
    dates = gov.replay_catalog(registry())
    assert dates == {'GOVREC-cam06': '2026-09-28'}
    caption = gov.playback_caption({'live': 1, 'live_ids': list(dates)}, 'replay', list(dates), dates)
    assert caption == 'RECORDED GOVERNMENT FOOTAGE · captured 2026-09-28 · replayed'
    beats = plan(wall_domain='replay', wall_cameras=list(dates), replay_dates=dates)
    for b in beats:
        if b.wall or b.visible_motion:
            assert 'live' not in (b.title + b.say).lower()
    assert 'captured 2026-09-28' in beat(beats, 'RECORDED GOVERNMENT FOOTAGE').title


def test_replay_needs_frames_but_not_peer_connections():
    clean = {'shell': True, 'fatal': 0, 'loading': 0, 'loadingText': False}
    sample = {'passed': True, 'visible_live': 1, 'connected': 0}
    assert gov.opening_ready(sample, clean, 1, 'replay')
    assert not gov.opening_ready(sample, clean, 1)
    assert not gov.opening_ready({**sample, 'passed': False}, clean, 1, 'replay')
    assert not gov.opening_ready(sample, {**clean, 'loading': 1}, 1, 'replay')


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def count(self):
        return 0 if self.selector in self.page.missing else 1

    def get_attribute(self, name):
        if name == 'type':
            return self.page.input_type
        return 'true'

    @property
    def first(self):
        return self

    def scroll_into_view_if_needed(self):
        pass


class Page:
    url = 'http://unused/ui/#investigate'
    input_type = 'password'

    def __init__(self):
        self.fields, self.actions, self.missing = {}, [], set()
        self.response = SimpleNamespace(status=200, json=lambda: {'candidates': [
            {'camera_id': 'cam06', 'colour': 'white', 'object_type': 'car'}]},
            request=SimpleNamespace(post_data_json={'dry_run': True}))

    def locator(self, selector):
        return Locator(self, selector)

    def fill(self, selector, value):
        self.fields[selector] = value

    def check(self, selector):
        self.fields[selector] = True

    def uncheck(self, selector):
        self.fields[selector] = False

    def click(self, selector, **kwargs):
        self.actions.append(('click', selector))

    def press(self, *args):
        self.actions.append(('press', args))

    def goto(self, url, **kwargs):
        self.actions.append(('goto', url))
        self.url = url

    def evaluate(self, *args):
        self.actions.append(('evaluate', args))

    def wait_for_selector(self, *args, **kwargs):
        pass

    def wait_for_function(self, *args, **kwargs):
        pass

    def expect_response(self, *args, **kwargs):
        page = self
        class Pending:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            @property
            def value(self):
                return page.response
        return Pending()


def test_gate_checks_mask_before_filling_and_does_not_submit_during_capture():
    page = Page()
    b = plan(page, officer_id='demo.officer')[0]
    b.action()
    assert page.fields['#gate-token'] == 'officer-placeholder'
    assert page.fields['#gate-officer'] == 'demo.officer'
    assert page.fields['#gate-case'] and page.fields['#gate-purpose']
    assert not any(a[0] == 'click' for a in page.actions)
    assert 'officer-placeholder' not in json.dumps(gov.beats_report([b]))
    page = Page()
    page.input_type = 'text'
    with pytest.raises(gov.RecorderFailure, match='not masked'):
        plan(page, officer_id='demo.officer')[0].action()
    assert '#gate-token' not in page.fields


def test_missing_ui_is_skipped_without_clicking():
    page = Page()
    page.missing.add('button[data-view="alerts"]')
    with pytest.raises(gov.SkipBeat, match='UI unavailable'):
        beat(plan(page), 'Alerts — queue').action()
    assert not page.actions


@pytest.mark.parametrize('kind', ['partial', 'fuzzy', 'attribute'])
def test_search_variants_use_ui_case_purpose_and_clear_stale_filters(monkeypatch, kind):
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: None)
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)
    page = Page()
    b = beat(plan(page), 'Investigate — ' + kind)
    result = b.action()
    assert result['variant'] == kind and result['returned_observations'] == 1
    assert page.fields['#case-id'] and len(page.fields['#purpose']) >= 12
    assert page.fields['#q-from'] == page.fields['#q-to'] == ''
    if kind == 'partial':
        assert page.fields['#q-plate'] == 'GJ11*'
    elif kind == 'fuzzy':
        assert page.fields['#q-fuzzy'] is True
        assert page.fields['#q-plate'] != 'GJ11S7924'
    else:
        assert page.fields['#q-plate'] == ''
        assert page.fields['#q-colour'] == 'white'
        assert page.fields['#q-type'] == 'car'
        assert page.fields['#q-camera'] == 'cam06'


def test_attribute_search_does_not_invent_unmeasured_colour(monkeypatch):
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: None)
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)
    page = Page()
    page.response.json = lambda: {'candidates': [{'camera_id': 'cam06', 'object_type': 'car'}]}
    with pytest.raises(gov.SkipBeat, match='no government observation'):
        beat(plan(page), 'Investigate — attribute').action()


def test_manual_validation_checks_request_dry_run_and_never_imports(monkeypatch):
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: None)
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)
    page = Page()
    b = beat(plan(page), 'Model 1 — manual')
    b.action()
    first = page.fields['#ob-camera-id']
    b.action()
    assert first.startswith('DRYRUN-') and first != page.fields['#ob-camera-id']
    assert ('click', '#btn-ob-dry') in page.actions
    assert ('click', '#btn-ob-submit') not in page.actions
    page.response.request.post_data_json = {'dry_run': False}
    with pytest.raises(gov.RecorderFailure, match='dry-run validation failed'):
        b.action()


def test_bulk_fresh_ids_keep_metadata_and_do_not_overwrite_existing_rows():
    sample = 'camera_id,name\nC-1,Camera one\nC-2,Camera two\n'
    a = gov.dry_run_rows(sample, namespace='take-a')
    b = gov.dry_run_rows(sample, namespace='take-b')
    assert a.splitlines() == ['camera_id,name', 'DRYRUN-take-a-01,Camera one', 'DRYRUN-take-a-02,Camera two']
    assert set(a.splitlines()[1:]).isdisjoint(b.splitlines()[1:])


def test_unconfigured_copilot_is_a_skip_not_a_fabricated_answer(monkeypatch):
    monkeypatch.setattr(gov, 'api_read', lambda *a: (200, {'available': False, 'backend': 'local'}))
    with pytest.raises(gov.SkipBeat, match='not configured'):
        beat(plan(), 'Gemini').action()


def test_private_text_detection_is_boolean_and_report_has_no_raw_values(tmp_path, monkeypatch):
    import io
    # Construct an email-shaped fixture without putting an address in source.
    address = 'private' + chr(64) + 'example.invalid'
    assert gov.private_text(address)
    assert gov.private_text('secret-marker', ('secret-marker',))
    assert not gov.private_text('demo.officer · GOVREC-cam06')
    body = 'plate,timestamp_utc,camera_id,note\nX,2026-09-28,cam06,' + address + '\n'
    monkeypatch.setattr(gov.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(body.encode()))
    result = gov.fetch_report('http://unused', 'placeholder', tmp_path / 'out.csv')
    assert not result['ok'] and address not in json.dumps(result)
    assert not (tmp_path / 'out.csv').exists()


def test_replay_preflight_uses_registered_files_and_no_peer_connection_gate(tmp_path, monkeypatch):
    page = Page()
    page.evaluate = lambda script, *args: {'shell': True, 'fatal': 0, 'loading': 0,
                                          'loadingText': False, 'markers': 30, 'visible': True}
    catalog = registry()
    catalog['features'].extend({'camera_id': f'cam{i:02}', 'source_domain': 'GOVERNMENT'}
                               for i in range(1, 31) if i != 6)
    monkeypatch.setattr(gov, 'api_read', lambda base, token, path, timeout: (
        200, catalog if path.startswith('/gis/') else {}))
    monkeypatch.setattr(gov, 'wall_ids', lambda *a: ['GOVREC-cam06'])
    monkeypatch.setattr(gov, 'scroll_wall', lambda *a: None)
    monkeypatch.setattr(gov, 'sample_video', lambda *a: {
        'live': 1, 'live_ids': ['GOVREC-cam06'], 'visible_live': 1,
        'connected': 0, 'passed': True})
    result = gov.preflight(page, 'http://unused', 'placeholder', tmp_path, 1, 30,
                           wall_domain='replay')
    assert result['passed']
    assert result['replay_dates'] == {'GOVREC-cam06': '2026-09-28'}
    assert result['wall_ids'] == ['GOVREC-cam06']
    assert result['gates']['WHEP_READY']['measured']['transport'] == 'file replay; WHEP not required'
    assert ('click', '[data-live-domain="replay"]') in page.actions
    assert ('click', '[data-live-domain="simulation"]') not in page.actions


def test_incident_workflow_keeps_group_identity_and_records_a_clear_reason(monkeypatch):
    monkeypatch.setattr(gov, 'navigate', lambda *a, **k: None)
    monkeypatch.setattr(gov, 'wait_view', lambda *a, **k: None)

    class IncidentLocator(Locator):
        def filter(self, **kwargs):
            return self

        def all(self):
            return [self]

        def get_attribute(self, name):
            return 'representative-group' if name == 'data-group' else super().get_attribute(name)

        def get_by_role(self, role, name):
            label = name.pattern if hasattr(name, 'pattern') else name
            return IncidentLocator(self.page, label)

        def locator(self, selector):
            return IncidentLocator(self.page, selector)

        def click(self):
            self.page.actions.append(('button', self.selector))

        def focus(self):
            self.page.actions.append(('focus', self.selector))

        def select_option(self, value):
            self.page.fields[self.selector] = value

        def fill(self, value):
            self.page.fields[self.selector] = value

    page = Page()
    page.locator = lambda selector, **kwargs: IncidentLocator(page, selector)
    page.response.json = lambda: {'groups': [{'group_id': 'representative-group'}],
                                 'changed': ['representative-alert']}
    beats = plan(page)
    beat(beats, 'Open the representative').action()
    for action in ('acknowledge', 'investigate', 'resolve'):
        result = beat(beats, 'Representative alert — ' + action).action()
        assert result == {'action': action, 'changed': 1}
    assert page.fields['[aria-label="Disposition"]'] == 'cleared'
    assert 'Representative demonstration' in page.fields['[aria-label="Reason"]']
    assert ('button', 'Resolve all reads') in page.actions


def test_failed_full_preflight_never_reaches_gate_or_recording(tmp_path, monkeypatch):
    from types import ModuleType
    page = SimpleNamespace(set_default_timeout=lambda *a: None)
    ctx = SimpleNamespace(add_init_script=lambda *a: None, new_page=lambda: page)
    browser = SimpleNamespace(new_context=lambda **k: ctx, close=lambda: None)
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
        'passed': False, 'gates': {'VIDEO_ADVANCING': {'passed': False}}})
    monkeypatch.setattr(gov, 'build_full', lambda *a, **k: pytest.fail('must not prepare gate'))
    monkeypatch.setattr(gov, 'Screencast', lambda *a, **k: pytest.fail('must not capture'))
    with pytest.raises(SystemExit, match='preflight failed'):
        gov.record('http://unused', 'placeholder', 'X', tmp_path,
                   admin_token='administrator-placeholder', tour='full', wall_domain='replay')


def test_full_capture_starts_at_gate_and_pauses_for_submission(tmp_path, monkeypatch):
    from types import ModuleType
    events = []
    now = [0.0]
    def clock():
        now[0] += 1
        return now[0]
    monkeypatch.setattr(gov.time, 'monotonic', clock)
    ui = {'shell': True, 'fatal': 0, 'loading': 0, 'loadingText': False}
    page = SimpleNamespace(set_default_timeout=lambda *a: None, evaluate=lambda *a: ui,
                           wait_for_function=lambda *a: None, url='http://unused/ui/',
                           locator=lambda *a: SimpleNamespace(inner_text=lambda: 'masked sign-in'))
    ctx = SimpleNamespace(add_init_script=lambda *a: None, new_page=lambda: page)
    browser = SimpleNamespace(new_context=lambda **k: ctx, close=lambda: None)
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
        'passed': True, 'government_ids': ['cam06']})
    monkeypatch.setattr(gov, 'fetch_report', lambda *a: {'ok': True})
    monkeypatch.setattr(gov, 'api_read', lambda *a: (200, {'principal': {'user_id': 'demo.officer'}}))
    monkeypatch.setattr(gov, 'wall_ids', lambda *a: ['cam06'])
    monkeypatch.setattr(gov, 'sample_video', lambda *a: {
        'passed': True, 'visible_live': 1, 'connected': 1, 'live': 1})
    monkeypatch.setattr(gov, 'show_caption', lambda *a: None)
    fake_beats = [gov.Beat('Gate', 0, lambda: events.append('gate prepared'), gate=True),
                  gov.Beat('Overview', 0, lambda: events.append('gate submitted'))]
    monkeypatch.setattr(gov, 'build_full', lambda *a, **k: fake_beats)

    class Cast:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            events.append('capture starts')
            return self
        def __exit__(self, *a):
            pass
        def timeline_time(self):
            return now[0]
        def pause(self):
            events.append('paused')
        def resume(self):
            events.append('resumed')
        def first_timestamp(self):
            return 0
        def write(self, *a, **k):
            return {'ok': True}
        def cleanup(self):
            pass
    monkeypatch.setattr(gov, 'Screencast', Cast)
    results = gov.record('http://unused', 'officer-placeholder', 'X', tmp_path,
                         admin_token='admin-placeholder', tour='full', min_live=1, voice=None)
    assert all(b.ok for b in results)
    assert events[:2] == ['gate prepared', 'capture starts']
    assert events.count('gate prepared') == 1
    index = events.index('gate submitted')
    assert events[index - 1] == 'paused' and events[index + 1] == 'resumed'
    assert 'officer-placeholder' not in (tmp_path / 'beats.json').read_text()
