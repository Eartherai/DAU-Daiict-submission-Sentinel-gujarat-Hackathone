# High-Level Design

**SAAKSHYA — Federated CCTV Intelligence and Evidence Fabric**
Gujarat Police Innovation Challenge 2026 · Hybrid of Models 1 + 2 + 3 with a
selected-camera Model 4 central analytics proof-of-concept.

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

**Submitted as a hybrid of Models 1 + 2 + 3, with selected-camera Model 4
central analytics.** The official evaluation target is approximately 50
heterogeneous cameras. The currently accessible sandbox evidence contains 30
reachable/probed cameras; that is an access result, not the evaluation limit.
The catalogue-driven importer accepts the authoritative set when its
authenticated Resources-page endpoint is available.

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

**Model 4 — selected central analytics (kept as a PoC).** Own-feed and
selected-camera streams can be pulled through one controlled gateway into
central analytics, event storage, watchlist correlation, evidence, and GIS.
This proves the central monitoring/analytics pattern required by the challenge
without claiming that all statewide video is permanently centralized.
**Statewide full-video centralization remains rejected on arithmetic:**
~80,000 cameras × 2 Mbps ≈ 160 Gbps ingest and ~52 PB for 30-day retention.

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

The models, and what each is for: **RT-DETRv2-R18** (Apache-2.0) detects vehicles
and people in one pass, on the GPU where there is one; **ByteTrack** holds them
across frames; a **YOLOv9 plate detector** (MIT, ONNX) finds plates; a text
recogniser reads them; and marks are **voted per track** across frames before
anything is published.

*Restricted-zone entries (intrusion, by rule).* The platform does not call a
person an intruder on its own: whether someone may stand somewhere is a matter
of permission, and permission is the department's to state. A department sets
a rule - a polygon on one camera's frame, the IST hours it applies, the classes
it concerns, the authority it rests on - and the platform reports every stored
sighting whose ground point (the bottom centre of its box) falls inside it in
those hours, with how long the person stayed (`/zones`, admin:write to set,
alert:read to read, both audited). On the government grid, a rule on the toll
lane at Tri Mandir Adalaj reports 142 of 1,533 person sightings on the lane's
carriageway.

*Finding plates.* A camera whose frame is wider than 1920 px is searched in
**overlapping full-resolution tiles** as well as whole: the detector's input is
640 px, and a 2560 px frame had reached it at a quarter scale. On the Mumbai
signal-queue footage that took a 40-frame sample from 0 valid plates to 20, at
0.28 s a frame instead of 0.05 s.

*Reading them.* The portable OCR (CCT, ONNX) was trained on plates from about
sixty regions, not including India; on 21 plate crops read by eye from the
same footage it read 1 exactly (2 once the positions of the format are typed),
with 49% of characters wrong. Apple Vision, on device, read 2 exactly and 5
after typing (25% of characters wrong). The recogniser the pipeline now
carries is **Awiros-ANPR-OCR** (Apache-2.0): PP-OCRv5's recogniser fine-tuned
on 558,767 Indian plates, single- and dual-row. Its authors trained it to
abstain on an unreadable plate; here it did not always - on the 2 crops a
person could not read it returned a valid-looking mark both times (at 0.73 and
0.81, under the 0.82 single-read bar), and on a car whose digits the footage
blurs it returned a spread of confident marks, which is why the vote now asks
the frames to agree (below). On the same crops it reads **17 of 21 exactly, with 2.4% of
characters wrong** - once it is fed as it was trained. The inference script
published with the weights pads a crop with black before scaling; PaddleOCR
trains with grey padding after scaling, and with black the model read the edge
as characters (6 of 21). Its framework has no Metal backend and runs on one CPU
core here (50 ms a plate), so the network is **restated in PyTorch** with the
checkpoint's own layer names; the published weights load unchanged and match
PaddlePaddle's forward pass to 7.5×10⁻⁶ with identical text on every crop. On
the GPU it takes 14 ms a plate, 6.6 ms when a frame's plates go as one batch;
on CUDA the authors measure 5 ms. Over a whole 57-second clip it published 83
marks against Vision's 29: checked by eye, 47 correct against 17, at a similar
error rate where a crop could settle it (22% against 26%), and 12 of the 20
hand-read plates exactly against 5 (`var/reports/ocr_indian_eval.json`).
Apple Vision and the ONNX model remain the fallbacks where the weights are not
installed. Every read is interpreted against the **positions of the Indian format**:
an O where the RTO must be a digit is 0, an 8 where a series letter must be is
B; only forced, unambiguous pairs, at most two, stated in the read, with the raw
OCR kept. End to end on 20 s of the queue, the published marks checked by eye
went from 0 of 9 correct to at least 7 correct. Most wrong marks that remain
are one character from a real plate on the same clip, at 40-50 px of plate;
better optics buy the rest, and a one-vote read is published only as a lead
requiring verification.

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

