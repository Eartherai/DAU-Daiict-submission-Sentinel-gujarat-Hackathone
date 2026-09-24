"""The own-feed demonstration, to the length the challenge allows.

Submission item 3 asks for a screen recording of **maximum 2-3 minutes** on the
participant's own feed, showing four things:

  1. onboarding and processing of live or recorded CCTV feeds;
  2. AI-powered detection and analytics;
  3. correlation of detected entities with a representative watchlist;
  4. automatic real-time alert generation and visualisation on a match.

The full platform tour runs twenty minutes, which is the wrong artifact for
this requirement: a reviewer with a three-minute budget should not have to find
the relevant ninety seconds inside it. This records only those four things, in
that order, and refuses to finish over the limit.

    python tools/demo/record_own_feed.py --base http://127.0.0.1:8083 \
        --token-file /path/to/token.raw

Nothing here is staged. Onboarding really onboards through the registry API,
the detections are drawn by the AI worker on our own feeds, and the alert is
whatever the watchlist actually fired.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hq_screencast import Screencast, probe  # noqa: E402

#: 1440p. Measured against Playwright's own recorder on the same
#: content: that path stretched a 20.3s interaction into 27.3s of
#: video and capped at 25fps, which makes the product look slower
#: than it is. The CDP screencast came back timing-accurate to
#: 0.1s at 30fps and half the size, with equivalent sharpness.
VIEW_W, VIEW_H = 2560, 1440
#: The challenge says 2-3 minutes. Aim under three and fail loudly if over.
HARD_LIMIT_S = 180.0


@dataclass
class Beat:
    title: str
    dwell_s: float
    action: Callable[[], None] = lambda: None
    #: What the narrator says over this beat. Its measured length can extend the
    #: beat, never shorten it, so the voice always finishes over its own screen.
    say: str = ""
    ok: bool = True
    err: str = ""
    at: float = field(default=0.0)
    say_s: float = 0.0
    audio: Path | None = None


def build(page, plate: str, case_id: str = "FIR-000/2026",
          purpose: str = "tracing a designated vehicle",
          admin_token: str = "", investigator_token: str = "") -> list[Beat]:
    def use_token(token: str):
        """Sign in as a different officer, the way the workspace does it.

        Not a convenience: onboarding needs `admin:write` and ADMIN holds no
        search permission, because running the estate and investigating people
        are different jobs. One token cannot film both halves, and the first
        take proved it — the onboarding beat recorded
        `PERMISSION_DENIED: role SUPERVISOR does not hold admin:write`, which
        is the authorisation model working exactly as designed and the
        demonstration failing because of it.
        """
        def go():
            if not token:
                return
            page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
        return go

    def nav(view: str, settle: float = 1.5):
        def go():
            # A report left open is modal; close it before moving on.
            if page.evaluate("!!document.querySelector('#report-dialog')?.open"):
                page.click("#report-close")
                page.wait_for_timeout(300)
            page.click(f'button[data-view="{view}"]')
            page.wait_for_timeout(int(settle * 1000))
        return go

    def onboard():
        """Onboard a camera the way an operator does, on camera.

        This used to POST to /registry/cameras/import from page.evaluate. The
        onboarding happened and the recording showed nothing: a reviewer saw a
        page reload and a new row appear, with no visible cause. Model 1's
        named deliverable is a *demonstration* of manual and bulk onboarding,
        and an invisible fetch demonstrates nothing.

        It now fills the form in the Cameras view, validates first, then
        commits — which is also the honest order, because the validate step is
        what proves the dry run writes nothing.
        """
        page.click('button[data-view="cameras"]')
        page.wait_for_timeout(2200)
        page.click("#btn-onboard-toggle")
        page.wait_for_timeout(700)
        for sel, value in (
                ("#ob-camera-id", "MC-ONBOARD-01"),
                ("#ob-name", "Onboarded during this recording"),
                ("#ob-department", "Municipal Corporation"),
                ("#ob-district", "Ahmedabad"),
                ("#ob-lat", "23.0301"),
                ("#ob-lon", "72.5800"),
                ("#ob-vms", "Milestone"),
                ("#ob-retention", "15")):
            try:
                page.fill(sel, value, timeout=3000)
                page.wait_for_timeout(110)
            except Exception:
                continue
        page.wait_for_timeout(500)
        # Validate first: the panel reports what would happen and writes
        # nothing, which is the guarantee worth filming.
        try:
            page.click("#btn-ob-dry", timeout=3000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
        try:
            page.click("#btn-ob-submit", timeout=3000)
            page.wait_for_timeout(2600)
        except Exception:
            pass

    def registry_gaps():
        """The other half of Model 1: what the registry does not know.

        Filtering to the rows with unsupplied metadata is the gap report made
        interactive — the same 94% the generated report names, on screen and
        narrowable.
        """
        try:
            page.click("#btn-onboard-toggle", timeout=2500)
        except Exception:
            pass
        page.wait_for_timeout(500)
        try:
            page.check("#reg-missing", timeout=2500)
            page.wait_for_timeout(1800)
            page.fill("#reg-q", "panchayat", timeout=2500)
            page.wait_for_timeout(1800)
            page.click("#btn-reg-clear", timeout=2500)
        except Exception:
            pass
        page.wait_for_timeout(900)

    def own_feeds():
        page.click('button[data-view="intelligence"]')
        # The stages fetch the recording and its frame track before playing;
        # wait for real playback rather than a fixed sleep, so the beat never
        # films a still that is about to become a video.
        try:
            page.wait_for_function(
                """() => [...document.querySelectorAll('.intel-stage video')]
                         .some(v => !v.paused && v.currentTime > 0.5)""",
                timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(1500)

    def watchlist_hit():
        """Correlation on fictional plates, and only on fictional plates.

        The own feed is real footage of real vehicles. Putting one of them on a
        "stolen" watchlist to make a demonstration fire would show a real owner
        as a suspect. The watchlist hit is therefore shown on the synthetic
        corpus, whose plates belong to nobody, and the narration says so.
        """
        page.click('button[data-view="alerts"]')
        page.wait_for_timeout(2500)

    def trace_report(report_plate: str = "GJ18JX7786"):
        """Open the printable trace report for the vehicle the alert named.

        The alert is on a fictional plate, which is also the one with a route
        across cameras; the plate read off our own footage was read once and
        has no route to print. The report opens in place, from the alert card,
        and is scrolled so the legs, the reads and the signature block are on
        screen long enough to read.
        """
        def go():
            card = page.locator(".incident", has_text=report_plate).first
            try:
                card.locator("button", has_text="Trace report").click(timeout=4000)
            except Exception:
                page.click("#btn-trace-report", timeout=3000)
            page.wait_for_function(
                "() => (document.querySelector('#report-frame')?.srcdoc || '').length > 1000",
                timeout=10000)
            page.wait_for_timeout(2600)
            # Scrolled from the parent: the report frame runs no script of its
            # own (it is sandboxed without allow-scripts), but it is same-origin.
            for y in (520, 1040, 1700, 2600):
                page.evaluate("y => document.querySelector('#report-frame')"
                              ".contentWindow.scrollTo({top: y, behavior: 'smooth'})", y)
                page.wait_for_timeout(1700)
        return go

    def bind_purpose():
        """Purpose binding is a gate, not decoration.

        A vehicle search is refused outright without a case identifier and a
        stated reason, both of which are written into the audit record. The
        first take of this recording typed a plate, pressed Enter, and filmed
        `PURPOSE_REQUIRED` in red with an empty trajectory — the control
        working exactly as designed, and the demonstration failing because of
        it. Fill them the way an officer must.
        """
        for sel, value in (("#case-id", case_id), ("#purpose", purpose)):
            try:
                page.fill(sel, value, timeout=4000)
            except Exception:
                continue
        page.wait_for_timeout(600)

    def search_plate():
        page.click('button[data-view="investigate"]')
        page.wait_for_timeout(1800)
        bind_purpose()
        for sel in ('#q-plate', '#q', 'input[name="q"]', '.search input'):
            try:
                page.fill(sel, plate, timeout=2500)
                page.press(sel, "Enter")
                break
            except Exception:
                continue
        page.wait_for_timeout(4000)

    return [
        # The estate administrator onboards; the investigating officer
        # investigates. Filming the handover is not ceremony: it is the role
        # separation the bonus criteria ask about, shown rather than asserted.
        Beat("Signed in as the estate administrator", 3, use_token(admin_token),
             say="The estate administrator signs in. Registering cameras is "
                 "their job. Searching for vehicles is not."),
        Beat("Onboarding — a camera added through the registry portal", 14, onboard,
             say="A department's camera is onboarded through the registry "
                 "portal. The form validates first, and writes nothing. Then it "
                 "commits. Only the camera id is required."),
        Beat("What the registry does not know", 9, registry_gaps,
             say="The gap report moves as the camera lands. The two fields "
                 "supplied leave the missing list. The three not supplied stay "
                 "named, so a department knows what to send."),
        Beat("Handing over to the investigating officer", 3,
             use_token(investigator_token),
             say="The investigating officer takes over."),
        Beat("Own feeds, with AI detection drawn on them", 22, own_feeds,
             say="Our own feed is licensed footage of Mumbai traffic, filmed "
                 "from a foot-over-bridge and playing at thirty frames a second. "
                 "Every box is this platform's own pipeline, on that exact frame. "
                 "A number plate appears only once the pipeline's vote accepts "
                 "it. Faces are blurred."),
        Beat("What the analytics produced", 10, nav("analytics", 2.5),
             say="Detections become counts and read rates, measured from the "
                 "store rather than declared."),
        Beat("The mark, traced across the estate", 15, search_plate,
             say="A plate read off that footage, agreed across hundreds of frames, "
                 "is now searchable. Every search carries a case number and a "
                 "stated purpose, or it does not run."),
        Beat("Watchlist match, and the alert it fired", 16, watchlist_hit,
             say="Watchlist correlation is shown on fictional plates. We do not "
                 "put a real person's vehicle on a watchlist for a "
                 "demonstration. The alert sets the read beside the listed "
                 "plate, character by character."),
        Beat("A trace report an officer can sign", 11, trace_report(),
             say="From the alert, the route becomes a report an officer can "
                 "print and sign. Every read, each leg timed, and a digest "
                 "over the rows."),
        Beat("Evidence, sealed and hash-chained", 9, nav("evidence", 2.0),
             say="Evidence is sealed with a hash chain."),
        Beat("Every query attributed", 9, nav("audit", 2.0),
             say="And every query is attributed: who searched, for which "
                 "vehicle, when, and why."),
    ]

#: Allowance per beat for the clicks and loads the action itself takes, used to
#: project the take's length before recording rather than discover it after.
ACTION_ALLOWANCE_S = 2.5


def narrate(beats: list[Beat], work: Path, voice: str) -> float:
    """Synthesise every beat's line and project the take's length.

    Refuses a take that cannot fit: finding out at 3m04s that a recording is
    over the limit costs a whole take, and the government grid's session
    budget with it on the other film.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import narration

    if not narration.available():
        raise SystemExit("narration needs macOS `say`, ffmpeg and ffprobe")
    projected = 0.0
    for i, b in enumerate(beats):
        if b.say:
            b.audio = work / f"line_{i:02d}.wav"
            b.say_s = narration.synth(b.say, b.audio, voice=voice)
        projected += max(b.dwell_s + ACTION_ALLOWANCE_S, b.say_s + 0.6)
    if projected > HARD_LIMIT_S - 5:
        raise SystemExit(
            f"the narrated take projects to {projected:.0f}s against a "
            f"{HARD_LIMIT_S:.0f}s limit; shorten a line before recording")
    return projected


