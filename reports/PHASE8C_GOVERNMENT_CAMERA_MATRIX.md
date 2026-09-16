# Phase 8C government camera matrix

Updated after authenticated cam01 gateway/WHEP/browser certification
(2026-09-16). Credentials were injected via process environment only and were
not written into this report.

| Camera | Raw RTSP/PyAV | Gateway (local MediaMTX) | WHEP | RTP | Browser | Overlay | First failure / conclusion |
|---|---|---|---|---|---|---|---|
| cam01 | VERIFIED GREEN (30 frames, H.264 1920x1080, has_b_frames=false) | VERIFIED — RTSP republish to `stream/gov-cam01` | VERIFIED local WHEP | VERIFIED continuous | VERIFIED 12 s soak | PARTIAL — canvas pixel proof only; AI overlay not run | **PASS on managed gateway path** |
| cam02 | VERIFIED GREEN (prior raw) | UNAVAILABLE this cycle | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Next candidate after cam01 |
| cam05 | VERIFIED GREEN (prior raw) | UNAVAILABLE this cycle | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Next candidate after cam01 |
| cam03 | VERIFIED AMBER; raw frame already degraded | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Raw already degraded; later layers unverified |
| cam06 | VERIFIED GREEN HEVC | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | HEVC browser/transcode still required |
| cam12 | VERIFIED GREEN HEVC | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | HEVC browser/transcode still required |
| cam18 | INTERMITTENT raw | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Startup/session candidate |
| cam22 | INTERMITTENT raw | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Startup/session candidate |

## cam01 browser soak evidence

Artifact: `var/reports/phase8c/gov/cam01_whep.json` (+ canvas PNG)

- Endpoint tested: `http://127.0.0.1:8889/stream/gov-cam01/whep` (local gateway only)
- Status: MEASURED
- Resolution: 1920x1080
- First decoded frame: ~1.5 s
- `currentTime` advanced to ~12.1 s
- framesDecoded progressed continuously (~1 → 169)
- DTLS remained connected; packetsLost=0; framesDropped=0
- Canvas mean luma ~97 (non-black)
- Canvas PNG shows Chimanbhai Bridge night traffic with camera overlay text

## Architecture note

```text
Government cam01 RTSP/TCP (authenticated in process)
  -> local MediaMTX path stream/gov-cam01
  -> WHEP
  -> Chromium decode + canvas sample
```

Browser never received government credentials. Direct government WHEP from the
browser remains disallowed.

## External support email

Not justified for cam01. The managed gateway path works on our side.
