# 30-camera pipeline: baseline versus adaptive scheduler

These are **synthetic-catalogue measurements** using the available six local
media clips. They are not a 30-government-camera result and do not satisfy the
official approximately-50-camera government gate.

| Run | Target | Catalogue | Media processed | Frames | Throughput | Errors |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 30 | 6 | 6 | 42 | 4.583 fps | 0 |
| Adaptive | 30 | 6 | 6 | 42 | 8.181 fps | 0 |

The adaptive run was faster in this short CPU measurement, but the result is
not a universal speedup claim: process startup, model warm-up, and the small
six-clip corpus materially affect this sample. Detection, OCR, tracking, and
observation counts were zero in both runs because this short sample did not
produce qualifying detections. A longer run on the complete corpus is required
for an accuracy/latency trade-off decision.

## Interpretation

- **Verified:** scheduler integration, bounded admission, independent OCR and
  re-identification cadence, and reproducible benchmark output.
- **Measured here:** 8.181 versus 4.583 frames/s on the named host/corpus.
- **Not verified:** simultaneous 30-camera government analytics.
- **Not inferred:** CPU/GPU utilization or accuracy without corresponding
  ground truth.