The route leaves the screen as a **vehicle trace report**
(`GET /reports/vehicle/{plate}.html`, opened in place from the target card or
an alert): every read in the officer's jurisdiction, the legs between cameras
with any leg a road vehicle could not drive flagged as a possible misread or
cloned plate, the watchlist status at the moment of printing, the sealed stills
re-hashed and withheld if they no longer match, the case and purpose, signature
blocks, and a SHA-256 over the rows so a printed copy can be checked against
the store. The page carries no script and fetches nothing. It is gated and
audited exactly as the plate search is.

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

### 4.9 Copilot — Gemini over all four models (optional)
One orchestrator, twenty **read-only** tools over the same services the interface
calls, and at least one for each reference model the platform combines:

| Model | Tools | Asked from |
|---|---|---|
| **M1** registry & GIS | `registry_gaps`, `list_estate`, `get_camera_context`, `get_camera_capability` | Cameras view |
| **M2** viewing & health | `estate_health`, `get_camera_neighbors` | Live view |
| **M3** federation | `connected_systems`, `list_timebase`, `check_timebase` | System view |
| **M4** intelligence | `alert_queue`, `search_plate`, `build_trajectory`, `query_watchlist`, `get_evidence`, `verify_evidence`, `draft_report` … | Alerts view, Investigate |

Every tool keeps the gate of the screen it serves (an auditor is refused the
alert queue, with the reason); every factual token in an answer is checked
against the tool results before the answer is shown, and an unverifiable answer
is withheld with the results left for the officer to read directly. Injection
detection runs on camera-derived text. `refuse_imagery` always refuses to
enhance or invent a still. Gemini, when configured, is a coordinator over those
tools — never a detector and never a source of a plate: detection and ANPR stay
on the deployment's own hardware. Measured on the film store, all four model
questions came back grounded. The copilot is absent from the mandatory chain;
the platform works in full without it.

### 4.10 Store — SQLite and PostgreSQL + PostGIS, both exercised

One SQLAlchemy Core schema serves both. SQLite carries a laptop or an edge
node; PostgreSQL 18 with PostGIS 3.6 carries a district or the centre
(`tools/db/setup_postgres.sh` installs it into the project, bound to
127.0.0.1, with a generated password). On PostgreSQL the store adds a
generated geometry column on cameras with GiST indexes on it and on its
geography cast: the map's viewport query uses the index, and `GET /gis/near`
answers "which cameras are within r metres of this point" with `ST_DWithin`
on the spheroid, nearest first, inside the officer's districts.

It is exercised, not claimed. `tools/db/migrate.py` copied the government
store - 1,191,681 rows, 1.16 million observations - in 84 s, counted every
table on both sides, and verified the 1,239-entry audit chain and the
213-record evidence chain on PostgreSQL. The same API then ran against it:
heavy aggregates are faster there (the overview 2.50 s → 0.97 s, a camera's
page 876 → 183 ms), point lookups pay a few milliseconds of client round trip
(`var/reports/store_engines.json`). On 80,000 cameras viewport and radius
queries take about 1 ms on either engine and return the same cameras at 20 of
20 points (`var/reports/gis_postgis.json`). `tests/postgres/` runs search,
trajectory, evidence, audit, zone rules, the trace report and `/gis/near` on a
fresh database each run.