def finish_narrated(beats: list[Beat], silent: Path, out: Path, work: Path,
                    offset_s: float) -> None:
    """Lay each line at its beat's recorded start and burn the captions in."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import narration

    total = narration.probe_duration(silent)
    lines, chapters = [], []
    for i, b in enumerate(beats):
        start = max(0.0, b.at - offset_s)
        if b.audio:
            lines.append(narration.Line(start, b.say, b.audio, b.say_s))
        nxt = (beats[i + 1].at - offset_s) if i + 1 < len(beats) else total
        chapters.append((start, min(start + 3.2, nxt), b.title))
    track = narration.build_track(lines, total, work / "narration.wav")
    ass = narration.write_ass(lines, work / "captions.ass",
                              width=VIEW_W, height=VIEW_H, chapter=chapters)
    narration.finish(silent, track, ass, out)


def record(base: str, token: str, plate: str, out_dir: Path,
           admin_token: str = "", voice: str | None = "Aman") -> list[Beat]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:                                # pragma: no cover
        raise SystemExit("needs Playwright:  pip install -e '.[demo]'") from None

    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": VIEW_W, "height": VIEW_H})
        page = ctx.new_page()
        page.goto(f"{base}/ui/", wait_until="domcontentloaded")
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        try:
            page.wait_for_selector('button[data-view="live"]',
                                   state="visible", timeout=20000)
        except Exception:
            ctx.close()
            browser.close()
            raise SystemExit(
                "the workspace did not open — the token is expired or refused. "
                "Mint one:\n  python tools/admin/users.py "
                "--db sqlite:///var/live.db token --user supervisor.live --days 7")

        beats = build(page, plate, admin_token=admin_token,
                      investigator_token=token)
        mp4 = Path(str(out_dir) + ".mp4")
        work = out_dir / "narration"
        if voice:
            projected = narrate(beats, work, voice)
            print(f"  narration synthesised; take projects to {projected:.0f}s")
        silent = Path(str(out_dir) + "_silent.mp4") if voice else mp4
        with Screencast(page, out_dir / "frames", width=VIEW_W,
                        height=VIEW_H, quality=98) as cast:
            t0 = time.time()
            wall0 = t0
            for b in beats:
                b.at = time.time() - t0
                print(f"  {int(b.at)//60}:{int(b.at) % 60:02d}  {b.title}",
                      flush=True)
                try:
                    b.action()
                except Exception as exc:
                    b.ok, b.err = False, f"{type(exc).__name__}: {exc}"[:120]
                # Hold for the planned dwell, or until the narrator finishes
                # this beat's line, whichever is later.
                spent = time.time() - t0 - b.at
                hold = max(b.dwell_s, b.say_s + 0.6 - spent)
                page.wait_for_timeout(int(max(0.0, hold) * 1000))
        res = cast.write(silent, crf=15, fps=30)
        first = cast.first_timestamp()
        cast.cleanup()
        if voice and res.get("ok"):
            offset = (first - wall0) if first else 0.0
            finish_narrated(beats, silent, mp4, work, offset)
            print(f"  narrated and captioned -> {mp4} "
                  f"(first frame {offset:+.2f}s after start)")
        if not res.get("ok"):
            print(f"  capture FAILED: {res.get('why')}")
        else:
            print(f"  captured {res['frames']} frames at "
                  f"{res['captured_fps']} fps -> {res['mb']} MB")

        ctx.close()
        browser.close()
        return beats


def duration_s(mp4: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(mp4)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8083")
    ap.add_argument("--token")
    ap.add_argument("--token-file")
    ap.add_argument("--voice", default="Aman",
                    help="macOS voice for the narration; 'none' records silently")
    ap.add_argument("--admin-token-file",
                    help="ADMIN token. Onboarding needs admin:write, which "
                         "SUPERVISOR does not hold; without this the "
                         "onboarding beat films a refusal.")
    ap.add_argument("--plate", default="MH02GB4920")
    ap.add_argument("--out", default="var/demo/own_feed")
    a = ap.parse_args()

    if a.token_file:
        token = Path(a.token_file).read_text(encoding="ascii").strip()
    elif a.token:
        token = a.token
    else:
        raise SystemExit("need --token-file or --token")

    admin_token = ""
    if a.admin_token_file:
        admin_token = Path(a.admin_token_file).read_text(encoding="ascii").strip()
    else:
        print("  no --admin-token-file: the onboarding beat will film a "
              "PERMISSION_DENIED refusal, because SUPERVISOR does not hold "
              "admin:write.")

    out_dir = Path(a.out)
    mp4 = Path(str(out_dir) + ".mp4")
    print(f"recording the own-feed demonstration -> {mp4}")
    beats = record(a.base, token, a.plate, out_dir, admin_token=admin_token,
                   voice=None if a.voice.lower() == "none" else a.voice)
    ok = mp4.exists()

    print()
    failed = [b for b in beats if not b.ok]
    print(f"beats  : {len(beats) - len(failed)}/{len(beats)} driven cleanly")
    for b in failed:
        print(f"  could not drive: {b.title}: {b.err}")
    if ok:
        secs = duration_s(mp4)
        if secs is not None:
            print(f"length : {int(secs)//60}m{int(secs) % 60:02d}s "
                  f"(limit {int(HARD_LIMIT_S)//60}m{int(HARD_LIMIT_S) % 60:02d}s)")
            if secs > HARD_LIMIT_S:
                raise SystemExit(
                    f"the recording is {secs - HARD_LIMIT_S:.0f}s over the "
                    "challenge's three-minute limit. Shorten a beat rather "
                    "than submitting something that will be cut off.")
    print(f"video  : {mp4 if ok else out_dir}")


if __name__ == "__main__":
    main()
