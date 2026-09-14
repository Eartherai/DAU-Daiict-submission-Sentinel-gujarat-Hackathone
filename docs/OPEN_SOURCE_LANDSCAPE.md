# Open-Source Landscape

**Date:** 1 September 2026  
**Method:** GitHub API, **55 repositories**, audited 1 September 2026.
Star count is reported but is **not** a decision criterion — maintenance, licence
and fitness are. `days` = days since last push at audit time; ⚠ marks >365.

**Legend:** `ADOPT` in the build · `CANDIDATE` benchmark first · `REFERENCE` read, do not depend on ·
`DEFER` needs hardware we lack · `REJECT` with reason · `REJECT - LICENCE` blocked by policy

## Video infrastructure

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `FFmpeg/FFmpeg` | 63,824 | **non-SPDX** | 2026-08-31 | 0 | 3 | **ADOPT (indirect)** | Via PyAV. GPL build used as an external build-time tool only. |
| `blakeblackshear/frigate` | 35,527 | MIT | 2026-08-31 | 0 | 159 | **REFERENCE** | Excellent NVR; wrong shape for a federation layer. |
| `bluenviron/mediamtx` | 19,982 | MIT | 2026-08-31 | 0 | 195 | **ADOPT** | Sandbox replica + own-feed demo server. Pushed same day as audit. |
| `AlexxIT/go2rtc` | 14,078 | MIT | 2026-07-13 | 49 | 897 | **REJECT** | 897 open issues; MediaMTX covers the need. |
| `GStreamer/gstreamer` | 3,300 | **non-SPDX** | 2026-08-31 | 0 | 14 | **ADOPT (indirect)** | Via PyAV/FFmpeg. Direct GStreamer only on the GPU profile. |

## Detection

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `ultralytics/ultralytics` | 61,130 | AGPL-3.0 | 2026-08-31 | 0 | 87 | **REJECT - LICENCE** | AGPL-3.0; Ultralytics states it covers trained models. |
| `facebookresearch/detectron2` | 34,692 | Apache-2.0 | 2026-08-19 | 12 | 588 | **REJECT** | Stale. Not needed. |
| `open-mmlab/mmdetection` | 32,897 | Apache-2.0 | 2024-08-21 | 740 ⚠ | 1,962 | **REJECT** | Stale (>2y). Heavy toolchain. |
| `roboflow/rf-detr` | 9,112 | Apache-2.0 | 2026-08-25 | 6 | 102 | **CANDIDATE** | Apache-2.0, ICLR 2026. GPU-tier candidate. |
| `lyuwenyu/RT-DETR` | 5,481 | Apache-2.0 | 2026-08-17 | 14 | 419 | **ADOPT (weights)** | Apache-2.0 via PekingU HF checkpoints. |
| `Peterande/D-FINE` | 3,306 | Apache-2.0 | 2026-08-19 | 12 | 162 | **REFERENCE** | Apache-2.0, strong; no advantage over RT-DETRv2 here. |
| `RT-DETRs/RT-DETRv4` | 603 | Apache-2.0 | 2026-07-06 | 56 | 17 | **WATCH** | ECCV 2026, Apache-2.0, small community so far. |

## Tracking

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `mikel-brostrom/boxmot` | 8,285 | AGPL-3.0 | 2026-08-27 | 4 | 3 | **REJECT - LICENCE** | AGPL-3.0. The default trap. |
| `FoundationVision/ByteTrack` | 6,659 | MIT | 2024-06-19 | 803 ⚠ | 331 | **REFERENCE** | MIT but stale; 331 open issues. |
| `roboflow/trackers` | 3,727 | Apache-2.0 | 2026-08-31 | 0 | 28 | **ADOPT** | Apache-2.0, maintained, clean reimplementations. |
| `NirAharon/BoT-SORT` | 1,525 | MIT | 2024-08-08 | 753 ⚠ | 79 | **REFERENCE** | MIT but stale. Use the maintained reimplementation. |
| `noahcao/OC_SORT` | 1,135 | MIT | 2026-04-21 | 131 | 25 | **CANDIDATE** | MIT, maintained. Good for occlusion-heavy scenes. |

## ANPR / OCR

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `PaddlePaddle/PaddleOCR` | 88,546 | Apache-2.0 | 2026-07-22 | 40 | 233 | **DEFER** | Apache-2.0. Needed only if we adopt Awiros India OCR. |
| `ankandrew/fast-alpr` | 788 | MIT | 2026-03-16 | 168 | 2 | **ADOPT** | MIT, 2 open issues. In production use here. |
| `ankandrew/fast-plate-ocr` | 737 | MIT | 2026-03-14 | 169 | 1 | **ADOPT** | MIT. Provides cct-s-v2-global (10 plate slots). |
| `ankandrew/open-image-models` | 109 | MIT | 2026-07-27 | 35 | 1 | **ADOPT** | MIT. Provides yolo-v9-t-640 plate detector. |

