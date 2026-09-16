# Phase 8 final live-video report

## 1. Environment

The repository contains a local MediaMTX configuration for synthetic clips. No authenticated government WHEP gateway endpoint, browser automation session, or browser capture environment was configured for this phase.

## 2. Authentication

Ephemeral `SENTINEL_GRID_EMAIL` and `SENTINEL_GRID_PASSWORD` injection authenticated the RTSP authority for the repeatability run. Values were not written to files, logs, reports, screenshots, or frontend assets.

## 3. Raw RTSP results

The frozen baseline was 14 GREEN, 3 AMBER, and 13 RED/NO_FRAME from the prior concurrent run. Phase 8 repeated every RED/AMBER camera five times sequentially and five times concurrently for 10 seconds per run. Results are in `reports/REPEATABILITY_MATRIX.md` and `var/reports/phase8_repeatability.json`.

The repeated results show intermittent delivery for most cameras, with some concurrency-sensitive differences. This does not prove an upstream cause. It does prove that the earlier single bounded run was not sufficient to call the feeds consistently unavailable.

## 4. Gateway results

UNAVAILABLE for government feeds. The repository's local MediaMTX file is a synthetic test gateway, not evidence of a configured government relay.

## 5. WebRTC results

UNAVAILABLE. No authenticated WHEP POST/SDP negotiation was performed because no usable authenticated gateway/browser session was configured. See `reports/WHEP_CAMERA_RESULTS.md`.

## 6. Browser results

UNAVAILABLE. No browser screenshots, video-element state, or WebRTC `getStats()` artifacts exist for the government run.

## 7. AI comparison

UNAVAILABLE for authenticated browser video. No AI-off/AI-on browser measurement was performed.

## 8-11. 4/9/16/30-camera tests

UNAVAILABLE at the browser/video-wall layer. Existing frontend policy remains: shared ingest, selected-camera high-quality preview, lower-cost wall previews, and independent tile states. This is architecture, not measured browser certification.

## 12. Root causes

**PROVEN:** authenticated RTSP access works for at least some cameras; raw frame quality varies; repeated runs show intermittent/no-frame behavior; cam26 has a degraded raw frame in the frozen evidence.

**LIKELY:** startup/keyframe, session, network, or concurrency interactions for cameras whose sequential and concurrent outcomes differ. These are candidates only.

**UNVERIFIED:** government encoder fault, gateway fault, WebRTC/browser decoder fault, frontend overlay fault, AI-induced video degradation, and duplicate-upstream effects.

## 13. Fixes implemented

No media architecture rewrite was made. Existing RTSP/TCP transport, bounded decoding, reconnect/watchdog seams, snapshot fallback, and explicit unavailable-state reporting were retained. Phase 8 added baseline and repeatability evidence artifacts only.

## 14. Remaining external issues

No issue is escalated as proven external. The missing gateway/browser evidence is the blocking boundary for attribution.

## 15. Final demo configuration

Use cam01, cam02, and cam05 as the initial raw-evidence candidates. Keep degraded/no-frame cameras off the primary demo wall until repeated gateway/browser evidence exists. `config/demo_live.yaml` remains the configuration source; its WebRTC preference is not a measured success claim.

## 16. Support escalation

Do not send a final government-feed escalation yet. The required raw-to-gateway-to-browser comparison is incomplete. The existing neutral draft `docs/GOVERNMENT_FEED_SUPPORT_EMAIL.md` remains a draft only.
