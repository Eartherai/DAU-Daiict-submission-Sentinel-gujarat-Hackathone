# High-Level Design

**SAAKSHYA — Federated CCTV Intelligence and Evidence Fabric**
Gujarat Police Innovation Challenge 2026 · Hybrid of Models 1 + 2 + 3 with a
selected-camera Model 4 central analytics proof-of-concept.

Submitted as the Technical Proposal. Engineering detail is in
`docs/ARCHITECTURE.md`; this document states the design and its justification.

**Where the portal's headings are answered**

| Portal heading | Section |
|---|---|
| Overall Architecture | 2, 3, 4 |
| Integration Strategy | 3 (Models 1–3), 10, 13 (items 1, 6) |
| AI & Video Analytics | 4.2–4.5, 11, 11.2 |
| Cybersecurity Architecture | 18 (application gates in 4.8) |
| Deployment Architecture | 6, 20.1 |
| Infrastructure Sizing | 20.1–20.3 (on the model in 17) |
| Cost-Benefit Analysis | 17.5, 20.8, 20.9 |
| Department-wise Information Requirements | 13 |
| Scalability Strategy | 12, 17, 20.6, `docs/SCALE_MODEL.md` |
| Future Roadmap | 14 |
| Hardware & Software Requirements | 20.3 |
| Network & Bandwidth Planning | 20.4 |
| Storage & Retention Strategy | 20.5 |
| AI Processing Capacity | 17.1–17.4, 20.2 |
| Disaster Recovery Strategy | 15, 20.7 |
| Statewide Rollout Plan | 16 |

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
| P1 | Move metadata, not video | Analytics run at the edge; ~400 B MODELLED optimised payload vs 1,331.7 B MEASURED serialised row (`var/reports/bandwidth.json`); sizing uses the measured row |
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
central analytics.** The evaluation baseline is **30 GOVERNMENT + 2 OWN_FEED + 18
SYNTHETIC_CONTROL = 50** (`src/saakshya/command/domain.py`,
`enforce_evaluation_50`). Operator-onboarded cameras are retained, so a runtime
registry can exceed that baseline. Government availability is measured during
a test window; onboarding does not establish simultaneous viewing or inference.


**Model 1 — Camera registry & GIS (mandatory, kept).** Identity, geometry,
transport, health and *measured capability*. The historical government snapshot
placed nineteen cameras from names (`DERIVED_FROM_NAME`) and left eleven
unlocated (`NAME_INSUFFICIENT`), listed without invented coordinates
(`docs/MEASURED_RESULTS.md`, 6 September snapshot).
Model 1 does not stream live video.

**Model 2 — Unified viewing (kept).** Direct integration with reachable
cameras/NVRs and departmental systems over RTSP/ONVIF, without federation
middleware. Both the direct path and the Model 3 path register in compulsory
Model 1 (official FAQ Q12–Q23).

**Model 2 media policies (VERIFIED, `ui/app.js`, `tileWhepBudget`).**
CONTROL ROOM (Dense 6×5) opens one direct WHEP session per tile, up to 30,
400 ms apart. OPTIMIZED VIEW (default scrolling wall) holds at most 12
sessions near the viewport, prefetches 600 px, and releases sessions 15 s
after leaving it. `#media-policy` names the active policy. Browser signalling
uses SAAKSHYA’s authenticated proxy; Sentinel credentials stay server-side.
Selected AI workers read RTSP/TCP separately. These are local viewing policies,
not sandbox limits or a claim that every tile is currently live.


**Model 3 — VMS federation middleware (kept).** Departmental VMS APIs/SDKs
connect through system adapters to a unified downstream interface. The
adapter contract and DEMO/TEST connectors are in `docs/ADAPTERS.md`; live
departmental VMS credentials are still required. Government RTSP and local
MediaMTX transport alone do not establish Model 3 federation. Departmental
infrastructure is retained; metadata feeds search, correlation and alerts.

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
on CUDA the authors measure 5 ms. Over a whole 57-second clip, with the vote as
it first stood, it published 83 marks against Vision's 29: 47 checked correct by
eye against 17, 13 wrong against 6. The vote was then made to refuse what the
frames do not agree on (below), and never-issued numbers (0000, RTO 0). The
final pipeline publishes 56 marks on that clip: 40 checked correct, 4 wrong,
12 not settled by a crop; 11 of the 20 hand-read plates exactly (Vision: 5);
and nothing on the car whose digits the footage blurs, where it had invented
three marks (`var/reports/ocr_indian_eval.json`, `final_pipeline`). Fewer marks,
a third of the wrong ones: for a system whose output starts investigations,
that is the trade to make.
Apple Vision and the ONNX model remain the fallbacks where the weights are not
installed. Every read is interpreted against the **positions of the Indian format**:
an O where the RTO must be a digit is 0, an 8 where a series letter must be is
B; only forced, unambiguous pairs, at most two, stated in the read, with the raw
OCR kept. End to end on 20 s of the queue, the published marks checked by eye
went from 0 of 9 correct to at least 7 correct. Most wrong marks that remain
are one character from a real plate on the same clip, at 40-50 px of plate;
better optics buy the rest, and a one-vote read is published only as a lead
requiring verification.

Current demonstration hardware limits simultaneous deep-inference
concurrency. Analytics workers scale horizontally, so additional GPU nodes
raise concurrent inference throughput without redesigning ingest, event,
watchlist, GIS or investigation services.

The default is **4 deep-inference slots, prioritised by measured capability**
(VERIFIED in `src/saakshya/analytics/worker.py`, `SAAKSHYA_AI_CAMERA_LIMIT`).
At worker boot, stream-capable enabled cameras are ranked GOOD > DEGRADED >
UNKNOWN > UNSUITABLE by ANPR grade; ties use camera id. Assignments do not
rotate at runtime. This configured default is separate from the historical
four-camera measurement in `reports/SCALE_80K_LOAD_TEST.md`.
`command/summary.py` reports “N of M camera(s) with a stream under
analysis”. Integrated cameras remain available to the viewer and health
surfaces, subject to source availability. `AdaptiveInferenceScheduler` changes
inference **cadence** by NORMAL / HIGH_PRIORITY / ALERT / FORENSIC priority;
it does not rotate which cameras receive deep inference. GPU pool capacities
in this proposal are **MODELLED/SIZED**, not measured cluster throughput.

