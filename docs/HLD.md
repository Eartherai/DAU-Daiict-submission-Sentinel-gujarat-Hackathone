# High-Level Design

**SAAKSHYA — Federated CCTV Intelligence and Evidence Fabric**
Gujarat Police Innovation Challenge 2026 · Hybrid of Models 1 + 2 + 3. Model 4 rejected on arithmetic.

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

**Submitted as a hybrid of Models 1 + 2 + 3.** Model 4 is rejected, not deferred.

**Model 1 — Camera registry & GIS (mandatory, kept).** Identity, geometry,
transport, health and *measured capability*. Nineteen cameras are placed from
their names (`DERIVED_FROM_NAME`). Eleven remain in the registry without
coordinates (`NAME_INSUFFICIENT`) and are listed, not invented onto the map.
Model 1 does not stream live video.

**Model 2 — Unified viewing (kept as stills).** One JPEG per camera, written by
ingest at about 1 Hz. The organiser's guide: each client gets its own stream
copy. A thirty-tile WebRTC wall would be thirty extra RTSP sessions against the
government grid. Click-to-play is optional; the demonstration is the still wall.

**Model 3 — Federation & metadata (kept).** Heterogeneous sources: government
RTSP plus local MediaMTX synthetic. The observation store is the metadata bus.
Search, camera graph, trajectory, watchlist, alerts and evidence read that bus.
Adapters, not a replacement VMS.

**Model 4 — Central VMS recording (rejected).** MODELLED: ~80,000 cameras ×
2 Mbps ≈ 160 Gbps ingest; 30-day retention ≈ 52 PB. Not built. The arithmetic
is the justification.

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
One orchestrator, sixteen **read-only** tools over the same service the interface
calls (including estate list, timebase check, and `refuse_imagery`). Injection
detection on camera-derived text; mechanical grounding verification of every
factual token. Absent from the mandatory chain. Gemini, when configured, is a
coordinator over those tools — not a detector.

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

## 10. Heterogeneous CCTV onboarding (Model 1 + 3)

Cameras arrive as RTSP (and, on the replica, MediaMTX). There is no assumption
of a shared VMS. Each camera is a registry row: identity, transport, codec,
resolution, measured capability, health, and — only if known — coordinates.

**MEASURED on the issued grid:** 30 cameras, 23× h264 + 6× hevc, mixed
resolutions, five departments in the estate of which three self-identify.
Nineteen placed `DERIVED_FROM_NAME`; eleven `NAME_INSUFFICIENT` listed, not
invented. The published catalogue redirects to login, so every record is
`source="probe"`.

NVR and VMS vendors are not replaced. An adapter that can deliver frames (or
already-decoded JPEGs) and a stable camera id is enough to sit on the
observation bus. A vendor SDK is not a prerequisite.

## 11. Watchlist correlation and alerts

Every plated observation is matched against the active watchlist at ingest.
A hit raises an alert with decomposed confidence, camera, time, category and
priority. The Alerts view is the operational surface; Investigate traces the
mark; Evidence seals a sighting.

The demonstration watchlist is **representative** — stolen vehicle, investigation
target — created by the team. No government stolen-vehicle or wanted-person
database is integrated. An adapter that received such a feed would be the same
match path; the feed is what is missing.

**MEASURED:** `GJ38BH5815` stolen_vehicle HIGH OPEN on cam21. Designated
rehearsal `GJ1VV0119` is on the live watchlist. Exact cross-camera repeats among
published marks on this grid: **0**. Multi-camera trace is demonstrated on the
synthetic corpus (`GJ01CD5678`, `GJ35BV6925`).

Face recognition is **not built**. Person detection and dwell are.

## 12. Statewide operations — what is asked, what is claimed

Organisers asked for edge / GPU / bandwidth / storage / HA / cost. Status is
the same discipline as the rest of the proposal.

