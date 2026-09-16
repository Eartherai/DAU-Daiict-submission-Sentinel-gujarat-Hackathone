# Phase 8B frame-path matrix

Phase 8B tested the existing local MediaMTX path as a synthetic control and
did not fabricate government gateway/browser outcomes.

| Camera | Raw RTSP | Gateway | WHEP SDP | Browser/ICE | Browser media | First failure layer | Conclusion |
|---|---|---|---|---|---|---|---|
| local C-014 control | VERIFIED: H.264 1280x720, 60 frames/5 s | VERIFIED: MediaMTX path ready | VERIFIED: POST returned 201 and SDP answer | VERIFIED: ICE connected | UNAVAILABLE: no decoded frame in 5 s; blank screenshot | Browser media/transport remains unresolved | Synthetic control proves gateway signaling, not browser playback |
| cam01 | VERIFIED: GREEN raw evidence | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Gateway not configured | No browser conclusion |
| cam03 | VERIFIED: AMBER raw evidence | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Gateway not configured | Raw RTSP/PyAV frame is already degraded; later stages unverified |
| cam06 | VERIFIED: GREEN HEVC raw evidence | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Gateway not configured | Browser HEVC compatibility unverified |
| cam12 | VERIFIED: GREEN HEVC raw evidence | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Gateway not configured | Browser HEVC compatibility unverified |
| cam18 | VERIFIED: intermittent/no-frame raw evidence | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Gateway not configured | Raw startup/session/keyframe candidate; no attribution |
| cam22 | VERIFIED: intermittent/no-frame raw evidence | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Gateway not configured | Raw startup/session/keyframe candidate; no attribution |

## Evidence boundary

The local MediaMTX control used synthetic `C-014` media and is not evidence
about the government source. No authenticated government gateway endpoint,
WHEP proxy session, or browser-accessible route was configured. Therefore no
government camera is marked browser LIVE, smooth, low-latency, or certified.
