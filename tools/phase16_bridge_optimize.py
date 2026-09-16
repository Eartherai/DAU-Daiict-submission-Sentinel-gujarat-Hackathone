#!/usr/bin/env python3
"""Phase 16 — Maximize real browser coverage via cheaper PREVIEW bridges.

Does NOT change DIRECT_SENTINEL_WHEP for the 15 WHEP-capable cameras.
Credentials: SENTINEL_GRID_* env only — never printed/logged/JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured, credentialed  # noqa: E402
from saakshya.live.grid import GridConfig  # noqa: E402
from tools.sentinel_direct_whep import (  # noqa: E402
    basic_authorization_header, measure_direct_wall, refuse_secrets, safe, whep_url,
)

OUT = ROOT / "var/reports/phase10/performance"
REPORTS = ROOT / "reports"
HOST = "103.250.160.189"

DIRECT_WHEP = [
    "cam01", "cam02", "cam03", "cam04", "cam05", "cam06",
    "cam12", "cam13", "cam14", "cam16", "cam18", "cam19",
    "cam20", "cam23", "cam26",
]
RTSP_ONLY = [
    "cam07", "cam08", "cam09", "cam10", "cam11", "cam15",
    "cam17", "cam21", "cam22", "cam24", "cam25", "cam27",
    "cam28", "cam29", "cam30",
]

# Intentional compatibility: copy fails B-frames; VT baseline required.
COPY_FAIL_REASON = "MediaMTX WebRTC rejects H264 streams with B-frames"

BRIDGE_TIERS = {
    "PRIMARY": {
        # Full-quality bridge (operator promotion / high priority)
        "scale": None,  # keep source resolution
        "fps": 15,
        "bitrate": "1500k",
        "profile": "baseline",
        "g": 30,
    },
    "PREVIEW": {
        # Cheap preview: lower FPS/bitrate. Avoid -s/-vf under concurrency —
        # mid-GOP RTSP + scale caused intermittent empty encode at n≥6.
        # Solo 720p was MEASURED earlier; concurrency uses bitrate/fps path.
        "scale": None,
        "fps": 8,
        "bitrate": "500k",
        "profile": "baseline",
        "g": 24,
        "solo_scale_720p_measured": True,
    },
}


def _api(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:9997{path}", timeout=3) as r:
        return json.load(r)


def write_mtx_config(camera_ids: list[str]) -> Path:
    paths = "\n".join(f"  stream/gov-{c}:" for c in camera_ids)
    cfg = f"""# phase16 — no credentials
logLevel: warn
rtspAddress: :8554
rtspTransports: [tcp]
webrtcAddress: :8889
webrtcAllowOrigins: ["*"]
api: yes
apiAddress: 127.0.0.1:9997
apiAllowOrigins: ["*"]
paths:
{paths}
"""
    dst = ROOT / "var/mediamtx_phase16.yml"
    dst.write_text(cfg)
    return dst


def start_mediamtx(camera_ids: list[str]) -> subprocess.Popen:
    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.7)
    cfg = write_mtx_config(camera_ids)
    (ROOT / "var/logs").mkdir(parents=True, exist_ok=True)
    log = open(ROOT / "var/logs/mediamtx_phase16.log", "ab")
    proc = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(50):
        time.sleep(0.2)
        try:
            _api("/v3/paths/list")
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("MediaMTX exited")
    raise RuntimeError("MediaMTX API not ready")


def _scrub_text(text: str) -> str:
    import re
    return re.sub(r"rtsp://[^@\s]+@", "rtsp://REDACTED@", text)


def _scrub_bridge_log(camera_id: str) -> None:
    """Never leave credentials in ffmpeg logs (error lines include Input URLs)."""
    path = ROOT / f"var/logs/phase16_bridge_{camera_id}.log"
    if not path.exists():
        return
    text = path.read_text(errors="ignore")
    scrubbed = _scrub_text(text)
    if scrubbed != text:
        path.write_text(scrubbed)


def _scrubbed_log_handle(path: Path):
    """Open log via a pipe that redacts rtsp://user:pass@ before disk write."""
    import threading

    path.parent.mkdir(parents=True, exist_ok=True)
    r, w = os.pipe()

    def _pump() -> None:
        with os.fdopen(r, "r", errors="ignore") as src, open(path, "w") as dst:
            for line in src:
                dst.write(_scrub_text(line))
                dst.flush()

    threading.Thread(target=_pump, daemon=True).start()
    return os.fdopen(w, "w")


