"""Record a demonstration of the live workspace. No duration floor or cap.

This is not a slideshow of screenshots. Playwright records the real Chrome
tab at 1920×1080 while an operator-paced tour drives every surface the
evaluation asks for. Offline Indian-English speech is muxed afterwards.

    python tools/demo/record_launch_film.py \
        --base http://127.0.0.1:8080 \
        --token-file /tmp/saakshya-live-token.raw \
        --out var/demo/SAAKSHYA_launch

Nothing is mocked. If a panel is empty here, it is empty in the product.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))
from saakshya.common.paths import display

W, H = 1920, 1080
CASE = "FIR-000/2026"
PURPOSE = "live government grid verification"
PLATE = "GJ1VV0119"
LOOKALIKE = "6J1VV0119"
ALERT_PLATE = "GJ38BH5815"


def ffmpeg_bin() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def voice_name() -> str:
    """Prefer a clear Indian-English voice; fall back rather than fail."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
    names = [ln.split("  ")[0].strip() for ln in out.stdout.splitlines() if ln.strip()]
    for candidate in ("Aman", "Rishi", "Veena", "Daniel"):
        if any(n.startswith(candidate) for n in names):
            return candidate
    return "Samantha"


CHAPTERS = [
    ("title",
     "SAAKSHYA",
     "Evidence you can stand behind. Hybrid of Models 1, 2 and 3.",
     "This is Saakshya — साक्ष्य, evidence — a federated C C T V intelligence "
     "and evidence fabric proposed for the Gujarat Police Innovation Challenge. "
     "Everything you are about to see is the real interface, driven against a "
     "live server on the government-provided grid. Nothing is staged, and nothing "
     "is a mock-up. Hybrid of models one, two and three. Model four — central "
     "recording of every camera — was rejected on arithmetic, not left unfinished."),
    ("signin",
     "Sign in",
     "A case and a purpose are standing furniture, not a dialog dismissed once.",
     "Sign in is a bearer token held in this tab only. Before the workspace "
     "opens, the officer states a case identifier and a purpose. Both are written "
     "into every audit record. A search without a stated purpose is refused."),
    ("overview",
     "Shift picture",
     "What is on fire, which cameras published a mark, and that ANPR GOOD is not emptiness.",
     "A shift begins on the command picture. Four numbers: cameras onboarded, "
     "how many are showing a frame, marks read in the last hour, and alerts still open. "
     "Then what the estate can actually prove — graded from each camera's own stream — "
     "the open alerts, and the plates with the camera that published them."),
    ("live",
     "Live government wall",
     "Thirty government cameras. Live stills, then WebRTC video on the camera you open.",
     "The live wall. Thirty government cameras from the Sentinel sandbox. "
     "Focus, two-up, grid, dense, and a table — same estate, different layouts. "
     "Each tile is a still the platform already decoded, with vehicles and plates boxed. "
     "Click one camera: one extra stream copy, R T S P over T C P, paced from presentation timestamps. "
     "Stills on this wall are ingest, not thirty extra clients. "
     "That is Model 2, honestly: a wall of stills, and live video when you ask "
     "for a camera, not thirty extra clients on the organiser's grid."),
    ("map",
     "Estate map",
     "Street map of Gujarat. Nineteen placed. Eleven listed, not invented.",
     "The estate map. A real street basemap of Gujarat, with camera markers "
     "where a name was enough to place them. Nineteen on the map. That is Model 1 — "
     "registry and G I S, mandatory, kept. Precision is drawn as a radius — "
     "a landmark is not a survey. Eleven more remain in the registry strip "
     "because a name was not enough. They are listed, not invented onto the map."),
    ("cameras",
     "Measured capability",
     "A N P R unsuitable is yield at this geometry, not emptiness.",
     "Every camera is graded from its own stream, never from a catalogue claim. "
     "Unsuitable for A N P R means yield is too low to rely on — a busy junction "
     "whose plates are forty pixels wide will read none. Cameras that nevertheless "
     "published a mark show that count beside the grade. The two facts are not the "
     "same, and this table refuses to collapse them."),
    ("find",
     "Designated mark",
     "Find, with the basis of every match, on the live government store.",
     "The evaluation asks us to identify a designated vehicle by registration "
     "mark. On this live grid we rehearse G J 1 V V 0 1 1 9. Every candidate "
     "carries the basis of its match. A one-camera pattern is labelled as such — "
     "looping footage, not a fleet. Cross-camera identity on this government "
     "feed is measured at zero repeats. The synthetic corpus is where two-camera "
     "traces exist by construction, and we will not substitute it for this store."),
    ("lookalike",
     "Lookalike, not an edit",
     "An O-slash-zero confusion is offered. The stored read is not rewritten.",
     "If the panel types a near mark, search still finds the stored read and "
     "labels it an O C R lookalike requiring verification. The stored registration "
     "is not edited. Trajectory on a single camera has no interval to reason about, "
     "so its place on a timeline is marked restricted or refused — never guessed."),
    ("alerts",
     "Watchlist and alert",
     "Representative watchlist. Automated alert on a match. Not a government feed.",
     "A representative watchlist, ours, not a government list. G J 3 8 B H 5 8 1 5 "
     "is stolen-vehicle, high, open, on cam twenty-one. Category, priority and "
     "confidence are on the row so an officer can triage before opening it. "
     "Continuous cross-reference runs in ingest, not as a page refresh."),
    ("analytics",
     "What the estate can actually do",
     "Yield, timebase clusters, and the cameras that may share a timeline.",
     "Analytics answers a different question from Cameras. What can this estate "
     "actually do? Distinct marks in the live store. Person observations from the "
     "same detector pass, never plated. Timebase: thirteen cameras share one "
     "measured cluster. cam one and cam twenty-one do not. Joining those would "
     "draw a journey that never happened, so the system refuses."),
    ("system",
     "Hybrid architecture",
     "Models 1 plus 2 plus 3. Model 4 rejected on modelled bandwidth.",
     "The submitted architecture is a hybrid. Model 1, registry and G I S, "
     "mandatory and kept. Model 2, unified viewing as ingest stills plus one live "
     "Web R T C copy when an officer opens a camera. Model 3, "
     "federation: government R T S P plus local media, with the observation store "
     "as the metadata bus. Model 4, central V M S recording of eighty thousand "
     "cameras, is modelled at one hundred and sixty gigabits per second. Not built. "
     "The arithmetic is the justification. Face recognition is a deliberate abstention."),
    ("checklist",
     "Sentinel sandbox checklist",
     "How this platform consumes the government grid. Protocol, not a slide.",
     "The organiser's integration checklist, on this running system. "
     "Every client forces R T S P over T C P. Timing is driven from presentation "
     "timestamps, never from declared frame rate, never from arrival time. "
     "Inter-frame gaps do not stall the pipeline. Reconnect uses exponential backoff, "
     "two seconds, capped at thirty. Decoder warnings on join are logged, not fatal. "
     "The camera list is the catalogue contract; until that endpoint is served we "
     "probe and label the source as probe. Mixed H two six four and H two six five, "
     "mixed resolutions, no fixed-shape batch. A scene discontinuity at the loop "
     "point flushes tracks rather than inventing a journey. We consume. We do not "
     "publish to the gateway."),
    ("evidence",
     "Evidence and audit",
     "Hash-chained. B S A section 63 unsigned. A refusal is recorded as carefully as a result.",
     "Evidence is hash-chained and append-only. Integrity and truthfulness are "
     "reported apart: a record whose wording overstates what it holds raises a "
     "caution without breaking the chain. We do not retain government footage, "
     "and the manifest says so. The audit log attributes every query — actor, "
     "role, case and purpose."),
    ("copilot",
     "Copilot — last, and optional",
     "Gemini on or off, in the masthead. Sixteen read-only tools either way.",
     "The copilot is last on purpose. It is not in the mandatory chain. The "
     "masthead switch turns Gemini on or off. On: Gemini coordinates sixteen "
     "read-only tools. Off: deterministic rules answer from the same tools, and "
     "no investigation data leaves this host. Search, trajectory, watchlist, "
     "alerting and evidence never called a language model. We will now ask it, "
     "and then ask it to do something it must refuse."),
    ("copilot_ask",
     "With tools, without invention",
     "Estate question. Grounded in tool results. No plate is invented.",
     "Which cameras cannot read plates? The estate specialist runs. The answer "
     "is pinned to cameras the tool actually returned. If Gemini cannot complete, "
     "the warning is on screen: answered from deterministic rules, no data left "
     "this deployment, the investigation chain is unaffected."),
    ("copilot_refuse",
     "A refusal, recorded",
     "Enhance this still. Sharpen the plate. The copilot will not.",
     "Enhance this still and sharpen the plate. The copilot will not. Stills are "
     "never enhanced. Detection and A N P R stay on this host. A government frame "
     "is not sent off-box to look like a better read. That refusal is the product."),
    ("copilot_time",
     "Timebase in plain language",
     "May cam one and cam twenty-one share a timeline? The system already knows.",
     "May cam zero one and cam twenty-one share a timeline? This is the same "
     "verdict the trajectory panel already showed, now in a sentence. Allowed, "
     "restricted, or refused — never estimated. Then: may cam zero one and cam "
     "zero four? The cluster that was measured."),
    ("close",
     "What we will not claim",
     "Not production ready. Not legally admissible. Not tested at eighty thousand.",
     "We will not say this is production ready. We will not say it is legally "
     "admissible — a B S A signature is a human act, and the certificate stays "
     "draft pending signature. We will not say it was tested at eighty thousand "
     "cameras. We have thirty of the issued grid, measured, with eleven unlocated. "
     "Saakshya — evidence you can stand behind."),
]


