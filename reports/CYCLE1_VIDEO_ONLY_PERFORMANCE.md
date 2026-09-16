# Cycle-1 media performance (VIDEO-ONLY)

Timestamp UTC: `2026-09-16T04:27:35.017750+00:00`

## Hardware (MEASURED)

| Item | Value |
|---|---|
| Machine | Apple M5 · 10 CPU · 10 GPU · Metal 4 |
| RAM | ~25.8 GB total |
| NVIDIA/CUDA | None |
| OS | macOS 26.6.2 arm64 |
| MediaMTX | v1.20.1 |
| Chromium (harness) | Playwright 151 headless · **SwiftShader** |
| H.264 in harness | supported, smooth=true, **powerEfficient=false** |
| HEVC in harness | unsupported |

See `reports/MACHINE_MEDIA_PERFORMANCE_PROFILE.md`.

## SMOOTH definition (provisional)

A tile is PASS when, over soak S seconds:

- `currentTime` ≥ 0.55·S
- freezes ≤ 2
- packetsLost = 0
- ICE in {connected, completed}
- black-frame sample ratio ≤ 0.25 (when sampled)

## Architecture A — concurrent independent WHEP (VIDEO-ONLY)

| N | Overall | first_frame p50/p95 (ms) | currentTime p50 | eff FPS p50 | Label |
|---:|---|---:|---:|---:|---|
| 1 | **PASS** | 821 / 821 | 17.86 | 15.0 | MEASURED |
| 4 | **PASS** | 2697 / 4007 | 19.79 | 27.1 | MEASURED |
| 6 | **FAIL (timeout)** | — | — | — | MEASURED harness hang |
| 9 | **FAIL (timeout)** | — | — | — | MEASURED harness hang |

### n=4 tile detail (MEASURED)

| Camera | Verdict | currentTime | eff FPS | first_frame_ms | freezes |
|---|---|---:|---:|---:|---:|
| cam01 | PASS | 20.965 | 14.93 | 4171.89999999851 | 0 |
| cam02 | PASS | 20.234 | 29.85 | 3074.10000000149 | 0 |
| cam05 | PASS | 19.34 | 29.89 | 2320.300000000745 | 0 |
| cam04 | PASS | 17.932 | 24.43 | 1428.5 | 0 |

## Hybrid evidence (prior MEASURED)

9 cameras publishing concurrently + 4 sequential browser WHEP decodes: **PASS**
(`var/reports/phase8c/gov/wall9_results.json`). Remaining tiles PUBLISH_ONLY.

## First bottleneck (MEASURED)

**Browser concurrent decode / headless SwiftShader main-thread**, not RTSP→PyAV→MediaMTX for ≤9 H.264 publishers.

Evidence: all 9 MediaMTX paths stayed `ready` with multi-MB `bytesReceived` while the concurrent 6/9-tile Chromium evaluate never returned.

## Latency components (MEASURED vs UNAVAILABLE)

| Component | Value | Label |
|---|---|---|
| First-frame n=1 | ~821 ms | MEASURED |
| First-frame n=4 p50/p95 | ~2697 / 4007 ms | MEASURED |
| Negotiation (n=4 tiles) | [135.4, 134.8, 127.2, 127.9] ms | MEASURED |
| True camera→screen E2E | — | **UNAVAILABLE** (no trusted source timestamps) |

Do not call first-frame latency end-to-end latency.

## Current 30-camera limitation

Honest today:

- **30 managed/registered** tiles: feasible (priority model)
- **≤4 concurrent full WHEP** under headless harness: **PASS**
- **≥6 concurrent full WHEP** under headless harness: **not sustained** (timeout)
- **9 publish + 4 decode**: proven hybrid
- **30 simultaneous full-quality WHEP**: **not achieved** on this machine/harness

## Highest-value next optimization

1. **Architecture C (hybrid wall)** — keep 30 tiles visible; WHEP only for PRIMARY+SECONDARY budget (target 4–8 after headed Metal test); PREVIEW via snapshot/low-cost path already in `ui/app.js`.
2. Measure **headed Chromium/Metal** concurrent ceiling (may raise >4).
3. Only then consider VideoToolbox decode in PyAV relay if CPU profiling shows software decode saturation on publish side.

Do **not** redesign DIRECT_H264 / HEVC_TRANSCODED_H264 paths.

## Reproduce

```bash
python tools/perf_machine_profile.py
python tools/perf_video_only_wall.py --levels 1 4 --seconds 18
```

Artifacts: `var/reports/phase9/performance/`
