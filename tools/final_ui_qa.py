#!/usr/bin/env python3
"""Headed visual QA screenshots of the production UI. No secrets in artifacts."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/final/ui"
TOKEN_FILE = Path("/tmp/saakshya-demo-token.raw")

SCREENS = [
    ("login", None, "LOGIN"),
    ("overview", "overview", "OPERATIONS"),
    ("live-12", "live", "12-camera wall"),
    ("live-16", "live", "16-camera wall"),
    ("live-25", "live", "25-camera wall"),
    ("live-30", "live", "30-camera wall"),
    ("live-50", "live", "50-camera logical wall"),
    ("intelligence", "intelligence", "INTELLIGENCE"),
    ("investigate", "investigate", "INVESTIGATION"),
    ("system", "system", "SYSTEM"),
    ("map", "map", "GIS"),
    ("watchlist", "alerts", "WATCHLIST"),
    ("alerts", "alerts", "ALERT DETAIL"),
    ("cameras", "cameras", "CAMERA HEALTH"),
    ("federation", "system", "CONNECTED SYSTEMS"),
]


def refuse(blob: str) -> None:
    key = (os.environ.get("GOOGLE_MAPS_API_KEY")
           or os.environ.get("SAAKSHYA_GOOGLE_MAPS_KEY") or "")
    if key and key in blob:
        raise SystemExit("refusing maps key in UI artifact")
    if "AIzaSy" in blob:
        raise SystemExit("refusing maps-key-shaped token in UI artifact")


def click_js(page, selector: str) -> None:
    page.evaluate(
        """(sel) => { const n = document.querySelector(sel); if (n) n.click(); }""",
        selector)


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.is_file() else ""
    if not token:
        print("no demo token at", TOKEN_FILE)
        return 2
    base = os.environ.get("SAAKSHYA_UI", "http://127.0.0.1:8080")
    shots: list[dict] = []
    console: list[dict] = []
    boot = (
        "sessionStorage.setItem('saakshya.token'," + json.dumps(token) + ");"
        "sessionStorage.setItem('saakshya.case','FIR-214/2026');"
        "sessionStorage.setItem('saakshya.purpose',"
        "'final live production visual acceptance');"
    )
    refuse(boot)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        guest = browser.new_context(viewport={"width": 1440, "height": 900})
        page = guest.new_page()
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(700)
        page.evaluate(
            "() => { const g = document.getElementById('gate'); if (g) g.hidden = false; }")
        login_path = OUT / "A_LOGIN.png"
        page.screenshot(path=str(login_path), full_page=True)
        shots.append({"screen": "LOGIN",
                      "artifact": str(login_path.relative_to(ROOT)),
                      "result": "CAPTURED"})
        guest.close()

        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(boot)
        page = context.new_page()
        console = []
        page.on("console", lambda msg: console.append(
            {"type": msg.type, "text": (msg.text or "")[:240]}))
        page.on("pageerror", lambda err: console.append(
            {"type": "pageerror", "text": str(err)[:240]}))
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('officer-name')?.textContent !== 'Sign in'",
            timeout=8000)
        page.wait_for_timeout(600)

        walls = {"live-12": "12", "live-16": "16", "live-25": "25",
                 "live-30": "30", "live-50": "50"}
        for key, view, title in SCREENS[1:]:
            if view:
                click_js(page, f"nav button[data-view='{view}']")
                page.wait_for_timeout(1100)
            wall = walls.get(key)
            if wall:
                click_js(page, "nav button[data-view='live']")
                page.wait_for_timeout(400)
                click_js(page, "#view-live [data-live-layout='grid']")
                page.wait_for_timeout(200)
                if wall == "50":
                    click_js(page, "#view-live [data-live-domain='fifty']")
                else:
                    click_js(page, "#view-live [data-live-domain='government']")
                page.wait_for_timeout(400)
                click_js(page, f"#view-live [data-live-wall='{wall}']")
                page.wait_for_timeout(8000 if wall in {"12", "16"} else 11000)
            if key == "map":
                click_js(page, "#btn-fit2")
                page.wait_for_timeout(1800)
            if key in {"system", "federation"}:
                page.wait_for_timeout(2500)
            if key == "cameras":
                page.wait_for_timeout(2500)
            path = OUT / f"{title.replace(' ', '_').replace('/', '_')}.png"
            page.screenshot(path=str(path), full_page=True)
            shots.append({
                "screen": title,
                "artifact": str(path.relative_to(ROOT)),
                "result": "CAPTURED",
                "url_path": view,
            })
            if key == "alerts":
                page.evaluate("""() => {
                  const hit = (label) => {
                    const b = [...document.querySelectorAll('button')]
                      .find(x => (x.textContent || '').trim().toUpperCase() === label);
                    if (b) b.click();
                    return Boolean(b);
                  };
                  hit('TRACK');
                }""")
                page.wait_for_timeout(2200)
                tpath = OUT / "TRACKING.png"
                page.screenshot(path=str(tpath), full_page=True)
                shots.append({"screen": "TRACKING",
                              "artifact": str(tpath.relative_to(ROOT)),
                              "result": "CAPTURED"})
                page.evaluate("""() => {
                  const b = [...document.querySelectorAll('button')]
                    .find(x => (x.textContent || '').trim().toUpperCase() === 'ROUTE');
                  if (b) b.click();
                }""")
                page.wait_for_timeout(1800)
                rpath = OUT / "ROUTE.png"
                page.screenshot(path=str(rpath), full_page=True)
                shots.append({"screen": "ROUTE",
                              "artifact": str(rpath.relative_to(ROOT)),
                              "result": "CAPTURED"})
        cfg = page.evaluate("""async () => {
          const r = await fetch('/config', {headers: {
            Authorization: 'Bearer ' + sessionStorage.getItem('saakshya.token')}});
          return await r.json();
        }""")
        cfg_text = json.dumps(cfg)
        refuse(cfg_text)
        maps = {
            "google_enabled": bool(
                (cfg.get("map") or {}).get("google", {}).get("enabled")),
            "google_key_published": (
                (cfg.get("map") or {}).get("google", {}).get("key")
                not in (None, "", False)),
            "loader": (cfg.get("map") or {}).get("google", {}).get("loader"),
        }
        officer = page.evaluate(
            "() => document.getElementById('officer-name')?.textContent || ''")
        live_note = page.evaluate(
            "() => document.querySelector('#live-count')?.textContent || ''")
        browser.close()

    safe_console = []
    for row in console:
        text = row.get("text") or ""
        if "AIzaSy" in text or "skv_" in text or "Bearer " in text:
            continue
        safe_console.append(row)
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED",
        "shots": shots,
        "maps_config": maps,
        "officer": officer,
        "live_count": live_note,
        "console": safe_console[:40],
        "console_errors": [r for r in safe_console if r.get("type") in {"error", "pageerror"}],
        "note": "Product-shell screenshots. Government live tiles depend on Sentinel.",
    }
    text = json.dumps(payload, indent=2)
    refuse(text)
    (OUT / "visual_qa.json").write_text(text)
    print("wrote", len(shots), "screenshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