Running on PostgreSQL found four defects SQLite had hidden: 32-bit timestamp
columns and a SQLite-only BLOB type; a count that used SQLite's
`json_extract`; a NUL character in a request, which PostgreSQL text cannot
hold and which failed as a 500 (it is now refused at the door on every
engine); and a `SELECT DISTINCT` that read every observation, now an index
walk. Each has a test.

## 5. Technology

| Layer | Choice | Licence | Why |
|---|---|---|---|
| Decode | PyAV | BSD-3 | Real PTS access |
| Detection / OCR | PyTorch (RT-DETRv2, Awiros-ANPR-OCR port) + ONNX Runtime (plate detector, fallbacks) | BSD-3 / MIT / Apache-2.0 | GPU where present, CPU path always; weights pinned by hash |
| Tracking | ByteTrack, own implementation | — | Upstream is neither PTS- nor segment-aware |
| Store | SQLAlchemy Core · SQLite → PostgreSQL 18 + PostGIS 3.6 (+ pgvector planned) | MIT / PostgreSQL / GPL-2.0 (PostGIS, unmodified server extension) | One interface, two dialects, both exercised (§4.10) |
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

**MEASURED** — 30 government cameras were onboarded in the recorded accessible
estate. Separately, 50 logical local cameras with mixed codecs delivered
52,637 frames with **0 decoder
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
| Catalogue exposes fewer cameras than the official target | Catalogue-driven intake; preserve the exact returned count and do not fabricate capacity | **Current accessible evidence is 30; target is approximately 50** |
| Unavailable government feed | Catalogue-driven intake; no code change needed | **Blocked on authenticated catalogue/session** |

## 9. Compliance

- **BSA s.63** — draft certificate prepared, unsigned, never claimed admissible.
- **Purpose limitation** — enforced at the gate, recorded in an immutable log.
- **No biometric identification** — no face pipeline exists, by decision.
  Footage published for this submission is anonymised without adding one: the
  person detector's boxes, found on the whole frame and on overlapping tiles,
  have their top quarter pixelated and held for three frames either side
  (`tools/demo/blur_heads.py`). Nothing that locates a face is shipped.
- **Purpose in any script** — a purpose written in Gujarati reaches the audit
  log as written; header values outside ISO-8859-1 are percent-encoded by the
  interface and decoded once at the gate.
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
| HA / backup / DR | Edge detection, watchlist, alerts and evidence continue with the uplink down (18 e2e tests). Central HA, backup and DR designed in §15; still **UNTESTED** multi-node | **MEASURED** offline; **DESIGNED** §15; **UNTESTED** multi-node |
| Cybersecurity | Four gates (auth, role, jurisdiction, purpose). ADMIN cannot search. Tokens not in query strings. No secrets in the repository | **MEASURED** on the API; statewide SOC integration **UNTESTED** |
| Cost | Not estimated in rupees. §17 gives the model and its measured inputs (11.4 fps; **S = 2.0** whole-pipeline on an Apple M5 integrated GPU, 3.4 for the detector alone); the target accelerator's **S** comes from the same scripted benchmark before any figure is quoted | **MODELLED** §17; **S MEASURED** on dev hardware; unit prices **NOT ESTIMATED** |

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

## 15. Disaster recovery and redundancy design

A named Model 4 deliverable. Section 12 records DR as **UNTESTED** at the
centre; this is the design that would be tested, not a claim that it has been.

**What must survive what.** The estate is federated by construction: video
stays at the camera or NVR and district nodes hold their own store, queue and
watchlist. That is a resilience property, not only a bandwidth one — losing the
centre does not stop a district detecting, matching or sealing evidence.

