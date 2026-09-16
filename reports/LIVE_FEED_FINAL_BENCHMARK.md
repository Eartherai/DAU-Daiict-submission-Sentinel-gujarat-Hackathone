# Live feed final benchmark

## Status

This report is a measurement ledger, not a promise that unavailable external
feeds work. The authenticated government catalogue and a browser/Gateway
environment were not available in this workspace, so external paths remain
`UNAVAILABLE` rather than receiving guessed values.

| Path | Codec | Startup | FPS | Latency | Freeze | Black | Red/Corrupt | Recovery |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RTSP -> PyAV | not measured | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| RTSP -> WebRTC | not measured | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| RTSP -> HLS | not measured | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| H.265 -> H.264 -> WebRTC | not measured | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |

## Authenticated government probe

On **2026-09-15 23:55 UTC**, all 30 registered RTSP URLs were probed
concurrently. Result: **30/30 HTTP 401 Unauthorized before stream open**.
Because no media packet was received, startup, FPS, latency, freeze, black,
green/corruption, and recovery are all **UNAVAILABLE** for the government
sources. This is currently classified as access/credential configuration, not
as an encoder or network diagnosis.

The local diagnostic tool can populate this table from a permitted URL or media
file. It records codec, dimensions, pixel format, PTS progression, frame
interval variance, decoder errors, suspected black/corrupt frames, and
reconnect/freeze events. No government result is inferred from a local clip.

## Local control decode

The existing local government-labelled clips were useful as decoder controls,
but their sampled frames carried a constant PTS and an implausible declared
frame rate. The diagnostic therefore correctly withheld observed FPS rather
than turning container metadata into a performance claim:

| Source | Codec | Resolution | Frames decoded | PTS | Black | Freeze | Result |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `var/demo/live_clips/cam16.mp4` | H.264 | 1920x1080 | 120 | constant / unusable | 0 | 0 | MEASURED decode control |
| `var/demo/live_clips/cam21.mp4` | H.264 | 1920x1080 | 120 | constant / unusable | 0 | 0 | MEASURED decode control |

These files are not a live transport comparison and do not establish
government-camera latency, FPS, or browser reliability.

## Existing measured controls

- The Python regression suite passes 655 tests with 38 skipped.
- The browser performs WHEP negotiation only for the selected camera and falls
  back to ingest snapshots when negotiation fails.
- Browser WebRTC stats are shown only when `getStats()` reports them; CPU/GPU
  utilisation remains explicitly unavailable.
