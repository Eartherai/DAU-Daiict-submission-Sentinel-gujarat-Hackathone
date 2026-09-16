# 30-camera final performance

Timestamp UTC: `2026-09-16T14:07:43.065266+00:00`

## Full-WHEP

| Layer | Result | Label |
|---|---|---|
| Gov headed peak PASS tiles | ~12 | MEASURED (prior) |
| Synthetic headed n=16 | **16/16 PASS** | MEASURED_SYNTHETIC |
| Synthetic headed n=20 | 19P/1F | MEASURED_SYNTHETIC |
| Synthetic headed n=24 | 19P/3A/2F | MEASURED_SYNTHETIC |
| Synthetic headed n=30 | 18P/7A/5F | MEASURED_SYNTHETIC |
| Live HLS preview | **PASS** | MEASURED |
| Prewarm speedup | **7.74×** | MEASURED_SYNTHETIC |
| Gov RTSP now | 401 BLOCKED | MEASURED |

## Production recommendation

1. Budget **12–16 concurrent full WHEP** (gov source-limited → synthetic browser-proven).
2. Remaining cameras: **live HLS PREVIEW** (sequence-advancing).
3. Prewarm pool for PRIMARY/SECONDARY promotion.
4. VIDEO-FIRST: maximize full WHEP toward 16; AI adaptive.
5. AI-FIRST: hold ≥8 full WHEP; 4+4 full AI; rest low cadence.

## Unacceptable avoided

- Not settling at 4/8 without exhausting negotiation + proving higher ceiling.
- Not using static screenshots as live.
- Not claiming 30×1080p60 government WHEP (not MEASURED).

Machine-readable: `var/reports/phase10/performance/`