| Failure | Blast radius | Behaviour | Label |
|---|---|---|---|
| Centre unreachable | Statewide search, cross-district correlation | Districts continue: detection, watchlist, alerts and evidence all local. Metadata queues and replays on reconnect. | **MEASURED** — 18 offline e2e tests |
| District node lost | That district's live analytics | Cameras keep recording to their own NVR. No central video was being written, so no footage is lost — only analysis is paused. | **DESIGNED** |
| Store corruption at a node | That node's metadata | Restore from the last snapshot; replay the queue from the centre's copy of that district's metadata. | **DESIGNED**, **UNTESTED** |
| Evidence tampering | One record | Hash chain detects it. 5 of 5 tamper tests detected. | **MEASURED** |
| Upstream grid refuses sessions | Live wall only | Tiles fall back to their last still and say so; the AI plane and the store are unaffected. | **MEASURED** — observed repeatedly |

**Objectives to be agreed, not asserted.** RPO and RTO are procurement
decisions with cost attached, so this proposal states the shape and leaves the
numbers to the department that will fund them:

- **Metadata RPO** is bounded by the queue flush interval at the district.
- **Evidence RPO is zero by design** — a manifest is sealed before it is
  acknowledged, and the chain makes a gap detectable rather than silent.
- **RTO for a district node** is a restore-and-replay, not a rebuild: the node
  is stateless apart from its store and queue.

**Redundancy that is deliberately absent.** There is no central video farm to
replicate, because no video is centralised. Removing that requirement is the
single largest availability and cost decision in this design.

## 16. Statewide rollout plan

Section 14 gives the roadmap by capability. This is the same progression by
phase, with the gate that must pass before the next phase begins — the point
being that no phase starts because the previous one finished on a calendar.

| Phase | Scope | Exit gate | Label |
|---|---|---|---|
| 0 — PoC | The 30-camera evaluation grid, one node | Designated-vehicle search, watchlist alert, sealed evidence, audit chain verified | **MEASURED** |
| 1 — First district | One district, 2,000–3,000 cameras, `TARGET_GPU` | Detector throughput sustained at the district's camera count; gap report shows department metadata supplied, not inferred | **DESIGNED** |
| 2 — Region | 3–5 adjacent districts, centre aggregating metadata only | Cross-district search over metadata; queue replay proven under a deliberate uplink cut | **DESIGNED** |
| 3 — Statewide | ~33 district nodes | Per-district onboarding without central redesign; centre holds no video | **MODELLED** |

**What paces this is not software.** Phase 1's gate is a *departmental data*
gate as much as a technical one: 94% of the evaluation estate has no `vms`,
`storage_location` or `retention_days`, and those are facts only the owning
department can supply. The registry reports that shortfall precisely so a
rollout plan can be scheduled against it rather than around it.

## 17. Indicative cost model

Section 12 recorded cost as **NOT ESTIMATED**. That was the honest status, but
the challenge asks for estimated implementation and operational costs, so this
is a model with its assumptions exposed. Unit prices are procurement's to
supply; what this section owes is the *shape* of the bill and the one
measurement that decides it.

### 17.1 Two measured throughputs, and which one to size on

A single figure here would be misleading, because two different things were
measured and they differ by a factor of two.

| Measurement | Value | What it covers |
|---|---|---|
| Single analytics process, detection only, one stream | **11.4 frames/s** | Best case. 1,019 frames, `var/reports/camera_load.json`. |
| Live AI worker, full pipeline, four cameras concurrently | **~1.4 frames/s per camera, ~5.6 aggregate** | Detection *and* ANPR and tracking, sharing a host with the API and media planes. |

**Size on the second.** The first is a component benchmark taken with nothing
else running; the second is what the software actually sustains doing the whole
job. A statewide estimate built on the best case is the kind of number that
collapses in the first question about it.

One further figure from that same 50-camera run matters more than either:
**50,775 of 52,637 delivered frames — 96.5% — were dropped by the consumer.**
Ingest was never the constraint. The analytics process was, by a wide margin,
and that is the finding to carry into procurement.

### 17.2 The model, and its one unknown