SLATE_SHOW = """({title, dek, kicker}) => {
  let s = document.getElementById('launch-slate');
  if (!s) {
    s = document.createElement('div');
    s.id = 'launch-slate';
    s.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#161412;'
      + 'color:#f3eee7;display:flex;flex-direction:column;justify-content:center;'
      + 'padding:12vh 12vw;font-family:ui-sans-serif,system-ui,sans-serif;';
    document.body.appendChild(s);
  }
  s.style.display = 'flex';
  s.style.pointerEvents = 'auto';
  s.removeAttribute('hidden');
  const k = document.createElement('div');
  k.style.cssText = 'font-size:13px;letter-spacing:.22em;text-transform:uppercase;color:#c45c32;font-weight:600';
  k.textContent = kicker;
  const h = document.createElement('h1');
  h.style.cssText = 'font-size:64px;line-height:1.05;margin:18px 0 20px;font-weight:650;letter-spacing:-0.03em';
  h.textContent = title;
  const p = document.createElement('p');
  p.style.cssText = 'font-size:26px;line-height:1.4;max-width:22em;color:#c9bfb3;margin:0';
  p.textContent = dek;
  const foot = document.createElement('div');
  foot.style.cssText = 'position:absolute;bottom:48px;left:12vw;right:12vw;display:flex;justify-content:space-between;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#8a8178';
  const a = document.createElement('span');
  a.textContent = 'Gujarat Police Innovation Challenge 2026';
  const b = document.createElement('span');
  b.textContent = 'Official · sensitive';
  foot.append(a, b);
  s.replaceChildren(k, h, p, foot);
}"""

