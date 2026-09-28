# Final Architecture Decision

**Date:** 1 September 2026
**Status:** **DECIDED — implementation gate is open**
**Supersedes:** the architecture freeze in `MASTER_BUILD_PLAN.md` §Phase 0 (amended, not replaced)

This is the gate document required before implementation resumes.

---

## 1. Selected architecture

**SAAKSHYA — Federated CCTV Intelligence & Evidence Fabric**
**Submission amendment (28 September 2026).** Hybrid Models 1 + 2 + 3
with selected-camera Model 4 analytics. Model 1 is registry/GIS/governance;
Model 2 is unified viewing and metadata search; Model 3 is VMS federation
middleware; Model 4 is selected central analytics. Only statewide central
recording is declined on MODELLED bandwidth/storage arithmetic
(`docs/SCALE_MODEL.md`).

The Model 2 wall has CONTROL ROOM (up to 30 direct WHEP tile sessions,
400 ms apart) and OPTIMIZED VIEW (at most 12 near the viewport, 600 px
prefetch, released 15 s off screen). These local policies are VERIFIED in
`ui/app.js`; they are not sandbox limits. Browser signalling uses the
authenticated proxy; selected AI workers use RTSP/TCP separately.

**Amended by this review in four ways:**

| # | Amendment | Driver |
|---|---|---|
| A1 | **Graph and structure prune *before* appearance search**, not after | Vehicle Re-ID degrades 20–40% cross-dataset (arXiv 2606.01981). Leading with the fragile signal is unsound. |
| A2 | **Calibration-free by design** becomes an explicit principle | The strongest MTMC methods need BEV/calibrated cameras. 80,000 uncalibrated cameras will never be surveyed. |
| A3 | **Quality moves from per-camera to per-observation** | A grade-B camera still yields occasional excellent crops; scoring them alike discards information. |
| A4 | **Lakehouse adopted as the statewide cold tier** | Postgres-forever was an unstated and wrong implication for 80k cameras. |

**Thesis, unchanged:** keep the video where it already lives; centralise
intelligence, correlation and evidence.

## 2. Rejected alternatives

| Alternative | Score | Why rejected |
|---|---|---|
| Central VMS (Model 4) | 17/40 | 0.16–0.48 Tbps and 12–78 PB per retention window, for capability obtainable at ~103 Mbps |
| Agent-centric | 14/40 | Non-deterministic at a live government evaluation |
| Federated search, no central index | 27/40 | Privacy-maximal and politically elegant, but unpredictable query latency across 26 departments and very hard to demo in 3 minutes. **Kept as the documented privacy-maximal variant.** |
| Event-driven lakehouse as primary | 27/40 | Query latency and build time wrong for the PoC. **Adopted for the cold tier only.** |
| Edge-first (no central intelligence) | 32/40 | Cross-district correlation is the whole product |
| Federated VMS alone (Model 3 only) | 32/40 | Fails the mandatory Model 1 requirement |

## 3. Model stack

| Task | Selected | Licence | Status |
|---|---|---|---|
| Plate detect + OCR | `anpr-onnx-cpu@1.0.0` (yolo-v9-t-640 + cct-s-v2-global) | MIT | **ACTIVE, measured** |
| Vehicle detect | `PekingU/rtdetr_v2_r18vd` @ `5650961749fa` | Apache-2.0 | Candidate → implement |
| Tracker | `roboflow/trackers` (ByteTrack reimpl.) | Apache-2.0 | Candidate → implement |
| Appearance embedding | `facebook/dinov2-base` @ `f9e44c814b77` | Apache-2.0 | Baseline |
| India OCR upgrade | `Awiros/anpr-ocr` @ `eadbc5ae4faa` | Apache-2.0 | Candidate — dual-row support |
| Forensic VLM | `Qwen/Qwen3-VL-4B-Instruct` | Apache-2.0 | GPU-only, tier 3, optional |

**Blocked in code, not by intention:** Ultralytics (AGPL, covers weights),
BoxMOT (AGPL), `morsetechlab/yolov11` (AGPL), Neo4j (GPL), Redpanda (BSL),
Vault (BUSL). Asserted by `test_router_never_returns_a_copyleft_model`.

## 4. Open-source stack

```
Decode/ingest   PyAV (FFmpeg)                     BSD-3 / LGPL
Gateway         MediaMTX 1.20.1                   MIT      (dev/test only)
Inference       ONNX Runtime → Triton/TensorRT     MIT / BSD-3
Store (PoC)     Postgres 16 + PostGIS + pgvector  PostgreSQL
Vector (pilot)  Qdrant                             Apache-2.0
Vector (state)  Milvus                             Apache-2.0
Cold history    Object store + Iceberg-style       Apache-2.0
Bus             NATS JetStream → Kafka             Apache-2.0
Graph           Postgres recursive CTE             —
Policy          OPA                                Apache-2.0
Observability   Prometheus + OTel (+ Grafana as a separate service)
API             FastAPI                            MIT
UI              React + MapLibre GL                BSD/MIT
```

