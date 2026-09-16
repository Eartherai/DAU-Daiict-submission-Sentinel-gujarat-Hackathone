# Real 30-camera WHEP certification

Timestamp UTC: `2026-09-16T15:17:41.561117+00:00`

## Labels

| Label | Meaning |
|---|---|
| MEASURED_REAL | Direct Sentinel WHEP on government endpoints |
| MEASURED_SYNTHETIC | Prior local synthetic browser ceiling (separate) |
| DESIGNED | Scheduler / UX / 50-logical |
| NOT_AUTHORITATIVE | Camera IDs without `/api/ingest` catalogue session |

## Catalogue

Authoritative `/api/ingest`: **False** (no `SENTINEL_GRID_COOKIE` / TOKEN).  
Camera IDs use documented `cam01`–`cam30` probe set — **NOT authoritative catalogue**.

## Progression — best unique-camera MEASURED_REAL

| N | Overall | PASS | AMBER | FAIL | first p50 | first p95 | neg p50 | Notes |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | **PASS** | 1 | 0 | 0 | 2485 | 2485 | 941 | cam01 |
| 4 | **PASS** | 4 | 0 | 0 | 2066 | 2949 | 420 | cam01/02/05/04 |
| 8 | **PASS** | 8 | 0 | 0 | 2821 | 3079 | 989 | strong H.264 set |
| 12 | **AMBER** | 10 | 0 | 2 | 3155 | 5015 | 2137 | FAIL cam11/cam07; **cam06 HEVC PASS** |
| 16 | **AMBER** | 10 | 0 | 6 | 2456 | 3476 | 2065 | peak PASS band ~10 |
| 20 | **AMBER** | 10 | 0 | 10 | 3008 | 6291 | 2003 | half NO_FRAME/source |
| 24 | **AMBER** | 7 | 3 | 14 | 8234 | 17270 | 6535 | negotiation skew |
| 30 | **AMBER** | 9 | 1 | 20 | 2619 | 4225 | 2089 | isolation OK |

**Peak simultaneous PASS tiles (real): 10**  
**Best all-PASS wall: n=8 (8/8)**  
**n=4 also 4/4 PASS (reconfirmed)**

Failed tiles at higher N concentrate on weaker/unavailable sources (cam07–12, cam16+), not wall-wide collapse. Slow tiles do not block others (independent negotiation).

## Adaptive 30-camera wall (MEASURED_REAL + DESIGNED)

FULL_WHEP budget seeded at **10** (measured peak band).

| UX state | Count |
|---|---:|
| LIVE | 10 |
| PREVIEW | 20 |
| DEGRADED | 0 |
| CONNECTING | 0 |
| NO_SIGNAL | 0 |
| RECONNECTING | 0 |

FULL_WHEP measured overall: **PASS**  
Summary: `{'PASS': 10, 'AMBER': 0, 'FAIL': 0, 'first_frame_ms_p50': 3289.6499999910593, 'first_frame_ms_p95': 4864.23999999836, 'negotiation_ms_p50': 2085.5999999940395, 'negotiation_ms_p95': 3445.044999995082}`

No tile outside FULL_WHEP is labeled LIVE without a live transport.

## HEVC (MEASURED_REAL)

`cam06` achieved **PASS** on direct Sentinel WHEP in the n=12 wall — native browser path viable for at least one HEVC camera. Do not force transcode for all HEVC without per-camera evidence.

## Prewarm

Prior MEASURED_SYNTHETIC local prewarm: 337→44 ms (7.74×).  
Direct Sentinel WHEP prewarm promotion: use same attach-without-renegotiate pattern (Phase 11 client). Re-measure on direct path before claiming 44 ms class on Sentinel.

## VIDEO-FIRST / AI-FIRST (DESIGNED)

- VIDEO-FIRST: maximize FULL_WHEP toward peak PASS (~8–10); AI adaptive/low.
- AI-FIRST: hold ≥4–8 FULL_WHEP; AI on RTSP/TCP only; never decode WHEP for AI.

## 50-camera story (DESIGNED)

30 real + 20 synthetic/control scheduler entries.  
Budget example: `10` FULL_WHEP.  
**Do not claim 50 government feeds.**

## Synthetic ceiling (MEASURED_SYNTHETIC — separate)

16/16 PASS · 20=19P · 24=19P · 30=18P on local synthetic publishers.

## Recommendation

1. **Primary browser path:** Direct Sentinel WHEP + `Authorization: Basic`.
2. **Real demo wall:** 8–10 FULL_WHEP (LIVE) + remaining PREVIEW/RECONNECTING/NO_SIGNAL.
3. **Do not hardcode 8 forever** — scheduler uses measured peak + resource pressure.
4. **AI:** RTSP/TCP plane only.
5. **Catalogue:** obtain `SENTINEL_GRID_COOKIE` for authoritative `/api/ingest`.

## Security

Credentials never in artifacts. SECRET SCAN required.

Machine-readable: `var/reports/phase10/performance/phase12_real_30_cert_payload.json`
