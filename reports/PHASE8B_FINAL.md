# Phase 8B final report

## Status

**PARTIAL.** The P0 credential-artifact issue is fixed and verified. The
existing local MediaMTX gateway was activated and exercised through an actual
WHEP SDP POST. The government RAW → gateway → WHEP → browser → AI path remains
**UNAVAILABLE** at the government gateway boundary.

## Security

- `SECRET_SCAN: PASS` after redacting the supplied credential values from
  generated JSON/diagnostic artifacts and `var/live.db`.
- Supplied values are absent from current files and all git history.
- The scanner now evaluates history line-by-line and permits clearly marked
  non-secret test fixtures without weakening detection of real credentials.
- Credential-boundary tests: 37 passed.
- No credentials were written to the browser tool, screenshots, reports, or
  frontend assets.

## Verified local control path

- Existing MediaMTX binary: `var/bin/mediamtx`.
- Existing project config: `var/mediamtx.yml`.
- Six synthetic paths became ready through the configured API on port 9997.
- Local `C-014` RTSP decoded 60 H.264 frames at 1280x720 over 5 seconds.
- Local WHEP GET returned 405, which was correctly not treated as failure.
- Actual WHEP SDP POST to `/stream/C-014/whep` returned HTTP 201 with an SDP
  answer.
- Playwright completed SDP negotiation and ICE reached `connected`, but no
  browser frame decoded during the 5-second control run; the screenshot is
  blank and WebRTC inbound reports were empty. This is a local browser/media
  control failure to investigate, not a government-source conclusion.

## Government camera status

| Camera | Raw | Gateway | WHEP | Browser | AI |
|---|---|---|---|---|---|
| cam01 | VERIFIED GREEN | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| cam03 | VERIFIED AMBER | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| cam06 | VERIFIED GREEN HEVC | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| cam12 | VERIFIED GREEN HEVC | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| cam18 | INTERMITTENT/NO-FRAME | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| cam22 | INTERMITTENT/NO-FRAME | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |

The detailed matrix is in `reports/PHASE8B_FRAME_PATH_MATRIX.md`.

## Architecture and AI

The existing application keeps selected-camera WHEP video separate from
analytics metadata and uses canvas/UI overlay scheduling rather than routing
every browser frame through Python. This is an architectural property, not an
authenticated browser performance measurement. AI-off versus AI-on browser
measurements, 4/9/16/30-camera browser walls, and 5/15/30-minute browser
soaks were not run because the government gateway/browser path is unavailable
and the local WHEP control has not yet produced decoded media.

## Root-cause categories

**VERIFIED:** credential cleanup; RTSP authentication and raw observations;
local MediaMTX readiness; local WHEP SDP POST signaling; local ICE connection.

**PARTIAL:** local browser path reaches ICE but does not produce a decoded
frame; this may be browser transport, codec negotiation, or gateway media
delivery and needs a focused local fix.

**UNAVAILABLE:** government gateway relay, government WHEP media, government
browser screenshots/stats, HEVC browser/transcode comparison, AI-on/off,
video-wall certification, and long browser stability tests.

**EXTERNAL-CANDIDATE:** none. No final government support email is justified
until the gateway/browser comparison exists.

## Artifacts

- `tools/test_whep_camera.py` performs safe WHEP POST, ICE, frame, screenshot,
  and WebRTC-stat collection without accepting credential-bearing endpoints.
- `var/reports/phase8b/browser/C-014.json`
- `var/reports/phase8b/browser/C-014.png`
- `reports/PHASE8B_FRAME_PATH_MATRIX.md`

## Validation

Full prior regression: 657 passed, 39 skipped. Phase 8B credential tests:
37 passed. Secret scan passed. Ruff, frontend syntax, and `git diff --check`
passed after the final cleanup.
