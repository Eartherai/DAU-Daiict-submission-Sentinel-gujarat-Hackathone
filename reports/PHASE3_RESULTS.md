# Phase 3 results

Phase 3 added measured backend profiling, detector/tracker availability
benchmarks, adaptive baseline comparisons, and a bounded video-wall mode. This
report separates verified implementation from measurements that remain
environment- or data-limited.

## Pipeline profile

Run: `tools/profile_pipeline.py --max-seconds 1 --max-cameras 2`

| Stage | p50 | p95 | p99 |
|---|---:|---:|---:|
| Decode | 0.216 ms | 0.311 ms | 0.391 ms |
| Pipeline | 70.506 ms | 117.742 ms | 1,574.892 ms |
| Flush | 0.005 ms | 0.005 ms | 0.005 ms |

Measured top bottleneck: **analytics pipeline execution**, not decode or flush.
The run processed 29 frames at 6.685 frames/s with zero pipeline errors.
CPU/GPU utilization and per-stage device counters were not collected and are
not claimed.

## Detector benchmark

Measured on `C-014.mp4` and `C-021.mp4`, six frames per registered candidate:

| Detector | p50 | p95 | FPS | Detections |
|---|---:|---:|---:|---:|
| `vehicle-rtdetrv2-r18@0.1.0` | 47.826 ms | 229.689 ms | 11.253 | 0 |
| `vehicle-rfdetr-base@0.1.0` | 72.508 ms | 101.793 ms | 12.951 | 0 |

No vehicle bounding-box ground truth is present, so precision/recall are
**unverified**. YOLO26n/s/m and other unregistered candidates were not
installed or benchmarked blindly; they remain an evaluation task requiring
compatible weights and a licensing/runtime decision.

## Tracker benchmark

The in-tree PTS-aware ByteTracker measured 20 frames at 3,072.255 FPS with
0.208 ms p50 and 0.378 ms p95 latency on the named motion-input sample.
DeepSORT, OC-SORT, and BoT-SORT were checked and were unavailable in the
environment. Track accuracy is unverified because no identity/box ground truth
exists.

## Adaptive scheduler

The scheduler supports `NORMAL`, `HIGH_PRIORITY`, `ALERT`, and `FORENSIC`.
It independently gates sampling, detector inference, OCR, and re-identification
cadence, with bounded priority-aware admission and a synchronous evidence-safe
fallback when the queue is full.

Short local synthetic-catalogue comparison:

| Scenario | Baseline | Adaptive |
|---|---:|---:|
| Target 30, six local clips | 4.583 fps | 8.181 fps |
| Target 50, six local clips | 5.850 fps | 10.606 fps |

Both runs processed 42 frames with zero errors and zero qualifying detections.
These are smoke measurements, not claims of government-camera accuracy or
simultaneous 30/50-camera analytics.

## Frontend/video wall

Implemented:

- 4/9/16/30 wall modes;
- lazy wall selection and focus mode;
- `PRIMARY`, `SECONDARY`, `PREVIEW`, and `INACTIVE` priorities;
- shared snapshot/blob caching to avoid duplicate requests;
- visible priority/status metadata;
- WHEP fallback and existing authentication preserved.

`node --check ui/app.js` passes. Browser CPU, memory, rendered FPS, and network
throughput were not instrumented, so quantitative frontend improvement is
unverified.

## Government feed and Model 4 status

- **Verified:** 30 currently reachable/probed government cameras and the
  catalogue-driven N-camera architecture.
- **Verified:** 50 logical decoder/fan-out and benchmark target path.
- **Unverified:** 50 simultaneous government-camera analytics.
- **Verified on own/demo architecture:** selected-camera central analytics
  pattern; statewide full-video centralization remains intentionally rejected.
- **Not fabricated:** no government cross-camera vehicle repeat is claimed.

## Remaining P0/P1 work

1. Acquire the authenticated approximately-50-camera catalogue and run the
   complete government benchmark.
2. Add real stage-level queue/drop/notification instrumentation and browser
   performance telemetry.
3. Benchmark compatible YOLO26/PaddleOCR/BoT-SORT candidates only after
   dependencies, weights, and licensing are verified.
4. Complete the integrated Follow Vehicle route/timeline/evidence workflow and
   central-analytics demo narrative.
