"""Add an Indian-English voiceover to the recorded walkthrough.

The walkthrough films the interface; this gives it a voice, so it can be watched
without reading every caption. Narration is generated with the system's offline
text-to-speech (`say`, voice Rishi — en_IN) and muxed onto the existing frames.
No cloud service touches it, and nothing about the recording changes: the same
real screens, now spoken over.

Each segment's audio is padded with silence to exactly its segment's on-screen
duration and the segments are concatenated in order, so the voice stays in sync
with the screen by construction rather than by a timing guess.

    python tools/demo/narrate.py --shots var/demo/walkthrough_live \
        --out var/demo/walkthrough_live_narrated

Requires the recorded screenshots (run record_walkthrough.py first) and the
bundled ffmpeg from imageio-ffmpeg. Voice generation is macOS `say`; on a host
without it the tool says so and exits rather than shipping a silent file that
looks narrated.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

from record_walkthrough import Shot, Step, compose
from render_demo_video import FPS, card, display, encode

VOICE = "Rishi"            # en_IN, clear and professional
WPM = 168                  # `say` rate; measured comfortable for this voice
PAD_S = 0.9                # breath after each line before the screen moves on
MIN_HOLD = 4.0

#: Title, screenshot index, and what the voice says over it. The narration is
#: written to be heard, not read — fuller than the on-screen caption, in the
#: register of a briefing rather than a manual.
NARRATION = [
    ("Government feed demonstration", None,
     "This is Saakshya — साक्ष्य, evidence — a federated C C T V intelligence "
     "and evidence platform for the Gujarat Police. Everything you are about to "
     "see is the real interface, driven against a live server. Nothing is "
     "staged."),
    ("Overview", 0,
     "A shift begins on the command picture. The first panel is the shift "
     "picture: the open alert, how many cameras published a mark, and that "
     "zero graded good for A N P R is a statement about yield, not emptiness. "
     "The panels under it are the evidence for those three facts."),
    ("Purpose binding", 1,
     "Before any search runs, the officer states a case and a reason. This is "
     "not a dialog dismissed once. It is standing furniture, and it is written "
     "into every audit record the search produces."),
    ("Find", 2,
     "Here the platform has found the registration mark on a real government "
     "camera. Every candidate carries the basis of its match. A one-camera "
     "pattern is labelled as such — looping footage, not a fleet — and a "
     "lookalike is offered without editing the stored read."),
    ("Trace", 3,
     "The movement is plotted, with the vehicle's provenance beside it. And "
     "the platform is honest about its limits: a single camera means there is "
     "no interval to reason about, so its place on a timeline is marked "
     "provisional, not asserted."),
    ("Cameras", 4,
     "Every camera is graded from its own stream, never from a catalogue's "
     "claim. Unsuitable for A N P R is a statement about yield at this "
     "geometry, not that the store is empty of plates. Cameras that published "
     "a mark show the count beside the grade."),
    ("Analytics", 5,
     "What the estate can actually do, measured. Plate yield is a property of "
     "geometry and light, not of traffic volume. A busy junction whose plates "
     "are forty pixels wide will read none, and the platform says so rather "
     "than pretending otherwise."),
    ("Estate map", 6,
     "Nineteen cameras sit on the map, placed from their names with the "
     "precision stated. Eleven more are in the registry strip, because a name "
     "was not enough to locate them. Nothing is invented to fill the gaps."),
    ("Live", 7,
     "The live wall — real cameras from the government grid. Each tile is the "
     "still analytics already decoded, badged live when the frame is under two "
     "and a half seconds old, otherwise stale. Where a camera has published a "
     "mark, that count sits next to the grade. This is not thirty extra video "
     "sessions."),
    ("Alerts", 8,
     "A watchlist match carries its category, its priority, and the confidence "
     "it matched at, so an officer can triage before opening it."),
    ("The case file", 9,
     "What an officer hands on: targets attached with who attached them and "
     "when, notes, and the full audit trail behind every one — exportable as a "
     "single sealed record."),
    ("Evidence", 10,
     "Evidence is hash-chained and append-only. The chain verifies here. And "
     "where a record's own wording overstates what it holds, the platform "
     "raises a caution without failing the chain — because integrity and "
     "truthfulness are different questions, and both deserve an answer."),
    ("Audit", 11,
     "The audit log. Every query — actor, role, case, and purpose — "
     "hash-chained and append-only. A refusal is recorded as carefully as a "
     "result."),
    ("Copilot", 12,
     "The copilot is last, and optional. Sixteen read-only tools over the same "
     "service the officer already uses. It is not in the mandatory chain, and "
     "it will not enhance a government still."),
    ("Close", None,
     "Purpose bound before the search. Capability measured, never declared. "
     "Evidence sealed and honestly labelled. A restriction never reported as an "
     "absence. Saakshya — evidence you can stand behind."),
]


@dataclass
class Seg:
    title: str
    shot_index: int | None
    text: str
    audio: Path
    dur_s: float = 0.0
    hold_s: float = 0.0


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def audio_duration(ff: str, path: Path) -> float:
    """Duration in seconds, read straight from the container."""
    out = subprocess.run(
        [ff, "-i", str(path)], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def say_available() -> bool:
    from shutil import which
    return which("say") is not None


def generate(out_dir: Path, ff: str) -> list[Seg]:
    """Speak each line to its own file and measure it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    segs: list[Seg] = []
    for i, (title, idx, text) in enumerate(NARRATION):
        aiff = out_dir / f"{i:02d}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", str(WPM),
                        "-o", str(aiff), text], check=True)
        dur = audio_duration(ff, aiff)
        segs.append(Seg(title=title, shot_index=idx, text=text, audio=aiff,
                        dur_s=dur, hold_s=max(MIN_HOLD, dur + PAD_S)))
        print(f"  {i:02d}  {title:<26} {dur:5.1f}s speech → {segs[-1].hold_s:4.1f}s hold")
    return segs