## Re-ID / embedding

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `facebookresearch/dinov2` | 13,284 | Apache-2.0 | 2026-06-03 | 89 | 297 | **ADOPT (baseline)** | Apache-2.0. Appearance embedding baseline. |
| `KaiyangZhou/deep-person-reid` | 4,904 | MIT | 2026-01-09 | 234 | 163 | **REFERENCE** | MIT. Person-focused. |
| `JDAI-CV/fast-reid` | 3,983 | Apache-2.0 | 2024-07-30 | 762 ⚠ | 18 | **WEIGHTS ONLY** | Apache-2.0 but stale. Vendor inference; do not depend on the framework. |
| `Syliz517/CLIP-ReID` | 520 | MIT | 2023-11-21 | 1014 ⚠ | 47 | **REFERENCE** | MIT, ~3y stale. Research reference. |

## Vision-language

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `QwenLM/Qwen3-VL` | 19,873 | Apache-2.0 | 2026-01-30 | 213 | 425 | **CANDIDATE - GPU ONLY** | Apache-2.0. Tier-3 description only. |
| `OpenGVLab/InternVideo` | 2,372 | Apache-2.0 | 2026-07-02 | 60 | 147 | **REFERENCE** | Apache-2.0. Long-video research. |
| `DAMO-NLP-SG/VideoLLaMA3` | 1,178 | Apache-2.0 | 2025-08-14 | 382 ⚠ | 71 | **REFERENCE** | Stale. |

## Vector search

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `milvus-io/milvus` | 45,908 | Apache-2.0 | 2026-08-31 | 0 | 1,295 | **ADOPT (statewide)** | Apache-2.0. Billion-scale horizontal sharding. |
| `facebookresearch/faiss` | 40,832 | MIT | 2026-08-31 | 0 | 282 | **REFERENCE** | MIT. Library, not a service. |
| `qdrant/qdrant` | 34,295 | Apache-2.0 | 2026-08-31 | 0 | 710 | **ADOPT (pilot+)** | Apache-2.0. 2-4x faster on FILTERED queries; our workload is heavily filtered. |
| `pgvector/pgvector` | 22,839 | **non-SPDX** | 2026-08-20 | 11 | 14 | **ADOPT (PoC)** | PostgreSQL licence. Fine to ~5-10M vectors. |
| `weaviate/weaviate` | 16,770 | BSD-3-Clause | 2026-08-31 | 0 | 688 | **REJECT** | BSD-3 but no advantage over Qdrant here. |

## Graph

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `neo4j/neo4j` | 17,173 | GPL-3.0 | 2026-08-24 | 7 | 251 | **REJECT - LICENCE** | GPL-3.0 Community. And the graph is ~10^2 nodes. |
| `apache/age` | 4,789 | Apache-2.0 | 2026-08-28 | 3 | 241 | **REJECT** | Apache-2.0 but unnecessary; a recursive CTE suffices. |

## Event bus

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `apache/kafka` | 33,648 | Apache-2.0 | 2026-08-31 | 0 | 528 | **DOCUMENTED PATH** | Apache-2.0. Statewide swap-in. |
| `nats-io/nats-server` | 20,640 | Apache-2.0 | 2026-08-31 | 0 | 546 | **ADOPT (PoC/pilot)** | Apache-2.0, single binary. 926 ev/s statewide. |
| `apache/pulsar` | 15,321 | Apache-2.0 | 2026-08-31 | 0 | 1,730 | **REJECT** | Apache-2.0 but 1730 open issues; operational weight unjustified. |
| `redpanda-data/redpanda` | 12,504 | NONE | 2026-08-22 | 9 | 546 | **REJECT - LICENCE** | BSL. Unsuitable for government procurement. |

