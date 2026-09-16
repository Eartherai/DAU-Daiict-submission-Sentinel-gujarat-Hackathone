# Phase 8C browser certification

## Synthetic local control

**CERTIFIED for the tested local C-014 control path (re-verified 2026-09-16).**
This is not a government-camera certification.

### Measured path

```text
synthetic H.264 MP4 (Constrained Baseline, B-frames=0)
  -> MediaMTX RTSP/TCP publisher
  -> MediaMTX WHEP SDP POST
  -> ICE/DTLS
  -> Chromium RTCPeerConnection
  -> HTMLVideoElement + canvas pixel sample
```

### Evidence (`var/reports/phase8c/browser/C-014_nobf_soak.json`)

- WHEP negotiation: ~1.2 s to first decoded frame in the 12 s soak.
- Continuous playback: `currentTime` advanced to ~12.2 s.
- Inbound RTP: framesDecoded progressed 1 → 168 at ~15 FPS.
- ICE/DTLS: remained `connected` for the full soak.
- Packet loss / drops: 0 / 0 in the sampled reports.
- Codec: H.264 `profile-level-id=42e01f`, packetization-mode 1.
- Canvas mean luma: ~64–65 (non-black decoded pixels).
- Canvas PNG proof written by the harness (not the headless compositor screenshot).

### Root cause fixed on our side

MediaMTX closed WebRTC sessions with:

> WebRTC doesn't support H264 streams with B-frames

Synthetic H.264 clips and `make_media.py` now encode Constrained Baseline with
`-bf 0`. After that change, the 12 s soak no longer stalls.

### Harness notes

- Diagnostic Chromium is launched with `--disable-web-security` because the
  minimal player document is not same-origin with MediaMTX. Production UI uses
  the same-origin `/cameras/<id>/whep` signaling proxy and does not need that flag.
- UI `ontrack` now attaches `event.track` and calls `video.play()`.

## Government status

Government browser certification is **UNAVAILABLE** in this environment:

- `SENTINEL_GRID_EMAIL` / `SENTINEL_GRID_PASSWORD` are not present in the
  current process environment.
- No authenticated government gateway relay session was opened in this cycle.

Raw government RTSP/PyAV evidence from prior phases remains in
`var/reports/live30_live/` and is unchanged.

## Still pending

- Government cam01/cam02/cam05 through the same MediaMTX → WHEP → Chromium path
- HEVC (cam06/cam12) browser/transcode comparison
- AI-off vs AI-on browser overlay comparison
- Local 4/9/16/30 wall soaks
