# High-Level Design

**SAAKSHYA — Federated CCTV Intelligence and Evidence Fabric**
Gujarat Police Innovation Challenge 2026 · Models 1 + 3, Model 2 as fallback

Submitted as the Technical Proposal. Engineering detail is in
`docs/ARCHITECTURE.md`; this document states the design and its justification.

---

## 1. Problem statement

Gujarat operates tens of thousands of cameras across Home, Health, GSRTC,
Panchayat and Municipal departments, installed over two decades for local
supervision. The estate is heterogeneous in vendor, codec, resolution, frame
rate, mounting, illumination and network path.

An investigator's question is **"where did this vehicle go?"**. Answering it
across that estate has three obstacles:

1. **Video cannot be centralised.** 80,000 cameras at 2 Mbps is 160 Gbps
   sustained ingress and ~52 PB for 30 days.
2. **Camera capability is unknown and unequal.** Most cameras were never
   installed to read a plate. No inventory of which ones can exists.
3. **Connectivity is unreliable**, and outages correlate with incidents.

## 2. Design principles

| # | Principle | Consequence in the build |
|---|---|---|
| P1 | Move metadata, not video | Analytics run at the edge; ~400 B per observation crosses the network |
| P2 | Measure capability, never assume it | Three graded capabilities per camera per time band, with evidence |
| P3 | Absence of evidence is not evidence of absence | Four leg types; coverage gaps stated in words |
| P4 | Abstention is a correct answer | No colour rather than a guessed colour; UNKNOWN rather than a grade from three frames |
| P5 | Every conclusion decomposes | No screen shows a bare confidence number |
| P6 | Intrusive queries are accountable | Purpose binding at the authorisation gate, hash-chained |
| P7 | Degrade, never stop | Edge continues with the uplink down; nothing is lost |
| P8 | The deterministic core owes nothing to a language model | Chain tested with LLM imports asserted absent |

## 3. Logical architecture

```
 CAMERA ESTATE ── RTSP / HLS ──►  DISTRICT EDGE NODE  ──metadata──►  CENTRE
 heterogeneous                   ingest · analytics                 aggregation
 5 departments                   local store · queue                cross-district
 unknown capability              watchlist · alerts                 search · evidence
                                 evidence                           audit · GIS
                                 ▲                                       │
                                 └───────── watchlist bundles ───────────┘
                                            (fail closed)
```

**Model 1 — Camera registry** is the spine, not a screen. Identity, geometry,
transport, health and *measured capability*. Every other plane reads from it.

**Model 3 — Federated metadata intelligence** is the analytic layer: search,
camera graph, trajectory, watchlist, alerts, evidence.

**Model 2 — Central processing** is the fallback for sites that cannot host
analytics; the same pipeline runs centrally against a pulled stream.

## 4. Component design

### 4.1 Ingest
PyAV, chosen because it is the only practical option exposing real `pts` and
`time_base`. **All ordering is by presentation timestamp**, never wall clock or
frame count. One capture per camera, fanned out. Reconnect with exponential
backoff and jitter. Dual-signal discontinuity detection (PTS regression *and*
block-grid scene cut), because a looping publisher advances PTS across the loop
and a PTS-only detector misses it.

### 4.2 Analytics — adaptive tiers
**T0** motion presence · **T1** detection and tracking · **T2** plate and
attributes · **T3** forensic re-processing.

Tier is selected from measured capability, observation quality, event priority
and resource pressure. **Priority never overrides a capability ceiling**: asking
harder does not make an unreadable plate readable.

### 4.3 Retrieval — graph-first
```
structured prune → graph prune → candidate scoring → decomposed rerank
```
Appearance ranks last because it was measured and found unfit to lead: the
DINOv2 baseline scored a decoy at 0.941 against the target while scoring the
target against itself at 0.412. Structure and physics prune before the fragile
signal ranks anything.

### 4.4 Camera Link Model
Travel-time distributions learned from observed traversals. An edge is *trusted*
only at ≥3 samples; below that it is a prior, not evidence. Drives trajectory
plausibility, gap search and next-best-camera ranking.

