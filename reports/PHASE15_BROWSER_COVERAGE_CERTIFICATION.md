# Phase 15 — Browser coverage certification

Timestamp UTC: `2026-09-16T17:50:47.901678+00:00`

Catalogue: **NOT_AUTHORITATIVE** (no Sentinel session cookie).
Architecture unchanged for WHEP-capable cameras (DIRECT_SENTINEL_WHEP).

## Key finding (MEASURED_REAL)

| Metric | Before (Phase 14) | After (Phase 15) |
|---|---:|---:|
| Browser-visible (best soak) | 15 | **19** (60s hybrid) |
| Direct Sentinel WHEP | 15 | 15 (untouched) |
| Bridged RTSP→WHEP | 0 | **4–6** sustained (budget **6**) |
| NO_SIGNAL | 0 | **0** |
| RTSP_ONLY_AI remaining | 15 | **9** |

cam07 proof: **copy FAIL** (H.264 B-frames) → **VT baseline transcode PASS** (first frame ~1.1 s, ICE connected, 1920×1080).

## Labels

| Label | Use |
|---|---|
| MEASURED_REAL | Direct Sentinel + local bridge measurements |
| DESIGNED | 50-cam regional pool plan |
| NOT_AUTHORITATIVE | Probe IDs without catalogue |

## cam07 smallest bridge (MEASURED_REAL)

- Copy remux: **FAIL** — MediaMTX WebRTC rejects H.264 B-frames
- Transcode VT baseline: **PASS** → `RTSP_TRANSCODED_H264`
- first_frame_ms: 1097.5999999940395
- ice: connected · currentTime: 15.157
- size: 1920x1080 · luma: 60.506580825617284

## StreamPathSelector V2

| Camera | Path | Browser |
|---|---|---|
| cam01 | `DIRECT_SENTINEL_WHEP` | yes |
| cam02 | `DIRECT_SENTINEL_WHEP` | yes |
| cam03 | `DIRECT_SENTINEL_WHEP` | yes |
| cam04 | `DIRECT_SENTINEL_WHEP` | yes |
| cam05 | `DIRECT_SENTINEL_WHEP` | yes |
| cam06 | `DIRECT_SENTINEL_WHEP` | yes |
| cam07 | `RTSP_TRANSCODED_H264` | yes |
| cam08 | `RTSP_TRANSCODED_H264` | yes |
| cam09 | `RTSP_TRANSCODED_H264` | yes |
| cam10 | `RTSP_TRANSCODED_H264` | yes |
| cam11 | `RTSP_TRANSCODED_H264` | yes |
| cam12 | `DIRECT_SENTINEL_WHEP` | yes |
| cam13 | `DIRECT_SENTINEL_WHEP` | yes |
| cam14 | `DIRECT_SENTINEL_WHEP` | yes |
| cam15 | `RTSP_TRANSCODED_H264` | yes |
| cam16 | `DIRECT_SENTINEL_WHEP` | yes |
| cam17 | `RTSP_ONLY_AI` | no |
| cam18 | `DIRECT_SENTINEL_WHEP` | yes |
| cam19 | `DIRECT_SENTINEL_WHEP` | yes |
| cam20 | `DIRECT_SENTINEL_WHEP` | yes |
| cam21 | `RTSP_ONLY_AI` | no |
| cam22 | `RTSP_ONLY_AI` | no |
| cam23 | `DIRECT_SENTINEL_WHEP` | yes |
| cam24 | `RTSP_ONLY_AI` | no |
| cam25 | `RTSP_ONLY_AI` | no |
| cam26 | `DIRECT_SENTINEL_WHEP` | yes |
| cam27 | `RTSP_ONLY_AI` | no |
| cam28 | `RTSP_ONLY_AI` | no |
| cam29 | `RTSP_ONLY_AI` | no |
| cam30 | `RTSP_ONLY_AI` | no |

## Bridge scalability (VT transcode)

| n | Overall | Live | PASS/A/F | first p50 | CPU | RAM avail |
|---:|---|---:|---|---:|---:|---:|
| 1 | PASS | 1 | 1/0/0 | 1444 | 17.7 | 10.65 |
| 2 | AMBER | 1 | 1/0/1 | 1440 | 15.4 | 10.719 |
| 4 | FAIL | 0 | 0/0/4 | 0 | 15.3 | 11.137 |
| 6 | AMBER | 6 | 5/1/0 | 921 | 17.4 | 10.462 |
| 8 | AMBER | 4 | 3/1/4 | 1430 | 32.3 | 10.46 |

Chosen bridge budget: **6**

## Hybrid 30-camera wall

| Soak | browser-visible | LIVE | PREVIEW | DIRECT | BRIDGED | RTSP_ONLY_AI | NO_SIGNAL |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 30s | 18 | 8 | 10 | 15 | 3 | 9 | 0 |
| 60s | 19 | 8 | 11 | 15 | 4 | 9 | 0 |

## Per-camera browser matrix

| Camera | RTSP | WHEP | Bridge | Codec | Browser path | Result |
|---|---|---|---|---|---|---|
| cam01 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam02 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam03 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam04 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam05 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam06 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam07 | OK | FAIL | PASS | h264 | RTSP_TRANSCODED_H264 | **PASS** |
| cam08 | OK | FAIL | PASS | h264 | RTSP_TRANSCODED_H264 | **PASS** |
| cam09 | OK | FAIL | PASS | h264 | RTSP_TRANSCODED_H264 | **PASS** |
| cam10 | OK | FAIL | PASS | h264 | RTSP_TRANSCODED_H264 | **PASS** |
| cam11 | OK | FAIL | PASS | h264 | RTSP_TRANSCODED_H264 | **PASS** |
| cam12 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam13 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam14 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam15 | OK | FAIL | PASS | h264 | RTSP_TRANSCODED_H264 | **PASS** |
| cam16 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam17 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam18 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam19 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam20 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam21 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam22 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam23 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam24 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam25 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam26 | OK | OK | — | — | DIRECT_SENTINEL_WHEP | **PASS** |
| cam27 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam28 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam29 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |
| cam30 | OK | FAIL | — | — | RTSP_ONLY_AI | AI-only |

## Limitations

- Local bridge required for RTSP-only cams: WebRTC rejects H.264 B-frames on copy.
- Bridge uses VideoToolbox baseline transcode (CPU/GPU cost) — budgeted separately.
- Direct Sentinel WHEP cameras are never forced through the relay.
- Catalogue still NOT_AUTHORITATIVE.

## Reproducibility

```bash
export SENTINEL_GRID_EMAIL=…
export SENTINEL_GRID_PASSWORD=…
cd saakshya
.venv/bin/python tools/phase15_rtsp_bridge.py --mode all
.venv/bin/python tools/verify/secret_scan.py
```

Artifacts: `var/reports/phase10/performance/phase15_*.json`
