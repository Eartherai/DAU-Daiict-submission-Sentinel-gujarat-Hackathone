# Scalability and load test — 80,000 cameras

Generated 2026-09-28 04:35:18Z. The registry table below was measured by this script on a
throwaway database of synthetic camera rows; none is a live stream.

## Registry plane, at statewide scale

| Operation | Result |
|---|---:|
| Bulk onboarding of 80,000 cameras | **1.388s** (57,647/s) |
| Registry gap analysis (all 80,000) | **181.7 ms** |
| Capability grading summary | 336.4 ms |
| Map viewport, zoom 11 → 1,665 features | 426.2 ms |
| Single camera lookup | **0.69 ms** |
| Department filter over the whole estate (80,000 rows) | 651.3 ms |
| Database size | 58.05 MB |

The map viewport is a bounded query rather than a full dump: it returns
1,665 features from 80,000 cameras, so the cost of
drawing the map does not grow with the estate.

## What this does not prove

Registry rows say nothing about video or inference, and it would be
dishonest to present the numbers above as statewide readiness.

- **Video plane.** CONTROL ROOM opens up to 30 direct WHEP sessions;
  OPTIMIZED VIEW holds at most 12 near the viewport (`ui/app.js`). These
  local policies are not Sentinel limits: availability varies with shared
  load (`docs/SENTINEL_SUPPORT_CLARIFICATION.md`). This run opens no streams.
- **AI plane.** The historical report recorded four selected cameras at
  roughly 1.4 fps each (~5.6 aggregate), before the current GPU recogniser.
  That measurement is not repeated by this registry-only harness. The GPU
  path is separately measured in `var/reports/pipeline_device.json` and
  `var/reports/ocr_indian_eval.json`. It does not analyse every registry row.
- **Storage.** These are synthetic camera metadata rows, not observations
  or retained video. Retention and media bandwidth are sized separately.

## What the numbers imply for sizing

Bounded viewport output keeps drawing manageable; gap analysis still scans
registry metadata, and this single-host result does not establish distributed
capacity. Current demonstration hardware limits simultaneous deep-inference
concurrency. Analytics workers scale horizontally, so additional GPU nodes
raise concurrent inference throughput without redesigning ingest, event,
watchlist, GIS or investigation services. Cluster capacities are MODELLED.

This registry run used SQLite. PostgreSQL 18 + PostGIS 3.6 carries the same
schema; the government store was copied and served there with both chains
verified (`var/reports/store_engines.json`, `docs/HLD.md` §4.10). A district-scale
PostgreSQL deployment with replication and failover has not been exercised
here and should not be claimed.