### 4.5 Trajectory
Ranked hypotheses, never one forced route. Legs typed OBSERVED / UNOBSERVED /
COVERAGE_GAP / CONTRADICTION. Contradictions stay in the output with their
alternatives — OCR error, cloned mark, clock drift, mis-association — and cap the
score. Track fragments of one pass at one camera coalesce, and the merge is
stated.

### 4.6 Evidence
Hash-chained frame, clip and manifest. BSA s.63 certificate prepared as a
**draft** with signature blocks empty. The system never asserts admissibility.

### 4.7 Offline
Durable local queue; events acknowledged, not deleted, so a lost acknowledgement
replays rather than losing data. `dedup_key` makes central application
idempotent. Watchlist bundles fail closed on integrity, issuer and version.

### 4.8 Security
Four independent gates: authentication, role permission, jurisdiction scope,
purpose binding. ADMIN holds no search permission — running the estate and
investigating people are different jobs.

### 4.9 Copilot (optional)
One orchestrator, twelve **read-only** tools over the same service the interface
calls. Injection detection on camera-derived text; mechanical grounding
verification of every factual token. Absent from the mandatory chain.

## 5. Technology

| Layer | Choice | Licence | Why |
|---|---|---|---|
| Decode | PyAV | BSD-3 | Real PTS access |
| Detection / OCR | ONNX Runtime + open models | MIT / Apache-2.0 | Portable, pinned by weight hash |
| Tracking | ByteTrack, own implementation | — | Upstream is neither PTS- nor segment-aware |
| Store | SQLAlchemy Core · SQLite → PostgreSQL + PostGIS + pgvector | MIT / PostgreSQL | One interface, two dialects |
| API | FastAPI + Uvicorn | MIT / BSD-3 | OpenAPI generated from routes |
| Interface | Vanilla ES modules, hand-written canvas map | — | **No third-party asset**: runs with no internet route |
| Replica | MediaMTX | MIT | Mirrors the organiser's sandbox |

Licence policy is enforced in code: the model router refuses a non-permissive
licence, and `make verify` fails on one.

## 6. Deployment

| Tier | Scope | Hosts |
|---|---|---|
| Edge | 2,000–3,000 cameras per district node | Ingest, analytics, local store, queue, watchlist, alerts, evidence |
| Centre | Statewide | Aggregation, cross-district search, evidence chain, audit, GIS |

Three runtime profiles — `DEV_CPU`, `CLOUD_GPU`, `TARGET_GPU` — selected at
runtime from detected hardware. One codebase.

## 7. Measured, and modelled

**MEASURED** — 50 concurrent cameras, mixed codecs: 52,637 frames, **0 decoder
errors**, 6 failures recovered. One analytics process sustains 11.4 frames/s
(~11 cameras at 1 fps). 10 of 10 hot queries indexed. API p50 1.7–9.6 ms.
Offline replay with no duplicates and no loss. 5 of 5 tamper tests detected.

**MODELLED** — 80,000 cameras across ~33 district nodes; 160 Gbps / 52 PB for
central video; ~90–180 GB/day of metadata statewide.

The distinction is maintained everywhere. Nothing modelled is quoted as tested.

## 8. Risks

| Risk | Mitigation | Residual |
|---|---|---|
| Real feeds differ from the corpus | Profile before tuning; staged model selection per tier | High until access exists |
| Analytics throughput per process | GPU profiles; more processes per node | Measured, understood |
| No PKI for evidence or bundles | Content hashes with the limitation stated everywhere | Accepted; needs a policy decision |
| Insider misuse | Purpose binding, scope, hash-chained audit | Recorded, not prevented |
| Unavailable government feed | Catalogue-driven intake; no code change needed | **Blocked on registration** |

## 9. Compliance

- **BSA s.63** — draft certificate prepared, unsigned, never claimed admissible.
- **Purpose limitation** — enforced at the gate, recorded in an immutable log.
- **No biometric identification** — no face pipeline exists, by decision.
- **No government database integration claimed** — VAHAN, CCTNS, SARATHI, AFIS
  and NAFIS adapters raise `NotImplementedError` naming what each would require.
- **ER/STQC** — camera compliance status is a registry field, not an assertion
  about this software.