**MEASURED government output (historical store, not simultaneous coverage).**
`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md` records 1,155,325 observations,
including 529,966 car and 307,290 person observations; persons were detected
across all 30 government cameras over the stored date range. ANPR has 901
read rows, 178 distinct plates, and 97 distinct plates with at least two
agreeing frames (474 read rows), on 9 cameras. There are no government
cross-camera plate matches or appearance embeddings. The cam12 person-zone
rule is an administrator-created demonstration rule. These are stored
analytics outputs, not ground-truth accuracy or a completed government
multi-location vehicle trace (official FAQ Q27–Q31).

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

**Older sealed-still limitation.** A content hash verifies unchanged bytes,
not that the image shows the vehicle named by its plate record. The older
worker sealed the frame in hand when a track closed; that frame can show a
different vehicle. Treat older stills as requiring visual/source verification,
including those in historical trace reports and films. Since commit `672a2a0` the worker
seals the frame each plate was best read from, so new captures show the read
vehicle's frame; stills sealed before it are unchanged. See `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`.

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
(`var/reports/store_engines.json`). On 80,000 synthetic registry rows, viewport and radius
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
errors**, ending with 44 streaming and 6 down, 36 open failures and no
recovery (`var/reports/camera_load.json`). The single-process local-load rate
was 11.4 frames/s; sizing uses the historical ~5.6 fps full-pipeline baseline
(§17.1). API p50 2.0–23.1 ms, p99 ≤44.7 ms on the DEMO store
(`var/reports/api_latency.json`). Offline replay is VERIFIED in
`tests/e2e/test_offline_mode.py`.

**MODELLED** — 80,000 cameras across ~33 district nodes; 160 Gbps / 52 PB for
central video. At 10–20% activity, metadata is 92.16–184.32 GB/day on the
MODELLED 400 B payload or 306.82–613.65 GB/day on the MEASURED 1,331.7 B
row; both daily rates are MODELLED (`docs/SCALE_MODEL.md`). Sizing uses the latter.

The distinction is maintained everywhere. Nothing modelled is quoted as tested.

## 8. Risks

| Risk | Mitigation | Residual |
|---|---|---|
| Real feeds differ from the corpus | Profile before tuning; staged model selection per tier | High until access exists |
| Analytics throughput per process | GPU profiles; more processes per node | Measured, understood |
| No PKI for evidence or bundles | Content hashes with the limitation stated everywhere | Accepted; needs a policy decision |
| Insider misuse | Purpose binding, scope, hash-chained audit | Recorded, not prevented |
| Evaluation mixes source domains | Preserve GOVERNMENT / OWN_FEED / SYNTHETIC_CONTROL labels and operator additions | Baseline composition in §3; not 50 government streams |
| Unavailable government feed | Per-camera backoff, isolation and visible health state | Shared-load availability varies; no participant catalogue is provided (`SENTINEL_SUPPORT_CLARIFICATION.md`) |

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
- **No government database integration claimed** — VAHAN, SARATHI, eGujCop (CCTNS), AFIS
  and NAFIS adapters refuse with `SourceUnavailable` (`watchlist/government.py`) naming what each would require.
- **ER/STQC** — camera compliance status is a registry field, not an assertion
  about this software.

## 10. Heterogeneous CCTV onboarding (Models 1 + 2 + 3)

Cameras arrive as RTSP (and, on the replica, MediaMTX). There is no assumption
of a shared VMS. Each camera is a registry row: identity, transport, codec,
resolution, measured capability, health, and — only if known — coordinates.

**MEASURED on the issued grid:** 30 cameras, 23× h264 + 6× hevc, mixed
resolutions, five departments in the estate of which three self-identify.
This is the 6 September snapshot (`docs/MEASURED_RESULTS.md`): the codec
counts exclude the unobserved camera. Nineteen were placed `DERIVED_FROM_NAME`;
eleven were listed `NAME_INSUFFICIENT`. No participant-specific catalogue is
provided; government intake uses probe-derived records (`source="probe"`).

**Integration feasibility (DESIGNED).** IP cameras and NVR exports use the
Model 2 direct path; departmental VMS APIs/SDKs use the Model 3 federation
path. Analog cameras require an existing DVR's supported digital channel
export or an encoder gateway; raw analog input is not implemented here.
Survey vendor/version, channel mapping, codec, clock/NTP configuration,
network route, bandwidth, retention, licences and access authority before
promising an integration. Private public-facing cameras may be viewed only
where feasible and permitted; require owner consent, scope and retention
policy. This proposal covers the FAQ's 26-department estate; the sandbox's
five departments are an evaluation sample, not the statewide total.

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

**MEASURED, read-only store snapshot:** government designated vehicle
`GJ11S7924` has 52 reads on cam06 only: **SINGLE-CAMERA** evidence.
`GJ38BH5815` has one read and a HIGH OPEN `evaluation_designated` alert on
cam21; it is not listed as stolen. The older `GJ1VV0119` rehearsal is an
`investigation_target` on cam07. **DEMO:** `GJ18JX7786`, C-014 then C-021,
is the **CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION**. Sources and SQL
are in `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`; no government cross-camera
trajectory is claimed.

### 11.1 Alert workflow — from a read to an officer's decision

1. **Correlate at ingest.** Every published plate is checked against the
   active watchlist in the same transaction that stores the sighting, so a hit
   cannot be missed by a later batch job. The match is exact, or a declared
   near match: the read and the listed mark are aligned character by character
   and every difference is labelled an OCR confusion (0/O, 5/S, 8/B...) or a
   real difference, so "EXACT" and "NEAR" are claims the officer checks by eye.
2. **Categorise.** Stolen, wanted, suspect and blacklisted vehicles,
   investigation targets, and wanted- and missing-person entries (matched today
   through their associated vehicles - see 11.2). Each entry carries a priority,
   a reason and the authority that listed it.
3. **Prioritise honestly.** The priority shown is the entry's, stepped down one
   level when the read rests on a single frame (a lead, not a hit) and up one
   level when the vehicle has been seen on three or more cameras, with the
   reason in words (`watchlist/incidents.py`).
