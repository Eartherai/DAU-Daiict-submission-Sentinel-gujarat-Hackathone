# Phase 8C local media root cause

## Result

Two independent local failures were identified and fixed.

### 1. Diagnostic harness / CORS

A blank `about:blank` document is a null origin, so the browser `fetch` to the
MediaMTX WHEP endpoint fails even when `webrtcAllowOrigins: ["*"]` is set.
The certification harness therefore launches Chromium with
`--disable-web-security` for local diagnostics only. Production UI already uses
the same-origin `/cameras/<id>/whep` proxy.

Headless compositor screenshots can remain black while the video element has
pixels. The harness now persists a canvas PNG sampled from the decoded frame.

### 2. MediaMTX B-frame rejection (playback freeze)

After a successful first-frame decode, MediaMTX closed the WebRTC session with:

```text
WebRTC doesn't support H264 streams with B-frames
```

Observed effect: ~1 s of video, DTLS `closed`, framesDecoded stuck near 16,
`currentTime` frozen near 1.07. This matches the operator-visible freeze.

Fix: re-encode synthetic H.264 sources as Constrained Baseline with
`bframes=0`, and update `tools/sandbox/make_media.py` so future corpus builds
stay WebRTC-safe. After the fix, a 12 s soak kept DTLS connected and advanced
framesDecoded continuously at ~15 FPS with zero loss/drops.

## Verified path

| Layer | Result | Evidence |
|---|---|---|
| Synthetic source | PASS | C-014 H.264 Constrained Baseline, `has_b_frames=False` |
| MediaMTX RTSP | PASS | path ready; publisher online |
| WHEP SDP POST | PASS | HTTP 201 / negotiated answer H.264 PT 108 |
| ICE/DTLS | PASS | connected for full 12 s soak |
| RTP | PASS | packets/frames increase continuously; 0 loss |
| Browser decode | PASS | readyState=4, 1280x720, currentTime≈12.2 |
| Pixel output | PASS | canvas mean luma ~64–65; canvas PNG saved |

## Government implication

Any government H.264 feed that includes B-frames will hit the same MediaMTX
WebRTC close unless the managed gateway transcodes to baseline/`bf=0` (or
another browser-safe profile) before WHEP fan-out. Do not attribute that class
of freeze to "bad government video" until the no-B-frame gateway path is tested.