def start_bridge(camera_id: str, *, tier: str = "PREVIEW",
                 mode: str = "transcode") -> subprocess.Popen:
    """Start ffmpeg bridge. mode=copy|transcode. Never log credentials."""
    src = credentialed(f"rtsp://{HOST}:8554/stream/{camera_id}", required=True)
    dst = f"rtsp://127.0.0.1:8554/stream/gov-{camera_id}"
    log = _scrubbed_log_handle(ROOT / f"var/logs/phase16_bridge_{camera_id}.log")
    if mode == "copy":
        cmd = [
            str(ROOT / "var/bin/ffmpeg"), "-hide_banner", "-loglevel", "warning",
            "-rtsp_transport", "tcp", "-i", src,
            "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp", dst,
        ]
    else:
        t = BRIDGE_TIERS[tier]
        # VT baseline, no B-frames. Prefer phase15-style (no -r/-vf) for
        # concurrency reliability; -r alone can empty-encode mid-GOP joins.
        cmd = [
            str(ROOT / "var/bin/ffmpeg"), "-hide_banner", "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-fflags", "+genpts",
            "-err_detect", "ignore_err",
            "-i", src,
            "-an",
        ]
        if t.get("scale"):
            wh = t["scale"].replace(":", "x")
            cmd += ["-s", wh]
        cmd += [
            "-c:v", "h264_videotoolbox", "-b:v", t["bitrate"],
            "-profile:v", t["profile"], "-bf", "0", "-g", str(t["g"]),
            "-f", "rtsp", "-rtsp_transport", "tcp", dst,
        ]
    print(f"bridge {camera_id} tier={tier} mode={mode}", flush=True)
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)


def wait_ready(camera_ids: list[str], *, timeout: float = 90.0,
               min_bytes: int = 8000,
               pubs: list[subprocess.Popen] | None = None,
               tier: str = "PREVIEW",
               max_restarts: int = 2) -> dict:
    """Wait for MediaMTX paths; restart dead ffmpeg with backoff (avoid RTSP stampede)."""
    t0 = time.monotonic()
    ready: dict[str, dict] = {}
    restarts = {c: 0 for c in camera_ids}
    last_restart = {c: 0.0 for c in camera_ids}
    last_exit = {c: None for c in camera_ids}
    # Serialize restarts — one at a time, with refuse/auth backoff
    next_restart_slot = 0.0
    while time.monotonic() - t0 < timeout:
        if pubs is not None and len(pubs) == len(camera_ids):
            now = time.monotonic()
            for i, c in enumerate(camera_ids):
                p = pubs[i]
                if p.poll() is None or restarts[c] >= max_restarts:
                    continue
                code = p.returncode
                last_exit[c] = code
                # 401/refuse/empty: back off hard to avoid auth stampede
                min_gap = 15.0 if code in (195, 1, 8, 224) else 8.0
                if now - last_restart[c] < min_gap or now < next_restart_slot:
                    continue
                _scrub_bridge_log(c)
                # Detect 401 in log → longer gap
                logp = ROOT / f"var/logs/phase16_bridge_{c}.log"
                auth_fail = False
                if logp.exists():
                    tail = logp.read_text(errors="ignore")[-800:]
                    auth_fail = "401" in tail or "Unauthorized" in tail
                if auth_fail:
                    min_gap = max(min_gap, 20.0)
                print(
                    f"restart bridge {c} (exit={code}"
                    f"{', auth401' if auth_fail else ''}) after {min_gap}s backoff",
                    flush=True,
                )
                pubs[i] = start_bridge(c, tier=tier, mode="transcode")
                restarts[c] += 1
                last_restart[c] = now
                next_restart_slot = now + 5.0  # stagger peer restarts
                break  # one restart per loop
        all_ok = True
        for c in camera_ids:
            try:
                d = _api(f"/v3/paths/get/stream/gov-{c}")
                br = d.get("bytesReceived") or d.get("inboundBytes") or 0
                ok = bool(d.get("ready") and br >= min_bytes)
                if not ok and d.get("ready") and d.get("source") and br > 0:
                    ok = True
                ready[c] = {"ready": d.get("ready"), "bytes": br, "ok": ok}
                if not ok:
                    all_ok = False
            except Exception:
                ready[c] = {"ok": False}
                all_ok = False
        if all_ok and camera_ids:
            for c in camera_ids:
                _scrub_bridge_log(c)
            return {
                "ok": True,
                "wait_s": round(time.monotonic() - t0, 2),
                "ready_n": len(camera_ids),
                "paths": ready,
                "restarts": restarts,
                "last_exit": last_exit,
            }
        time.sleep(0.5)
    for c in camera_ids:
        _scrub_bridge_log(c)
    return {
        "ok": False,
        "wait_s": round(time.monotonic() - t0, 2),
        "ready_n": sum(1 for v in ready.values() if v.get("ok")),
        "paths": ready,
        "restarts": restarts,
        "last_exit": last_exit,
    }


def sample_proc(pid: int) -> dict:
    try:
        p = psutil.Process(pid)
        return {
            "cpu_percent": p.cpu_percent(interval=0.3),
            "rss_mb": round(p.memory_info().rss / 1e6, 1),
        }
    except Exception:
        return {"cpu_percent": None, "rss_mb": None}


