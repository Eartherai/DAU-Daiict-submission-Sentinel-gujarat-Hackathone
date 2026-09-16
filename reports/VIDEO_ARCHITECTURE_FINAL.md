# Video architecture (final for local M5 demo)

Timestamp: cycle after headed Metal benchmarks  
Labels: **MEASURED** where cited from `var/reports/phase9/performance/`

## What changed vs the invalid “4 is the limit”

| Harness | n=4 | n=6 | n=9 | n=12 |
|---|---|---|---|---|
| Headless SwiftShader | PASS | **TIMEOUT hang** | **TIMEOUT hang** | — |
| **Headed Metal** | AMBER (3P/1A) | AMBER (4P/1A/1F) | AMBER (7P/0A/2F best) | AMBER (5P/4A/3F) |

WebGL headed: `ANGLE Metal Renderer: Apple M5`  
H.264/HEVC MediaCapabilities headed: `powerEfficient=true` (**MEASURED**)

**4 is not the machine limit.** It was the SwiftShader harness limit.

## Production wall architecture (local)

```
Government RTSP
  → PyAV ingest (env credentials only)
  → MediaMTX fanout
       ├─ VIDEO PLANE (browser)
       │     PRIMARY / SECONDARY → full WHEP (budget ≤ headed operable)
       │     PREVIEW → live low-cost representation (not static screenshot)
       └─ AI PLANE (separate consumers)
             adaptive cadence by tier
```

Path policy (unchanged):

- H.264 → `DIRECT_H264`
- HEVC → `HEVC_TRANSCODED_H264`

## Measured budgets (this M5, headed Chromium)

| Budget | Value | Label |
|---|---:|---|
| Max concurrent full WHEP operable (PASS/AMBER wall) | **12** | MEASURED |
| Best concurrent PASS tiles in one wall | **7** (of 9) | MEASURED |
| Recommended demo full-WHEP budget | **8** | DESIGNED from MEASURED |
| Registered cameras | **30** | DESIGNED |
| Preview live slots | **18** | DESIGNED |

Failures at high N are **isolated tile FAIL** (setup timeout / ICE), not wall-wide hangs.

## Operator modes

| Mode | Video | AI |
|---|---|---|
| VIDEO-FIRST | full WHEP budget (8) | adaptive low |
| AI-FIRST | reduced WHEP (≥4) | full on selected cameras |

## 50-camera honesty

- 30 real government feeds + synthetic control slots for registry/GIS/scheduler
- Do **not** claim 50 government streams

## Next bottlenecks (ordered)

1. Concurrent WHEP negotiation / late first-frame under load (MEASURED)
2. Software PyAV decode on publish side under 12+ (suspect; VT decode not yet wired)
3. Preview live representation implementation in UI (design ready; wire next)
