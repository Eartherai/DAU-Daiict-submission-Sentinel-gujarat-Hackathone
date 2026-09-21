# Final visual QA (30-camera layouts + product chrome)

Government tile appearance was scored from the headed Direct WHEP wall (MEASURED_REAL), not from substituting synthetic tiles. Product-shell screenshots are under `var/reports/final/ui/`.

## Layouts (headed WHEP, GOVERNMENT cameras only)

| Layout | Soak | Verdict | Why | Artifact |
|---|---|---|---|---|
| 12 | 30 s | **AMBER** | 9/12 browser-visible; 8 LIVE, 1 PREVIEW, 1 NO_SIGNAL, 2 DEGRADED | `var/reports/final/live/wall_12_30s.json` |
| 16 | 30 s | **AMBER** | 13/16 visible; 8 LIVE, 5 PREVIEW, 1 NO_SIGNAL | `var/reports/final/live/wall_16_30s.json` |
| 25 | 30 s | **AMBER** | 11 visible; 6 RTSP_ONLY_AI kept (not NO_SIGNAL while RTSP can be live) | `var/reports/final/live/wall_25_30s.json` |
| 30 | 30 s | **AMBER** | 10 visible; 11 RTSP_ONLY_AI, 4 NO_SIGNAL | `var/reports/final/live/wall_30_30s.json` |
| 30 | 60 s | **AMBER** | Best: 15 visible, 11 LIVE, 4 PREVIEW, 6 RTSP_ONLY_AI, **0 NO_SIGNAL** | `var/reports/final/live/wall_30_60s.json` |

Criteria (black/green/macroblock/frozen/stale LIVE/blank/domain/name/status/latency/AI/overlay/map/spinner) cannot all be marked PASS: several tiles are PREVIEW or RTSP_ONLY_AI, and first-frame P95 on the 30@60 wall is 52 s. **Not perfect.**

Product 12/16/25/30/50 screenshots: `var/reports/final/ui/*-camera*.png` — AMBER (grid min-height fixed after capture; stills on demo store, not Sentinel WHEP).

## Per-tile honesty

- LIVE only when WHEP decoded.
- PREVIEW when frames exist but FPS/continuity is weak.
- RTSP_ONLY_AI when RTSP decoded and WHEP did not.
- NO_SIGNAL only when both planes failed.
- DEGRADED for freeze/loss/ICE issues on an otherwise visible tile.
