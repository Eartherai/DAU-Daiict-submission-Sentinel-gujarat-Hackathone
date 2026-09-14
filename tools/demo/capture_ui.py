"""Capture the live workspace, one PNG per view, for the submission deck.

    python tools/demo/capture_ui.py --base http://127.0.0.1:8080 \
        --token-file /tmp/saakshya-live-token.raw --out var/demo/ui_shots

Nothing is mocked. Each file is Chrome displaying the served page. Slow
endpoints on the live store are waited for by content, not by a guess.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from saakshya.common.paths import display

CASE = "FIR-000/2026"
PURPOSE = "jury verification of live person and plate search"
PLATE = "GJ1VV0119"


def wait_ok(page, js: str, timeout: int, label: str) -> None:
    try:
        page.wait_for_function(js, timeout=timeout)
    except Exception as exc:
        print(f"  {label:12} wait failed: {type(exc).__name__}")


def shot(page, out: Path, name: str) -> None:
    dest = out / f"{name}.png"
    page.screenshot(path=str(dest), full_page=False)
    print(f"  {name:12} {display(dest, ROOT)}")


def bind_purpose(page) -> None:
    page.evaluate(
        """({caseId, purpose}) => {
          const c = document.getElementById('case-id');
          const p = document.getElementById('purpose');
          if (c) { c.value = caseId; c.dispatchEvent(new Event('input', {bubbles:true})); }
          if (p) { p.value = purpose; p.dispatchEvent(new Event('input', {bubbles:true})); }
        }""",
        {"caseId": CASE, "purpose": PURPOSE},
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--out", default="var/demo/ui_shots")
    ap.add_argument("--views", default="",
                    help="Comma-separated view names to recapture; empty means all")
    a = ap.parse_args()
    token = Path(a.token_file).read_bytes().strip().decode("ascii")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900},
                                device_scale_factor=2)

        page.goto(f"{a.base}/ui/?v=cr069", wait_until="domcontentloaded")
        wait_ok(page, "() => { const g = document.getElementById('gate'); return g && !g.hidden; }",
                15000, "signin")
        page.wait_for_timeout(400)
        shot(page, out, "signin")

        page.evaluate(
            """({token, caseId, purpose}) => {
              sessionStorage.setItem('saakshya.token', token);
              sessionStorage.setItem('saakshya.case', caseId);
              sessionStorage.setItem('saakshya.purpose', purpose);
              localStorage.setItem('saakshya.theme', 'light');
              document.documentElement.dataset.theme = 'light';
            }""",
            {"token": token, "caseId": CASE, "purpose": PURPOSE},
        )
        page.reload(wait_until="domcontentloaded")
        wait_ok(page, "() => /supervisor\\.live/i.test(document.body.innerText)",
                20000, "identify")
        page.evaluate("() => { const g = document.getElementById('gate'); if (g) g.hidden = true; }")
        bind_purpose(page)

        page.click('button[data-view="overview"]')
        wait_ok(page,
                "() => /open alert/i.test(document.body.innerText) "
                "&& document.querySelectorAll('.health-row').length >= 1",
                60000, "overview")
        page.wait_for_timeout(800)
        shot(page, out, "overview")

        page.click('button[data-view="investigate"]')
        bind_purpose(page)
        page.fill("#q-plate", PLATE)
        page.click("#search-form button.primary")
        wait_ok(page,
                "() => { const n = document.getElementById('result-count'); "
                "return n && /observation/.test(n.textContent); }",
                45000, "investigate")
        page.wait_for_timeout(1200)
        shot(page, out, "investigate")

        page.click('button[data-view="cameras"]')
        wait_ok(page,
                "() => document.querySelectorAll('#cameras table.data tbody tr').length >= 8",
                45000, "cameras")
        page.wait_for_timeout(600)
        shot(page, out, "cameras")

        page.click('button[data-view="live"]')
        wait_ok(page,
                "() => document.querySelectorAll('#live .live-tile').length >= 8",
                30000, "live-tiles")
        wait_ok(page,
                "() => [...document.querySelectorAll('#live .live-tile img')]"
                ".filter(i => i.naturalWidth > 20).length >= 4",
                90000, "live-stills")
        page.wait_for_timeout(800)
        shot(page, out, "live")

        page.click('button[data-view="alerts"]')
        wait_ok(page, "() => /GJ38BH5815/.test(document.body.innerText)",
                20000, "alerts")
        page.wait_for_timeout(500)
        shot(page, out, "alerts")

        page.click('button[data-view="analytics"]')
        wait_ok(page,
                "() => /plated observations/i.test(document.body.innerText) "
                "|| /distinct marks/i.test(document.body.innerText)",
                120000, "analytics")
        page.wait_for_timeout(800)
        shot(page, out, "analytics")

        page.click('button[data-view="map"]')
        wait_ok(page,
                "() => document.querySelectorAll('#registry-rail .registry-chip').length >= 4 "
                "|| /\\d+ cameras/.test(document.getElementById('map2-count')?.textContent || '')",
                30000, "map")
        page.wait_for_timeout(800)
        shot(page, out, "map")

        page.click('button[data-view="evidence"]')
        wait_ok(page,
                "() => /Evidence subsystem/i.test(document.body.innerText) "
                "|| /Evidence chain verified/i.test(document.body.innerText) "
                "|| /EVIDENCE CHAIN BROKEN/i.test(document.body.innerText) "
                "|| /Recomputing manifests/i.test(document.body.innerText)",
                25000, "evidence")
        page.wait_for_timeout(600)
        shot(page, out, "evidence")

        page.click('button[data-view="system"]')
        wait_ok(page,
                "() => /hybrid of models/i.test(document.body.innerText)",
                90000, "system")
        page.wait_for_timeout(800)
        shot(page, out, "system")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
