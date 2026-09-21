"""A full-length motion recording of the platform, every view, in one take.

`record_walkthrough.py` composes a *slideshow*: it screenshots each step and
holds the still for `hold_s` seconds. That is the right shape for a caption-led
summary, but a still frame cannot show a live camera moving, which is precisely
the claim the Live wall exists to support. This recorder captures the real
browser surface instead, so thirty government cameras are seen running rather
than asserted.

    python tools/demo/record_full_tour.py \
        --base http://127.0.0.1:8083 \
        --token-file /path/to/token.raw

The token is read from a file or the command line and never written to disk or
logged. Every request the recording makes is a real, audited request.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VIEW_W, VIEW_H = 1920, 1080


@dataclass
class Scene:
    """One view, held long enough to actually be read."""

    title: str
    #: Seconds to remain on this view once its action has run.
    dwell_s: float
    #: Drives the interface. A scene that raises is reported, not hidden: a
    #: recording missing a screen with no explanation is worse than one that
    #: says which screen is missing.
    action: Callable[[], None] = lambda: None
    ok: bool = True
    err: str = ""
    started_at: float = field(default=0.0)


def build_scenes(page, plate: str) -> list[Scene]:
    def nav(view: str, settle_ms: int = 2500):
        def go():
            page.click(f'button[data-view="{view}"]')
            page.wait_for_timeout(settle_ms)
        return go

    def slow_scroll(selector: str, steps: int = 6, dy: int = 420, pause: int = 1400):
        """Scroll a pane so long lists are seen rather than implied."""
        def go():
            try:
                page.hover(selector, timeout=5000)
            except Exception:
                pass
            for _ in range(steps):
                page.mouse.wheel(0, dy)
                page.wait_for_timeout(pause)
            for _ in range(steps):
                page.mouse.wheel(0, -dy)
                page.wait_for_timeout(pause // 2)
        return go

    def open_live():
        page.click('button[data-view="live"]')
        # The wall paints in about five seconds; the sessions it opens need
        # longer, and this is the one scene where waiting is the point.
        try:
            page.wait_for_selector("#live .live-tile", timeout=60000)
        except Exception:
            page.goto(page.url.split("#")[0] + "#live", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.click('button[data-view="live"]')
            page.wait_for_selector("#live .live-tile", timeout=60000)
        # videoWidth > 0 is satisfied by the 2x2 placeholder Chrome reports
        # before a WHEP track's first keyframe, so it was passing on a wall of
        # black tiles. Wait for a real decoded frame size instead.
        decoding = ("() => [...document.querySelectorAll('#live-grid video')]"
                    ".filter(v => v.readyState >= 2 && v.videoWidth > 16).length >= 5")
        try:
            page.wait_for_function(decoding, timeout=75000)
        except Exception:
            pass  # recorded as it is, however it is

    def live_wall(size: str):
        def go():
            try:
                page.click(f'[data-live-wall="{size}"]', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(6000)
        return go

    def live_scroll():
        try:
            page.hover("#live-grid", timeout=5000)
        except Exception:
            pass
        for _ in range(7):
            page.mouse.wheel(0, 380)
            page.wait_for_timeout(2600)
        for _ in range(7):
            page.mouse.wheel(0, -380)
            page.wait_for_timeout(1500)

    def bind_and_search():
        page.click('button[data-view="investigate"]')
        page.wait_for_timeout(2000)
        for sel in ('#q', 'input[name="q"]', '#search-q', '.search input'):
            try:
                page.fill(sel, plate, timeout=4000)
                page.press(sel, "Enter")
                break
            except Exception:
                continue
        page.wait_for_timeout(5000)

    def open_first_result():
        for sel in ("#results .result", "#result-list .result", ".result"):
            try:
                page.click(sel, timeout=6000)
                break
            except Exception:
                continue
        page.wait_for_timeout(4000)

    def open_case():
        page.click('button[data-view="cases"]')
        page.wait_for_timeout(2500)
        try:
            page.click("#case-list .result", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

    return [
        Scene("Overview — the shift picture", 42, nav("overview")),
        Scene("Overview — reading down the estate", 40, slow_scroll("main", 5)),
        Scene("Investigate — purpose binding, then the search", 55, bind_and_search),
        Scene("Find — what matched, and how sure", 45, open_first_result),
        Scene("Cameras — capability measured, never declared", 45, nav("cameras")),
        Scene("Cameras — six dimensions, camera by camera", 48, slow_scroll("main", 6)),
        Scene("Analytics — what the estate can actually do", 52, nav("analytics")),
        Scene("Estate map — placed, and honestly unplaced", 58, nav("map", 4000)),
        # The centre of the recording: real government cameras, moving.
        Scene("Live — thirty government cameras, direct WHEP", 95, open_live),
        Scene("Live — twelve up, at full quality", 70, live_wall("12")),
        Scene("Live — scrolling the wall", 60, live_scroll),
        Scene("Live — the dense wall", 55, live_wall("30")),
        Scene("Alerts — matched, and worth a person's time", 45, nav("alerts")),
        Scene("The case file — what an officer hands on", 52, open_case),
        Scene("Evidence — integrity and truthfulness, apart", 48, nav("evidence")),
        Scene("Audit — every query, attributed", 45, nav("audit")),
        Scene("Audit — the chain, row after row", 42, slow_scroll("main", 5)),
        Scene("Intelligence — the demonstration plane", 45, nav("intelligence")),
        Scene("System — what this process is actually doing", 42, nav("system")),
        Scene("Copilot — last, and optional", 48, nav("copilot")),
    ]


def record(base: str, token: str, plate: str, out_dir: Path) -> list[Scene]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:                                # pragma: no cover
        raise SystemExit(
            "This recorder drives a real browser and needs Playwright:\n"
            "  pip install -e '.[demo]'"
        ) from None

    out_dir.mkdir(parents=True, exist_ok=True)
    scenes: list[Scene] = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEW_W, "height": VIEW_H},
            record_video_dir=str(out_dir),
            record_video_size={"width": VIEW_W, "height": VIEW_H},
        )
        page = context.new_page()
        page.goto(f"{base}/ui/", wait_until="domcontentloaded")
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        # An expired token puts the sign-in panel up and leaves every nav
        # button behind it, so each click times out and the recording is
        # twenty-six minutes of a login screen. That has happened once; check
        # before spending the time rather than after.
        try:
            page.wait_for_selector('button[data-view="live"]',
                                   state="visible", timeout=20000)
        except Exception:
            context.close()
            browser.close()
            raise SystemExit(
                "the workspace did not open - the token is expired or refused, "
                "so the recording would be of the sign-in screen. Mint a new "
                "one:\n"
                "  python tools/admin/users.py --db sqlite:///var/live.db \\\n"
                "      token --user supervisor.live --days 7"
            )

        scenes = build_scenes(page, plate)
        t0 = time.time()
        for i, sc in enumerate(scenes):
            sc.started_at = time.time() - t0
            print(f"  {i:02d}  {sc.title[:52]:<52} "
                  f"+{int(sc.started_at)//60:d}:{int(sc.started_at)%60:02d}", flush=True)
            try:
                sc.action()
            except Exception as exc:
                sc.ok, sc.err = False, f"{type(exc).__name__}: {exc}"[:140]
            page.wait_for_timeout(int(sc.dwell_s * 1000))

        video = page.video
        context.close()          # the webm is only finalised on close
        browser.close()
        if video:
            try:
                Path(video.path()).rename(out_dir / "tour.webm")
            except Exception:
                pass
    return scenes


def to_mp4(out_dir: Path, mp4: Path) -> bool:
    src = out_dir / "tour.webm"
    if not src.exists():
        webms = sorted(out_dir.glob("*.webm"))
        if not webms:
            return False
        src = webms[0]
    if not shutil.which("ffmpeg"):
        return False
    mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _token(args: argparse.Namespace) -> str:
    if args.token_file:
        raw = Path(args.token_file).read_bytes().strip().decode("ascii")
        if not raw:
            raise SystemExit(f"empty token file: {args.token_file}")
        return raw
    if args.token:
        return args.token
    raise SystemExit("need --token-file or --token")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8083")
    ap.add_argument("--token")
    ap.add_argument("--token-file",
                    help="read the bearer token from a file; never logged")
    ap.add_argument("--plate", default="GJ1VV0119")
    ap.add_argument("--out", default="var/demo/full_tour")
    a = ap.parse_args()

    out_dir = Path(a.out)
    mp4 = Path(str(out_dir) + ".mp4")
    print(f"recording the full tour at {a.base} -> {mp4}")
    t0 = time.time()
    scenes = record(a.base, _token(a), a.plate, out_dir)
    took = time.time() - t0

    ok = to_mp4(out_dir, mp4)
    print()
    failed = [s for s in scenes if not s.ok]
    print(f"scenes : {len(scenes) - len(failed)}/{len(scenes)} driven cleanly")
    for s in failed:
        print(f"  could not drive: {s.title}: {s.err}")
    print(f"took   : {int(took)//60}m{int(took)%60:02d}s")
    print(f"video  : {mp4 if ok else out_dir} "
          f"({'mp4' if ok else 'webm only — ffmpeg missing or failed'})")


if __name__ == "__main__":
    main()
