"""High-fidelity screen capture for submission films.

Playwright's VP8 webm is the quality ceiling of the old films: ffmpeg cannot
invent detail that was never recorded. This pipes JPEG screenshots of the real
Chrome viewport into libx264 at CRF 15, so the file is the interface at 1080p.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

CURSOR_JS = """() => {
  if (document.getElementById('saakshya-cursor')) return;
  const d = document.createElement('div');
  d.id = 'saakshya-cursor';
  d.style.cssText = 'position:fixed;left:40px;top:40px;width:20px;height:20px;'
    + 'border-radius:50%;border:2px solid #a8502b;background:rgba(168,80,43,.4);'
    + 'pointer-events:none;z-index:2147483647;transform:translate(-30%,-30%);'
    + 'box-shadow:0 0 0 3px rgba(255,255,255,.85)';
  document.body.appendChild(d);
  window.addEventListener('mousemove', (e) => {
    d.style.left = e.clientX + 'px';
    d.style.top = e.clientY + 'px';
  }, true);
}"""


class JpegFilm:
    """One 1920×1080 JPEG per tick, encoded as we go."""

    def __init__(self, page, dest: Path, ff: str, *,
                 fps: int = 10, quality: int = 90):
        self.page = page
        self.dest = Path(dest)
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.quality = quality
        self._interval = 1.0 / fps
        self._n = 0
        self._err = open(self.dest.with_suffix(".ffmpeg.log"), "wb")
        self.proc = subprocess.Popen(
            [ff, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "image2pipe", "-framerate", str(fps),
             "-vcodec", "mjpeg", "-i", "-",
             "-an",
             "-vf", "scale=1920:1080:flags=lanczos,fps=" + str(fps),
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-preset", "slow", "-crf", "12",
             "-profile:v", "high", "-level", "4.2",
             "-x264-params", "ref=4:bframes=2:aq-mode=3",
             "-movflags", "+faststart",
             str(self.dest)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._err)
        if self.proc.stdin is None:
            raise SystemExit("ffmpeg stdin missing")

    def tick(self) -> None:
        jpeg = self.page.screenshot(
            type="jpeg", quality=self.quality,
            clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
        try:
            self.proc.stdin.write(jpeg)
            self.proc.stdin.flush()
        except BrokenPipeError as exc:
            err = b""
            try:
                err = self.proc.stderr.read() if self.proc.stderr else b""
            except Exception:
                pass
            raise SystemExit(
                "ffmpeg died while recording:\n"
                + err.decode("utf-8", "replace")[-1500:]) from exc
        self._n += 1

    def hold(self, ms: int) -> None:
        if ms <= 0:
            return
        deadline = time.monotonic() + ms / 1000.0
        while True:
            t0 = time.monotonic()
            self.tick()
            remain = deadline - time.monotonic()
            if remain <= 0:
                break
            wait = self._interval - (time.monotonic() - t0)
            if wait > 0.004:
                time.sleep(min(wait, remain))

    def close(self) -> Path:
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            rc = self.proc.wait(timeout=180)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            rc = self.proc.wait()
        try:
            self._err.close()
        except Exception:
            pass
        err = ""
        logp = self.dest.with_suffix(".ffmpeg.log")
        if logp.is_file():
            err = logp.read_text(errors="replace")[-1500:]
        if rc != 0:
            raise SystemExit(f"ffmpeg encode failed ({rc}):\n{err}")
        if not self.dest.is_file() or self.dest.stat().st_size < 50_000:
            raise SystemExit("ffmpeg wrote no usable picture")
        print(f"picture {self.dest.name}: {self._n} frames, "
              f"{self.dest.stat().st_size / 1e6:.1f} MB", flush=True)
        return self.dest


class ScreencastFilm:
    """Chrome compositor screencast → H264 at a measured frame rate.

    Playwright JPEG screenshots cannot sustain 30 FPS on this machine (the
    previous film was 12 FPS because that was the capture loop, not the
    encoder). CDP Page.startScreencast streams compositor frames; ffmpeg
    records them as they arrive. ffprobe must still be used to report the
    actual avg_frame_rate — we do not label a slow capture as 30 FPS.
    """

    def __init__(self, page, dest: Path, ff: str, *, fps: int = 30, quality: int = 80):
        import base64
        import queue
        import threading
        self._b64 = base64
        self.page = page
        self.dest = Path(dest)
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.quality = quality
        self._n = 0
        self._latest: bytes | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._err = open(self.dest.with_suffix(".ffmpeg.log"), "wb")
        self.proc = subprocess.Popen(
            [ff, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "image2pipe", "-framerate", str(fps),
             "-vcodec", "mjpeg", "-i", "-",
             "-an",
             "-vsync", "cfr",
             "-r", str(fps),
             "-vf", "scale=1920:1080:flags=lanczos",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-preset", "veryfast", "-crf", "18",
             "-profile:v", "high", "-level", "4.2",
             "-movflags", "+faststart",
             str(self.dest)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._err)
        if self.proc.stdin is None:
            raise SystemExit("ffmpeg stdin missing")
        self._cdp = page.context.new_cdp_session(page)
        self._cdp.on("Page.screencastFrame", self._on_frame)
        self._cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": quality,
            "maxWidth": 1920,
            "maxHeight": 1080,
            "everyNthFrame": 1,
        })
        self._writer = threading.Thread(target=self._pump, name="screencast-pump", daemon=True)
        self._writer.start()
        self._q = queue

    def _on_frame(self, params: dict) -> None:
        try:
            raw = self._b64.b64decode(params.get("data") or "")
            with self._lock:
                self._latest = raw
                self._n += 1
            sid = params.get("sessionId")
            if sid is not None:
                self._cdp.send("Page.screencastFrameAck", {"sessionId": sid})
        except Exception:
            pass

    def _pump(self) -> None:
        interval = 1.0 / max(1, self.fps)
        last = b""
        while not self._stop.is_set():
            t0 = time.monotonic()
            with self._lock:
                blob = self._latest
            if blob:
                try:
                    self.proc.stdin.write(blob)
                    self.proc.stdin.flush()
                except BrokenPipeError:
                    break
            wait = interval - (time.monotonic() - t0)
            if wait > 0.002:
                self._stop.wait(wait)

    def tick(self) -> None:
        return

    def hold(self, ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000.0)

    def close(self) -> Path:
        self._stop.set()
        try:
            self._cdp.send("Page.stopScreencast")
        except Exception:
            pass
        try:
            self._writer.join(timeout=2.0)
        except Exception:
            pass
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            rc = self.proc.wait(timeout=180)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            rc = self.proc.wait()
        try:
            self._err.close()
        except Exception:
            pass
        err = ""
        logp = self.dest.with_suffix(".ffmpeg.log")
        if logp.is_file():
            err = logp.read_text(errors="replace")[-1500:]
        if rc != 0:
            raise SystemExit(f"ffmpeg encode failed ({rc}):\n{err}")
        if not self.dest.is_file() or self.dest.stat().st_size < 50_000:
            raise SystemExit("ffmpeg wrote no usable picture")
        print(f"screencast {self.dest.name}: {self._n} compositor frames, "
              f"target {self.fps} fps, {self.dest.stat().st_size / 1e6:.1f} MB",
              flush=True)
        return self.dest