```
cameras_per_district        = 2,500          design assumption
sample_rate_hz              = 1              policy choice, not a limit
frames_per_second_needed    = 2,500
process_throughput_fps      = 5.6            MEASURED, full pipeline
gpu_speedup_factor          = S              UNKNOWN — must be benchmarked
inference_nodes_per_district= 2,500 / (5.6 × S)
districts                   = 33
```

### 17.3 Solved for every value of S

Rather than quote a speedup this proposal has not measured, the model is solved
across the range. Procurement benchmarks **S** once and reads its own row.

| GPU speedup **S** | Nodes per district | Statewide | Statewide on the best-case figure |
|---:|---:|---:|---:|
| 1 (CPU only) | 447 | 14,751 | 7,260 |
| 5 | 90 | 2,970 | 1,452 |
| 10 | 45 | 1,485 | 726 |
| 20 | 23 | 759 | 363 |
| 40 | 12 | 396 | 198 |

The last column is the same statewide arithmetic on 11.4 frames/s, set
beside column three so the sensitivity to the *measurement* is as visible
as the sensitivity to **S**. The
two differ by 2× at every row, which is smaller than the range of **S** itself
— and that is the point: **S dominates the bill, and nobody should sign one
until it is measured.**

### 17.4 The benchmark that closes this section

**S** is not a literature value; it depends on the accelerator, the batch size,
the model precision and the decode path. It is one afternoon of work on the
target hardware:

1. Run the existing analytics process against a fixed 1,000-frame sample on the
   CPU baseline and record frames/s. That is the denominator, already measured
   here at 5.6 with the full pipeline.
2. Repeat on the candidate accelerator with the same sample, same model weights
   and same precision.
3. **S** is the ratio. Read the matching row above.
4. Re-run at the district's real camera count, because contention — not raw
   inference speed — is what cost this platform half its throughput.

**Steps 1–3 are now one command, and have been run once.** On the development
machine — an Apple M5, whose GPU is integrated, not a data-centre accelerator —
`tools/bench/detector_device.py` runs the production detector and then the
whole per-frame pipeline on CPU and on the GPU (MPS), each in its own process,
over the same 2560×1440 frames, and checks the outputs agree before reporting a
ratio:

| What was timed | CPU median | GPU median | **S** | Parity |
|---|---:|---:|---:|---|
| Detector alone (RT-DETRv2-R18) | 448 ms | 133 ms | **3.4** | 3,622 of 3,622 boxes matched at IoU ≥ 0.9 |
| Whole pipeline (detect, track, plate, OCR) | 598 ms | 293 ms | **2.0** | same 67 observations, same plates |

Source: `var/reports/detector_device.json`, `var/reports/pipeline_device.json`.
The whole-pipeline ratio is the one to read into §17.3, and it is lower than
the detector's because the plate detector is an ONNX model kept on CPU
(CoreML fails on its zero-element dynamic shapes, recorded in
`runtime/profile.py`). It was measured with the earlier CPU recogniser; the
Indian recogniser that replaced it (§4.2) runs on the GPU, a frame's plates in
one batch, and this table has not been re-run since. The first GPU measurement was 201 ms, not 133: a
post-processing loop synced the GPU once per detected box. That was software,
and it is fixed; what remains is the model on the device. **S = 2.0 is a
laptop's integrated GPU.** It says the method works and the pipeline is not
CPU-bound by construction; it is not the target accelerator's row, which the
same command produces on that hardware.

Step 4 is the one usually skipped, and it is the one this project learned the
hard way: moving from one camera to four raised aggregate throughput roughly
sixfold while per-camera latency stayed flat, which says the worker was waiting
on frames rather than saturating the processor. Ingest concurrency is the first
thing to size, not the accelerator.

### 17.5 What this design does not spend, and why

The costs avoided are as material as the ones incurred.

| Avoided | Because |
|---|---|
| Central video storage (~52 PB modelled) | Video stays at the camera/NVR |
| Central video bandwidth (~160 Gbps modelled) | Only metadata and ~1 Hz stills traverse the uplink |
| Per-camera VMS licensing at the centre | Departmental VMS platforms are integrated, not replaced |
| Registry sharding | 80,000 camera rows occupy **58.01 MB**; onboarding runs at **114,742 cameras/s**, gap analysis over all 80,000 in **85 ms**, single lookup **0.46 ms** — all **MEASURED**, and regenerated by `tools/reports/scale_load_test.py` rather than transcribed |

