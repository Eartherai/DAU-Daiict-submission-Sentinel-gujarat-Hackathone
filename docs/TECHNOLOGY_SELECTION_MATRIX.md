# Technology Selection Matrix

**Date:** 1 September 2026

Columns: **Prod** = production proof · **Res** = research proof · **OSS** ·
**Lic** = licence class (P permissive, C copyleft, X blocked) · **Perf** ·
**Cplx** = operational complexity (lower better) · **Hack** = feasible before
7 Sep · **State** = fitness at 80,000 cameras. Scores 1–5.

---

## 1. Component selection

| Category | Option | Prod | Res | OSS | Lic | Perf | Cplx | Hack | State | **Decision** |
|---|---|---:|---:|:--:|:--:|---:|---:|---:|---:|---|
| **Decode** | **PyAV (FFmpeg)** | 5 | – | ✔ | P | 4 | 2 | 5 | 4 | **SELECTED** — only path to real PTS |
| | OpenCV VideoCapture | 5 | – | ✔ | P | 3 | 1 | 5 | 3 | Rejected — hides PTS; `CAP_PROP_FPS` documented unreliable |
| | GStreamer direct | 5 | – | ✔ | P | 5 | 4 | 2 | 5 | Deferred to GPU profile |
| | DeepStream | 5 | – | ~ | X* | 5 | 5 | 1 | 5 | Deferred — no NVIDIA hardware; NVIDIA EULA |
| **Stream gateway** | **MediaMTX** | 4 | – | ✔ | P | 4 | 1 | 5 | 4 | **SELECTED** — replica + own-feed server |
| | go2rtc | 3 | – | ✔ | P | 4 | 2 | 4 | 3 | Rejected — 897 open issues |
| **Vehicle detector** | **RT-DETRv2-R18** | 4 | 5 | ✔ | P | 4 | 2 | 4 | 4 | **SELECTED** — Apache-2.0, 81 MB, COCO classes |
| | RF-DETR-base | 3 | 5 | ✔ | P | 5 | 3 | 3 | 4 | Candidate — GPU profile |
| | Ultralytics YOLO | 5 | 4 | ✔ | **X** | 5 | 1 | 5 | 4 | **BLOCKED — AGPL-3.0 covers weights** |
| **Plate detector** | **yolo-v9-t-640** (open-image-models) | 3 | 3 | ✔ | P | 5 | 1 | 5 | 4 | **SELECTED** — measured 0.83–0.86 |
| | yolo-v9-s-608 | 3 | 3 | ✔ | P | 2 | 1 | 5 | 3 | Rejected — measured 0.30–0.44 |
| | rtdetr-v2 plate (justjuu) | 1 | 4 | ✔ | P | ? | 2 | 3 | 4 | Candidate — unbenchmarked |
| | morsetechlab yolov11 | 4 | 3 | ✔ | **X** | 5 | 1 | 5 | 4 | **BLOCKED — AGPL-3.0** |
| **Plate OCR** | **cct-s-v2-global** | 3 | 3 | ✔ | P | 4 | 1 | 5 | 4 | **SELECTED** — 10 slots fits Indian marks |
| | global-plates-mobile-vit-v2 | 3 | 3 | ✔ | P | 1 | 1 | 5 | 1 | **REJECTED — 9 slots; structurally cannot represent a 10-char mark** |
| | Awiros anpr-ocr (India) | 1 | 4 | ✔ | P | ? | 3 | 2 | 5 | **Candidate — highest-value upgrade**; dual-row support |
| **Tracker** | **roboflow/trackers** | 3 | 4 | ✔ | P | 4 | 1 | 5 | 4 | **SELECTED** — maintained, Apache-2.0 |
| | BoxMOT | 4 | 4 | ✔ | **X** | 5 | 2 | 5 | 4 | **BLOCKED — AGPL-3.0** |
| | ByteTrack / BoT-SORT upstream | 4 | 5 | ✔ | P | 4 | 2 | 4 | 3 | Reference — >2 y stale |
| **Embedding** | **DINOv2-base** | 5 | 5 | ✔ | P | 3 | 2 | 4 | 4 | **SELECTED as baseline** |
| | fast-reid weights | 3 | 5 | ✔ | P | 4 | 3 | 3 | 3 | Weights only — framework 762 d stale |
| | vehicle_reid_siglip2 | 1 | 2 | ✔ | P | ? | 2 | 3 | 3 | Candidate — 0 downloads, unproven |
| | DINOv3 | 4 | 5 | ✔ | **?** | 4 | 2 | 3 | 4 | Avoided — licence is "other", not Apache |
| **Vector (PoC)** | **pgvector** | 5 | – | ✔ | P | 4 | 1 | 5 | 2 | **SELECTED for PoC** — one database |
| **Vector (pilot)** | **Qdrant** | 5 | – | ✔ | P | 5 | 2 | 3 | 4 | **SELECTED for pilot** — 2–4× on *filtered* queries |
| **Vector (state)** | **Milvus** | 5 | – | ✔ | P | 5 | 4 | 1 | 5 | **Documented statewide path** |
| | FAISS | 5 | 5 | ✔ | P | 5 | 3 | 4 | 3 | Library, not a service |
| **Event bus** | **NATS JetStream** | 4 | – | ✔ | P | 4 | 1 | 5 | 4 | **SELECTED** — single binary; 926 ev/s |
| | Kafka | 5 | – | ✔ | P | 5 | 4 | 2 | 5 | **Documented statewide path** |
| | Redpanda | 4 | – | ~ | **X** | 5 | 3 | 3 | 5 | **BLOCKED — BSL** |
| | Pulsar | 4 | – | ✔ | P | 4 | 5 | 1 | 5 | Rejected — 1,730 open issues |
| **Graph** | **Postgres recursive CTE** | 5 | – | ✔ | P | 4 | 1 | 5 | 3 | **SELECTED** — graph is ~10² nodes |
| | Apache AGE | 3 | – | ✔ | P | 3 | 3 | 3 | 4 | Rejected — unnecessary |
| | Neo4j | 5 | 5 | ~ | **X** | 5 | 4 | 3 | 4 | **BLOCKED — GPL-3.0 Community** |
| **Relational/GIS** | **Postgres + PostGIS** | 5 | – | ✔ | P | 4 | 2 | 5 | 4 | **SELECTED** |
| **Time-series** | TimescaleDB (community) | 5 | – | ~ | P/TSL | 5 | 2 | 4 | 4 | Optional — watch TSL boundary |
| | ClickHouse | 5 | – | ✔ | P | 5 | 3 | 2 | 5 | **Statewide analytics tier** |
| **Cold history** | **Object store + Iceberg-style tables** | 5 | – | ✔ | P | 3 | 3 | 1 | 5 | **Documented statewide path** (new in this review) |
| **Policy** | **OPA** | 5 | – | ✔ | P | 4 | 2 | 4 | 5 | **SELECTED** |
| **Secrets** | Vault | 5 | – | ~ | **X** | 5 | 3 | 3 | 5 | **BLOCKED — BUSL**; use SOPS/age or cloud KMS |
| **Identity** | Keycloak | 5 | – | ✔ | P | 4 | 3 | 2 | 5 | Pilot tier |
| **Observability** | Prometheus + OTel | 5 | – | ✔ | P | 5 | 2 | 4 | 5 | **SELECTED** |
| | Grafana | 5 | – | ✔ | **C** | 5 | 2 | 4 | 5 | **Separate service only — AGPL** |
| **Agent runtime** | **One tool-calling loop** | 4 | 3 | ✔ | P | 5 | 1 | 5 | 4 | **SELECTED** |
| | LangGraph | 5 | 4 | ✔ | P | 4 | 3 | 3 | 4 | Rejected *for us* — we need one loop, not a graph runtime |
| | CrewAI / AutoGen | 3 | 3 | ✔ | P/? | 2 | 4 | 3 | 2 | Rejected — determinism; AutoGen in maintenance |

