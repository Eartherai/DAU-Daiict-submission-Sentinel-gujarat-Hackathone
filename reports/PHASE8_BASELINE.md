# Phase 8 baseline

**Captured:** 2026-09-16 00:20 UTC (2026-09-16 05:50 IST evidence run)

This is the frozen baseline for Phase 8. The prior evidence under
`var/reports/live30_live/` is preserved and is not overwritten by this phase.

## Authenticated raw RTSP/TCP baseline

| Classification | Cameras | Count |
|---|---|---:|
| GREEN | cam01, cam02, cam04, cam05, cam06, cam11, cam12, cam13, cam14, cam15, cam17, cam19, cam20, cam29 | 14 |
| AMBER | cam03, cam10, cam23 | 3 |
| RED | cam07, cam08, cam09, cam16, cam18, cam21, cam22, cam24, cam25, cam26, cam27, cam28, cam30 | 13 |

The RED set includes twelve `NO_FRAME` cases and cam26, whose one fresh raw
frame was visibly white/overexposed. AMBER includes marginal frame counts;
cam03 also showed a macroblock/chroma artefact signal.

## Current demo candidates

- **Primary:** cam01, cam02, cam05 (clean H.264 1920x1080 evidence).
- **Secondary:** cam06, cam12, cam11, cam13, cam14, cam15, cam17, cam19,
  cam20, cam29, subject to repeated-run confirmation.
- **Degraded / hold for investigation:** cam03, cam10, cam23, cam26.
- **Do not use on the main wall until repeated:** cam07, cam08, cam09, cam16,
  cam18, cam21, cam22, cam24, cam25, cam27, cam28, cam30.

## Known unknowns

The baseline proves authenticated RTSP/PyAV observations only. It does not
prove gateway, WHEP/WebRTC, HLS, browser rendering, browser decoder
compatibility, AI-on video stability, or 4/9/16/30 browser-wall continuity.
No authenticated catalogue session, WHEP gateway session, browser automation
session, or browser screenshots/WebRTC statistics were available at capture
time. Therefore upstream, gateway, WebRTC, browser, frontend, and AI root
cause categories remain separated and unverified where no artifact exists.

## Evidence preservation

The baseline references the existing fresh capture, raw frames, contact sheet,
diagnostics, and forensic reports. No prior artifact was deleted or replaced.
