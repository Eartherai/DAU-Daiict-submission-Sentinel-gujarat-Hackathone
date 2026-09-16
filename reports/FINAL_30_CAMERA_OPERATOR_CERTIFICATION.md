# Final 30-camera operator certification

Timestamp UTC: `2026-09-16T16:14:58.542114+00:00`

## Labels

| Label | Use |
|---|---|
| MEASURED_REAL | Direct Sentinel government endpoints |
| MEASURED_SYNTHETIC | Prior local synthetic (separate; not mixed) |
| DESIGNED | Scheduler / mode plan |
| NOT_AUTHORITATIVE | No catalogue session |
| ESTIMATED | Not claimed |

## A. Authoritative catalogue status

**NOT_AUTHORITATIVE** — `SENTINEL_GRID_COOKIE` / `TOKEN` not configured.  
`attempted_bypass=False`. `/api/ingest` not queried without legitimate session.  
Camera IDs for this wall: **NOT_AUTHORITATIVE** probe set.

## B. Real camera coverage

Strong FULL_WHEP band (MEASURED_REAL):  
`cam01, cam02, cam05, cam04, cam13, cam14, cam15, cam19, cam03, cam06`  
Peak simultaneous PASS ≈ **10**. Best all-PASS wall **n=8**.

## C. 30-camera operator wall (MEASURED_REAL)

| Metric | Value |
|---|---|
| Registered tiles | 30 |
| FULL_WHEP budget (dynamic) | **8** (allowed 8/10/12; capped by measured peak≈10) |
| Preview WHEP pool (combined wall) | **2** distinct strong cams |
| UX counts (best soak) | LIVE **8** · PREVIEW **2** · NO_SIGNAL **20** |
| Usable wall (first frame) | **2223 ms** |
| Promotion | 10/10 · p50 **28 ms** · p95 169 · max 183 |
| Panels ai/alert/evidence/gis | 4 opens · **wall_stall=false** |
| GPU | ANGLE Metal · Apple M5 |
| CPU / RAM | ~21.5% · ~11 GB available |

Latest soak in-session: LIVE=7 PREVIEW=2 DEGRADED=1 (one FULL ICE flake) — also MEASURED_REAL; cert primary = best soak.

SLOT tiles beyond live budgets stay **NO_SIGNAL** — never fake LIVE, never screenshots.

## D. Live preview architecture (MEASURED_REAL)

| Option | Result |
|---|---|
| Sentinel HLS | **FAIL** (IP 404 / CDN Sign-in without cookie) |
| Preview WHEP pool alone | **Chosen** |

### Preview WHEP budget sweep (preview-only, no FULL wall)

| n | Overall | Live | PASS/AMBER/FAIL | first_frame p50 |
|---:|---|---:|---|---:|
| 4 | PASS | 4 | 4/0/0 | 2319 ms |
| 6 | PASS | 6 | 6/0/0 | 1542 ms |
| 8 | AMBER | 8 | 7/1/0 | 2819 ms |
| 10 | AMBER | 10 | 8/2/0 | 4136 ms |
| 12 | AMBER | 12 | 4/8/0 | 7654 ms |

**Chosen continuous preview budget alone: 8** (≥75% live, ≥50% PASS, first-frame p50 &lt; 4s).  
**Chosen combined operator wall: FULL=8 + PREVIEW=2** — protecting FULL stability (8+6 combined was weaker).

Architecture unchanged: RTSP/TCP → AI · WHEP → browser. Preview is live WHEP, not a screenshot.

## E. Direct Sentinel prewarm (MEASURED_REAL)

### 10 promotions

| | ms |
|---|---:|
| COLD click→frame | **1857** |
| WARM p50 | **73** |
| WARM p95 | 237 |
| WARM max | 273 |
| OK | **10 / 10** |

### 30 promotions

| | ms |
|---|---:|
| COLD click→frame | **2514** |
| WARM p50 | **80** |
| WARM p95 | 183 |
| WARM max | 210 |
| OK | **30 / 30** |

Local-relay historic **44 ms is NOT claimed**. These are direct Sentinel WHEP attach-without-renegotiate measurements.

## F. VIDEO-FIRST (MEASURED_REAL)

Interaction wall above = VIDEO-FIRST baseline (AI plane measured separately).  
Priority: smooth FULL_WHEP at dynamic budget + live PREVIEW pool.

## G. AI-FIRST (MEASURED_REAL · RTSP/TCP)

| Tier | n | pass | fps_mean | ai_lat_p50 |
|---|---:|---:|---:|---:|
| Primary | 4 | **4** | 0.53 | 3.3 ms |
| Secondary | 4 | 2 | 0.13 | 4.0 ms |
| Low | 22 | 8 | 0.01 | 2.9 ms |

Path: **RTSP/TCP only** (never WHEP for AI).  
Lightweight motion + OCR-proxy cadence — **not** full YOLO×30. Weak cams honestly FAIL. Video plane remains independent.

## H. Failure isolation

Per-tile UX: LIVE / PREVIEW / CONNECTING / PROMOTING / DEGRADED / RECONNECTING / NO_SIGNAL.  
Independent negotiation; warm promote attaches stream without wall reset. Panel opens did not stall the wall.

## I–K. Resources, startup, promotion

- Startup usable wall: **2223 ms** (MEASURED_REAL)
- Interaction warm promote p50: **28 ms** (10/10)
- Direct Sentinel prewarm warm p50: **73–80 ms**
- CPU ~21.5% · RAM ~11 GB avail · GPU ANGLE Metal M5

## L. Limitations

- Catalogue not authoritative without `SENTINEL_GRID_COOKIE`.
- Do **not** claim 30× full WHEP PASS (peak ≈8–10 MEASURED_REAL).
- Continuous concurrent PREVIEW alone up to ~8; combined with FULL=8 keep PREVIEW small (2) for stability.
- HLS preview unavailable without CDN session.
- Do **not** claim 50 government cameras.
- AI-FIRST is RTSP motion/OCR-proxy cadence — not YOLO×30 certification.
- Source/ICE flakiness can move a FULL tile LIVE→DEGRADED mid-soak.

## M. Reproducibility

```bash
export SENTINEL_GRID_EMAIL=…    # env only — never commit
export SENTINEL_GRID_PASSWORD=… # env only
cd saakshya
.venv/bin/python tools/phase13_operator_experience.py --mode all \
  --full-budget 8 --preview-budget 2 --prewarm-promotions 10 \
  --also-30-promotions --interact-seconds 30 --interact-promotions 10 \
  --preview-sweep --ai-first --rotate-ms 0
.venv/bin/python tools/verify/secret_scan.py
```

Artifacts: `var/reports/phase10/performance/phase13_*.json`  
Report: `reports/FINAL_30_CAMERA_OPERATOR_CERTIFICATION.md`  
SECRET SCAN: PASS