SLATE_HIDE = """() => {
  const s = document.getElementById('launch-slate');
  if (!s) return;
  s.style.display = 'none';
  s.style.pointerEvents = 'none';
  s.setAttribute('hidden', '');
}"""


class Tour:
    """Drive the real workspace. Short slates; narration continues over the UI."""

    SLATE_MS = 4200
    FULL_SLATE = frozenset({"title", "close"})

    def __init__(self, page, token: str, log: list[dict], rec=None):
        self.page = page
        self.token = token
        self.log = log
        self.rec = rec
        self.t0 = time.monotonic()
        self.marks: dict[str, float] = {}

    def mark(self, chapter: str) -> None:
        now = time.monotonic()
        self.marks[chapter] = now
        self.log.append({"t": round(now - self.t0, 2), "chapter": chapter})
        print(f"  {self.log[-1]['t']:7.1f}s  {chapter}", flush=True)

    def hold(self, ms: int) -> None:
        if ms <= 0:
            return
        if self.rec is not None:
            self.rec.hold(ms)
        else:
            self.page.wait_for_timeout(ms)

    def spoken_ms(self, key: str) -> int:
        speech = next(c[3] for c in CHAPTERS if c[0] == key)
        return int((len(speech.split()) / 148.0 * 60.0 + 2.2) * 1000)

    def chapter(self, key: str) -> None:
        meta = next(c for c in CHAPTERS if c[0] == key)
        _, title, dek, _speech = meta
        self.page.evaluate(SLATE_SHOW, {
            "title": title, "dek": dek, "kicker": "SAAKSHYA  ·  સાક્ષ્ય"})
        self.mark(key)
        if key in self.FULL_SLATE:
            self.hold(self.spoken_ms(key))
        else:
            self.hold(self.SLATE_MS)
        self.page.evaluate(SLATE_HIDE)
        self.hold(350)

    def finish(self, key: str, extra_ms: int = 7000) -> None:
        """Finish the VO, then linger on the product."""
        elapsed_ms = (time.monotonic() - self.marks[key]) * 1000
        remain_vo = self.spoken_ms(key) - elapsed_ms
        if remain_vo > 200:
            self.hold(int(remain_vo))
        if extra_ms > 0:
            self.hold(extra_ms)

    def nav(self, view: str, wait_ms: int = 1800) -> None:
        sel = (
            f'button.primary-nav[data-view="{view}"]'
            if view in {
                "overview", "investigate", "alerts", "evidence",
                "live", "cameras", "analytics", "system"}
            else f'button.sub-nav[data-view="{view}"]')
        self.page.locator(sel).scroll_into_view_if_needed()
        box = self.page.locator(sel).bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2,
                                 box["y"] + box["height"] / 2)
            self.hold(180)
        self.page.locator(sel).click(force=True)
        self.hold(wait_ms)

    def wait_text(self, js: str, timeout: int = 45000, what: str = "") -> bool:
        deadline = time.monotonic() + timeout / 1000.0
        while time.monotonic() < deadline:
            try:
                if self.page.evaluate(js):
                    return True
            except Exception:
                pass
            self.hold(280)
        print(f"    wait skipped {what or js[:40]}: TimeoutError",
              flush=True)
        return False

    def bots(self) -> int:
        return int(self.page.evaluate(
            "() => document.querySelectorAll('#chat-log .msg.bot').length"))

    def ask(self, text: str, delay: int = 22) -> int:
        p = self.page
        before = self.bots()
        p.fill("#chat-input", "")
        p.type("#chat-input", text, delay=delay)
        self.hold(300)
        p.locator("#chat-form button[type=submit]").click(force=True)
        self.wait_text(
            f"() => document.querySelectorAll('#chat-log .msg.bot').length > {before}",
            90000, "copilot reply")
        try:
            p.locator("#chat-log .msg.bot").last.scroll_into_view_if_needed()
        except Exception:
            pass
        return self.bots()

    def run(self) -> None:
        p = self.page
        self.chapter("title")
        self.hold(2500)

        self.chapter("signin")
        p.evaluate("() => { const g = document.getElementById('gate'); if (g) g.hidden = false; }")
        self.hold(2200)
        p.fill("#gate-case", CASE)
        self.hold(450)
        p.fill("#gate-purpose", PURPOSE)
        self.hold(700)
        p.fill("#gate-token", self.token)
        self.hold(500)
        p.locator("#gate-form button[type=submit]").click(force=True)
        self.wait_text(
            "() => /supervisor\\.live/i.test(document.getElementById('who')?.textContent || '')",
            25000, "signed in")
        p.evaluate(
            """({caseId, purpose}) => {
              const c = document.getElementById('case-id');
              const q = document.getElementById('purpose');
              if (c) { c.value = caseId; c.dispatchEvent(new Event('input', {bubbles:true})); }
              if (q) { q.value = purpose; q.dispatchEvent(new Event('input', {bubbles:true})); }
              localStorage.setItem('saakshya.theme', 'light');
              document.documentElement.dataset.theme = 'light';
            }""",
            {"caseId": CASE, "purpose": PURPOSE})
        self.nav("overview", 800)
        self.wait_text(
            "() => !document.querySelector('#overview .loading-note') "
            "&& /Cameras onboarded/i.test(document.body.innerText) "
            "&& document.querySelectorAll('#overview .kpi .big').length >= 4",
            120000, "overview filled after sign-in")
        self.finish("signin", 2500)

        self.chapter("overview")
        self.nav("overview", 800)
        self.wait_text(
            "() => !document.querySelector('#overview .loading-note') "
            "&& /Cameras onboarded/i.test(document.body.innerText) "
            "&& /What the estate can prove/i.test(document.body.innerText)",
            120000, "overview stats")
        self.hold(4000)
        try:
            p.locator("#overview .plate-gallery, #overview .ov-card").last.scroll_into_view_if_needed()
        except Exception:
            pass
        self.wait_text(
            "() => document.querySelectorAll('#overview .plate-card').length >= 4",
            20000, "overview plate cards")
        self.hold(5000)
        self.finish("overview", 5000)

        self.chapter("live")
        self.nav("live", 2500)
        self.wait_text(
            "() => document.querySelectorAll('#live .live-tile').length >= 20",
            90000, "live tiles")
        self.wait_text(
            "() => { const s = document.querySelector('#live-stage img'); "
            "return !!(s && s.naturalWidth > 40); }",
            120000, "live focus stage")
        self.wait_text(
            "() => /Live/.test(document.querySelector('#live-stage .hud-chip.live')?.textContent || '')",
            40000, "live chip")
        self.wait_text(
            "() => [...document.querySelectorAll('#live .live-tile .frame img, #live-stage img')]"
            ".filter(i => i.naturalWidth > 40).length >= 6",
            90000, "live frames")
        self.hold(10000)
        try:
            p.locator("#live-filters button").filter(has_text="Ahmedabad").click(force=True)
            self.hold(4000)
            p.locator("#live-filters button").filter(has_text="All").click(force=True)
            self.hold(2500)
        except Exception as exc:
            print(f"    district filter: {type(exc).__name__}", flush=True)
        for cam in ("cam01", "cam21", "cam06"):
            try:
                loc = p.locator(f'#live-strip .live-tile[data-camera="{cam}"]')
                loc.scroll_into_view_if_needed()
                self.hold(400)
                loc.click(force=True)
                self.wait_text(
                    "() => { const s = document.querySelector('#live-stage img'); "
                    "return !!(s && s.naturalWidth > 40); }",
                    25000, f"live {cam}")
                self.wait_text(
                    "() => /Live/.test(document.querySelector('#live-stage .hud-chip.live')?.textContent || '')",
                    20000, f"live {cam} chip")
                self.hold(9000)
                p.locator("#here-plates").scroll_into_view_if_needed()
                self.hold(2500)
            except Exception as exc:
                print(f"    live {cam}: {type(exc).__name__}", flush=True)
        for layout, hold_ms in (("grid", 4200), ("dense", 3600), ("tab", 3200),
                                ("twoup", 3600), ("focus", 5000)):
            try:
                p.locator(f'[data-live-layout="{layout}"]').click(force=True)
                self.hold(hold_ms)
            except Exception as exc:
                print(f"    layout {layout}: {type(exc).__name__}", flush=True)
        try:
            p.locator('#live-strip .live-tile[data-camera="cam01"]').click(force=True)
            self.hold(6000)
        except Exception as exc:
            print(f"    live focus: {type(exc).__name__}", flush=True)
        p.mouse.wheel(0, -2000)
        self.hold(1500)
        self.finish("live", 5000)

        self.chapter("map")
        self.nav("map", 2800)
        self.wait_text(
            "() => /on the map/i.test(document.body.innerText) "
            "|| document.querySelectorAll('#registry-rail .registry-chip, "
            "#registry-rail img').length >= 8",
            45000, "estate map")
        try:
            p.locator("#btn-fit2").click(force=True)
        except Exception:
            pass
        self.wait_text(
            "() => document.querySelector('#map2')?.classList.contains('over-basemap') "
            "|| document.querySelector('#view-map canvas.over-basemap')",
            40000, "street tiles")
        self.hold(6000)
        try:
            p.locator('#view-map button[data-toggle="labels"]').click(force=True)
        except Exception:
            try:
                p.locator('#view-map button:has-text("Labels")').click(force=True)
            except Exception:
                pass
        self.hold(5000)
        box = p.locator("#map2").bounding_box()
        if box:
            p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            for _ in range(4):
                p.mouse.wheel(0, -180)
                self.hold(900)
            self.hold(4000)
            p.mouse.down()
            p.mouse.move(box["x"] + box["width"] / 2 + 80,
                         box["y"] + box["height"] / 2 + 40, steps=12)
            p.mouse.up()
        self.hold(6000)
        p.mouse.wheel(0, 280)
        self.hold(4000)
        self.finish("map", 6000)

        self.chapter("cameras")
        self.nav("cameras", 1600)
        self.wait_text(
            "() => document.querySelectorAll('#cameras table.data tbody tr').length >= 20 "
            "&& /published a mark/i.test(document.body.innerText)",
            120000, "camera table")
        self.hold(8000)
        p.mouse.wheel(0, 700)
        self.hold(7000)
        self.finish("cameras", 6000)

        self.chapter("find")
        self.nav("investigate", 1600)
        p.fill("#q-type", "")
        p.fill("#q-camera", "")
        p.fill("#q-plate", "")
        p.type("#q-plate", PLATE, delay=65)
        self.hold(400)
        p.locator("#search-form button.primary").click(force=True)
        self.wait_text(
            "() => { const n = document.getElementById('result-count'); "
            "return n && /observation/.test(n.textContent || ''); }",
            60000, "plate search")
        self.hold(5000)
        try:
            p.locator("#results .result").first.click(force=True)
        except Exception:
            pass
        self.hold(12000)
        self.finish("find", 6000)

        self.chapter("lookalike")
        p.fill("#q-plate", "")
        p.type("#q-plate", LOOKALIKE, delay=65)
        p.check("#q-fuzzy")
        self.hold(350)
        p.locator("#search-form button.primary").click(force=True)
        self.wait_text(
            "() => /lookalike|REQUIRES_VERIFICATION|near match|one camera/i"
            ".test(document.body.innerText)",
            45000, "lookalike")
        self.hold(9000)
        p.fill("#q-plate", "")
        p.fill("#q-type", "person")
        p.fill("#q-camera", "cam28")
        self.hold(350)
        p.locator("#search-form button.primary").click(force=True)
        self.wait_text(
            "() => /person/i.test(document.getElementById('result-count')?.textContent || '') "
            "|| /observation/.test(document.getElementById('result-count')?.textContent || '')",
            45000, "person search")
        self.hold(10000)
        p.fill("#q-type", "")
        p.fill("#q-camera", "")
        self.finish("lookalike", 5000)

        self.chapter("alerts")
        self.nav("alerts", 1600)
        self.wait_text(
            f"() => /{ALERT_PLATE}/.test(document.body.innerText)",
            30000, "watchlist alert")
        self.finish("alerts", 5000)

        self.chapter("analytics")
        self.nav("analytics", 1600)
        self.wait_text(
            "() => /UNSUITABLE|distinct marks|timebase/i.test(document.body.innerText) "
            "&& !/Loading from the live store/i.test(document.body.innerText)",
            120000, "analytics filled")
        self.hold(8000)
        p.mouse.wheel(0, 650)
        self.hold(8000)
        self.finish("analytics", 5000)

        self.chapter("system")
        self.nav("system", 1600)
        self.wait_text(
            "() => /hybrid of models/i.test(document.body.innerText) "
            "|| /Model 4/i.test(document.body.innerText)",
            90000, "architecture")
        self.hold(6000)
        p.mouse.wheel(0, 720)
        self.hold(6000)
        p.mouse.wheel(0, 720)
        self.hold(6000)
        self.finish("system", 5000)

        self.chapter("checklist")
        self.nav("cameras", 1600)
        self.hold(8000)
        p.mouse.wheel(0, 900)
        self.hold(7000)
        self.nav("system", 1600)
        self.hold(8000)
        p.mouse.wheel(0, 600)
        self.hold(8000)
        self.finish("checklist", 5000)

        self.chapter("copilot")
        try:
            p.locator("#btn-gemini").click(force=True)
            self.hold(2500)
            p.locator("#btn-gemini").click(force=True)
            self.hold(2000)
        except Exception:
            pass
        self.nav("copilot", 2200)
        self.wait_text(
            "() => /gemini|local rules|read-only tools/i.test(document.body.innerText)",
            30000, "copilot configured")
        self.finish("copilot", 5000)

        self.chapter("copilot_ask")
        self.ask("Which cameras are graded UNSUITABLE for ANPR?")
        self.hold(14000)
        self.finish("copilot_ask", 6000)

        self.chapter("copilot_refuse")
        self.ask("Enhance this still and sharpen the plate so I can read it.")
        self.wait_text(
            "() => /refuse|never enhanced|fabricat|will not/i.test("
            "document.getElementById('chat-log')?.innerText || '')",
            20000, "imagery refusal")
        self.hold(12000)
        self.finish("copilot_refuse", 5000)

        self.chapter("copilot_time")
        self.ask("May cam01 and cam21 share a timeline?")
        self.wait_text(
            "() => /REFUSED|refused/i.test(document.getElementById('chat-log')?.innerText || '')",
            30000, "timebase refuse")
        self.hold(10000)
        self.ask("May cam01 and cam04 share a timeline?")
        self.wait_text(
            "() => /ALLOWED|allowed|RESTRICTED|restricted/i.test("
            "document.getElementById('chat-log')?.innerText || '')",
            30000, "timebase allow")
        self.hold(12000)
        self.finish("copilot_time", 5000)

        self.chapter("evidence")
        self.nav("audit", 1800)
        self.wait_text(
            "() => /chain verified|CHAIN BROKEN|audit/i.test("
            "document.getElementById('view-audit')?.innerText || document.body.innerText)",
            45000, "audit log")
        self.hold(12000)
        self.nav("evidence", 1800)
        self.wait_text(
            "() => /Evidence subsystem/i.test(document.body.innerText) "
            "|| /Evidence chain verified/i.test(document.body.innerText) "
            "|| /EVIDENCE CHAIN BROKEN/i.test(document.body.innerText) "
            "|| /Recomputing manifests/i.test(document.body.innerText)",
            20000, "evidence first paint")
        self.hold(16000)
        self.finish("evidence", 5000)

        self.chapter("close")
        self.nav("overview", 1200)
        self.hold(18000)


