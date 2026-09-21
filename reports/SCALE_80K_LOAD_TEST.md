# Scalability and load test — 80,000 cameras

Generated 2026-09-21 14:54:12Z. Every figure below was measured by this script on a
throwaway database; none is extrapolated.

## Registry plane, at statewide scale

| Operation | Result |
|---|---:|
| Bulk onboarding of 80,000 cameras | **1.305s** (61,305/s) |
| Registry gap analysis (all 80,000) | **171.3 ms** |
| Capability grading summary | 269.0 ms |
| Map viewport, zoom 11 → 1,665 features | 399.7 ms |
| Single camera lookup | **0.7 ms** |
| Department filter over the whole estate (80,000 rows) | 648.8 ms |
| Database size | 58.01 MB |

The map viewport is a bounded query rather than a full dump: it returns
1,665 features from 80,000 cameras, so the cost of
drawing the map does not grow with the estate.

## What this does not prove

Registry rows say nothing about video or inference, and it would be
dishonest to present the numbers above as statewide readiness.

- **Video plane.** The wall holds a bounded number of concurrent WHEP
  sessions, and the upstream grid refuses further sessions under churn.
  Statewide viewing is a regional-fan-out problem, not a registry one.
- **AI plane.** Inference is the real constraint. Measured on this host,
  CPU-only: four cameras at roughly 1.4 fps each, aggregate ~5.6 fps,
  P50 around 170 ms and P95 up to 1.5 s. Scaling that to a meaningful
  fraction of the estate needs GPU capacity, not more registry rows.
- **Storage.** The registry is metadata. Footage retention, hot/warm/
  cold tiering and the bandwidth to move it are sized separately and are
  not exercised here.

## What the numbers imply for sizing

The registry is not the bottleneck at statewide scale and does not need
sharding for camera metadata. Two findings matter more:

1. **The AI plane was waiting on frames, not saturating CPU.** Moving
   from one camera to four raised aggregate throughput roughly sixfold
   while per-camera latency stayed flat. Ingest concurrency, not raw
   inference speed, is the first thing to size.
2. **A viewport query is already bounded**, so the map and the gap
   report scale with what is being looked at rather than with the
   estate.

This run used SQLite. The store abstracts its backend, and the
PostgreSQL + PostGIS deployment the challenge suggests is the
appropriate target for a statewide estate; that migration has not been
exercised here and should not be claimed.
