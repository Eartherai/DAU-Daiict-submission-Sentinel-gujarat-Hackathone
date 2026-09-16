# Government feed issue report

## Status

A concurrent 30-camera probe was run at **2026-09-15 23:55 UTC** with one
bounded RTSP attempt per registered camera. All `cam01`–`cam30` attempts
returned **HTTP 401 Unauthorized** before a video stream could be opened.
This currently classifies as **access/credential configuration**, not as proof
that the government encoders or network are defective.

The available browser preview files were also inspected separately. They are
about 29.96 hours old and several contain visible green or block-corrupted
regions, but they are stale stored previews and cannot be used to diagnose the
current upstream feed.

## Evidence required before submission

- affected camera IDs and UTC timestamps;
- protocol, codec, resolution, pixel format, and keyframe interval;
- RTSP/PyAV diagnostic output;
- gateway/WebRTC or HLS comparison;
- browser `getStats()` output and screenshots;
- known-good own-feed control using the same player;
- reconnect and recovery timings.

After credentials are corrected, repeat the same comparison. Only if a
camera fails after authenticated direct decode and a known-good control works
with the same client should the result be described as evidence that the issue
persists upstream of browser rendering.
