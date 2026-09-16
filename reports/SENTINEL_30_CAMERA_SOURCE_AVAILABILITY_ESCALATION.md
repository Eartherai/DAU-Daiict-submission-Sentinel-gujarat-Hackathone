# Sentinel browser-WHEP coverage note (Phase 14)

Timestamp UTC: `2026-09-16T17:11:37.030551+00:00`

## Statement

**30** of the documented camera IDs (`cam01`…`cam30`) produced RTSP/TCP frames 
during the measured window. **15** also produced direct Sentinel WHEP browser frames 
(real Chromium SDP offer). **0** were source-down on both planes.

This is not a claim that the government system is broken. It documents measured reachability.

## WHEP no-frame after retries (RTSP still OK)

cam07, cam08, cam09, cam10, cam11, cam15, cam17, cam21, cam22, cam24, cam25, cam27, cam28, cam29, cam30

## Catalogue

NOT_AUTHORITATIVE — no SENTINEL_GRID_COOKIE/TOKEN; `/api/ingest` not queried without legitimate session.

## Endpoints

- `rtsp://103.250.160.189:8554/stream/{id}`
- `http://103.250.160.189:8889/stream/{id}/whep`
