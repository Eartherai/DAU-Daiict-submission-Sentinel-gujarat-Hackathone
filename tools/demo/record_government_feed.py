"""The government-feed demonstration, and the report that must accompany it.

Submission item 4 asks for four things on the Government-provided feed:

  1. onboard the feed(s) onto the platform;
  2. demonstrate successful onboarding and live or recorded viewing;
  3. demonstrate the available video-analytics output;
  4. submit a screen-recorded video **along with an output report showing
     detected vehicles or number plates with corresponding timestamps**.

The fourth is the one most easily missed, because a recording feels like the
deliverable. It is not: a video cannot be grepped, sorted or checked against a
case file. This script emits both, from the same run and the same store, so the
plates on screen and the plates in the report cannot disagree.

    python tools/demo/record_government_feed.py \
        --base http://127.0.0.1:8083 --token-file /path/to/token.raw

The government plane is real Sentinel video over direct WHEP. The wall needs
time to negotiate its sessions, so the viewing beats wait for frames to be
decoding rather than assuming they are — an empty wall filmed confidently is
worse than one that is honest about connecting.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
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


@dataclass
class Beat:
    title: str
    dwell_s: float
    action: Callable[[], None] = lambda: None
    #: The narrator's line. Its measured length can extend the beat, never
    #: shorten it, so the voice always finishes over its own screen.
    say: str = ""
    ok: bool = True
    err: str = ""
    at: float = field(default=0.0)
    say_s: float = 0.0
    audio: Path | None = None


def build(page, plate: str, admin_token: str = "", officer_token: str = "") -> list[Beat]:
    """Every capability, on the government store and the live grid.

    The first cut of this film was ten silent beats. The challenge leaves the
    government demonstration without a length limit, so this one shows the
    whole platform on the organisers' own cameras - registry and onboarding,
    GIS, live viewing, detection, the designated-vehicle trace and its report,
    alerts, evidence, the copilot over each model, role separation and the
    audit trail - and says what each screen is while it is on it.
    """
    def use_token(token: str):
        def go():
            if not token:
                return
            page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
        return go

    def close_modals():
        if page.evaluate("!!document.querySelector('#report-dialog')?.open"):
            page.click("#report-close")
            page.wait_for_timeout(300)

    def nav(view: str, settle: float = 2.0):
        def go():
            close_modals()
            page.click(f'button[data-view="{view}"]')
            page.wait_for_timeout(int(settle * 1000))
        return go

    def onboarded():
        """The government cameras as the registry holds them."""
        close_modals()
        page.click('button[data-view="cameras"]')
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, -700)

    def bulk_validate():
        """Bulk onboarding, validated first: the dry run writes nothing."""
        page.click("#btn-onboard-toggle")
        page.wait_for_timeout(600)
        page.click('[data-onboard="bulk"]')
        page.wait_for_timeout(600)
        csv_path = Path(__file__).resolve().parents[2] / "reports" / "sample_camera_metadata.csv"
        try:
            text = csv_path.read_text(encoding="utf-8")
            page.fill("#ob-csv", "\n".join(text.splitlines()[:8]))
            page.wait_for_timeout(900)
            page.click("#btn-ob-bulk-dry")
        except Exception:
            pass
        page.wait_for_timeout(3000)

    def gaps_and_copilot():
        """Model 1 gap report, then the copilot asked about it from the screen."""
        try:
            page.click("#btn-onboard-toggle")
        except Exception:
            pass
        page.wait_for_timeout(600)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(2500)
        _ask(lambda: page.click('button[data-ask-model="m1"]'))

    def _answers() -> int:
        return page.evaluate(
            "() => document.querySelectorAll('#chat-log .msg.bot:not(.dim)').length")

    def _ask(click, timeout_ms: int = 90000):
        """Click, then wait for a new answer - not the 'working' placeholder."""
        before = _answers()
        click()
        try:
            page.wait_for_function(
                "n => document.querySelectorAll('#chat-log .msg.bot:not(.dim)').length > n",
                arg=before, timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(1500)

    def estate_map():
        close_modals()
        page.click('button[data-view="map"]')
        page.wait_for_timeout(5000)

    def live_wall():
        page.click('button[data-view="live"]')
        page.wait_for_selector("#live .live-tile", timeout=60000)
        # Wait for real decoded frames, not merely attached elements, and for
        # every visible tile to show something; if the grid cannot get there,
        # film it as it is rather than waiting for ever.
        ready = """() => {
          const vs=[...document.querySelectorAll('#live-grid video')];
          const decoding=vs.filter(v=>v.readyState>=2&&v.videoWidth>16).length;
          const g=document.getElementById('live-grid');
          const vh=innerHeight;
          const vis=g?[...g.children].filter(t=>{const r=t.getBoundingClientRect();
            return r.bottom>0&&r.top<vh&&r.width>8;}):[];
          const shown=vis.filter(t=>{
            const v=t.querySelector('video');
            const i=t.querySelector('.frame img');
            return (v&&v.videoWidth>16) ||
                   (i&&i.getAttribute('src')&&i.style.display!=='none');
          }).length;
          return decoding>=8 && shown===vis.length;
        }"""
        try:
            page.wait_for_function(ready, timeout=110000)
        except Exception:
            pass

    def wall_size(n: int):
        def go():
            try:
                page.click(f'[data-live-wall="{n}"]', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(6000)
        return go

    def focus_camera():
        """One camera, full quality, with the analytics overlay drawn on it."""
        try:
            page.click('[data-live-wall="12"]', timeout=6000)
            page.wait_for_timeout(3000)
            page.click("#live-grid .live-tile >> nth=0", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(9000)

    def trace():
        close_modals()
        page.click('button[data-view="investigate"]')
        page.wait_for_timeout(2000)
        # A search is refused without a case and a stated purpose, and both
        # are written into the audit log with the search.
        for sel, value in (("#case-id", "FIR-000/2026"),
                           ("#purpose", "tracing a designated vehicle")):
            try:
                page.fill(sel, value, timeout=4000)
            except Exception:
                continue
        page.wait_for_timeout(600)
        page.fill("#q-plate", plate, timeout=4000)
        page.press("#q-plate", "Enter")
        page.wait_for_timeout(6000)

    def follow_and_next():
        """Where the vehicle could have gone next, and why."""
        for sel in ('button:has-text("Follow vehicle")', 'button:has-text("Where to look next")'):
            try:
                page.click(sel, timeout=3000)
                page.wait_for_timeout(4500)
            except Exception:
                continue

    def trace_report():
        try:
            page.click("#btn-trace-report", timeout=5000)
            page.wait_for_function(
                "() => (document.querySelector('#report-frame')?.srcdoc || '').length > 1000",
                timeout=15000)
        except Exception:
            return
        page.wait_for_timeout(2200)
        for y in (500, 1100, 1900):
            page.evaluate("y => document.querySelector('#report-frame')"
                          ".contentWindow.scrollTo({top: y, behavior: 'smooth'})", y)
            page.wait_for_timeout(1600)

    def copilot_model(model: str):
        def go():
            close_modals()
            page.click('button[data-view="copilot"]')
            page.wait_for_timeout(1500)
            _ask(lambda: page.click(f'#prompt-chips button:has-text("{model.upper()} ·")',
                                    timeout=4000))
        return go

    def copilot_refuse():
        close_modals()
        page.click('button[data-view="copilot"]')
        page.wait_for_timeout(800)
        _ask(lambda: page.click('#prompt-chips button:has-text("Enhance a still")',
                                timeout=4000))

    def system_view():
        close_modals()
        page.click('button[data-view="system"]')
        page.wait_for_timeout(4000)
        for _ in range(3):
            page.mouse.wheel(0, 650)
            page.wait_for_timeout(1500)

    def admin_refused():
        """Role separation, shown: the administrator may not search plates."""
        page.click('button[data-view="investigate"]')
        page.wait_for_timeout(1500)
        for sel, value in (("#case-id", "FIR-000/2026"),
                           ("#purpose", "checking the registry")):
            try:
                page.fill(sel, value, timeout=3000)
            except Exception:
                continue
        page.fill("#q-plate", plate, timeout=4000)
        page.press("#q-plate", "Enter")
        page.wait_for_timeout(3500)

    return [
        Beat("The government grid, signed in as the estate administrator", 3,
             use_token(admin_token),
             say="This is the government grid: the organisers' cameras from five "
                 "departments, replayed as live by their streaming middleware. The "
                 "estate administrator signs in first."),
        Beat("Model 1 — every camera onboarded, and graded", 12, onboarded,
             say="Every government camera sits in one registry: department, codec, "
                 "resolution and location. Capability is measured from each "
                 "camera's own stream. Where a view cannot read plates, the "
                 "registry says so, instead of promising it."),
        Beat("Bulk onboarding, validated before it writes", 10, bulk_validate,
             say="A department onboards in bulk from its own spreadsheet. "
                 "Validation runs first and writes nothing. Cameras already on the "
                 "registry are reported, not duplicated."),
        Beat("What the registry does not know — asked of Gemini", 14, gaps_and_copilot,
             say="The gap report names what no department has supplied yet. The "
                 "Gemini copilot sits over the registry as well: asked from this "
                 "screen, it answers from the gap analysis, and every figure is "
                 "checked against it before it is shown."),
        Beat("GIS — the estate on the map", 10, estate_map,
             say="On the map, each camera is coloured by measured health, and "
                 "cameras without a surveyed position are listed, never placed "
                 "where they are not."),
        Beat("Role separation: the administrator may not search vehicles", 6,
             admin_refused,
             say="Running the estate and searching for people are different jobs. "
                 "Asked for a vehicle, the administrator is refused, in plain "
                 "words, and the refusal is audited."),
        Beat("Handing over to the investigating officer", 3, use_token(officer_token),
             say="The investigating officer takes over."),
        Beat("Model 2 — live viewing over direct WebRTC", 22, live_wall,
             say="Live viewing is direct WebRTC from the grid, twelve sessions at "
                 "a time. Video is not re-recorded centrally; the detection "
                 "overlay is drawn beside it, from metadata."),
        Beat("Thirty cameras on one wall", 14, wall_size(30),
             say="Thirty cameras on one wall. Tiles beyond the live budget show "
                 "the last analysed still, and say so."),
        Beat("One camera, with the AI overlay", 16, focus_camera,
             say="One camera, at full quality, with vehicles, people and plates "
                 "from this platform's own detector drawn on the frame."),
        Beat("What the analytics produced", 14, nav("analytics", 3.0),
             say="Everything the pipeline produced on these cameras, counted from "
                 "the store: marks read, vehicles and people by class, and each "
                 "camera's measured plate-reading grade."),
        Beat("Every mark read, with camera and time", 12, nav("overview", 3.0),
             say="Every registration mark read, with its camera and time, is on "
                 "the overview, and in the ANPR report that ships beside this film."),
        Beat("The designated vehicle, traced", 18, trace,
             say="Given a designated vehicle, the search runs under a case number "
                 "and a stated purpose. The card says first whether the vehicle is "
                 "wanted. Then every read, its time, its camera, and the route."),
        Beat("Where it could have gone next", 12, follow_and_next,
             say="The platform ranks where to look next, from travel times and each "
                 "camera's ability to read a plate, and rejects any transition a "
                 "vehicle could not have driven."),
        Beat("The trace, as a report an officer can sign", 12, trace_report,
             say="The trace becomes a page an officer can print and sign: every "
                 "read, each leg timed, and a digest over the rows."),
        Beat("Watchlist match, and the alert it fired", 14, nav("alerts", 3.0),
             say="Watchlist hits arrive as one decision per vehicle, with the read "
                 "set beside the listed plate, character by character, and a "
                 "single-frame read marked for verification."),
        Beat("Evidence, sealed and hash-chained", 10, nav("evidence", 3.0),
             say="Evidence is sealed as it is captured and chained by hash, so a "
                 "removed or altered record is detectable."),
        Beat("Model 4 — Gemini over the alert queue", 12, copilot_model("m4"),
             say="Asked about the alert queue, the copilot answers from it, and "
                 "withholds anything it cannot verify."),
        Beat("Model 2 — Gemini over camera health", 12, copilot_model("m2"),
             say="And about camera health, from what ingest last measured."),
        Beat("The copilot refuses to fabricate", 10, copilot_refuse,
             say="Asked to enhance a still, it refuses. That would be fabricating "
                 "evidence."),
        Beat("Model 3, health and roles — the system view", 14, system_view,
             say="The system view shows each subsystem's measured health, how "
                 "Gujarat's ranks map onto the platform's roles, and the VMS "
                 "systems the federation layer connects."),
        Beat("Every query attributed", 10, nav("audit", 3.0),
             say="And every query is attributed: who searched, for which vehicle, "
                 "when, and why, in a log whose entries are chained by hash."),
    ]


def fetch_report(base: str, token: str, out: Path, limit: int = 1000) -> dict:
    """The output report the submission must carry beside the video."""
    req = urllib.request.Request(
        f"{base}/reports/anpr.csv?limit={limit}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "why": f"HTTP {exc.code}"}
    except Exception as exc:                            # pragma: no cover
        return {"ok": False, "why": type(exc).__name__}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(body)))
    plates = {r.get("plate") for r in rows if r.get("plate")}
    cams = {r.get("camera_id") for r in rows if r.get("camera_id")}
    return {"ok": True, "rows": len(rows), "plates": len(plates),
            "cameras": len(cams)}


def prewarm_stills(base: str, token: str, cameras: int = 14) -> dict:
    """Ask the server for a still per wall camera before the wall opens.

    Four tiles filmed as black `CONNECTING` boxes in the last take. They were
    not failing: a tile shows that placeholder when it has neither a decoded
    WHEP frame nor a cached still, and those cameras' snapshots were being
    refused (287 of them, 503, in the server log) while the wall was being
    recorded. A capture on this estate takes one to ten seconds, so a tile
    asked for the first time during a recording is very likely to be filmed
    before it answers.

    Warming the server's own cache first is not staging: the same endpoint
    serves the same frame, just sooner. A camera that genuinely cannot produce
    a still still shows as connecting, which is the honest outcome.
    """
    import concurrent.futures as cf

    try:
        req = urllib.request.Request(
            f"{base}/gis/cameras?zoom=16",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "why": type(exc).__name__}

    ids = [c.get("camera_id") for c in
           (body.get("features") or []) + (body.get("unlocated") or [])
           if c.get("camera_id") and not str(c["camera_id"]).startswith("CTL-")]
    ids = ids[:cameras]

    def warm(cid: str) -> bool:
        try:
            rq = urllib.request.Request(
                f"{base}/cameras/{cid}/snapshot",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(rq, timeout=45) as rs:
                return rs.status == 200
        except Exception:
            return False

    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        got = sum(1 for ok in pool.map(warm, ids) if ok)
    return {"ok": True, "asked": len(ids), "warmed": got}


def narrate(beats: list[Beat], work: Path, voice: str) -> float:
    """Synthesise every line first; its length sets the beat's dwell."""
    import narration

    if not narration.available():
        raise SystemExit("narration needs macOS `say`, ffmpeg and ffprobe")
    projected = 0.0
    for i, b in enumerate(beats):
        if b.say:
            b.audio = work / f"line_{i:02d}.wav"
            b.say_s = narration.synth(b.say, b.audio, voice=voice)
        projected += max(b.dwell_s + 2.5, b.say_s + 0.6)
    return projected


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
        ctx = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H})
        page = ctx.new_page()
        page.goto(f"{base}/ui/", wait_until="domcontentloaded")
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)",
                      admin_token or token)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        try:
            page.wait_for_selector('button[data-view="live"]', state="visible", timeout=20000)
        except Exception:
            ctx.close()
            browser.close()
            raise SystemExit(
                "the workspace did not open — the token is expired or refused.\n"
                "  python tools/admin/users.py --db sqlite:///var/live.db "
                "token --user supervisor.live --days 7")

        beats = build(page, plate, admin_token=admin_token, officer_token=token)
        mp4 = Path(str(out_dir) + ".mp4")
        work = out_dir / "narration"
        work.mkdir(parents=True, exist_ok=True)
        if voice:
            projected = narrate(beats, work, voice)
            print(f"  narration synthesised; take projects to {projected / 60:.1f} min")
        silent = Path(str(out_dir) + "_silent.mp4") if voice else mp4
        with Screencast(page, out_dir / "frames", width=VIEW_W,
                        height=VIEW_H, quality=98) as cast:
            t0 = time.time()
            for b in beats:
                b.at = time.time() - t0
                print(f"  {int(b.at)//60}:{int(b.at) % 60:02d}  {b.title}", flush=True)
                started = time.time()
                try:
                    b.action()
                except Exception as exc:
                    b.ok, b.err = False, f"{type(exc).__name__}: {exc}"[:120]
                spent = time.time() - started
                hold = max(b.dwell_s, b.say_s + 0.6 - spent)
                page.wait_for_timeout(int(max(0.0, hold) * 1000))
            first = cast.first_timestamp()
            offset = (first - t0) if first else 0.0
        res = cast.write(silent, crf=15, fps=30)
        cast.cleanup()
        if not res.get("ok"):
            print(f"  capture FAILED: {res.get('why')}")
        else:
            print(f"  captured {res['frames']} frames at "
                  f"{res['captured_fps']} fps -> {res['mb']} MB")
            if voice:
                _finish_narrated(beats, silent, mp4, work, max(0.0, offset or 0.0))
                print(f"  narrated and captioned -> {mp4}")
        ctx.close()
        browser.close()
        return beats


