"""Record government footage only after measured readiness gates pass.

Live command (run by the primary after merging; never run during offline work):
    PYTHONPATH="$PWD/src" "/Users/earther/Desktop/Gujarat CCTV/saakshya/.venv/bin/python" \
        tools/demo/record_government_feed.py \
        --base http://127.0.0.1:8083 --token-file /path/to/officer.token \
        --admin-token-file /path/to/admin.token --min-live 12 \
        --preflight-timeout 300 --plate GJ11S7924 --out var/demo/government_feed
Add --preflight-only to write preflight.json without starting capture.
Add --tour full for the complete operator story, beginning at the masked
sign-in gate. --wall-domain replay uses the REPLAY lane's registered GOVREC
files, dated public GIS metadata and replay domain button; choose --min-live
no higher than the number of files. In replay mode this legacy option counts
advancing recordings, never live government sessions. Synthetic test clips
cannot qualify. The separate ANPR deliverable remains GOVERNMENT-only.

One context and page; only the application's own media sessions. Transition
waits are cut out of capture, with their durations retained in beats.json.
Counts are measurements during this recording, never upstream session limits.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import uuid
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hq_screencast import Screencast

VIEW_W, VIEW_H = 2560, 1440
ROOT = Path(__file__).resolve().parents[2]
GATES = ("API_READY", "DB_READY", "UI_READY", "MAP_READY", "WHEP_READY",
         "VIDEO_ADVANCING", "NO_FATAL_TOAST")


@dataclass
class Beat:
    title: str
    dwell_s: float
    action: Callable = lambda: None
    say: str = ""
    wall: bool = False
    optional: bool = False
    motion: Callable | None = None
    visible_motion: bool = False
    #: Re-selects after a visible stall (another advancing camera), or None.
    retry: Callable | None = None
    ok: bool = False
    err: str = ""
    at: float = 0.0
    say_s: float = 0.0
    audio: Path | None = None
    skipped: bool = False
    prepare_s: float = 0.0
    recorded_s: float = 0.0
    samples: list = field(default_factory=list)
    selectors: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    gate: bool = False


class SkipBeat(Exception):
    """A known unavailable optional output, not a successful demonstration."""


class RecorderFailure(Exception):
    """Recorder-authored reason, safe to put in logs without server content."""


def registry_composition(body: dict) -> tuple[dict, list[str]]:
    counts = dict.fromkeys(("GOVERNMENT", "OWN_FEED", "SYNTHETIC_CONTROL"), 0)
    rows = {r["camera_id"]: r for r in
            body.get("features", []) + body.get("unlocated", [])
            if r.get("camera_id") and not r.get("cluster")}
    government = []
    for cid, row in rows.items():
        domain = row.get("source_domain") or "UNKNOWN"
        counts[domain] = counts.get(domain, 0) + 1
        if domain == "GOVERNMENT":
            government.append(cid)
    return counts, sorted(government)


def evaluate_tiles(before: list[dict], after: list[dict], min_live: int) -> dict:
    """Only advancing rendered video is LIVE; never a still or PC alone."""
    previous = {r["camera"]: r for r in before}
    rows = []
    for tile in after:
        old = previous.get(tile["camera"], {})
        elapsed = (tile.get("sample_ms", 0) - old.get("sample_ms", 0)) / 1000
        advancing = bool(
            old and tile.get("video_id") is not None
            and tile.get("video_id") == old.get("video_id")
            and elapsed >= 1 and tile.get("width", 0) > 16
            and tile.get("ready", 0) >= 2
            and tile.get("time", 0) > old.get("time", 0)
            and tile.get("vfc", 0) > old.get("vfc", 0))
        rows.append({**tile, "elapsed_s": elapsed, "advancing": advancing})
    # Duplicated filmstrip elements must never inflate the count.
    live = sorted({r["camera"] for r in rows if r["advancing"]})
    connected = sorted({r["camera"] for r in rows if r.get("pc") == "connected"})
    visible_live = sorted({r["camera"] for r in rows if r["advancing"] and r.get("visible")})
    return {"live": len(live), "live_ids": live, "visible_live": len(visible_live),
            "visible_live_ids": visible_live, "connected": len(connected),
            "passed": len(live) >= min_live, "min_live": min_live, "tiles": rows}


#: Consecutive failing samples that end a hold. Samples come about every 2.3 s
#: and each compares two snapshots 1.1 s apart, so one failure is a pause of
#: about a second - on 28 Sep cam01 froze 1.3 s between 11 s of steady play,
#: and the strict rule threw the take away. Two in a row is a freeze of about
#: 3.5 s, which a viewer would see. Every sample is still written to beats.json.
STALL_SAMPLES = 2


#: A stalled focused camera is replaced by the next one measured advancing on
#: the wall, at most this many times per beat; each gets this long to advance.
#: On 28 Sep cam06 played 28 s cleanly in one take and froze after 6 s in the
#: next: no single shared-sandbox stream can be relied on for a whole beat.
FOCUS_SWITCHES = 2
FOCUS_START_S = 12


#: How long the opening may wait, after narration is prepared, for the wall
#: to meet the preflight threshold again before the take is abandoned.
OPENING_WAIT_S = 90


def opening_ready(sample: dict, ui: dict, min_live: int, wall_domain: str = 'government') -> bool:
    """The film may start: enough advancing tiles on screen, a clean view."""
    return bool(sample['passed'] and sample['visible_live']
                and (wall_domain == 'replay' or sample['connected'] >= min_live) and ui['shell']
                and not ui['fatal'] and not ui['loading'] and not ui['loadingText'])


def dry_run_rows(sample_csv: str, rows: int = 7, namespace: str = '') -> str:
    """The sample spreadsheet's first rows under fresh DRYRUN-NN ids.

    The sample cameras are onboarded already, so validating them returns 409
    ALREADY_ONBOARDED - correctly (take 7 stopped there). The beat shows a
    department's new rows being validated; it is a dry run and writes nothing.
    """
    lines = sample_csv.splitlines()
    prefix = f'DRYRUN-{namespace}-' if namespace else 'DRYRUN-'
    body = [f"{prefix}{i:02d},{line.split(',', 1)[1]}"
            for i, line in enumerate(lines[1:rows + 1], 1)]
    return "\n".join([lines[0], *body])


def focus_order(live_ids: list[str], preferred: str = "cam06") -> list[str]:
    """Focus candidates: the designated vehicle's camera first, if advancing.

    On the recorded wall that camera is its replay row, GOVREC-<camera>.
    """
    ids = list(dict.fromkeys(live_ids))
    first = [c for c in ids if c in (preferred, f"GOVREC-{preferred}")][:1]
    return first + [c for c in ids if c not in first]


def hold_stalled(history: list[bool], tolerance: int = STALL_SAMPLES) -> bool:
    """True when the last ``tolerance`` hold samples all failed to advance."""
    return len(history) >= tolerance and not any(history[-tolerance:])


def live_caption(live: int, total: int = 30) -> str:
    if not 0 <= live <= total:
        raise ValueError("live count must be within the measured wall size")
    return f"{live} of {total} government cameras live in this recording"


def replay_catalog(body: dict) -> dict[str, str]:
    """Only government-linked archival files qualify; never the simulation plane.

    REPLAY integration contract: GIS rows have camera_id GOVREC-<government id>,
    source_domain ARCHIVAL_REPLAY, recorded_file=true, synthetic=false, and
    capture_start_ist (ISO timestamp, supplied by live.recordings metadata).
    An explicit government_camera_id/source_camera_id is also accepted.
    Only these allowlisted fields are retained, never a source URL.
    """
    _, government = registry_composition(body)
    dates = {}
    for row in body.get('features', []) + body.get('unlocated', []):
        cid = str(row.get('camera_id', ''))
        parent = row.get('government_camera_id') or row.get('source_camera_id')
        if not parent and cid.startswith('GOVREC-'):
            parent = cid.removeprefix('GOVREC-')
        captured = str(row.get('capture_start_ist') or row.get('captured_at') or row.get('capture_start') or '')
        if (row.get('source_domain') == 'ARCHIVAL_REPLAY' and parent in government
                and row.get('recorded_file') is True and row.get('synthetic') is False
                and re.fullmatch(r'[A-Za-z0-9_-]+', cid)
                and re.match(r'^\d{4}-\d{2}-\d{2}(?:T| |$)', captured)):
            from datetime import date
            try:
                date.fromisoformat(captured[:10])
            except ValueError:
                continue
            dates[cid] = captured[:10]
    return dates


def playback_caption(sample: dict, domain: str, ids: list[str], dates: dict[str, str]) -> str:
    if domain == 'government':
        return live_caption(sample['live'], len(ids))
    captured = ', '.join(sorted({dates[c] for c in sample['live_ids']}))
    return f"RECORDED GOVERNMENT FOOTAGE · captured {captured} · replayed"


def single_camera(sightings: list[dict]) -> bool:
    return bool(sightings) and all(r.get("camera_id") for r in sightings) and len(
        {r["camera_id"] for r in sightings}) == 1


def search_caption(sightings: list[dict], government: list[str]) -> str:
    if not sightings:
        return "No designated-plate sightings returned"
    if all(r.get("camera_id") in government for r in sightings):
        if single_camera(sightings):
            return "SINGLE-CAMERA GOVERNMENT OBSERVATION — camera and timestamps"
        return "Government observations — cameras and timestamps"
    return "Search observations — verify each camera's source domain"


def beat_plan_duration(beats: list[Beat]) -> float:
    return sum(max(b.dwell_s, b.say_s + 0.6) for b in beats if not b.skipped)


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def api_read(base: str, token: str, path: str, timeout: float = 15) -> tuple[int, dict]:
    req = urllib.request.Request(base.rstrip("/") + path,
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=max(0.1, timeout)) as res:
            data = res.read()
            try:
                body = json.loads(data)
            except (ValueError, UnicodeError):
                body = {}
            return res.status, body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception:
        # Never log request headers, bodies or exception strings containing URLs.
        return 0, {}


# Observe the PCs created by the application; this creates no media session.
# Receiver track identity associates a tile with its actual peer connection.
INSTRUMENT = """() => {
  const peers = new Set();
  const Native = window.RTCPeerConnection;
  window.RTCPeerConnection = class extends Native {
    constructor(...args) { super(...args); peers.add(this);
      this.addEventListener('connectionstatechange', () => {
        if (this.connectionState === 'closed') peers.delete(this);
      });
    }
  };
  const videos = new WeakMap(); let serial = 0;
  window.__govSample = (ids, focus) => ids.map(camera => {
    const tile = document.querySelector(
      '#live-grid .live-tile[data-camera="' + CSS.escape(camera) + '"]');
    const v = focus ? document.querySelector('#live-stage video') : tile?.querySelector('video');
    let stat = v && videos.get(v);
    if (v && !stat) {
      stat = {id: ++serial, frames: 0}; videos.set(v, stat);
      if (v.requestVideoFrameCallback) {
        const tick = () => { stat.frames++;
          if (v.isConnected) v.requestVideoFrameCallback(tick); };
        v.requestVideoFrameCallback(tick);
      }
    }
    const tracks = v?.srcObject?.getTracks?.() || [];
    const rect = v?.getBoundingClientRect();
    const bounds = (focus ? document.querySelector('#live-stage') :
      document.querySelector('#live-grid'))?.getBoundingClientRect();
    const visible = !!rect && !!bounds && rect.width > 0 && rect.height > 0 &&
      getComputedStyle(v).visibility !== 'hidden' &&
      rect.bottom > Math.max(0, bounds.top) && rect.top < Math.min(innerHeight, bounds.bottom) &&
      rect.right > Math.max(0, bounds.left) && rect.left < Math.min(innerWidth, bounds.right);
    const pc = [...peers].find(p => p.getReceivers().some(r =>
      r.track && tracks.some(t => t.id === r.track.id)));
    return {camera, sample_ms: performance.now(), video_id: stat?.id ?? null,
      width: v?.videoWidth || 0, ready: v?.readyState || 0,
      time: v?.currentTime || 0, vfc: stat?.frames || 0,
      pc: pc?.connectionState || 'absent', visible};
  });
}"""

UI_SAMPLE = """() => {
  const visible = e => !!e && e.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
  const view = document.querySelector('.view.active');
  const loading = view ? [...view.querySelectorAll('.loading-note')].filter(visible).length : 0;
  const loadingText = view ? /\\bLoading\\b/i.test(view.innerText) : true;
  const fatal = [...document.querySelectorAll(
    '#toast-stack .toast.bad, .view.active .notice.bad, .view.active .onboard-result.bad')]
    .filter(visible).length;
  return {shell: visible(document.querySelector('.shell')) && visible(view)
      && !visible(document.querySelector('#gate')), loading, loadingText, fatal,
    view: view?.id || null};
}"""

MAP_SAMPLE = """() => {
  const canvas = document.querySelector('#map2');
  const map = window.__saakshya?.map2;
  const r = canvas?.getBoundingClientRect();
  const markers = (map?._hit || []).filter(h => ['camera', 'cluster'].includes(h.kind)
    && h.x >= 0 && h.x <= r?.width && h.y >= 0 && h.y <= r?.height).length;
  const images = [...document.querySelectorAll('#view-map .gmap-host img')]
    .filter(i => i.complete && i.naturalWidth > 16 && i.getBoundingClientRect().width > 0).length;
  return {visible: !!r && r.width > 0 && r.height > 0, markers, tiles: images};
}"""


def wait_view(page, view: str, content: str, timeout: float = 45000,
              allow_error: bool = False) -> None:
    page.wait_for_selector(f"#view-{view}.active", timeout=timeout)
    page.wait_for_selector(content, timeout=timeout)
    page.wait_for_function("() => { const s = (" + UI_SAMPLE + ")(); return "
                           "s.shell && !s.loading && !s.loadingText" +
                           ("; }" if allow_error else " && !s.fatal; }"), timeout=timeout)


def wait_search_idle(page) -> None:
    """Enter is ignored while the previous search, or its route panel, is loading."""
    page.wait_for_function("() => { const b = document.querySelector('#search-form button[type=submit]'); "
                           "const s = (" + UI_SAMPLE + ")(); return !!b && !b.disabled && !s.loading; }",
                           timeout=90000)


def navigate(page, view: str, content: str, *, allow_error: bool = False) -> None:
    if page.locator("#report-dialog[open]").count():
        page.click("#report-close")
    page.click(f'button[data-view="{view}"]')
    wait_view(page, view, content, allow_error=allow_error)


def sample_video(page, ids: list[str], min_live: int, focus: bool = False) -> dict:
    args = {"ids": ids, "focus": focus}
    read = "a => window.__govSample(a.ids, a.focus)"
    before = page.evaluate(read, args)
    page.wait_for_timeout(1100)  # Measurement interval, never a content wait.
    after = page.evaluate(read, args)
    return evaluate_tiles(before, after, min_live)


def wall_ids(page, government: list[str]) -> list[str]:
    ids = page.locator('#live-grid .live-tile').evaluate_all(
        'es => es.map(e => e.dataset.camera)')
    return list(dict.fromkeys(cid for cid in ids if cid in government))


def wait_wall_motion(page, government: list[str], threshold: int, samples: list) -> dict:
    deadline = time.monotonic() + 30
    while True:
        sample = sample_video(page, wall_ids(page, government), threshold)
        samples.append(sample)
        if sample['passed'] and sample['visible_live']:
            return sample
        if time.monotonic() >= deadline:
            raise RecorderFailure('wall motion threshold not met')


def wall_mode(page, layout: str) -> None:
    selector = f'[data-live-layout="{layout}"]'
    if not page.locator(selector).evaluate("e => e.classList.contains('on')"):
        page.click(selector)
    page.wait_for_selector(f'#live[data-layout="{layout}"] #live-grid .live-tile', state='attached')
    policy = "control-room" if layout == "dense" else "optimized"
    page.wait_for_selector(f'#media-policy[data-policy="{policy}"]')


def scroll_wall(page, fraction: float) -> None:
    page.evaluate("""fraction => {
      const grid = document.querySelector('#live-grid');
      grid.scrollTo({top: fraction * (grid.scrollHeight - grid.clientHeight), behavior: 'smooth'});
      if (grid.scrollHeight <= grid.clientHeight) {
        const tiles = [...grid.querySelectorAll('.live-tile')];
        tiles[Math.round(fraction * (tiles.length - 1))]?.scrollIntoView({behavior:'smooth', block:'center'});
      }
    }""", fraction)
    page.wait_for_timeout(1600)  # Deliberate visible scroll motion.


#: The two wall layouts the film can open on, and the media policy each shows.
#: Dense is the 6x5 CONTROL ROOM (a session per tile); Grid is the scrolling
#: OPTIMIZED VIEW (at most 12 sessions near the viewport, large tiles).
OPENING_POLICY = {"dense": "control-room", "grid": "optimized"}
#: OPTIMIZED VIEW never streams more than this many tiles at once.
GRID_SESSION_BUDGET = 12


def opening_beats(page, layout: str, wall_group: Callable[[float], Callable]) -> list[Beat]:
    """The wall beats, opening on the layout the preflight measured.

    Dense opens on the 6x5 CONTROL ROOM, which needs a session per tile. When
    the shared sandbox cannot deliver that many at once (organisers: fan-in
    varies with overall load), the film opens on the OPTIMIZED VIEW instead:
    large tiles, at most 12 sessions near the viewport. The CONTROL ROOM still
    appears afterwards with all thirty cameras and the live count measured at
    that moment, so the film never claims more simultaneous video than it had.
    """
    groups = [Beat(f'Government wall — {name}', 14, wall_group(fraction),
                   'The scrolling view uses the optimized media policy. Watch the moving footage; '
                   'cached previews are not counted as live.',
                   wall=True, motion=lambda fraction=fraction: scroll_wall(page, fraction))
              for name, fraction in [('top', 0.0), ('middle', 0.5), ('bottom', 1.0)]]
    if layout == "dense":
        return [Beat('Government live viewing — CONTROL ROOM', 20,
                     say='Government footage, measured in this recording. The control room holds a '
                         'session per tile. Analytics coverage is separate from viewing.',
                     wall=True), *groups]

    def control_room():
        wall_mode(page, "dense")
        wait_view(page, "live", "#live-grid .live-tile")

    return [
        Beat('Government live viewing — OPTIMIZED VIEW', 20,
             say='Government footage, measured in this recording. The optimized view streams the '
                 'large tiles on screen, up to twelve at once. Analytics coverage is separate from viewing.',
             wall=True),
        *groups,
        Beat('All thirty government cameras — CONTROL ROOM', 14, control_room,
             'The control room holds a session per tile for all thirty. How many play at once is '
             'measured now; the shared sandbox decides it, and the rest say so.',
             wall=True),
    ]


def preflight(page, base: str, token: str, out: Path, min_live: int, timeout: float,
              layout: str = "dense", wall_domain: str = 'government') -> dict:
    started = time.monotonic()
    deadline = started + timeout
    result = {"passed": False, "min_live": min_live, "timeout_s": timeout,
              "gates": {name: {"passed": False, "measured": None} for name in GATES},
              "samples": []}

    def gate(name, passed, measured):
        result["gates"][name] = {"passed": bool(passed), "measured": measured,
                                 "at_s": round(time.monotonic() - started, 3)}
        save_json(out / "preflight.json", result)

    def remaining_ms():
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("preflight deadline")
        return max(1, left * 1000)

    try:
        codes = {p: api_read(base, token, p, min(15, remaining_ms() / 1000))[0]
                 for p in ("/healthz", "/readyz")}
        gate("API_READY", all(c == 200 for c in codes.values()), codes)
        status, body = api_read(base, token, "/gis/cameras?zoom=16&limit=20000",
                                min(30, remaining_ms() / 1000))
        counts, government = registry_composition(body)
        result["government_ids"] = government
        dates = replay_catalog(body) if wall_domain == 'replay' else {}
        media_ids = sorted(dates) if wall_domain == 'replay' else government
        result.update(wall_domain=wall_domain, wall_ids=media_ids, replay_dates=dates)
        gate("DB_READY", status == 200 and not body.get("clustered")
             and counts["GOVERNMENT"] >= 30 and len(media_ids) >= min_live,
             {"status": status, "composition": counts,
              "expected_baseline": {"GOVERNMENT": 30, "OWN_FEED": 2, "SYNTHETIC_CONTROL": 18},
              "clustered": body.get("clustered")})
        if not result["gates"]["API_READY"]["passed"] or not result["gates"]["DB_READY"]["passed"]:
            return result
        page.goto(base.rstrip("/") + "/ui/#map", wait_until="domcontentloaded",
                  timeout=remaining_ms())
        page.wait_for_selector('#view-map.active #map2', timeout=remaining_ms())
        page.wait_for_function("() => {const m = (" + MAP_SAMPLE + ")(); "
                               "return m.visible && (m.markers > 0 || m.tiles > 0);}",
                               timeout=remaining_ms())
        gate("MAP_READY", True, page.evaluate(MAP_SAMPLE))
        page.click('button[data-view="live"]', timeout=remaining_ms())
        page.wait_for_selector('#live-grid .live-tile', timeout=remaining_ms())
        page.click(f'[data-live-domain="{wall_domain}"]', timeout=remaining_ms())
        policy = OPENING_POLICY[layout]
        page.click(f'[data-live-layout="{layout}"]', timeout=remaining_ms())
        page.wait_for_selector(f'#media-policy[data-policy="{policy}"]', timeout=remaining_ms())
        wall_attr = '[data-wall="30"]' if wall_domain == 'government' else ''
        page.wait_for_selector(f'#live{wall_attr}[data-layout="{layout}"] .live-tile',
                               timeout=remaining_ms())
        warmed = False
        while time.monotonic() + 1.1 < deadline:
            ids = wall_ids(page, media_ids)
            sample = sample_video(page, ids, min_live)
            result["samples"].append(sample)
            result["latest"] = sample
            ui = page.evaluate(UI_SAMPLE)
            gate("UI_READY", ui["shell"] and not ui["loading"] and not ui["loadingText"], ui)
            gate("NO_FATAL_TOAST", ui["fatal"] == 0, {"visible_errors": ui["fatal"]})
            transport_ok = (len(ids) == 30 and sample['connected'] >= min_live
                            if wall_domain == 'government' else len(ids) >= min_live)
            gate("WHEP_READY", transport_ok,
                 {"connected": sample["connected"], "tiles": len(ids), "policy": policy,
                  "transport": 'file replay; WHEP not required' if dates else 'WHEP'})
            gate("VIDEO_ADVANCING", sample["passed"] and sample['visible_live'] > 0, sample)
            print(f"  preflight: {sample['live']}/{len(ids)} advancing; "
                  f"{sample['connected']} connected", flush=True)
            if all(g["passed"] for g in result["gates"].values()):
                if not warmed:
                    if time.monotonic() + 8 > deadline:
                        break
                    for fraction in (0.0, 0.5, 1.0, 0.0):
                        scroll_wall(page, fraction)
                    warmed = True
                    continue  # Required fresh sample after returning to the top.
                result["passed"] = True
                break
    except Exception as exc:
        result["error"] = type(exc).__name__
        if page.url.startswith(base.rstrip('/') + '/ui/'):
            try:
                if not result['gates']['MAP_READY']['passed']:
                    gate('MAP_READY', False, page.evaluate(MAP_SAMPLE))
                ui = page.evaluate(UI_SAMPLE)
                gate('UI_READY', ui['shell'] and not ui['loading'] and not ui['loadingText'], ui)
                gate('NO_FATAL_TOAST', ui['fatal'] == 0, {'visible_errors': ui['fatal']})
            except Exception:
                pass  # A crashed browser is already a failed, unsampled gate.
    finally:
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        save_json(out / "preflight.json", result)
    return result


def build(page, plate: str, admin_token: str = "", officer_token: str = "",
          *, base: str = "http://127.0.0.1:8083", government: list[str] | None = None,
          gallery: Path | None = None, csv_path: Path | None = None,
          opening_layout: str = "dense", wall_cameras: list[str] | None = None) -> list[Beat]:
    government = government or []
    wall_cameras = government if wall_cameras is None else wall_cameras
    selected = {"camera": None}
    gallery = gallery or ROOT / "var/demo/plate_gallery/gallery.html"

    handoffs = [0]

    def use_token(token, role, view, content):
        if not token:
            raise RecorderFailure("role token missing")
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
        # A different query forces exactly one document navigation (a hash-only
        # navigation would leave the previous principal in app state).
        # A repeated role URL would be a hash-only change: no document loads, the
        # view never switches. Each handoff gets its own query.
        handoffs[0] += 1
        page.goto(base.rstrip('/') + f'/ui/?recorder-role={role}&handoff={handoffs[0]}#{view}',
                  wait_until='domcontentloaded')
        # The registry view computes capability over the whole store; give it
        # time. Capture is paused while a beat prepares.
        wait_view(page, view, content, timeout=150000)

    def wall_group(fraction):
        def go():
            # Grid makes deliberate top/middle/bottom views possible when Dense fits.
            wall_mode(page, "grid")
            wait_view(page, "live", "#live-grid .live-tile")
        return go

    def focus():
        # Candidates are measured on the wall, before Focus: in Focus the strip
        # tiles hold no session, so their motion cannot be measured there.
        if "candidates" not in selected:
            latest = sample_video(page, wall_ids(page, wall_cameras), 1)
            ids = latest["live_ids"]
            if not ids:
                raise RecorderFailure("no advancing government camera for focus")
            selected["candidates"] = focus_order(ids)
            selected["tried"] = []
            # Command chrome hides the filmstrip even in Focus; expose it first.
            if page.locator('#btn-command-bar').get_attribute('aria-pressed') != 'true':
                page.click('#btn-command-bar')
            # Layout changes preserve tile decoders; selecting uses the app's shared PC.
            wall_mode(page, "focus")
        for cid in [c for c in selected["candidates"] if c not in selected["tried"]]:
            selected["tried"].append(cid)
            selected["camera"] = cid
            page.locator(f'#live-strip .live-tile[data-camera="{cid}"]').click()
            page.wait_for_selector('#live-stage video', timeout=30000)
            deadline = time.monotonic() + FOCUS_START_S
            while time.monotonic() < deadline:
                measured = sample_video(page, [cid], 1, focus=True)
                if measured["passed"] and measured['visible_live']:
                    wait_view(page, "live", "#live-sidecar")
                    return {"camera": cid, "video": measured}
        raise RecorderFailure("no measured-advancing government camera held in focus")

    def analytics():
        cid = selected["camera"]
        if not cid:
            raise SkipBeat("no selected government camera")
        wait_view(page, "live", "#live-sidecar")
        if not page.locator('#here-plate-row .here-plate').count():
            raise SkipBeat('no stored plate observations rendered for the selected camera')
        page.locator('#here-plate-row .here-plate').first.scroll_into_view_if_needed()
        return {"camera": cid}

    def search_form(mark='', camera='', object_type=''):
        if page.url.startswith('file:'):
            page.goto(base.rstrip('/') + '/ui/#investigate', wait_until='domcontentloaded')
            wait_view(page, 'investigate', '#q-plate')
        else:
            navigate(page, 'investigate', '#q-plate')
        page.fill('#case-id', 'FIR-000/2026')
        page.fill('#purpose', 'reviewing government camera observations')
        # Person and plate beats share a form: no stale camera/type/date filter.
        for selector in ('#q-colour', '#q-district', '#q-from', '#q-to', '#q-event', '#q-severity'):
            page.fill(selector, '')
        page.uncheck('#q-fuzzy')
        page.uncheck('#q-watchlist')
        page.fill('#q-plate', mark)
        page.fill('#q-camera', camera)
        page.fill('#q-type', object_type)
        wait_search_idle(page)
        with page.expect_response(lambda r: '/search?' in r.url and r.request.method == 'GET') as pending:
            page.press('#q-plate', 'Enter')
        response = pending.value
        if response.status != 200:
            raise RecorderFailure('search refused or unavailable')
        rows = response.json().get('candidates', [])
        page.wait_for_function("() => !document.querySelector('#search-form button[type=submit]').disabled")
        wait_view(page, 'investigate', '#results .result, #results .empty, #results .notice')
        return rows

    def persons():
        if 'cam12' not in government:
            raise RecorderFailure('cam12 is not a government camera in this registry')
        rows = search_form(camera='cam12', object_type='person')
        if not rows or any(r.get('camera_id') != 'cam12' or r.get('object_type') != 'person' for r in rows):
            raise RecorderFailure('government person detections were not returned')
        page.wait_for_selector('#results .result')
        return {'camera': 'cam12', 'object_type': 'person', 'returned_observations': len(rows)}

    def restricted_zone():
        status, data = api_read(base, officer_token, '/zones')
        name = 'No pedestrians on the toll-lane carriageway'
        rules = [r for r in data.get('rules', []) if r.get('camera_id') == 'cam12'
                 and r.get('name') == name and 'person' in r.get('classes', [])]
        if status != 200 or len(rules) != 1:
            raise RecorderFailure('cam12 demonstration person-zone rule is unavailable')
        navigate(page, 'analytics', '#analytics .zone-rule')
        rule = page.locator('#analytics .zone-rule').filter(has_text=name)
        rule.locator('.zone-count').wait_for(state='visible')
        rule.scroll_into_view_if_needed()
        return {'camera': 'cam12', 'rule_id': rules[0]['rule_id'],
                'name': name, 'label': 'DEMONSTRATION RULE',
                'rendered_entries': rule.locator('.zone-count').inner_text()}

    def plate_gallery():
        # plateCard uses snapshots. herePlateCard calls /plate.jpg, whose route
        # crops the CURRENT still with a stored box, not the captured evidence.
        # Neither qualifies as a gallery of stored evidence crops.
        manifest = gallery.with_name('selected.json')
        stats_path = gallery.with_name('stats.json')
        if not gallery.is_file() or not manifest.is_file():
            raise SkipBeat("plate gallery or selected.json absent")
        rows = json.loads(manifest.read_text(encoding='utf-8'))
        required = {'image', 'camera', 'timestamp', 'plate_text', 'confidence', 'agreeing_reads', 'provenance'}
        if not isinstance(rows, list) or not rows or any(
                not isinstance(r, dict) or not required <= r.keys()
                or r['camera'] not in government or not r['provenance'] for r in rows):
            raise SkipBeat("gallery contract or government provenance missing")
        # The producer does not put source_domain in selected.json. Its camera
        # is checked against our registry; stats cover all reads, not selection.
        if not stats_path.is_file():
            raise SkipBeat('gallery stats.json absent')
        stats = json.loads(stats_path.read_text(encoding='utf-8'))
        stat_keys = ('total_reads', 'distinct_plates', 'confirmed_registrations',
                     'confirmed_reads', 'cameras_with_reads', 'government_cameras_in_registry')
        if not isinstance(stats, dict) or any(type(stats.get(k)) is not int or stats[k] < 0 for k in stat_keys):
            raise SkipBeat('gallery stats.json contract missing')
        page.goto(gallery.resolve().as_uri(), wait_until='domcontentloaded')
        page.wait_for_function("() => document.images.length > 0 && "
                               "[...document.images].every(i => i.complete && i.naturalWidth > 16)")
        return {"manifest": str(manifest), "crops": len(rows),
                "store_stats": {k: stats[k] for k in stat_keys}}

    def search():
        rows = search_form(mark=plate)
        search_beat.title = search_caption(rows, government)
        return {"sightings": len(rows), "cameras": sorted({r.get('camera_id', '') for r in rows}),
                "single_camera": single_camera(rows)}

    def gis():
        cid = selected['camera']
        if not cid:
            raise SkipBeat('no selected government camera')
        navigate(page, 'map', '#registry-rail .registry-chip')
        chip = page.locator('#registry-rail .registry-chip').filter(
            has=page.locator(f'img[alt="{cid}"]'))
        if chip.count() != 1 or 'unlocated' in (chip.get_attribute('class') or ''):
            raise SkipBeat('selected camera has no recorded map location')
        chip.click()
        page.wait_for_function("cid => document.querySelector('#map-detail')?.innerText.includes(cid)", arg=cid)
        page.wait_for_function("() => { const m = (" + MAP_SAMPLE + ")(); return m.visible && m.markers > 0; }")
        return {"camera": cid, "map": page.evaluate(MAP_SAMPLE)}

    def trace_report():
        navigate(page, 'investigate', '#btn-trace-report')
        page.click('#btn-trace-report')
        page.wait_for_function("""() => {
          const doc = document.querySelector('#report-frame')?.contentDocument;
          return doc?.querySelector('table tr td') && doc.body.innerText.trim().length > 0;
        }""")

    def report_csv():
        if not csv_path or not csv_path.is_file():
            raise RecorderFailure('ANPR CSV was not downloaded')
        # A local read-only view of the exact CSV delivered beside the film.
        rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding='utf-8'))))
        if not rows:
            raise RecorderFailure('ANPR CSV contains no observations')
        import html
        keys = list(rows[0])
        table = '<tr>' + ''.join('<th>' + html.escape(k) + '</th>' for k in keys) + '</tr>'
        table += ''.join('<tr>' + ''.join('<td>' + html.escape(r[k] or '') + '</td>' for k in keys) + '</tr>' for r in rows[:20])
        local = csv_path.with_suffix('.html')
        local.write_text('<!doctype html><meta charset="utf-8"><style>body{font:22px sans-serif;padding:40px}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:left}</style><h1>ANPR CSV — stored observations</h1><table>' + table + '</table>', encoding='utf-8')
        page.goto(local.resolve().as_uri(), wait_until='domcontentloaded')
        page.wait_for_selector('table tr td')
        return {"csv": str(csv_path), "rows": len(rows)}

    def evidence():
        # From inside the app a goto to /ui/#evidence is a hash-only change: no
        # document loads and the view never switches. Use the navigation there.
        if page.url.startswith(base.rstrip('/') + '/ui/'):
            if page.locator("#report-dialog[open]").count():
                page.click("#report-close")
            page.click('button[data-view="evidence"]')
        else:
            page.goto(base.rstrip('/') + '/ui/#evidence', wait_until='domcontentloaded')
        wait_view(page, 'evidence', '#evidence-chain table', timeout=120000)

    def onboarded():
        use_token(admin_token, 'administrator', 'cameras', '#cameras table tbody tr')

    def system_status():
        navigate(page, 'system', '#system .command-grid .health-row')
        page.locator('#system .command-grid .health-row').first.scroll_into_view_if_needed()

    def bulk():
        if page.locator('#btn-onboard-toggle').get_attribute('aria-expanded') != 'true':
            page.click('#btn-onboard-toggle')
        page.click('[data-onboard="bulk"]')
        text = (ROOT / 'reports/sample_camera_metadata.csv').read_text(encoding='utf-8')
        page.fill('#ob-csv', dry_run_rows(text, namespace=uuid.uuid4().hex[:10]))
        page.uncheck('#ob-bulk-update')
        with page.expect_response(lambda r: '/registry/cameras/import.csv?dry_run=true' in r.url) as pending:
            page.click('#btn-ob-bulk-dry')
        if pending.value.status != 200:
            raise RecorderFailure('bulk validation failed')
        page.wait_for_selector('#onboard-result.ok')
        wait_view(page, 'cameras', '#onboard-result.ok')

    def refused():
        navigate(page, 'investigate', '#q-plate')
        page.fill('#case-id', 'FIR-000/2026')
        page.fill('#purpose', 'checking the registry role separation')
        page.fill('#q-plate', plate)
        wait_search_idle(page)
        # The form is idle, so the next search for this plate is the administrator's.
        # A 200 here (wrong role in effect) still fails the beat below.
        with page.expect_response(lambda r: '/search?' in r.url and f'plate={plate}' in r.url) as pending:
            page.press('#q-plate', 'Enter')
        if pending.value.status != 403:
            raise RecorderFailure('expected administrator refusal not observed '
                                  f'(HTTP {pending.value.status})')
        wait_view(page, 'investigate', '#results .notice.bad', allow_error=True)

    search_beat = Beat('Designated plate — sightings with timestamps and camera', 30, search,
                       'The officer searches under a case and stated purpose. Each returned observation names its camera and timestamp.')
    return [
        *opening_beats(page, opening_layout, wall_group),
        Beat('One advancing government camera, with its intelligence panel', 28, focus,
             'A camera with measured advancing frames, beside its intelligence panel. The panel states the available observations.',
             visible_motion=True, retry=focus),
        Beat('Analytics output on the selected government camera', 18, analytics,
             'These are the observations available for this camera. Viewing a stream does not imply that every camera is under deep analysis.', optional=True),
        Beat('Government person detections — cam12, stored observations', 18, persons,
             'Stored person detections on government camera cam12, with camera and timestamps. These are object observations, not identified people.'),
        Beat('cam12 restricted zone — DEMONSTRATION RULE set by the estate administrator', 18, restricted_zone,
             'No pedestrians on the toll-lane carriageway. This is a demonstration rule set by the estate administrator. The screen reports sightings against that rule, not identities or a claim of unlawful intrusion.'),
        Beat('Government ANPR — measured observations (crops from the evidence store)', 24, plate_gallery,
             'Retained government crops and recorded reads. Older sealed stills can show a different vehicle from the recorded plate. Verify each crop against its provenance; a hash alone does not establish that match.', optional=True),
        search_beat,
        Beat('GIS — selected camera and recorded location', 18, gis,
             'The selected camera at its recorded location. Read the location basis beside the map.', optional=True),
        Beat('The trace report — reads and timestamps', 22, trace_report,
             'The trace report is generated from the same store, with the reads, timestamps and integrity information.'),
        Beat('ANPR CSV — the output delivered with this film', 12, report_csv,
             'The CSV delivered beside this recording contains stored plate observations and their camera timestamps.'),
        Beat('Evidence — integrity results and stated cautions', 18, evidence,
             'Evidence verification reports integrity separately from cautions about what a record says.'),
        Beat('System status and resilience', 24, system_status,
             'Subsystem health and the reported analysis coverage. Unavailable measurements remain unavailable.'),
        Beat('Model 1 — cameras onboarded, as estate administrator', 16, onboarded,
             'The estate administrator manages registry metadata and measured capability.'),
        Beat('Bulk onboarding — validation only', 12, bulk,
             'A sample spreadsheet is validated before import. This demonstration performs no import.'),
        Beat('Role separation — administrator search refused', 8, refused,
             'The administrator may manage the estate but may not search vehicle observations.'),
        Beat('Handing back to the investigating officer', 8,
             lambda: use_token(officer_token, 'officer', 'cameras', '#cameras table tbody tr'),
             'The investigating officer takes over. Searches remain attributable to the signed-in role.'),
    ]
def require_ui(page, *selectors: str) -> None:
    for selector in selectors:
        if not page.locator(selector).count():
            raise SkipBeat(f'UI unavailable: {selector}')


def absent_feature(reason: str):
    def skip():
        raise SkipBeat(reason)
    return skip


def build_full(page, plate: str, admin_token: str = '', officer_token: str = '',
               *, base: str = 'http://127.0.0.1:8083', government=None, gallery=None,
               csv_path=None, opening_layout='dense', wall_domain='government',
               wall_cameras=None, replay_dates=None, officer_id='') -> list[Beat]:
    """Executable operator story. Selectors and source citations travel with the plan.

    Missing UI/data produces a named skip. A present control that fails its
    response/readiness checks fails the take. No invented watchlist CRUD UI.
    """
    old = build(page, plate, admin_token, officer_token, base=base,
                government=government, gallery=gallery, csv_path=csv_path,
                opening_layout=opening_layout, wall_cameras=wall_cameras)
    wall_count = 4 if opening_layout == 'dense' else 5
    wall = old[:wall_count]
    (focus, analytics, persons, zone, crops, exact, gis, trace, csv_beat,
     evidence, health, registry, bulk, refused, handoff) = old[wall_count:]
    dates = replay_dates or {}
    downloads = Path(csv_path).parent if csv_path else ROOT / 'var/demo'

    def view(name, selector):
        require_ui(page, f'button[data-view="{name}"]')
        navigate(page, name, f'#view-{name}')
        # Some loaders (alerts/cases) leave the old DOM in place or start with
        # no loading-note. Wait for the output, not merely the active section.
        try:
            page.wait_for_selector(selector, timeout=30000)
        except Exception:
            require_ui(page, selector)  # Absent output is a logged skip.
            raise
        # The loader can render twice (old DOM, then fresh); re-locate after a detach.
        for attempt in range(3):
            try:
                page.locator(selector).first.scroll_into_view_if_needed()
                break
            except Exception as exc:
                if attempt == 2 or 'not attached' not in str(exc):
                    raise
                page.wait_for_timeout(400)

    def feature(title, action, selectors, source, say='', dwell=20):
        return Beat(title, dwell, action, say, optional=True,
                    selectors=tuple(selectors), sources=(source,))

    def gate():
        if not officer_id or '@' in officer_id:
            raise RecorderFailure('a non-email officer user_id is required for gate sign-in')
        page.evaluate("() => { sessionStorage.setItem('gov.recorder.gate', '1'); "
                      "sessionStorage.removeItem('saakshya.token'); }")
        page.goto(base.rstrip('/') + '/ui/?recorder-gate=1#overview', wait_until='domcontentloaded')
        page.wait_for_selector('#gate:not([hidden]) #gate-token')
        require_ui(page, '#gate-officer', '#gate-case', '#gate-purpose')
        if page.locator('#gate-token').get_attribute('type') != 'password':
            raise RecorderFailure('gate token input is not masked')
        page.fill('#gate-officer', officer_id)
        page.fill('#gate-case', 'FIR-000/2026')
        page.fill('#gate-purpose', 'demonstrating review of government observations')
        page.fill('#gate-token', officer_token)

    def overview():
        page.click('#gate-form button[type="submit"]')
        wait_view(page, 'overview', '#overview .command-grid, #overview .ov-card')
        page.evaluate("() => sessionStorage.removeItem('gov.recorder.gate')")

    def return_wall():
        view('live', '#live-grid .live-tile')
        require_ui(page, f'[data-live-domain="{wall_domain}"]')
        page.click(f'[data-live-domain="{wall_domain}"]')
        wall_mode(page, opening_layout)
        wait_view(page, 'live', '#live-grid .live-tile')

    wall[0].action = return_wall
    for b in wall:
        b.selectors = ('#live-grid .live-tile', '#media-policy', f'[data-live-domain="{wall_domain}"]')
        b.sources = ('ui/index.html:308', 'ui/app.js:2764')
        if wall_domain == 'replay':
            b.title = 'Recorded government wall — ' + ('CONTROL ROOM' if 'CONTROL ROOM' in b.title else 'OPTIMIZED VIEW')
            b.say = 'Recorded government footage, replayed from captured files. Playback is measured separately from stored analytics.'
    if wall_domain == 'replay':
        focus.title = 'RECORDED GOVERNMENT FOOTAGE · captured ' + ', '.join(sorted(set(dates.values()))) + ' · replayed'
        focus.say = 'This government recording is replayed beside its intelligence panel. It is recorded footage.'
        analytics.say = 'The panel states the observations available for this recorded camera. Replay findings retain their archival source domain.'

    # Existing guarded actions remain the authority for these features.
    for b, selectors, source in [
        (focus, ('#live-stage video', '#live-sidecar'), 'ui/app.js:5231'),
        (analytics, ('#here-plate-row .here-plate',), 'ui/app.js:3754'),
        (persons, ('#q-type', '#q-camera', '#results .result'), 'ui/index.html:149'),
        (zone, ('#analytics .zone-rule', '.zone-count'), 'ui/app.js:2435'),
        (crops, ('img',), 'tools/demo/record_government_feed.py:plate_gallery'),
        (exact, ('#case-id', '#purpose', '#q-plate', '#results'), 'ui/index.html:149'),
        (gis, ('#map2', '#registry-rail .registry-chip'), 'ui/app.js:1438'),
        (trace, ('#btn-trace-report', '#report-frame'), 'ui/app.js:7699'),
        (csv_beat, ('table tr td',), 'tools/demo/record_government_feed.py:fetch_report'),
        (evidence, ('#evidence-chain table',), 'ui/app.js:5953'),
        (registry, ('#cameras table tbody tr', '#cap-note'), 'ui/app.js:5629'),
        (bulk, ('#btn-ob-bulk-dry', '#ob-csv'), 'ui/app.js:7418'),
        (health, ('#system .command-grid .health-row',), 'ui/app.js:2543'),
        (refused, ('#q-plate', '#results .notice.bad'), 'ui/app.js:646'),
        (handoff, ('#cameras table tbody tr',), 'ui/app.js:619'),
    ]:
        if source.startswith('tools/'):
            source = f'tools/demo/record_government_feed.py:{b.action.__code__.co_firstlineno}'
        b.selectors, b.sources = selectors, (source,)
        b.dwell_s = max(b.dwell_s, 20)
    exact.title = 'Representative plate — case, purpose and timestamped observations'
    exact.say = 'This plate is a team-selected representative from government reads, not the organiser-issued evaluation mark. Government histories in this store are single-camera.'
    analytics.visible_motion, analytics.retry = True, focus.action

    def search_variant(kind):
        # Reuse the UI response, including its case/purpose headers. No hidden
        # unaudited API search and no invented colour/type values.
        with page.expect_response(lambda r: '/search?' in r.url and r.request.method == 'GET') as baseline:
            exact.action()
        if kind == 'partial':
            # GJ11S*: a prefix the replayed recordings' plates do not share.
            page.fill('#q-plate', plate[:5] + '*')
        elif kind == 'fuzzy':
            page.check('#q-fuzzy')
            replacement = '0' if plate[-1:] != '0' else '1'
            page.fill('#q-plate', plate[:-1] + replacement)
        else:
            data = baseline.value.json()
            rows = [r for r in data.get('candidates', []) if r.get('camera_id') in (government or [])
                    and r.get('object_type') and (r.get('colour') or r.get('color'))]
            if not rows:
                raise SkipBeat('no government observation has colour, type and camera for attribute search')
            row = rows[0]
            page.fill('#q-plate', '')
            page.fill('#q-colour', row.get('colour') or row['color'])
            page.fill('#q-type', row['object_type'])
            page.fill('#q-camera', row['camera_id'])
        wait_search_idle(page)
        with page.expect_response(lambda r: '/search?' in r.url and r.request.method == 'GET') as pending:
            page.press('#q-plate', 'Enter')
        if pending.value.status != 200:
            raise RecorderFailure('search variant failed')
        body = pending.value.json()
        rows = body.get('candidates', [])
        # A pattern search answers with marks, each naming its cameras.
        cams = [r.get('camera_id') for r in rows] + [
            c.get('camera_id') if isinstance(c, dict) else c
            for m in body.get('marks', []) for c in m.get('cameras', [])]
        if any(c not in (government or []) for c in cams):
            raise SkipBeat('search variant returned non-government sources; omitted from government film')
        wait_view(page, 'investigate', '#results .result, #results .empty, #results .notice, #results .mark-row')
        rows = rows or body.get('marks', [])
        return {'variant': kind, 'returned_observations': len(rows)}

    def trajectory():
        exact.action()
        require_ui(page, '#traj-body', '#map')
        page.locator('#traj-body').scroll_into_view_if_needed()

    def verify():
        evidence.action()
        button = page.locator('#evidence-chain button').filter(has_text='Verify now')
        if not button.count():
            raise SkipBeat('UI unavailable: #evidence-chain button Verify now')
        with page.expect_response(lambda r: '/evidence/chain/verify?fresh=1' in r.url,
                                  timeout=180000) as pending:
            button.click()
        if pending.value.status != 200:
            raise RecorderFailure('fresh evidence verification unavailable')
        wait_view(page, 'evidence', '#evidence-chain .ev-when', timeout=180000, allow_error=True)
        body = pending.value.json()
        # The endpoint reports 'verified', 'failures' and 'cautions'; there is no 'ok'.
        return {'integrity_ok': body.get('verified') is True and not body.get('failures'),
                'cautions': len(body.get('cautions') or [])}

    def cases():
        with page.expect_response(lambda r: '/cases' in r.url and r.request.method == 'GET') as pending:
            view('cases', '#case-list')
        if pending.value.status != 200:
            raise SkipBeat('case list unavailable to this role')
        page.wait_for_selector('#case-list .result, #case-list .empty')
        require_ui(page, '#case-list .result')
        page.locator('#case-list .result').first.click()
        page.wait_for_selector('#case-detail dl')

    def export_case():
        cases()
        require_ui(page, '#btn-export-case')
        with page.expect_download() as pending:
            page.click('#btn-export-case')
        destination = downloads / 'government_tour_case_export.json'
        retain_download(pending.value, destination, (officer_token, admin_token))
        return {'export': str(destination)}

    def native_gallery():
        restore_officer_workspace()
        view('overview', '#overview .plate-gallery')
        page.wait_for_function("() => [...document.querySelectorAll('#overview .plate-gallery img')]"
                               ".every(i => i.complete)")

    def ui_csv():
        native_gallery()
        button = page.get_by_role('button', name='Download ANPR report (CSV)', exact=True)
        if not button.count():
            raise SkipBeat('ANPR CSV download button is unavailable')
        with page.expect_download() as pending:
            button.click()
        destination = downloads / 'government_tour_ui_anpr_all_domains.csv'
        retain_download(pending.value, destination, (officer_token, admin_token))
        return {'export': str(destination), 'scope': 'UI export; all source domains'}

    def copilot():
        status, config = api_read(base, officer_token, '/copilot/describe')
        if status != 200 or not config.get('available') or 'gemini' not in str(config.get('backend', '')).lower():
            raise SkipBeat('Gemini is not configured')
        view('copilot', '#chat-input')
        # A focused question: the broad capability question ran into the
        # coordinator's six-step limit without a final answer (measured twice).
        page.fill('#chat-input', f'Where has {plate} been seen, and how strong is that evidence?')
        # The coordinator makes several model calls in turn: 17-108 s measured.
        # Capture is paused meanwhile; an answer that never comes is a named skip.
        try:
            with page.expect_response(lambda r: '/copilot/ask' in r.url, timeout=240000) as pending:
                page.press('#chat-input', 'Enter')
            answer = pending.value.json() if pending.value.status == 200 else {}
        except Exception as exc:
            if 'Timeout' not in type(exc).__name__:
                raise
            raise SkipBeat('Gemini did not answer within 240 s') from None
        if not answer.get('grounded'):
            raise SkipBeat('copilot did not return a grounded answer')
        if not str(answer.get('answer') or '').strip():
            raise SkipBeat('copilot returned no prose to show')
        page.wait_for_selector('#chat-log .msg.bot:not(.dim) .md', state='attached', timeout=30000)
        page.locator('#chat-log .msg.bot .md').last.scroll_into_view_if_needed()

    def manual():
        view('cameras', '#btn-onboard-toggle')
        if page.locator('#btn-onboard-toggle').get_attribute('aria-expanded') != 'true':
            page.click('#btn-onboard-toggle')
        page.click('[data-onboard="manual"]')
        for selector, value in {'#ob-camera-id': 'DRYRUN-' + uuid.uuid4().hex[:10],
                                '#ob-name': 'DEMO validation only', '#ob-department': 'Police',
                                '#ob-district': 'Ahmedabad', '#ob-lat': '23.03',
                                '#ob-lon': '72.58', '#ob-retention': '15'}.items():
            page.fill(selector, value)
        page.uncheck('#ob-update-existing')
        with page.expect_response(lambda r: r.url.endswith('/registry/cameras/import')
                                  and r.request.method == 'POST') as pending:
            page.click('#btn-ob-dry')
        response = pending.value
        if response.status != 200 or response.request.post_data_json.get('dry_run') is not True:
            raise RecorderFailure('manual dry-run validation failed')
        wait_view(page, 'cameras', '#onboard-result.ok')

    def grades():
        view('cameras', '#reg-anpr')
        page.select_option('#reg-anpr', 'GOOD')
        page.wait_for_function("() => document.querySelector('#reg-count').textContent.length > 0")

    def gaps():
        page.click('#btn-reg-clear')
        card = page.locator('#cameras .ov-card').filter(has_text='Registry gap analysis')
        if not card.count():
            raise SkipBeat('registry gap analysis is unavailable')
        card.scroll_into_view_if_needed()

    def layers():
        view('map', '#map2')
        require_ui(page, '[data-mode2="capability"]')
        page.click('[data-mode2="capability"]')
        page.wait_for_selector('[data-mode2="capability"].on')
        page.locator('#legend2').scroll_into_view_if_needed()

    def map_filter():
        view('map', '#map2')
        require_ui(page, '#map-filter-q')
        page.fill('#map-filter-q', 'junagadh')
        page.wait_for_function("() => /match .junagadh./.test("
                               "document.querySelector('#map2-count')?.textContent || '')")
        page.wait_for_function("() => /match .junagadh./.test("
                               "document.querySelector('#registry-rail .registry-rail-head')?.textContent || '')")

    def systems():
        view('system', '#system .panel')
        panel = page.locator('#system .panel').filter(has_text='Connected systems · DEMO / TEST')
        if not panel.count():
            raise SkipBeat('connected systems panel is unavailable')
        panel.scroll_into_view_if_needed()

    def audit():
        # ADMIN has audit:read; the investigator does not. State the role explicitly.
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", admin_token)
        page.goto(base.rstrip('/') + '/ui/?recorder-role=administrator#audit', wait_until='domcontentloaded')
        wait_view(page, 'audit', '#audit table')
        page.wait_for_function("() => /chain verified|CHAIN BROKEN/.test(document.querySelector('#audit-chain').textContent)")

    incident = {}

    def queue():
        with page.expect_response(lambda r: '/alerts?grouped=true' in r.url) as pending:
            view('alerts', '#alerts .inc-summary')
        if pending.value.status != 200:
            raise RecorderFailure('alert queue unavailable')

    def selected_incident():
        queue()
        # "All" re-renders the queue into a new container. Its old render can
        # hold the same number of cards, so wait for the new node, not a count.
        page.evaluate("() => document.querySelector('#alerts .incidents')?.setAttribute('data-stale', '1')")
        with page.expect_response(lambda r: '/alerts?grouped=true&status=&' in r.url) as pending:
            page.click('[data-alert-status=""]')
        if pending.value.status != 200:
            raise RecorderFailure('all-status alert queue unavailable')
        groups = pending.value.json().get('groups', [])
        page.wait_for_function("n => { const box = document.querySelector('#alerts .incidents'); "
                               "return !!box && !box.hasAttribute('data-stale') && "
                               "box.querySelectorAll('.incident').length === n; }", arg=len(groups))
        wait_view(page, 'alerts', '#alerts .inc-summary')
        cards = page.locator('#alerts .incident')
        if incident.get('group'):
            # Exact group identity survives queue reordering after transitions.
            cards = page.locator('#alerts .incident').filter(
                has=page.locator('.inc-plate', has_text=re.compile('^' + re.escape(plate) + '$')))
            cards = cards.filter(has=page.locator('.inc-cat'))
            cards = [c for c in cards.all() if c.get_attribute('data-group') == incident['group']]
            if not cards:
                raise SkipBeat('selected representative incident no longer present')
            return cards[0]
        cards = cards.filter(has=page.locator('.inc-plate', has_text=re.compile('^' + re.escape(plate) + '$')))
        if not cards.count():
            raise SkipBeat('no incident for the representative plate')
        card = cards.first
        incident['group'] = card.get_attribute('data-group')
        card.scroll_into_view_if_needed()
        return card

    def settled(fn, attempts=3):
        """Re-run a locate-and-act step a render detached; nothing was sent yet."""
        for i in range(attempts):
            try:
                return fn()
            except Exception as exc:
                if i == attempts - 1 or 'not attached' not in str(exc):
                    raise
                page.wait_for_timeout(400)

    def open_incident():
        settled(lambda: selected_incident().focus())

    def transition(action):
        card = settled(selected_incident)
        label = {'acknowledge': 'Acknowledge', 'investigate': 'Investigate', 'resolve': 'Resolve…'}[action]
        button = card.get_by_role('button', name=re.compile('^' + re.escape(label)))
        if not button.count():
            raise SkipBeat(f'no {action} control for the selected incident')
        if action == 'resolve':
            button.click()
            card.locator('[aria-label="Disposition"]').select_option('cleared')
            card.locator('[aria-label="Reason"]').fill('Representative demonstration concluded; no operational determination.')
            button = card.get_by_role('button', name='Resolve all reads')
        with page.expect_response(lambda r: '/alerts/transition' in r.url
                                  and r.request.method == 'POST') as pending:
            button.click()
        if pending.value.status != 200:
            raise RecorderFailure('incident transition did not change any alert')
        if not pending.value.json().get('changed'):
            raise SkipBeat('representative incident already transitioned; no alert changed')
        if action == 'investigate':
            wait_view(page, 'investigate', '#results .result, #results .empty')
        else:
            wait_view(page, 'alerts', '#alerts .inc-summary')
        return {'action': action, 'changed': len(pending.value.json()['changed'])}

    def watchlist():
        view('intelligence', '#intel-watchlist')
        page.locator('#intel-wl-cats').scroll_into_view_if_needed()

    def restore_officer_workspace():
        page.goto(base.rstrip('/') + '/ui/#overview', wait_until='domcontentloaded')
        wait_view(page, 'overview', '#overview .ov-card, #overview .command-grid')

    result = [
        Beat('Sign-in gate — officer, masked token, case and purpose', 14, gate,
             'The officer signs in with a masked access token, a case identifier and a stated purpose.',
             selectors=('#gate-officer', '#gate-token', '#gate-case', '#gate-purpose'),
             sources=('ui/index.html:823', 'ui/app.js:449'), gate=True),
        feature('Overview — command dashboard', overview, ('#overview',), 'ui/index.html:303',
                'The command dashboard reports the signed-in role, estate status and available observations.', 26),
        *wall, focus, analytics, persons, zone, crops,
        feature('ANPR gallery — current previews and stored reads · mixed sources', native_gallery,
                ('#overview .plate-gallery',), 'ui/app.js:1937',
                'Current previews sit beside stored reads. This view can include own feeds and the synthetic rendered test corpus; these previews are not sealed evidence.', 14),
        feature('ANPR CSV — UI export across source domains', ui_csv,
                ('#overview button',), 'ui/app.js:2018',
                'The UI exports stored reads across source domains. The separate government-only CSV accompanies this film.', 14),
        csv_beat,
        # The CSV/gallery are local documents; return to the application first.
        feature('Return to officer workspace', restore_officer_workspace,
                ('#overview',), 'ui/index.html:303', dwell=1),
        feature('Watchlist matches and categories — own-feed intelligence workspace', watchlist,
                ('#intel-watchlist', '#intel-wl-cats'), 'ui/index.html:477',
                'This panel lists watchlist matches by category. The own-feed intelligence workspace is separate from the government wall.'),
        feature('Watchlist entry creation — unavailable UI', absent_feature('No watchlist add form in ui/index.html or ui/app.js'),
                (), 'ui/app.js:7198', dwell=0),
        feature('Alerts — queue and incident grouping', queue, ('#alerts .inc-summary', '#alerts .incident'), 'ui/app.js:8050',
                'The queue groups reads into vehicle incidents. Categories and recorded reasons remain visible.'),
        feature('Open the representative alert incident', open_incident, ('#alerts .incident', '.inc-plate'), 'ui/app.js:7995'),
        *[feature('Representative alert — ' + action, lambda action=action: transition(action),
                  ('#alerts .incident button',), 'ui/app.js:7958',
                  'A representative demonstration incident. The transition is recorded in the audit log.')
          for action in ('acknowledge', 'investigate', 'resolve')],
        exact,
        *[feature('Investigate — ' + kind + ' search', lambda kind=kind: search_variant(kind),
                  ('#q-plate', '#q-fuzzy', '#q-colour', '#q-type', '#q-camera'), 'ui/index.html:153',
                  'Results remain observations to review; near matches do not establish vehicle identity.')
          for kind in ('partial', 'fuzzy', 'attribute')],
        feature('Trajectory and route panel — government single-camera history', trajectory,
                ('#traj-body', '#map'), 'ui/app.js:1139',
                'The government history is single-camera. This does not demonstrate a real cross-camera route.'),
        gis, evidence,
        feature('Evidence — fresh integrity verification', verify, ('#evidence-chain button',), 'ui/app.js:6000',
                'Verification checks stored bytes and the chain. It cannot prove that an older still depicts the recorded vehicle.'),
        # A prior local document navigation cleared in-memory search state.
        feature('Trace report — restore the representative search', trajectory, ('#q-plate',), 'ui/app.js:7699', dwell=1),
        trace,
        feature('Cases — case file and attached evidence', cases, ('#case-list .result', '#case-detail'), 'ui/app.js:5790'),
        feature('Evidence export — case package', export_case, ('#btn-export-case',), 'ui/app.js:5917',
                'The case export contains the selected case and its attachments; the package reports audit integrity.'),
        feature('Gemini copilot — grounded capability question, if configured', copilot,
                ('#chat-input', '#chat-log'), 'ui/app.js:6240'),
        feature('Audit log — administrator hash-chain check', audit, ('#audit', '#audit-chain'), 'ui/app.js:5934',
                'The estate administrator can inspect the audit chain. Investigator access remains separate.'),
        registry,
        feature('Model 1 — measured capability grades and registry filters', grades,
                ('#reg-anpr', '#reg-count'), 'ui/index.html:651'),
        feature('Model 1 — registry gap analysis', gaps, ('#cameras .ov-card',), 'ui/app.js:5645'),
        feature('Model 1 — manual onboarding, validation only', manual,
                ('#onboard-manual', '#btn-ob-dry'), 'ui/app.js:7378',
                'A fresh demonstration identifier is validated through the form. No camera is imported.'),
        bulk,
        feature('Model 1 — GIS capability layer', layers, ('[data-mode2="capability"]', '#legend2'), 'ui/app.js:1642'),
        feature('GIS — camera search on the estate map', map_filter,
                ('#map-filter-q', '#map2-count', '#registry-rail'), 'ui/app.js:1664',
                'The estate map narrows to the cameras matching a district, name or identifier, and the registry strip follows.', 16),
        feature('Model 3 — connected systems and adapters · DEMO / TEST', systems,
                ('#system .panel',), 'ui/app.js:2516',
                'These demo and test systems exercise the federation adapter contract. They are not verified government VMS integrations.'),
        # Analytics needs the officer; preserve the final administrator refusal later.
        feature('Officer handoff for Model 4 analytics', handoff.action, ('#cameras',), 'ui/app.js:619', dwell=1),
        feature('Model 4 — selected analytics output and timebase', lambda: view('analytics', '#analytics .command-grid'),
                ('#analytics .command-grid',), 'ui/app.js:2370',
                'Selected cameras run detection, tracking and ANPR. Deep-inference slots are prioritised by measured capability; they do not rotate at runtime.'),
        health,
        feature('Watchlist revocation — no entry created', absent_feature('No watchlist revoke control exists; this tour added no entry'),
                (), 'ui/app.js:7198', dwell=0),
        feature('Administrator handoff for RBAC check', registry.action, ('#cameras',), 'ui/app.js:619', dwell=1),
        refused, handoff,
    ]
    return result


def private_text(value: str, secrets: tuple[str, ...] = ()) -> bool:
    """Fail closed without returning the offending text to logs or reports."""
    return any(s and s in value for s in secrets) or bool(
        re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', value))


def retain_download(download, destination: Path, secrets: tuple[str, ...]) -> None:
    """Never trust a download filename or retain an export containing secrets."""
    try:
        raw = Path(download.path()).read_text(encoding='utf-8')
        if private_text(raw, secrets):
            raise RecorderFailure('export contains private text; download discarded')
        destination.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(destination)
    finally:
        download.delete()


def fetch_report(base: str, token: str, out: Path, limit: int = 5000) -> dict:
    """The output report the submission must carry beside the video."""
    req = urllib.request.Request(
        # Every government read, not the latest per mark and never another
        # domain's: this CSV is delivered as the government-feed output report.
        f"{base}/reports/anpr.csv?reads=all&domain=GOVERNMENT&limit={limit}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "why": f"HTTP {exc.code}"}
    except Exception as exc:                            # pragma: no cover
        return {"ok": False, "why": type(exc).__name__}
    reader = csv.DictReader(io.StringIO(body))
    required = {'plate', 'timestamp_utc', 'camera_id'}
    if not required <= set(reader.fieldnames or []):
        return {'ok': False, 'why': 'ANPR CSV columns missing'}
    rows = list(reader)
    if not rows or any(not all(r.get(k) for k in required) for r in rows):
        return {'ok': False, 'why': 'ANPR CSV has no complete observations'}
    if private_text(body, (token,)):
        return {'ok': False, 'why': 'ANPR CSV contains private text'}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    plates = {r.get("plate") for r in rows if r.get("plate")}
    cams = {r.get("camera_id") for r in rows if r.get("camera_id")}
    return {"ok": True, "rows": len(rows), "plates": len(plates),
            "cameras": len(cams)}


def narrate(beats: list[Beat], work: Path, voice: str) -> float:
    """Synthesise every line first; its length sets the beat's dwell."""
    import narration

    if not narration.available():
        raise SystemExit("narration needs macOS `say`, ffmpeg and ffprobe")
    projected = 0.0
    for i, b in enumerate(beats):
        if b.say:
            b.audio = work / f"line_{i:02d}.wav"
            b.say_s = narration.synth(b.say, b.audio, voice=voice)
        projected += max(b.dwell_s, b.say_s + 0.6)
    return projected


