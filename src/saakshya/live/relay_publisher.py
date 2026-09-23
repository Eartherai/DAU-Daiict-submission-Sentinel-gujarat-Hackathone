"""Credential-safe RTSP publisher for the local media relay.

The parent relay deliberately passes a clean Sentinel URL in argv.  This
process adds the environment-only credential immediately before PyAV opens the
upstream connection, then publishes clean H.264 (or a packet copy) to the
loopback-only MediaMTX instance.  Do not log an upstream URL without redacting
it first.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from fractions import Fraction

import av
from av.video.frame import PictureType

from saakshya.live.credentials import credentialed, needs_grid_credential, redact

AUTH_BACKOFF_S = 300.0
#: A pool of publishers shares one Sentinel identity, so an admission
#: refusal arrives for all of them within seconds.  An unjittered backoff
#: makes the whole pool go dark and come back in lockstep, which is what a
#: fifteen-camera hole in the wall every five minutes actually is.  Spread
#: the retries so the account is re-approached gradually instead of at once.
AUTH_BACKOFF_JITTER = (0.7, 1.45)
#: Every retry against a locked identity is itself an admission attempt,
#: and the grid counts it — so a fixed five-minute retry does not wait out
#: a lockout, it sustains one.  Double the wait per consecutive refusal up
#: to this multiple of the base, then hold there until the account answers.
AUTH_BREAKER_MAX_SCALE = 6
#: Decode the upstream on the GPU. Software-decoding thirty 1080p30 sources is
#: what actually caps this wall: the decode falls behind real time, the RTSP
#: socket backs up, and the grid resets the connection for reading too slowly -
#: which surfaces as ConnectionResetError and BrokenPipeError rather than as
#: CPU saturation, and is why fifteen cameras were stable where thirty were
#: not. VideoToolbox moves that cost off the CPU. Falls back to software
#: automatically, so an unsupported parameter set costs one camera, not the
#: wall. Set SAAKSHYA_RELAY_HWACCEL=0 to disable.
HWACCEL = os.environ.get("SAAKSHYA_RELAY_HWACCEL", "1").strip().lower() not in {
    "0", "false", "off", "no"}


def _hwaccel():
    """A VideoToolbox decode context, or None where it is unavailable."""
    if not HWACCEL:
        return None
    try:
        from av.codec.hwaccel import HWAccel
        return HWAccel("videotoolbox", allow_software_fallback=True)
    except Exception:
        return None


#: Output clock. RTP carries H.264 at 90 kHz, and so does every consumer of
#: the local RTSP; a 1/fps counter could only ever say "the next frame".
OUTPUT_CLOCK = 90_000
#: Seconds of source time between forced IDRs. A late joiner - a tile that
#: scrolls into view, the AI worker reconnecting - waits for the next IDR
#: before it can decode anything, so this bounds that wait.
IDR_INTERVAL_S = float(os.environ.get("SAAKSHYA_RELAY_IDR_S", "1.0"))
#: A source clock that jumps further than this, either way, has been reset
#: (camera reboot, gateway reconnect), not merely jittered.
DISCONTINUITY_S = 5.0


class WallTimebase:
    """Map source PTS onto the published stream, and decide IDRs by time.

    The publisher used to stamp its output with a frame counter at 1/fps and
    force an IDR every ``fps * 2`` frames. Both assume the source delivers the
    nominal rate, and on this grid it does not: measured delivery runs from 4
    to 30 fps, several cameras at 3.7-5.9 under load. A camera sending 4 fps
    into a 12 fps counter was published playing three times too fast, then
    starving; its 24-frame GOP became six seconds of wall time, which is what
    MediaMTX logged as "segment duration changed from 2s to 3s" and what a
    late-joining tile spent staring at a frozen still. Anything downstream -
    the AI worker's dwell, speed and trajectory - inherited invented time.

    Here output PTS is source time since the first frame at 90 kHz, clamped
    to stay monotonic, and an IDR is due once a second of *source time* has
    passed since the last one, however many frames that took. Pure: it never
    touches a codec, so it is tested on its own.
    """

    def __init__(self, fps: int, *, idr_interval_s: float = IDR_INTERVAL_S,
                 clock: int = OUTPUT_CLOCK) -> None:
        self.min_gap_s = 1.0 / max(1, fps)
        self.idr_interval_s = max(0.1, idr_interval_s)
        self.clock = clock
        self._origin: float | None = None  # source seconds mapped to output 0
        self._offset = 0  # output ticks added after a discontinuity rebase
        self._last_source: float | None = None
        self._next_admit: float | None = None
        self._last_idr: float | None = None
        self.last_pts: int | None = None
        self.rebases = 0

    def admit(self, source_s: float) -> bool:
        """Whether this source frame is published at the wall cadence."""
        if self._jumped(source_s):
            self._rebase(source_s)
        if self._next_admit is not None and source_s + 1e-6 < self._next_admit:
            return False
        self._next_admit = source_s + self.min_gap_s
        return True

    def stamp(self, source_s: float) -> tuple[int, bool]:
        """Output PTS in ``clock`` ticks, and whether to force an IDR."""
        if self._jumped(source_s):
            self._rebase(source_s)
        if self._origin is None:
            self._origin = source_s
        pts = self._offset + round((source_s - self._origin) * self.clock)
        if self.last_pts is not None and pts <= self.last_pts:
            pts = self.last_pts + 1
        self.last_pts = pts
        self._last_source = source_s
        keyframe = (self._last_idr is None
                    or source_s - self._last_idr >= self.idr_interval_s - 1e-6)
        if keyframe:
            self._last_idr = source_s
        return pts, keyframe

    def _jumped(self, source_s: float) -> bool:
        return (self._last_source is not None
                and abs(source_s - self._last_source) > DISCONTINUITY_S)

    def _rebase(self, source_s: float) -> None:
        # Continue the output one frame after where it was, rather than
        # clamping every later frame to last_pts + 1 (a backwards jump) or
        # publishing a gap of minutes (a forwards one).
        self.rebases += 1
        step = round(self.min_gap_s * self.clock)
        self._offset = (self.last_pts or 0) + step
        self._origin = source_s
        self._next_admit = None
        self._last_idr = None
        self._last_source = source_s


def _publish_destination(destination: str) -> str:
    """The loopback destination with the relay's per-boot publish credential.

    The relay's MediaMTX refuses anonymous publishers, so a publisher without
    this cannot write its path. It arrives by environment, like the grid
    credential, so it never appears in a process list.
    """
    user = os.environ.get("SAAKSHYA_RELAY_PUBLISH_USER", "")
    password = os.environ.get("SAAKSHYA_RELAY_PUBLISH_PASS", "")
    if not user or not password:
        return destination
    from urllib.parse import quote
    scheme, sep, rest = destination.partition("://")
    if not sep or "@" in rest.split("/", 1)[0]:
        return destination
    return f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}@{rest}"


def _encoder(*, software: bool = False) -> str:
    """Prefer the local hardware encoder but retain a portable fallback."""
    if software:
        return "libx264"
    try:
        av.codec.Codec("h264_videotoolbox", "w")
        return "h264_videotoolbox"
    except Exception:
        return "libx264"


def _copy_or_transcode(source: str, destination: str, mode: str,
                       bitrate: str, max_height: int, fps: int,
                       *, software: bool = False) -> None:
    """Publish until the upstream ends; callers apply reconnect backoff."""
    upstream = credentialed(source, required=needs_grid_credential(source))
    inp = None
    out = None
    try:
        is_rtsp = upstream.startswith(("rtsp://", "rtsps://"))
        # PyAV accepts these protocol options for RTSP only.  Passing them to
        # an own-feed file can leave the local replay opening indefinitely on
        # some FFmpeg builds, so keep the replay path protocol-neutral.
        input_options = ({"rtsp_transport": "tcp", "stimeout": "8000000"}
                         if is_rtsp else {})
        open_kwargs = {}
        accel = _hwaccel() if is_rtsp else None
        if accel is not None:
            open_kwargs["hwaccel"] = accel
        try:
            inp = av.open(upstream, options=input_options,
                          timeout=20.0 if is_rtsp else None, **open_kwargs)
        except Exception:
            # A hardware decoder that refuses this stream must cost one camera,
            # never the wall: retry once on the software path before giving up.
            if not open_kwargs:
                raise
            inp = av.open(upstream, options=input_options,
                          timeout=20.0 if is_rtsp else None)
        stream = next(s for s in inp.streams if s.type == "video")
        # A packet copy is only as browser-safe as its source. Part of the grid
        # serves HEVC, which no browser will take over WebRTC, and which camera
        # serves what is not knowable until the stream is open - a hardcoded
        # list of HEVC cameras was silently wrong in both directions. Decide
        # from the stream itself: copy H.264, transcode anything else.
        source_codec = (getattr(stream.codec_context, "name", "") or "").lower()
        if mode == "copy" and source_codec != "h264":
            print(f"publisher source codec {source_codec or 'unknown'}: "
                  f"not browser-safe for packet copy, transcoding",
                  file=sys.stderr, flush=True)
            mode = "transcode"
        # The relay always publishes RTSP. A file destination is accepted so
        # the timing of what this function publishes can be read back and
        # tested without a media server.
        if destination.startswith(("rtsp://", "rtsps://")):
            out = av.open(_publish_destination(destination), mode="w",
                          format="rtsp", options={"rtsp_transport": "tcp"})
        else:
            out = av.open(destination, mode="w")
        if mode == "copy":
            output_stream = out.add_stream_from_template(stream)
            for packet in inp.demux(stream):
                if packet.dts is None:
                    continue
                packet.stream = output_stream
                out.mux(packet)
            return

        codec = _encoder(software=software)
        output_stream = out.add_stream(codec, rate=max(1, fps))
        source_width = int(stream.codec_context.width)
        source_height = int(stream.codec_context.height)
        width, height = _wall_geometry(source_width, source_height, max_height)
        output_stream.width = width
        output_stream.height = height
        output_stream.pix_fmt = "yuv420p"
        output_stream.bit_rate = _bitrate(bitrate)
        # Readers join this long-running stream at arbitrary points, and each
        # waits for an IDR before it can decode. The IDR cadence is therefore
        # set in source *time* by WallTimebase, one a second, with the GOP
        # size kept only as a ceiling: counted in frames it stretched to
        # three to six seconds on a camera delivering four frames a second.
        timebase = WallTimebase(fps)
        out_time_base = Fraction(1, OUTPUT_CLOCK)
        output_stream.time_base = out_time_base
        output_stream.codec_context.time_base = out_time_base
        gop_ceiling = max(30, fps * 4)
        output_stream.codec_context.gop_size = gop_ceiling
        output_stream.codec_context.max_b_frames = 0
        if codec == "libx264":
            output_stream.options = {
                "profile": "baseline", "bf": "0", "preset": "veryfast",
                "tune": "zerolatency", "g": str(gop_ceiling),
                "forced-idr": "1",
            }
        else:
            output_stream.options = {
                "realtime": "1", "profile": "baseline", "bf": "0",
                "g": str(gop_ceiling),
            }
        wall_start = time.monotonic()
        for frame in inp.decode(stream):
            # ``rate=fps`` configures the encoder; it does not discard the
            # source's other frames. Sample by source PTS so we neither
            # backlog nor manufacture a slow-motion wall. A frame with no
            # PTS is timed by arrival, which is the best truth left.
            if frame.pts is not None and frame.time_base is not None:
                source_s = float(frame.pts * frame.time_base)
            else:
                source_s = time.monotonic() - wall_start
            if not timebase.admit(source_s):
                continue
            if frame.width != width or frame.height != height:
                frame = frame.reformat(width=width, height=height, format="yuv420p")
            pts, keyframe = timebase.stamp(source_s)
            frame.pts = pts
            frame.time_base = out_time_base
            frame.pict_type = PictureType.I if keyframe else PictureType.NONE
            for packet in output_stream.encode(frame):
                out.mux(packet)
        for packet in output_stream.encode(None):
            out.mux(packet)
    finally:
        if out is not None:
            out.close()
        if inp is not None:
            inp.close()


def _bitrate(value: str) -> int:
    text = (value or "800k").strip().lower()
    try:
        return int(float(text[:-1]) * 1000) if text.endswith("k") else int(text)
    except ValueError:
        return 800_000


def _wall_geometry(width: int, height: int, max_height: int) -> tuple[int, int]:
    """Preserve aspect ratio and encoder-required even dimensions."""
    if max_height <= 0 or height <= max_height:
        return width - (width % 2), height - (height % 2)
    scaled_width = int(width * (max_height / height))
    return max(2, scaled_width - (scaled_width % 2)), max_height - (max_height % 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--mode", choices=("copy", "transcode"), required=True)
    parser.add_argument("--bitrate", default="800k")
    parser.add_argument("--max-height", type=int, default=0,
                        help="optional local wall rendition cap; source is untouched")
    parser.add_argument("--fps", type=int, default=5,
                        help="wall rendition cadence; source timestamps remain upstream truth")
    args = parser.parse_args()

    backoff = 2.0
    #: Consecutive admission refusals. Reset by any successful upstream open.
    auth_failures = 0
    # VideoToolbox is the normal 30-wall encoder on this machine.  A handful
    # of unusual source parameter sets can make its open call reject the
    # stream; fall back only for that publisher rather than failing its tile
    # forever or forcing all cameras onto CPU encoding.
    software = False
    while True:
        try:
            _copy_or_transcode(args.source, args.destination, args.mode,
                               args.bitrate, args.max_height, args.fps,
                               software=software)
            backoff = 2.0
            auth_failures = 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            # PyAV exception messages can include the authenticated upstream
            # URL.  Preserve the diagnostic class, but never the authority.
            print(f"upstream {type(exc).__name__}: {redact(str(exc))[:240]}",
                  file=sys.stderr, flush=True)
            if (not software and args.mode == "transcode"
                    and "h264_videotoolbox" in str(exc).lower()):
                software = True
                print("publisher encoder fallback: libx264", file=sys.stderr,
                      flush=True)
            # A 401 means upstream admission/authentication rejected this
            # handshake.  Retrying every few seconds fans that into a wall-wide
            # lockout; leave the account time to recover before one new try.
            if "unauthorized" in str(exc).lower() or " 401" in str(exc):
                auth_failures += 1
                scale = min(AUTH_BREAKER_MAX_SCALE, 2 ** (auth_failures - 1))
                backoff = max(backoff, AUTH_BACKOFF_S * scale
                              * random.uniform(*AUTH_BACKOFF_JITTER))
                print(f"publisher authentication backoff {backoff:.0f}s "
                      f"(consecutive refusals: {auth_failures})",
                      file=sys.stderr, flush=True)
        time.sleep(backoff)
        backoff = min(30.0, backoff * 1.5)


if __name__ == "__main__":
    raise SystemExit(main())