def _finish_narrated(beats: list[Beat], silent: Path, out: Path, work: Path,
                     offset_s: float) -> None:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8083")
    ap.add_argument("--token")
    ap.add_argument("--token-file")
    ap.add_argument("--plate", default="GJ11S7924")
    ap.add_argument("--out", default="var/demo/government_feed")
    ap.add_argument("--admin-token-file",
                    help="the estate administrator's token, for the onboarding beats")
    ap.add_argument("--voice", default="Aman", help="macOS voice; 'none' records silently")
    a = ap.parse_args()

    if a.token_file:
        token = Path(a.token_file).read_text(encoding="ascii").strip()
    elif a.token:
        token = a.token
    else:
        raise SystemExit("need --token-file or --token")

    out_dir = Path(a.out)
    mp4 = Path(str(out_dir) + ".mp4")
    report = Path(str(out_dir) + "_anpr_report.csv")

    print(f"recording the government-feed demonstration -> {mp4}")
    warm = prewarm_stills(a.base, token)
    print(f"  pre-warmed stills: {warm.get('warmed')}/{warm.get('asked')}"
          if warm.get("ok") else f"  pre-warm skipped ({warm.get('why')})")
    admin = Path(a.admin_token_file).read_text(encoding="ascii").strip() \
        if a.admin_token_file else ""
    beats = record(a.base, token, a.plate, out_dir, admin_token=admin,
                   voice=None if a.voice.lower() == "none" else a.voice)
    ok = mp4.exists()

    # The report is half the deliverable, so fetch it from the same store the
    # recording just showed rather than from an earlier run.
    rep = fetch_report(a.base, token, report)

    print()
    failed = [b for b in beats if not b.ok]
    print(f"beats  : {len(beats) - len(failed)}/{len(beats)} driven cleanly")
    for b in failed:
        print(f"  could not drive: {b.title}: {b.err}")
    print(f"video  : {mp4 if ok else out_dir}")
    if rep.get("ok"):
        print(f"report : {report} — {rep['rows']} rows, "
              f"{rep['plates']} distinct plates, {rep['cameras']} cameras")
    else:
        print(f"report : NOT WRITTEN ({rep.get('why')}). The submission needs "
              "the report as well as the video.")


if __name__ == "__main__":
    main()
