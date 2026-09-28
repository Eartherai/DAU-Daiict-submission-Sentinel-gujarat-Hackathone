"""Record government footage only after measured readiness gates pass.

Live command (run by the primary after merging; never run during offline work):
    PYTHONPATH="$PWD/src" "/Users/earther/Desktop/Gujarat CCTV/saakshya/.venv/bin/python" \
        tools/demo/record_government_feed.py \
        --base http://127.0.0.1:8083 --token-file /path/to/officer.token \
        --admin-token-file /path/to/admin.token --min-live 12 \
        --preflight-timeout 300 --plate GJ11S7924 --out var/demo/government_feed
Add --preflight-only to write preflight.json without starting capture.

One context and page; only the application's own media sessions. Transition
waits are cut out of capture, with their durations retained in beats.json.
Counts are measurements during this recording, never upstream session limits.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
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
    ok: bool = False
    err: str = ""
    at: float = 0.0
    say_s: float = 0.0
    audio: Path | None = None
    skipped: bool = False
    prepare_s: float = 0.0
    recorded_s: float = 0.0
    samples: list = field(default_factory=list)


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


def live_caption(live: int, total: int = 30) -> str:
    if not 0 <= live <= total:
        raise ValueError("live count must be within the measured wall size")
    return f"{live} of {total} government cameras live in this recording"


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
              layout: str = "dense") -> dict:
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
        gate("DB_READY", status == 200 and not body.get("clustered")
             and counts["GOVERNMENT"] >= 30,
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
        page.click('[data-live-domain="government"]', timeout=remaining_ms())
        policy = OPENING_POLICY[layout]
        page.click(f'[data-live-layout="{layout}"]', timeout=remaining_ms())
        page.wait_for_selector(f'#media-policy[data-policy="{policy}"]', timeout=remaining_ms())
        page.wait_for_selector(f'#live[data-wall="30"][data-layout="{layout}"] .live-tile',
                               timeout=remaining_ms())
        warmed = False
        while time.monotonic() + 1.1 < deadline:
            ids = wall_ids(page, government)
            sample = sample_video(page, ids, min_live)
            result["samples"].append(sample)
            result["latest"] = sample
            ui = page.evaluate(UI_SAMPLE)
            gate("UI_READY", ui["shell"] and not ui["loading"] and not ui["loadingText"], ui)
            gate("NO_FATAL_TOAST", ui["fatal"] == 0, {"visible_errors": ui["fatal"]})
            gate("WHEP_READY", len(ids) == 30 and sample["connected"] >= min_live,
                 {"connected": sample["connected"], "tiles": len(ids), "policy": policy})
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
          opening_layout: str = "dense") -> list[Beat]:
    government = government or []
    selected = {"camera": None}
    gallery = gallery or ROOT / "var/demo/plate_gallery/gallery.html"

    def use_token(token, role, view, content):
        if not token:
            raise RecorderFailure("role token missing")
        page.evaluate("t => sessionStorage.setItem('saakshya.token', t)", token)
        # A different query forces exactly one document navigation (a hash-only
        # navigation would leave the previous principal in app state).
        page.goto(base.rstrip('/') + '/ui/?recorder-role=' + role + '#' + view,
                  wait_until='domcontentloaded')
        wait_view(page, view, content)

    def wall_group(fraction):
        def go():
            # Grid makes deliberate top/middle/bottom views possible when Dense fits.
            wall_mode(page, "grid")
            wait_view(page, "live", "#live-grid .live-tile")
        return go

    def focus():
        latest = sample_video(page, wall_ids(page, government), 1)
        ids = latest["live_ids"]
        if not ids:
            raise RecorderFailure("no advancing government camera for focus")
        cid = "cam06" if "cam06" in ids else ids[0]
        selected["camera"] = cid
        # Command chrome hides the filmstrip even in Focus; expose it first.
        if page.locator('#btn-command-bar').get_attribute('aria-pressed') != 'true':
            page.click('#btn-command-bar')
        # Layout changes preserve tile decoders; selecting uses the app's shared PC.
        wall_mode(page, "focus")
        page.locator(f'#live-strip .live-tile[data-camera="{cid}"]').click()
        page.wait_for_selector('#live-stage video', timeout=30000)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            measured = sample_video(page, [cid], 1, focus=True)
            if measured["passed"] and measured['visible_live']:
                wait_view(page, "live", "#live-sidecar")
                return {"camera": cid, "video": measured}
        raise RecorderFailure("selected video stopped advancing")

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
        page.goto(base.rstrip('/') + '/ui/#evidence', wait_until='domcontentloaded')
        wait_view(page, 'evidence', '#evidence-chain table', timeout=120000)

    def onboarded():
        use_token(admin_token, 'administrator', 'cameras', '#cameras table tbody tr')

    def system_status():
        navigate(page, 'system', '#system .command-grid .health-row')
        page.locator('#system .command-grid .health-row').first.scroll_into_view_if_needed()

    def bulk():
        page.click('#btn-onboard-toggle')
        page.click('[data-onboard="bulk"]')
        text = (ROOT / 'reports/sample_camera_metadata.csv').read_text(encoding='utf-8')
        page.fill('#ob-csv', '\n'.join(text.splitlines()[:8]))
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
        with page.expect_response(lambda r: '/search?' in r.url) as pending:
            page.press('#q-plate', 'Enter')
        if pending.value.status != 403:
            raise RecorderFailure('expected administrator refusal not observed')
        wait_view(page, 'investigate', '#results .notice.bad', allow_error=True)

    search_beat = Beat('Designated plate — sightings with timestamps and camera', 30, search,
                       'The officer searches under a case and stated purpose. Each returned observation names its camera and timestamp.')
    return [
        *opening_beats(page, opening_layout, wall_group),
        Beat('One advancing government camera, with its intelligence panel', 28, focus,
             'A camera with measured advancing frames, beside its intelligence panel. The panel states the available observations.', visible_motion=True),
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
def fetch_report(base: str, token: str, out: Path, limit: int = 1000) -> dict:
    """The output report the submission must carry beside the video."""
    req = urllib.request.Request(
        f"{base}/reports/anpr.csv?limit={limit}",
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
             "samples": b.samples} for b in beats]


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
           gallery: Path | None = None, opening_layout: str = "dense") -> list[Beat]:
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
                                ' && !sessionStorage.getItem("saakshya.token")) '
                                'sessionStorage.setItem("saakshya.token", ' + json.dumps(token) + ');')
            page = ctx.new_page()
            page.set_default_timeout(30000)
            ready = preflight(page, base, token, out_dir, min_live, preflight_timeout,
                              layout=opening_layout)
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
            beats = build(page, plate, admin_token, token, base=base,
                          government=government, gallery=gallery, csv_path=csv_path,
                          opening_layout=opening_layout)
            work = out_dir / 'narration'
            work.mkdir(parents=True, exist_ok=True)
            if voice:
                narrate(beats, work, voice)
            save_json(out_dir / 'plan.json', {
                'label': 'DESIGNED', 'dwell_s': beat_plan_duration(beats),
                'beats': [{'title': b.title, 'dwell_s': b.dwell_s,
                           'narration_s': b.say_s, 'optional': b.optional} for b in beats]})
            # Narration/report preparation may take time: gate the opening again.
            opening = sample_video(page, wall_ids(page, government), min_live)
            ui = page.evaluate(UI_SAMPLE)
            if (not opening['passed'] or not opening['visible_live']
                    or opening['connected'] < min_live or not ui['shell']
                    or ui['fatal'] or ui['loading'] or ui['loadingText']):
                save_json(out_dir / 'opening.json', {'passed': False, 'sample': opening, 'ui': ui})
                raise SystemExit('opening readiness changed after preflight; no recording started')
            save_json(out_dir / 'opening.json', {'passed': True, 'sample': opening, 'ui': ui})
            show_caption(page, live_caption(opening['live']))
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
                        detail = beat.action()
                        if detail:
                            beat.samples.append({'preparation': detail})
                        if beat.wall:
                            threshold = min_live if i == 0 else 1
                            sample = wait_wall_motion(page, government, threshold, beat.samples)
                            beat.title = live_caption(sample['live'])
                        if beat.wall:
                            wait_view(page, 'live', '#live-grid .live-tile')
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
                            sample = wait_wall_motion(page, government, threshold, beat.samples)
                            beat.prepare_s += round(time.monotonic() - ready_at, 3)
                            show_caption(page, live_caption(sample['live']))
                            cast.resume()
                        until = time.monotonic() + hold
                        beat.ok = True
                        while time.monotonic() < until:
                            if beat.wall and time.monotonic() + 1.1 < until:
                                sample = sample_video(page, wall_ids(page, government), threshold)
                                sample['at_s'] = cast.timeline_time() - t0
                                beat.samples.append(sample)
                                show_caption(page, live_caption(sample['live']))
                                if not sample['passed'] or not sample['visible_live']:
                                    raise RecorderFailure('wall motion fell below threshold during hold')
                            elif beat.visible_motion and time.monotonic() + 1.1 < until:
                                sample = sample_video(page, [detail['camera']], 1, focus=True)
                                beat.samples.append(sample)
                                if not sample['passed'] or not sample['visible_live']:
                                    raise RecorderFailure('focused government video stopped advancing')
                            ui = page.evaluate(UI_SAMPLE) if not page.url.startswith('file:') else None
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
    ap.add_argument('--opening-layout', choices=sorted(OPENING_POLICY), default='dense',
                    help='wall layout the preflight measures and the film opens on')
    ap.add_argument('--gallery', type=Path, default=ROOT / 'var/demo/plate_gallery/gallery.html')
    ap.add_argument('--voice', default='Aman', help="macOS voice; 'none' records silently")
    a = ap.parse_args()
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
                   opening_layout=a.opening_layout)
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
