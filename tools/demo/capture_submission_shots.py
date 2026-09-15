"""Capture latest workspace PNGs for the submission deck.

    python tools/demo/capture_submission_shots.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from saakshya.common.paths import display

OUT = ROOT / "var/demo/ui_shots_final"
CACHE = "cr086"


def wait_ok(page, js: str, timeout: int, label: str) -> bool:
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception as exc:
        print(f"  {label:18} wait failed: {type(exc).__name__}")
        return False


def shot(page, name: str) -> None:
    dest = OUT / f"{name}.png"
    page.screenshot(path=str(dest), full_page=False)
    print(f"  {name:18} {display(dest, ROOT)}")


def sign_in(page, base: str, token: str, case: str, purpose: str) -> None:
    page.goto(f"{base}/ui/?v={CACHE}", wait_until="domcontentloaded")
    wait_ok(page, "() => { const g = document.getElementById('gate'); return g && !g.hidden; }",
            15000, "signin")
    page.wait_for_timeout(300)
    page.evaluate(
        """({token, caseId, purpose}) => {
          sessionStorage.setItem('saakshya.token', token);
          sessionStorage.setItem('saakshya.case', caseId);
          sessionStorage.setItem('saakshya.purpose', purpose);
          localStorage.setItem('saakshya.theme', 'light');
          document.documentElement.dataset.theme = 'light';
        }""",
        {"token": token, "caseId": case, "purpose": purpose},
    )
    page.reload(wait_until="domcontentloaded")
    wait_ok(page, "() => /supervisor\\.(live|demo)/i.test(document.body.innerText)",
            20000, "identify")
    page.evaluate("() => { const g = document.getElementById('gate'); if (g) g.hidden = true; }")
    page.evaluate(
        """({caseId, purpose}) => {
          const c = document.getElementById('case-id');
          const p = document.getElementById('purpose');
          if (c) { c.value = caseId; c.dispatchEvent(new Event('input', {bubbles:true})); }
          if (p) { p.value = purpose; p.dispatchEvent(new Event('input', {bubbles:true})); }
        }""",
        {"caseId": case, "purpose": purpose},
    )


def nav(page, view: str) -> None:
    page.click(f'button[data-view="{view}"]')


def capture_gov(page) -> None:
    nav(page, "overview")
    wait_ok(page,
            "() => !document.querySelector('#overview .loading-note') "
            "&& document.querySelectorAll('#overview .plate-card').length >= 4",
            90000, "overview plates")
    page.wait_for_timeout(1200)
    shot(page, "gov_overview")
    try:
        page.locator("#overview .plate-gallery, #overview .ov-card").last.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        shot(page, "gov_overview_plates")
    except Exception:
        pass

    nav(page, "live")
    wait_ok(page, "() => document.querySelectorAll('#live .live-tile').length >= 8",
            45000, "live tiles")
    wait_ok(page,
            "() => [...document.querySelectorAll('#live .live-tile img, #live-stage img')]"
            ".filter(i => i.naturalWidth > 20).length >= 4",
            90000, "live frames")
    page.wait_for_timeout(1500)
    try:
        page.locator('[data-live-layout="twoup"]').click(force=True)
        page.wait_for_timeout(2500)
        shot(page, "gov_live_twoup")
    except Exception as exc:
        print(f"  twoup {type(exc).__name__}")
    try:
        page.locator('[data-live-layout="dense"]').click(force=True)
        page.wait_for_timeout(2500)
        shot(page, "gov_live_dense")
    except Exception as exc:
        print(f"  dense {type(exc).__name__}")
    try:
        page.locator('[data-live-layout="grid"]').click(force=True)
        page.wait_for_timeout(2000)
        shot(page, "gov_live_grid")
    except Exception:
        pass

    nav(page, "analytics")
    wait_ok(page,
            "() => /plated observations|distinct marks|WHAT ANALYTICS/i.test("
            "document.body.innerText) "
            "&& !/Loading from the live store/i.test("
            "document.querySelector('#view-analytics')?.innerText || '')",
            120000, "analytics")
    page.wait_for_timeout(800)
    shot(page, "gov_analytics")

    nav(page, "map")
    wait_ok(page,
            "() => document.querySelectorAll('#registry-rail .registry-chip').length >= 4 "
            "|| /\\d+ cameras/.test(document.getElementById('map2-count')?.textContent || '')",
            40000, "map")
    try:
        page.locator("#btn-fit2").click(force=True)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    shot(page, "gov_map")

    nav(page, "evidence")
    wait_ok(page,
            "() => /Evidence subsystem|Evidence chain verified|EVIDENCE CHAIN|"
            "Recomputing manifests|Chain verified/i.test(document.body.innerText)",
            25000, "evidence")
    page.wait_for_timeout(700)
    shot(page, "gov_evidence")

    nav(page, "system")
    wait_ok(page, "() => /hybrid of models/i.test(document.body.innerText)",
            60000, "system")
    page.wait_for_timeout(700)
    shot(page, "gov_system")


def capture_own(page) -> None:
    nav(page, "overview")
    wait_ok(page, "() => /Cameras onboarded|open alert|GJ05AB1234/i.test(document.body.innerText)",
            60000, "own overview")
    page.wait_for_timeout(900)
    shot(page, "own_overview")

    nav(page, "live")
    wait_ok(page, "() => document.querySelectorAll('#live .live-tile').length >= 2",
            30000, "own live tiles")
    page.wait_for_timeout(1500)
    shot(page, "own_live")
    try:
        loc = page.locator('[data-camera="OWN-PEOPLE"]').first
        loc.scroll_into_view_if_needed()
        loc.click(force=True)
        wait_ok(page,
                "() => { const s = document.querySelector('#live-stage img, #live-stage video'); "
                "return !!(s && (s.naturalWidth || s.videoWidth) > 40); }",
                25000, "own people stage")
        page.wait_for_timeout(2500)
        shot(page, "own_live_people")
    except Exception as exc:
        print(f"  own people {type(exc).__name__}")

    nav(page, "investigate")
    page.wait_for_timeout(400)
    page.fill("#q-plate", "GJ05AB1234")
    page.click("#search-form button.primary")
    wait_ok(page,
            "() => { const n = document.getElementById('result-count'); "
            "return n && /observation/.test(n.textContent); }",
            45000, "own find")
    page.wait_for_timeout(1400)
    shot(page, "own_find")

    nav(page, "alerts")
    wait_ok(page, "() => /GJ05AB1234|GJ15NT6564/i.test(document.body.innerText)",
            20000, "own alerts")
    page.wait_for_timeout(500)
    shot(page, "own_alerts")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    live_tok = Path("/tmp/saakshya-live-token.raw").read_bytes().strip().decode("ascii")
    demo_tok = Path("/tmp/saakshya-demo-token.raw").read_bytes().strip().decode("ascii")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=1)

        print("government 8080")
        sign_in(page, "http://127.0.0.1:8080", live_tok,
                "FIR-000/2026", "jury verification of live person and plate")
        capture_gov(page)

        print("own feed 8081")
        sign_in(page, "http://127.0.0.1:8081", demo_tok,
                "FIR-214/2026", "designated vehicle on own CCTV")
        capture_own(page)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