def _finish_narrated(beats: list[Beat], silent: Path, out: Path, work: Path,
                     offset_s: float) -> None:
    import narration

    total = narration.probe_duration(silent)
    lines, chapters = [], []
    for i, b in enumerate(beats):
        start = max(0.0, b.at - offset_s)
        if b.audio:
            lines.append(narration.Line(start, b.say, b.audio, b.say_s))
        nxt = (beats[i + 1].at - offset_s) if i + 1 < len(beats) else total
        chapters.append((start, min(start + 3.2, nxt), b.title))
    track = narration.build_track(lines, total, work / "narration.wav")
    ass = narration.write_ass(lines, work / "captions.ass",
                              width=VIEW_W, height=VIEW_H, chapter=chapters)
    narration.finish(silent, track, ass, out)



def beats_report(beats: list[Beat]) -> list[dict]:
    return [{"title": b.title, "passed": b.ok, "skipped": b.skipped,
             "error": b.err, "at_s": b.at, "prepare_s": b.prepare_s,
             "recorded_s": b.recorded_s, "dwell_s": b.dwell_s,
             "samples": b.samples, "selectors": b.selectors, "sources": b.sources} for b in beats]


def show_caption(page, title: str) -> None:
    """Measured chapter captions also appear when narration is disabled."""
    page.evaluate("""title => {
      let caption = document.getElementById('gov-recording-caption');
      if (!caption) {
        caption = document.createElement('div'); caption.id = 'gov-recording-caption';
        caption.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);'
          + 'z-index:2147483647;background:#10273dee;color:white;padding:12px 24px;'
          + 'font:26px sans-serif;max-width:90vw;text-align:center;pointer-events:none';
        document.body.append(caption);
      }
      caption.textContent = title;
    }""", title)