4. **Group, not spam.** One incident per vehicle and watchlist entry; reads
   within a ten-minute duplicate-hit window are one pass, a later read is a new
   pass inside the same incident. On the evaluation store this turned 128 open
   alert rows into thirteen incidents.
5. **Visualise.** The Alerts view is the queue: priority, category, read
   against list, camera, time and the sealed still. From an alert the officer
   opens the vehicle's route on the map, the next cameras it could reach, and a
   printable trace report with a digest over its rows.
6. **Act, on the record.** An alert moves OPEN -> ACKNOWLEDGED -> UNDER
   INVESTIGATION -> CLEARED, clearing requires a reason, and every transition
   is written to the hash-chained audit log with the officer, case and purpose
   (`POST /alerts/{id}/acknowledge | investigate | clear`). Evidence from the
   sighting is sealed into the evidence chain on demand.
7. **Notify.** In the PoC the operator is notified in the workspace queue. A
   control-room integration (SMS, radio dispatch, an existing CAD system) is an
   adapter on the incident stream, not built here, and would carry the same
   priority and reason text.

### 11.2 Persons: what is built, and the gated path to facial recognition

**Built.** Person detection and tracking on every analysed frame, a
long-stay report (a duration on one camera, never called loitering or
intrusion), and restricted-zone rules a department sets - polygon, hours,
classes, reason and authority - with every entry into the zone listed as a
sighting. Wanted- and missing-person watchlist entries exist as categories and
are correlated today through vehicles associated with the person.

**Facial recognition is designed and gated, not shipped.** The platform can
carry an FRS module on the same observation bus; it is deliberately not
switched on in this PoC, for three reasons that a deployment would have to
answer first:

- *Authority and gallery.* 1:N search needs an enrolled gallery from an
  authorised departmental database, a recorded legal basis per entry, and a
  retention limit - the same authority and reason fields the watchlist and zone
  rules already carry. No such gallery was provided, and enrolling faces
  scraped from footage would be the wrong precedent. The Digital Personal Data
  Protection Act, 2023 applies to such processing.
- *Capability.* As with plates, a camera must be graded for faces before it is
  asked to recognise them: the useful measure is pixels across a face at the
  camera's measured distances. On the footage used here faces are a few pixels
  across (the published own-feed film blurs heads for that reason), so these
  cameras would be graded unsuitable, exactly as most government views are
  graded unsuitable for plates.
- *Harm.* A wrong plate points at a car; a wrong face points at a person.
  The design therefore returns candidates requiring verification, never
  identifications; binds every search to a case and purpose, as plate search
  already is; logs every search in the audit chain; and lets a department set
  the threshold per camera grade.

The design: face detection only on person tracks at cameras graded suitable;
embeddings compared against the authorised gallery; a hit raises a
`wanted_person` or `missing_person` incident through the same workflow as 11.1,
at one priority step below a verified plate hit until an officer confirms it.
What a department must supply for this is listed in section 13.

## 12. Statewide operations — what is asked, what is claimed

Organisers asked for edge / GPU / bandwidth / storage / HA / cost. Status is
the same discipline as the rest of the proposal.

| Topic | Claim | Label |
|---|---|---|
| Central / regional / edge | ~33 district nodes × 2,000–3,000 cameras; centre aggregates metadata | **MODELLED** (`docs/SCALE_MODEL.md`) |
| GPU / accelerators | One CPU process: 11.4 fps local-load benchmark; historical 5.6 fps full pipeline (size on this, §17.1). A 2,500-camera node at that rate needs GPU inference at the district, not a rewrite. Profiles: `DEV_CPU` / `CLOUD_GPU` / `TARGET_GPU` | **MEASURED** throughput; **DESIGNED** GPU split |
| Bandwidth | Do not copy video to the centre. Wall policies are in §3. MODELLED gated metadata: 92.16–184.32 GB/day at 400 B or 306.82–613.65 GB/day at the measured 1,331.7 B row; sizing uses the latter (§20.4). Low-connectivity: edge continues, queue replays | **MODELLED** / **MEASURED** offline tests |
| Hot / warm / cold storage | Video stays at the camera/NVR. Hot: 30 days of metadata + sealed evidence at the node. Warm/cold: partition observations by month. Retention is a policy decision | **DESIGNED**, **UNTESTED** at 80k |
| Load balancing / health | Horizontal processes per node; `/system/health`; hash-chained audit | **MEASURED** on 30 cameras; **UNTESTED** as a cluster scheduler |
| HA / backup / DR | Edge detection, watchlist, alerts and evidence continue with the uplink down (`tests/e2e/test_offline_mode.py`). Central HA, backup and DR designed in §15; still **UNTESTED** multi-node | **MEASURED** offline; **DESIGNED** §15; **UNTESTED** multi-node |
| Cybersecurity | Four gates (auth, role, jurisdiction, purpose). ADMIN cannot search. Tokens not in query strings. No secrets in the repository | **MEASURED** on the API; statewide SOC integration **UNTESTED** |
| Cost | §17 gives the model and its measured inputs (5.6 fps full pipeline; **S = 2.0** whole-pipeline on an Apple M5 integrated GPU, 3.4 for the detector alone); the target accelerator's **S** comes from the same scripted benchmark before any figure is signed. §20.8 prices the model on an assumed **S** and assumed unit rates, as ranges, for procurement to replace | **MODELLED** §17; **S MEASURED** on dev hardware; unit rates **ASSUMED** §20.8 |

Nothing in this table is quoted as “tested at 80,000”.

## 13. Prerequisites from participating departments

To assess a further camera, and to stop inferring what a catalogue would have
stated:

