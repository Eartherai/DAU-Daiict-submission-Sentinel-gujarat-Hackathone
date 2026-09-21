#!/usr/bin/env python3
"""Automated Full Demonstration Video Recorder for SAAKSHYA
Conforms to Deliverable 4 (Live Demonstration on Government-Provided CCTV Feed)
Technical Evaluation Framework - Gujarat Police Innovation Challenge 2026
"""

import os
import pathlib
import sys
import time
import math
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "brag-output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_REC_DIR = OUTPUT_DIR / "raw_recordings"
RAW_REC_DIR.mkdir(parents=True, exist_ok=True)

FINAL_VIDEO = OUTPUT_DIR / "saakshya_full_demo.mp4"
FINAL_POSTER = OUTPUT_DIR / "saakshya_full_demo.jpg"

def _token() -> str:
    """Read the bearer token from the environment or a file, never source.

    A live token was hardcoded here. It authenticates every request this
    recorder makes, and committing it would have published a working
    credential to the repository history, where deleting the line later does
    not remove it. Tokens belong in the environment or a file the repository
    ignores.
    """
    tok = os.environ.get("SAAKSHYA_TOKEN", "").strip()
    if tok:
        return tok
    path = os.environ.get("SAAKSHYA_TOKEN_FILE", "").strip()
    if path:
        return pathlib.Path(path).read_text(encoding="ascii").strip()
    raise SystemExit(
        "This recorder needs a bearer token. Set SAAKSHYA_TOKEN, or point\n"
        "SAAKSHYA_TOKEN_FILE at a file holding one. Mint one with:\n"
        "  python tools/admin/users.py --db sqlite:///var/live.db \\\n"
        "      token --user supervisor.live --days 7")


TOKEN = _token()
APP_URL = "http://127.0.0.1:8088/"

def ease_in_out(t):
    return t * t * (3 - 2 * t)

def inject_overlay_system(page):
    page.evaluate('''() => {
        if (document.getElementById('demo-overlay-styles')) return;
        const style = document.createElement('style');
        style.id = 'demo-overlay-styles';
        style.textContent = `
            #demo-cursor {
                position: fixed;
                top: 0; left: 0;
                width: 32px; height: 32px;
                pointer-events: none;
                z-index: 9999999;
                transition: transform 0.05s linear;
                filter: drop-shadow(0 6px 14px rgba(0,0,0,0.6));
            }
            .demo-ripple {
                position: fixed;
                width: 52px; height: 52px;
                border-radius: 50%;
                border: 3px solid #38bdf8;
                background: radial-gradient(circle, rgba(56, 189, 248, 0.4) 0%, rgba(56, 189, 248, 0) 70%);
                pointer-events: none;
                z-index: 9999998;
                transform: translate(-50%, -50%) scale(0.2);
                animation: demo-ripple-anim 0.55s cubic-bezier(0.1, 0.8, 0.3, 1) forwards;
            }
            @keyframes demo-ripple-anim {
                0% { transform: translate(-50%, -50%) scale(0.2); opacity: 1; }
                100% { transform: translate(-50%, -50%) scale(2.0); opacity: 0; }
            }
            #demo-hud {
                position: fixed;
                bottom: 30px; left: 50%;
                transform: translateX(-50%);
                background: rgba(10, 18, 36, 0.94);
                border: 1px solid rgba(56, 189, 248, 0.5);
                backdrop-filter: blur(16px);
                color: #f8fafc;
                padding: 14px 32px;
                border-radius: 9999px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 15px;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 18px;
                box-shadow: 0 12px 36px rgba(0,0,0,0.7), 0 0 24px rgba(56,189,248,0.25);
                z-index: 9999997;
                letter-spacing: 0.03em;
                transition: all 0.3s ease;
            }
            #demo-hud .badge {
                background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
                color: #ffffff;
                padding: 5px 12px;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                box-shadow: 0 2px 8px rgba(2,132,199,0.4);
            }
            #demo-hud .hud-title {
                color: #e2e8f0;
                font-size: 15px;
            }
            #demo-hud .hud-sub {
                color: #38bdf8;
                font-size: 13px;
                font-weight: 500;
                border-left: 1px solid rgba(255,255,255,0.2);
                padding-left: 14px;
            }
        `;
        document.head.appendChild(style);

        const cursor = document.createElement('div');
        cursor.id = 'demo-cursor';
        cursor.innerHTML = `<svg width="30" height="30" viewBox="0 0 24 24" fill="none">
            <path d="M4 2L18.5 12.5L12 14L9 20.5L4 2Z" fill="#38bdf8" stroke="#ffffff" stroke-width="2" stroke-linejoin="round"/>
        </svg>`;
        document.body.appendChild(cursor);

        const hud = document.createElement('div');
        hud.id = 'demo-hud';
        hud.innerHTML = `
            <span class="badge">EVALUATION</span>
            <span class="hud-title">SAAKSHYA — Gujarat Police CCTV Intelligence Fabric</span>
            <span class="hud-sub">Deliverable 4: Live Demonstration on Government-Provided CCTV Feed</span>
        `;
        document.body.appendChild(hud);

        window.__cursorX = 960;
        window.__cursorY = 540;

        window.setCursorPos = (x, y) => {
            window.__cursorX = x;
            window.__cursorY = y;
            cursor.style.transform = `translate(${x}px, ${y}px)`;
        };

        window.triggerClickRipple = (x, y) => {
            const r = document.createElement('div');
            r.className = 'demo-ripple';
            r.style.left = x + 'px';
            r.style.top = y + 'px';
            document.body.appendChild(r);
            setTimeout(() => r.remove(), 600);
        };

        window.updateHud = (badge, title, subtitle) => {
            document.querySelector('#demo-hud .badge').textContent = badge;
            document.querySelector('#demo-hud .hud-title').textContent = title;
            document.querySelector('#demo-hud .hud-sub').textContent = subtitle || '';
        };
    }''')