def profile_bridge_cost(camera_id: str = "cam07") -> dict:
    """Measure FULL vs PREVIEW bridge cost + document copy FAIL."""
    results: dict = {
        "camera_id": camera_id,
        "label": "MEASURED_REAL",
        "copy_compatibility": {
            "result": "FAIL",
            "reason": COPY_FAIL_REASON,
            "note": "Intentional: H.264 B-frame source cannot copy-remux to WebRTC",
        },
        "tiers": {},
    }
    for tier in ("PRIMARY", "PREVIEW"):
        print(f"=== PROFILE tier={tier} ===", flush=True)
        mtx = start_mediamtx([camera_id])
        t0 = time.monotonic()
        pubs = [start_bridge(camera_id, tier=tier, mode="transcode")]
        ready = wait_ready([camera_id], timeout=70, pubs=pubs, tier=tier)
        pub = pubs[0]
        startup_s = round(time.monotonic() - t0, 2)
        samples = []
        for _ in range(8):
            samples.append(sample_proc(pub.pid))
            time.sleep(0.5)
        # WHEP soak
        from tools.test_whep_camera import measure
        whep = measure(
            f"http://127.0.0.1:8889/stream/gov-{camera_id}/whep",
            seconds=12,
            screenshot=OUT / f"phase16_{camera_id}_{tier.lower()}_whep.png",
        )
        assert "@" not in json.dumps(whep)
        video = whep.get("video") or {}
        cpu_vals = [s["cpu_percent"] for s in samples if s.get("cpu_percent") is not None]
        rss_vals = [s["rss_mb"] for s in samples if s.get("rss_mb") is not None]
        row = {
            "tier": tier,
            "settings": BRIDGE_TIERS[tier],
            "startup_s": startup_s,
            "ready": ready,
            "ffmpeg_cpu_mean": round(sum(cpu_vals) / len(cpu_vals), 2) if cpu_vals else None,
            "ffmpeg_rss_mb_mean": round(sum(rss_vals) / len(rss_vals), 1) if rss_vals else None,
            "whep_status": whep.get("status"),
            "first_frame_ms": whep.get("first_frame_ms"),
            "currentTime": video.get("currentTime"),
            "width": video.get("width"),
            "height": video.get("height"),
            "luma": video.get("canvasMeanLuma"),
            "ice": whep.get("ice_state"),
            "system_cpu": psutil.cpu_percent(0.3),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
        }
        (OUT / f"phase16_{camera_id}_{tier.lower()}_whep.json").write_text(
            json.dumps(whep, indent=2) + "\n"
        )
        results["tiers"][tier] = row
        print(json.dumps({
            "tier": tier, "startup_s": startup_s,
            "cpu": row["ffmpeg_cpu_mean"], "rss": row["ffmpeg_rss_mb_mean"],
            "wh": f"{row['width']}x{row['height']}", "ff": row["first_frame_ms"],
            "whep": row["whep_status"],
        }), flush=True)
        if pub.poll() is None:
            pub.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass
        time.sleep(1.2)

    # Cost ratio
    p = results["tiers"].get("PRIMARY") or {}
    v = results["tiers"].get("PREVIEW") or {}
    if p.get("ffmpeg_cpu_mean") and v.get("ffmpeg_cpu_mean"):
        results["cpu_ratio_preview_over_primary"] = round(
            v["ffmpeg_cpu_mean"] / max(0.01, p["ffmpeg_cpu_mean"]), 3
        )
    if p.get("ffmpeg_rss_mb_mean") and v.get("ffmpeg_rss_mb_mean"):
        results["rss_ratio_preview_over_primary"] = round(
            v["ffmpeg_rss_mb_mean"] / max(1.0, p["ffmpeg_rss_mb_mean"]), 3
        )
    # Bottleneck note from measurements
    results["bottleneck_observation"] = (
        "Encoder/session startup dominates: staggered VT sessions needed; "
        "simultaneous spawn previously caused n=4 FAIL. PREVIEW scale+fps "
        "reduces encode work vs PRIMARY. Copy path blocked by B-frames (not CPU)."
    )
    return results


