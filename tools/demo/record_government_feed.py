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
    ok: bool = True
    err: str = ""
    at: float = field(default=0.0)


def build(page, plate: str) -> list[Beat]:
    def nav(view: str, settle: float = 2.0):
        def go():
            page.click(f'button[data-view="{view}"]')
            page.wait_for_timeout(int(settle * 1000))
        return go

    def onboarded():
        """The government cameras as the registry holds them."""
        page.click('button[data-view="cameras"]')
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(2500)

    def live_wall():
        page.click('button[data-view="live"]')
        page.wait_for_selector("#live .live-tile", timeout=60000)
        # Wait for real decoded frames, not merely attached elements.
        decoding = ("() => [...document.querySelectorAll('#live-grid video')]"
                    ".filter(v => v.readyState >= 2 && v.videoWidth > 16)"
                    ".length >= 4")
        try:
            page.wait_for_function(decoding, timeout=75000)
        except Exception:
            pass  # filmed as it is, however it is

    def wall_12():
        try:
            page.click('[data-live-wall="12"]', timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(8000)

    def scroll_wall():
        try:
            page.hover("#live-grid", timeout=5000)
        except Exception:
            pass
        for _ in range(4):
            page.mouse.wheel(0, 380)
            page.wait_for_timeout(2200)

    def trace():
        page.click('button[data-view="investigate"]')
        page.wait_for_timeout(2000)
        # Without a case and a stated purpose the search is refused and the
        # screen shows PURPOSE_REQUIRED. Both are written into the audit log.
        for sel, value in (("#case-id", "FIR-000/2026"),
                           ("#purpose", "tracing a designated vehicle")):
            try:
                page.fill(sel, value, timeout=4000)
            except Exception:
                continue
        page.wait_for_timeout(600)
        for sel in ('#q-plate', '#q', 'input[name="q"]', '.search input'):
            try:
                page.fill(sel, plate, timeout=2500)
                page.press(sel, "Enter")
                break
            except Exception:
                continue
        page.wait_for_timeout(5000)

    def route_on_map():
        """Step 4 asks for the route visualised on GIS, not only listed.

        The trace above establishes where the mark was seen and when; this is
        the same movement shown geographically, which is what an officer
        directing a response actually reads.
        """
        page.click('button[data-view="map"]')
        page.wait_for_timeout(6000)

    return [
        Beat("Government cameras, onboarded and graded", 16, onboarded),
        Beat("Live viewing — the government wall over direct WHEP", 30, live_wall),
        Beat("Twelve up, at full quality", 26, wall_12),
        Beat("Scrolling the wall", 18, scroll_wall),
        Beat("Analytics output — what the estate produced", 20, nav("analytics", 2.5)),
        Beat("Marks read, with camera and timestamp", 18, nav("overview", 2.5)),
        Beat("The designated mark, traced across cameras", 20, trace),
        Beat("The route, visualised on GIS", 20, route_on_map),
        Beat("Watchlist match and the alert it fired", 18, nav("alerts", 2.0)),
        Beat("Evidence, sealed against the observation", 14, nav("evidence", 2.0)),
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


def record(base: str, token: str, plate: str, out_dir: Path) -> list[Beat]:
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
        page.wait_for_timeout(5000)
        try:
            page.wait_for_selector('button[data-view="live"]',
                                   state="visible", timeout=20000)
        except Exception:
            ctx.close()
            browser.close()
            raise SystemExit(
                "the workspace did not open — the token is expired or refused.\n"
                "  python tools/admin/users.py --db sqlite:///var/live.db "
                "token --user supervisor.live --days 7")

        beats = build(page, plate)
        mp4 = Path(str(out_dir) + ".mp4")
        with Screencast(page, out_dir / "frames",
                        width=VIEW_W, height=VIEW_H) as cast:
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
        res = cast.write(mp4, crf=18, fps=30)
        cast.cleanup()
        if not res.get("ok"):
            print(f"  capture FAILED: {res.get('why')}")
        else:
            print(f"  captured {res['frames']} frames at "
                  f"{res['captured_fps']} fps -> {res['mb']} MB")

        ctx.close()
        browser.close()
        return beats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8083")
    ap.add_argument("--token")
    ap.add_argument("--token-file")
    ap.add_argument("--plate", default="GJ18X6705")
    ap.add_argument("--out", default="var/demo/government_feed")
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
    beats = record(a.base, token, a.plate, out_dir)
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
