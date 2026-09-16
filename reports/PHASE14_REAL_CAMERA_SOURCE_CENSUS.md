# Phase 14 — Real camera source census

Timestamp UTC: `2026-09-16T17:00:14.133798+00:00`

Label: **NOT_AUTHORITATIVE** (catalogue `/api/ingest` unavailable without session cookie).
No authentication bypass. Credentials env-only.

## Summary

| Metric | Value |
|---|---:|
| Documented IDs probed | 30 |
| RTSP frame OK | **30** |
| WHEP browser decode OK | **15** |
| Both RTSP+WHEP | 15 |
| RTSP-only (AI plane OK, browser WHEP no frame) | 15 |
| Source-down (no RTSP, no WHEP) | 0 |

### Key finding

**30 of 30** documented IDs produced RTSP frames during the measured window.
**15 of 30** produced direct Sentinel WHEP browser frames (real Chromium SDP).

Phase 13 `NO_SIGNAL=20` was largely a **scheduler / WHEP-session-pressure / selection** issue,
not 20 dead cameras. RTSP proves most IDs are live sources.

## Camera matrix (scheduler source of truth)

| Camera | RTSP | WHEP | Preview | Codec | Frames | First fail | Classification | Tier |
|--------|------|------|---------|-------|--------|------------|----------------|------|
| cam01 | OK | OK | OK | h264 | rtsp=3;whep=1974.3 | — | **LIVE** | BROWSER_AND_RTSP |
| cam02 | OK | OK | OK | h264 | rtsp=3;whep=1454.6 | — | **LIVE** | BROWSER_AND_RTSP |
| cam03 | OK | OK | OK | h264 | rtsp=3;whep=1454.6 | — | **LIVE** | BROWSER_AND_RTSP |
| cam04 | OK | OK | OK | h264 | rtsp=3;whep=2484.8 | — | **LIVE** | BROWSER_AND_RTSP |
| cam05 | OK | OK | OK | h264 | rtsp=3;whep=2484.7 | — | **LIVE** | BROWSER_AND_RTSP |
| cam06 | OK | OK | OK | hevc | rtsp=3;whep=3527.1 | — | **LIVE** | BROWSER_AND_RTSP |
| cam07 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam08 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam09 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam10 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam11 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam12 | OK | OK | OK | hevc | rtsp=3;whep=1582.4 | — | **LIVE** | BROWSER_AND_RTSP |
| cam13 | OK | OK | OK | h264 | rtsp=3;whep=955.5 | — | **LIVE** | BROWSER_AND_RTSP |
| cam14 | OK | OK | OK | h264 | rtsp=3;whep=2009.7 | — | **LIVE** | BROWSER_AND_RTSP |
| cam15 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam16 | OK | OK | OK | h264 | rtsp=3;whep=4257.3 | — | **LIVE** | BROWSER_AND_RTSP |
| cam17 | OK | FAIL | N/A | hevc | rtsp=3 | WHEP_HEVC_BROWSER | **HEVC_UNSUPPORTED** | RTSP_ONLY_AI |
| cam18 | OK | OK | OK | hevc | rtsp=3;whep=4717.9 | — | **LIVE** | BROWSER_AND_RTSP |
| cam19 | OK | OK | OK | h264 | rtsp=3;whep=1984.2 | — | **LIVE** | BROWSER_AND_RTSP |
| cam20 | OK | OK | OK | h264 | rtsp=3;whep=5208.1 | — | **LIVE** | BROWSER_AND_RTSP |
| cam21 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam22 | OK | FAIL | N/A | hevc | rtsp=3 | WHEP_HEVC_BROWSER | **HEVC_UNSUPPORTED** | RTSP_ONLY_AI |
| cam23 | OK | OK | OK | h264 | rtsp=3;whep=4775.4 | — | **LIVE** | BROWSER_AND_RTSP |
| cam24 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam25 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam26 | OK | OK | OK | hevc | rtsp=3;whep=3715.6 | — | **LIVE** | BROWSER_AND_RTSP |
| cam27 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam28 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam29 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |
| cam30 | OK | FAIL | N/A | h264 | rtsp=3 | WHEP_NO_FRAME | **WHEP_UNAVAILABLE** | RTSP_ONLY_AI |

## Wall-eligible (WHEP decode OK)

cam01, cam02, cam03, cam04, cam05, cam06, cam12, cam13, cam14, cam16, cam18, cam19, cam20, cam23, cam26

## RTSP-only (not NO_SIGNAL — source live; browser WHEP unavailable in window)

cam07, cam08, cam09, cam10, cam11, cam15, cam17, cam21, cam22, cam24, cam25, cam27, cam28, cam29, cam30

## Classification counts

- `HEVC_UNSUPPORTED`: 2
- `LIVE`: 15
- `WHEP_UNAVAILABLE`: 13

## Preview pool push (MEASURED_REAL)

| n | Overall | Live | PASS/AMBER/FAIL | first_frame p50 |
|---:|---|---:|---|---:|
| 8 | PASS | 8 | 8/0/0 | 3554 |
| 10 | AMBER | 9 | 9/0/1 | 4200 |
| 12 | AMBER | 12 | 10/2/0 | 3930 |
| 16 | AMBER | 15 | 9/6/1 | 5744 |

Chosen preview budget (alone): **12**

## Hybrid wall (MEASURED_REAL)

| Soak | LIVE | PREVIEW | AWAITING_SLOT | NO_SIGNAL | Overall | Notes |
|---:|---:|---:|---:|---:|---|---|
| 30s | 8 | 7 | 10 | **0** | AMBER | mixed eligible |
| 60s | 8 | 12 | 10 | **0** | AMBER | preview push budget |
| 120s | 8 | 7 | 15 | **0** | AMBER | FULL=8 + all remaining WHEP-eligible as PREVIEW |

NO_SIGNAL reserved for census-unavailable sources only (none in this window).  
RTSP-only cameras → **AWAITING_SLOT** / AI plane — **not** false NO_SIGNAL.

Machine-readable: `var/reports/phase10/performance/phase14_source_census.json`  
120s wall: `var/reports/phase10/performance/phase14_hybrid_wall_120s.json`  
Escalation note: `reports/SENTINEL_30_CAMERA_SOURCE_AVAILABILITY_ESCALATION.md`