**Operational cost is dominated by inference, not by storage or transport.**
That is the opposite of the assumption a central-VMS design starts from, and it
is why this proposal declines statewide central recording in §3 rather than
costing it.

## 18. Cybersecurity architecture

Step 3 names cybersecurity architecture as a design dimension in its own right,
and Step 6 asks for cybersecurity controls alongside backup and disaster
recovery. `docs/SECURITY.md` covers what the *application* enforces — four
independent authorisation gates, purpose binding, a hash-chained audit. This
section covers the *deployment*: the network it sits in, what is encrypted,
and where keys live.

Every control below is marked **IMPLEMENTED** — enforced by code in this
repository and covered by tests — or **SPECIFIED**, meaning it is a deployment
requirement this build does not itself perform. The distinction is the point.
A prototype claiming enterprise controls it does not run is worth less than one
that says which is which, because only the second can be deployed against.

### 18.1 Trust zones

Five zones, each crossing into the next through exactly one control point.

| # | Zone | Holds | Crosses into the next via |
|---|---|---|---|
| 1 | Camera | Departmental cameras, NVRs, existing VMS | RTSP/ONVIF pull, read-only, initiated from zone 2 |
| 2 | Edge node | Ingest, detection, ANPR, local store, queue | Outbound mTLS to zone 4. No inbound path. |
| 3 | Operator | Browsers on the police network | HTTPS to zone 4 only |
| 4 | Core | API, registry, search, evidence, audit | Database protocol to zone 5 |
| 5 | Data | PostgreSQL/PostGIS, object store, audit chain | — |

Two properties matter more than the table.

**Zone 1 is never trusted.** Departmental cameras are unpatched, multi-vendor,
and outside this project's control. Zone 2 pulls from them; nothing in zone 1
initiates a connection, so a compromised camera reaches a decoder and no
further. §6.2 of `docs/SECURITY.md` treats camera-supplied text as hostile for
the same reason — a camera name is attacker-controlled input.

**Zone 2 has no inbound path from zone 4.** An edge node dials the centre; the
centre never dials the edge. A compromised centre therefore cannot reach into
district infrastructure, and an edge node behind carrier NAT needs no inbound
firewall rule. The cost is that commands to an edge node are pulled on its own
schedule rather than pushed, which §15 already assumes for recovery.

**Nor does a library make a call of its own.** ONNX Runtime 1.29 starts
Microsoft's usage-telemetry client on import and uploads a queue it keeps in
the user's Library folder; on the development machine it had been doing so
for four weeks. It was found from a crash report - its worker thread aborted
interpreter shutdown about one run in four - not from a review, which is the
lesson: an edge node's egress should be denied by default at the host
firewall, so a dependency that phones home fails closed. The package now sets
`ORT_DISABLE_TELEMETRY` before the runtime can load, and a test holds it.

### 18.2 Encryption in transit

| Leg | Control | Status |
|---|---|---|
| Operator → core | TLS 1.3, HSTS with preload, no fallback below 1.2 | **SPECIFIED** — terminated at the gateway, not by this process |
| Edge → core | Mutual TLS; the client certificate is the node's identity | **SPECIFIED** |
| Core → database | TLS, certificate pinned to the database host | **SPECIFIED** |
| Camera → edge | RTSP, commonly cleartext on departmental networks | **SPECIFIED** as a segregated VLAN, because it frequently cannot be encrypted |

The last row is the honest one. Much of the existing estate speaks RTSP without
transport security and cannot be upgraded without replacing hardware, which the
Core Goal rules out. The mitigation is topological rather than cryptographic:
camera traffic stays on its own VLAN, terminates at the edge node, and never
traverses the WAN. Claiming end-to-end encryption across an estate of this age
would be false.

