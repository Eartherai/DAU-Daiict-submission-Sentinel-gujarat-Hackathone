# Computer Vision SOTA Review — 2025/2026

**Date:** 1 September 2026
**Rule applied:** newest ≠ best. Each area answers five questions, and the last
one is the only one that changes what we build.

---

## Summary table

| Area | Best research | Best open impl. | Best production | **Best for us** |
|---|---|---|---|---|
| Object detection | RT-DETRv4 (ECCV 2026), RF-DETR (ICLR 2026) | `PekingU/rtdetr_v2_r18vd` (Apache-2.0) | NVIDIA DeepStream + TensorRT | **RT-DETRv2-R18** — Apache-2.0, 81 MB, transformers-native, COCO classes give vehicle types free |
| Small-object detection | tiling / SAHI-style inference | — | — | **Resolution normalisation** (measured: 1080p native → 0 detections; downscaled → 0.66) |
| Plate detection | — | `open-image-models` yolo-v9-t-640 (MIT) | commercial ALPR | **yolo-v9-t-640** — measured 0.83–0.86 vs 0.30–0.44 for the "larger" -s-608 |
| Plate OCR | PP-OCRv5 fine-tunes | `Awiros/anpr-ocr` (Apache-2.0, India-specific, dual-row) | commercial ALPR | **`cct-s-v2-global` now** (10 slots); **Awiros is the upgrade path** |
| Vehicle Re-ID | transformer + metric learning; IBNT-Net reports 84.9 mAP / 97.7 R1 on VeRi-776 | `fast-reid` (stale), CLIP-ReID (stale) | Genetec ML Core | **DINOv2 embedding as a ranking signal only** — see §2 |
| Multi-query Re-ID | VCNet (TIP 2023) | none production | — | **Quality-weighted mean pooling** — no training, degrades gracefully |
| Multi-camera tracking | Spatial-Temporal Multi-Cuts (+14% IDF1 CityFlow) | — | AI City Challenge entries | **Camera-link + temporal gating** — the multi-cut method needs calibration we lack |
| VLM / long video | Qwen3-VL (256K ctx, 2h video) | `QwenLM/Qwen3-VL` (Apache-2.0) | — | **Tier-3 description only, GPU-only, never a decision-maker** |
| Uncertainty / calibration | Platt scaling, temperature scaling | scikit-learn | — | **Transparent weighted scoring labelled "engineering score"** until a labelled held-out set exists |

---

## 1. Detection

RT-DETRv4 (ECCV 2026) and RF-DETR (ICLR 2026, first real-time detector past
60 mAP COCO) are the current frontier, both Apache-2.0. RT-DETRv3 reports
+2.0–4.4% over comparable YOLO-S variants.

**Decision: RT-DETRv2-R18.** Not the newest, not the largest. It is Apache-2.0,
81 MB, natively supported by `transformers`, has 405k downloads, and its COCO
class set gives car/motorcycle/bus/truck without retraining. RF-DETR-base is
registered as a candidate for the GPU profile.

**Rejected: every Ultralytics YOLO.** AGPL-3.0, and Ultralytics states it covers
trained models — not merely training code.

**The measured lesson that outranks all of the above:** for objects as small as a
plate at 80 px, *input resolution normalisation* mattered more than any model
choice. A 1920×1080 frame returned zero detections where the same frame
downscaled returned 0.66 confidence. On a heterogeneous estate, unnormalised
resolution silently decides whether analytics work at all.

## 2. Vehicle Re-ID — the finding that changed the architecture

**arXiv 2606.01981, *Generalization Limits in Vehicle Re-Identification* (2026)**
reports **20–40% degradation** moving a trained model to a different camera
network, attributed to dataset bias, illumination and viewpoint variation, and
domain gap. Its practical recommendations are site-specific labelled data,
fine-tuning, and continuous monitoring — none of which we can do before
7 September.

Published benchmark numbers for context (IBNT-Net, 2025): 84.9 mAP / 97.7 Rank-1
on VeRi-776. **These are in-domain numbers and should never be quoted as what we
expect.** Applying the paper's stated degradation range puts realistic
out-of-domain expectations far lower, on an estate materially harder than any
Re-ID benchmark.

**Architectural consequences:**

1. Appearance is a **ranking** signal, never an identity assertion.
2. **Graph and temporal constraints prune before ANN runs**, because physics
   does not suffer domain shift.
3. Every appearance-derived result is presented as a candidate **for human
   verification**, with its decomposition visible.
4. `facebook/dinov2-base` (Apache-2.0, 2.8M downloads) is the baseline embedder.
   A task-specific Re-ID model is adopted **only** if our harness beats DINOv2
   on Recall@K — and the HF survey found no task-specific vehicle Re-ID model
   with more than zero downloads or any published evaluation.

## 3. Multi-camera tracking

*Spatial-Temporal Multi-Cuts* (arXiv 2410.02638) solves single- and
multi-camera association in one combined min-cost multicut step using a GPU RAMA
solver, fully online, +14% IDF1 on CityFlow and +25% on Synthehicle. It is the
strongest method reviewed.

**It requires bird's-eye-view ground-plane positions.** Gujarat has no
calibration for these cameras and will not acquire it for 80,000 devices.

**Decision: calibration-free by design.** We use the **Camera Link Model**
family (established in AI City Challenge work since ~2019–2021): learn entry/exit
zone transitions and travel-time distributions from observed co-occurrences, then
use them to gate association. This is **N1 — known research** and we say so. The
literature also notes vehicles have lower appearance variance than people, which
makes uncalibrated appearance matching more viable for vehicles than persons.

`CalibFree` (arXiv 2605.09245) confirms calibration-free MCMOT is an active
direction, but it is research-stage and person-focused.

## 4. Trajectory inference

Established solvers for the association step: min-cost max-flow, lifted multicut,
k-shortest paths, Hungarian assignment, hierarchical/correlation clustering.

**Decision: k-shortest-path over a time-dependent transition graph, with a
Hungarian assignment step per camera pair.** Rationale: explainable to a jury,
runs in milliseconds at 50 cameras, and produces *ranked hypotheses with stated
contradictions* rather than a single opaque answer. A learned ranker is deferred
until officer-confirmation data exists (§7).

Rejected for now: GNN-based association. Will not train on hours of data, is not
explainable, and a deterministic graph filter captures most of the benefit.

## 5. Multi-query and quality-aware retrieval

VCNet (TIP 2023, arXiv 2305.15764) conditions on viewpoint to combine multiple
query images. Sound, unimplemented in production, and inherits §2's problem.

**Decision: quality-weighted mean pooling** over an identity's observations,
where weights come from the observation quality vector. Requires no training,
has no domain-shift failure mode of its own, and degrades to single-observation
behaviour when only one good crop exists. Attention pooling and learned
aggregation are deferred.

## 6. VLM

Qwen3-VL (Apache-2.0, 2B–235B, 256K context expandable to 1M, native video to
~2 hours) is the current open frontier.

**Decision: Tier-3 forensic description only.** GPU-only, never on the critical
path, output treated as untrusted data. Not a plate matcher, not a watchlist
engine, not a threat classifier. The core test case must pass with it disabled.

## 7. Uncertainty and human feedback

Calibration (Platt / temperature scaling) is standard and cheap — but it needs a
labelled held-out set we do not have. **Until then, the UI must say "engineering
score", not "probability".** Claiming calibrated probability without a
calibration set is exactly the kind of overclaim this project exists to avoid.

Officer confirmations (accept / reject / correct plate / correct route) are the
natural label source. Design the capture now, defer the learned ranker. No online
retraining during operations.