\* DeepStream: NVIDIA EULA, not an OSI licence.

---

## 2. System compositions compared

Per instruction §52 — whole architectures, not parts.

| # | Composition | Latency | Scale | Ops burden | Licence risk | Build by 7 Sep | Eval fit | **Verdict** |
|---|---|---|---|---|---|---|---|---|
| **C1** | **PyAV + ONNX Runtime + Postgres/PostGIS/pgvector + NATS** | Good | to ~2k cams | **Lowest** | **None** | **Yes** | **Best** | **SELECTED for PoC + pilot** |
| C2 | DeepStream + Triton + Qdrant + Postgres + NATS | Best | to ~20k | High | NVIDIA EULA | No | Good | **Target profile**, documented |
| C3 | DeepStream + Kafka + Milvus + ClickHouse + PostGIS | Best | 80k+ | Highest | NVIDIA EULA | No | Poor | **Statewide**, documented |
| C4 | GStreamer + OpenVINO + Postgres + Redis | Good | ~2k | Medium | None | Marginal | Good | Intel-edge alternative |
| C5 | Frigate-derived + custom federation | Medium | ~500 | Medium | MIT | Marginal | Medium | Rejected — wrong shape |
| C6 | Lakehouse-first (Iceberg + Trino + object store) | Poor | 80k+ | High | None | No | Poor | Rejected for PoC; **adopted for cold tier** |

**The migration story is the deliverable, not any single composition.** C1 → C2 →
C3 changes *deployment*, not application code, because everything sits behind
`InferenceBackend`, the repository layer and the event schema. That is what the
runtime-profile work already built.

---

## 3. Hardware

| Tier | Hardware | Role | Status |
|---|---|---|---|
| Dev | Apple Silicon, CPU-only | correctness, regression | **Current.** Measured ~69 ms/frame ANPR |
| Bench | Rented CUDA (L4 / A10) | model comparison, GPU latency | **Not yet used** |
| Edge | Jetson Orin NX | district/site inference | Modelled: ~16 streams decode-bound |
| Regional | NVIDIA L4 24 GB | district node | Modelled: ~64 streams at 2 fps |
| State | L40S 48 GB | central forensic tier | Modelled |

**≈1,634 L4-equivalents statewide** under role-tiered sampling (~48/district).
**MODELLED, not measured.** No GPU figure in this project is measured.
