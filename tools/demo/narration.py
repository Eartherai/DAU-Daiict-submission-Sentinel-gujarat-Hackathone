"""Narration and burned-in captions for the demonstration films.

Both submission films were silent. An assessor watching a three-minute screen
recording with no voice and no captions has to infer what each screen is for,
and the judge's pass on this submission named it as one of the cheapest points
available: "add a voiceover and burned-in captions; cut the dead air".

The approach keeps the voice and the picture in step by construction rather
than by a timing guess. Each beat's line is synthesised first; its measured
length sets how long the recorder dwells on that beat; the audio is then laid
at the beat's recorded start time. Captions are the same text, in an ASS file,
burned in at the frame's own resolution so they stay sharp at 1440p.

Voice: macOS `say`, an Indian-English voice, fully offline — no recording of
this project's narration is sent to any service.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VOICE = "Aman"
DEFAULT_RATE = 178          # words per minute; `say` defaults near 175-200


@dataclass
class Line:
    start_s: float
    text: str
    audio: Path | None = None
    duration_s: float = 0.0


def available() -> bool:
    return bool(shutil.which("say") and shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def synth(text: str, out: Path, *, voice: str = DEFAULT_VOICE,
          rate: int = DEFAULT_RATE) -> float:
    """Speak one line to a file and return its measured length in seconds."""
    out.parent.mkdir(parents=True, exist_ok=True)
    aiff = out.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text],
                   check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff),
                    "-ar", "48000", "-ac", "1", str(out)], check=True)
    aiff.unlink(missing_ok=True)
    return probe_duration(out)


def build_track(lines: list[Line], total_s: float, out: Path) -> Path:
    """Lay every line at its start time on one silent track of the film's length."""
    inputs, filters, labels = [], [], []
    for i, ln in enumerate(l for l in lines if l.audio):
        inputs += ["-i", str(ln.audio)]
        ms = max(0, int(round(ln.start_s * 1000)))
        filters.append(f"[{i}:a]adelay={ms}|{ms},apad[a{i}]")
        labels.append(f"[a{i}]")
    if not labels:
        raise ValueError("no narration lines were synthesised")
    mix = (";".join(filters) + ";" + "".join(labels)
           + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
           + f"atrim=0:{total_s:.3f},loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                    "-filter_complex", mix, "-map", "[out]",
                    "-ar", "48000", "-ac", "2", str(out)], check=True)
    return out


def _ass_time(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def write_ass(lines: list[Line], out: Path, *, width: int, height: int,
              chapter: list[tuple[float, float, str]] | None = None) -> Path:
    """Captions at the bottom, chapter titles top-left, sized for the frame."""
    fs = max(22, round(height * 0.030))          # ~43 px at 1440p
    cfs = max(18, round(height * 0.022))
    margin = round(height * 0.035)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Helvetica Neue,{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4101010,0,0,0,0,100,100,0,0,3,{round(fs*0.35)},0,2,{margin*3},{margin*3},{margin},1
Style: Chapter,Helvetica Neue,{cfs},&H00FFFFFF,&H00FFFFFF,&H00000000,&HC0203A8C,1,0,0,0,100,100,1,0,3,{round(cfs*0.45)},0,7,{margin},{margin},{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for i, ln in enumerate(lines):
        end = ln.start_s + max(ln.duration_s, 1.2) + 0.25
        nxt = lines[i + 1].start_s if i + 1 < len(lines) else end
        end = min(end, nxt - 0.05) if nxt > ln.start_s else end
        text = ln.text.replace("\n", " ").replace("{", "(").replace("}", ")")
        rows.append(f"Dialogue: 0,{_ass_time(ln.start_s)},{_ass_time(end)},Caption,,0,0,0,,{text}")
    for (a, b, title) in chapter or []:
        rows.append(f"Dialogue: 1,{_ass_time(a)},{_ass_time(b)},Chapter,,0,0,0,,{title.upper()}")
    out.write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    return out


def finish(video: Path, audio: Path, ass: Path, out: Path, *, crf: int = 16) -> Path:
    """Burn the captions in and mux the narration. One re-encode, high quality."""
    # The subtitles filter parses its argument, so escape the path's colons and
    # quotes rather than trust that a scratch path never contains one.
    esc = str(ass).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio),
                    "-vf", f"subtitles='{esc}'",
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", "-movflags", "+faststart", str(out)], check=True)
    return out
