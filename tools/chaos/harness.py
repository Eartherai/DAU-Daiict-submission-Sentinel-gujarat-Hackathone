#!/usr/bin/env python3
"""Chaos harness for the ingest layer.

The organiser's Integrator's Guide is, in effect, a list of the ways client
pipelines fail on their grid. This harness reproduces those conditions on demand
against the local replica so we find out in development rather than at the live
evaluation.

Faults injected
---------------
publisher_kill    Kill a path's publisher. Exercises reconnect + backoff.
path_remove       Remove a path entirely. Exercises "feed disappeared".
path_restore      Bring a removed path back. Exercises catalogue mutation.
scene_swap        Repoint a path at a different clip. Exercises the silent
                  scene cut that carries no PTS evidence.
codec_swap        Repoint a path at a clip with a different codec + resolution,
                  mid-session. Exercises decoder rebuild and re-baselining.

Usage
-----
    python tools/chaos/harness.py --minutes 5
    python tools/chaos/harness.py --minutes 120 --report var/logs/chaos.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.common.paths import display
from saakshya.ingest.stream import StreamConfig, StreamManager

API = "http://127.0.0.1:9997/v3"
FFMPEG_REL = "var/bin/ffmpeg"


def publish_cmd(clip: str, name: str) -> str:
    return (
        f"{FFMPEG_REL} -hide_banner -loglevel error -re -stream_loop -1 "
        f"-i var/media/{clip} -c copy -f rtsp rtsp://127.0.0.1:8554/{name}"
    )


class Chaos:
    def __init__(self, cameras: list[str], clips: dict[str, str]) -> None:
        self.cameras = cameras
        self.clips = clips           # camera_id -> its own clip filename
        self.all_clips = sorted(set(clips.values()))
        self.removed: set[str] = set()
        self.serving: dict[str, str] = dict(clips)
        self.log: list[dict] = []
        self.counts: Counter[str] = Counter()
        self.errors: list[str] = []

    @staticmethod
    def _enc(cam: str) -> str:
        # MediaMTX v3 expects the path name URL-encoded ("stream%2FC-014").
        # JSON-Pointer style ("stream~1C-014") 404s — verified against the API.
        return f"stream%2F{cam}"

    def _api(self, method: str, path: str, **kw) -> bool:
        try:
            r = httpx.request(method, f"{API}{path}", timeout=8.0, **kw)
            if r.status_code >= 400:
                self.errors.append(f"{method} {path} -> {r.status_code} {r.text[:120]}")
                return False
            return True
        except Exception as exc:
            self.errors.append(f"{method} {path} -> {type(exc).__name__}: {exc}")
            return False

    def _ready_time(self, cam: str) -> str | None:
        try:
            r = httpx.get(f"{API}/paths/get/{self._enc(cam)}", timeout=6.0)
            if r.status_code == 200:
                return r.json().get("readyTime")
        except Exception:
            pass
        return None

    def _session_id(self, cam: str) -> str | None:
        try:
            r = httpx.get(f"{API}/rtspsessions/list", timeout=6.0)
            for it in r.json().get("items", []):
                if it.get("path") == f"stream/{cam}" and it.get("state") == "publish":
                    return it.get("id")
        except Exception:
            pass
        return None

    def _record(self, fault: str, camera: str, ok: bool) -> None:
        self.counts[fault if ok else f"{fault}:FAILED"] += 1
        self.log.append({"t": round(time.time(), 2), "fault": fault,
                         "camera": camera, "ok": ok})

    # -- faults ------------------------------------------------------------- #
    def publisher_kill(self, cam: str) -> None:
        """Kick the publishing RTSP session. Exercises reconnect + backoff."""
        before = self._ready_time(cam)
        sid = self._session_id(cam)
        ok = bool(sid) and self._api("POST", f"/rtspsessions/kick/{sid}")
        if ok:
            ok = self._verify_restart(cam, before)
        self._record("publisher_kill", cam, ok)

    def path_remove(self, cam: str) -> None:
        if cam in self.removed:
            return
        ok = self._api("DELETE", f"/config/paths/delete/{self._enc(cam)}")
        if ok:
            self.removed.add(cam)
        self._record("path_remove", cam, ok)

    def path_restore(self, cam: str) -> None:
        if cam not in self.removed:
            return
        ok = self._api("POST", f"/config/paths/add/{self._enc(cam)}",
                       json={"runOnInit": publish_cmd(self.clips[cam], f"stream/{cam}"),
                             "runOnInitRestart": True})
        if ok:
            self.removed.discard(cam)
        self._record("path_restore", cam, ok)

    def _verify_restart(self, cam: str, before: str | None, timeout: float = 12.0) -> bool:
        """A fault that did not actually change anything is not a fault.

        Without this check the harness reports a green run while injecting
        nothing — which is exactly the false-confidence failure the system is
        supposed to avoid, so it must not exist in our own tooling either.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            after = self._ready_time(cam)
            if after and after != before:
                return True
            time.sleep(0.5)
        self.errors.append(f"{cam}: publisher did not restart (readyTime unchanged)")
        return False

    def _repoint(self, cam: str, clip: str, fault: str) -> None:
        if cam in self.removed:
            return  # path is currently removed; repointing it is a harness race
        before = self._ready_time(cam)
        # PATCH (not POST) — verified: POST to .../patch/ returns 404.
        ok = self._api("PATCH", f"/config/paths/patch/{self._enc(cam)}",
                       json={"runOnInit": publish_cmd(clip, f"stream/{cam}"),
                             "runOnInitRestart": True})
        if ok:
            ok = self._verify_restart(cam, before)
        self.serving[cam] = clip
        self._record(fault, cam, ok)

    def scene_swap(self, cam: str) -> None:
        others = [c for c in self.all_clips if c != self.serving.get(cam, self.clips[cam])]
        if others:
            self._repoint(cam, random.choice(others), "scene_swap")

    def codec_swap(self, cam: str) -> None:
        h265 = ["C-021.mp4", "C-047.mp4"]
        cur = self.serving.get(cam, self.clips[cam])
        target = random.choice(h265) if cur not in h265 else "C-014.mp4"
        self._repoint(cam, target, "codec_swap")

    def restore_all(self) -> None:
        for cam in list(self.removed):
            self.path_restore(cam)
        for cam in self.cameras:
            self._api("PATCH", f"/config/paths/patch/{self._enc(cam)}",
                      json={"runOnInit": publish_cmd(self.clips[cam], f"stream/{cam}"),
                            "runOnInitRestart": True})
            self.serving[cam] = self.clips[cam]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--interval", type=float, default=20.0,
                    help="seconds between injected faults")
    ap.add_argument("--report", default="var/logs/chaos_report.json")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)

    cat = json.loads((ROOT / "var" / "media" / "catalogue.json").read_text())
    catalogue = {c["id"]: c["urls"]["rtsp"] for c in cat["cameras"]}
    clips = {c["id"]: f"{c['id']}.mp4" for c in cat["cameras"]}
    cams = sorted(catalogue)

    print(f"chaos: {len(cams)} cameras, {args.minutes:.1f} min, "
          f"fault every ~{args.interval:.0f}s")

    mgr = StreamManager(StreamConfig())
    mgr.reconcile(catalogue)
    queues = {c: mgr.get(c).subscribe("chaos") for c in cams}  # type: ignore[union-attr]

    chaos = Chaos(cams, clips)
    stop = threading.Event()
    frames: Counter[str] = Counter()

    def drain() -> None:
        while not stop.is_set():
            for cid, q in queues.items():
                try:
                    f = q.get(timeout=0.01)
                except Exception:
                    continue
                if f is not None:
                    frames[cid] += 1

    t = threading.Thread(target=drain, daemon=True)
    t.start()

    faults = [chaos.publisher_kill, chaos.scene_swap, chaos.codec_swap,
              chaos.path_remove, chaos.path_restore]
    t_end = time.time() + args.minutes * 60
    next_fault = time.time() + 8.0
    last_report = time.time()

    try:
        while time.time() < t_end:
            now = time.time()
            if now >= next_fault:
                fault = random.choice(faults)
                cam = random.choice(cams)
                fault(cam)
                # Keep the running catalogue honest: a removed path is a camera
                # that has genuinely disappeared, and reconcile must handle it.
                live = {c: u for c, u in catalogue.items() if c not in chaos.removed}
                mgr.reconcile(live)
                next_fault = now + args.interval * random.uniform(0.6, 1.4)
            if now - last_report >= 30.0:
                a = mgr.aggregate()
                print(f"  [{int(t_end-now):>4}s left] streaming={a['cameras_streaming']}/"
                      f"{a['cameras_total']} reconn={a['reconnects']} "
                      f"segs={a['segment_breaks']} cuts={a['scene_cuts']} "
                      f"derr={a['decoder_errors']} frames={a['frames']}")
                last_report = now
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        stop.set()
        t.join(timeout=3)
        chaos.restore_all()

    agg = mgr.aggregate()
    per_cam = mgr.stats()
    mgr.stop_all()

    starved = [c for c in cams if frames[c] == 0]
    report = {
        "duration_min": args.minutes,
        "faults_injected": dict(chaos.counts),
        "api_errors": chaos.errors[:20],
        "aggregate": agg,
        "frames_per_camera": dict(frames),
        "cameras_that_never_produced_a_frame": starved,
        "per_camera": per_cam,
        "fault_log": chaos.log,
    }
    out = ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))

    print("\n=== CHAOS RESULT ===")
    print(f"faults injected : {dict(chaos.counts)}")
    print(f"frames decoded  : {agg['frames']:,}")
    print(f"reconnects      : {agg['reconnects']}")
    print(f"segment breaks  : {agg['segment_breaks']} (scene cuts {agg['scene_cuts']})")
    print(f"decoder errors  : {agg['decoder_errors']} (tolerated, not fatal)")
    print(f"open failures   : {agg['open_failures']}")
    print(f"report          : {display(out, ROOT)}")

    # Pass requires BOTH: faults actually landed, and the pipeline survived them.
    # A run where nothing was injected is a failed experiment, not a green tick.
    failed_injections = sum(v for k, v in chaos.counts.items() if k.endswith(":FAILED"))
    landed = sum(v for k, v in chaos.counts.items() if not k.endswith(":FAILED"))
    survived = agg["frames"] > 0 and not starved
    recovered = agg["reconnects"] > 0 or agg["segment_breaks"] > 0

    print(f"\nfaults landed   : {landed}   failed to inject: {failed_injections}")
    checks = [
        ("faults actually injected", landed > 0),
        ("no fault failed to inject", failed_injections == 0),
        ("pipeline kept decoding", survived),
        ("pipeline observed and recovered from disruption", recovered),
    ]
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    if starved:
        print(f"  starved cameras: {starved}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
