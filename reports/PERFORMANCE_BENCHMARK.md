# Performance benchmark

This report distinguishes measured artifacts from architecture projections.

## Measured artifacts already in the repository

| Workload | Result | Source |
|---|---|---|
| 50 logical camera decode/load run | 50 requested, 44 streaming, 52,637 frames, 0 decoder errors, 6 cameras failed mid-run | `var/reports/camera_load.json` |
| Consumer analytics sample | 1,019 frames analyzed; approximately 11.4 frames/s per process in the recorded run | `var/reports/camera_load.json` |
| API latency | In-process TestClient against demo SQLite; route-specific p50/p95/p99 | `var/reports/api_latency.json` |
| Live evaluation search/trajectory | 0.017 s for the recorded ten-stage evaluation | `var/reports/live_evaluation.json` |
| Security | 14/14 adversarial controls passed in the recorded scorecard | `var/reports/security_scorecard.json` |

The 50-camera result is a stream/decode/load measurement, not a claim that one
CPU process performs full-resolution analytics on 50 feeds. Memory, inference
backend, resolution, sampling policy, and hardware must be reported alongside
any new run.

## Reproduction

```bash
make loadtest
make perf
make queryplan
make judge-score
```

`make loadtest` uses the local MediaMTX replica. It does not contact the
government grid. Government-feed measurements are produced by the `live-*`
commands and must retain their provenance.

## Known bottlenecks

The recorded CPU run identifies analytics throughput and single-process memory
as earlier bottlenecks than stream decode. The statewide 80,000-camera numbers
in `docs/SCALE_MODEL.md` are modeled sizing assumptions, not benchmark results.
