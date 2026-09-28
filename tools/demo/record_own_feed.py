"""Record the OWNFILM lane: actual UI, 2:30-2:55, no loading screens.

Run against the primary's prepared local demo server (licensed OWN-* MP4s and
matching tracks, plus the separately labelled synthetic corpus). Both tokens
are required: ADMIN has admin:write; an officer has search permission. Tokens
are read from existing files into memory and entered only in #gate-token.
No server, ingest, or synthetic sightings are started by this recorder.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hq_screencast import Screencast

VIEW_W, VIEW_H = 2560, 1440
MIN_LENGTH_S, HARD_LIMIT_S = 150.0, 175.0
MIN_VIDEO_CAPTURE_FPS = 20.0
SYNTHETIC_PLATE = "GJ18JX7786"
SYNTHETIC_LABEL = "SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage"
OWN_LABEL = "DEMO · RECORDED LICENSED MUMBAI FOOTAGE · pipeline analysis replay"


def noop() -> None:
    pass


class RecordingError(RuntimeError):
    """Only fixed, non-sensitive diagnostics may leave the recording driver."""


@dataclass
class Beat:
    title: str
    dwell_s: float
    action: Callable[[], None] = noop
    say: str = ""
    prepare: Callable[[], None] = noop
    label: str = "DEMO · actual application · loading intervals omitted"
    monitor_video: bool = False
    ok: bool = True
    err: str = ""
    at: float = 0.0
    say_s: float = 0.0
    audio: Path | None = None


# Observe the application's own drawing calls, without changing any pixel,
# track, playback cadence, or detection. Installed before app.js is loaded.
DRAW_PROBE_JS = r"""(() => {
  const p = CanvasRenderingContext2D.prototype;
  const stroke = p.strokeRect, text = p.fillText;
  p.strokeRect = function(...args) {
    const c = this.canvas;
    if (c.matches('.intel-stage canvas.live-overlay')) {
      c.__ownDrawAt = performance.now();
      c.__ownDrawCount = (c.__ownDrawCount || 0) + 1;
    }
    return stroke.apply(this, args);
  };
  p.fillText = function(value, ...args) {
    if (this.canvas.matches('.intel-stage canvas.live-overlay') &&
        /^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$/.test(String(value))) {
      this.canvas.__ownPlateAt = performance.now();
    }
    return text.call(this, value, ...args);
  };
})();"""

MEDIA_SAMPLE_JS = r"""() => {
  const visible = e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 8 && r.height > 8 && r.bottom > 0 && r.right > 0 &&
      r.top < innerHeight && r.left < innerWidth && s.visibility !== 'hidden' &&
      s.display !== 'none';
  };
  return [...document.querySelectorAll('video')].filter(visible).map(v => {
    const host = v.closest('.intel-stage'), c = host?.querySelector('canvas.live-overlay');
    return {id: host?.dataset.camera || '', time: v.currentTime, duration: v.duration,
      ready: v.readyState, paused: v.paused, width: v.videoWidth,
      draws: c?.__ownDrawCount || 0, drawAge: performance.now() - (c?.__ownDrawAt ?? -1e9),
      plate: performance.now() - (c?.__ownPlateAt ?? -1e9) < 1500};
  });
}"""


def check_media_samples(
    before: list[dict], after: list[dict], *, require_plate: bool = False
) -> None:
    """Require every visible video, not merely one video, to advance and draw."""
    expected = {"OWN-MUM-AUTOSTAND", "OWN-MUM-QUEUE"}
    if {r["id"] for r in before} != expected or len(before) != 2:
        raise RecordingError("Both licensed own-feed videos must be visible")
    if {r["id"] for r in after} != expected or len(after) != 2:
        raise RecordingError("A visible video disappeared or an unverified video appeared")
    previous = {r["id"]: r for r in before}
    for row in after:
        old = previous[row["id"]]
        delta = row["time"] - old["time"]
        if delta < 0 and math.isfinite(row["duration"]):
            delta += row["duration"]  # native looping is still advancing
        if row["paused"] or row["ready"] < 2 or row["width"] <= 0 or delta < 0.05:
            raise RecordingError("A visible own-feed video is stalled")
        if row["draws"] <= old["draws"] or row["drawAge"] > 500:
            raise RecordingError("A visible own-feed overlay is not drawing boxes")
    if require_plate and not any(row["plate"] for row in after):
        raise RecordingError("No accepted plate was drawn during media preflight")


def preflight_media(page, *, require_plate: bool = True) -> list[dict]:
    page.wait_for_function(
        """() => [...document.querySelectorAll('.intel-stage video')]
      .length === 2 && [...document.querySelectorAll('.intel-stage video')]
      .every(v => v.readyState >= 2 && !v.paused && v.videoWidth > 0)""",
        timeout=30000,
    )
    before = page.evaluate(MEDIA_SAMPLE_JS)
    page.wait_for_timeout(1000)
    after = page.evaluate(MEDIA_SAMPLE_JS)
    check_media_samples(before, after, require_plate=require_plate)
    return after


def wait_text(page, selector: str, text: str) -> None:
    page.wait_for_function(
        """([selector, text]) => {
      const e = document.querySelector(selector);
      return !!e && e.textContent.includes(text);
    }""",
        arg=[selector, text],
        timeout=30000,
    )


def clean_screen(page) -> None:
    """Wait out transient UI; fail before capture if sensitive text is visible."""
    page.wait_for_function(
        r"""() => {
      const visible = e => !!e.getClientRects().length &&
        getComputedStyle(e).visibility !== 'hidden';
      return ![...document.querySelectorAll('.loading-note, [aria-busy="true"], .toast')]
        .some(visible) && ![...document.querySelectorAll('button:disabled')]
        .some(e => visible(e) && /Searching|Loading|Verifying/.test(e.textContent));
    }""",
        timeout=30000,
    )
    # Return a boolean, never page text or input values, to Python/logs.
    if page.evaluate(r"""() => {
      const report = document.querySelector('#report-frame')
        ?.contentDocument?.body?.innerText || '';
      const text = document.body.innerText + report;
      return /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(text) ||
        /\bskv_[A-Za-z0-9_-]+/.test(text) ||
        [...document.querySelectorAll('input')].some(e => e.getClientRects().length &&
          e.type !== 'password' && /\bskv_[A-Za-z0-9_-]+/.test(e.value));
    }"""):
        raise RecordingError("Sensitive text is visible; use non-personal demo identities")


def label_screen(page, text: str) -> None:
    # A provenance caption only; never cover or alter application results.
    page.evaluate(
        """text => {
      let e = document.querySelector('#ownfilm-provenance');
      if (!e) {
        e = document.createElement('div'); e.id = 'ownfilm-provenance';
        e.style.cssText = 'position:fixed;top:0;left:400px;right:0;z-index:2147483647;'
          + 'padding:7px 12px;background:#101821;color:#fff;font:16px monospace;'
          + 'pointer-events:none;text-align:center';
        document.body.append(e);
      }
      e.textContent = text;
    }""",
        text,
    )


def reset_gate(page, base: str, view: str = "cameras") -> None:
    page.evaluate("sessionStorage.clear()")
    # A hash-only goto keeps app.js state alive; force a fresh document.
    page.goto("about:blank")
    page.goto(f"{base}/ui/#{view}", wait_until="domcontentloaded")
    page.wait_for_selector("#gate", state="visible")
    if page.get_attribute("#gate-token", "type") != "password":
        raise RecordingError("The sign-in token field is not masked")


def fill_gate(page, token: str, officer: str, case: str, purpose: str) -> None:
    if page.get_attribute("#gate-token", "type") != "password":
        raise RecordingError("The sign-in token field is not masked")
    for selector, value in (
        ("#gate-officer", officer),
        ("#gate-token", token),
        ("#gate-case", case),
        ("#gate-purpose", purpose),
    ):
        page.fill(selector, value)


def enter_gate(page) -> None:
    page.click('#gate-form button[type="submit"]')
    page.wait_for_selector("#gate", state="hidden", timeout=20000)


def build(
    page,
    plate: str,
    case_id: str = "DEMO-OWN-2026",
    purpose: str = "demonstrating recorded feed investigation",
    admin_token: str = "",
    investigator_token: str = "",
    *,
    base: str = "http://127.0.0.1:8083",
    admin_officer: str = "admin.demo",
    investigator: str = "supervisor.demo",
    camera_id: str | None = None,
) -> list[Beat]:
    camera_id = camera_id or f"DEMO-OWN-{uuid4().hex[:10].upper()}"

    def nav(view):
        if page.evaluate("!!document.querySelector('#report-dialog')?.open"):
            page.click("#report-close")
        page.click(f'button[data-view="{view}"]')
        page.wait_for_selector(f"#view-{view}.active", state="visible")

    def onboard_form():
        enter_gate(page)
        page.wait_for_selector("#btn-onboard-toggle", state="visible")
        page.click("#btn-onboard-toggle")
        page.wait_for_selector("#onboard-manual", state="visible")

    def onboard():
        for selector, value in (
            ("#ob-camera-id", camera_id),
            ("#ob-name", "DEMO camera — no connected stream"),
            ("#ob-department", "Municipal Corporation"),
            ("#ob-district", "Ahmedabad"),
            ("#ob-lat", "23.0301"),
            ("#ob-lon", "72.5800"),
            ("#ob-vms", "DEMO registry entry"),
            ("#ob-retention", "15"),
        ):
            page.fill(selector, value)
            page.wait_for_timeout(160)

    def validate():
        page.click("#btn-ob-dry")
        wait_text(page, "#onboard-result.ok", "Valid — nothing was written. 1 row(s)")

    def commit_camera():
        # This assertion precedes the write, so a validation failure cannot fall through.
        wait_text(page, "#onboard-result.ok", "Valid — nothing was written. 1 row(s)")
        page.click("#btn-ob-submit")
        wait_text(page, "#onboard-result.ok", "Onboarded 1 camera(s)")

    def officer_gate():
        reset_gate(page, base, "investigate")

    def own_feeds():
        enter_gate(page)
        nav("intelligence")
        page.wait_for_selector("#intel-stage-a video", state="visible", timeout=30000)
        page.wait_for_selector("#intel-stage-b video", state="visible", timeout=30000)
        # Seek the recorded files to actual accepted-plate frames from their
        # authenticated sidecars. No synthetic box or plate is ever inserted.
        page.evaluate(
            """async plate => {
          for (const host of document.querySelectorAll('.intel-stage')) {
            const path = '/media/own/' + encodeURIComponent(host.dataset.camera) + '/tracks';
            const r = await fetch(path,
              {headers: {Authorization: 'Bearer ' + sessionStorage.getItem('saakshya.token')}});
            if (!r.ok) throw new Error('Track preflight failed');
            const t = await r.json();
            const index = t.frames.findIndex(f => f[1].some(b => b[7] === plate));
            const v = host.querySelector('video');
            if (index >= 0) v.currentTime = index / t.fps;
            await v.play();
          }
        }""",
            plate,
        )
        preflight_media(page)
        page.wait_for_selector("#intel-plates .alert-card", state="visible")

    def search(target):
        nav("investigate")
        page.fill("#case-id", case_id)
        page.fill("#purpose", purpose)
        page.fill("#q-plate", target)
        page.uncheck("#q-fuzzy")
        page.uncheck("#q-watchlist")
        page.press("#q-plate", "Enter")
        page.wait_for_function(
            """target => {
          const button = document.querySelector('#search-form button.primary');
          return !button.disabled &&
            document.querySelector('#traj-target')?.textContent === target &&
            !!document.querySelector('#results .result');
        }""",
            arg=target,
            timeout=30000,
        )
        page.wait_for_selector("#map", state="visible")
        if target == plate:
            page.wait_for_function("""() => {
              const rows = [...document.querySelectorAll('#results .result .cam')];
              return rows.length > 0 && rows.every(r => r.textContent.startsWith('OWN-'));
            }""")

    def alert():
        nav("alerts")
        page.click('button[data-alert-status=""]')
        card = page.locator("#alerts .incident", has_text=SYNTHETIC_PLATE).first
        card.wait_for(state="visible", timeout=30000)
        card.scroll_into_view_if_needed()

    def route():
        search(SYNTHETIC_PLATE)
        wait_text(page, "#traj-body", "C-014")
        wait_text(page, "#traj-body", "C-021")
        page.wait_for_selector("#hyp-tabs button", state="visible")
        # loadTrajectory awaits this GIS response; check the actual map layer too.
        page.wait_for_function("""() => !!document.querySelector('#map')?.width &&
          !!window.__saakshya?.map1?.layers?.trajectory &&
          !document.querySelector('#search-form button.primary').disabled""")

    def report():
        alert()
        page.locator("#alerts .incident", has_text=SYNTHETIC_PLATE).first.locator(
            "button", has_text="Trace report"
        ).click()
        page.wait_for_function(
            """() =>
          (document.querySelector('#report-frame')?.srcdoc || '').length > 1000""",
            timeout=30000,
        )
        # A modal is in the browser top layer; put the truth caption inside it.
        page.evaluate(
            """text => {
          document.querySelector('#ownfilm-report-label')?.remove();
          const e = document.createElement('p'); e.id = 'ownfilm-report-label';
          e.textContent = text;
          e.style.cssText = 'margin:0;padding:8px;color:#fff;background:#101821;'
            + 'font:16px monospace';
          document.querySelector('#report-dialog').prepend(e);
        }""",
            SYNTHETIC_LABEL,
        )

    def evidence():
        nav("evidence")
        page.wait_for_selector("#evidence-chain .ev-when", state="visible", timeout=60000)
        page.wait_for_selector("#evidence-chain table", state="visible", timeout=60000)

    return [
        Beat(
            "Sign-in gate · estate administrator",
            8,
            action=lambda: fill_gate(page, admin_token, admin_officer, case_id, purpose),
            say=(
                "The estate administrator signs in with a masked token. Camera "
                "registration needs the administrator role."
            ),
        ),
        Beat(
            "Onboarding · camera form",
            12,
            action=onboard,
            prepare=onboard_form,
            say=(
                "A clearly named demonstration camera is entered through the actual "
                "registry form. No stream is connected to this registry entry."
            ),
        ),
        Beat(
            "Onboarding · validation before write",
            7,
            prepare=validate,
            say=(
                "Validate only checks the form. The application confirms that nothing has "
                "been written."
            ),
        ),
        Beat(
            "Onboarding · committed registry entry",
            6,
            prepare=commit_camera,
            say="Only after validation does the administrator onboard the camera.",
        ),
        Beat(
            "Administrator → officer handoff",
            9,
            prepare=officer_gate,
            action=lambda: fill_gate(page, investigator_token, investigator, case_id, purpose),
            say=(
                "The investigating officer takes over, with a separate token, a case "
                "identifier and a stated purpose."
            ),
        ),
        Beat(
            "Own-feed detection · accepted ANPR votes",
            34,
            prepare=own_feeds,
            label=OWN_LABEL + " · Other corpus results: SYNTHETIC RENDERED TEST CORPUS",
            monitor_video=True,
            say=(
                "These are licensed recordings of Mumbai traffic. The browser plays each "
                "file at its native rate. The production pipeline analysed each frame "
                "beforehand. Boxes follow the video's frame clock. Plates appear when the "
                "pipeline's agreement vote holds. This is analysis replay, not a claim of "
                "live inference speed."
            ),
        ),
        Beat(
            "ANPR search · licensed own feed",
            14,
            prepare=lambda: search(plate),
            label=OWN_LABEL,
            say=(
                "A plate read from the licensed footage is searched under the officer's "
                "case and purpose. The stored observations are the evidence for this "
                "result. No real multi-camera journey is claimed."
            ),
        ),
        Beat(
            "Representative watchlist · automatic match alert",
            18,
            prepare=alert,
            label=SYNTHETIC_LABEL + " · FICTIONAL PLATE · stored automatic alert",
            say=(
                "This fictional plate belongs to the synthetic rendered test corpus. The "
                "stored automatic alert compares the read with the representative "
                "watchlist. It shows the real-time matching mechanism's output, not a new "
                "alert firing during this take."
            ),
        ),
        Beat(
            "Alert visualisation · map and route",
            20,
            prepare=route,
            label=SYNTHETIC_LABEL + " · FICTIONAL PLATE",
            say=(
                "The same fictional plate opens its observations, map and timed route. C "
                "zero fourteen to C zero twenty-one is a synthetic rendered test corpus "
                "route, not camera footage. It tests route logic; we have no real "
                "multi-camera evidence to claim."
            ),
        ),
        Beat(
            "Synthetic route · trace report",
            16,
            prepare=report,
            label=SYNTHETIC_LABEL,
            say=(
                "The application produces a trace report from those synthetic "
                "observations. The report preserves the timed legs and the digest over "
                "its rows. It is a route-logic demonstration."
            ),
        ),
        Beat(
            "Evidence · chain verification",
            18,
            prepare=evidence,
            label="DEMO · stored evidence · a verified hash proves bytes, not vehicle identity",
            say=(
                "The evidence page recomputes the hash chain. Read any cautions with the "
                "result: a verified hash proves the stored bytes. Older stills can show a "
                "different vehicle. The officer must verify the record before relying on "
                "it."
            ),
        ),
    ]


#: Map tile and Maps script hosts the workspace's basemap loads from. Nothing
#: else leaves the local origin during a take.
BASEMAP_HOSTS = ("tile.openstreetmap.org", "maps.googleapis.com", "maps.gstatic.com",
                 "khms0.googleapis.com", "khms1.googleapis.com")


def _basemap(url: str) -> bool:
    from urllib.parse import urlsplit
    host = urlsplit(url).hostname or ""
    return url.startswith("https://") and any(
        host == h or host.endswith("." + h) for h in BASEMAP_HOSTS)


def plan_duration(beats: list[Beat]) -> float:
    total = sum(b.dwell_s for b in beats)
    if not MIN_LENGTH_S <= total <= HARD_LIMIT_S - 3:
        raise RecordingError("The planned film must fit 2:30-2:52 with encoding headroom")
    return total


def narrate(beats: list[Beat], work: Path, voice: str) -> float:
    import narration

    if not narration.available():
        raise RecordingError("Narration needs macOS say, ffmpeg and ffprobe")
    work.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(beats):
        b.audio = work / f"line_{i:02d}.wav"
        b.say_s = narration.synth(b.say, b.audio, voice=voice)
        if not math.isfinite(b.say_s) or b.say_s <= 0:
            raise RecordingError(f"Narration produced no measurable audio at beat {i + 1}")
        if b.say_s + 0.6 > b.dwell_s:
            raise RecordingError(
                f"Narration exceeds its fixed slot at beat {i + 1}; shorten the line"
            )
    return plan_duration(beats)


def finish_narrated(beats, silent, out, work, offset_s):
    import narration

    total = narration.probe_duration(silent)
    lines, chapters = [], []
    for b in beats:
        start = max(0.0, b.at - offset_s)
        if b.audio:
            lines.append(narration.Line(start, b.say, b.audio, b.say_s))
        chapters.append((start, min(start + 3.2, total), b.title))
    track = narration.build_track(lines, total, work / "narration.wav")
    ass = narration.write_ass(
        lines, work / "captions.ass", width=VIEW_W, height=VIEW_H, chapter=chapters
    )
    narration.finish(silent, track, ass, out)


def validate_base(base: str) -> str:
    parts = urlsplit(base)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise RecordingError(
            "Use a local HTTP server origin without credentials or query parameters"
        )
    return base.rstrip("/")


def identity(ctx, base: str, token: str, roles: set[str]) -> str:
    res = ctx.request.get(f"{base}/me", headers={"Authorization": f"Bearer {token}"})
    if not res.ok:
        raise RecordingError("A required sign-in token was refused (PERMISSION_DENIED or expired)")
    principal = res.json().get("principal", {})
    name = principal.get("user_id", "")
    if principal.get("role", "").upper() not in roles:
        raise RecordingError("The supplied token has the wrong role")
    if not name or "@" in name or "@" in (principal.get("display_name") or ""):
        raise RecordingError("Use demo identities without personal email addresses")
    return name


def run_beats(page, cast, beats: list[Beat]) -> float:
    """Prepare while paused; the entire visible slot includes its UI actions."""
    origin = cast.timeline_time()
    for i, b in enumerate(beats):
        cast.pause()
        try:
            b.prepare()
            clean_screen(page)
            label_screen(page, b.label)
            if b.monitor_video:
                preflight_media(page)
            b.at = cast.timeline_time() - origin
            cast.resume()
            start = cast.timeline_time()
            video_frames = cast.frame_count() if b.monitor_video else 0
            print(f"  beat {i + 1}: {b.title}", flush=True)
            b.action()
            previous = page.evaluate(MEDIA_SAMPLE_JS) if b.monitor_video else None
            while cast.timeline_time() - start < b.dwell_s:
                remaining = b.dwell_s - (cast.timeline_time() - start)
                page.wait_for_timeout(min(500, max(1, int(remaining * 1000))))
                if b.monitor_video:
                    current = page.evaluate(MEDIA_SAMPLE_JS)
                    # Avoid demanding movement over the last few milliseconds.
                    if remaining >= 0.25:
                        check_media_samples(previous, current)
                    previous = current
            if b.monitor_video:
                captured_fps = (cast.frame_count() - video_frames) / (cast.timeline_time() - start)
                if captured_fps < MIN_VIDEO_CAPTURE_FPS:
                    raise RecordingError("The video beat captured too slowly; take discarded")
                print(f"  measured video-beat capture: {captured_fps:.1f} fps", flush=True)
            if cast.timeline_time() - start > b.dwell_s + 1:
                raise RecordingError("A recorded action exceeded its fixed time slot")
            if cast.timeline_time() - origin > HARD_LIMIT_S - 1:
                raise RecordingError("The capture exceeded the 2:55 budget")
        except Exception:
            cast.pause()
            b.ok, b.err = False, "Required beat failed; take discarded"
            # Playwright exceptions may include the value passed to fill().
            # Do not stringify or chain one into logs, captions, or a report.
            raise RecordingError(f"Required beat {i + 1} failed; take discarded") from None
    return origin


def duration_s(mp4: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(mp4),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip()) if result.returncode == 0 else None
    except ValueError:
        return None


def verify_duration(mp4: Path) -> float:
    secs = duration_s(mp4)
    if secs is None or not math.isfinite(secs):
        raise RecordingError("Cannot verify the final film duration")
    if secs > HARD_LIMIT_S:
        raise RecordingError("The film exceeds the hard 2:55 cap")
    if secs < MIN_LENGTH_S:
        raise RecordingError("The film is shorter than 2:30")
    return secs


def record(
    base: str,
    token: str,
    plate: str,
    out_dir: Path,
    admin_token: str = "",
    voice: str | None = "Aman",
) -> list[Beat]:
    base = validate_base(base)
    if not token or not admin_token:
        raise RecordingError(
            "Both officer and ADMIN token files are required; admin:write is mandatory"
        )
    if not re.fullmatch(r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}", plate):
        raise RecordingError("The own-feed search plate must be a canonical registration mark")
    from playwright.sync_api import sync_playwright

    mp4 = Path(str(out_dir) + ".mp4")
    # Never allow a previous successful take to masquerade as this failed take.
    if mp4.exists() or out_dir.exists():
        raise RecordingError("Choose a fresh output path for each take")
    out_dir.mkdir(parents=True)
    candidate, silent = out_dir / "candidate.mp4", out_dir / "silent.mp4"
    cast = None
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": VIEW_W, "height": VIEW_H}, service_workers="block"
            )
            # Own-film browser requests stay on the selected local origin, except
            # the basemap: without its tiles the route is drawn over a blank map.
            ctx.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(base + "/") or _basemap(route.request.url)
                    else route.abort()
                ),
            )
            ctx.add_init_script(DRAW_PROBE_JS)
            page = ctx.new_page()
            page.set_default_timeout(15000)
            admin = identity(ctx, base, admin_token, {"ADMIN"})
            officer = identity(ctx, base, token, {"SUPERVISOR", "INVESTIGATOR"})
            page.goto(f"{base}/ui/#investigate", wait_until="domcontentloaded")
            page.wait_for_selector("#gate", state="visible")
            fill_gate(
                page, token, officer, "DEMO-OWN-2026", "demonstrating recorded feed investigation"
            )
            # The own-feed prepare action enters the filled gate, then verifies both feeds.
            beats = build(
                page,
                plate,
                admin_token=admin_token,
                investigator_token=token,
                base=base,
                admin_officer=admin,
                investigator=officer,
            )
            plan_duration(beats)
            if voice:
                narrate(beats, out_dir / "narration", voice)
            # Rehearsal catches missing footage, search, synthetic alert, route,
            # report and evidence before capture/onboarding. Searches are audited.
            for b in beats[5:]:
                print(f"  preflight: {b.title}", flush=True)
                b.prepare()
                clean_screen(page)
            reset_gate(page, base)
            clean_screen(page)
            label_screen(page, beats[0].label)
            cast = Screencast(page, out_dir / "frames", width=VIEW_W, height=VIEW_H, quality=98)
            with cast:
                origin = run_beats(page, cast, beats)
            res = cast.write(silent if voice else candidate, crf=15, fps=30)
            if not res.get("ok"):
                raise RecordingError("Screen capture encoding failed")
            if voice:
                offset = (cast.first_timestamp() or origin) - origin
                finish_narrated(beats, silent, candidate, out_dir / "narration", offset)
            verify_duration(candidate)
            ctx.close()
            browser.close()
        candidate.replace(mp4)
        return beats
    except RecordingError:
        candidate.unlink(missing_ok=True)
        raise
    except Exception:
        candidate.unlink(missing_ok=True)
        raise RecordingError(
            "Own-film preflight/capture failed; no submission MP4 published"
        ) from None
    finally:
        if cast:
            cast.cleanup()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8083")
    ap.add_argument("--token-file", required=True, help="Existing officer token file; never echoed")
    ap.add_argument(
        "--admin-token-file", required=True, help="Existing ADMIN token file (admin:write)"
    )
    ap.add_argument("--voice", default="Aman", help="macOS voice, or none for a silent film")
    ap.add_argument("--plate", default="MH02GB4920")
    ap.add_argument("--out", default="var/demo/own_feed_final")
    a = ap.parse_args()
    try:
        token = Path(a.token_file).read_text(encoding="ascii").strip()
        admin = Path(a.admin_token_file).read_text(encoding="ascii").strip()
        beats = record(
            a.base,
            token,
            a.plate,
            Path(a.out),
            admin_token=admin,
            voice=None if a.voice.lower() == "none" else a.voice,
        )
        secs = verify_duration(Path(a.out + ".mp4"))
    except Exception as exc:
        # Only our fixed messages are safe; never print a raw library exception.
        raise SystemExit(
            str(exc)
            if isinstance(exc, RecordingError)
            else "Own-film failed; check local prerequisites"
        ) from None
    print(f"Verified {len(beats)} beats; {secs:.1f}s (hard cap 175s). Video: {a.out}.mp4")


if __name__ == "__main__":
    main()