def record(base: str, token: str, plate: str, out_dir: Path,
           admin_token: str = "", voice: str | None = "Aman", *, min_live: int = 12,
           preflight_timeout: float = 300, preflight_only: bool = False,
           gallery: Path | None = None, opening_layout: str = "dense",
           tour: str = 'standard', wall_domain: str = 'government') -> list[Beat]:
    from urllib.parse import urlsplit

    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(out_dir / 'beats.json', [])
    if not preflight_only and not admin_token:
        raise SystemExit('need --admin-token-file to demonstrate the RBAC handoff')
    with sync_playwright() as p:
        browser = None
        try:
            try:
                browser = p.chromium.launch(channel='chrome', headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': VIEW_W, 'height': VIEW_H})
            ctx.add_init_script('(' + INSTRUMENT + ')();')
            parsed = urlsplit(base)
            origin = f'{parsed.scheme}://{parsed.netloc}'
            # Seed once. Subsequent administrator/officer handoffs survive reload.
            ctx.add_init_script('if (location.origin === ' + json.dumps(origin) +
                                ' && !sessionStorage.getItem("gov.recorder.gate")'
                                ' && !sessionStorage.getItem("saakshya.token")) '
                                'sessionStorage.setItem("saakshya.token", ' + json.dumps(token) + ');')
            page = ctx.new_page()
            page.set_default_timeout(30000)
            ready = preflight(page, base, token, out_dir, min_live, preflight_timeout,
                              layout=opening_layout, wall_domain=wall_domain)
            if not ready['passed']:
                latest = ready.get('latest', {})
                failed = [k for k, v in ready['gates'].items() if not v['passed']]
                raise SystemExit(f"preflight failed: {latest.get('live', 0)} advancing, "
                                 f"{latest.get('connected', 0)} connected; gates: {', '.join(failed)}")
            if preflight_only:
                return []
            csv_path = Path(str(out_dir) + '_anpr_report.csv')
            report = fetch_report(base, token, csv_path)
            save_json(out_dir / 'report.json', report)
            if not report['ok']:
                raise SystemExit('ANPR report NOT WRITTEN; submission needs the report beside the video')
            government = ready['government_ids']
            media_ids = ready.get('wall_ids', government)
            dates = ready.get('replay_dates', {})
            builder = build_full if tour == 'full' else build
            options = {}
            if tour == 'full':
                status, me = api_read(base, token, '/me')
                officer_id = me.get('principal', {}).get('user_id', '')
                if status != 200 or not officer_id or private_text(officer_id):
                    raise RecorderFailure('officer user_id is unavailable or contains private text')
                options = {'wall_domain': wall_domain, 'replay_dates': dates, 'officer_id': officer_id}
            beats = builder(page, plate, admin_token, token, base=base,
                            government=government, gallery=gallery, csv_path=csv_path,
                            opening_layout=opening_layout, wall_cameras=media_ids, **options)
            work = out_dir / 'narration'
            work.mkdir(parents=True, exist_ok=True)
            if voice:
                narrate(beats, work, voice)
            save_json(out_dir / 'plan.json', {
                'label': 'DESIGNED', 'tour': tour, 'wall_domain': wall_domain,
                'dwell_s': beat_plan_duration(beats),
                'beats': [{'title': b.title, 'dwell_s': b.dwell_s,
                           'narration_s': b.say_s, 'optional': b.optional,
                           'selectors': b.selectors, 'sources': b.sources} for b in beats]})
            # Narration/report preparation may take time: gate the opening again.
            # One sample was too brittle on a shared sandbox (take 6: 4 live
            # against 5, a minute after preflight measured 6), so re-sample for
            # a bounded time; the gate itself is unchanged and nothing is
            # filmed until it passes.
            deadline = time.monotonic() + OPENING_WAIT_S
            tries = []
            while True:
                opening = sample_video(page, wall_ids(page, media_ids), min_live)
                ui = page.evaluate(UI_SAMPLE)
                ready = opening_ready(opening, ui, min_live, wall_domain)
                tries.append({'live': opening['live'], 'visible_live': opening['visible_live'],
                              'connected': opening['connected'], 'ready': ready})
                if ready or time.monotonic() >= deadline:
                    break
            save_json(out_dir / 'opening.json',
                      {'passed': ready, 'sample': opening, 'ui': ui, 'tries': tries})
            if not ready:
                raise SystemExit('opening readiness changed after preflight; no recording started')
            caption = lambda sample: playback_caption(sample, wall_domain, media_ids, dates)
            if tour == 'full':
                beats[0].action()  # Gate must be the very first captured frame.
                show_caption(page, beats[0].title)
            else:
                show_caption(page, caption(opening))
            mp4 = Path(str(out_dir) + '.mp4')
            silent = Path(str(out_dir) + '_silent.mp4') if voice else mp4
            filmed = []
            with Screencast(page, out_dir / 'frames', width=VIEW_W, height=VIEW_H, quality=98) as cast:
                t0 = cast.timeline_time()
                for i, beat in enumerate(beats):
                    # No loading screen or role-token reload can enter the film.
                    cast.pause()
                    started = time.monotonic()
                    capture_started = False
                    try:
                        detail = None if tour == 'full' and i == 0 else beat.action()
                        if detail:
                            beat.samples.append({'preparation': detail})
                        if beat.wall:
                            threshold = min_live if not any(b.wall and b.ok for b in beats[:i]) else 1
                            sample = wait_wall_motion(page, media_ids, threshold, beat.samples)
                            beat.title = caption(sample)
                        if beat.wall:
                            wait_view(page, 'live', '#live-grid .live-tile')
                        if wall_domain == 'replay' and beat.visible_motion:
                            beat.title = ('RECORDED GOVERNMENT FOOTAGE · captured '
                                          + dates[detail['camera']] + ' · replayed · intelligence panel')
                        if tour == 'full' and not beat.gate and not page.url.startswith('file:'):
                            page.wait_for_function("() => { const s = (" + UI_SAMPLE + ")(); "
                                                   "return s.shell && !s.loading && !s.loadingText; }")
                        if tour == 'full':
                            text_on_screen = page.locator('body').inner_text()
                            if private_text(text_on_screen, (token, admin_token)):
                                raise RecorderFailure('private text is present; capture remains paused')
                        show_caption(page, beat.title)
                        beat.prepare_s = round(time.monotonic() - started, 3)
                        cast.resume()
                        capture_started = True
                        beat.at = cast.timeline_time() - t0
                        print(f'  {beat.at:.1f}s  {beat.title}', flush=True)
                        hold = max(beat.dwell_s, beat.say_s + 0.6)
                        if beat.motion:
                            beat.motion()
                            # The app may need to attach newly visible tiles after
                            # the filmed scroll. Exclude that wait from the hold.
                            cast.pause()
                            ready_at = time.monotonic()
                            sample = wait_wall_motion(page, media_ids, threshold, beat.samples)
                            beat.prepare_s += round(time.monotonic() - ready_at, 3)
                            show_caption(page, caption(sample))
                            cast.resume()
                        until = time.monotonic() + hold
                        beat.ok = True
                        held: list[bool] = []
                        switches = 0
                        while time.monotonic() < until:
                            if beat.wall and time.monotonic() + 1.1 < until:
                                sample = sample_video(page, wall_ids(page, media_ids), threshold)
                                sample['at_s'] = cast.timeline_time() - t0
                                beat.samples.append(sample)
                                show_caption(page, caption(sample))
                                held.append(bool(sample['passed'] and sample['visible_live']))
                                if hold_stalled(held):
                                    raise RecorderFailure('wall motion fell below threshold during hold')
                            elif beat.visible_motion and time.monotonic() + 1.1 < until:
                                sample = sample_video(page, [detail['camera']], 1, focus=True)
                                beat.samples.append(sample)
                                held.append(bool(sample['passed'] and sample['visible_live']))
                                if hold_stalled(held):
                                    if not beat.retry or switches >= FOCUS_SWITCHES:
                                        raise RecorderFailure('focused government video stopped advancing')
                                    # Off camera: select the next camera measured
                                    # advancing, then give the beat its time back.
                                    cast.pause()
                                    paused_at = time.monotonic()
                                    stalled = detail['camera']
                                    detail = beat.retry()
                                    if wall_domain == 'replay':
                                        beat.title = ('RECORDED GOVERNMENT FOOTAGE · captured '
                                                      + dates[detail['camera']] + ' · replayed · intelligence panel')
                                        show_caption(page, beat.title)
                                    switches += 1
                                    held.clear()
                                    beat.samples.append({'switched': {'from': stalled,
                                                                      'to': detail['camera']}})
                                    until += time.monotonic() - paused_at
                                    cast.resume()
                            ui = page.evaluate(UI_SAMPLE) if not beat.gate and not page.url.startswith('file:') else None
                            if ui and (ui['loading'] or ui['loadingText']):
                                raise RecorderFailure('loading appeared during hold')
                            if ui and ui['fatal'] and 'administrator search refused' not in beat.title:
                                raise RecorderFailure('error appeared during hold')
                            page.wait_for_timeout(min(1000, max(0, until - time.monotonic()) * 1000))
                        beat.recorded_s = round(cast.timeline_time() - t0 - beat.at, 3)
                        filmed.append(beat)
                    except SkipBeat as exc:
                        beat.skipped, beat.err = beat.optional, str(exc)
                        print(f'  skipped: {beat.title}: {beat.err}', flush=True)
                        if not beat.optional:
                            break
                    except Exception as exc:
                        # Exception text can include auth headers or server replies.
                        beat.ok, beat.err = False, str(exc) if isinstance(exc, RecorderFailure) else type(exc).__name__
                        print(f'  failed: {beat.title}: {beat.err}', flush=True)
                        if capture_started:
                            beat.recorded_s = round(cast.timeline_time() - t0 - beat.at, 3)
                            filmed.append(beat)
                        break  # Unexpected failures must never become a usable take.
                    finally:
                        cast.pause()
                        beat.prepare_s = beat.prepare_s or round(time.monotonic() - started, 3)
                        save_json(out_dir / 'beats.json', beats_report(beats))
                first = cast.first_timestamp()
                offset = max(0.0, (first - t0) if first else 0.0)
            res = cast.write(silent, crf=15, fps=30)
            save_json(out_dir / 'capture.json', res)
            if not res.get('ok'):
                raise SystemExit('capture failed; frames retained for diagnosis')
            cast.cleanup()
            if voice:
                _finish_narrated(filmed, silent, mp4, work, offset)
            return beats
        except Exception as exc:
            if not (out_dir / 'preflight.json').exists():
                save_json(out_dir / 'preflight.json', {'passed': False, 'error': type(exc).__name__,
                          'gates': {g: {'passed': False, 'measured': None} for g in GATES}})
            raise SystemExit(f'recorder failed: {type(exc).__name__}') from None
        finally:
            if browser:
                browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', default='http://127.0.0.1:8083')
    ap.add_argument('--token-file', required=True)
    ap.add_argument('--admin-token-file')
    ap.add_argument('--plate', default='GJ11S7924')
    ap.add_argument('--out', default='var/demo/government_feed')
    ap.add_argument('--min-live', type=int, default=12)
    ap.add_argument('--preflight-timeout', type=float, default=300)
    ap.add_argument('--preflight-only', action='store_true')
    ap.add_argument('--tour', choices=('standard', 'full'), default='standard')
    ap.add_argument('--wall-domain', choices=('government', 'replay'), default='government',
                    help='replay requires the REPLAY lane UI and dated government-linked ARCHIVAL_REPLAY GIS rows')
    ap.add_argument('--opening-layout', choices=sorted(OPENING_POLICY), default='dense',
                    help='wall layout the preflight measures and the film opens on')
    ap.add_argument('--gallery', type=Path, default=ROOT / 'var/demo/plate_gallery/gallery.html')
    ap.add_argument('--voice', default='Aman', help="macOS voice; 'none' records silently")
    a = ap.parse_args()
    if a.wall_domain == 'replay' and a.tour != 'full':
        ap.error('--wall-domain replay requires --tour full')
    if not re.fullmatch(r'[A-Za-z0-9]+', a.plate):
        ap.error('--plate must contain only letters and digits')
    if not 1 <= a.min_live <= 30 or a.preflight_timeout <= 0:
        ap.error('--min-live must be in 1..30 and --preflight-timeout must be positive')
    if a.opening_layout == 'grid' and a.min_live > GRID_SESSION_BUDGET:
        ap.error(f'--min-live cannot exceed {GRID_SESSION_BUDGET} with --opening-layout grid: '
                 'the optimized view never streams more tiles at once')
    if not a.preflight_only and not a.admin_token_file:
        ap.error('--admin-token-file is required for the registry and RBAC beats')
    token = Path(a.token_file).read_text(encoding='ascii').strip()
    admin = Path(a.admin_token_file).read_text(encoding='ascii').strip() if a.admin_token_file else ''
    if not token or (a.admin_token_file and not admin):
        ap.error('token file is empty')
    out_dir = Path(a.out)
    beats = record(a.base, token, a.plate, out_dir, admin_token=admin,
                   voice=None if a.voice.lower() == 'none' else a.voice,
                   min_live=a.min_live, preflight_timeout=a.preflight_timeout,
                   preflight_only=a.preflight_only, gallery=a.gallery,
                   opening_layout=a.opening_layout, tour=a.tour, wall_domain=a.wall_domain)
    if a.preflight_only:
        print(f'preflight passed: {out_dir / "preflight.json"}')
        return
    # Refresh the deliverable from the same store after the recording as well.
    report = fetch_report(a.base, token, Path(str(out_dir) + '_anpr_report.csv'))
    save_json(out_dir / 'report.json', report)
    if not report.get('ok'):
        raise SystemExit('ANPR report NOT WRITTEN; submission needs the report beside the video')
    failed = [b for b in beats if not b.ok and not b.skipped]
    print(f'video: {out_dir}.mp4; beat measurements: {out_dir / "beats.json"}')
    if failed:
        raise SystemExit('recording incomplete: inspect beats.json before submission')


if __name__ == '__main__':
    main()