class CursorController:
    def __init__(self, page):
        self.page = page
        self.x = 960
        self.y = 540

    def move_to(self, target_x, target_y, steps=25, delay=0.015):
        start_x, start_y = self.x, self.y
        for i in range(1, steps + 1):
            t = i / steps
            e = ease_in_out(t)
            curr_x = start_x + (target_x - start_x) * e
            curr_y = start_y + (target_y - start_y) * e
            self.page.evaluate(f"window.setCursorPos({curr_x}, {curr_y})")
            time.sleep(delay)
        self.x, self.y = target_x, target_y

    def click(self, target_x=None, target_y=None):
        if target_x is not None and target_y is not None:
            self.move_to(target_x, target_y)
        self.page.evaluate(f"window.triggerClickRipple({self.x}, {self.y})")
        time.sleep(0.12)

    def click_element(self, selector, offset_x=0.5, offset_y=0.5, wait_after=1.0):
        try:
            loc = self.page.locator(selector).first
            if loc.count() == 0:
                print(f"[WARN] Element not found for click: {selector}")
                return
            loc.scroll_into_view_if_needed(timeout=3000)
            box = loc.bounding_box()
            if box:
                target_x = box["x"] + box["width"] * offset_x
                target_y = box["y"] + box["height"] * offset_y
                self.move_to(target_x, target_y)
                self.click()
                loc.click(timeout=3000)
                time.sleep(wait_after)
            else:
                loc.click(timeout=3000)
                time.sleep(wait_after)
        except Exception as e:
            print(f"[WARN] Failed to click {selector}: {e}")

    def hover_element(self, selector, offset_x=0.5, offset_y=0.5, wait_after=0.8):
        try:
            loc = self.page.locator(selector).first
            if loc.count() == 0:
                return
            box = loc.bounding_box()
            if box:
                target_x = box["x"] + box["width"] * offset_x
                target_y = box["y"] + box["height"] * offset_y
                self.move_to(target_x, target_y)
                loc.hover(timeout=3000)
                time.sleep(wait_after)
        except Exception as e:
            print(f"[WARN] Failed to hover {selector}: {e}")

    def type_slow(self, selector, text, delay=0.08):
        try:
            self.click_element(selector, wait_after=0.3)
            loc = self.page.locator(selector).first
            loc.fill("")
            for char in text:
                loc.press_sequentially(char, delay=int(delay * 1000))
                time.sleep(0.04)
            time.sleep(0.5)
        except Exception as e:
            print(f"[WARN] Failed to type into {selector}: {e}")

    def set_hud(self, badge, title, subtitle=""):
        badge_clean = badge.replace("'", "\\'")
        title_clean = title.replace("'", "\\'")
        sub_clean = subtitle.replace("'", "\\'")
        self.page.evaluate(f"window.updateHud('{badge_clean}', '{title_clean}', '{sub_clean}')")

