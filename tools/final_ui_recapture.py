#!/usr/bin/env python3
"""Single-pass recapture: grid-12, intelligence, track, system. No wall thrash."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/final/ui"
TOKEN = Path("/tmp/saakshya-demo-token.raw").read_text().strip()
BASE = "http://127.0.0.1:8080"


def click_js(page, sel: str) -> None:
    page.evaluate(
        """(sel) => { const n = document.querySelector(sel); if (n) n.click(); }""",
        sel)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    boot = (
        "sessionStorage.setItem('saakshya.token'," + json.dumps(TOKEN) + ");"
        "sessionStorage.setItem('saakshya.case','FIR-214/2026');"
        "sessionStorage.setItem('saakshya.purpose',"
        "'final live production visual acceptance');"
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(boot)
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('officer-name')?.textContent !== 'Sign in'",
            timeout=8000)
        page.wait_for_timeout(800)

        click_js(page, "nav button[data-view='intelligence']")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "INTELLIGENCE.png"), full_page=True)

        click_js(page, "nav button[data-view='live']")
        page.wait_for_timeout(500)
        click_js(page, "#view-live [data-live-layout='grid']")
        click_js(page, "#view-live [data-live-domain='government']")
        page.wait_for_timeout(400)
        click_js(page, "#view-live [data-live-wall='12']")
        page.wait_for_timeout(16000)
        page.screenshot(path=str(OUT / "12-camera_wall.png"), full_page=True)

        click_js(page, "nav button[data-view='alerts']")
        page.wait_for_timeout(1200)
        page.evaluate("""() => {
          const b = [...document.querySelectorAll('button')]
            .find(x => (x.textContent || '').trim() === 'TRACK');
          if (b) b.click();
        }""")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "TRACKING.png"), full_page=True)

        click_js(page, "nav button[data-view='system']")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "SYSTEM.png"), full_page=True)
        page.evaluate("""() => {
          const box = document.getElementById('system');
          if (box) box.scrollTop = box.scrollHeight;
        }""")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "CONNECTED_SYSTEMS.png"), full_page=True)

        click_js(page, "nav button[data-view='cameras']")
        page.wait_for_timeout(4000)
        page.screenshot(path=str(OUT / "CAMERA_HEALTH.png"), full_page=True)

        browser.close()
    print("recapture done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
