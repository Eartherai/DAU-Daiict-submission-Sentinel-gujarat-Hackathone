#!/usr/bin/env python3
"""Capture the workspace screenshots the submission deck shows, from the build.

The deck's own-feed pages carried screenshots of an interface several
revisions old. These are taken from the running server, signed in as the
officer the films use, so the deck shows what a reviewer who opens the app
will see.

    python tools/demo/capture_deck_shots.py --base http://127.0.0.1:8126 \\
        --token-file sup.tok

Writes var/demo/ui_shots_final/own_{intel,find,alerts,trace_report,evidence}.png
at 2560x1440. The tokens are read from files and never printed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "var" / "demo" / "ui_shots_final"
CASE = ("FIR-214/2026", "tracing a designated vehicle")


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8126")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--plate", default="GJ18JX7786")
    ap.add_argument("--government", action="store_true",
                    help="capture the government-store pages instead (live grid)")
    ap.add_argument("--wall-from", help="government film to take the live-wall frame from")
    ap.add_argument("--wall-at", type=float, default=185.0, help="seconds into that film")
    a = ap.parse_args()
    if a.government:
        return government(a)
    token = Path(a.token_file).read_text().strip()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 2560, "height": 1440})
        pg.goto(f"{a.base}/ui/")
        pg.evaluate("t => { sessionStorage.clear(); sessionStorage.setItem('saakshya.token', t) }", token)
        pg.reload()
        pg.wait_for_timeout(3000)

        pg.click('button[data-view="intelligence"]')
        pg.wait_for_function("() => [...document.querySelectorAll('.intel-stage video')]"
                             ".some(v => !v.paused && v.currentTime > 2)", timeout=30000)
        pg.wait_for_timeout(5000)
        pg.screenshot(path=str(OUT / "own_intel.png"))

        pg.click('button[data-view="investigate"]')
        pg.wait_for_timeout(1200)
        pg.fill("#case-id", CASE[0])
        pg.fill("#purpose", CASE[1])
        pg.fill("#q-plate", a.plate)
        pg.press("#q-plate", "Enter")
        pg.wait_for_timeout(6000)
        pg.screenshot(path=str(OUT / "own_find.png"))

        pg.click("#btn-trace-report")
        pg.wait_for_function("() => (document.querySelector('#report-frame')?.srcdoc || '')"
                             ".length > 1000", timeout=15000)
        pg.wait_for_timeout(1500)
        pg.evaluate("() => document.querySelector('#report-frame').contentWindow.scrollTo(0, 420)")
        pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "own_trace_report.png"))
        pg.click("#report-close")
        pg.wait_for_timeout(500)

        pg.click('button[data-view="alerts"]')
        pg.wait_for_timeout(3500)
        pg.screenshot(path=str(OUT / "own_alerts.png"))

        pg.click('button[data-view="evidence"]')
        pg.wait_for_timeout(4000)
        pg.screenshot(path=str(OUT / "own_evidence.png"))
        b.close()
    for n in ("intel", "find", "trace_report", "alerts", "evidence"):
        print(f"  wrote {(OUT / f'own_{n}.png').relative_to(ROOT)}")
    return 0


def government(a) -> int:
    """The deck's government pages, from the live grid as it is now."""
    from playwright.sync_api import sync_playwright

    token = Path(a.token_file).read_text().strip()
    shots = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 2560, "height": 1440})
        # A live page never fires "load": map tiles and streams keep arriving.
        pg.goto(f"{a.base}/ui/", wait_until="domcontentloaded")
        pg.evaluate("t => { sessionStorage.clear(); sessionStorage.setItem('saakshya.token', t) }", token)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(5000)
        # Wait for each page's own content, not a fixed time: on a loaded
        # server the first capture filmed four "Loading..." screens.
        ready = {
            "overview": "() => !document.querySelector('#view-overview')?.innerText.includes('Loading')"
                        " && document.querySelector('#view-overview')?.innerText.length > 400",
            "alerts": "() => document.querySelectorAll('#alerts .incident').length > 0",
            "cameras": "() => document.querySelectorAll('#view-cameras table tbody tr').length > 5",
            "map": "() => !!document.querySelector('#view-map .gmap-host, #view-map canvas')",
        }
        for view, name, settle in (("overview", "gov_overview.png", 3000),
                                   ("alerts", "gov_alerts_film.jpg", 2000),
                                   ("cameras", "gov_cameras_film.jpg", 2500),
                                   ("map", "gov_map_film.jpg", 9000)):
            pg.click(f'button[data-view="{view}"]')
            try:
                pg.wait_for_function(ready[view], timeout=90000)
            except Exception:
                print(f"  {view}: content did not appear; captured as it was")
            pg.wait_for_timeout(settle)
            path = OUT / name
            pg.screenshot(path=str(path), type="jpeg" if name.endswith(".jpg") else "png",
                          **({"quality": 92} if name.endswith(".jpg") else {}))
            shots[name] = path
        b.close()
    # The live wall is taken from the government film itself: a frame of the
    # recorded take, not a second set of grid sessions opened for a still.
    if a.wall_from:
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a.wall_at), "-i", a.wall_from,
                        "-frames:v", "1", str(OUT / "gov_live_grid.png")], check=True)
        shots["gov_live_grid.png"] = OUT / "gov_live_grid.png"
    for n in shots:
        print(f"  wrote {(OUT / n).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