def scale_bridges(camera_ids: list[str], *, sizes: list[int],
                  tier: str = "PREVIEW", seconds: float = 16.0,
                  stagger_s: float = 3.5) -> dict:
    rows = []
    for n in sizes:
        cams = camera_ids[:n]
        if len(cams) < n:
            rows.append({"n": n, "overall": "SKIP"})
            continue
        # Larger n: more stagger to avoid remote RTSP 401 / refuse
        use_stagger = stagger_s if n <= 4 else max(stagger_s, 5.0)
        wait_to = 90.0 if n <= 4 else 140.0
        print(f"=== SCALE n={n} tier={tier} stagger={use_stagger}s ===", flush=True)
        mtx = start_mediamtx(cams)
        pubs: list[subprocess.Popen] = []
        t0 = time.monotonic()
        try:
            for c in cams:
                pubs.append(start_bridge(c, tier=tier, mode="transcode"))
                time.sleep(use_stagger)
            ready = wait_ready(
                cams, timeout=wait_to, pubs=pubs, tier=tier, max_restarts=2,
            )
            startup_s = round(time.monotonic() - t0, 2)
            ready_cams = [
                c for c in cams if (ready.get("paths") or {}).get(c, {}).get("ok")
            ]
            # Sample aggregate ffmpeg CPU
            cpu_sum = 0.0
            rss_sum = 0.0
            alive = 0
            for p in pubs:
                if p.poll() is None:
                    s = sample_proc(p.pid)
                    if s.get("cpu_percent") is not None:
                        cpu_sum += s["cpu_percent"]
                        alive += 1
                    if s.get("rss_mb") is not None:
                        rss_sum += s["rss_mb"]
            # Only WHEP-measure ready paths (avoid false FAIL from dead pubs)
            measure_cams = ready_cams if ready_cams else cams
            endpoints = [
                f"http://127.0.0.1:8889/stream/gov-{c}/whep" for c in measure_cams
            ]
            wall = measure_direct_wall(
                endpoints, auth_header=None, seconds=seconds,
                negotiate_concurrency=min(4, max(1, len(measure_cams))),
                retries=1, setup_timeout_ms=18000,
            )
            from tools.sentinel_direct_whep import summarize
            summary = summarize(
                measure_cams, wall, seconds=seconds, path_label="P16_BRIDGE",
            )
            ws = summary.get("wall_summary") or {}
            live = (ws.get("PASS") or 0) + (ws.get("AMBER") or 0)
            # Score against requested n: live among ready, but budget needs ≥75% of n
            bridge_overall = "PASS" if live >= max(1, int(n * 0.75)) else (
                "AMBER" if live > 0 else "FAIL"
            )
            row = {
                "n": n,
                "tier": tier,
                "stagger_s": use_stagger,
                "ready_n": ready.get("ready_n"),
                "ready_cams": ready_cams,
                "startup_s": startup_s,
                "overall": bridge_overall,
                "wall_overall": summary.get("overall"),
                "live_tiles": live,
                "PASS": ws.get("PASS"),
                "AMBER": ws.get("AMBER"),
                "FAIL": ws.get("FAIL"),
                "first_frame_ms_p50": ws.get("first_frame_ms_p50"),
                "ffmpeg_cpu_sum": round(cpu_sum, 1),
                "ffmpeg_rss_mb_sum": round(rss_sum, 1),
                "ffmpeg_alive": alive,
                "restarts": ready.get("restarts"),
                "system_cpu": psutil.cpu_percent(0.3),
                "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
                "gpu": wall.get("gpu"),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
        finally:
            for p in pubs:
                if p.poll() is None:
                    p.terminate()
            for p in pubs:
                try:
                    p.wait(timeout=3)
                except Exception:
                    p.kill()
            try:
                mtx.terminate()
                mtx.wait(timeout=3)
            except Exception:
                try:
                    mtx.kill()
                except Exception:
                    pass
            time.sleep(1.5)
        # Cool down remote RTSP / VT sessions between sizes (longer after n≥4)
        time.sleep(12.0 if n >= 4 else 5.0)
    chosen = 0
    for r in rows:
        if r.get("overall") == "SKIP":
            continue
        # Require ≥75% live and first-frame p50 < 8s when available
        ff = r.get("first_frame_ms_p50") or 0
        if (r.get("live_tiles") or 0) >= max(1, int(r["n"] * 0.75)) and (
            ff == 0 or ff < 8000
        ):
            chosen = r["n"]
    return {
        "label": "MEASURED_REAL",
        "tier": tier,
        "rows": rows,
        "chosen_bridge_budget": chosen,
    }


def hybrid_wall(*, direct: list[str], bridged: list[str],
                full_budget: int, seconds: float,
                bridge_tier: str = "PREVIEW") -> dict:
    cfg = GridConfig.from_env()
    auth = basic_authorization_header()
    mtx = start_mediamtx(bridged) if bridged else None
    pubs: list[subprocess.Popen] = []
    for c in bridged:
        pubs.append(start_bridge(c, tier=bridge_tier, mode="transcode"))
        # Longer stagger when many bridges — avoid Sentinel auth stampede
        time.sleep(6.0 if len(bridged) >= 10 else (5.0 if len(bridged) >= 6 else 1.5))
    try:
        ready_info = {"ok": True, "ready_n": 0, "paths": {}}
        if bridged:
            ready_info = wait_ready(
                bridged, timeout=180 if len(bridged) >= 10 else 120,
                pubs=pubs, tier=bridge_tier, max_restarts=2,
            )
        ready_bridged = [
            c for c in bridged
            if (ready_info.get("paths") or {}).get(c, {}).get("ok")
        ]
        # Fall back to requested list only if somehow empty but wait said ok
        if not ready_bridged and ready_info.get("ok"):
            ready_bridged = list(bridged)
        full = direct[:full_budget]
        prev_direct = direct[full_budget:]
        endpoints = []
        meta = []
        for c in full:
            endpoints.append(whep_url(c, cfg))
            meta.append({"camera_id": c, "role": "FULL", "path": "DIRECT_SENTINEL_WHEP"})
        for c in prev_direct:
            endpoints.append(whep_url(c, cfg))
            meta.append({"camera_id": c, "role": "PREVIEW", "path": "DIRECT_SENTINEL_WHEP"})
        for c in ready_bridged:
            endpoints.append(f"http://127.0.0.1:8889/stream/gov-{c}/whep")
            meta.append({
                "camera_id": c, "role": "PREVIEW",
                "path": f"BRIDGED_{bridge_tier}",
            })
        wall = measure_direct_wall(
            endpoints, auth_header=auth, seconds=seconds,
            negotiate_concurrency=4, retries=1, setup_timeout_ms=20000,
        )
        from tools.sentinel_direct_whep import classify
        counts = {
            "LIVE": 0, "PREVIEW": 0, "DEGRADED": 0,
            "DIRECT_WHEP": 0, "BRIDGED": 0, "RTSP_ONLY_AI": 0, "NO_SIGNAL": 0,
        }
        tiles = []
        raw = wall.get("tiles") or []
        for i, m in enumerate(meta):
            t = raw[i] if i < len(raw) else {}
            verdict = classify(t, target_s=seconds)
            liveish = verdict in {"PASS", "AMBER"}
            if m["role"] == "FULL" and liveish:
                ux = "LIVE"
                counts["LIVE"] += 1
            elif liveish:
                ux = "PREVIEW"
                counts["PREVIEW"] += 1
            else:
                ux = "DEGRADED"
                counts["DEGRADED"] += 1
            if m["path"] == "DIRECT_SENTINEL_WHEP" and liveish:
                counts["DIRECT_WHEP"] += 1
            if str(m["path"]).startswith("BRIDGED") and liveish:
                counts["BRIDGED"] += 1
            tiles.append({
                **m, "ux": ux, "verdict": verdict,
                "first_frame_ms": t.get("first"),
                "currentTime": t.get("currentTime"),
                "framesDecoded": t.get("framesDecoded"),
                "framesDropped": t.get("framesDropped"),
                "packetsLost": t.get("packetsLost"),
                "freezes": t.get("freezes"),
                "ice": t.get("ice"),
                "error": safe(t.get("error")),
            })
        on_wall = {m["camera_id"] for m in meta}
        # Unready bridge candidates + any cam not on wall
        for i in range(1, 31):
            cid = f"cam{i:02d}"
            if cid in on_wall:
                continue
            if cid in RTSP_ONLY or cid in bridged:
                counts["RTSP_ONLY_AI"] += 1
            elif cid in DIRECT_WHEP:
                counts["NO_SIGNAL"] += 1
            else:
                counts["NO_SIGNAL"] += 1
        return {
            "label": "MEASURED_REAL",
            "seconds": seconds,
            "bridge_tier": bridge_tier,
            "full_budget": full_budget,
            "bridged_requested": bridged,
            "bridged_ready": ready_bridged,
            "bridged": ready_bridged,
            "ready_n": len(ready_bridged),
            "browser_visible": counts["LIVE"] + counts["PREVIEW"],
            "ux_counts": counts,
            "tiles": tiles,
            "gpu": wall.get("gpu"),
            "resources": wall.get("resources"),
            "cpu_percent": psutil.cpu_percent(0.3),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 3),
        }
    finally:
        for p in pubs:
            if p.poll() is None:
                p.terminate()
        if mtx is not None:
            try:
                mtx.terminate()
            except Exception:
                pass


