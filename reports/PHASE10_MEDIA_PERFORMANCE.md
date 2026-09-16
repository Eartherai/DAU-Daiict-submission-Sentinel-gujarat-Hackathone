# Phase 10 — Media performance breakthrough

Timestamp UTC: `2026-09-16T14:07:43.065266+00:00`

## Verdict

**12 is not the architecture limit.** Headed ANGLE Metal on Apple M5 can run **16 concurrent full WHEP at PASS** when publishers are healthy (MEASURED_SYNTHETIC). Government-source walls previously peaked near **12 PASS** because of weak/flaky upstream cams + negotiation contention — not a hard browser ceiling.

Government RTSP auth is currently **401 BLOCKED** (credentials still env-configured; server rejects). Live gov re-runs paused; synthetic isolates the browser plane.

## Before → after

| Item | Before Phase 10 | After |
|---|---|---|
| Browser | Headed Metal | Headed Metal (required) |
| WHEP negotiation | contended wave | semaphore + late join + retry |
| Best gov n=12 | 5P / 4A / 3F | **11P / 1F** (conc 4 or 8) |
| Synthetic n=16 | — | **16 PASS / 0 FAIL** |
| Synthetic n=20 | — | **19 PASS / 1 FAIL** |
| Live PREVIEW | claimed | **HLS MEDIA-SEQUENCE advances (PASS)** |
| Prewarm promotion | — | **7.74× faster** (337ms → 44ms) |
| VideoToolbox encode | unwired preference | **KEEP** — ~2× lower CPU/frame vs libx264 |

## Concurrency sweep (gov n=12, MEASURED)

Best concurrency: **8**

| Conc | PASS | AMBER | FAIL | neg p50 | first p50 |
|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 3 | 5 | 4650.10000000149 | 6600.30000000447 |
| 2 | 7 | 0 | 5 | 2347.6999999955297 | 2987.10000000149 |
| 3 | 0 | 0 | 12 | None | None |
| 4 | 11 | 0 | 1 | 1227.699999999255 | 2458.89999999851 |
| 6 | 9 | 0 | 3 | 628.7999999970198 | 1541.5 |
| 8 | 11 | 0 | 1 | 456.04999999701977 | 1520.0 |

## Government scale progression (prior MEASURED; auth now blocked)

| N | Overall | PASS | AMBER | FAIL |
|---:|---|---:|---:|---:|
| 12 | AMBER | 6 | 4 | 2 |
| 14 | AMBER | 11 | 1 | 2 |
| 16 | AMBER | 12 | 0 | 4 |
| 18 | AMBER | 12 | 0 | 6 |
| 20 | AMBER | 11 | 1 | 8 |
| 24 | AMBER | 8 | 4 | 12 |
| 30 | AMBER | 7 | 5 | 18 |

## Synthetic browser ceiling (MEASURED_SYNTHETIC, healthy publishers)

| N | Overall | PASS | AMBER | FAIL | neg p50 | first p50 |
|---:|---|---:|---:|---:|---:|---:|
| 16 | PASS | 16 | 0 | 0 | 882.4499999955297 | 1415.1000000014901 |
| 20 | AMBER | 19 | 0 | 1 | 1426.1000000014901 | 1945.1000000014901 |
| 24 | AMBER | 19 | 3 | 2 | 1394.699999999255 | 1933.5999999977648 |
| 30 | AMBER | 18 | 7 | 5 | 2732.2000000029802 | 3474.2999999970198 |

## Live PREVIEW (HLS)

Overall: **PASS**  
Variant playlist `MEDIA-SEQUENCE` advances with session query retained (stripping `?session=` → 401). Not a static still.

## Prewarm / session pool (10B)

| Path | click→first frame |
|---|---:|
| COLD negotiate | 336.79999999701977 ms |
| WARM attach | 43.5 ms |
| Speedup | **7.74×** |

GPU: `ANGLE (Apple, ANGLE Metal Renderer: Apple M5, Unspecified Version)`

## VideoToolbox (10E)

- H.264 ingest: **DIRECT_H264 packet copy** (no decode).
- HEVC→H.264 encode bench (local HEVC file): keep **h264_videotoolbox** — VT lower CPU/frame with similar FPS.
- PyAV VT *decode* not required on the copy path.

## Recommended 30-camera architecture

| Tier | Count | Representation |
|---|---:|---|
| PRIMARY | 1 | full WHEP (prewarmed) |
| SECONDARY | up to 15 | full WHEP within measured PASS band |
| PREVIEW | remaining → 30 | **live HLS** (or low-cost WHEP if HLS lag) |

Do **not** freeze at 8 full WHEP. Synthetic proves ≥16; gov PASS peak ~12 is source-limited.

## Remaining bottleneck

1. **Government RTSP auth currently 401** — blocks live gov re-push.
2. Upstream gov cam flakiness beyond ~12 concurrent ready publishers.
3. At n≥24 synthetic: negotiation p95 rises; adaptive preview + resource controller required for 30 smooth tiles.

## Next optimization

1. Restore gov auth → re-run headed 16/20 on strongest cams with conc=4.
2. Wire prewarm pool into operator promotion path.
3. HLS `<video>` PREVIEW tiles in UI with sessioned playlists.
4. MediaResourceController pressure → demote WHEP→HLS before black tiles.

Artifacts: `var/reports/phase10/performance/`
