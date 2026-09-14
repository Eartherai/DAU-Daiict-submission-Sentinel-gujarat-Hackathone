# ADR-002: RT-DETRv2-R18 for vehicle detection
**Status:** accepted **Date:** 2026-09-01

## Context
Need car / motorcycle / bus / truck detection, CPU-viable for development and
GPU-scalable for deployment, in a government platform served over a network.

## Options
1. Ultralytics YOLO (v8/v11/26) — best ecosystem, **AGPL-3.0**.
2. **RT-DETRv2-R18** (`PekingU`) — Apache-2.0, 81 MB, transformers-native.
3. RF-DETR-base — Apache-2.0, first real-time model past 60 mAP COCO, 129 MB.
4. D-FINE — Apache-2.0, strong, no advantage here.

## Evaluation
Ultralytics states AGPL-3.0 covers the trained models, not only training code.
For a network-served government platform this implies an obligation over the
larger work — unacceptable, and unacceptable *silently* is worse. RT-DETRv2-R18
is Apache-2.0, has 405k downloads, and its COCO class set gives the four vehicle
classes without retraining. RF-DETR is stronger but larger; registered as a
GPU-profile candidate.

## Decision
RT-DETRv2-R18 as primary; RF-DETR-base as GPU candidate. Ultralytics **blocked
in code** via the model router's licence gate.

## Trade-offs accepted
Slower than YOLO on CPU. Acceptable: detection runs at 0.5–6 fps per camera
under the analytics budget, not at full frame rate.

## Revisit when
Benchmarked on the GPU profile, or if RT-DETRv4 gains production adoption.