1. **A camera inventory per department** (a spreadsheet is enough; the
   registry's CSV import takes it): camera id, department, site, mount height
   and direction, codec, resolution, and coordinates. For the evaluation the
   organisers confirmed no participant catalogue (`/api/ingest`) would be
   provided, so this grid's records are probed and say `source="probe"`; a
   `CATALOGUE` basis supersedes them with no code change.
2. **Surveyed coordinates** where names are insufficient (the eleven unlocated
   cameras on this grid).
3. **Stream access** already issued for the 30-camera evaluation grid.
4. **Retention and evidence policy** — how long metadata and sealed records may
   be kept; BSA s.63 signing authority is outside this software.
5. **Watchlist authority** if a government list is to replace the representative
   one: issuer, validity, revocation, and the legal basis for matching.
6. **NVR / VMS access** where cameras are not reachable directly: vendor and
   version, and either an RTSP/ONVIF export per channel or the VMS's own API
   for live and recorded streams. Only frames and a stable camera id are
   needed; no VMS is replaced.
7. **Network path and bandwidth** from each district to its edge node: whether
   streams can be pulled on demand, and the uplink for metadata (1,331.7 B MEASURED serialised row; ~400 B MODELLED compact payload,
   `var/reports/bandwidth.json`; sizing uses the measured row) to the centre.
8. **For facial recognition, if a department wants it (11.2):** an authorised
   gallery with a recorded legal basis per person, a retention limit, a
   decision on who may search, and cameras surveyed for face resolution.

### Department-wise information requirements

The common inventory and authority fields above apply to every department.
These are requested inputs, not claims of access already granted.

| Department | Required local information |
|---|---|
| Home / Police | Junction and jurisdiction mapping, control-room VMS exports, authorised watchlist issuer, incident escalation and evidence signing authority |
| Food & Civil Supplies | Godown/PDS shop inventory, DVR/NVR exports, retention, ownership, uplink and authorised viewing roles |
| RTO | Office/test-track/checkpoint channels, plate visibility, time synchronisation, vendor/API access and retention |
| Health | Hospital camera ownership, restricted clinical areas, privacy masks, access roles and retention policy |
| GSRTC | Depot and bus-station channel mapping, vehicle lanes, timetable context, VMS/RTSP exports and uplink constraints |
| Panchayat | Village/site coordinates, power and backhaul availability, local maintenance owner and offline queue requirements |
| Municipal bodies | Ward and traffic asset mapping, overlapping coverage, NVR/channel inventory, storage retention and maintenance contacts |

## 14. Future roadmap (PoC → district → state)

This is a plan, not a claim of work already done.

| Horizon | What | Label |
|---|---|---|
| Next on-site PoC (date to be confirmed) | Evaluation baseline in §3, designated-vehicle search, watchlist alerts, CONTROL ROOM / OPTIMIZED VIEW. Target GPU benchmark before sizing. | **DESIGNED** |
| District node | One district, 2,000–3,000 cameras, `TARGET_GPU` profile, local store and queue, watchlist bundles from the centre | **DESIGNED** |
| Catalogue-backed Model 1 | Authoritative ids, departments and surveyed coordinates replace `DERIVED_FROM_NAME` / `probe` | **DESIGNED** — requires departmental inventory; no participant sandbox catalogue is promised |
| Government watchlist feed | Same match path; replace `REPRESENTATIVE` with an authorised issuer | **DESIGNED** — blocked on legal basis and API |
| Statewide centre | Cross-district search over metadata; no central video farm | **MODELLED** |
| Face recognition | Gated (11.2): only with an authorised gallery, a legal basis per entry, and cameras graded for face resolution. | Department decision |
| VAHAN / SARATHI / eGujCop (CCTNS) / AFIS / NAFIS | Adapters refuse with `SourceUnavailable`, stating required access (`watchlist/government.py`). No integration is claimed. | **DESIGNED** access |

## 15. Disaster recovery and redundancy design

A named Model 4 deliverable. Section 12 records DR as **UNTESTED** at the
centre; this is the design that would be tested, not a claim that it has been.

**What must survive what.** The estate is federated by construction: video
stays at the camera or NVR and district nodes hold their own store, queue and
watchlist. That is a resilience property, not only a bandwidth one — losing the
centre does not stop a district detecting, matching or sealing evidence.

| Failure | Blast radius | Behaviour | Label |
|---|---|---|---|
| Centre unreachable | Statewide search, cross-district correlation | Districts continue: detection, watchlist, alerts and evidence all local. Metadata queues and replays on reconnect. | **MEASURED** — `tests/e2e/test_offline_mode.py` |
| District node lost | That district's live analytics | Cameras keep recording to their own NVR. No central video was being written, so no footage is lost — only analysis is paused. | **DESIGNED** |
| Store corruption at a node | That node's metadata | Restore from the last snapshot; replay the queue from the centre's copy of that district's metadata. | **DESIGNED**, **UNTESTED** |
| Evidence tampering | One record | Hash chain detects it. 5 of 5 tamper tests detected. | **MEASURED** |
| Upstream grid refuses sessions | Affected viewing or AI source connections | Tiles show fallback/health state and workers back off per camera. Stored observations remain available; separate RTSP and WHEP paths do not guarantee independent upstream availability. | **VERIFIED** — `live/hub.py`, `ingest/stream.py`; support guidance in `SENTINEL_SUPPORT_CLARIFICATION.md` |

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
| Local replica load, one analytics process | **11.4 frames/s** | 1,019 frames processed across local camera queues; `tools/perf/camera_load.py`, `var/reports/camera_load.json`. |
| Historical AI worker, full pipeline, four cameras concurrently | **~1.4 frames/s per camera, ~5.6 aggregate** | Historical measurement recorded in `reports/SCALE_80K_LOAD_TEST.md`; detection, ANPR and tracking share the host. Not remeasured with the current recogniser. |

**Size on the second.** The first is the local replica harness, which times
`CameraPipeline.process` across camera queues (not detection only or a
single stream). The second is the historical government worker doing the whole
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
gpu_speedup_factor          = S              2.0 MEASURED laptop GPU; target UNKNOWN — must be benchmarked
inference_nodes_per_district= 2,500 / (5.6 × S)
districts                   = 33
```

### 17.3 Solved for every value of S

Speedup is measured only on the laptop integrated GPU (§17.4), so the model
is solved across the range. Procurement benchmarks **S** once and reads its own row.

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
| Whole pipeline (detect, track, plate, OCR) | 598 ms | 293 ms | **2.0** | same 67 observations; no plates on either device in this 145-frame sample |

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

Step 4 measures contention at the intended concurrency. Registry scale alone
cannot determine ingest or inference capacity; benchmark both independently
on the target host before using the MODELLED GPU pool sizes.

### 17.5 What this design does not spend, and why

The costs avoided are as material as the ones incurred.

| Avoided | Because |
|---|---|
| Central video storage (~52 PB modelled) | Video stays at the camera/NVR |
| Central video bandwidth (~160 Gbps modelled) | Metadata uplink sized separately from on-demand wall viewing (§20.4) |
| Per-camera VMS licensing at the centre | Departmental VMS platforms are integrated, not replaced |
| Registry sharding | 80,000 camera rows occupy **58.05 MB**; onboarding runs at **57,647 cameras/s**, gap analysis over all 80,000 in **181.7 ms**, single lookup **0.69 ms** — all **MEASURED**, and regenerated by `tools/reports/scale_load_test.py` rather than transcribed (`reports/SCALE_80K_LOAD_TEST.md`) |

**Operational cost is dominated by inference, not by storage or transport.**
That is the opposite of the assumption a central-VMS design starts from, and it
is why this proposal declines statewide central recording in §3 rather than
costing it. §20.8 and §20.9 put both sides of that on assumed unit rates.

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

## 20. Infrastructure sizing, costs and cost-benefit

The portal asks for central / regional / edge compute, accelerators, hardware
and software, bandwidth, storage by retention, operations, DR, costs, and a
cost-benefit case. This section answers each from the figures already measured
above and the model in §17; it adds no new measurement. Every line carries one
of four labels:

- **MEASURED** — a run of this software, with its report under `var/reports/`.
- **MODELLED** — arithmetic on measured inputs (§17, `docs/SCALE_MODEL.md`).
- **ASSUMED** — a planning input this project did not measure: the accelerator
  speedup **S**, a unit price, a retention period. Each is stated so it can be
  replaced.
- **ESTIMATE** — a benefit figure that follows from assumptions. None is a
  measurement.

The planning unit is the one §6 and §17 use: **33 district nodes of 2,500
cameras** (82,500 camera slots, so 80,000 cameras fit with room), each camera
sampled at 1 Hz.

### 20.1 Compute tiers

| Tier | Where | Runs | Sized by | Label |
|---|---|---|---|---|
| **Camera site** | Existing cameras and NVRs | Nothing new. Cameras keep recording to their department's NVR at the department's own retention. | — | Existing estate |
| Camera site, thin backhaul (optional) | A site whose link cannot carry its streams to the district node | A small accelerator box on the same codebase (`TARGET_GPU` or `DEV_CPU` profile, SQLite store, local queue) running T0/T1 and shipping metadata only | Network survey per site; 25 per district **ASSUMED** in §20.8 | **DESIGNED**, not run on such hardware |
| **Regional — district edge node** | One per district | Ingest and decode, detection, tracking, ANPR, watchlist match at ingest, alerts, evidence sealing, local PostgreSQL + PostGIS, durable queue | Inference: §17 model. Decode: 50 streams in one process on a 10-core host, 44 sustained, ~98 MB RSS per camera (`camera_load.json`) | Inputs **MEASURED**; node **MODELLED** |
| **Central** | State data centre plus a DR site | Metadata aggregation, cross-district search and trajectory, evidence chain, hash-chained audit, GIS, watchlist issuance (bundles fail closed, §4.7) | Metadata rate (§20.4) and query load; no video, so no inference at the centre except selected-camera Model 4 PoC streams | **MODELLED** |

The centre does not run detection for the estate. That is the decision §3
makes on arithmetic, and it is why the accelerators below all sit at the
district.

### 20.2 Accelerator sizing — the planning cases

From §17.2: `inference units per district = 2,500 / (5.6 × S)`, where 5.6
frames/s is the **MEASURED** full-pipeline rate and **S** is the accelerator's
speedup over that CPU baseline. The only **S** measured is 2.0, on a laptop's
integrated GPU (§17.4). A data-centre accelerator's **S** is not known here.

**Planning assumption: S = 10 (ASSUMED)**, one inference unit per GPU, four
GPUs per server (**ASSUMED**). S = 10 is chosen to sit well above the
integrated-GPU figure without borrowing a vendor's benchmark; the §17.4
command replaces it with a measurement on the tendered hardware before
anything is bought.

| Case | S | Inference units | 4-GPU servers | Label |
|---|---:|---:|---:|---|
| One district, 2,500 cameras | 2.0 (the laptop's, **MEASURED**) | 224 | 56 | **MODELLED** — shows why a laptop-class GPU is not the target |
| **One district, 2,500 cameras** | **10 (ASSUMED)** | **45** | **12** | **MODELLED** — the planning case |
| One district, 2,500 cameras | 20 (ASSUMED) | 23 | 6 | **MODELLED** — sensitivity |
| Statewide, 33 districts | 2.0 | 7,392 | 1,848 | **MODELLED** |
| **Statewide, 33 districts** | **10 (ASSUMED)** | **1,485** | **396** | **MODELLED** — the planning case |
| Statewide, 33 districts | 20 (ASSUMED) | 759 | 198 | **MODELLED** |

Solved directly on 80,000 cameras rather than 33 × 2,500 slots, S = 10 gives
1,429 units; the table keeps the per-district rounding because nodes are
bought per district.

Two things move this table and neither is software:

- **T0 gating is not counted.** `docs/SCALE_MODEL.md` models ~10% of cameras
  active at T1+ at once; if that held, a district would need about a tenth of
  the units above. It is not measured against a real estate, so the planning
  case sizes every camera at 1 Hz.
- **Decode is sized separately.** Linear from the one measurement (40 streams
  per 10 cores, derated from the 44 of 50 sustained), 2,500 streams need ~625
  CPU cores and ~245 GB of decoder memory — about ten 64-core servers per
  district (**MODELLED**, linear extrapolation from one host). Hardware video
  decode on the accelerators may absorb part of this; that is unmeasured and
  is step 4 of §17.4.

### 20.3 Hardware and software bill, per tier

Quantities follow from 20.2 (S = 10) and 20.5. Specifications are classes,
not models or vendors; the design is vendor-neutral and the tender picks the
part.

**One district node (2,500 cameras)**

| Item | Qty | Class | Why this many |
|---|---:|---|---|
| Inference servers | 12 | 2-socket, 4 data-centre inference GPUs, 256 GB RAM | 45 units at S = 10, plus 3 spare GPUs |
| Ingest / decode servers | 10 | 2-socket, 64 cores, 256 GB RAM | ~625 cores, ~245 GB decoder memory (20.2) |
| Database servers | 2 | 32–64 cores, 256–512 GB RAM, NVMe | PostgreSQL + PostGIS primary and synchronous standby |
| Application servers | 2 | 16–32 cores, 64 GB RAM | API, alerts, queue shipper; one active, one taking load |
| Hot storage (NVMe, usable) | 8 TB | Split across the two database servers | ~1.2 TB of 30-day metadata with indexes (20.5), with room for growth, per copy |
| Warm storage (HDD / object, usable) | 20 TB | NAS or object store | ~14.00 TB for a year of metadata with indexes, plus sealed evidence |
| Network | 1 set | 10 GbE top-of-rack pair, firewall pair, load balancer pair | Camera VLAN terminates here (§18.2) |
| Rack, UPS, cooling | 1 set | — | — |
| Site boxes (optional) | 25 | Embedded accelerator, 1 per thin-backhaul site | **ASSUMED** count, set by the site survey |

**Centre (statewide)**

| Item | Qty | Class | Why this many |
|---|---:|---|---|
| Database servers | 3 | 64 cores, 512 GB–1 TB RAM, NVMe | Primary, synchronous standby, asynchronous replica at the DR site |
| Application servers | 4 | 16–32 cores, 64–128 GB RAM | Stateless API behind the load balancer; N+1 |
| Monitoring and logging servers | 3 | 16 cores, 64 GB RAM, 20 TB | Metrics, logs, audit export (20.6) |
| Hot storage (NVMe, usable) | 120 TB | 40 TB per database copy | ~36.82 TB of 30-day metadata with indexes at the measured row size (20.5) |
| Warm storage (usable) | 450 TB | Object store or HDD tier | ~447.96 TB for a year of metadata with indexes |
| Cold / backup storage | 500 TB | Tape or cold object tier, off-site | Base backups, WAL archive, detached partitions |
| Evidence store | 50 TB | Object store with write-once retention | Sealed stills and manifests (**ASSUMED** volume) |
| Network, security, DR site facility | 1 set each | Core switches, firewalls, load balancers; DR rack | — |

**Software, every tier**

| Layer | Choice | Licence cost | Status |
|---|---|---|---|
| OS | Linux (any supported enterprise or community distribution) | ₹0, or a support subscription | **ASSUMED** — every measurement in this document was taken on macOS; Linux is the deployment target and is not measured in this build |
| Database | PostgreSQL 18 + PostGIS 3.6 | ₹0; optional support contract | **MEASURED** — §4.10 |
| Edge store | SQLite (same schema) | ₹0 | **MEASURED** |
| Inference | PyTorch, ONNX Runtime; vendor GPU driver and runtime | ₹0 | **MEASURED** on CPU and Apple MPS; the data-centre GPU path is **UNTESTED** |
| Application | FastAPI + Uvicorn, this codebase | ₹0 | **MEASURED** |
| Orchestration | Kubernetes (or a lightweight distribution at the edge), or systemd units per process | ₹0; optional support | **SPECIFIED** — the build runs as processes; no manifests ship |
| Monitoring / logging | Prometheus-compatible scraper, dashboards, a log store | ₹0 for open-source stacks | **SPECIFIED** — the endpoints exist (20.6) |
| Backup | PostgreSQL base backup + WAL archiving tool | ₹0 | **SPECIFIED** |
| Secrets | KMS / Vault / platform equivalent | Varies | **SPECIFIED** — §18.4 |

No per-camera software licence appears anywhere in this bill. Departmental VMS
platforms keep their own licences; this platform does not replace them (§10).

### 20.4 Network and bandwidth

| Flow | Rate | Crosses | Label |
|---|---|---|---|
| Camera → district node, video | 2 Mbps per pulled stream; 2,500 × 2 Mbps = **5 Gbps** if every camera is pulled continuously | Departmental / district network only, on a camera VLAN; never the WAN | **MODELLED** (the 2 Mbps of §1) |
| District → centre, metadata, modelled row | 400 B MODELLED optimised payload → 2.88–5.76 GB/day gated, ≤ **2.67 Mbps** at the ungated worst case (20 vehicles per camera-minute) | WAN | **MODELLED** (`docs/SCALE_MODEL.md`) |
| District → centre, metadata, measured row | The serialised row this build ships is **1,331.7 B** (`var/reports/bandwidth.json`), so 9.59–19.18 GB/day gated and ≤ **8.88 Mbps** ungated | WAN | Row size **MEASURED**; rate **MODELLED** |
| Wall video / still fallback | CONTROL ROOM up to 30 streams; OPTIMIZED VIEW at most 12 (§3). At an assumed 2 Mbps per stream: 60 / 24 Mbps per wall. Fallback JPEG size and rate must be measured separately. | Viewing network; WAN if viewed centrally | Policy **VERIFIED** in `ui/app.js`; bandwidth **MODELLED** |
| Evidence | Sealed stills and manifests, per case | WAN, on demand | **DESIGNED** |
| Centre inbound, statewide | 80,000 cameras × 20/min × 1,331.7 B × 8: **284.10 Mbps** worst case (33 × 2,500 district slots: 292.97 Mbps), metadata only | WAN | **MODELLED** |

**Provisioning (ASSUMED).** Per district: a 20 Mbps primary uplink to the
centre and a 10 Mbps secondary on a different carrier — above the metadata-only ungated
worst case. Central viewing adds the wall-video budget above; a dense wall
cannot be budgeted inside this metadata uplink. At the centre: two 500 Mbps links. Against the 160 Gbps a central
video design needs, statewide metadata at its worst is under 0.2% of that.

The planning figures use the measured row. The 400 B model is kept because
§2 and `docs/SCALE_MODEL.md` state it; the difference is what the code
actually serialises (identifiers, the `dedup_key`, the box, the raw OCR),
and a compact wire encoding is an optimisation not yet made.

**Low bandwidth and disconnection (MEASURED, `tests/e2e/test_offline_mode.py`).** The
district node keeps detecting, matching the watchlist, raising alerts and
sealing evidence with the uplink down (§15). Observations wait in a durable
local queue that is acknowledged, not deleted, so a lost acknowledgement
replays rather than losing data; the centre applies each event once by its
`dedup_key`. At the measured row size a district produces 9.59–19.18 GB a day
gated, so a week of disconnection is at most ~134.24 GB of queue
(`docs/SCALE_MODEL.md`, before queue/index overhead) — a disk, not
a design problem. Watchlist bundles travel the other way and fail closed on
integrity, issuer or version, so a node offline keeps its last valid list
rather than none.

### 20.5 Storage and retention

Video is not in any tier of this platform. It stays on departmental NVRs at
the department's retention (§13 item 4); a clip is pulled for a case, sealed,
and only then held here. Every retention period below is **ASSUMED** for
sizing and is a policy decision the department makes (§13).

| Tier | Holds | Medium | Retention (**ASSUMED**) | Per district | Centre |
|---|---|---|---|---:|---:|
| **Hot** | Current month's observations, open alerts, watchlist, audit | PostgreSQL on NVMe, indexed (10 of 10 hot queries use an index, **MEASURED**) | 30 days | ~1.2 TB | ~36.82 TB |
| **Warm** | Older monthly observation partitions, still queryable | PostgreSQL tablespace on HDD / object-backed volume | 1 year | ~14.00 TB | ~447.96 TB |
| **Cold** | Detached partitions, base backups, WAL archive | Tape or cold object tier, off-site | Set by policy (1–7 years is the range to decide within) | — | 500 TB provisioned |
| **Evidence** | Sealed stills, clips, manifests, BSA s.63 drafts | Object store with write-once retention; hash chain verified on read | Life of the case plus the appeal period | per case | 50 TB provisioned |
| **Audit** | Hash-chained audit log | PostgreSQL, partitioned, never pruned | Indefinite (`docs/SCALE_MODEL.md`) | small | small |

Sizes are the measured 1,331.7-byte row × the gated daily volume × retention,
doubled for indexes (the factor of two is **ASSUMED**; index overhead on the
production schema was not measured). `docs/SCALE_MODEL.md` shows both payload
cases: at 400 B the statewide 30-day range is 5.53–11.06 TB and the annual
range is 67.28–134.55 TB; the measured-row ranges are 18.41–36.82 TB and
223.98–447.96 TB. Storage provisions use the upper measured-row bound.

**What is built and what is not.** One schema on SQLite and PostgreSQL +
PostGIS is **MEASURED** (§4.10). Monthly partitioning of observations, the
tablespace move from hot to warm, and detaching partitions to cold are
**DESIGNED** — no partitioning code ships in this build. Partitioning is by
time because observations are append-only and every hot query is time-bounded.

### 20.6 Load balancing, scaling, monitoring, logging, health

| Concern | In the code today | A deployment adds |
|---|---|---|
| Liveness | `GET /healthz` — process answers | Load-balancer and orchestrator probes against it |
| Readiness | `GET /readyz` — store answers, evidence root present, graph loaded; 503 otherwise. Camera reachability deliberately excluded: an estate with cameras down is degraded, not unready | Remove an instance from rotation on 503 |
| Subsystem health | `GET /system/health` — eight components (feeds, grid access, inference, database, search, evidence, queue, AI provider), each with its evidence; UNKNOWN is never shown as HEALTHY; gated by `HEALTH_READ` | A dashboard and paging on FAILED / DEGRADED per district |
| Metrics | `GET /metrics` (Prometheus text) and `/metrics.json`: request latency per route, requests by status, access denials, admission rejections, unhandled errors, copilot grounding counters | Scraping, retention, alert rules; host, database and GPU exporters |
| Request correlation | `X-Request-Id` accepted or minted per request, returned on the response, carried into every log line and into access records | Trace propagation across the load balancer |
| Logging | Structured JSON logs to stderr (`SAAKSHYA_LOG_FORMAT`), method, route, status, duration, actor | Shipping to a central log store with retention |
| Audit | Hash-chained audit of every search, export, alert transition and admin change, with officer, case and purpose; verifiable | Export of the chain head outside the system (§18.6) and to a SIEM |
| Load bounding | Concurrency caps (8 searches, 2 exports), result caps, 30 s timeout, 400-day span refusal (§18.5) | Per-principal rate limiting at the gateway |
| API scaling | Stateless handlers over a shared store | N instances behind a load balancer (20.3 has 2 per district, 4 at the centre) |
| Analytics scaling | More processes, each taking a set of cameras — the architectural answer the load test names (`camera_load.json`) | A scheduler assigning cameras to workers and moving them on failure: **UNTESTED** as a cluster scheduler (§12) |

Everything in the middle column is **MEASURED** on the API and covered by
tests; everything in the right-hand column is **SPECIFIED**.

### 20.7 HA, backup and DR targets

The failure design is §15; the security of backups is §18.3. This adds the
numbers §15 left to the funder, as **ASSUMED** targets to be agreed:

| Scope | RPO (**ASSUMED**) | RTO (**ASSUMED**) | Mechanism |
|---|---|---|---|
| Evidence | 0 | Same as its store | Sealed before acknowledged (§15, by design) |
| District metadata | ≤ 5 min (the queue flush interval) | ≤ 8 h | Restore the last base backup, replay the queue from the centre's copy (§15) |
| District analytics | — (nothing to lose: video stays on the NVR) | ≤ 4 h to resume on spare GPUs | 3 spare GPUs per node (20.3); cameras keep recording throughout |
| Centre database | 0 for committed rows within the primary site; ≤ 15 min to the DR site | ≤ 4 h failover to DR | Synchronous standby on site, asynchronous replica at DR, nightly base backup + continuous WAL archive |
| Centre API | — | Minutes | Stateless instances behind a load balancer |

**Backup (SPECIFIED).** Nightly base backups and continuous WAL archiving at
every PostgreSQL instance, encrypted with a key held apart from the medium
(§18.3), one copy off-site; a quarterly restore drill whose success is the
only evidence the backup exists. Multi-node HA and DR are **UNTESTED** in
this build (§12).

### 20.8 Indicative implementation and operational costs (INR)

**Every unit rate below is ASSUMED**: a range typical of Indian public
procurement as this proposal understands it, not a quotation. **Procurement
replaces these rates with tendered prices; the quantities in 20.3 and the
model in §17 are what this proposal stands behind.** Figures are in lakh
(₹1 crore = 100 lakh), before taxes, and assume **S = 10**.

**Unit rates (ASSUMED)**

| Item | Rate |
|---|---|
| Inference server, 4 data-centre inference GPUs | ₹30–70 lakh each |
| CPU server (ingest, application, monitoring) | ₹8–15 lakh each |
| District database server | ₹15–30 lakh each |
| Centre database server | ₹25–50 lakh each |
| Hot storage, NVMe, usable | ₹0.5–1.5 lakh per TB |
| Warm storage, HDD / object, usable | ₹0.1–0.3 lakh per TB |
| Cold storage, tape / cold object | ₹0.02–0.06 lakh per TB |
| Site accelerator box | ₹1.5–4 lakh each |
| District network set (switches, firewalls, load balancers) | ₹15–35 lakh |
| District rack, UPS, cooling | ₹10–20 lakh |
| WAN bandwidth, district scale | ₹700–2,000 per Mbps-month |
| WAN bandwidth, centre scale | ₹300–800 per Mbps-month |
| Hardware maintenance (AMC) | 8–12% of hardware cost a year |
| Power and cooling | ₹2–3 lakh per GPU server-year; ₹0.5–1 lakh per CPU server-year |
| Operations engineer | ₹8–15 lakh a year (district); ₹10–20 lakh (centre) |

**Totals**

| Scope | What it includes | Implementation (capex) | Operations (per year) |
|---|---|---:|---:|
| **PoC** (≈50 cameras) | 1 server with 1–2 GPUs (S = 10 gives 1 unit for 50 cameras) ₹8–20 lakh, 1 small database server ₹5–10 lakh, network ₹1–3 lakh; integration services ₹15–30 lakh. Operations: AMC, power, 2–3 engineers | **₹29–63 lakh** | **₹18–50 lakh** |
| **One district** (2,500 cameras) | Hardware in 20.3: ₹555–1,253 lakh, of which inference servers ₹360–840 lakh; onboarding, survey and integration services ₹30–60 lakh. Operations: AMC ₹44–150 lakh, power ₹31–50 lakh, 30 Mbps of WAN ₹2.5–7.2 lakh, 2 engineers ₹16–30 lakh, support contracts ₹2–8 lakh | **₹5.8–13.1 crore** | **₹0.96–2.5 crore** |
| **Centre** | Hardware in 20.3: ₹351–815 lakh; integration, security audit and central services ₹100–200 lakh. Operations: AMC ₹28–98 lakh, power ₹10–20 lakh, 1 Gbps of WAN ₹36–96 lakh, 10 engineers ₹100–200 lakh, support ₹20–50 lakh | **₹4.5–10.2 crore** | **₹1.9–4.6 crore** |
| **Statewide** (33 districts + centre) | 33 × one district + centre | **₹197–443 crore** | **₹34–86 crore** |

Inference servers are about two thirds of a district's hardware at S = 10,
which is §17.5's conclusion in rupees: **the bill is set by S**. At S = 20 a
district needs 6 inference servers, not 12, and the statewide capex falls by
roughly ₹59–139 crore; at the laptop's S = 2.0 it would be about five times
the inference line. The benchmark in §17.4 is therefore the first thing to
run on tendered hardware, before these rows are used for anything.

### 20.9 Cost-benefit

**Costs not incurred (MODELLED on the ASSUMED rates above).** Section 17.5
lists what the design does not spend; priced on the same rates:

| Avoided | Arithmetic | Indicative |
|---|---|---:|
| Central video storage, 30 days | 52 PB × ₹0.1–0.3 lakh per TB, one copy, disks only | ₹52–156 crore, before replication, DR or growth |
| Central video bandwidth | 160 Gbps × ₹300–800 per Mbps-month | ₹58–154 crore **a year** |
| Replacing departmental VMS | Not required (§10) | Not priced; the departments' existing spend continues unchanged |

A year of central video bandwidth alone is about a third of the whole
statewide implementation above, and it recurs every year. A central design
would also still need the accelerators, because the inference is the same
work wherever it runs.

**Operational benefits (ESTIMATE — none of these is measured on an
investigation).**

- **Time to trace a vehicle.** On the live store a plate search takes
  3.4 ms and a trajectory 1.5 ms (**MEASURED**, `live_evaluation.json`). The
  manual alternative is requesting footage from each department holding a
  camera on the likely route and reviewing it. At an **ASSUMED** 1–3
  officer-hours per camera location reviewed and 5–10 locations per trace,
  that is 5–30 officer-hours per trace replaced by minutes of verification.
- **Officer-hours.** At an **ASSUMED** 50–200 traces per district per month,
  that range becomes 250–6,000 officer-hours a month per district. The spread
  is wide because both inputs are assumed; Phase 1 (§16) should measure both
  and replace them.
- **Investigations started from an index.** A watchlist hit becomes an
  incident at ingest, not after someone thinks to look (§11.1); on the
  evaluation store 128 alert rows grouped into 13 incidents (**MEASURED**),
  so the queue an officer works is incidents, not raw reads.
- **Evidence handling.** Sealed, hash-chained stills with a draft BSA s.63
  certificate and a printable trace report with a digest (§4.5, §4.6) replace
  ad-hoc exports whose integrity has to be argued afterwards. The certificate
  remains a draft for a signing authority.

**What limits the benefit.** On the evaluation grid 28 of 30 cameras grade
UNSUITABLE for ANPR and none GOOD (`docs/MEASURED_RESULTS.md`). The
plate-trace benefits above accrue only where cameras can read plates; the
registry's capability grades are how a district finds out, per camera, before
counting on them. Presence and appearance grades are higher (27 and 20 GOOD),
so detection, counting and restricted-zone reports reach more of the estate
than plate traces do.
