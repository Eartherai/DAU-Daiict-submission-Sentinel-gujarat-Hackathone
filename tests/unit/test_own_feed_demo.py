"""Offline guardrails for the final own-feed recording plan and capture clock."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "demo"))
import record_own_feed as own


def test_plan_is_ordered_and_within_the_lane_budget():
    beats = own.build(None, "MH02GB4920")
    assert own.HARD_LIMIT_S == 175
    assert 150 <= own.plan_duration(beats) <= 172
    titles = [b.title for b in beats]
    assert titles[0].startswith("Sign-in gate")
    assert "camera form" in titles[1]
    assert "validation before write" in titles[2]
    assert "committed" in titles[3]
    assert "handoff" in titles[4]
    assert "detection" in titles[5]
    assert "ANPR search" in titles[6]
    assert "watchlist" in titles[7] and "alert" in titles[7]
    assert "map and route" in titles[8]
    assert "Evidence" in titles[-1]
    assert beats[5].monitor_video
    for beat in beats[7:10]:
        assert own.SYNTHETIC_LABEL in beat.label
    assert "stored automatic alert" in beats[7].label
    spoken = " ".join(b.say for b in beats)
    assert "no real multi-camera evidence" in spoken
    assert "not a claim of live inference speed" in spoken
    assert "hundreds of frames" not in spoken


def sample(id, t=2, draws=5, **kw):
    return dict(
        id=id,
        time=t,
        duration=10,
        ready=4,
        paused=False,
        width=768,
        draws=draws,
        drawAge=20,
        plate=True,
        **kw,
    )


def pair(t=2, draws=5):
    return [sample("OWN-MUM-AUTOSTAND", t, draws), sample("OWN-MUM-QUEUE", t, draws)]


def test_preflight_accepts_both_advancing_videos_and_native_loop():
    own.check_media_samples(pair(), pair(3, 15), require_plate=True)
    own.check_media_samples(pair(9.8), pair(0.8, 15), require_plate=True)


@pytest.mark.parametrize(
    "change",
    [
        lambda rows: rows.pop(),
        lambda rows: rows[1].update(time=2),
        lambda rows: rows[1].update(paused=True),
        lambda rows: rows[1].update(ready=1),
        lambda rows: rows[1].update(width=0),
        lambda rows: rows[1].update(draws=5),
        lambda rows: rows[1].update(drawAge=900),
        lambda rows: rows.append(sample("unexpected")),
        lambda rows: [r.update(plate=False) for r in rows],
    ],
)
def test_preflight_refuses_partial_playback_or_missing_drawn_boxes(change):
    after = pair(3, 15)
    change(after)
    with pytest.raises(own.RecordingError):
        own.check_media_samples(pair(), after, require_plate=True)


class FormPage:
    def __init__(self, valid=True):
        self.events = []
        self.valid = valid

    def click(self, selector):
        self.events.append(("click", selector))

    def fill(self, selector, value):
        self.events.append(("fill", selector))  # no credential values in test logs

    def wait_for_timeout(self, _):
        pass

    def wait_for_function(self, _, *, arg, timeout):
        self.events.append(("wait", arg[1]))
        if not self.valid:
            raise RuntimeError("validation failed")

    def get_attribute(self, selector, attr):
        return "password"


def test_onboarding_uses_form_and_requires_success_before_write():
    page = FormPage()
    beats = own.build(page, "MH02GB4920")
    beats[1].action()
    beats[2].prepare()
    beats[3].prepare()
    assert ("fill", "#ob-camera-id") in page.events
    dry = page.events.index(("click", "#btn-ob-dry"))
    write = page.events.index(("click", "#btn-ob-submit"))
    assert any(e[0] == "wait" and "nothing was written" in e[1] for e in page.events[dry:write])
    refused = FormPage(valid=False)
    with pytest.raises(RuntimeError):
        own.build(refused, "MH02GB4920")[3].prepare()
    assert ("click", "#btn-ob-submit") not in refused.events


def test_gate_uses_masked_field_and_case_purpose():
    page = FormPage()
    own.fill_gate(page, "", "admin.demo", "DEMO", "demo purpose")
    assert page.events == [
        ("fill", s) for s in ("#gate-officer", "#gate-token", "#gate-case", "#gate-purpose")
    ]
    page.get_attribute = lambda *_: "text"
    with pytest.raises(own.RecordingError, match="not masked"):
        own.fill_gate(page, "", "admin.demo", "DEMO", "demo purpose")


class Clock:
    def __init__(self):
        self.now = 0
        self.paused = False

    def timeline_time(self):
        return self.now

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


def test_load_waits_are_excluded_actions_count_inside_slots(monkeypatch):
    clock = Clock()
    events = []

    def sleep(ms):
        if not clock.paused:
            clock.now += ms / 1000

    def prepare():
        assert clock.paused
        sleep(60000)
        events.append("ready")

    def action():
        assert not clock.paused
        sleep(2000)

    monkeypatch.setattr(own, "clean_screen", lambda _: None)
    monkeypatch.setattr(own, "label_screen", lambda *_: None)
    beats = [
        own.Beat("one", 4, action=action, prepare=prepare),
        own.Beat("two", 5, prepare=prepare),
    ]
    own.run_beats(SimpleNamespace(wait_for_timeout=sleep), clock, beats)
    assert clock.now == pytest.approx(9, abs=0.002)
    assert beats[1].at == pytest.approx(4, abs=0.002)
    assert events == ["ready", "ready"]


def test_failed_beat_discards_take_without_printing_library_error(monkeypatch):
    def fail():
        raise ValueError("untrusted library error must never be echoed")

    clock = Clock()
    beats = [own.Beat("failed", 4, prepare=fail)]
    with pytest.raises(own.RecordingError) as error:
        own.run_beats(None, clock, beats)
    assert "untrusted" not in str(error.value)
    assert clock.paused and not beats[0].ok


@pytest.mark.parametrize("seconds", [None, float("nan"), 149.9, 175.01, 180])
def test_duration_is_verified_and_enforced(monkeypatch, seconds):
    monkeypatch.setattr(own, "duration_s", lambda _: seconds)
    with pytest.raises(own.RecordingError):
        own.verify_duration(Path("unused.mp4"))


@pytest.mark.parametrize("seconds", [150, 162, 175])
def test_valid_duration(monkeypatch, seconds):
    monkeypatch.setattr(own, "duration_s", lambda _: seconds)
    assert own.verify_duration(Path("unused.mp4")) == seconds


def test_missing_role_token_fails_before_browser_or_output(tmp_path):
    out = tmp_path / "film"
    with pytest.raises(own.RecordingError, match="Both officer and ADMIN"):
        own.record("http://127.0.0.1:8083", "", "MH02GB4920", out)
    assert not out.exists()


@pytest.mark.parametrize(
    "base",
    [
        "https://external.invalid",
        "http://example.invalid",
        "http://user:pass@localhost",
        "http://localhost?token=anything",
    ],
)
def test_external_and_credentialed_origins_are_rejected(base):
    with pytest.raises(own.RecordingError):
        own.validate_base(base)


def test_narration_cannot_extend_a_fixed_slot(monkeypatch, tmp_path):
    import narration

    monkeypatch.setattr(narration, "available", lambda: True)
    monkeypatch.setattr(narration, "synth", lambda *_a, **_kw: 50)
    with pytest.raises(own.RecordingError, match="fixed slot"):
        own.narrate(own.build(None, "MH02GB4920"), tmp_path, "unused")


def test_canvas_probe_and_all_video_preflight_in_offline_browser(tmp_path):
    """Exercise the actual JS against native video, with no HTTP server/network."""
    import base64
    import shutil
    import subprocess

    playwright = pytest.importorskip("playwright.sync_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for the offline video fixture")
    clip = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=12",
            "-t",
            "4",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    uri = "data:video/mp4;base64," + base64.b64encode(clip.read_bytes()).decode()
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                pytest.skip("Browser launch unavailable in this sandbox")
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content("""<div class="intel-stage" data-camera="OWN-MUM-AUTOSTAND">
              <video muted autoplay loop width="160" height="90"></video>
              <canvas class="live-overlay"></canvas>
              </div><div class="intel-stage" data-camera="OWN-MUM-QUEUE">
              <video muted autoplay loop width="160" height="90"></video>
              <canvas class="live-overlay"></canvas></div>""")
            page.evaluate(own.DRAW_PROBE_JS)
            page.evaluate(
                """async uri => {
              for (const v of document.querySelectorAll('video')) {
                v.muted = true; v.src = uri; await v.play();
              }
              function draw() {
                for (const c of document.querySelectorAll('canvas')) {
                  const ctx = c.getContext('2d'); ctx.clearRect(0, 0, c.width, c.height);
                  ctx.strokeRect(1, 1, 30, 20); ctx.fillText('MH02GB4920', 1, 40);
                }
                requestAnimationFrame(draw);
              }
              draw();
            }""",
                uri,
            )
            assert len(own.preflight_media(page)) == 2
            page.evaluate("document.querySelectorAll('video')[1].pause()")
            before = page.evaluate(own.MEDIA_SAMPLE_JS)
            page.wait_for_timeout(500)
            after = page.evaluate(own.MEDIA_SAMPLE_JS)
            with pytest.raises(own.RecordingError, match="stalled"):
                own.check_media_samples(before, after)
        finally:
            browser.close()


@pytest.mark.parametrize("seconds", [0, float("nan"), -1])
def test_narration_refuses_silent_or_unmeasured_synthesis(monkeypatch, tmp_path, seconds):
    import narration

    monkeypatch.setattr(narration, "available", lambda: True)
    monkeypatch.setattr(narration, "synth", lambda *_a, **_kw: seconds)
    with pytest.raises(own.RecordingError, match="no measurable audio"):
        own.narrate(own.build(None, "MH02GB4920"), tmp_path, "unused")


def test_handoff_loads_a_fresh_document_not_only_a_hash():
    calls = []
    page = SimpleNamespace(
        evaluate=lambda js: calls.append(("evaluate", js)),
        goto=lambda url, **_: calls.append(("goto", url)),
        wait_for_selector=lambda *_a, **_kw: None,
        get_attribute=lambda *_: "password",
    )
    own.reset_gate(page, "http://127.0.0.1:8083", "investigate")
    assert calls[0] == ("evaluate", "sessionStorage.clear()")
    assert calls[1] == ("goto", "about:blank")
    assert calls[2] == ("goto", "http://127.0.0.1:8083/ui/#investigate")


@pytest.mark.parametrize("fps, accepted", [(10, False), (25, True)])
def test_video_capture_cadence_is_measured_before_publishing(monkeypatch, fps, accepted):
    clock = Clock()
    clock.frame_count = lambda: int(clock.now * fps)
    page = SimpleNamespace(
        wait_for_timeout=lambda ms: setattr(clock, "now", clock.now + ms / 1000),
        evaluate=lambda *_: [],
    )
    monkeypatch.setattr(own, "clean_screen", lambda *_: None)
    monkeypatch.setattr(own, "label_screen", lambda *_: None)
    monkeypatch.setattr(own, "preflight_media", lambda *_: None)
    monkeypatch.setattr(own, "check_media_samples", lambda *_: None)
    beats = [own.Beat("video", 2, monitor_video=True)]
    if accepted:
        own.run_beats(page, clock, beats)
        assert beats[0].ok
    else:
        with pytest.raises(own.RecordingError, match="take discarded"):
            own.run_beats(page, clock, beats)
