# Phase 8C final live path

## Measured local path

```text
synthetic H.264 MP4
  -> MediaMTX RTSP/TCP
  -> MediaMTX WHEP SDP POST
  -> ICE/DTLS
  -> Chromium RTCPeerConnection
  -> HTMLVideoElement + decoded-pixel canvas sample
```

This path is verified on local synthetic C-014. The project’s existing
MediaMTX architecture is retained; no competing gateway was introduced.

## Browser implementation fixes

- Attach remote `event.track` directly, while retaining stream metadata.
- Explicitly call `video.play()` after the remote description.
- Iterate `RTCStatsReport.values()` rather than entry tuples.
- Capture lifecycle events and bounded stats.
- Refuse credential-bearing endpoint arguments.
- Redact SDP connection secrets before persistence.

## Government transition gate

Only after a configured authenticated gateway is available should the same
harness be run for cam01, cam02, cam05, one HEVC camera, cam03, and cam18.
The current government result is therefore:

- RAW: measured in prior phases.
- Gateway/WHEP/RTP/browser/overlay: unavailable.
- External attribution: not established.

The local control proves the browser/media stack can decode a valid H.264
WHEP stream. It does not prove any government camera’s browser behavior.
