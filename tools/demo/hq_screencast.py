"""High-quality browser capture via the Chrome DevTools Protocol.

Playwright's built-in `record_video` is convenient but has a hard ceiling: it
exposes only *mode* and *size*, with no control over codec, bitrate or frame
rate, and it encodes VP8. For a submission video that is watched once by an
assessor and judged on what they can read, that ceiling is worth stepping past.

`Page.startScreencast` hands us the frames the compositor actually presented,
each with its own timestamp. We keep them, then stitch with ffmpeg using the
real inter-frame intervals rather than assuming a constant rate. Two details
from the CDP documentation and from measurements by others matter:

* **Format.** The screencast defaults to JPEG at a low quality and the
  artifacts are visible on UI text. We ask for a high JPEG quality instead:
  PNG is lossless but a 2560x1440 frame is several megabytes, and a four-minute
  recording would be tens of gigabytes of disk and enough I/O to disturb the
  very video smoothness we are trying to capture.
* **Frames in flight.** Chromium drops screencast frames when acknowledgements
  lag. Each frame is acknowledged immediately on receipt, before it is written,
  so the browser is never waiting on our disk.

The result is a recording at the viewport's true resolution, stitched to the
timestamps the browser reported, and encoded once at high quality.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Screencast:
    """An open screencast. Use as a context manager around the driving code."""

    page: Any
    out_dir: Path
    width: int = 2560
    height: int = 1440
    #: 100 is wasteful for photographic content and invisible against 95 on UI.
    quality: int = 95
    _cdp: Any = field(default=None, repr=False)
    _frames: list[tuple[float, Path]] = field(default_factory=list, repr=False)
    _n: int = 0
    _paused_at: float | None = field(default=None, repr=False)
    _paused_s: float = 0.0
    _accept_after: float = 0.0
    _ended_at: float | None = field(default=None, repr=False)

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause(self) -> None:
        """Exclude content preparation from both frames and the output clock."""
        if self._paused_at is None:
            self._paused_at = time.time()
            self._cdp.send("Page.stopScreencast")

    def resume(self) -> None:
        if self._paused_at is not None:
            now = time.time()
            self._paused_s += now - self._paused_at
            self._accept_after = now
            self._paused_at = None
            self._start()

    def timeline_time(self) -> float:
        """Epoch-like capture time, matching the timestamps stored for frames."""
        return (self._paused_at if self._paused_at is not None else time.time()) - self._paused_s

    def _start(self) -> None:
        self._cdp.send("Page.startScreencast", {
            "format": "jpeg", "quality": self.quality,
            "maxWidth": self.width, "maxHeight": self.height,
            "everyNthFrame": 1,
        })

    def __enter__(self) -> Screencast:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for stale in self.out_dir.glob("f_*.jpg"):
            stale.unlink()
        self._cdp = self.page.context.new_cdp_session(self.page)
        self._cdp.on("Page.screencastFrame", self._on_frame)
        self._start()
        return self

    def _on_frame(self, params: dict) -> None:
        # Acknowledge first: Chromium stops sending while an ack is outstanding,
        # so any work done before this point is throughput lost.
        try:
            self._cdp.send("Page.screencastFrameAck",
                           {"sessionId": params["sessionId"]})
        except Exception:
            return
        if self._paused_at is not None:
            return
        meta = params.get("metadata") or {}
        raw_ts = float(meta.get("timestamp") or time.time())
        if raw_ts < self._accept_after:
            return  # A queued frame from before resume must not enter this beat.
        ts = raw_ts - self._paused_s
        path = self.out_dir / f"f_{self._n:06d}.jpg"
        try:
            path.write_bytes(base64.b64decode(params["data"]))
        except Exception:
            return
        self._frames.append((ts, path))
        self._n += 1

    def __exit__(self, *exc: object) -> None:
        self._ended_at = self.timeline_time()
        try:
            self._cdp.send("Page.stopScreencast")
        except Exception:
            pass

    # -- assembly ---------------------------------------------------------- #

    def frame_count(self) -> int:
        return len(self._frames)

    def first_timestamp(self) -> float | None:
        """Wall-clock time of the first captured frame, for aligning narration.

        The stitched video starts at this frame, not at the moment recording
        was requested, so anything timed from the request - a voiceover line,
        a caption - must be shifted by the difference or it leads the picture.
        """
        return self._frames[0][0] if self._frames else None

    def measured_fps(self) -> float | None:
        if len(self._frames) < 2:
            return None
        span = self._frames[-1][0] - self._frames[0][0]
        return (len(self._frames) - 1) / span if span > 0 else None

    def write(self, mp4: Path, *, crf: int = 18, fps: int = 30) -> dict:
        """Stitch the captured frames into an mp4.

        The concat demuxer is given each frame's real duration, so a moment the
        browser rendered slowly stays slow rather than being silently sped up.
        """
        if not self._frames:
            return {"ok": False, "why": "no frames captured"}
        if not shutil.which("ffmpeg"):
            return {"ok": False, "why": "ffmpeg not on PATH"}

        listing = self.out_dir / "frames.txt"
        lines: list[str] = []
        for i, (ts, path) in enumerate(self._frames):
            lines.append(f"file '{path.name}'")
            if i + 1 < len(self._frames):
                dur = max(0.001, self._frames[i + 1][0] - ts)
                lines.append(f"duration {dur:.6f}")
            elif self._ended_at is not None:
                # A static final screen may emit no further compositor frames.
                # Preserve its actual held duration, including the narration.
                lines.append(f"duration {max(0.001, self._ended_at - ts):.6f}")
        # The concat demuxer ignores the final entry's duration unless the last
        # file is repeated, which is the documented idiom.
        lines.append(f"file '{self._frames[-1][1].name}'")
        listing.write_text("\n".join(lines), encoding="utf-8")

        mp4.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(listing),
            "-vsync", "cfr", "-r", str(fps),
            "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(mp4),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"ok": False, "why": proc.stderr.strip()[-300:]}
        return {
            "ok": True,
            "frames": len(self._frames),
            "captured_fps": round(self.measured_fps() or 0.0, 1),
            "mb": round(mp4.stat().st_size / 1048576, 1),
        }

    def cleanup(self) -> None:
        for _, path in self._frames:
            try:
                path.unlink()
            except OSError:
                pass
        listing = self.out_dir / "frames.txt"
        if listing.exists():
            listing.unlink()


def probe(mp4: Path) -> dict:
    """What actually landed on disk, for reporting rather than assuming."""
    if not shutil.which("ffprobe"):
        return {}
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,nb_frames",
         "-show_entries", "format=duration,size",
         "-of", "json", str(mp4)], capture_output=True, text=True)
    try:
        d = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}
    st = (d.get("streams") or [{}])[0]
    fmt = d.get("format") or {}
    rate = st.get("avg_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        fps = round(int(num) / int(den), 1) if int(den) else 0.0
    except Exception:
        fps = 0.0
    return {
        "width": st.get("width"), "height": st.get("height"), "fps": fps,
        "duration_s": round(float(fmt.get("duration") or 0), 1),
        "mb": round(int(fmt.get("size") or 0) / 1048576, 1),
    }
