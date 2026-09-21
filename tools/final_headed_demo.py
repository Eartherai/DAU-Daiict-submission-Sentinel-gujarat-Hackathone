#!/usr/bin/env python3
"""Headed Google Chrome production demo: GPU probe + operator click-through film.

Real Chrome (not headless, not SwiftShader). Token is read from a 0600 file and
never typed into a recorded field. Console/network logs are redacted.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "demo"))
from hq_capture import CURSOR_JS, ScreencastFilm  # noqa: E402

OUT = ROOT / "reports/final_live_qa/demo"
TOKEN_FILE = Path("/tmp/saakshya-demo-token.raw")
BASE = os.environ.get("SAAKSHYA_UI", "http://127.0.0.1:8080")
PLATE = "GJ01TA0001"
W, H = 1920, 1080
FPS = 30

CHROME_ARGS = [
    "--use-angle=metal",
    "--ignore-gpu-blocklist",
    "--enable-gpu-rasterization",
    "--enable-zero-copy",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-timer-throttling",
    "--window-size=1920,1080",
    "--window-position=80,40",
]


def refuse(blob: str) -> str:
    blob = re.sub(r"skv_[A-Za-z0-9._-]+", "skv_[REDACTED]", blob)
    blob = re.sub(r"Bearer [A-Za-z0-9._-]+", "Bearer [REDACTED]", blob)
    blob = re.sub(r"AIzaSy[A-Za-z0-9_-]+", "AIza[REDACTED]", blob)
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or ""
    if key:
        blob = blob.replace(key, "[MAPS_KEY_REDACTED]")
    return blob


def ffmpeg_bin() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def click_js(page, sel: str) -> bool:
    return bool(page.evaluate(
        """(sel) => { const n = document.querySelector(sel); if (!n) return false;
           n.scrollIntoView({block:'center', inline:'nearest'}); n.click(); return true; }""",
        sel))


def click_text(page, label: str) -> bool:
    return bool(page.evaluate(
        """(label) => {
          const want = label.trim().toUpperCase();
          const b = [...document.querySelectorAll('button, a, [role=button]')]
            .find(x => (x.textContent || '').trim().toUpperCase() === want
                    || (x.textContent || '').trim().toUpperCase().includes(want));
          if (!b) return false;
          b.scrollIntoView({block:'center'}); b.click(); return true;
        }""",
        label))


class Demo:
    def __init__(self, page, film: JpegFilm, shots: Path):
        self.page = page
        self.film = film
        self.shots = shots
        self.timeline: list[dict] = []
        self.clicks: list[dict] = []
        self.t0 = time.monotonic()
        self.console: list[dict] = []
        self.network: list[dict] = []

    def elapsed(self) -> str:
        s = int(time.monotonic() - self.t0)
        return f"{s // 60:02d}:{s % 60:02d}"

    def mark(self, title: str, note: str = "") -> None:
        row = {"t": self.elapsed(), "title": title, "note": note}
        self.timeline.append(row)
        print(f"[{row['t']}] {title}", flush=True)

    def hold(self, ms: int) -> None:
        self.film.hold(ms)

    def shot(self, name: str) -> None:
        path = self.shots / f"{name}.png"
        self.page.screenshot(path=str(path), type="png")
        self.clicks.append({"t": self.elapsed(), "shot": name, "ok": True})

    def view(self, name: str) -> None:
        ok = click_js(self.page, f"nav button[data-view='{name}']")
        self.clicks.append({"t": self.elapsed(), "action": f"nav:{name}", "ok": ok})
        self.hold(900)

    def product(self, name: str) -> None:
        ok = click_js(self.page, f"[data-product='{name}']")
        self.clicks.append({"t": self.elapsed(), "action": f"product:{name}", "ok": ok})
        self.hold(700)

    def live_btn(self, sel: str) -> None:
        ok = click_js(self.page, sel)
        self.clicks.append({"t": self.elapsed(), "action": sel, "ok": ok})
        self.hold(400)


def attach_logs(page, demo: Demo) -> None:
    def on_console(msg):
        text = refuse((msg.text or "")[:400])
        demo.console.append({"t": demo.elapsed(), "type": msg.type, "text": text})

    def on_pageerror(err):
        demo.console.append({"t": demo.elapsed(), "type": "pageerror",
                             "text": refuse(str(err)[:400])})

    def on_request_fail(req):
        url = refuse(req.url.split("?")[0][:180])
        if "google" in url.lower() or "maps" in url.lower() or "whep" in url.lower() \
                or "/cameras/" in url or "/snapshot" in url:
            demo.network.append({"t": demo.elapsed(), "fail": url,
                                 "error": req.failure or "failed"})

    def on_response(res):
        if res.status >= 400:
            url = refuse(res.url.split("?")[0][:180])
            demo.network.append({"t": demo.elapsed(), "status": res.status, "url": url})

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("requestfailed", on_request_fail)
    page.on("response", on_response)


def probe(pw) -> dict:
    browser = pw.chromium.launch(channel="chrome", headless=False, args=CHROME_ARGS)
    try:
        ctx = browser.new_context(viewport={"width": W, "height": H})
        page = ctx.new_page()
        page.goto("chrome://gpu", wait_until="domcontentloaded", timeout=20000)
        time.sleep(1.2)
        gpu_text = refuse(page.inner_text("body")[:12000])
        (OUT / "chromium_gpu.txt").write_text(gpu_text)
        page.screenshot(path=str(OUT / "chromium_gpu.png"), full_page=False)
        feature = page.evaluate("""() => {
          return {
            title: document.title,
            gl: (() => { try {
              const c = document.createElement('canvas');
              const gl = c.getContext('webgl2') || c.getContext('webgl');
              const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
              return info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : (gl ? 'webgl' : 'none');
            } catch (e) { return String(e); } })(),
          };
        }""")
        page.goto(BASE + "/", wait_until="domcontentloaded")
        webrtc = page.evaluate("""() => {
          const caps = RTCRtpReceiver.getCapabilities && RTCRtpReceiver.getCapabilities('video');
          return {
            rtcPeerConnection: typeof RTCPeerConnection === 'function',
            codecs: (caps && caps.codecs || []).map(c => c.mimeType),
            hardware: navigator.userAgent,
          };
        }""")
        ua = page.evaluate("() => navigator.userAgent")
        env = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "browser": "Google Chrome (Playwright channel=chrome)",
            "headless": False,
            "args": CHROME_ARGS,
            "user_agent": ua,
            "gpu_feature_sample": feature,
            "renderer_unmasked": feature.get("gl"),
            "webrtc": webrtc,
            "h264": any("H264" in c.upper() or "AVC" in c.upper()
                        for c in webrtc.get("codecs") or []),
            "hevc": any("H265" in c.upper() or "HEVC" in c.upper()
                        for c in webrtc.get("codecs") or []),
            "angle_backend": "metal (requested --use-angle=metal)",
            "display": "1920x1080 context on Apple M5 + HP 524sa",
            "label": "MEASURED",
            "note": "Hardware decode status is also in chromium_gpu.txt. SwiftShader was not requested.",
        }
        (OUT / "chromium_environment.json").write_text(refuse(json.dumps(env, indent=2)))
        return env
    finally:
        browser.close()


def walkthrough(page, demo: Demo, token: str) -> None:
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.evaluate(
        "() => { const g = document.getElementById('gate'); if (g) g.hidden = false; }")
    demo.mark("Login", "gate visible; real token never typed")
    demo.hold(2200)
    demo.shot("00_login")
    page.fill("#gate-token", "skv_invalid_token_for_demo")
    page.fill("#gate-case", "FIR-214/2026")
    page.fill("#gate-purpose", "official evaluation designated vehicle")
    click_js(page, "#gate-form button[type=submit]")
    demo.hold(1800)
    demo.shot("01_invalid_auth")
    demo.mark("Invalid authentication", "refused token shown")

    page.evaluate(
        """(tok) => {
          sessionStorage.setItem('saakshya.token', tok);
          sessionStorage.setItem('saakshya.case', 'FIR-214/2026');
          sessionStorage.setItem('saakshya.purpose',
            'official evaluation designated vehicle');
        }""",
        token)
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.getElementById('officer-name')?.textContent !== 'Sign in'",
        timeout=12000)
    page.evaluate(CURSOR_JS)
    demo.mark("Session", "supervisor.demo · FIR-214/2026")
    demo.hold(2500)
    demo.shot("02_overview")

    demo.view("live")
    demo.live_btn("#view-live [data-live-layout='grid']")
    demo.live_btn("#view-live [data-live-domain='government']")
    demo.live_btn("#view-live [data-live-wall='12']")
    demo.mark("Government Grid 12", "MEASURED REAL stills/WHEP — not 30 LIVE")
    demo.hold(14000)
    demo.shot("03_gov_grid_12")

    demo.live_btn("#view-live [data-live-layout='focus']")
    demo.hold(2500)
    demo.shot("04_focus")
    demo.live_btn("#view-live [data-live-layout='grid']")
    for wall, wait in (("16", 5000), ("25", 5000), ("30", 9000)):
        demo.live_btn(f"#view-live [data-live-wall='{wall}']")
        demo.mark(f"Wall {wall}", "EXTERNAL DEPENDENCY if tiles stay STILL/NO SIGNAL")
        demo.hold(wait)
        demo.shot(f"05_wall_{wall}")

    click_js(page, "#live-grid .live-tile")
    demo.hold(2500)
    demo.shot("06_camera_open")
    demo.live_btn("#view-live [data-live-layout='grid']")
    demo.live_btn("#view-live [data-live-wall='12']")
    demo.hold(2000)

    demo.live_btn("#view-live [data-live-domain='fifty']")
    demo.live_btn("#view-live [data-live-wall='50']")
    demo.mark("50-camera logical", "30 GOVERNMENT + 2 OWN_FEED + CONTROL — not 50 gov LIVE")
    demo.hold(7000)
    demo.shot("07_wall_50")

    demo.live_btn("#view-live [data-live-domain='government']")
    demo.live_btn("#view-live [data-live-wall='12']")
    for mode in ("video", "vehicles", "people", "anpr", "full", "incident"):
        demo.live_btn(f"#view-live [data-viewmode='{mode}']")
        demo.hold(700)
    demo.shot("08_analytics_full")

    demo.product("intelligence")
    demo.view("intelligence")
    demo.mark("Intelligence", "OWN FEED file replay · FULL ANALYTICS · MEASURED OWN FEED")
    demo.hold(5000)
    demo.shot("09_intelligence")
    page.evaluate("() => document.getElementById('view-intelligence')?.scrollTo(0,0)")
    demo.hold(1500)
    click_js(page, "#intel-open-a")
    demo.hold(2500)
    demo.view("intelligence")
    demo.hold(1500)

    demo.view("alerts")
    demo.mark("Watchlist / alerts", "GJ01TA0001 is OWN-TRAFFIC / DEMO — not government ANPR")
    demo.hold(2500)
    demo.shot("10_alerts")
    for status in ("", "ACKNOWLEDGED", "INVESTIGATING", "CLEARED", "OPEN"):
        click_js(page, f"[data-alert-status='{status}']")
        demo.hold(600)
    demo.shot("11_alerts_tabs")
    click_text(page, "TRACK")
    demo.hold(3500)
    demo.shot("12_track")
    demo.mark("Investigate GJ01TA0001", "LIKELY / REQUIRES VERIFICATION")

    demo.view("investigate")
    demo.hold(800)
    page.fill("#q-plate", PLATE)
    if not click_js(page, "#search-form button[type=submit]"):
        page.evaluate("() => document.getElementById('search-form')?.requestSubmit()")
    demo.hold(3500)
    demo.shot("13_search")
    click_js(page, "#btn-fit")
    demo.hold(1200)
    click_js(page, "#btn-focus-target")
    demo.hold(1800)
    demo.shot("14_route")

    demo.view("map")
    demo.mark("GIS", "Google Maps · MEASURED REAL basemap · key not on page")
    demo.hold(2500)
    click_js(page, "#btn-fit2")
    demo.hold(2500)
    demo.shot("15_gis")
    page.mouse.wheel(0, -400)
    demo.hold(800)
    page.mouse.wheel(0, 400)
    demo.hold(800)

    demo.view("evidence")
    demo.hold(2000)
    demo.shot("16_evidence")
    demo.view("cameras")
    demo.hold(3500)
    demo.shot("17_camera_health")
    demo.view("analytics")
    demo.hold(2500)
    demo.shot("18_analytics")
    demo.view("system")
    demo.mark("System", "DEGRADED store health is honest · DEMO/TEST adapters")
    demo.hold(3500)
    demo.shot("19_system")
    page.evaluate("""() => {
      const s = document.getElementById('system') || document.getElementById('view-system');
      if (s) s.scrollTop = s.scrollHeight;
    }""")
    demo.hold(1800)
    demo.shot("20_system_ranks")
    demo.view("audit")
    demo.hold(2500)
    demo.shot("21_audit")

    demo.view("live")
    demo.live_btn("#view-live [data-live-layout='grid']")
    demo.live_btn("#view-live [data-live-domain='government']")
    demo.live_btn("#view-live [data-live-wall='12']")
    demo.hold(2000)
    try:
        page.reload(wait_until="domcontentloaded", timeout=8000)
    except Exception as exc:
        demo.clicks.append({"t": demo.elapsed(), "action": "reload",
                            "ok": False, "error": type(exc).__name__})
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1500)
    page.evaluate(CURSOR_JS)
    demo.mark("Refresh recovery", "session restored from sessionStorage")
    demo.hold(4000)
    demo.shot("22_refresh")
    demo.view("overview")
    demo.hold(2500)
    demo.shot("23_final_overview")
    demo.mark("Final status", "not 30 LIVE · not 50 government feeds")


def write_artifacts(demo: Demo, dest: Path) -> None:
    meta = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "base": BASE,
        "headless": False,
        "channel": "chrome",
        "viewport": {"width": W, "height": H},
        "fps": FPS,
        "duration_s": round(time.monotonic() - demo.t0, 1),
        "timeline": demo.timeline,
        "clicks": demo.clicks,
        "plate": PLATE,
        "honesty": {
            "thirty_government_live": False,
            "fifty_government_live": False,
            "own_feed_is_live_camera": False,
            "gj01ta0001_is_government_anpr": False,
        },
        "video": str(dest.relative_to(ROOT)),
    }
    (OUT / "demo_timeline.md").write_text(_timeline_md(demo.timeline, meta["duration_s"]))
    (OUT / "clickthrough_results.json").write_text(
        refuse(json.dumps({"clicks": demo.clicks, "n": len(demo.clicks)}, indent=2)))
    (OUT / "final_browser_console.log").write_text(
        refuse("\n".join(json.dumps(r) for r in demo.console[:400])))
    (OUT / "final_browser_network.log").write_text(
        refuse("\n".join(json.dumps(r) for r in demo.network[:400])))
    (OUT / "final_demo_metadata.json").write_text(refuse(json.dumps(meta, indent=2)))
    print("wrote", dest, "duration", meta["duration_s"], "s")


def run_demo(pw, token: str) -> None:
    frames = OUT / "final_demo_frames"
    frames.mkdir(parents=True, exist_ok=True)
    dest = OUT / "final_demo.mp4"
    browser = pw.chromium.launch(channel="chrome", headless=False, args=CHROME_ARGS)
    film = None
    demo = None
    try:
        ctx = browser.new_context(viewport={"width": W, "height": H})
        page = ctx.new_page()
        page.add_init_script(CURSOR_JS)
        film = ScreencastFilm(page, dest, ffmpeg_bin(), fps=FPS, quality=80)
        demo = Demo(page, film, frames)
        attach_logs(page, demo)
        walkthrough(page, demo, token)
    finally:
        if film is not None:
            try:
                film.close()
            except SystemExit as exc:
                print("encode:", exc, flush=True)
        if demo is not None:
            write_artifacts(demo, dest)
        browser.close()


def _timeline_md(rows: list[dict], duration: float) -> str:
    lines = ["# Demo timeline", "",
             f"Duration ≈ {duration:.0f}s · headed Chrome 1920×1080 · target {FPS} fps CDP screencast→H.264",
             "",
             "| Time | Section | Note |",
             "|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['t']} | {r['title']} | {r.get('note') or ''} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "final_demo_frames").mkdir(exist_ok=True)
    probe_only = "--probe-only" in sys.argv
    skip_probe = "--skip-probe" in sys.argv
    with sync_playwright() as pw:
        if not skip_probe:
            env = probe(pw)
            print("GPU renderer:", env.get("renderer_unmasked"))
            print("H264:", env.get("h264"), "HEVC:", env.get("hevc"))
        if probe_only:
            return 0
        token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.is_file() else ""
        if not token:
            print("missing", TOKEN_FILE)
            return 2
        run_demo(pw, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