def record_browser(base: str, token: str, work: Path) -> tuple[Path, list[dict]]:
    from playwright.sync_api import sync_playwright

    from hq_capture import CURSOR_JS, JpegFilm

    work.mkdir(parents=True, exist_ok=True)
    picture = work / "picture.mp4"
    log: list[dict] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                channel="chrome", headless=True,
                args=[
                    "--autoplay-policy=no-user-gesture-required",
                    "--use-fake-ui-for-media-stream",
                    "--disable-blink-features=AutomationControlled",
                ])
        except Exception:
            browser = pw.chromium.launch(
                headless=True,
                args=["--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            device_scale_factor=1)
        page = ctx.new_page()
        page.goto(f"{base}/ui/?v=cr086", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        page.evaluate(CURSOR_JS)
        rec = JpegFilm(page, picture, ffmpeg_bin(), fps=12, quality=94)
        try:
            Tour(page, token, log, rec).run()
        finally:
            rec.close()
        page.close()
        ctx.close()
        browser.close()
    if not picture.is_file() or picture.stat().st_size < 10_000:
        raise SystemExit("JPEG film did not write a picture")
    return picture, log


def say_chapter(ff: str, voice: str, text: str, dest: Path) -> float:
    aiff = dest.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-r", "148", "-o", str(aiff), text],
                   check=True)
    wav = dest.with_suffix(".wav")
    subprocess.run(
        [ff, "-y", "-i", str(aiff), "-ar", "44100", "-ac", "2", str(wav)],
        check=True, capture_output=True)
    aiff.unlink(missing_ok=True)
    probe = subprocess.run([ff, "-i", str(wav)], capture_output=True, text=True)
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def mux(ff: str, video: Path, log: list[dict], out: Path, work: Path) -> None:
    voice = voice_name()
    print(f"narrating with {voice}", flush=True)
    by_key = {c[0]: c[3] for c in CHAPTERS}
    parts = []
    for i, ev in enumerate(log):
        text = by_key.get(ev["chapter"])
        if not text:
            continue
        wav = work / f"n{i:02d}.wav"
        dur = say_chapter(ff, voice, text, wav)
        start = ev["t"] + 0.35
        print(f"  VO {ev['chapter']:<16} t={start:6.1f}s  speech={dur:5.1f}s")
        parts.append((wav, start, dur))

    # Mix delayed tracks onto a silent bed matching the video duration.
    probe = subprocess.run([ff, "-i", str(video)], capture_output=True, text=True)
    vdur = 0.0
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            vdur = int(h) * 3600 + int(m) * 60 + float(s)
            break
    print(f"picture {vdur:.1f}s", flush=True)

    filters = []
    labels = []
    inputs = ["-i", str(video)]
    for i, (wav, start, _dur) in enumerate(parts):
        inputs += ["-i", str(wav)]
        delay_ms = max(0, int(start * 1000))
        filters.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms},volume=1.0[a{i}]")
        labels.append(f"[a{i}]")
    n = len(parts)
    if n == 0:
        raise SystemExit("no narration parts")
    # Picture length is the tour length. No 15-minute floor and no cap.
    target = vdur
    if vdur < 60:
        print(f"WARNING: picture is only {vdur:.1f}s — the tour did not run.",
              file=sys.stderr)
    filters.append(
        f"{''.join(labels)}amix=inputs={n}:duration=longest:dropout_transition=0:normalize=0,"
        f"apad=whole_dur={target:.3f}[aout]")
    bed = work / "voice.wav"
    mix = subprocess.run(
        [ff, "-y", *inputs,
         "-filter_complex", ";".join(filters),
         "-map", "[aout]", "-t", f"{target:.3f}", "-ar", "44100", "-ac", "2",
         str(bed)],
        capture_output=True, text=True)
    if mix.returncode != 0:
        print(mix.stderr[-2000:], file=sys.stderr)
        raise SystemExit("voice mix failed")

    final = out.with_suffix(".mp4")
    pad = target - vdur
    if pad > 0.05:
        vargs = ["-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
                 "-crf", "15", "-profile:v", "high"]
    else:
        vargs = ["-c:v", "copy"]
    enc = subprocess.run(
        [ff, "-y", "-i", str(video), "-i", str(bed),
         *vargs,
         "-c:a", "aac", "-b:a", "320k",
         "-t", f"{target:.3f}", "-movflags", "+faststart",
         str(final)],
        capture_output=True, text=True)
    if enc.returncode != 0:
        print(enc.stderr[-2000:], file=sys.stderr)
        raise SystemExit("encode failed")
    mb = final.stat().st_size / 1e6
    print(f"\nlaunch film : {display(final)} ({target/60:.1f} min, {mb:.1f} MB)",
          flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--token-file", default="")
    ap.add_argument("--out", default="var/demo/SAAKSHYA_launch")
    ap.add_argument("--mux-only", action="store_true",
                    help="Remux an existing webm + chapters.json; do not record")
    a = ap.parse_args()
    out = Path(a.out)
    work = out.parent / "launch_work"
    work.mkdir(parents=True, exist_ok=True)
    if a.mux_only:
        log = json.loads((work / "chapters.json").read_text())
        picture = work / "picture.mp4"
        if not picture.is_file():
            webs = list((work / "raw").glob("*.webm"))
            if not webs:
                raise SystemExit("no picture.mp4 or webm in launch_work")
            picture = max(webs, key=lambda p: p.stat().st_mtime)
        print(f"mux-only {picture.name} → {display(out)}.mp4", flush=True)
        mux(ffmpeg_bin(), picture, log, out, work)
        return 0
    if not a.token_file:
        raise SystemExit("--token-file is required unless --mux-only")
    token = Path(a.token_file).read_bytes().strip().decode("ascii")
    out = Path(a.out)
    work = out.parent / "launch_work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"recording launch film at {a.base} → {display(out)}.mp4")
    t0 = time.time()
    webm, log = record_browser(a.base, token, work)
    (work / "chapters.json").write_text(json.dumps(log, indent=2))
    print(f"raw picture {webm} ({time.time()-t0:.0f}s to drive)", flush=True)
    mux(ffmpeg_bin(), webm, log, out, work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
