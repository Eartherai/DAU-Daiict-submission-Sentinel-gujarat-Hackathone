"""Read each camera's burned-in clock, so correlation rests on measurement.

Cross-camera correlation is refused by default because the live grid is a set of
replayed windows, not a synchronised estate: some cameras sit minutes apart and
others weeks. Joining two of the latter yields a journey that never happened, so
the system will not do it without evidence that a timebase is shared.

The strongest evidence available is the clock the cameras themselves burn into
the picture. There is no general-purpose OCR in this deployment — the ANPR model
reads plates, not date banners — so this uses the local vision-language model
from the registry. It runs on this machine: no frame leaves the deployment, and
`EXTERNAL_AI` is not involved.

A reading is kept only when independent frames agree on it to the minute. One
frame's reading of a small, low-contrast, moving overlay is a guess, and a guess
that becomes a cluster becomes a route.

Output is **candidates**. Declaring a cluster is a separate, deliberate act with
a stated basis — see tools/live/clusters.py.

    python tools/live/read_overlays.py --db sqlite:///var/live.db \
        --out var/reports/overlays.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# Heavy dependencies are imported where they are used, not at module scope.
# The text logic in this file — matching signage against a recorded label,
# wording the note that results — is pure and is unit-tested; importing it
# should not require torch, and in a clean install without the ML extras it
# cannot. `av` and `numpy` stay: they are needed by everything that touches a
# stream, and the pure functions do not touch one.
import av
import numpy as np

from saakshya.common.paths import display
from saakshya.live.credentials import credentialed, redact
from saakshya.store import Store

RTSP = "rtsp://103.250.160.189:8554/stream/{cam}"
OPTS = {"rtsp_transport": "tcp", "stimeout": "8000000",
        "rw_timeout": "8000000"}
#: A camera that connects and then stops delivering frames must not stop the
#: run. `stimeout` bounds the socket, `rw_timeout` bounds a read that has
#: started, and the deadline below bounds the loop itself — decode can keep
#: returning frames slowly for longer than the whole pass is worth waiting for.
GRAB_DEADLINE_S = 25.0

PROMPT = ("Read the date and time burned into this CCTV banner. Reply with only "
          "the timestamp exactly as shown, or NONE if there is no timestamp.")

#: These are heterogeneous devices from different departments and they do not
#: agree on a format. Three real readings were lost to a parser that only knew
#: dd-mm-yyyy: "2026-06-13 10:34:19 PM" and "2026-08-04 08:56:55" are perfectly
#: good clocks. A camera whose time cannot be read is excluded from every
#: cluster, so a parser gap silently costs correlation.
_DMY = re.compile(
    r"(\d{2})[-/.](\d{2})[-/.](\d{4})\D{0,6}?(\d{1,2})[:.](\d{2})[:.](\d{2})\s*([AP]M)?",
    re.IGNORECASE)
_YMD = re.compile(
    r"(\d{4})[-/.](\d{2})[-/.](\d{2})\D{0,6}?(\d{1,2})[:.](\d{2})[:.](\d{2})\s*([AP]M)?",
    re.IGNORECASE)


def grab(cam: str, wanted: int) -> tuple[str, list[np.ndarray], str | None]:
    """Frames from one camera, under a deadline that belongs to that camera.

    The bound has to be per-camera, not per-pass: with six workers and thirty
    cameras, a single global deadline is spent by whichever cameras happen to
    start first, and everything queued behind them is reported as "no frames"
    when it was never given a turn. That is a measurement about the scheduler
    masquerading as a measurement about the estate.
    """
    stop_at = time.monotonic() + GRAB_DEADLINE_S
    """Frames spread across the connection, so agreement means what it says."""
    frames: list[np.ndarray] = []
    try:
        c = av.open(credentialed(RTSP.format(cam=cam)), options=OPTS, timeout=30)
    except Exception as exc:
        return cam, [], f"{type(exc).__name__}: {redact(str(exc))[:90]}"
    try:
        for i, f in enumerate(c.decode(video=0)):
            if len(frames) >= wanted or time.monotonic() > stop_at:
                break
            if i % 40 == 0:
                frames.append(f.to_ndarray(format="rgb24"))
    except Exception as exc:
        if not frames:
            return cam, [], f"{type(exc).__name__}: {redact(str(exc))[:90]}"
    finally:
        with contextlib.suppress(Exception):
            c.close()
    if not frames:
        return cam, [], (f"connected but delivered no usable frame within "
                         f"{GRAB_DEADLINE_S:.0f}s")
    return cam, frames, None

def collect(cams: list[str], wanted: int, workers: int
            ) -> tuple[dict[str, list[np.ndarray]], dict[str, str]]:
    """Grab from every camera, and give up on the ones that stall.

    `ThreadPoolExecutor.map` waits for every task, so one camera stuck inside
    `decode()` held an entire pass indefinitely — observed as a process sitting
    at 0.3% CPU with no output. A thread blocked in a C extension cannot be
    cancelled, so the pool is abandoned rather than joined: the stalled camera
    is reported as such and the run continues with what it has.
    """
    grabbed: dict[str, list[np.ndarray]] = {}
    errors: dict[str, str] = {}
    ex = cf.ThreadPoolExecutor(workers)
    try:
        futures = {ex.submit(grab, c, wanted): c for c in cams}
        # Each camera bounds itself, so this only has to cover the queue:
        # ceil(cameras / workers) batches, plus slack for connection setup.
        batches = -(-len(cams) // max(1, workers))
        deadline = GRAB_DEADLINE_S * batches + 30.0
        done, pending = cf.wait(futures, timeout=deadline)
        for fut in done:
            cam, frames, err = fut.result()
            if err and not frames:
                errors[cam] = err
            else:
                grabbed[cam] = frames
        for fut in pending:
            errors[futures[fut]] = (
                f"did not finish within the {deadline:.0f}s pass budget; "
                "skipped so the pass could complete")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return grabbed, errors


def banner(img: np.ndarray) -> Any:
    """Top and bottom strips stacked. These are heterogeneous devices and the
    overlay sits at either end; reading both beats assuming one."""
    from PIL import Image

    h = img.shape[0]
    return Image.fromarray(np.vstack([img[: int(h * 0.12)], img[int(h * 0.88):]]))


def parse(text: str) -> str | None:
    """Read a burned-in clock in any of the formats this estate produces."""
    flat = re.sub(r"[^0-9A-Za-z:/.\-]", "", text)
    for pattern, order in ((_YMD, "ymd"), (_DMY, "dmy")):
        m = pattern.search(flat)
        if not m:
            continue
        a, b, c, hh, mm, ss, ampm = m.groups()
        y, mo, d = ((int(a), int(b), int(c)) if order == "ymd"
                    else (int(c), int(b), int(a)))
        hh, mm, ss = int(hh), int(mm), int(ss)
        if ampm:
            ampm = ampm.upper()
            # 12 AM is 00, 12 PM is 12; every other PM hour adds twelve.
            if ampm == "PM" and hh != 12:
                hh += 12
            elif ampm == "AM" and hh == 12:
                hh = 0
        try:
            return datetime(y, mo, d, hh, mm, ss).isoformat()
        except ValueError:
            continue
    return None


def cluster(readings: dict[str, str], tolerance_min: float) -> list[list[str]]:
    parsed = {c: datetime.fromisoformat(t) for c, t in readings.items()}
    groups: list[list[str]] = []
    for cam in sorted(parsed, key=lambda c: parsed[c]):
        if groups and (parsed[cam] - parsed[groups[-1][-1]]
                       ) <= timedelta(minutes=tolerance_min):
            groups[-1].append(cam)
        else:
            groups.append([cam])
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--cameras", default="")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--tolerance-min", type=float, default=5.0)
    ap.add_argument("--agreement", type=int, default=2,
                    help="frames that must agree before a reading is kept")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    from saakshya.runtime.backend import quiet_transformers

    quiet_transformers()
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    mid = "Qwen/Qwen3-VL-4B-Instruct"
    device = ("mps" if torch.backends.mps.is_available()
              else "cuda" if torch.cuda.is_available() else "cpu")
    print(f"reader     : {mid} on {device} (local; no frame leaves this host)")
    # Cache first: a government network has no route to huggingface.co, and
    # `from_pretrained` reaching for the hub there does not fail promptly — it
    # sat at 0% CPU for twelve minutes with the model never loaded.
    proc = AutoProcessor.from_pretrained(mid, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        mid, dtype=torch.float16 if device != "cpu" else torch.float32,
        local_files_only=True,
    ).to(device).eval()

    store = Store(a.db)

    store.create_all()      # a store older than the code is migrated, not queried
    cams = ([c.strip() for c in a.cameras.split(",") if c.strip()]
            or [c["camera_id"] for c in store.list_cameras()])
    print(f"cameras    : {len(cams)}, {a.frames} frame(s) each, "
          f"{a.agreement} must agree\n")

    grabbed, errors = collect(cams, a.frames, workers=6)

    records: list[dict[str, Any]] = []
    for cam in cams:
        if cam in errors:
            print(f"  {cam:<8} unreachable — {errors[cam]}", flush=True)
            records.append({"camera_id": cam, "error": errors[cam],
                            "reading": None, "agreement": 0, "raw": []})
            continue
        raw: list[str] = []
        for img in grabbed[cam]:
            msgs = [{"role": "user", "content": [
                {"type": "image"}, {"type": "text", "text": PROMPT}]}]
            text = proc.apply_chat_template(msgs, tokenize=False,
                                            add_generation_prompt=True)
            inputs = proc(text=[text], images=[banner(img)],
                          return_tensors="pt").to(device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=40, do_sample=False)
            raw.append(proc.batch_decode(
                out[:, inputs["input_ids"].shape[1]:],
                skip_special_tokens=True)[0].strip())

        stamps = [s for s in (parse(r) for r in raw) if s]
        keep, n = None, 0
        if stamps:
            # Agreement to the minute: the second hand differs between frames
            # taken seconds apart, and demanding it would reject every camera.
            best, n = Counter(s[:16] for s in stamps).most_common(1)[0]
            if n >= a.agreement:
                keep = best
        state = keep or ("no agreement" if stamps else "no clock read")
        print(f"  {cam:<8} {state:<20} {n}/{len(raw)} agree   raw={raw[:2]}", flush=True)
        records.append({"camera_id": cam, "error": None, "reading": keep,
                        "agreement": n, "raw": raw})

    readings = {r["camera_id"]: r["reading"] for r in records if r["reading"]}
    groups = cluster(readings, a.tolerance_min)
    print(f"\nread a clock from {len(readings)} of {len(cams)} camera(s)")
    print(f"candidate clusters at +/-{a.tolerance_min:g} min:")
    for i, g in enumerate(sorted(groups, key=len, reverse=True), 1):
        print(f"  {i}. {len(g):>2} camera(s)  {readings[g[0]][:16]}  "
              f"{', '.join(sorted(g))}")
    if not groups:
        print("  none — no two cameras were shown to share a timebase")

    # Record the readings against the cameras. A measurement that lives only in
    # a report file cannot be used by the correlation gate, and the gate is the
    # whole reason for taking it.
    from saakshya.live.timebase import (
        OverlayClock,
        PtsHealth,
        TimebaseHealth,
        TimebaseRegistry,
    )

    timebase = TimebaseRegistry(store)
    stored = 0
    for rec in records:
        prior = timebase.get(rec["camera_id"])
        clock = (OverlayClock.PRESENT if rec["reading"]
                 else OverlayClock.ABSENT if not rec["error"]
                 else OverlayClock.UNKNOWN)
        timebase.record(TimebaseHealth(
            camera_id=rec["camera_id"],
            pts_health=(prior.pts_health if prior else PtsHealth.UNKNOWN),
            pts_regressions=(prior.pts_regressions if prior else 0),
            pts_forward_jumps=(prior.pts_forward_jumps if prior else 0),
            realtime_ratio=(prior.realtime_ratio if prior else None),
            measured_fps=(prior.measured_fps if prior else None),
            mean_interframe_gap_s=(prior.mean_interframe_gap_s if prior else None),
            max_interframe_gap_s=(prior.max_interframe_gap_s if prior else None),
            overlay_clock=clock, overlay_reading=rec["reading"],
            time_cluster=(prior.time_cluster if prior else None),
            cluster_confidence=(prior.cluster_confidence if prior else "UNKNOWN"),
            evidence={"source": f"overlay read by {mid}",
                      "frames_agreeing": rec["agreement"],
                      "raw": rec.get("raw", [])[:3]}))
        stored += 1
    print(f"recorded   : {stored} overlay reading(s) against the camera registry")

    payload = {"model": mid, "device": device,
               "tolerance_minutes": a.tolerance_min,
               "agreement_required": a.agreement,
               "cameras": records, "readings": readings,
               "candidate_clusters": [sorted(g) for g in groups],
               "note": ("Candidates only, measured from burned-in overlays. A "
                        "cluster becomes usable for correlation when declared "
                        "with a basis via tools/live/clusters.py declare.")}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(payload, indent=2))
        print(f"\nwritten: {display(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
