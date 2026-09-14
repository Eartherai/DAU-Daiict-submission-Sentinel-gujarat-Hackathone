"""Corroborate each camera's position from what the camera can see.

Nineteen of thirty cameras were placed from their names alone — "Paldi Circle"
put near the Paldi junction — and recorded as DERIVED_FROM_NAME, precision
LANDMARK or LOCALITY. That is honest but weak: a name is a label someone typed,
and nothing had checked it against the picture.

The picture often settles it. A junction camera sees road signs, hospital and
shop boards, hoardings and direction plates, frequently in both Gujarati and
English. cam04's view carries "PALDI JUNCTION", "V.S. Hospital" and "UDIPI CAFE"
— three independent confirmations that the name-derived position is right.

This reads that signage with the local vision-language model and records it as
corroborating evidence. It does **not** move a camera: a place name read off a
hoarding is evidence about the view, not a survey, and turning text into
coordinates without a gazetteer would be inventing precision. What it does is
tell an operator whether the picture agrees with the label — and say so when it
does not, which is the case worth catching.

Runs entirely on this host; no frame leaves the deployment.

    python tools/live/read_landmarks.py --db sqlite:///var/live.db \
        --out var/reports/landmarks.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import json
import re
import sys
import time
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


PROMPT = (
    "This is a CCTV view of an Indian street. List every place name you can "
    "read on signs, shop boards, hoardings, direction signs or buildings — "
    "road names, junction names, hospitals, shops, landmarks. Include Gujarati "
    "text transliterated. Reply as a comma-separated list of names only, with "
    "no commentary. Reply NONE if no place name is legible.")

#: Words that name no place. A model asked for landmarks will sometimes return
#: the category rather than the name, and "hospital" on its own corroborates
#: nothing.
_GENERIC = {
    "none", "n/a", "hospital", "cafe", "restaurant", "shop", "store", "road",
    "street", "junction", "circle", "signal", "traffic", "bus", "stop", "city",
    "market", "school", "college", "bank", "atm", "hotel", "petrol", "pump",
    "police", "station", "temple", "medical", "clinic", "office", "building",
}


def grab(cam: str, wanted: int) -> tuple[str, list[np.ndarray], str | None]:
    """Frames from one camera, under a deadline that belongs to that camera.

    The bound has to be per-camera, not per-pass: with six workers and thirty
    cameras, a single global deadline is spent by whichever cameras happen to
    start first, and everything queued behind them is reported as "no frames"
    when it was never given a turn. That is a measurement about the scheduler
    masquerading as a measurement about the estate.
    """
    stop_at = time.monotonic() + GRAB_DEADLINE_S
    frames: list[np.ndarray] = []
    try:
        c = av.open(credentialed(RTSP.format(cam=cam)), options=OPTS, timeout=30)
    except Exception as exc:
        return cam, [], f"{type(exc).__name__}: {redact(str(exc))[:90]}"
    try:
        for i, f in enumerate(c.decode(video=0)):
            if len(frames) >= wanted or time.monotonic() > stop_at:
                break
            if i % 60 == 0:
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


def clean(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,\n;]+", raw):
        name = re.sub(r"[^0-9A-Za-z.\s&'-]", " ", part).strip(" .-")
        name = re.sub(r"\s+", " ", name)
        if len(name) < 3 or name.lower() in _GENERIC:
            continue
        if name.lower().startswith(("none", "no place", "i cannot", "there is")):
            continue
        out.append(name)
    return out


def _tokens(text: str) -> set[str]:
    """Distinctive words in a label, with acronyms preserved.

    Punctuation is stripped *before* words are extracted, so "O.N.G.C." becomes
    "ongc" rather than five one-letter fragments that no minimum length can
    keep. Without that, cam03's label "O.N.G.C. Office" retained no token at all
    — "office" is generic — and a reading of "O.N.G.C. Office BS-103 B1" was
    reported as disagreeing with it.
    """
    flat = re.sub(r"[.\-']", "", text.lower())
    return {w for w in re.findall(r"[a-z]{3,}", flat) if w not in _GENERIC}


def agrees(names: list[str], camera_name: str, site: str) -> list[str]:
    """Which read names share a distinctive word with the recorded label.

    Two tests, because either alone loses real matches. Whole-token overlap
    catches "O.N.G.C. Office" against "O.N.G.C. Office BS-103 B1", which
    substring matching missed once acronyms were normalised. Substring
    containment catches "Suvidha Park" against "Suvidhapark", where the sign
    runs the words together and no token is shared. Signage is written by
    whoever painted the board, and it does not agree with a registry on
    spacing.
    """
    words = _tokens(f"{camera_name} {site}")
    if not words:
        return []
    hits = []
    for n in names:
        read = _tokens(n)
        joined = re.sub(r"[^a-z]", "", n.lower())
        if (read & words
                or any(w in joined for w in words if len(w) >= 5)
                or any(joined and joined in w for w in words if len(joined) >= 5)):
            hits.append(n)
    return hits


def signage_note(rec: dict[str, Any], model_id: str) -> str:
    """What to record against a camera, given what its own view showed.

    Three cases, and conflating them misleads. A camera whose signage matches
    its label is corroborated. A camera whose signage names somewhere else is a
    disagreement worth a human look. A camera with **no recorded label at all**
    — several here are called nothing but `cam25` — is neither: the signage is
    the first evidence anyone has about where it points, and reporting that as
    "does not match the recorded label" states a conflict with a label that does
    not exist.
    """
    read = ", ".join(rec["names"][:6])
    label = str(rec.get("label") or "").strip()
    unnamed = not label or label.lower().startswith("cam")
    if rec["corroborates"]:
        return (f"Signage in this camera's own view names "
                f"{', '.join(rec['corroborates'][:3])} — corroborates the "
                f"recorded position. Read locally by {model_id}.")
    if unnamed:
        return (f"This camera has no recorded name. Signage in its own view "
                f"names {read} — the first evidence of where it points, and a "
                f"lead for an operator to place it. Not a position: a name on "
                f"a hoarding is not a survey. Read locally by {model_id}.")
    return (f"Signage in this camera's own view names {read}, which does not "
            f"match the recorded label. Not corrected automatically — a place "
            f"name on a hoarding is evidence about the view, not a survey. "
            f"Read locally by {model_id}.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--cameras", default="")
    ap.add_argument("--frames", type=int, default=2)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    from saakshya.runtime.backend import quiet_transformers

    quiet_transformers()
    import torch
    from PIL import Image
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
    registry = {c["camera_id"]: c for c in store.list_cameras()}
    cams = ([c.strip() for c in a.cameras.split(",") if c.strip()]
            or sorted(registry))
    print(f"cameras    : {len(cams)}, {a.frames} frame(s) each\n")

    grabbed, errors = collect(cams, a.frames, workers=6)

    records: list[dict[str, Any]] = []
    for cam in cams:
        info = registry.get(cam, {})
        if cam in errors:
            print(f"  {cam:<8} unreachable — {errors[cam]}", flush=True)
            records.append({"camera_id": cam, "error": errors[cam],
                            "names": [], "corroborates": [], "raw": []})
            continue
        raw: list[str] = []
        for img in grabbed[cam]:
            msgs = [{"role": "user", "content": [
                {"type": "image"}, {"type": "text", "text": PROMPT}]}]
            text = proc.apply_chat_template(msgs, tokenize=False,
                                            add_generation_prompt=True)
            inputs = proc(text=[text], images=[Image.fromarray(img)],
                          return_tensors="pt").to(device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=120, do_sample=False)
            raw.append(proc.batch_decode(
                out[:, inputs["input_ids"].shape[1]:],
                skip_special_tokens=True)[0].strip())

        names = sorted({n for r in raw for n in clean(r)}, key=str.lower)
        hits = agrees(names, str(info.get("name") or ""), str(info.get("site") or ""))
        verdict = ("CORROBORATED" if hits else
                   "NO OVERLAP" if names else "NO SIGNAGE READ")
        print(f"  {cam:<8} {verdict:<16} label={info.get('name') or '-'!s:<26} "
              f"read={', '.join(names[:5]) or '-'}")
        records.append({"camera_id": cam, "error": None,
                        "label": info.get("name"), "site": info.get("site"),
                        "district": info.get("district"),
                        "location_basis": info.get("location_basis"),
                        "names": names, "corroborates": hits,
                        "verdict": verdict, "raw": raw})

    tally: dict[str, int] = {}
    for r in records:
        tally[r.get("verdict", "ERROR")] = tally.get(r.get("verdict", "ERROR"), 0) + 1
    print(f"\nverdicts   : {tally}")
    disagree = [r for r in records if r.get("verdict") == "NO OVERLAP"]
    if disagree:
        print("\ncameras whose signage names nothing in their recorded label — "
              "worth a human look, not an automatic correction:")
        for r in disagree:
            print(f"  {r['camera_id']:<8} label={r['label']!s:<28} "
                  f"read={', '.join(r['names'][:6])}")

    # Record it against the camera. A finding that lives only in a report file
    # cannot reach the investigator looking at that camera, and the point of
    # corroborating a position is that the person relying on it can see what it
    # rests on. Written to `location_note`, which is curated metadata: it never
    # changes the coordinates.
    stored = 0
    for rec in records:
        if rec.get("error") or not rec.get("names"):
            continue
        store.upsert_camera({"camera_id": rec["camera_id"],
                             "location_note": signage_note(rec, mid)})
        stored += 1
    print(f"recorded   : {stored} signage note(s) against the camera registry")

    payload = {"model": mid, "device": device, "cameras": records,
               "note": ("Signage read from the cameras' own imagery. This "
                        "corroborates or questions a recorded position; it "
                        "never moves a camera. Turning a hoarding into "
                        "coordinates without a gazetteer would be inventing "
                        "precision.")}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(payload, indent=2))
        print(f"\nwritten: {display(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
