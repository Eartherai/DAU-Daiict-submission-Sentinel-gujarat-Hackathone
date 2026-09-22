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
    ok: bool = True
    err: str = ""
    at: float = field(default=0.0)


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
        page.wait_for_timeout(6000)

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
        # The estate administrator onboards; the supervisor investigates.
        # Filming the handover is not ceremony — it is the role separation the
        # bonus criteria ask about, shown rather than asserted.
        Beat("Signed in as the estate administrator", 4,
             use_token(admin_token)),
        Beat("Onboarding — a camera added through the registry portal", 18, onboard),
        Beat("What the registry does not know", 11, registry_gaps),
        Beat("Handing over to the investigating officer", 5,
             use_token(investigator_token)),
        Beat("Own feeds, with AI detection drawn on them", 18, own_feeds),
        Beat("What the analytics produced", 13, nav("analytics", 2.5)),
        Beat("The mark, traced across the estate", 16, search_plate),
        Beat("Watchlist match, and the alert it fired", 16, nav("alerts", 2.0)),
        Beat("Evidence, sealed and hash-chained", 12, nav("evidence", 2.0)),
        Beat("Every query attributed", 11, nav("audit", 2.0)),
    ]


def record(base: str, token: str, plate: str, out_dir: Path,
           admin_token: str = "") -> list[Beat]:
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
        with Screencast(page, out_dir / "frames", width=VIEW_W,
                        height=VIEW_H, quality=98) as cast:
            t0 = time.time()
            for b in beats:
                b.at = time.time() - t0
                print(f"  {int(b.at)//60}:{int(b.at) % 60:02d}  {b.title}",
                      flush=True)
                try:
                    b.action()
                except Exception as exc:
                    b.ok, b.err = False, f"{type(exc).__name__}: {exc}"[:120]
                page.wait_for_timeout(int(b.dwell_s * 1000))
        res = cast.write(mp4, crf=15, fps=30)
        cast.cleanup()
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
    ap.add_argument("--admin-token-file",
                    help="ADMIN token. Onboarding needs admin:write, which "
                         "SUPERVISOR does not hold; without this the "
                         "onboarding beat films a refusal.")
    ap.add_argument("--plate", default="GJ18X6705")
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
    beats = record(a.base, token, a.plate, out_dir,
                   admin_token=admin_token)
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
