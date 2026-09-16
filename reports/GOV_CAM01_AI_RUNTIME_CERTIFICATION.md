# Government cam01 AI runtime certification

Measured UTC: `2026-09-16T03:41:32.122281+00:00`

Path: Government RTSP → PyAV relay → MediaMTX → (WHEP browser ‖ local RTSP AI)

Camera: **cam01** (GOLDEN). Duration per mode: **45 s**. Credentials: environment only.

| Mode | Verdict | browser currentTime | freezes | pkt loss | AI status | AI frames | p50 ms |
|---|---|---:|---:|---:|---|---:|---:|
| VIDEO_ONLY | **AMBER** | 19.42 | 1 | 0 | SKIPPED | — | — |
| DETECTION | **PASS** | 45.327 | 1 | 0 | MEASURED | 775 | 47.8 |
| DETECTION_TRACKER | **PASS** | 45.351 | 0 | 0 | MEASURED | 761 | 61.0 |
| DETECTION_TRACKER_OCR | **PASS** | 45.361 | 0 | 0 | MEASURED | 777 | 54.45 |
| FULL | **PASS** | 45.116 | 0 | 0 | MEASURED | 547 | 101.07 |

## Key finding

With AI enabled (DETECTION through FULL), browser `currentTime` reached ~45 s
with ICE connected and 0 packet loss. VIDEO_ONLY in the same session was AMBER
(early ICE disconnect at ~19 s). **AI load did not prevent browser playback.**

## Acceptance

- Browser path remains alive with AI on the same gateway fanout — **PASS**
- AI measured independently on local MediaMTX RTSP — **PASS**
- No credentials in artifacts — re-run secret scan after this report

Machine-readable: `var/reports/phase8c/gov/cam01_ai_runtime.json`