| Topic | Claim | Label |
|---|---|---|
| Central / regional / edge | ~33 district nodes × 2,000–3,000 cameras; centre aggregates metadata | **MODELLED** (`docs/SCALE_MODEL.md`) |
| GPU / accelerators | One CPU process: 11.4 fps (~11 cameras at 1 Hz). A 2,500-camera node at that rate needs GPU inference at the district, not a rewrite. Profiles: `DEV_CPU` / `CLOUD_GPU` / `TARGET_GPU` | **MEASURED** throughput; **DESIGNED** GPU split |
| Bandwidth | Do not copy video to the centre. Ingest stills ~1 Hz for the wall. Metadata ~90–180 GB/day statewide with T0 gating. Low-connectivity: edge continues, queue replays | **MODELLED** / **MEASURED** offline tests |
| Hot / warm / cold storage | Video stays at the camera/NVR. Hot: 30 days of metadata + sealed evidence at the node. Warm/cold: partition observations by month. Retention is a policy decision | **DESIGNED**, **UNTESTED** at 80k |
| Load balancing / health | Horizontal processes per node; `/system/health`; hash-chained audit | **MEASURED** on 30 cameras; **UNTESTED** as a cluster scheduler |
| HA / backup / DR | Edge detection, watchlist, alerts and evidence continue with the uplink down (18 e2e tests). Central HA, backup and DR: **UNTESTED** | **MEASURED** offline; **UNTESTED** multi-node |
| Cybersecurity | Four gates (auth, role, jurisdiction, purpose). ADMIN cannot search. Tokens not in query strings. No secrets in the repository | **MEASURED** on the API; statewide SOC integration **UNTESTED** |
| Cost | Not estimated in rupees. Hardware is driven by GPU-per-district from the measured 11.4 fps, not by a 52 PB video farm | **NOT ESTIMATED** |

Nothing in this table is quoted as “tested at 80,000”.

## 13. Prerequisites from participating departments

To assess a further camera, and to stop inferring what a catalogue would have
stated:

1. **A catalogue session** on `cctv.corp8.cloud` (or an export): authoritative
   camera id, department, mount, codec, and coordinates. `CATALOGUE` basis
   supersedes `DERIVED_FROM_NAME` with no code change.
2. **Surveyed coordinates** where names are insufficient (the eleven unlocated
   cameras on this grid).
3. **Stream access** already issued for the 30-camera evaluation grid.
4. **Retention and evidence policy** — how long metadata and sealed records may
   be kept; BSA s.63 signing authority is outside this software.
5. **Watchlist authority** if a government list is to replace the representative
   one: issuer, validity, revocation, and the legal basis for matching.

## 14. Future roadmap (PoC → district → state)

This is a plan, not a claim of work already done.

| Horizon | What | Label |
|---|---|---|
| On-site PoC (22–23 Sep 2026) | Same 30-camera grid, designated-vehicle search, watchlist alerts, still wall. GPU only if the venue supplies it. | **DESIGNED** |
| District node | One district, 2,000–3,000 cameras, `TARGET_GPU` profile, local store and queue, watchlist bundles from the centre | **DESIGNED** |
| Catalogue-backed Model 1 | Authoritative ids, departments and surveyed coordinates replace `DERIVED_FROM_NAME` / `probe` | **DESIGNED** — blocked on a catalogue session |
| Government watchlist feed | Same match path; replace `REPRESENTATIVE` with an authorised issuer | **DESIGNED** — blocked on legal basis and API |
| Statewide centre | Cross-district search over metadata; no central video farm | **MODELLED** |
| Face recognition | Not on this roadmap. Deliberate abstention. | — |
| VAHAN / CCTNS / AFIS | Adapters exist as `NotImplementedError`. No integration is claimed. | — |

## 15. What this proposal will not say

- Not production ready.
- Not legally admissible. BSA s.63 stays `DRAFT_PENDING_SIGNATURE`.
- Not tested at 80,000 cameras.
- Not that ANPR works on this estate uniformly — 0 cameras grade GOOD.
- Not that the live government grid has a multi-camera plate identity. It has **0** exact cross-camera repeats. That demonstration is on the own-feed corpus.