## 5. Data architecture

| Tier | Contents | Store | Retention |
|---|---|---|---|
| Hot | events, plate reads, embeddings, active vectors | Postgres + pgvector (PoC) → Qdrant (pilot) | 30 days |
| Warm | evidence clips for flagged events, case bundles | Object store | 1 year (UK NAS precedent) |
| Cold | full event history for analytics | Iceberg-style tables on object storage | policy-driven |
| Case | evidence under statutory hold | WORM, hash-verified | case lifetime |
| **Not ours** | continuous raw video | **stays with the department** | dept. policy (7/15+ days) |

## 6. Search architecture — the core algorithm

```
1. STRUCTURED PRUNE   plate exact/fuzzy · time · district · camera · class     SQL
2. GRAPH PRUNE        reachable cameras given learned transition times    recursive CTE
3. ANN CANDIDATES     appearance embedding, top-K in surviving cells      filtered ANN
4. RERANK             quality-weighted fusion + decomposition             in-process
```

Ordering is the decision. Steps 1–2 use structure and physics, which do not
suffer domain shift. Step 3 — the signal that loses 20–40% off-domain — only ever
ranks an already-plausible set.

## 7. Graph architecture

Camera Link Model (**N1 — established prior art, stated as such**). Nodes are
cameras; directed edges carry support count and a travel-time distribution
(p05/p50/p95) learned from confident plate co-observations, seeded from GIS
distance. Stored as Postgres tables, traversed with recursive CTEs.
**No graph database. No GNN.**

## 8. Evidence architecture

Manifest with SHA-256 of frame and clip, model/pipeline provenance, hash-chained
audit, verification endpoint, and a **BSA s.63 certificate prepared with
`status: DRAFT_PENDING_SIGNATURE`** and empty signature blocks for the person in
charge and the expert. The system never represents itself as certifying officer
or expert, and no UI string claims the evidence *is* admissible.

## 9. Agent architecture

**One tool-calling orchestrator. No graph runtime, no multi-agent.** Typed
tools, permission-checked, fully logged, no mutation tools. The mandatory chain
must pass with the LLM disabled — enforced as an exit criterion.

## 10. Novelty claim — conservative, and deliberately only two

**Primary (technical), N3:** capability-gated, graph-first, quality-weighted
vehicle retrieval that **declines rather than guessing**, and carries the reason
into the evidence record. Components are prior art (Chameleon-lineage
scheduling; Camera Link Model; standard calibration). The *composition* — one
measurement driving compute routing, user-facing confidence, and a procurement
gap-analysis artifact — has no precedent I could find.

**Secondary (operational), N4:** automatic preparation of a **BSA s.63**
evidence certificate. Legally required in India since 1 July 2024; implemented
by no VMS vendor; NFSU is a knowledge partner.

**Explicitly NOT claimed:** federation, ALPR, hotlists, vehicle search with
partial plate (Genetec/Axon ship it), camera link models (AI City literature),
adaptive configuration (Chameleon/VideoStorm), self-healing pipelines (published
practice), NL search (every vendor).

## 11. Implementation order — resumes now

| # | Deliverable | Exit criterion |
|---|---|---|
| 1 | Persistence + event sink | Events survive restart; idempotent replay by `dedup_key` |
| 2 | Vehicle detector (RT-DETRv2-R18) | car/motorcycle/bus/truck on corpus |
| 3 | Tracker + per-track plate voting | C-014 reports **all three** vehicles, not one |
| 4 | Plate search API | plate → observations, <200 ms at 50 cameras |
| 5 | Camera Link Model | bootstraps with zero manual config |
| 6 | Trajectory solver | correct route ranked first; contradictions shown |
| 7 | Watchlist + alerts | fires within one event; expiry/revocation provably honoured |
| 8 | Evidence + s.63 | tampering fails verification |
| 9 | Capability grading from live streams | grades match measured ANPR yield |
| 10 | GIS + investigation UI | judge completes plate → route → evidence unaided |
| 11 | Copilot (optional) | disable it; chain still passes |

**Priority ladder if time is lost — cut from the bottom, never the top:**
`1–8` mandatory · `9–10` differentiator · `11` optional.

## 12. Hardware strategy

`DEV_CPU` correctness · `CLOUD_GPU` benchmarking only · `TARGET_GPU` deployment.
One codebase, already implemented. **No GPU figure enters the PPT or HLD unless
measured**; all current GPU numbers are labelled MODELLED.

## 13. What this review changed in one line each

1. Re-ID demoted from identity recovery to candidate ranking — **changes the demo script.**
2. Search reordered: graph before ANN — **changes the core algorithm.**
3. Quality moved per-camera → per-observation — **changes the data model.**
4. Lakehouse adopted for the statewide cold tier — **changes the scale story.**
5. Three novelty claims downgraded to prior art — **changes the pitch.**
6. Six dependencies blocked on licence — **changes the stack.**

**Gate status: OPEN.** Implementation may resume at item 1.
