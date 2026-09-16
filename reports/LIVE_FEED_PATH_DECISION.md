# Live feed path decision

## Current decision

Use **selected-camera WHEP/WebRTC as the preferred path**, with ingest snapshots
as the visible fallback. This is a provisional engineering decision until the
authenticated government catalogue is available for a controlled RTSP, HLS,
WebRTC, and transcoded-H.264 comparison.

The decision is based on architecture rather than an invented latency claim:
the wall does not open one upstream stream per tile, the browser receives a
stream only after an operator selects a camera, and the fallback cannot leave a
black stage when WHEP is unavailable. The browser telemetry drawer records the
actual startup, decoded-frame, packet, jitter, codec, and reconnect values.

## What remains unverified

No reliable measured winner can yet be declared among direct RTSP, gateway
WebRTC, HLS, and transcoded WebRTC for government cameras. Source codec,
keyframe cadence, browser support, packet loss, and venue network conditions
must be measured on representative cameras. H.265 must not be assumed to work
in every judging browser; the transcoded-H.264 path is the planned fallback,
not a completed government result.

## Selection rule at the venue

Select the path with the lowest measured freeze/black/corruption rate, then
lowest practical startup/latency, then browser compatibility and recovery.
Record the camera IDs, UTC timestamps, browser, codec, and gateway settings in
the final benchmark before changing the claim from provisional to measured.
