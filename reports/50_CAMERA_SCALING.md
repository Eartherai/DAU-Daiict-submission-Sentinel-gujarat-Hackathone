# 50-camera scaling

Timestamp UTC: `2026-09-16T14:07:43.065266+00:00`

## Honesty

- ~30 real government feeds available for evaluation.
- **Do not claim 50 real government cameras.**

## Logical 50

| Layer | 30 real | +20 synthetic | Label |
|---|---|---|---|
| Registry / GIS / health / scheduler | yes | yes | DESIGNED / LOGICAL |
| Full WHEP concurrent | ≤12–16 PASS band | same browser budget | MEASURED |
| Preview live (HLS) | remaining | remaining | MEASURED path |
| Regional NVIDIA NVDEC/NVENC/AI | — | — | **ESTIMATED / untested** |

## Browser ceiling (synthetic control)

| N | PASS | FAIL | Label |
|---:|---:|---:|---|
| 16 | 16 | 0 | MEASURED_SYNTHETIC |
| 20 | 19 | 1 | MEASURED_SYNTHETIC |
| 24 | 19 | 2 | MEASURED_SYNTHETIC |
| 30 | 18 | 5 | MEASURED_SYNTHETIC |

## Regional GPU model (ESTIMATED)

```
Gov RTSP → regional ingest → NVDEC → AI batch
                              └→ NVENC ladder → MediaMTX → command-center WHEP
```

Local M5: headed Metal browser + VideoToolbox encode where beneficial.
