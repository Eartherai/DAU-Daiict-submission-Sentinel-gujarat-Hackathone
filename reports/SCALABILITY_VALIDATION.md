# Scalability validation

## Measured

The local load artifact requested 50 logical cameras and delivered 52,637
frames with zero decoder errors; 44 streams were active at the recorded
measurement point and six failed mid-run. Analytics sampled 1,019 frames at
approximately 11.4 frames/s per process. This validates bounded decode/fan-out
behavior, not statewide full-video processing.

## Designed

`docs/SCALE_MODEL.md` defines edge/regional nodes, metadata-first transport,
local buffering, central search/correlation, hot/warm/cold storage, and the
arithmetic rejecting centralization of 80,000 full-rate streams. The 80,000
camera figures are explicitly modeled.

## Next validation boundary

The next meaningful benchmark is 50-camera end-to-end analytics with an
explicit sampling policy, memory ceiling, inference backend, and alert latency
measurement. It must be reported separately from decode readiness. Central
PostgreSQL/PostGIS/pgvector, failover, and disaster recovery require a target
deployment environment and are not claimed as locally measured.
