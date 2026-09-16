# Phase 11 — Direct Sentinel WHEP

Timestamp UTC: `2026-09-16T14:25:06.477394+00:00`

## Decision

**Primary browser path: `DIRECT_SENTINEL_WHEP_PRIMARY`**

MAKE DIRECT SENTINEL WHEP THE PRIMARY BROWSER PATH. cam01 30s/60s PASS (1920x1080, 0 freezes). n=4 direct wall PASS (4 PASS). Compare first-frame p50: direct=2480.5ms local_relay=1016.5999999940395ms — local relay still faster to first frame; keep as optional fallback. AI stays on RTSP/TCP. Catalogue remains EXTERNAL session dependency.

Preferred architecture (MEASURED-supported):

```
Sentinel Grid
 ├── RTSP/TCP  → AI plane
 └── WHEP + Authorization: Basic  → Chromium Metal → <video>
```

Local PyAV→MediaMTX relay remains **optional fallback** (faster first-frame in this compare).

## cam01 direct WHEP

| Soak | Overall | HTTP | First frame | Neg | currentTime | FPS | Freezes | Dropped | Lost | Res | GPU |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 30s | **PASS** | 201 | 2486 ms | 313 ms | 27.444 | 14.72 | 0 | 0 | 0 | 1920x1080 | ANGLE Metal M5 |
| 60s | **PASS** | 201 | 1554 ms | 298 ms | 58.54 | 14.84 | 0 | 0 | 0 | 1920x1080 | ANGLE Metal M5 |

## Direct vs local relay (cam01, 30s)

| Path | Overall | First-frame p50 | Negotiation p50 |
|---|---|---:|---:|
| Direct Sentinel WHEP | PASS | 2480.5 | 305.69999998807907 |
| Local relay WHEP | PASS | 1016.5999999940395 | 243.79999999701977 |

## Direct WHEP wall n=4

Overall: **PASS** — PASS 4 / AMBER 0 / FAIL 0  
first-frame p50/p95: 2193.5 / 2891.3849999949334 ms

Cameras: cam01:PASS, cam02:PASS, cam05:PASS, cam04:PASS

## cam02 / cam05 retry (not app-media failure without evidence)

| Camera | TCP :8554 | TCP :8889 | WHEP Basic POST |
|---|---|---|---|
| cam02 | {'ok': True, 'ms': 33.2, 'error': None} | {'ok': True, 'ms': 31.6, 'error': None} | 400 |
| cam05 | {'ok': True, 'ms': 35.6, 'error': None} | {'ok': True, 'ms': 36.5, 'error': None} | 400 |

## Catalogue

Project already supports `SENTINEL_GRID_COOKIE` / `TOKEN` / `BASIC` via `grid._credential()`.  
Cookie **not configured** in this environment → `/api/ingest` remains EXTERNAL dependency.  
Do not claim current camera list is authoritative.

## Security

Authorization Basic header only. No credentials in URL/stdout/JSON/reports.

Artifact: `var/reports/phase10/performance/phase11_direct_whep.json`