## Agent frameworks

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `modelcontextprotocol/servers` | 89,991 | **non-SPDX** | 2026-08-31 | 0 | 513 | **REFERENCE** | Tool-exposure standard; watch. |
| `microsoft/autogen` | 60,727 | CC-BY-4.0 | 2026-04-15 | 138 | 1,002 | **REJECT** | CC-BY-4.0 on a code repo; 138d stale. Maintenance mode. |
| `crewAIInc/crewAI` | 57,886 | MIT | 2026-08-31 | 0 | 769 | **REJECT** | Multi-agent; rejected on determinism grounds. |
| `langchain-ai/langgraph` | 40,794 | MIT | 2026-08-30 | 1 | 732 | **REJECT (for us)** | MIT and healthy - but we need one tool-calling loop, not a graph runtime. |
| `microsoft/agent-framework` | 13,246 | MIT | 2026-08-31 | 0 | 641 | **REFERENCE** | MIT, active. Reconsider only if the copilot grows. |

## Serving

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `vllm-project/vllm` | 90,614 | Apache-2.0 | 2026-08-31 | 0 | 7,269 | **DEFER - GPU** | Apache-2.0. Only if a self-hosted LLM is needed. 7,269 open issues. |
| `NVIDIA/TensorRT-LLM` | 14,516 | **non-SPDX** | 2026-08-31 | 0 | 1,409 | **DEFER - GPU** | NVIDIA licence. Target profile only. |
| `triton-inference-server/server` | 10,953 | BSD-3-Clause | 2026-08-31 | 0 | 888 | **DEFER - GPU** | BSD-3. Target-profile serving. |
| `openvinotoolkit/openvino` | 10,773 | Apache-2.0 | 2026-08-31 | 0 | 767 | **REFERENCE** | Apache-2.0. Intel CPU/edge alternative. |

## Observability

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `grafana/grafana` | 76,535 | AGPL-3.0 | 2026-08-31 | 0 | 3,326 | **ADOPT AS SERVICE** | AGPL-3.0 - separate service only, never vendored. |
| `prometheus/prometheus` | 65,923 | Apache-2.0 | 2026-08-31 | 0 | 882 | **ADOPT** | Apache-2.0. |
| `open-telemetry/opentelemetry-collector` | 7,473 | Apache-2.0 | 2026-08-31 | 0 | 700 | **ADOPT** | Apache-2.0. |

## Security / policy

| Repository | Stars | Licence | Last push | days | Issues | Verdict | Rationale |
|---|---:|---|---|---:|---:|---|---|
| `keycloak/keycloak` | 36,518 | Apache-2.0 | 2026-08-31 | 0 | 3,175 | **CANDIDATE** | Apache-2.0. Pilot-tier identity. |
| `hashicorp/vault` | 36,194 | **non-SPDX** | 2026-08-31 | 0 | 1,434 | **REJECT - LICENCE** | BUSL since 2023. Prefer an Apache-licensed secret store. |
| `open-policy-agent/opa` | 12,181 | Apache-2.0 | 2026-08-31 | 0 | 331 | **ADOPT** | Apache-2.0. Purpose-binding as policy data. |
| `spiffe/spire` | 2,506 | Apache-2.0 | 2026-08-29 | 1 | 131 | **ROADMAP** | Apache-2.0. Workload identity at statewide scale. |

## Licence classification

| Class | Repositories | Policy |
|---|---|---|
| Permissive (MIT / Apache-2.0 / BSD / PostgreSQL) | majority | **Allowed** |
| **AGPL-3.0** | `ultralytics`, `boxmot`, `grafana` | **Blocked as a dependency.** Grafana permitted only as a separately-deployed service |
| **GPL-3.0** | `neo4j` (Community) | **Blocked** |
| **BSL / BUSL** (no SPDX) | `redpanda`, `vault` | **Blocked for government procurement** |
| Non-standard | `autogen` (CC-BY-4.0 on code), `TensorRT-LLM` (NVIDIA) | Flagged; avoid or treat as vendor-supplied |
| Model weights, licensed separately | all HF models | Audited individually in `MODEL_BENCHMARK.md` |

### The distinction that matters

Code licence, **model-weight licence** and dataset licence are three different
things, audited separately. The commonest failure in this domain is a permissive
wrapper around restrictively-licensed weights — exactly the shape of
`Koushim/yolov8-license-plate-detection` (declared MIT, YOLOv8-derived, 43k downloads).

### Why AGPL specifically is the risk here

AGPL's network clause covers precisely our case: a government platform served
over a network. That is why `ultralytics` and `boxmot` are blocked **in code**
rather than by intention — see `test_router_never_returns_a_copyleft_model`,
which asserts it across every task and every runtime profile.

### Stale-but-useful

`fast-reid`, `ByteTrack`, `BoT-SORT` and `CLIP-ReID` are all permissively
licensed and all >2 years without a push. Policy: **use the weights or the
algorithm, never the framework as a runtime dependency.** A stale dependency in
a government deployment is a security-patch liability, not just an inconvenience.

