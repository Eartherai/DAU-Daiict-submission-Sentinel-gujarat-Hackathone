# 30-camera performance certification

Timestamp UTC: `2026-09-16T13:31:23.386874+00:00`  
Overall: **PASS**

## Measured headed Metal concurrent WHEP

| Metric | Value |
|---|---|
| max PASS | 0 |
| max operable (PASS/AMBER) | 12 |
| Applied full-WHEP budget | 8 |

## 30-camera wall design

| Tier | Count (scheduler) | Representation |
|---|---:|---|
| Registered | 30 | management + health |
| Full WHEP | 8 | PRIMARY/SECONDARY live |
| Preview live | remaining | continuous low-cost live / refresh |

Scheduler artifact: `var/reports/phase9/performance/stream_scheduler_30.json`

## Modes

- **VIDEO-FIRST** — maximize full-WHEP budget, AI adaptive
- **AI-FIRST** — reduce concurrent WHEP slightly, full AI on selected cameras

## Path policy (unchanged)

H.264 → DIRECT_H264 · HEVC → HEVC_TRANSCODED_H264

Machine-readable: `/Users/earther/Desktop/Gujarat CCTV/saakshya/var/reports/phase9/performance/wall_30_cert.json`