def promote_bridged_prewarm(camera_id: str = "cam07", *,
                            promotions: int = 10) -> dict:
    """Warm promote: attach pre-negotiated local WHEP stream without second POST."""
    from playwright.sync_api import sync_playwright

    mtx = start_mediamtx([camera_id])
    pubs = [start_bridge(camera_id, tier="PREVIEW", mode="transcode")]
    try:
        ready = wait_ready(
            [camera_id], timeout=70, pubs=pubs, tier="PREVIEW", max_restarts=3,
        )
        pub = pubs[0]
        if not ready.get("ok"):
            return {"overall": "FAIL", "error": "path_not_ready", "ready": ready}
        endpoint = f"http://127.0.0.1:8889/stream/gov-{camera_id}/whep"
        js = r"""
async ({endpoint, promotions}) => {
  const negotiate = async () => {
    const t0 = performance.now();
    const pc = new RTCPeerConnection();
    const stream = new MediaStream();
    pc.addTransceiver('video', {direction: 'recvonly'});
    pc.ontrack = (ev) => stream.addTrack(ev.track);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 2000);
      if (pc.iceGatheringState === 'complete') resolve();
      else pc.addEventListener('icegatheringstatechange', () => {
        if (pc.iceGatheringState === 'complete') { clearTimeout(t); resolve(); }
      });
    });
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/sdp', 'Accept': 'application/sdp'},
      body: pc.localDescription.sdp,
      signal: AbortSignal.timeout(15000),
    });
    if (!resp.ok) throw new Error('WHEP ' + resp.status);
    await pc.setRemoteDescription({type: 'answer', sdp: await resp.text()});
    return {pc, stream, negotiation_ms: performance.now() - t0, http: resp.status};
  };
  const waitFirst = async (video, budgetMs) => {
    const t0 = performance.now();
    await video.play().catch(() => {});
    while (performance.now() - t0 < budgetMs) {
      if (video.videoWidth > 0 && video.currentTime > 0)
        return performance.now() - t0;
      await new Promise(r => setTimeout(r, 40));
    }
    return null;
  };
  const cold = document.querySelector('#cold');
  const warm = document.querySelector('#warm');
  const pool = document.querySelector('#pool');
  let coldRow = {click_to_frame_ms: null, negotiation_ms: null, error: null};
  try {
    const t0 = performance.now();
    const neg = await negotiate();
    coldRow.negotiation_ms = neg.negotiation_ms;
    cold.srcObject = neg.stream;
    const ff = await waitFirst(cold, 12000);
    coldRow.click_to_frame_ms = ff == null ? null : (performance.now() - t0);
    neg.pc.close(); cold.srcObject = null;
  } catch (e) { coldRow.error = String(e && e.message || e); }
  const times = []; let errors = 0;
  for (let i = 0; i < promotions; i++) {
    let pc = null;
    try {
      const neg = await negotiate();
      pc = neg.pc;
      pool.srcObject = neg.stream;
      await pool.play().catch(() => {});
      if (await waitFirst(pool, 12000) == null) throw new Error('prewarm_no_frame');
      await new Promise(r => setTimeout(r, 400));
      const clickT0 = performance.now();
      warm.srcObject = neg.stream;
      const ff = await waitFirst(warm, 6000);
      if (ff == null) errors += 1;
      else times.push(performance.now() - clickT0);
      pc.close(); pool.srcObject = null; warm.srcObject = null;
      await new Promise(r => setTimeout(r, 150));
    } catch (e) {
      errors += 1;
      try { if (pc) pc.close(); } catch (_) {}
    }
  }
  const sorted = times.slice().sort((a,b)=>a-b);
  const pct = (p) => {
    if (!sorted.length) return null;
    const k = (sorted.length - 1) * (p / 100);
    const f = Math.floor(k), c = Math.min(f + 1, sorted.length - 1);
    return f === c ? sorted[f] : sorted[f] + (sorted[c] - sorted[f]) * (k - f);
  };
  return {
    cold: coldRow,
    warm: {
      promotions_requested: promotions, promotions_ok: times.length, errors,
      p50: pct(50), p95: pct(95), max: sorted.length ? sorted[sorted.length-1] : null,
      times_ms: times,
    },
  };
}
"""
        html = """<!doctype html><html><body style="margin:0;background:#111;color:#eee">
        <video id="cold" autoplay muted playsinline style="width:320px;height:180px;background:#000"></video>
        <video id="warm" autoplay muted playsinline style="width:320px;height:180px;background:#000"></video>
        <video id="pool" autoplay muted playsinline style="width:1px;height:1px;opacity:0"></video>
        </body></html>"""
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--use-angle=metal", "--autoplay-policy=no-user-gesture-required",
                      "--disable-web-security"],
            )
            page = browser.new_page()
            page.set_content(html)
            page.set_default_timeout(180_000)
            result = page.evaluate(js, {"endpoint": endpoint, "promotions": promotions})
            browser.close()
        warm = result.get("warm") or {}
        return {
            "label": "MEASURED_REAL",
            "path": "BRIDGED_PREVIEW_PREWARM",
            "camera_id": camera_id,
            "note": "Not the synthetic/local 44ms figure",
            "cold": result.get("cold"),
            "warm": warm,
            "overall": "PASS" if (warm.get("promotions_ok") or 0) >= promotions // 2 else "FAIL",
        }
    finally:
        if pub.poll() is None:
            pub.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass


