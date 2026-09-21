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
        out = av.open(destination, mode="w", format="rtsp",
                      options={"rtsp_transport": "tcp"})
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
        # Readers join this long-running stream at arbitrary points.  Without
        # an explicit GOP VideoToolbox can publish indefinitely without a new
        # IDR, leaving WHEP/HLS sessions connected but permanently undecodable.
        # Keep the wall rendition low cadence and force a two-second IDR
        # interval for deterministic late joins.
        wall_time_base = Fraction(1, max(1, fps))
        output_stream.time_base = wall_time_base
        output_stream.codec_context.time_base = wall_time_base
        output_stream.codec_context.gop_size = max(2, fps * 2)
        output_stream.codec_context.max_b_frames = 0
        if codec == "libx264":
            output_stream.options = {
                "profile": "baseline", "bf": "0", "preset": "veryfast",
                "tune": "zerolatency", "g": str(max(10, fps * 2)),
            }
        else:
            output_stream.options = {
                "realtime": "1", "profile": "baseline", "bf": "0",
                "g": str(max(2, fps * 2)),
            }
        next_source_s: float | None = None
        wall_pts = 0
        for frame in inp.decode(stream):
            # ``rate=3`` configures the encoder timebase; it does not discard
            # the source's other ~22 frames each second.  Sample by source PTS
            # so we neither backlog nor manufacture a slow-motion wall.
            if frame.pts is not None and frame.time_base is not None:
                source_s = float(frame.pts * frame.time_base)
                if next_source_s is not None and source_s + 1e-6 < next_source_s:
                    continue
                next_source_s = source_s + (1.0 / max(1, fps))
            if frame.width != width or frame.height != height:
                frame = frame.reformat(width=width, height=height, format="yuv420p")
            frame.pts = wall_pts
            frame.time_base = wall_time_base
            wall_pts += 1
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
