#!/usr/bin/env python3
"""Final Model 1-4 certification. Runs measurements and writes evidence packs.

Never fabricates FPS, GPU, ANPR accuracy, 50 government live feeds, or 80k live
inference. Cites prior MEASURED_REAL wall artifacts; does not re-soak Sentinel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "verify"))

from final_reports import write_reports

from saakshya.command.certify import (
    NA,
    decode_own_window,
    measure_adapters,
    measure_ai_isolation,
    measure_bus,
    measure_gis_50,
    measure_gis_80k,
    measure_investigation,
    measure_logical_50,
    measure_overlay_modes,
    measure_registry,
    measure_scheduler_presets,
    measure_seek,
    measure_watchlist_fixture,
    percentile,
    probe_own_file,
    try_own_feed_ai,
)
from saakshya.store import Store

ART = ROOT / "var" / "reports" / "final"
OWN_A = Path("/Users/earther/Desktop/Gujarat CCTV/1.mp4")
OWN_B = Path("/Users/earther/Desktop/Gujarat CCTV/2.mp4")
OWN_PORTAL = ROOT / "var" / "submission" / "own_feed.mp4"


def dump(rel: str, payload: Any) -> Path:
    path = ART / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return path


def load_json(*parts: str) -> dict | list | None:
    p = ROOT.joinpath(*parts)
    if p.is_file():
        return json.loads(p.read_text())
    return None


def wall_from_hybrid() -> dict[str, Any]:
    hybrid = load_json("var", "reports", "phase10", "performance",
                       "phase16_hybrid_wall_120s.json") or {}
    tiles = hybrid.get("tiles") or []
    ff = [t["first_frame_ms"] for t in tiles
          if isinstance(t.get("first_frame_ms"), (int, float))]
    freezes = sum(int(t.get("freezes") or 0) for t in tiles)
    drops = sum(int(t.get("framesDropped") or 0) for t in tiles)
    lost = sum(int(t.get("packetsLost") or 0) for t in tiles)
    ux = hybrid.get("ux_counts") or {}
    return {
        "label": hybrid.get("label") or "MEASURED_REAL",
        "artifact": "var/reports/phase10/performance/phase16_hybrid_wall_120s.json",
        "seconds": hybrid.get("seconds"),
        "registered_government_probes": 30,
        "browser_visible": hybrid.get("browser_visible"),
        "FULL_LIVE": ux.get("LIVE"),
        "PREVIEW": ux.get("PREVIEW"),
        "DIRECT_WHEP": ux.get("DIRECT_WHEP"),
        "BRIDGED": ux.get("BRIDGED"),
        "RTSP_ONLY_AI": ux.get("RTSP_ONLY_AI"),
        "NO_SIGNAL": ux.get("NO_SIGNAL"),
        "first_frame_p50_ms": percentile(ff, 50),
        "first_frame_p95_ms": percentile(ff, 95),
        "freezes_sum": freezes,
        "frames_dropped_sum": drops,
        "packets_lost_sum": lost,
        "browser_cpu": NA,
        "browser_ram": NA,
        "gpu": NA,
        "note": ("Government hybrid wall. Do not mix with SYNTHETIC_CONTROL. "
                 "Not 50 government live feeds."),
    }


def wall_from_fresh_live() -> dict[str, Any] | None:
    """Cite the latest Direct WHEP soak when present. Does not re-hit Sentinel."""
    raw = load_json("var", "reports", "final", "live", "wall_30_60s.json")
    if not isinstance(raw, dict) or not raw.get("browser_visible"):
        return None
    cams = raw.get("cameras") or []
    ff = [c["first_frame_ms"] for c in cams
          if isinstance(c.get("first_frame_ms"), (int, float))]
    gpu = raw.get("gpu") if isinstance(raw.get("gpu"), dict) else {}
    return {
        "label": raw.get("label") or "MEASURED_REAL",
        "artifact": "var/reports/final/live/wall_30_60s.json",
        "seconds": raw.get("seconds"),
        "registered_government_probes": 30,
        "browser_visible": raw.get("browser_visible"),
        "FULL_LIVE": (raw.get("classes") or {}).get("LIVE") or raw.get("FULL"),
        "PREVIEW": raw.get("PREVIEW"),
        "RTSP_ONLY_AI": raw.get("RTSP_ONLY_AI"),
        "NO_SIGNAL": raw.get("NO_SIGNAL"),
        "DEGRADED": raw.get("DEGRADED"),
        "first_frame_p50_ms": raw.get("first_frame_p50_ms") or percentile(ff, 50),
        "first_frame_p95_ms": raw.get("first_frame_p95_ms") or percentile(ff, 95),
        "cpu_percent": raw.get("cpu_percent"),
        "gpu_renderer": gpu.get("renderer") or NA,
        "gpu_utilization": NA,
        "overall": raw.get("overall"),
        "note": ("Fresh Direct Sentinel WHEP 30-camera 60s soak. "
                 "NO_SIGNAL only when both planes fail. Not 50 government live feeds."),
    }


def wall_size_rows(hybrid: dict[str, Any]) -> list[dict[str, Any]]:
    scale = load_json("var", "reports", "phase10", "performance",
                      "phase16_bridge_scale.json") or {}
    by_n = {row["n"]: row for row in scale.get("rows") or []}
    wanted = (1, 4, 8, 12, 16, 25, 30, 50)
    out = []
    for n in wanted:
        row: dict[str, Any] = {"logical_n": n, "domain": "GOVERNMENT"}
        if n == 50:
            row.update({
                "registered": "30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL",
                "browser_visible_government": hybrid.get("browser_visible"),
                "label": "MEASURED_SYNTHETIC composition; government live ≠ 50",
                "FULL": NA, "PREVIEW": NA, "first_frame_p50_ms": NA,
            })
        elif n in by_n:
            r = by_n[n]
            row.update({
                "bridge_n": n,
                "tier": r.get("tier"),
                "live_tiles": r.get("live_tiles"),
                "first_frame_ms_p50": r.get("first_frame_ms_p50"),
                "ffmpeg_cpu_sum": r.get("ffmpeg_cpu_sum"),
                "label": r.get("label") or "MEASURED_REAL",
                "note": "PREVIEW-tier VT bridges, not the 19-tile hybrid wall",
            })
        elif n == 30:
            row.update({
                "registered": 30,
                "browser_visible": hybrid.get("browser_visible"),
                "FULL": hybrid.get("FULL_LIVE"),
                "PREVIEW": hybrid.get("PREVIEW"),
                "RTSP_ONLY_AI": hybrid.get("RTSP_ONLY_AI"),
                "NO_SIGNAL": hybrid.get("NO_SIGNAL"),
                "first_frame_p50_ms": hybrid.get("first_frame_p50_ms"),
                "first_frame_p95_ms": hybrid.get("first_frame_p95_ms"),
                "freezes": hybrid.get("freezes_sum"),
                "drops": hybrid.get("frames_dropped_sum"),
                "packet_loss": hybrid.get("packets_lost_sum"),
                "browser_cpu": NA, "browser_ram": NA, "gpu": NA,
                "label": "MEASURED_REAL hybrid 120s",
            })
        else:
            row.update({
                "label": NA,
                "note": f"No dedicated {n}-tile government wall soak in artifacts",
            })
        out.append(row)
    return out


def gov_ai_cite() -> dict[str, Any]:
    raw = load_json("var", "reports", "phase8c", "gov", "cam01_ai_runtime.json") or {}
    modes = []
    for row in raw.get("modes") or raw.get("results") or []:
        ai = row.get("ai") or {}
        modes.append({
            "mode": row.get("mode"),
            "verdict": row.get("verdict"),
            "pipeline_p50_ms": (ai.get("pipeline_latency") or {}).get("p50_ms"),
            "pipeline_p95_ms": (ai.get("pipeline_latency") or {}).get("p95_ms"),
            "frames_analysed": ai.get("frames_analysed"),
            "vehicle_detections": ai.get("vehicle_detections"),
            "person_note": "government cam01 — not an own-feed benchmark",
        })
    ocr = load_json("var", "reports", "ocr_evaluation.json")
    return {
        "label": "MEASURED_REAL government cam01",
        "artifact": "var/reports/phase8c/gov/cam01_ai_runtime.json",
        "modes": modes or "see JSON",
        "anpr_accuracy": (ocr or {}).get("accuracy") if ocr else NA,
        "not_own_feed": True,
        "gpu": NA,
    }


def pytest_unit() -> dict[str, Any]:
    t0 = time.perf_counter()
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/unit/test_command_final.py",
         "tests/unit/test_command_phase18.py",
         "tests/unit/test_annotate.py",
         "tests/unit/test_follow_vehicle.py",
         "tests/unit/test_watchlist_alerts.py", "-q"],
        cwd=ROOT, capture_output=True, text=True)
    return {
        "exit": r.returncode,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "tail": (r.stdout or "")[-1200:],
        "err_tail": (r.stderr or "")[-800:],
    }


def run() -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    for part in ("model1", "model2", "model3", "model4", "scale"):
        (ART / part).mkdir(parents=True, exist_ok=True)

    m1_rows = []
    gis80 = None
    with tempfile.TemporaryDirectory(prefix="m1-") as td:
        td_path = Path(td)
        for n in (1_000, 10_000, 50_000, 80_000):
            db = td_path / f"reg_{n}.db"
            row = measure_registry(n, db)
            dump(f"model1/registry_{n}.json", row)
            m1_rows.append(row)
            if n == 80_000:
                store80 = Store(f"sqlite:///{db}")
                gis80 = measure_gis_80k(store80)
                dump("model1/gis_80k.json", gis80)
                dump("scale/registry_80k.json", {"registry": row, "gis": gis80})

    with tempfile.TemporaryDirectory(prefix="m1-50-") as td:
        store50 = Store(f"sqlite:///{Path(td) / 'fifty.db'}")
        store50.create_all()
        fifty = measure_logical_50(store50)
        gis50 = measure_gis_50(store50)
        dump("model1/gis_50.json", gis50)
        dump("scale/fifty_logical.json", fifty)

    dump("model1/registry_all.json", m1_rows)

    hybrid = wall_from_hybrid()
    fresh_live = wall_from_fresh_live()
    sizes = wall_size_rows(hybrid)
    modes = measure_overlay_modes()
    dump("model2/hybrid_wall_120s_summary.json", hybrid)
    dump("model2/fresh_wall_30_60s.json", fresh_live)
    dump("model2/wall_sizes.json", sizes)
    dump("model2/overlay_modes.json", modes)

    adapters = [measure_adapters(n) for n in (2, 5, 10, 25, 50)]
    bus = measure_bus(5000)
    dump("model3/adapters.json", adapters)
    dump("model3/event_bus.json", bus)

    files = {}
    for key, path in (
            ("OWN-PEOPLE", OWN_A),
            ("OWN-TRAFFIC", OWN_B),
            ("portal_own_feed", OWN_PORTAL)):
        files[key] = probe_own_file(path) if path.is_file() else {
            "path": str(path), "exists": False, "label": NA}
    dump("model4/own_files.json", files)

    decode = []
    for cid, path in (("OWN-PEOPLE", OWN_A), ("OWN-TRAFFIC", OWN_B)):
        if not path.is_file():
            continue
        for w in (30.0, 60.0, 120.0):
            decode.append(decode_own_window(path, w, camera_id=cid))
    dump("model4/video_only_decode.json", decode)

    seek = measure_seek(OWN_A, 10.0) if OWN_A.is_file() else {
        "ok": False, "label": NA, "error": "OWN-PEOPLE file missing"}
    dump("model4/own_feed_seek.json", seek)

    ai_runs = []
    for cid, path in (("OWN-PEOPLE", OWN_A), ("OWN-TRAFFIC", OWN_B)):
        if path.is_file():
            ai_runs.append(try_own_feed_ai(path, cid, max_frames=12, timeout_s=50))
        else:
            ai_runs.append({"camera_id": cid, "label": NA, "error": "file missing"})
    dump("model4/own_feed_ai.json", ai_runs)

    with tempfile.TemporaryDirectory(prefix="m4-") as td:
        st = Store(f"sqlite:///{Path(td) / 'm4.db'}")
        st.create_all()
        watch = measure_watchlist_fixture(st)
        inv = measure_investigation(st)
        dump("model4/watchlist_controlled.json", watch)
        dump("model4/investigation.json", inv)

    cadence = measure_scheduler_presets()
    isolation = measure_ai_isolation()
    dump("model4/ai_cadence.json", cadence)
    dump("model4/failure_isolation.json", isolation)
    dump("model4/government_ai_cite.json", gov_ai_cite())

    unit = pytest_unit()
    dump("scale/unit_tests.json", unit)

    pack = {
        "generated_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "own_a": str(OWN_A),
        "own_b": str(OWN_B),
        "model1": m1_rows,
        "gis80": gis80,
        "fifty": fifty,
        "gis50": gis50,
        "hybrid": hybrid,
        "fresh_live": fresh_live,
        "wall_sizes": sizes,
        "modes": modes,
        "adapters": adapters,
        "bus": bus,
        "own_files": files,
        "decode": decode,
        "seek": seek,
        "own_ai": ai_runs,
        "watchlist": watch,
        "investigation": inv,
        "cadence": cadence,
        "isolation": isolation,
        "gov_ai": gov_ai_cite(),
        "unit": unit,
    }
    dump("certification_pack.json", pack)
    write_reports(ROOT / "reports", pack)
    return pack


if __name__ == "__main__":
    os.chdir(ROOT)
    run()