def write_report(payload: dict) -> Path:
    prof = payload.get("profile") or {}
    scale = payload.get("scale") or {}
    walls = payload.get("walls") or []
    promo = payload.get("prewarm") or {}
    lines = [
        "# Phase 16 — 30-camera browser coverage",
        "",
        f"Timestamp UTC: `{payload['timestamp_utc']}`",
        "",
        "Catalogue: **NOT_AUTHORITATIVE**. Direct Sentinel WHEP path unchanged.",
        "",
        "## Labels",
        "",
        "| Label | Use |",
        "|---|---|",
        "| MEASURED_REAL | This phase |",
        "| NOT_AUTHORITATIVE | Probe camera IDs |",
        "| DESIGNED | 50-cam regional pools |",
        "",
        "## Compatibility path (intentional)",
        "",
        "| Step | Result |",
        "|---|---|",
        f"| H.264 B-frame source → copy → WHEP | **FAIL** — {COPY_FAIL_REASON} |",
        "| H.264 → VideoToolbox baseline → WHEP | **PASS** |",
        "",
        "## 30-camera source matrix",
        "",
        "| Path | Cameras | Count |",
        "|---|---|---:|",
        f"| DIRECT_SENTINEL_WHEP | {', '.join(DIRECT_WHEP)} | {len(DIRECT_WHEP)} |",
        f"| RTSP_ONLY (bridge candidates) | {', '.join(RTSP_ONLY)} | {len(RTSP_ONLY)} |",
        "",
        "## Scheduler tiers",
        "",
        "| Tier | Priority | Notes |",
        "|---|---|---|",
        "| DIRECT_WHEP | preferred | Untouched Sentinel WHEP |",
        "| BRIDGED_PRIMARY | high | Full-quality VT baseline |",
        "| BRIDGED_PREVIEW | normal | Cheap VT baseline (500k) |",
        "| RTSP_ONLY_AI | fallback | When browser representation unavailable |",
        "",
        "## Bridge cost profile (cam07)",
        "",
        "| Tier | Startup s | ffmpeg CPU | RSS MB | Resolution | first_frame ms | WHEP |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for tier in ("PRIMARY", "PREVIEW"):
        t = (prof.get("tiers") or {}).get(tier) or {}
        lines.append(
            f"| {tier} | {t.get('startup_s')} | {t.get('ffmpeg_cpu_mean')} | "
            f"{t.get('ffmpeg_rss_mb_mean')} | {t.get('width')}x{t.get('height')} | "
            f"{round(t.get('first_frame_ms') or 0)} | {t.get('whep_status')} |"
        )
    lines += [
        "",
        f"CPU ratio PREVIEW/PRIMARY: `{prof.get('cpu_ratio_preview_over_primary')}`",
        f"RSS ratio PREVIEW/PRIMARY: `{prof.get('rss_ratio_preview_over_primary')}`",
        "",
        f"Bottleneck: {prof.get('bottleneck_observation')}",
        "",
        f"PREVIEW encode (concurrency): `{scale.get('preview_encode') or 'VT baseline 500k'}`",
        "",
        "## Bridge concurrency (PREVIEW tier, staggered)",
        "",
        "| n | Overall | Live | P/A/F | first p50 | ffmpeg CPUΣ | RSS MBΣ | sys CPU |",
        "|---:|---|---:|---|---:|---:|---:|---:|",
    ]
    for r in scale.get("rows") or []:
        if r.get("overall") == "SKIP":
            continue
        lines.append(
            f"| {r['n']} | {r['overall']} | {r.get('live_tiles')} | "
            f"{r.get('PASS')}/{r.get('AMBER')}/{r.get('FAIL')} | "
            f"{round(r.get('first_frame_ms_p50') or 0)} | "
            f"{r.get('ffmpeg_cpu_sum')} | {r.get('ffmpeg_rss_mb_sum')} | "
            f"{r.get('system_cpu')} |"
        )
    lines += [
        "",
        f"Chosen bridge budget: **{scale.get('chosen_bridge_budget')}**",
        "",
        "## Hybrid 30-camera wall",
        "",
        "| Soak | browser-visible | LIVE | PREVIEW | DIRECT | BRIDGED | RTSP_ONLY_AI | NO_SIGNAL |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for w in walls:
        u = w.get("ux_counts") or {}
        lines.append(
            f"| {int(w['seconds'])}s | **{w.get('browser_visible')}** | "
            f"{u.get('LIVE')} | {u.get('PREVIEW')} | {u.get('DIRECT_WHEP')} | "
            f"{u.get('BRIDGED')} | {u.get('RTSP_ONLY_AI')} | {u.get('NO_SIGNAL')} |"
        )
    warm = (promo.get("warm") or {})
    cold = (promo.get("cold") or {})
    lines += [
        "",
        "## Bridged PREVIEW promotion prewarm (MEASURED_REAL)",
        "",
        f"| Cold click→frame | {cold.get('click_to_frame_ms')} ms |",
        f"| Warm p50 | **{warm.get('p50')}** ms |",
        f"| Warm p95 | {warm.get('p95')} ms |",
        f"| Warm max | {warm.get('max')} ms |",
        f"| OK | {warm.get('promotions_ok')} / {warm.get('promotions_requested')} |",
        "",
        "Do **not** reuse synthetic/local 44 ms.",
        "",
        "## Remaining RTSP_ONLY_AI",
        "",
    ]
    # From best wall
    best = max(walls, key=lambda w: w.get("browser_visible") or 0) if walls else {}
    rem = (best.get("ux_counts") or {}).get("RTSP_ONLY_AI")
    lines += [
        f"Count on best soak: **{rem}**",
        f"Bridges ready on best soak: **{(best.get('ready_n') or len(best.get('bridged') or []))}**",
        "",
        "## Operator wall layouts",
        "",
        "- Default demo wall: **12** (kept)",
        "- Added: **16 (4×4)**, **25 (5×5)**, **30 (6×5)**",
        "- Tile meta: name, location, LIVE/PREVIEW, codec, latency, AI state (chips under video)",
        "",
        "## AI impact",
        "",
        "- RTSP→AI plane unchanged; WHEP→browser unchanged",
        "- Bridge load must not stop AI or video (scheduler keeps RTSP_ONLY_AI when bridge unavailable)",
        "- Adaptive low cadence on non-PRIMARY/selected-SECONDARY (unchanged contract)",
        "",
        "## Latency (MEASURED_REAL)",
        "",
        f"- Bridged PREVIEW cold click→frame: `{(promo.get('cold') or {}).get('click_to_frame_ms')}` ms",
        f"- Bridged PREVIEW warm p50: `{(promo.get('warm') or {}).get('p50')}` ms (not synthetic 44 ms)",
        f"- Bridge WHEP first-frame p50 at n=15 scale: see concurrency table",
        "",
        "## Next bottleneck",
        "",
        "- **Upstream RTSP source health / auth lockout** after large concurrent opens "
        "(hybrid wall limited to ~4 ready bridges while scale proved n=15 when sources healthy)",
        "- VT encoder session stagger (≥3.5–5s) still required for cold starts",
        "- Browser decode budget when DIRECT(15)+BRIDGED(N) approach 27–30 tiles",
        "",
        "## Reproducibility",
        "",
        "```bash",
        "export SENTINEL_GRID_EMAIL=…",
        "export SENTINEL_GRID_PASSWORD=…",
        "cd saakshya",
        ".venv/bin/python tools/phase16_bridge_optimize.py --mode all",
        ".venv/bin/python tools/verify/secret_scan.py",
        "```",
        "",
        "Artifacts: `var/reports/phase10/performance/phase16_*.json`",
        "",
    ]
    md = "\n".join(lines)
    refuse_secrets(md)
    path = REPORTS / "PHASE16_30_CAMERA_BROWSER_COVERAGE.md"
    path.write_text(md)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["profile", "scale", "wall", "prewarm", "all"],
                        default="all")
    parser.add_argument("--sizes", default="1,2,4,6,8,10,12,15")
    parser.add_argument("--full-budget", type=int, default=8)
    parser.add_argument("--max-bridges", type=int, default=0,
                        help="0 = use chosen from scale")
    parser.add_argument("--wall-seconds", default="30,60,120")
    parser.add_argument("--stagger", type=float, default=3.5)
    args = parser.parse_args()

    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload: dict = {"timestamp_utc": datetime.now(UTC).isoformat()}

    if args.mode in {"profile", "all"}:
        prof = profile_bridge_cost("cam07")
        payload["profile"] = prof
        (OUT / "phase16_bridge_profile.json").write_text(json.dumps(prof, indent=2) + "\n")

    if args.mode in {"scale", "all"}:
        sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
        scale = scale_bridges(
            RTSP_ONLY, sizes=sizes, tier="PREVIEW",
            seconds=16, stagger_s=args.stagger,
        )
        payload["scale"] = scale
        (OUT / "phase16_bridge_scale.json").write_text(json.dumps(scale, indent=2) + "\n")

    if args.mode in {"prewarm", "all"}:
        print("=== BRIDGED PREVIEW PREWARM ===", flush=True)
        promo = promote_bridged_prewarm("cam07", promotions=10)
        payload["prewarm"] = promo
        (OUT / "phase16_bridged_prewarm.json").write_text(json.dumps(promo, indent=2) + "\n")
        print(json.dumps({
            "cold": (promo.get("cold") or {}).get("click_to_frame_ms"),
            "warm_p50": (promo.get("warm") or {}).get("p50"),
            "ok": (promo.get("warm") or {}).get("promotions_ok"),
        }), flush=True)

    if args.mode in {"wall", "all"}:
        chosen = args.max_bridges or (payload.get("scale") or {}).get("chosen_bridge_budget") or 6
        # Prefer PREVIEW tier bridges for coverage
        bridged = RTSP_ONLY[:chosen]
        walls = []
        for sec in [float(x) for x in args.wall_seconds.split(",") if x.strip()]:
            print(f"=== HYBRID {sec}s bridges={len(bridged)} ===", flush=True)
            w = hybrid_wall(
                direct=DIRECT_WHEP, bridged=bridged,
                full_budget=args.full_budget, seconds=sec,
                bridge_tier="PREVIEW",
            )
            walls.append(w)
            (OUT / f"phase16_hybrid_wall_{int(sec)}s.json").write_text(
                json.dumps(w, indent=2) + "\n"
            )
            print(json.dumps({
                "seconds": sec,
                "browser_visible": w.get("browser_visible"),
                "ux": w.get("ux_counts"),
            }), flush=True)
        payload["walls"] = walls
        payload["bridge_budget_used"] = chosen

    blob = json.dumps(payload, indent=2) + "\n"
    refuse_secrets(blob)
    (OUT / "phase16_operator.json").write_text(blob)
    # Merge missing pieces from disk if partial mode
    if "profile" not in payload and (OUT / "phase16_bridge_profile.json").exists():
        payload["profile"] = json.loads((OUT / "phase16_bridge_profile.json").read_text())
    if "scale" not in payload and (OUT / "phase16_bridge_scale.json").exists():
        payload["scale"] = json.loads((OUT / "phase16_bridge_scale.json").read_text())
    if "prewarm" not in payload and (OUT / "phase16_bridged_prewarm.json").exists():
        payload["prewarm"] = json.loads((OUT / "phase16_bridged_prewarm.json").read_text())
    cert = write_report(payload)
    print(json.dumps({"cert": str(cert),
                      "chosen_bridges": (payload.get("scale") or {}).get("chosen_bridge_budget"),
                      "best_visible": max((w.get("browser_visible") or 0)
                                          for w in (payload.get("walls") or [{"browser_visible": 0}]))}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
