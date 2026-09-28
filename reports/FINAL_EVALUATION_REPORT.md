# Final evaluation report - Models 1-4

Historical measurement record. Concurrent live counts below are **MEASURED
DURING A TEST WINDOW**, not sandbox limits. Current support guidance and wall
policies: `docs/SENTINEL_SUPPORT_CLARIFICATION.md`.

Generated 2026-09-16T22:37:54.371769+00:00 UTC. Finished 2026-09-16T22:38:15.948127+00:00 UTC.

Unit tests: exit 0 in 0.7 s.

## Strongest measured result

| Model | Result |
|---|---|
| 1 | 80,000 synthetic registry records; lookup P50 0.044 ms / P95 0.0551 ms; insert 0.6686 s |
| 2 | 15 government tiles visible (fresh 60s Direct WHEP when present); first-frame P50 25954.04999999702 ms |
| 3 | 50 adapters isolated; bus 2036798.4 ev/s MEASURED_IN_PROCESS |
| 4 | own-file decode + controlled watchlist 1.701 ms DEMO/CONTROLLED TEST |

## Bottleneck

| Model | Bottleneck |
|---|---|
| 1 | shipping 80k unclustered markers to the browser |
| 2 | Sentinel upstream WHEP concurrency (fresh 15 visible / 30 at 60s; prior 19 at 120s) |
| 3 | no live departmental VMS; in-process bus ≠ Kafka |
| 4 | GPU/utilization and own-feed detector FPS not attached to this API process |

## Measured workload sizes during these test windows

- Registry: 80,000 synthetic SQLite rows (MEASURED_SYNTHETIC)
- Government live wall: 15 browser-visible / 30 registered at 60s Direct WHEP; 19 at prior 120s (MEASURED_REAL)
- Logical wall: 50 = 30+2+18 (MEASURED_SYNTHETIC composition)
- Federation: 50 DEMO/TEST adapters isolated (MEASURED_SYNTHETIC)
- Event bus: 2036798.4 events/s MEASURED_IN_PROCESS
- Own-feed decode: local MP4 PyAV (MEASURED_OWN_FEED)
- 80k live video / 80k live inference / 50 government live feeds: **not claimed**

## Demo-ready configuration

{
  "wall": "30 GOVERNMENT + 2 OWN_FEED (OWN-PEOPLE, OWN-TRAFFIC) + 18 SYNTHETIC_CONTROL",
  "intelligence": "INTELLIGENCE mode on the two own feeds",
  "system": "SYSTEM \u2192 Connected systems (DEMO / TEST)",
  "maps": "GOOGLE_MAPS_API_KEY from gitignored .env.local; loader /maps/google-api; key not in /config",
  "commands": [
    "make live-serve",
    "OPERATIONS \u2192 30-camera government wall (Direct Sentinel WHEP)",
    "OPERATIONS \u2192 50-CAMERA WALL (logical badges)",
    "INTELLIGENCE \u2192 OWN-PEOPLE / OWN-TRAFFIC (file replay)",
    "TRACK TARGET / ROUTE / GIS / EVIDENCE on a watchlist plate",
    "SYSTEM \u2192 Connected systems (DEMO / TEST)"
  ]
}

## Remaining external limitations

- Sentinel shared-load availability (EXTERNAL_DEPENDENCY; no fixed participant-facing limit confirmed)
- Departmental VMS credentials (EXTERNAL_DEPENDENCY)
- GPU utilization sampling (NOT_MEASURED)
- Own-feed ANPR accuracy without ground truth (NOT_MEASURED)
- Kafka/RabbitMQ production bus (DESIGNED)