def build_audio(ff: str, segs: list[Seg], work: Path) -> Path:
    """One track: each line padded with trailing silence to its segment's hold,
    concatenated in order. Sync is structural — no offset is ever guessed."""
    padded: list[Path] = []
    for i, seg in enumerate(segs):
        p = work / f"pad_{i:02d}.wav"
        # apad then trim to exactly hold_s: the line plays, then silence fills
        # the rest of the time its screen is up.
        subprocess.run(
            [ff, "-y", "-i", str(seg.audio), "-af", "apad",
             "-t", f"{seg.hold_s:.3f}", "-ar", "44100", "-ac", "2", str(p)],
            check=True, capture_output=True)
        padded.append(p)
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in padded))
    full = work / "narration_full.wav"
    subprocess.run(
        [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(full)], check=True, capture_output=True)
    return full


def build_video(segs: list[Seg], shots_dir: Path, out: Path) -> None:
    """The same frames as the silent walkthrough, held to the narration."""
    from PIL import Image
    frames: list[Image.Image] = []
    intro = card(
        [("WHAT THIS IS", "The real interface, driven live. Nothing staged."),
         ("VOICE", "Narrated with offline text-to-speech (en-IN)."),
         ("", ""),
         ("THE WORK", "Find → Trace → Verify → Act.")],
        "The platform, spoken through",
        "Every screen here is the served page, not a mock-up.")
    close = card(
        [("PURPOSE", "Bound before the search, in every audit row"),
         ("CAPABILITY", "Measured per camera; UNKNOWN is first class"),
         ("EVIDENCE", "Hash-chained; integrity and truthfulness apart"),
         ("REFUSAL", "A restriction is never reported as an absence")],
        "Evidence you can stand behind",
        "साक्ष्य · Saakshya — Gujarat Police Innovation Challenge 2026")

    for seg in segs:
        n = max(1, round(seg.hold_s * FPS))
        if seg.shot_index is None:
            img = intro if seg.title.startswith("Government") else close
        else:
            png = shots_dir / f"{seg.shot_index:02d}.png"
            step = Step(title=seg.title, caption=seg.text, action=lambda: None)
            img = compose(Shot(png=png, step=step))
        frames.extend([img] * n)
    encode(frames, out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shots", default="var/demo/walkthrough_live")
    ap.add_argument("--out", default="var/demo/walkthrough_live_narrated")
    a = ap.parse_args()

    if not say_available():
        print("no `say` on this host — cannot generate the voiceover. Nothing "
              "written, rather than a silent file that looks narrated.",
              file=sys.stderr)
        return 3
    shots = Path(a.shots)
    if not (shots / "00.png").exists():
        print(f"no screenshots in {shots}; run record_walkthrough.py first",
              file=sys.stderr)
        return 2

    ff = ffmpeg()
    out = Path(a.out)
    work = out.parent / "narration"
    print(f"narrating {display(shots)} with voice {VOICE} → {display(out)}.mp4")

    segs = generate(work, ff)
    total = sum(s.hold_s for s in segs)
    print(f"\nbuilding {total:.0f}s of video…")
    silent = work / "_silent.mp4"
    build_video(segs, shots, silent)
    audio = build_audio(ff, segs, work)

    subprocess.run(
        [ff, "-y", "-i", str(silent), "-i", str(audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
         str(out.with_suffix(".mp4"))], check=True, capture_output=True)

    size = out.with_suffix(".mp4").stat().st_size / 1e6
    print(f"\nnarrated video : {display(out.with_suffix('.mp4'))} "
          f"({total:.0f}s, {size:.1f} MB, voice {VOICE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
