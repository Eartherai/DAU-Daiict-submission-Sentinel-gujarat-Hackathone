"""Record the designated-vehicle path on the own controlled corpus.

The government grid has 0 cross-camera plate repeats. Expected outputs 1–3
(identify, timestamped route, watchlist alert) exist together on `var/demo.db`.
This film is that store — never labelled as the live grid.

    python tools/demo/record_designated_film.py \
        --base http://127.0.0.1:8081 \
        --token-file /tmp/saakshya-demo-token.raw \
        --out var/demo/SAAKSHYA_designated

Do not point this at port 8080 / live.db.
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
CASE = "FIR-214/2026"
PURPOSE = "designated vehicle on own CCTV"
PLATE = "GJ18JX7786"
PLATE2 = "GJ35BV6925"
ALERT = "GJ15NT6564"


def ffmpeg_bin() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def voice_name() -> str:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
    names = [ln.split("  ")[0].strip() for ln in out.stdout.splitlines() if ln.strip()]
    for candidate in ("Aman", "Rishi", "Veena", "Daniel"):
        if any(n.startswith(candidate) for n in names):
            return candidate
    return "Samantha"


CHAPTERS = [
    ("title",
     "Designated vehicle",
     "Own CCTV. Faces, vehicles, plates. Watchlist match. Not the government grid.",
     "This is Saakshya on our own feed. Faces and vehicles from recordings we onboarded. "
     "Plates and a two-camera route on the local corpus. A watchlist alert when ingest matched. "
     "Not the government grid."),
    ("signin",
     "Sign in",
     "Case and purpose on every query.",
     "Sign in with a short-lived token. Case and purpose stated before the workspace opens."),
    ("live",
     "Own cameras, live",
     "People, traffic, then plates. Boxes from this store.",
     "Own cameras. People and faces are presence, not identity. Traffic shows vehicles boxed. "
     "Then a plate camera from the local corpus. Watchlist matching runs in ingest."),
    ("find",
     "Identify",
     "G J 1 8 J X 7 7 8 6 — found on two cameras.",
     "Find G J one eight J X seven seven eight six. Two observations: Naroda Circle and the depot gate. "
     "Each row carries the basis of the match."),
    ("route",
     "Route",
     "Timestamped movement. Timebase stated, not guessed.",
     "The movement panel builds the route. Camera sequence, clocks, and the interval. "
     "The timebase verdict sits first."),
    ("alerts",
     "Watchlist",
     "Representative list. Automated alert on a match.",
     "A representative watchlist — ours. G J one eight J X seven seven eight six is stolen-vehicle, open, "
     "and a second mark is high. Continuous cross-reference is ingest."),
    ("map",
     "Estate map",
     "OpenStreetMap streets. Nothing invented onto the map.",
     "The estate map uses OpenStreetMap streets. Cameras sit where a name was enough to place them."),
    ("federation",
     "Federation",
     "M3 · adapters, event fabric, unchanged source systems.",
     "The federation layer keeps source systems independent. Adapters normalize access and events, "
     "then route only the metadata and authorised viewing sessions that the command centre needs."),
    ("copilot",
     "Copilot",
     "A real question against this store.",
     "Ask where that mark was seen. The answer comes from the same tools as Find. "
     "It will not invent a plate or identify a face."),
    ("close",
     "What this is not",
     "Not the live grid. The live grid still has zero cross-camera repeats.",
     "This film is the local corpus. The government film is the live grid. "
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
  h.style.cssText = 'font-size:56px;line-height:1.05;margin:18px 0 20px;font-weight:650;letter-spacing:-0.03em';
  h.textContent = title;
  const p = document.createElement('p');
  p.style.cssText = 'font-size:24px;line-height:1.4;max-width:22em;color:#c9bfb3;margin:0';
  p.textContent = dek;
  const foot = document.createElement('div');
  foot.style.cssText = 'position:absolute;bottom:48px;left:12vw;right:12vw;display:flex;justify-content:space-between;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#8a8178';
  const a = document.createElement('span');
  a.textContent = 'Gujarat Police Innovation Challenge 2026';
  const b = document.createElement('span');
  b.textContent = 'OWN CONTROLLED CORPUS  ·  not government data';
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
    SLATE_MS = 3800
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
            "title": title, "dek": dek,
            "kicker": "SAAKSHYA  ·  designated vehicle  ·  own feed"})
        self.mark(key)
        if key in self.FULL_SLATE:
            self.hold(self.spoken_ms(key))
        else:
            self.hold(self.SLATE_MS)
        self.page.evaluate(SLATE_HIDE)
        self.hold(300)

    def finish(self, key: str, extra_ms: int = 7000) -> None:
        elapsed_ms = (time.monotonic() - self.marks[key]) * 1000
        remain_vo = self.spoken_ms(key) - elapsed_ms
        if remain_vo > 200:
            self.hold(int(remain_vo))
        if extra_ms > 0:
            self.hold(extra_ms)

    def nav(self, view: str, wait_ms: int = 1400) -> None:
        sel = (
            f'button.primary-nav[data-view="{view}"]'
            if view in {
                "overview", "investigate", "alerts", "evidence", "intelligence",
                "live", "cameras", "analytics", "system"}
            else f'button.sub-nav[data-view="{view}"]')
        self.page.locator(sel).scroll_into_view_if_needed()
        box = self.page.locator(sel).bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2,
                                 box["y"] + box["height"] / 2)
            self.hold(160)
        self.page.locator(sel).click(force=True)
        self.hold(wait_ms)

    def ask(self, text: str, delay: int = 22) -> None:
        p = self.page
        before = int(p.evaluate(
            "() => document.querySelectorAll('#chat-log .msg.bot').length"))
        p.fill("#chat-input", "")
        p.type("#chat-input", text, delay=delay)
        self.hold(250)
        p.locator("#chat-form button[type=submit]").click(force=True)
        self.wait_text(
            f"() => document.querySelectorAll('#chat-log .msg.bot').length > {before}",
            90000, "copilot reply")
        try:
            p.locator("#chat-log .msg.bot").last.scroll_into_view_if_needed()
        except Exception:
            pass

    def wait_text(self, js: str, timeout: int = 30000, what: str = "") -> bool:
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

    def search_plate(self, plate: str) -> None:
        p = self.page
        p.fill("#q-type", "")
        p.fill("#q-camera", "")
        p.fill("#q-plate", "")
        p.type("#q-plate", plate, delay=55)
        self.hold(250)
        p.locator("#search-form button.primary").click(force=True)

    def run(self) -> None:
        p = self.page
        self.chapter("title")
        self.hold(800)

        self.chapter("signin")
        p.evaluate("() => { const g = document.getElementById('gate'); if (g) g.hidden = false; }")
        self.hold(1200)
        p.fill("#gate-case", CASE)
        self.hold(300)
        p.fill("#gate-purpose", PURPOSE)
        self.hold(400)
        p.fill("#gate-token", self.token)
        self.hold(350)
        p.locator("#gate-form button[type=submit]").click(force=True)
        self.wait_text(
            "() => /supervisor\\.demo/i.test(document.getElementById('who')?.textContent || '')",
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
            "&& document.querySelectorAll('#overview .plate-card, #overview .kpi .big').length >= 4",
            60000, "own-feed overview")
        self.hold(2800)
        self.finish("signin", 800)

        self.chapter("live")
        # The current product's own-feed presentation is the Intelligence
        # workspace: two labelled participant replays with stored analytics.
        # The old Focus-stage selector belonged to a retired layout and made a
        # recording wait on a node that no longer exists.
        self.nav("intelligence", 1400)
        self.wait_text(
            "() => [...document.querySelectorAll('#view-intelligence img[alt^=\"OWN-\"]')]"
            ".filter(i => i.naturalWidth > 40).length >= 2",
            45000, "own-feed Intelligence previews")
        self.hold(22000)
        self.finish("live", 800)

        self.chapter("find")
        self.nav("investigate", 1000)
        self.search_plate(PLATE)
        self.wait_text(
            "() => { const n = document.getElementById('result-count'); "
            "return n && /observation/.test(n.textContent || ''); }",
            45000, "plate search")
        self.hold(2800)
        try:
            p.locator("#results .result").first.click(force=True)
        except Exception:
            pass
        self.hold(3200)
        self.finish("find", 800)

        self.chapter("route")
        self.wait_text(
            "() => /C-014/.test(document.getElementById('traj-body')?.innerText || '') "
            "&& /C-021/.test(document.getElementById('traj-body')?.innerText || document.body.innerText)",
            30000, "two-camera route")
        self.hold(1800)
        try:
            p.locator("#btn-fit").click(force=True)
        except Exception:
            pass
        self.hold(2800)
        self.finish("route", 800)

        self.chapter("alerts")
        self.nav("alerts", 1200)
        self.wait_text(
            f"() => /{PLATE}/.test(document.body.innerText) "
            f"|| /{ALERT}/.test(document.body.innerText)",
            25000, "watchlist alert")
        self.hold(3200)
        self.finish("alerts", 800)

        self.chapter("map")
        self.nav("map", 1400)
        try:
            p.locator("#btn-fit2").click(force=True)
        except Exception:
            pass
        self.hold(3200)
        self.finish("map", 800)

        self.chapter("federation")
        self.nav("system", 1400)
        self.wait_text(
            "() => /Hybrid architecture|systems|federat/i.test(document.getElementById('system')?.innerText || '')",
            30000, "federation system view")
        self.hold(3600)
        self.finish("federation", 800)

        self.chapter("copilot")
        self.nav("copilot", 1400)
        self.hold(2200)
        self.ask("Where was GJ18JX7786 seen, and is it on the watchlist?")
        self.hold(5000)
        self.finish("copilot", 800)

        self.chapter("close")
        self.nav("overview", 800)
        self.hold(2200)


def record_browser(base: str, token: str, work: Path) -> tuple[Path, list[dict]]:
    from playwright.sync_api import sync_playwright

    from hq_capture import CURSOR_JS, JpegFilm

    work.mkdir(parents=True, exist_ok=True)
    picture = work / "picture.mp4"
    log: list[dict] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
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
    print(f"narrating with {voice}")
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

    probe = subprocess.run([ff, "-i", str(video)], capture_output=True, text=True)
    vdur = 0.0
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            vdur = int(h) * 3600 + int(m) * 60 + float(s)
            break
    print(f"picture {vdur:.1f}s")

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
    target = vdur
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
    enc = subprocess.run(
        [ff, "-y", "-i", str(video), "-i", str(bed),
         "-c:v", "copy",
         "-c:a", "aac", "-b:a", "320k",
         "-t", f"{target:.3f}", "-movflags", "+faststart",
         str(final)],
        capture_output=True, text=True)
    if enc.returncode != 0:
        print(enc.stderr[-2000:], file=sys.stderr)
        raise SystemExit("encode failed")
    mb = final.stat().st_size / 1e6
    print(f"\ndesignated film : {display(final)} ({target/60:.1f} min, {mb:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--out", default="var/demo/SAAKSHYA_designated")
    a = ap.parse_args()
    if ":8080" in a.base:
        raise SystemExit("refusing to film designated-vehicle on :8080 (live grid)")
    token = Path(a.token_file).read_bytes().strip().decode("ascii")
    out = Path(a.out)
    work = out.parent / "designated_work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"recording designated film at {a.base} → {display(out)}.mp4")
    t0 = time.time()
    webm, log = record_browser(a.base, token, work)
    (work / "chapters.json").write_text(json.dumps(log, indent=2))
    Path("var/demo/SAAKSHYA_designated_chapters.json").write_text(
        json.dumps(log, indent=2))
    print(f"raw picture {webm} ({time.time()-t0:.0f}s to drive)")
    mux(ffmpeg_bin(), webm, log, out, work)
    final = out.with_suffix(".mp4")
    _cap_own_feed_length(ffmpeg_bin(), final)
    own = Path("var/demo/own_feed.mp4")
    if final.resolve() != own.resolve():
        import shutil
        shutil.copy2(final, own)
        print(f"also wrote {display(own)}")
    return 0


def _cap_own_feed_length(ff: str, final: Path, cap_s: float = 178.0) -> None:
    """Portal own-feed is capped at 2–3 minutes."""
    probe = subprocess.run([ff, "-i", str(final)], capture_output=True, text=True)
    vdur = 0.0
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            vdur = int(h) * 3600 + int(m) * 60 + float(s)
            break
    if vdur <= cap_s or vdur < 1:
        return
    factor = vdur / cap_s
    tmp = final.with_suffix(".capped.mp4")
    # atempo accepts 0.5–100; chain if needed.
    a = factor
    filters = []
    while a > 2.0:
        filters.append("atempo=2.0")
        a /= 2.0
    filters.append(f"atempo={a:.6f}")
    r = subprocess.run(
        [ff, "-y", "-i", str(final),
         "-filter_complex",
         f"[0:v]setpts=PTS/{factor:.6f}[v];[0:a]{','.join(filters)}[a]",
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{cap_s:.3f}",
         "-movflags", "+faststart", str(tmp)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:], file=sys.stderr)
        raise SystemExit("own-feed duration cap failed")
    tmp.replace(final)
    print(f"capped own-feed {vdur:.1f}s → {cap_s:.0f}s (×{factor:.2f})")


if __name__ == "__main__":
    raise SystemExit(main())