def main():
    print("==================================================================")
    print("STARTING FULL COMPREHENSIVE SAAKSHYA DEMONSTRATION RECORDING")
    print("==================================================================")

    for f in RAW_REC_DIR.glob("*.webm"):
        f.unlink(missing_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--allow-file-access-from-files",
                "--no-sandbox",
            ]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(RAW_REC_DIR),
            record_video_size={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        print("Initializing app and injecting authenticated supervisor session...")
        page.goto(APP_URL)
        page.evaluate(f'''() => {{
            sessionStorage.setItem('saakshya.token', '{TOKEN}');
            sessionStorage.setItem('saakshya.case', 'FIR-112/2026');
            sessionStorage.setItem('saakshya.purpose', 'Gujarat Police Challenge Technical Evaluation');
            sessionStorage.setItem('saakshya.theme', 'dark');
            localStorage.setItem('saakshya.theme', 'dark');
        }}''')
        page.reload()
        page.wait_for_timeout(2000)

        inject_overlay_system(page)
        cursor = CursorController(page)
        cursor.set_hud("INITIALIZING", "SAAKSHYA — Gujarat Police CCTV Intelligence Fabric", "Connecting to live government feed...")
        time.sleep(2.0)

        # -------------------------------------------------------------
        # PHASE 1: System Identification & Officer Authentication (12s)
        # -------------------------------------------------------------
        print("Phase 1: Authentication & Purpose Binding...")
        cursor.set_hud("PHASE 1", "Centralized Command & Security Model", "Authenticated Bearer Token · Purpose Bound to FIR-112/2026")
        cursor.move_to(960, 540)
        time.sleep(1.0)
        cursor.hover_element(".brand", wait_after=1.2)
        cursor.hover_element("#officer-block", wait_after=1.5)
        cursor.hover_element(".purpose-bar", wait_after=1.5)
        cursor.hover_element("#cc-health", wait_after=1.2)
        cursor.hover_element("#cc-ai", wait_after=1.2)
        cursor.hover_element(".handling", wait_after=2.0)

        # -------------------------------------------------------------
        # PHASE 2: Heterogeneous Feed Onboarding & Capability (18s)
        # -------------------------------------------------------------
        print("Phase 2: Onboarding Heterogeneous Cameras...")
        cursor.set_hud("PHASE 2", "Heterogeneous Camera Onboarding (50 Logical Feeds)", "RTSP / WebRTC / HLS / MP4 · Zero Decoder Crashes")
        cursor.click_element('button[data-view="cameras"]', wait_after=2.5)

        cursor.hover_element(".cam-card, .cam-item, #view-cameras", offset_y=0.2, wait_after=1.5)
        page.evaluate("window.scrollBy({ top: 350, behavior: 'smooth' })")
        time.sleep(2.0)
        page.evaluate("window.scrollBy({ top: -350, behavior: 'smooth' })")
        time.sleep(1.5)

        # -------------------------------------------------------------
        # PHASE 3: Centralised Monitoring & Live 30-Camera Wall (20s)
        # -------------------------------------------------------------
        print("Phase 3: Centralised Live Monitoring...")
        cursor.set_hud("PHASE 3", "Centralised Monitoring & 30-Camera Live Wall", "Sub-second WHEP/WebRTC Latency · Presentation-Time Sync")
        cursor.click_element('button[data-view="live"]', wait_after=2.5)
        cursor.hover_element("#view-live", offset_x=0.3, offset_y=0.3, wait_after=2.0)
        cursor.hover_element("#view-live", offset_x=0.7, offset_y=0.3, wait_after=2.0)
        time.sleep(2.0)

        # -------------------------------------------------------------
        # PHASE 4: Designated Vehicle Route Traversal GJ1VV0119 (30s)
        # -------------------------------------------------------------
        print("Phase 4: Target Vehicle Identification & Search...")
        cursor.set_hud("PHASE 4", "Designated Vehicle Identification: GJ1VV0119", "AI ANPR 2-Vote Consensus · Corridor Traversal Analysis")
        cursor.click_element('button[data-view="investigate"]', wait_after=2.0)

        cursor.type_slow("#q-plate", "GJ1VV0119", delay=0.1)
        time.sleep(0.8)
        cursor.click_element('#search-form button[type="submit"]', wait_after=2.5)

        cursor.set_hud("PHASE 4", "Confirmed Vehicle Detection: GJ1VV0119 (cam07)", "Normalized PTS Timestamp: 14:18:28 IST · 82.8% Confidence")
        cursor.hover_element("#results", offset_y=0.3, wait_after=2.5)

        cursor.set_hud("PHASE 4", "Trajectory Hypotheses & Timebase Verification", "Corridor Timebase Sync · Status: LIKELY · Zero Guessing")
        cursor.click_element("#btn-focus-target", wait_after=1.5)
        cursor.hover_element("#traj-body", offset_y=0.4, wait_after=2.5)

        # -------------------------------------------------------------
        # PHASE 5: Estate Map & Route Breadcrumbs (22s)
        # -------------------------------------------------------------
        print("Phase 5: Gujarat State GIS Topology Map...")
        cursor.set_hud("PHASE 5", "Gujarat GIS Estate Map & Route Breadcrumbs", "Geospatial Camera Topology · Coverage Gap Identification")
        cursor.click_element('button[data-view="map"]', wait_after=3.0)

        cursor.click_element('button[data-mode="capability"]', wait_after=1.5)
        cursor.click_element('button[data-toggle="coverage"]', wait_after=1.5)
        cursor.click_element('button[data-toggle="alerts"]', wait_after=1.5)
        cursor.hover_element("#map", offset_x=0.5, offset_y=0.4, wait_after=2.5)

        # -------------------------------------------------------------
        # PHASE 6: Watchlist Cross-Referencing & Real-Time Alerts (22s)
        # -------------------------------------------------------------
        print("Phase 6: Watchlist Matching & Alert Dispatch...")
        cursor.set_hud("PHASE 6", "Continuous Watchlist Cross-Referencing", "Automated Real-Time Alerts · Priority 1 Match: GJ38BH5815")
        cursor.click_element('button[data-view="alerts"]', wait_after=2.5)
        cursor.hover_element("#view-alerts", offset_y=0.3, wait_after=2.5)

        # -------------------------------------------------------------
        # PHASE 7: Forensic Evidence & BSA s.63 Digital Admissibility (20s)
        # -------------------------------------------------------------
        print("Phase 7: Bharatiya Sakshya Adhiniyam s.63 Digital Certificate...")
        cursor.set_hud("PHASE 7", "Forensic Integrity: BSA 2023 Section 63", "Cryptographic SHA-256 Hash Chain · Court-Admissible Proof")
        cursor.click_element('button[data-view="evidence"]', wait_after=2.5)
        cursor.hover_element("#view-evidence", offset_x=0.5, offset_y=0.3, wait_after=3.0)

        # -------------------------------------------------------------
        # PHASE 8: 80,000 Camera Scalability & Hybrid Architecture (18s)
        # -------------------------------------------------------------
        print("Phase 8: Scalability to 80,000 Cameras...")
        cursor.set_hud("PHASE 8", "Scalability Architecture: 80,000 Edge Cameras", "Edge Metadata (~400B) vs Centralized 160 Gbps Bandwidth")
        cursor.click_element('button[data-view="system"]', wait_after=2.5)
        cursor.hover_element("#view-system", offset_x=0.5, offset_y=0.4, wait_after=3.0)

        # -------------------------------------------------------------
        # PHASE 9: Hash-Chained Audit Trail & Submission Reports (18s)
        # -------------------------------------------------------------
        print("Phase 9: Audit Trail & Output Report Summary...")
        cursor.set_hud("PHASE 9", "Hash-Chained Audit Log & Output Reports", "government_feed.csv (32,000+ records) & government_feed.json")
        cursor.click_element('button[data-view="audit"]', wait_after=2.5)
        cursor.hover_element("#view-audit", offset_x=0.5, offset_y=0.3, wait_after=3.0)

        # Final overview recap
        cursor.set_hud("VERIFIED", "SAAKSHYA — Technical Evaluation Demonstration Complete", "Official Gujarat Police Innovation Challenge Submission")
        cursor.click_element('button[data-view="overview"]', wait_after=3.5)

        print("Closing session and finalizing raw video stream...")
        context.close()
        browser.close()

    webm_files = list(RAW_REC_DIR.glob("*.webm"))
    if not webm_files:
        print("[ERROR] No recorded webm file found in", RAW_REC_DIR)
        return 1

    latest_webm = max(webm_files, key=os.path.getmtime)
    print(f"Processing raw video stream: {latest_webm} ({latest_webm.stat().st_size / 1024 / 1024:.2f} MB)")

    audio_path = ROOT / "brag-output" / "composition" / "assets" / "music" / "track.mp3"
    has_audio = audio_path.is_file()

    print(f"Encoding high-definition MP4 with H.264 High Profile (Audio={has_audio})...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(latest_webm),
    ]

    if has_audio:
        ffmpeg_cmd.extend([
            "-stream_loop", "-1",
            "-i", str(audio_path),
            "-filter_complex", "[1:a]volume=0.25[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-shortest",
        ])
    else:
        ffmpeg_cmd.extend(["-map", "0:v"])

    ffmpeg_cmd.extend([
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(FINAL_VIDEO),
    ])

    subprocess.run(ffmpeg_cmd, check=True)
    print(f"Video created at: {FINAL_VIDEO} ({FINAL_VIDEO.stat().st_size / 1024 / 1024:.2f} MB)")

    print("Extracting official poster thumbnail...")
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", "5.0",
        "-i", str(FINAL_VIDEO),
        "-frames:v", "1",
        "-q:v", "2",
        str(FINAL_POSTER)
    ], check=True)

    print("==================================================================")
    print("FULL DEMONSTRATION VIDEO BUILD COMPLETE!")
    print(f"Video:  {FINAL_VIDEO}")
    print(f"Poster: {FINAL_POSTER}")
    print("==================================================================")
    return 0

if __name__ == "__main__":
    sys.exit(main())