### 18.3 Encryption at rest

| Object | Control | Status |
|---|---|---|
| Database | Volume-level encryption (LUKS or the cloud equivalent) | **SPECIFIED** |
| Evidence files | Volume-level encryption plus a per-package content hash | Hash **IMPLEMENTED**; encryption **SPECIFIED** |
| Audit chain | Rows in the encrypted database, chained by SHA-256 | Chain **IMPLEMENTED**; encryption **SPECIFIED** |
| Backups | Encrypted with a key held separately from the backup medium | **SPECIFIED** |

`docs/SECURITY.md` §8 already records that this build performs no encryption at
rest. What it did not say, and this does, is what the deployment must provide
instead. Note the limit honestly: volume encryption protects a stolen disk, not
a live compromise of the host, and the hash chain detects tampering rather than
preventing it.

### 18.4 Key and secret management

**IMPLEMENTED.** No credential is read from a file in this repository. Keys come
from the process environment or they do not exist, which is stated in
`src/saakshya/copilot/backends.py` and enforced by `tools/verify/secret_scan.py`
across every tracked file and the full git history. Bearer tokens are stored
only as SHA-256 digests, are printed once at mint time, and cannot be recovered;
disabling a user invalidates every token it holds. Minting requires shell access
on the host — there is deliberately no credential-issuing HTTP endpoint, because
an ADMIN session on the network is a lower bar than a shell.

**SPECIFIED.** A deployment holds TLS private keys, database credentials, the
at-rest volume key and any upstream API keys in a managed secret store — KMS,
Vault or the platform equivalent — with rotation on a fixed schedule and on
departure of anyone who held them. This build has no PKI: evidence integrity is
a content hash, and signatures need a signing authority the deployment must
supply.

### 18.5 Gateway controls

| Control | Status |
|---|---|
| Concurrency bounds on search and export | **IMPLEMENTED** (`Limits`: 8 searches, 2 exports) |
| Result and export caps | **IMPLEMENTED** (2,000 results, 500 export items) |
| Absurd time ranges refused before the database | **IMPLEMENTED** (400-day span) |
| Request timeout | **IMPLEMENTED** (30 s) |
| Per-principal rate limiting | **SPECIFIED** — at the gateway |
| Request body size limit, HSTS, security headers | **SPECIFIED** — at the gateway |

Concurrency is bounded in this build; request *rate* is not. The submission
rules invite participants to host the platform publicly with test credentials,
and an unauthenticated rate limit is the control that matters most in that
setting.

### 18.6 What an attacker gains from each zone

Stated so the segmentation can be argued with rather than admired.

- **A compromised camera** reaches a decoder on one edge node. It cannot reach
  the core, and its name and metadata are already treated as hostile input.
- **A compromised edge node** holds its own district's recent observations and
  its client certificate. It cannot read another district's data, because the
  core scopes every query by jurisdiction, and revoking one certificate isolates
  it.
- **A compromised operator browser** acts as that operator, within their role,
  jurisdiction and purpose binding — and every action is in the audit chain. It
  cannot mint tokens, because minting needs a shell.
- **A compromised core** is the serious case: it reads the estate. Jurisdiction
  scoping is enforced there, so it is not a further boundary. What survives is
  detection rather than prevention — the audit chain is append-only and
  externally verifiable, so the compromise is visible afterwards. §15 covers
  recovery.

An unkeyed hash chain stored in the database it protects does not stop a writer
with database access from rebuilding it. Making that survivable needs the chain
head published outside the system — a separate append-only store or a
periodically notarised digest — and that is **SPECIFIED**, not built.

## 19. What this proposal will not say

- Not production ready.
- Not legally admissible. BSA s.63 stays `DRAFT_PENDING_SIGNATURE`.
- Not tested at 80,000 cameras.
- Not that ANPR works on this estate uniformly — 0 cameras grade GOOD.
- Not that the live government grid has a multi-camera plate identity. It has **0** exact cross-camera repeats. That demonstration is on the own-feed corpus.
