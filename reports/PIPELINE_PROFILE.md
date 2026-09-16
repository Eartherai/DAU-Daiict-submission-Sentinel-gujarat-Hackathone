# Pipeline profile

**Measurement:** measured on available project media.

| Stage | Samples | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| decode | 29 | 0.216 | 0.311 | 0.391 |
| pipeline | 29 | 70.506 | 117.742 | 1574.892 |
| flush | 2 | 0.005 | 0.005 | 0.005 |

Throughput: **6.685 frames/s**
Errors: **0**

## Top bottlenecks (measured p95)

1. `pipeline` — 117.742 ms
2. `decode` — 0.311 ms
3. `flush` — 0.005 ms

## Caveats
- CPU/GPU utilisation is not reported because it was not measured.
- Accuracy is not inferred from timing; see detector/tracker reports.
