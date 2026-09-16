# Phase 16 — 30-camera browser coverage

Timestamp UTC: `2026-09-16T19:55:39.232231+00:00`

Catalogue: **NOT_AUTHORITATIVE**. Direct Sentinel WHEP path unchanged.

## Labels

| Label | Use |
|---|---|
| MEASURED_REAL | This phase |
| NOT_AUTHORITATIVE | Probe camera IDs |
| DESIGNED | 50-cam regional pools |

## Compatibility path (intentional)

| Step | Result |
|---|---|
| H.264 B-frame source → copy → WHEP | **FAIL** — MediaMTX WebRTC rejects H264 streams with B-frames |
| H.264 → VideoToolbox baseline → WHEP | **PASS** |

## 30-camera source matrix

| Path | Cameras | Count |
|---|---|---:|
| DIRECT_SENTINEL_WHEP | cam01, cam02, cam03, cam04, cam05, cam06, cam12, cam13, cam14, cam16, cam18, cam19, cam20, cam23, cam26 | 15 |
| RTSP_ONLY (bridge candidates) | cam07, cam08, cam09, cam10, cam11, cam15, cam17, cam21, cam22, cam24, cam25, cam27, cam28, cam29, cam30 | 15 |

## Scheduler tiers

| Tier | Priority | Notes |
|---|---|---|
| DIRECT_WHEP | preferred | Untouched Sentinel WHEP |
| BRIDGED_PRIMARY | high | Full-quality VT baseline |
| BRIDGED_PREVIEW | normal | Cheap VT baseline (500k) |
| RTSP_ONLY_AI | fallback | When browser representation unavailable |

## Bridge cost profile (cam07)

| Tier | Startup s | ffmpeg CPU | RSS MB | Resolution | first_frame ms | WHEP |
|---|---:|---:|---:|---|---:|---|
| PRIMARY | 45.4 | 4.33 | 249.3 | 1920x1080 | 4972 | MEASURED |
| PREVIEW | 32.69 | 4.91 | 205.2 | 1280x720 | 3111 | MEASURED |

CPU ratio PREVIEW/PRIMARY: `1.134`
RSS ratio PREVIEW/PRIMARY: `0.823`

Bottleneck: Primary: upstream Sentinel RTSP auth concurrency / source timeouts after large fan-in. Secondary: VT session startup — stagger ≥3.5–5s required. PREVIEW cheap path = VT baseline @500k (no -s/-r under concurrency). Copy remux blocked by B-frames (intentional compatibility FAIL). Solo 720p PREVIEW was MEASURED earlier; concurrency uses bitrate-only PREVIEW.

PREVIEW encode (concurrency): `VT baseline 500k no-scale (concurrency-hardened); solo 720p previously MEASURED`

## Bridge concurrency (PREVIEW tier, staggered)

| n | Overall | Live | P/A/F | first p50 | ffmpeg CPUΣ | RSS MBΣ | sys CPU |
|---:|---|---:|---|---:|---:|---:|---:|
| 1 | PASS | 1 | 1/0/0 | 2011 | 6.4 | 222.6 | 0.0 |
| 2 | PASS | 2 | 2/0/0 | 2783 | 17.8 | 465.0 | 0.0 |
| 4 | PASS | 4 | 4/0/0 | 1574 | 45.4 | 683.4 | 33.7 |
| 6 | PASS | 6 | 5/1/0 | 1314 | 63.7 | 1295.3 | 11.6 |
| 8 | PASS | 8 | 8/0/0 | 1299 | 72.3 | 1949.5 | 14.0 |
| 10 | PASS | 10 | 9/1/0 | 1565 | 49.2 | 2338.5 | 15.0 |
| 12 | PASS | 12 | 12/0/0 | 2859 | 45.6 | 2847.6 | 14.9 |
| 15 | PASS | 15 | 14/1/0 | 2047 | 63.0 | 3617.4 | 15.4 |

Chosen bridge budget: **15**

## Hybrid 30-camera wall

| Soak | browser-visible | LIVE | PREVIEW | DIRECT | BRIDGED | RTSP_ONLY_AI | NO_SIGNAL |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 30s | **19** | 8 | 11 | 15 | 4 | 11 | 0 |
| 60s | **19** | 8 | 11 | 15 | 4 | 11 | 0 |
| 120s | **19** | 8 | 11 | 15 | 4 | 11 | 0 |

## Bridged PREVIEW promotion prewarm (MEASURED_REAL)

| Cold click→frame | 721.7000000029802 ms |
| Warm p50 | **35.75** ms |
| Warm p95 | 577.9599999956779 ms |
| Warm max | 904.2999999970198 ms |
| OK | 10 / 10 |

Do **not** reuse synthetic/local 44 ms.

## Remaining RTSP_ONLY_AI

Count on best soak: **11**
Bridges ready on best soak: **4**

## Operator wall layouts

- Default demo wall: **12** (kept)
- Added: **16 (4×4)**, **25 (5×5)**, **30 (6×5)**
- Tile meta: name, location, LIVE/PREVIEW, codec, latency, AI state (chips under video)

## AI impact

- RTSP→AI plane unchanged; WHEP→browser unchanged
- Bridge load must not stop AI or video (scheduler keeps RTSP_ONLY_AI when bridge unavailable)
- Adaptive low cadence on non-PRIMARY/selected-SECONDARY (unchanged contract)

## Latency (MEASURED_REAL)

- Bridged PREVIEW cold click→frame: `721.7000000029802` ms
- Bridged PREVIEW warm p50: `35.75` ms (not synthetic 44 ms)
- Bridge WHEP first-frame p50 at n=15 scale: see concurrency table

## Next bottleneck

- **Upstream RTSP source health / auth lockout** after large concurrent opens (hybrid wall limited to ~4 ready bridges while scale proved n=15 when sources healthy)
- VT encoder session stagger (≥3.5–5s) still required for cold starts
- Browser decode budget when DIRECT(15)+BRIDGED(N) approach 27–30 tiles

## Reproducibility

```bash
export SENTINEL_GRID_EMAIL=…
export SENTINEL_GRID_PASSWORD=…
cd saakshya
.venv/bin/python tools/phase16_bridge_optimize.py --mode all
.venv/bin/python tools/verify/secret_scan.py
```

Artifacts: `var/reports/phase10/performance/phase16_*.json`
