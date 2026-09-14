"""Record a walkthrough of the platform itself, from the running interface.

The other two demonstration videos show what the analytics produced — boxes and
registration marks drawn on the frames they came from. Neither shows the thing
an officer actually uses. This drives the real interface in a real browser
against a real server, screenshots each step, and renders the result as video.

Nothing is mocked and no screen is staged: every frame is Chrome displaying the
served page. If a panel is empty here, it is empty in the product.

    pip install -e '.[demo]'          # Playwright; uses the system Chrome
    python tools/demo/record_walkthrough.py --base http://127.0.0.1:8003 \
        --token-file /tmp/saakshya-live-token.raw --live \
        --out var/demo/walkthrough_live

The token is read from a file or the command line and never written to disk
by this tool. Mint a short-lived one for the recording and revoke it afterwards.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

from render_demo_video import (
    FPS,
    INK,
    INK_2,
    MONO,
    NAVY,
    NAVY_2,
    SANS,
    SANS_B,
    SEAL,
    _text,
    card,
    display,
    encode,
)

W, H = 1920, 1080
VIEW_W, VIEW_H = 1920, 1080

#: How long each step holds on screen. Long enough to read the caption, which
#: is the whole reason the step is in the film.
HOLD_S = 7.5
CAPTION_H = 96


@dataclass
class Step:
    """One thing the interface is asked to do, and why it is worth showing."""

    title: str
    caption: str
    #: Drives the interface for this step. May raise, and a step that raises is
    #: reported rather than silently skipped — a film missing a screen with no
    #: explanation is worse than one that says which screen is missing.
    action: Callable[[], None]
    hold_s: float = HOLD_S
    note: str = ""


@dataclass
class Shot:
    png: Path
    step: Step
    ok: bool = True
    error: str = ""


@dataclass
class Recording:
    shots: list[Shot] = field(default_factory=list)

    @property
    def failed(self) -> list[Shot]:
        return [s for s in self.shots if not s.ok]


def compose(shot: Shot) -> Image.Image:
    """One frame: the interface, with the caption that says why it matters."""
    src = Image.open(shot.png).convert("RGB")
    inner_h = H - CAPTION_H
    scale = min(W / src.width, inner_h / src.height)
    vw, vh = int(src.width * scale), int(src.height * scale)
    canvas = Image.new("RGB", (W, H), NAVY)
    canvas.paste(src.resize((vw, vh), Image.Resampling.LANCZOS),
                 ((W - vw) // 2, (inner_h - vh) // 2))

    d = ImageDraw.Draw(canvas)
    y0 = H - CAPTION_H
    d.rectangle([0, y0, W, H], fill=NAVY_2)
    d.line([(0, y0), (W, y0)], fill=(30, 65, 102), width=1)
    d.rectangle([28, y0 + 20, 31, y0 + 68], fill=SEAL)

    d.text((46, y0 + 17), shot.step.title, font=SANS_B(19), fill=INK)
    # Caption wraps to two lines at most; anything longer is a caption that has
    # stopped explaining and started narrating.
    words, lines, cur = shot.step.caption.split(), [], ""
    for wd in words:
        trial = f"{cur} {wd}".strip()
        if d.textlength(trial, font=SANS(14)) > W - 380:
            lines.append(cur)
            cur = wd
        else:
            cur = trial
    lines.append(cur)
    for i, ln in enumerate(lines[:2]):
        d.text((46, y0 + 44 + i * 20), ln, font=SANS(14), fill=INK_2)

    if shot.step.note:
        nw = int(d.textlength(shot.step.note, font=MONO(13)))
        d.text((W - nw - 28, y0 + 44), shot.step.note, font=MONO(13), fill=SEAL)
    _text(d, (W - 190, y0 + 20), "OFFICIAL · SENSITIVE", SANS_B(9), SEAL,
          spacing=1.4)
    return canvas


def steps(page, plate: str, case_id: str) -> list[Step]:
    """The walkthrough, in the order the work actually happens."""

    def nav(view: str):
        def go():
            page.click(f'button[data-view="{view}"]')
            page.wait_for_timeout(1800)
        return go

    def nav_overview():
        page.click('button[data-view="overview"]')
        page.wait_for_function(
            "() => /shift picture/i.test(document.body.innerText)"
            + " && /[\\d,]+\\s+observations/.test(document.body.innerText)"
            + " && document.querySelectorAll('.health-row').length >= 1",
            timeout=45000)
        page.wait_for_timeout(800)

    def bind_and_search():
        page.click('button[data-view="investigate"]')
        page.wait_for_timeout(600)
        page.fill("#case-id", case_id)
        page.fill("#purpose", "tracing a vehicle reported stolen")
        page.fill("#q-plate", plate)
        page.wait_for_timeout(400)
        page.click("#search-form button[type=submit]")
        page.wait_for_timeout(2600)

    def open_first_result():
        page.click("#results .result")
        page.wait_for_timeout(2200)

    def nav_cameras():
        page.click('button[data-view="cameras"]')
        page.wait_for_function(
            "() => /published a mark/.test(document.body.innerText)",
            timeout=20000)
        page.wait_for_timeout(800)

    def nav_analytics():
        page.click('button[data-view="analytics"]')
        # Yield and timebase used to stay blank while /overview ran. Wait
        # for both, not just the capability column that paints first.
        page.wait_for_function(
            "() => /distinct marks/.test(document.body.innerText)"
            + " && (/GRID-/.test(document.body.innerText)"
            + "     || /No cluster established/.test(document.body.innerText))",
            timeout=20000)
        page.wait_for_timeout(800)

    def open_live_and_wait():
        page.click('button[data-view="live"]')
        # Isolated Live paints 30 tiles in <20 s. After Overview+Analytics+Map
        # the same call can wait on SQLite. Wait for tiles only; chips travel
        # with them. Stills may badge later.
        page.wait_for_selector("#live .live-tile", timeout=90000)
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('#live .live-tile .badge').length >= 4"
                + " && /plates in store/i.test(document.body.innerText)",
                timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(1500)

    def open_map():
        page.click('button[data-view="map"]')
        page.wait_for_timeout(2800)

    def open_copilot():
        page.click('button[data-view="copilot"]')
        page.wait_for_timeout(2200)

    def open_evidence():
        page.click('button[data-view="evidence"]')
        page.wait_for_timeout(2600)

    def open_case():
        page.click('button[data-view="cases"]')
        page.wait_for_timeout(1600)
        # The first row in the case list, not a text match: the case identifier
        # also appears in the masthead's purpose-binding field, so `text=` is
        # ambiguous and matched a control rather than the record.
        page.click("#case-list .result")
        page.wait_for_timeout(1800)

    return [
        Step("Overview — where a shift starts",
             "The shift picture first: what is on fire, which cameras published "
             "a mark, and whether ANPR GOOD is being confused with emptiness.",
             nav_overview, note="one screen"),
        Step("Purpose binding is standing furniture",
             "A case and a stated reason are entered before the search runs. "
             "Both are written into every audit record it produces.",
             bind_and_search, hold_s=6.0, note=f"target {plate}"),
        Step("Find — what matched, and how sure",
             "Every candidate carries the basis of its match. A fuzzy result is "
             "labelled as requiring verification, never as a match.",
             open_first_result, hold_s=6.0),
        Step("Trace — a route, with its uncertainty attached",
             "Legs are typed OBSERVED or INFERRED, and the timebase panel says "
             "when two cameras cannot be placed on one timeline.",
             lambda: page.wait_for_timeout(1200), hold_s=6.0),
        Step("Cameras — capability measured, never declared",
             "ANPR UNSUITABLE is yield, not emptiness. Cameras that published "
             "a mark show it beside the grade.",
             nav_cameras, note="six dimensions"),
        Step("Analytics — what the estate can actually do",
             "Plate yield is a property of geometry and light, not traffic "
             "volume. A busy junction with forty-pixel plates reads none.",
             nav_analytics),
        Step("Estate map — nineteen placed, eleven listed",
             "Positions come from names with stated precision. Cameras whose "
             "names are not enough stay off the map, in the registry strip.",
             open_map, hold_s=7.0, note="19 + 11"),
        Step("Live — real government cameras, and honest about itself",
             "Thirty ingest stills, not a second RTSP copy. Tiles that "
             "published a mark chip it next to the ANPR grade.",
             open_live_and_wait, hold_s=8.0, note="ingest stills"),
        Step("Alerts — matched, and worth a person's time",
             "A watchlist hit carries its category, priority and the confidence "
             "it matched at, so an officer can triage before opening it.",
             nav("alerts")),
        Step("The case file — what an officer hands on",
             "Targets attached with who attached them and when, notes, and the "
             "audit trail behind every one.",
             open_case, hold_s=8.0),
        Step("Evidence — integrity and truthfulness, reported apart",
             "The chain verifies. A record whose own wording overstates what it "
             "holds raises a caution without failing the chain.",
             open_evidence, hold_s=6.5),
        Step("Audit — every query, attributed",
             "Actor, role, case and purpose, hash-chained and append-only. A "
             "refusal is recorded as carefully as a result.",
             nav("audit")),
        Step("Copilot — last, and optional",
             "Sixteen read-only tools over the same facade. It is not in the "
             "mandatory chain. Ask it after the deterministic work, not before.",
             open_copilot, hold_s=6.5, note="not the chain"),
    ]


def record(base: str, token: str, plate: str, case_id: str,
           shots_dir: Path) -> Recording:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:                                # pragma: no cover
        raise SystemExit(
            "This recorder drives a real browser and needs Playwright, which is "
            "an optional extra rather than a runtime dependency — the platform "
            "itself must install and run on a machine with no browser at all.\n"
            "  pip install -e '.[demo]'\n"
            "It uses the system Chrome, so no browser download is required."
        ) from None

    rec = Recording()
    shots_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": VIEW_W, "height": VIEW_H},
            device_scale_factor=2)
        page.goto(f"{base}/ui/?v=cr069", wait_until="domcontentloaded")
        # The interface reads its token from session storage, the same place
        # the sign-in dialog puts it. Nothing here bypasses authentication:
        # this is a real token, and every request it makes is audited.
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        for i, st in enumerate(steps(page, plate, case_id)):
            png = shots_dir / f"{i:02d}.png"
            ok, err = True, ""
            try:
                st.action()
            except Exception as exc:
                ok, err = False, f"{type(exc).__name__}: {exc}"[:120]
            page.wait_for_timeout(700)
            page.screenshot(path=str(png))
            rec.shots.append(Shot(png=png, step=st, ok=ok, error=err))
            print(f"  {i:02d}  {st.title[:46]:<48} {'ok' if ok else err}")
        browser.close()
    return rec


def _token(args: argparse.Namespace) -> str:
    if args.token_file:
        raw = Path(args.token_file).read_bytes().strip().decode("ascii")
        if not raw:
            raise SystemExit(f"empty token file: {args.token_file}")
        return raw
    if args.token:
        return args.token
    raise SystemExit("need --token-file or --token")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8003")
    ap.add_argument("--token")
    ap.add_argument("--token-file",
                    help="read the bearer token from a file; never logged")
    ap.add_argument("--plate", default="GJ23ZK2060")
    ap.add_argument("--case", default="FIR-214/2026")
    ap.add_argument("--live", action="store_true",
                    help="captions name the government grid, not the demo store")
    ap.add_argument("--out", default="var/demo/platform_walkthrough")
    a = ap.parse_args()
    if a.live and a.plate == "GJ23ZK2060":
        a.plate = "GJ1VV0119"
    if a.live and a.case == "FIR-214/2026":
        a.case = "FIR-000/2026"
    token = _token(a)

    out = Path(a.out)
    print(f"recording the interface at {a.base} → {display(out)}.mp4")
    t0 = time.time()
    rec = record(a.base, token, a.plate, a.case, out.with_suffix(""))

    data_blurb = (
        "The live government grid. Thirty cameras, ingest stills,\n"
        "not a second RTSP wall. The handling strip names the source."
        if a.live else
        "The local demonstration store. The handling strip on\n"
        "every screen says which store is open.")
    frames: list[Image.Image] = [
        card([("WHAT THIS IS", "The interface itself, driven in a real browser\n"
                               "against a real server. Nothing is mocked and no\n"
                               "screen is staged."),
              ("DATA", data_blurb),
              ("", ""),
              ("THE WORK", "Find → Trace → Verify → Act.")],
             "The platform, end to end",
             "If a panel is empty here, it is empty in the product.")
    ] * int(FPS * 6)

    for shot in rec.shots:
        frames.extend([compose(shot)] * int(shot.step.hold_s * FPS))

    frames.extend([card(
        [("PURPOSE", "Bound before the search, recorded in every audit row"),
         ("CAPABILITY", "Measured per camera, per time band; UNKNOWN is first class"),
         ("EVIDENCE", "Hash-chained; integrity and truthfulness reported apart"),
         ("REFUSAL", "A restriction is never reported as an absence"),
         ("", ""),
         ("STEPS RECORDED", f"{len(rec.shots)}"
                            + (f", {len(rec.failed)} could not be driven"
                               if rec.failed else ", all driven successfully"))],
        "What the interface guarantees",
        "Every claim above is visible on a screen in this recording.")
    ] * int(FPS * 7))

    encode(frames, out.with_suffix(".mp4"))
    print(f"\nvideo : {display(out.with_suffix('.mp4'))} "
          f"({len(frames) / FPS:.0f}s, {len(rec.shots)} steps, "
          f"{time.time() - t0:.0f}s to record)")
    if rec.failed:
        print("steps that could not be driven:")
        for s in rec.failed:
            print(f"  {s.step.title}: {s.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
