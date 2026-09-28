# SAAKSHYA statewide target architecture — only compute binds

**Status of this document.** The architecture is **DESIGNED**. Unit costs are
**MEASURED** on this project's development host (Apple M5, 10 cores, no NVIDIA GPU)
or **VERIFIED** by read-only checks made for this document. Every count derived from
them is **MODELLED**, with the formula shown. Hardware and rates nobody here measured
are **ASSUMED**, with a source class. Nothing here was run at 80,000 cameras; the
80,000 figure is sized, not tested.

Label tags used below: **(M)** measured, a committed report holds it (file and key
named where it is used, and listed in `reports/capacity_model.json:inputs`);
**(V)** verified read-only against the government store `var/live.db` for this
document; **(Mod)** modelled; **(A)** assumed; **(D)** a design choice. Every modelled
number is produced by `tools/sizing/capacity_model.py`, which reads its measured inputs
from `var/reports/` and `reports/measure_compression.json` and writes
`reports/capacity_model.json`; `tests/unit/test_capacity_model.py` pins its
conclusions. Measured row compressibility is in `reports/measure_compression.json`,
made by `tools/sizing/measure_compression.py` (store opened read-only). Code paths
such as `live/hub.py` are under `src/saakshya/`; other paths are from the repository
root. Three cited reports sit in the build machine's `var/reports/` but are not
committed: `var/reports/direct_whep_wall4.json`,
`var/reports/final/model1/gis_80k.json` and `var/reports/final/model4/ai_cadence.json`.
The compressed row size was re-run for this repository on the pinned snapshot window
(154.0 B/row). The first run gave 154.2 B; the store changed between the two runs, and
the difference moves no headroom by more than 0.01×. Two corrections were made when
the model moved into the repository: the state API is now priced on the 8 servers it
is sized on (it had been priced on 6), and the cell LAN row now carries the main
streams of ANPR-grade cameras, which §5 says run continuously (3.0 Gbps and 16.7×,
not 2.5 Gbps and 20×).

**The claim, stated so it can be attacked.** The number of cameras analysed can grow
from zero to 80,000. Only one resource then needs procurement in proportion to that
number, and it is inference compute: GPU, CPU for decode, and the RAM inside those
servers. Metadata bytes, rows and stored terabytes also grow linearly. They are
provisioned per cell, where a cell holds at most 2,500 cameras or 4,000
observations/s. At the pessimistic
rate they keep at least 5× headroom on camera-driven throughput and 2.2× on hot
storage at 100% analysed. The 3-year warm lake has 1.5×, and it is bought per
retention year. Together they are about a fifth of the hardware bill
(§11, §14). Three resources grow with viewers and users, not cameras: viewing
bandwidth, media gateway sessions and API requests. Each has its own admission
control. Section 11 recomputes every row pessimistically, and the Self-check at
the end lists what that changed.

---

## 1. Principles

1. **Video stays where it is captured; compute goes to the video.** Only metadata,
   events, requested clips and viewer-requested streams cross a WAN. Central video for
   80,000 cameras at 2 Mbps (A, `docs/SCALE_MODEL.md`) would be 160 Gbps (Mod). That is
   why statewide central recording (full Model 4) is declined.
2. **Place compute by link capacity, per site.** A site's streams are pulled to a
   district compute cell only if the site uplink can carry them with 1.5× headroom.
   Otherwise an edge box analyses at the site. Any would-be link bottleneck therefore
   becomes a compute cost, and compute is the resource allowed to grow.
3. **The cell is the unit of scale.** A cell holds at most 2,500 cameras **or**
   4,000 observations/s, whichever comes first. It has its own GPU pool, bus, database,
   media gateway and API. Adding cameras adds cells. No component is shared by all
   cameras except the state indexes, which receive a small fraction of the data (§6).
4. **Partition by the key the question asks.** Plates are partitioned by an OCR-folded
   plate key. A watchlist match or a route build then touches one partition,
   whatever the size of the estate.
5. **Degrade, never stop (kept from HLD P7).** A cell keeps detecting, matching,
   alerting and sealing evidence with every upstream link down. It replays
   idempotently by `dedup_key` (built: `store/schema.py:254`).
6. **Measure capability; never assume it (kept from HLD P2).** Scarce T2 capacity
   goes to cameras graded able to read plates (built: `analytics/worker.py:363-371`).
7. **Evolution, not rewrite.** Every tier runs this codebase's services: ingest, hub,
   pipeline, store, edge queue, watchlist, evidence, API. §17 lists what exists and
   what is added.
8. **Open and vendor-neutral.** Every named component has an open licence. Departments
   keep their VMS and NVRs.

## 2. Tiers

Planning geography (D): 33 districts, grouped into 40 cells and 6 regions. The six are
Ahmedabad–Gandhinagar, North, Kutch, Saurashtra, Central and South. The regions are a
planning grouping, not an administrative claim. Site-to-state distances reach
~1,000 km (FAQ Q9).

| Tier | Where | Runs (technology) | Failure domain and what survives it |
|---|---|---|---|
| **Camera** | Existing | IP cameras (main and sub-stream), analog cameras through ONVIF encoders, departmental NVRs/VMS, which keep recording at the department's retention | One camera. Health and capability graded in the registry. |
| **Site edge box** (only where the uplink cannot carry the site's streams) | Camera site, on the camera LAN | This codebase on the `TARGET_GPU` or `DEV_CPU` profile. SQLite store, durable queue (`edge/queue.py`), T0/T1, and T2 if the box has an accelerator. Local watchlist (hashed bundle). Embedded accelerator class (A). | One site. The NVR keeps recording. The queue holds 7 days (§11). |
| **District cell** (40) | District data room | Kubernetes (RKE2 or K3s). Ingest and decode workers (PyAV; NVDEC where present). GPU pool behind NVIDIA Triton Inference Server (BSD-3) with dynamic batching. NATS JetStream (Apache-2.0), 3 nodes. PostgreSQL 18 + PostGIS (Patroni, synchronous standby). MediaMTX gateway (MIT). Model 3 federation adapters. Cell API (FastAPI) serving the district control room. Prometheus. | ≤ 2,500 cameras' analysis. Cameras and NVRs keep recording, and no video is lost. Cell-internal HA covers any single node. |
| **Region** (6) | Regional data centre | SFU for many-viewer fan-out (LiveKit or mediasoup), coturn TURN, OCI registry mirror (Harbor), backup object store (Ceph RGW) for cell WAL and base backups, forensic GPU pool (T3 re-processing of NVR clips) | Remote viewing and backups of its cells. Cells keep running. Viewing fails over to a neighbour region. |
| **State DC** + **DR DC** | State data centre; DR ≥ 250 km away (D) | Apache Kafka (KRaft) with 6 brokers. Plate index on PostgreSQL (4 hosts carrying 64 virtual hash shards). Model 1 registry and GIS (PostgreSQL + PostGIS). Observation lake on an S3-compatible store (Ceph RGW, erasure-coded) with Trino (Apache-2.0). State API and command centre. Keycloak (OIDC), OPA (policy) and SPIFFE/SPIRE (workload identity). Evidence WORM bucket (object lock). Thanos, a log store and Argo CD. | Statewide search and cross-district routes. Cells continue locally. DR takes over (§8). |

**What runs where, by analytic tier.** T0 motion gating runs on a sub-stream at the
edge box or cell CPU (built: `analytics/motion.py`). T1 detection and tracking runs in
the cell GPU pool. T2 plate detection, OCR and attributes run on crops in the same pool,
batched (OCR batched per frame is 6.6 ms/plate on MPS vs 14.2 single (M)). T3
forensic re-processing of recorded clips runs in the regional pool. The state runs no
per-camera inference.

## 3. Integration plane — FAQ Models 1–4 and the hybrid split

**Model 1 (compulsory, FAQ Q12) is the source of truth.** The state registry holds
every camera: identity, department, owner, type, coordinates with basis and precision,
transport, main and sub-stream profiles, NVR/VMS, retention, consent, health, and
measured capability per time band. Cells hold a replica of their own cameras.
Onboarding is by CSV/JSON/API (built: `api/routes_registry.py:193,205`) and by
discovery. Registry and GIS were measured at 80,000 rows: PostGIS viewport p50 1.3 ms
(M `var/reports/gis_postgis.json`).

| Source kind | Path | Where it terminates | Model |
|---|---|---|---|
| IP camera or NVR channel reachable over RTSP / ONVIF Profile S or T | Direct pull, one session per camera, fan-out inside the cell (built: `live/hub.py:1-12`) | Cell ingest, or site edge box | **Model 2** (direct, no middleware; FAQ Q16-17) |
| Analog camera | ONVIF-compliant encoder at the site, then as above | Cell / edge box | Model 2 |
| ONVIF Profile G (recording), Profile M (analytics metadata) | Profile G for pulling recorded clips for evidence and T3; Profile M events ingested as observations where the camera computes them | Cell | Model 2 |
| Department running a VMS (vendor SDK / API) | One federation adapter per VMS instance: inventory, status, events and stream URLs (contract built: `federation/adapters.py:24-50`; vendor clients DESIGNED) | Cell federation service | **Model 3** (FAQ Q18-19) |
| Private public-facing camera (society, mall) | View-only. The owner runs an outbound connector (mTLS tunnel to the cell). The registry holds `consent_ref` and expiry. `analytics_permitted` is false by default. Every view is audited. Revoking consent tears down the session | Cell media gateway only | Model 2, view-only (FAQ Q7) |
| Selected cameras for central/regional analytics (designated vehicle, forensic) | Clip or stream pulled on request to the regional T3 pool | Region | **Model 4, selected only**. Statewide central recording is declined (§1) |

**Hybrid split, stated plainly:** Model 1 everywhere. Model 2 for every directly
reachable camera or NVR. Model 3 for departments whose cameras sit behind a VMS.
Model 4 for selected analytics only. Both Model 2 and Model 3 sources register in
Model 1 before any stream opens.

**Government databases (FAQ Q8).** VAHAN, SARATHI, eGujCop, AFIS and NAFIS are
integrated through adapters at the state. Stubs today refuse honestly and name what is
missing (`watchlist/government.py:192-243`). What each can drive:

- **Vehicle-keyed alerts** (stolen or wanted vehicle, eGujCop/VAHAN) feed the hashed
  watchlist.
- **VAHAN** enriches a confirmed plate: make and colour, used to check the camera's
  read.
- **SARATHI, AFIS, NAFIS** are enrichment only. A camera cannot trigger a fingerprint
  match. This is kept from the code's own docstring.

## 4. Media plane

- **One upstream session per camera, shared by analysis and every viewer** (built:
  `live/hub.py`). Upstream sessions are opened on demand and closed after 90 s idle
  (`HUB_IDLE_S`, `live/hub.py:48`). A viewer never causes a second pull from a camera.
- **Cell gateway** (MediaMTX) serves WHEP to the district control room on the LAN.
  H.264 without B-frames is packet-copied. HEVC and B-frame sources are transcoded
  (hardware encoder). Measured on the M5: 15 transcoded bridges, ~241 MB RSS and ~4.2%
  CPU each (M `var/reports/phase10/performance/phase16_bridge_scale.json`). Transcoding is compute.
- **Ladder** (D, bitrates from `var/reports/phase10/performance/phase16_bridge_profile.json`): PRIMARY 1.5 Mbps 15 fps
  for the focused tile, PREVIEW 0.5 Mbps 8 fps 720p for the wall, and a 1 Hz thumbnail
  (~15 KB, A) beyond the budget.
- **Wall budgets are kept as built.** CONTROL ROOM allows ≤ 30 sessions with a 400 ms
  stagger. OPTIMIZED allows ≤ 12 sessions (`ui/app.js`, `TILE_WHEP_STAGGER_MS`, `TILE_WHEP_BUDGET`).
- **Cross-region viewing.** State and remote viewers attach through their regional SFU.
  The SFU pulls once from the cell and fans out to many viewers. TURN (coturn) is used
  only for clients outside the police network. Viewing demand is set by people watching
  and is admission-controlled per cell (30 Mbps budget, D). It is independent of how
  many cameras are analysed.
- **Evidence clips** come from the NVR (ONVIF Profile G / VMS export) or from the
  cell's rolling pre-event buffer (built: `evidence/rolling.py`). They are sealed
  before acknowledgement.

## 5. Analytics plane

**Tiers and cadence (D).** Default analysis is 1 fps (HLD §17.2). Cameras graded GOOD
or DEGRADED for ANPR run at 5 fps. Voting needs ≥ 2 agreeing frames
(`CONFIRM_VOTES = 2`, `reports/anpr.py:39`), and at 1 fps a passing car yields one or
two frames. ANPR-grade cameras stream the main stream continuously. All others stream
the sub-stream. Cadence adapts by priority mode (built: NORMAL, HIGH_PRIORITY, ALERT,
FORENSIC; `runtime/inference_scheduler.py:14-19`). Under GPU pressure NORMAL work is
shed first (built: `runtime/inference_scheduler.py:90-93`; M
`var/reports/final/model4/ai_cadence.json`: 8 of 20 admitted, 12 shed under overload).

**Batching.** Frames from many cameras go to Triton with dynamic batching. Plate crops
from a frame go as one batch.

**Model changes.** New weights run in shadow on sampled frames and are compared with
production before promotion. This is the same parity method the repo used for CPU vs
MPS (3,622/3,622 boxes, M `var/reports/detector_device.json`). The licence gate is kept
(`models/router.py`).

**Cross-camera vehicle tracking (FAQ Q27-28) — plate-based, today's method.**

1. Every confirmed plate read leaves the cell on the real-time lane as a slim row
   (160 B, D). It goes to Kafka topic `plate-reads`, keyed by the OCR-folded plate
   (O→0, B→8 and the other confusion pairs the watchlist already declares).
2. One partition, and one plate-index shard, hold every read of that plate and its
   look-alikes. A route build therefore reads one shard with no scatter. The PostgreSQL
   trajectory p50 is 6.66 ms at 1.16 M rows (M `var/reports/store_engines.json`).
3. The route engine is the built one: Camera Link Model with trusted edges at ≥ 3
   samples, typed legs OBSERVED / UNOBSERVED / COVERAGE_GAP / CONTRADICTION, and
   timebase gating (`intelligence/graph.py:42-76`, `intelligence/trajectory.py:52-98`).
   Cross-cell legs use a state-held graph of border camera pairs.
4. **Designated vehicle (FAQ Q27).** An officer creates a watchlist entry of category
   DESIGNATED, with case and purpose. Its hashed key reaches every cell and edge box as
   a delta. Each read raises an incident at the cell (alert latency SLO in §9) and
   updates the route at the state. The output is the built vehicle trace report: a
   timestamped, location-wise history with a digest (`reports/vehicle_trace.py`).

**Honest limit, measured.** On the government grid no plate was read on two different
cameras; every government vehicle history is single-camera
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). Multi-camera
routes are demonstrated on own-feed and synthetic data only.

**Appearance re-identification — DESIGNED, not built.** The DINOv2 baseline was measured
and rejected: a decoy scored 0.941 against the target, and the target scored 0.412
against itself (`docs/ARCHITECTURE.md`). Government observations carry no embeddings.
The design:

- A purpose-trained vehicle re-ID model, adopted only after the same shadow and parity
  gate, and only on cameras graded GOOD for appearance.
- Embeddings stored in pgvector in the cell.
- Candidate search bounded first by the Camera Link Model: only neighbour cameras,
  within the travel-time window. Fan-out is therefore set by graph degree, not by
  camera count.
- Results returned as candidates requiring verification, never as identifications.

## 6. Event and data plane — partition keys

| Stream / table | Where | Key / partitioning (D) | Why this key |
|---|---|---|---|
| NATS subject `obs.<cell>.<camera>` | Cell JetStream R3 | per camera | per-camera order; replay by `dedup_key` |
| NATS `plate.<cell>`, `alert.<cell>`, `health.<cell>.<camera>`, `audit.<cell>` | Cell → state (leaf node, store-and-forward) | priority lanes: alerts > plates > health > audit > bulk | catch-up drains what matters first |
| Kafka `plate-reads` | State | key = folded plate, 128 partitions | route and watchlist touch one partition |
| Kafka `alerts` | State | key = incident key (vehicle + watchlist entry), 32 | incident grouping stays in one consumer (built logic: `watchlist/incidents.py:334`) |
| Kafka `camera-health` | State | key = camera_id, 64; per-camera series stay in the cell | health rollups only at state |
| Kafka `audit-heads` | State | key = cell, 32 | per-cell hash-chain heads anchored centrally |
| Kafka `registry`, `watchlist` | State → cells | key = camera_id / entry id, log-compacted | cells rebuild state from the compacted log |
| Bulk observations | Cell → object store | **not on Kafka.** Compressed micro-batches of ≥ 1 min, path `obs/date=/district=/cell=/hour=/` | removes the only large flow from the state bus (§11) |
| Cell `observations` table | Cell PostgreSQL | range-partitioned by day on `t_norm_us`. Existing indexes kept: plate+time, camera+time, district+time (10/10 hot queries indexed, M `var/reports/query_plans.json`). BRIN on time | 30-day hot window; drop or detach is O(1) |
| Rollups `camera_minute_counts`, `class_hour_counts` | Cell, streamed | camera, minute | `/overview` (965 ms at 1.16 M rows, M) and `/cameras/{id}` (183 ms, M) read rollups, not raw rows |
| State plate index | 4 PostgreSQL hosts | 64 virtual hash shards on the folded plate; monthly range sub-partitions | re-sharding moves virtual shards; the key matches the Kafka key |
| Lake | S3-compatible, Trino | date / district / cell | warm search and statewide analytics |
| Evidence | Cell object store, replicated to state WORM | case_id | sealed before acknowledgement (HLD §15) |

## 7. Security

- **Zero trust between workloads.** Each workload holds a SPIFFE identity issued by
  SPIRE, and every service-to-service call is mTLS. A cell dials the state and the
  state never dials a cell (HLD §18.1 kept). Edge boxes get a per-box identity and can
  only publish (the `edge:sync` pattern, `docs/SECURITY.md` §5).
- **Segmentation.** Camera VLANs terminate at the edge box or the cell and never reach
  the WAN (HLD §18.2). Egress is denied by default on every node, which the ONNX
  telemetry finding in HLD §18 shows is needed.
- **RBAC + ABAC.** The built four gates stay in-process: role, jurisdiction by
  district, purpose (`X-Case-Id`, `X-Purpose`), and object-level checks
  (`security/access.py:274`). The state adds OPA policies over department, district,
  role, case and data class. Identity is OIDC (Keycloak) with a hardware second factor
  for SUPERVISOR and ADMIN. ADMIN still cannot search (built).
- **Purpose-bound search and watchlist reads** (built). Watchlist bundles carry keyed
  hashes, not plates. An edge box that is stolen reveals no list in clear.
- **Tamper-evident audit.** Each cell keeps its hash chain (built:
  `store/repository.py:1363-1408`). Every 5 minutes it publishes the chain head to the
  state. The state writes a daily Merkle root of all heads to the WORM bucket and to an
  external notary. This closes the gap HLD §18.6 names: a chain stored only in the
  database it protects.
- **Evidence chain of custody.** Hash-chained manifests (built:
  `evidence/manifest.py:95,484`) are stored in an object-lock bucket. A BSA s.63
  certificate is prepared as a draft for a signing authority. The platform does not
  claim admissibility.
- **DPDP Act 2023.** The purpose is recorded per query (built). Retention is enforced
  by dropping partitions and by bucket lifecycle (D; not built today:
  `docs/ARCHITECTURE.md`). The design keeps data minimisation: hashed watchlists, no
  faces, slim plate rows. Security safeguards and breach-response runbooks are
  provided. Exemptions for law-enforcement processing do not remove these controls in
  this design.
- **Private cameras.** Consent record, view-only, audited, revocable (§3).

## 8. HA / DR with RPO / RTO

Targets are **ASSUMED** for procurement to confirm. Those marked (HLD) reuse the
targets HLD §20.7 set before this design; HLD §15 now carries this whole table.

| Scope | Mechanism (D) | RPO | RTO |
|---|---|---|---|
| Evidence | Sealed before ack, then object-lock replication to state and DR | 0 at the cell; ≤ 15 min to DR | as its store |
| Cell metadata | Patroni synchronous standby; WAL archive to the regional object store (pgBackRest) | 0 in-cell; ≤ 5 min off-cell (HLD) | ≤ 60 s automatic failover; ≤ 8 h rebuild (HLD) |
| Cell analytics | GPU pool N+2; Kubernetes reschedules workers | nothing to lose: video is on the NVR | ≤ 5 min for worker loss; ≤ 4 h for pool loss (HLD) |
| Site edge box | Durable queue on local disk, 7 days | 0 (queue) | box swap ≤ 1 business day (A); NVR keeps recording |
| State bus | Kafka RF 3, `min.insync.replicas` 2, `acks=all`; MirrorMaker 2 to DR | 0 in-site; ≤ 1 min to DR | ≤ 1 h at DR (D) |
| Plate index, registry | Synchronous standby per host; asynchronous to DR | 0 in-site; ≤ 1 min to DR | ≤ 1 h at DR (D) |
| Lake | Erasure-coded; multisite asynchronous | ≤ micro-batch interval (1 min) + replication lag | reads resume at DR ≤ 4 h |
| State API | Stateless, N+1 | — | minutes |

**Graceful degradation (D; the edge half is built and tested in
`tests/e2e/test_offline_mode.py`).**

| What fails | What keeps working | What degrades |
|---|---|---|
| Cell WAN | Detection, local watchlist match, local alerts, evidence sealing, district control room | Statewide search is stale for that cell. It catches up by priority lane (§11 catch-up rows). |
| Region | Cells; state | Remote viewing moves to a neighbour region's SFU. Backups queue at the cell. |
| State bus | Cells | Plate and alert lanes queue in cell JetStream. A 7-day queue of every observation is 194 GB compressed per cell at the pessimistic rate (Mod). |
| State database | Cells; Kafka retains 7 days | Statewide routes pause and replay from Kafka offsets. |
| Whole state DC | Everything local | DR takes over. Cells keep their own last-valid watchlist, fail-closed (built). |
| GPU pool saturation | ALERT and HIGH_PRIORITY cadence, ANPR-grade cameras first | NORMAL frames shed (M `var/reports/final/model4/ai_cadence.json`: 8 admitted and 12 shed of 20 under overload) |

## 9. Observability

- **Stack (D).** OpenTelemetry collectors feed a Prometheus per cell. Thanos gives the
  global view with downsampling. There is a log store (OpenSearch or Loki) and
  dashboards. The built endpoints `/healthz`, `/readyz`, `/system/health` and
  `/metrics`, plus `X-Request-Id` and JSON logs, are what gets scraped.
- **Metrics cardinality.** Per-camera series stay in the cell (~20 series × 2,500
  cameras). The state holds cell aggregates, about 0.8 M series (Mod; §11).
- **SLOs (D):**
  - read → incident at the cell, p95 ≤ 5 s;
  - designated-vehicle read → state route updated, p95 ≤ 30 s with the WAN up;
  - plate search p95 ≤ 500 ms;
  - wall first frame p50 ≤ 3 s, against a measured p50 of 1.95 s for direct WHEP on 4
    tiles (M `var/reports/direct_whep_wall4.json`);
  - queue oldest-event age ≤ 60 s with the WAN up.
- **Capacity alarms.** Every §11 row is a dashboard panel showing demand ÷ capacity.
  At 50% the owner plans. At 70% the scaling axis is actioned: add a cell, a shard, a
  broker or TB. This includes observations/s per cell against the 4,000/s cell cap.
- **Chaos and drills (D).**
  - Monthly: Patroni switchover, Kafka broker kill, cell WAN cut.
  - Quarterly: region isolation, and DR failover with a restore test. A backup is proven
    only by a restore.
  - Tooling: Chaos Mesh or LitmusChaos.
- **Rollout safety.** Argo CD with rings: lab → 1 canary cell → 1 region → state. Edge
  boxes follow the same rings via pull-based GitOps from the regional OCI mirror.
  Rollback is automatic when SLOs breach.

## 10. Capacity model at 80,000 cameras

Demand parameters are listed first, then each tier. The formulas are those in
`tools/sizing/capacity_model.py`.

**Demand parameters**

| Parameter | Value | Label and source |
|---|---:|---|
| Bytes per observation, serialised | 1,331.7 B | (M) `var/reports/bandwidth.json:observation_bytes_each` |
| Same, zlib-6, batches of 100 | 154.0 B (ratio 8.0) | (V) `reports/measure_compression.json:batches.100` |
| Observations per **active** camera-hour, government store | 902.6 | (V) 1,155,325 / 1,280 camera-hours with ≥ 1 observation |
| Observations per camera-calendar-hour | 71.7 | (Mod) 1,155,325 / (30 × 537.26 h); understates because 4 slots |
| Pessimistic statewide average | **3,000 / camera-hour** | (A) above the busiest camera's own average (2,529/h, V) |
| Busiest camera, peak hour / minute | 11,232 / 491 | (V) cam04 |
| Analysis rate | 1 fps; ANPR-grade 5 fps; ANPR-grade share 20% | (D) / (D) / (A) |
| Full-pipeline rate per CPU host | 5.6 fps | (M, prose only) `reports/SCALE_80K_LOAD_TEST.md:31` |
| GPU speedup **S** | 10 → 56 fps per GPU | (A) HLD §20.2. Only measured S is 2.04 on an integrated GPU (M `var/reports/pipeline_device.json`). |
| Decode | 0.25 core per stream | (A) HLD §20.2 derivation; no per-stream CPU measured |
| RAM | 98.1 MB per camera | (M) `var/reports/camera_load.json:peak_rss_mb` / 50 |

**Per tier (all Mod unless marked)**

| Tier | Demand formula | Unit cost (label, source) | Nodes at 80,000 | Headroom | Scaling axis |
|---|---|---|---|---|---|
| Inference GPUs | 80,000 × (0.8 × 1 + 0.2 × 5) = **144,000 fps** | 56 fps/GPU (A, S = 10) | **2,572 + 80 spares = 2,652 GPUs = 663 four-GPU servers** (1 Hz for all: 1,429, as in HLD) | N+2 per cell | GPUs per cell ∝ analysed cameras × fps |
| Decode | 80,000 × 0.25 core | (A) | 20,000 cores = 313 × 64-core servers | sized to demand | per cell; NVDEC may absorb part (unmeasured) |
| RAM (inside compute) | 80,000 × 98.1 MB | (M) | 7.85 TB across compute servers | — | with compute |
| Per cell (2,500 cameras) | as above | — | 83 GPUs (21 servers); 12 servers at 1 Hz, as HLD §20.3 | — | add cells |
| Site edge boxes | sites failing the 1.5× link rule | (A) accelerator class; 25 per cell (A, as HLD §20.1) | 1,000 | — | per site survey |
| Cell database | 2,500 × 3,000/h = 2,083 rows/s | 14,187 rows/s (M `var/reports/store_engines.json` migration) | 2 (Patroni) | 6.8× | new cell at 4,000 obs/s |
| Cell hot store, 30 d | 2,083 × 2.592 M s × 2,663 B | 2× wire (A) | 32 TB NVMe per copy | 2.2× (pess), 7.4× (mean rate) | hot window days (D) |
| Cell bus | 2,083 + 208 + 250 msg/s | 50,000 msg/s (A) | 3 nodes | 19.7× | per cell |
| State Kafka | 5.73 MB/s real-time lanes | 50 MB/s per broker (A) ÷ RF 3 | 6 brokers | 17.4× | brokers, partitions |
| State plate index | 6,667 rows/s | 14,187 rows/s per host (M) | 4 hosts × (primary + sync standby) | 8.5× | move virtual shards |
| Lake, 3 years | 66,667 obs/s × 154.0 B | (V) compression | 1.5 PB usable | 1.5× (pess), 5.1× (mean) | TB per retention year |
| State API | 5,000 users × 1 req/s (A) | 10.38 ms/req (M PG plate search p50) | 8 servers × 16 workers | 2.5× | stateless servers; users-driven |
| Registry and GIS | fixed 80,000 rows | 1.3 ms viewport (M) | 1 + standby | 77× on a 100 ms SLO | none needed |

## 11. Binding-constraint analysis

Every non-compute resource is listed at 80,000 cameras, all analysed. Rates are the
pessimistic 3,000 observations per camera-hour. "Headroom" is capacity ÷ demand. Each
row names the design choice that keeps it from binding.

| Resource | Demand (Mod) | Capacity (label) | Headroom | Design choice that removes the bottleneck |
|---|---:|---:|---:|---|
| **WAN backhaul, cell → state** (2,500-camera cell) | 3.83 Mbps (bulk 2.57 compressed + plates, health 1.27) | 20 Mbps = 50 Mbps link − 30 Mbps viewing budget (A/D) | **5.2×** | Batch-compressed metadata lane (8.0× measured, V); video never on WAN; viewing budget admission-controlled |
| Same, if metadata were sent uncompressed over the 20 Mbps link HLD §20.4 used to provision | 23.46 Mbps | 20 Mbps (A, earlier HLD §20.4) | **0.85× — would bind** | Therefore compression is mandatory in the design, not an optimisation |
| **Site uplinks** (site → cell) | n_site × 1.0 Mbps sub-stream (A) | site uplink (surveyed) | **≥ 1.5× by rule** | Pull only if the link carries it at 1.5×; else an edge box analyses on site. The bottleneck becomes compute. |
| Cell ingest LAN | 3.0 Gbps (2,000 sub-streams × 1 Mbps + 500 ANPR-grade main streams × 2 Mbps) | 50 Gbps (2 × 25 GbE, D) | 16.7× | Sub-stream for T0/T1; main stream only on ANPR-grade cameras |
| **Event bus, cell** | 2,542 msg/s | 50,000 msg/s (A, vendor-benchmark class) | 19.7× | One JetStream per cell; nothing statewide on it |
| **Event bus, state** | 5.73 MB/s | 100 MB/s = 6 × 50 / RF 3 (A) | 17.4× | Bulk observations bypass Kafka as micro-batches to the lake |
| Same, if all observations went through Kafka raw | 88.8 MB/s | 100 MB/s | 1.13× | Rejected alternative |
| **Bus partitions** (plate topic) | 52 msg/s per partition | 5,000 msg/s per partition (A) | 96× | 128 partitions keyed by folded plate |
| **DB write rate, cell** | 2,083 rows/s | 14,187 rows/s (M, single stream, laptop) | 6.8× | Batched COPY each second; cell split at 4,000 obs/s |
| **DB write rate, state plate index** | 6,667 rows/s | 56,748 rows/s (4 × M) | 8.5× | Hash shards on the same key as Kafka |
| **DB storage, cell hot 30 d** | 14.4 TB (2× wire row, A); 4.2 TB on the measured SQLite on-disk size (V) | 32 TB NVMe per copy (D) | 2.2× | Day partitions; hot window is a setting; older days detach to the lake and stay queryable |
| **Object storage, lake 3 y** | 971 TB (pess), 292 TB (mean rate) | 1.5 PB usable (D) | 1.5× / 5.1× | Bought per retention year; grows with years retained, not with frames |
| **Object storage request rate** | 334 PUT/s (40 cells × 1 batch/min + 333 evidence stills/s in an alert storm) | 4,000 PUT/s = 4 gateways × 1,000 (A) | 12× | ≥ 1-minute micro-batches keep object count low |
| **Spatial queries** | viewport on 80,000 cameras | 1.3 ms p50 (M) vs 100 ms SLO | 77× | Camera count is fixed by the estate; server-side clustering, max 1,500 features (M `var/reports/final/model1/gis_80k.json`) |
| **Media gateway sessions** per cell | 200 cameras viewed at once (A) | 450 = 3 nodes × 150 copy sessions (A; not measured) | 2.25× | One upstream session per camera shared by AI and all viewers (built); set by viewers, not analysed cameras |
| **Remote viewing** (state + investigators) | 650 Mbps (1,000 preview × 0.5 + 100 full × 1.5) | 2 Gbps state ingress (A) | 3.1× | Regional SFU pulls once per camera; per-role tile budgets |
| **TURN** | 100 Mbps (200 relayed tiles) | 6 Gbps (6 regions × 2 coturn × 0.5 Gbps, A) | 60× | Police-network clients connect directly |
| **API** | 5,000 req/s (all users at the state) | 12,331 req/s (128 workers × 1000/10.38 ms) | 2.5× | Stateless; district users served by their cell API; heavy aggregates from rollups (§6) |
| **Search index — plate** | one shard per query | — | no fan-out | Key choice removes scatter |
| **Search index — attributes** | 40 cell queries per statewide search | 8 concurrent searches per cell (built `api/deps.py:100`) = 320 in flight | 8× | Bounded by time window and 2,000-row cap (built) |
| **Control plane** | ~50 nodes per cell cluster | 5,000 nodes per cluster (upstream Kubernetes scalability threshold, documentation class, A) | 100× | One cluster per cell; no statewide cluster; edge boxes via pull-based GitOps |
| Image and model rollout | 25 boxes × 2 GB per cell = 5.6 h at 20 Mbps spare | 72 h per ring (D) | 13× | Regional OCI mirror; staged rings |
| **Watchlist matching fan-out** | O(1) hash lookup per read; bootstrap one cell + 25 boxes = 16 MB × 26 = 166 s at 20 Mbps | 1 h target (D) | 21.6× | 1,000,000 entries (A) as two 8-byte keyed hashes; deltas ~320 KB/day (A) |
| Health metrics at the state | 0.8 M series | 10 M active series (A, Thanos class) | 12.5× | Per-camera series stay in the cell |

**Hot spots**

| Hot spot | Demand (Mod) | Capacity | Headroom | Design choice |
|---|---:|---:|---:|---|
| **District with 5,000 cameras** (2 cells behind one 100 Mbps link, 60 Mbps viewing budget) | 7.67 Mbps | 40 Mbps | 5.2× | Split at 2,500 cameras / 4,000 obs/s per cell; link scaled per cell |
| **Busy highway camera** (cam04 peak minute, 491 obs/min) | 87 kbps raw off its site | 1 Mbps (A) | 11.5× | Its compute scales (5 fps ANPR). Its metadata does not matter. |
| **Highway-heavy cell** (every camera at cam04's peak hour, 11,232/h) | 7,800 obs/s | 14,187 rows/s (M) | 1.8× | Cell cap of 4,000 obs/s (1,282 such cameras per cell), from the Self-check |
| **Alert storm** (5% of plate reads match, e.g. a bad bulk list) | 333 alert rows/s | 14,187 rows/s (M) | 43× | Incident grouping (built) and per-district notification token buckets. The human queue is rate-limited on purpose. |
| **Catch-up after a 24 h WAN outage**, 5,000-camera district | backlog 55.4 GB compressed; drains in 1.33 h at 100 Mbps with viewing paused, 3.8 h with it on | outage 24 h | 18× | Priority lanes: alerts, plates, health, then bulk. Idempotent by `dedup_key` (built, tested). |
| **Catch-up after a 24 h state outage**, plate index | 576 M rows; drains in 3.2 h | 24 h | 7.5× | Kafka retains 7 days; shards absorb the backlog |
| 7-day WAN outage, one cell | 194 GB compressed queue | cell NVMe | — | Disk, not design |

**How demand grows as analysed cameras grow** (pessimistic rates, average cell of
80,000 / 40 cameras, Mod):

| Analysed cameras | GPUs (incl. spares) | Cell WAN, Mbps | State bus, MB/s | Cell DB rows/s | Lake TB/yr |
|---:|---:|---:|---:|---:|---:|
| 8,000 | 338 | 0.31 | 0.57 | 167 | 32 |
| 20,000 | 723 | 0.77 | 1.43 | 417 | 81 |
| 40,000 | 1,366 | 1.53 | 2.87 | 833 | 162 |
| 80,000 | 2,652 | 3.07 | 5.73 | 1,667 | 324 |

**Conclusion — what binds first.**

1. **Inference compute binds first, by construction.** GPUs are bought to demand with
   N+2 spares per cell, so at planning load their headroom is only the spares (~1.03×).
   Every other camera-driven resource keeps ≥ 5× headroom on throughput and ≥ 2.2× on
   hot storage at 100% analysed.
2. **The first non-compute resource to bind, if analysed cameras kept growing, is
   storage.** The 3-year lake (1.5×) binds first, then cell hot NVMe (2.2×). Both are
   bought per TB and are policy-elastic (retention days).
3. **Among throughput resources the lowest headroom is not camera-driven.** API (2.5×)
   and media gateway sessions (2.25×) are driven by people and have their own
   admission control.
4. **What cannot be claimed.** The capacities of Kafka, JetStream, gateway sessions,
   TURN and object gateways are ASSUMED, not measured here. Phase 1 gates (§15) measure
   them before procurement.

## 12. Bandwidth and low-bandwidth strategies

1. **No video on the WAN.** Central video would be 160 Gbps (Mod). The statewide
   metadata inflow at the pessimistic rate is 710 Mbps raw and **82 Mbps compressed**
   (Mod).
2. **Sub-streams for T0/T1.** Measured government streams ran at 0.26–0.66 Mbps each
   (Mod from `var/reports/bandwidth.json:cameras[]`). The main stream is used only on ANPR-grade
   cameras.
3. **Compression is mandatory.** Measured 8.0× with zlib on batches of 100 real rows,
   and 11× with lzma on 1,000 (V). The planning figure is 154.0 B/row.
4. **Priority lanes and store-and-forward.** Alerts go first, then plates, health and
   audit heads, then bulk. The queue is acknowledged, never deleted, and replay is
   idempotent (built).
5. **Viewing ladder and budgets.** 1.5 Mbps / 0.5 Mbps / 1 Hz thumbnail. Sessions are
   on demand with a 90 s idle close (built). Each role has a tile budget.
6. **Hashed, delta watchlists.** Kilobytes a day to each node.
7. **Remote and border sites** (Kutch, Banaskantha, coastal Dwarka and Valsad, FAQ Q4)
   get an edge box. A 4G/5G or satellite secondary carries the metadata lane only: a
   50-camera site at the pessimistic rate needs 50 × 3,000/3,600 × 154.0 B × 8 ≈
   51 kbps (Mod).
8. **QoS.** DSCP marking puts alerts above bulk on GSWAN (A: GSWAN supports marking;
   to confirm with the network owner).

## 13. Storage by retention — hot, warm, cold

| Class | Holds | Where | Retention | Size (Mod) |
|---|---|---|---|---|
| **Video, hot** | Continuous recording | **Departmental NVR / VMS / cloud, unchanged** (FAQ Q5) | 7 / 15 / 30+ days per department | Not in this platform. It stays where the department keeps it. |
| Pre-event buffer | Last N seconds per analysed camera | Cell RAM/NVMe (built: `evidence/rolling.py`) | seconds–minutes | small |
| **Evidence clips and stills** | Sealed, hash-chained | Cell object store, then state WORM (object lock) and DR | life of case + appeal (policy) | ~18 TB/yr at 10,000 HIGH alerts/day × 5 MB clip (A); 100 TB WORM provisioned |
| **Metadata, hot** | Observations, alerts, audit | Cell PostgreSQL NVMe | 30 days (setting) | 14.4 TB pess / 4.3 TB mean per cell |
| **Metadata, warm** | Compressed observations | State lake (S3-compatible + Trino); plate index on PostgreSQL | 1–3 years | lake 324 TB/yr pess, 97.4 mean; plate index 67 TB/yr pess |
| **Metadata, cold** | Old partitions, base backups, audit heads | Erasure-coded cold tier or tape, off-site | 7+ years or per policy | per year retained |
| Audit | Per-cell chains + anchored state roots | PostgreSQL + WORM | indefinite (HLD) | small |
| Optional: retention extension for a department without storage | Recorded video at the cell | Cell HDD tier, priced per camera-day | per department | **Outside the claim.** Video storage grows with cameras recorded; offered, not assumed. |

## 14. Costs — reusing and reconciling HLD §20

"HLD" in this section means the HLD's sizing before this design was integrated
(33 district nodes at 1 Hz). HLD §20.2–§20.8 now carry the figures below, and HLD
§20.8 keeps the earlier total only as a superseded reference.

This section uses HLD §20.8's **ASSUMED** unit rates unchanged: ₹30–70 lakh per 4-GPU
server, ₹8–15 lakh per CPU server, ₹15–30 lakh per district DB server, ₹25–50 lakh per
centre DB server, ₹0.5–1.5 lakh/TB NVMe, ₹0.1–0.3 lakh/TB HDD/object, ₹1.5–4 lakh per
edge box, and the WAN rates. Hardware only, before services and taxes (Mod,
`reports/capacity_model.json:cost_*`).

| Case | Compute (GPU + decode + edge boxes) | Non-compute (DB, bus, storage, network, media, racks) | Total hardware | Compute share |
|---|---:|---:|---:|---:|
| **Planning: ANPR-grade 20% at 5 fps** | ₹239–551 crore | ₹56–130 crore | **₹295–681 crore** | 81% |
| Same cells, everything at 1 Hz (HLD's assumption) | ₹153–352 crore | ₹56–130 crore | ₹210–482 crore | 73% |
| Earlier HLD §20.8 statewide (33 districts + centre, incl. services; superseded) | — | — | ₹197–443 crore | — |

**Reconciliation with HLD.**

1. **Same inference arithmetic.** At 1 Hz a 2,500-camera cell needs 47 GPUs = 12
   servers, exactly HLD §20.3.
2. **The planning case adds 1,143 GPUs.** 16,000 ANPR-grade cameras run at 5 fps,
   because voting needs two agreeing frames. This is the largest change: +₹86–199
   crore. It is compute, which is the one place the claim allows growth.
3. **Non-compute rises by ~₹27–68 crore.** HLD's equivalent lines come to about
   ₹29–62 crore (district DB, application, storage, network and rack lines × 33, plus
   the centre's hardware, at HLD's rates, Mod); this design's come to ₹56–130 crore.
   The causes:
   - 40 cells instead of 33 districts (7 more DB/network/rack sets);
   - hot NVMe per copy of 32 TB instead of HLD's 8 TB split across two servers. HLD
     sized hot metadata on the 400 B model with 10× T0 gating (~1.2 TB per district);
     at the measured 902.6 observations per active camera-hour and 1,331.7 B that is
     under-provisioned 3–12× (Mod);
   - a 3 PB raw-equivalent lake with a DR copy, instead of 450 TB warm + 500 TB cold;
   - six regional hubs;
   - 1,000 edge boxes instead of 825.
4. **Services.** Add HLD's integration services (₹30–60 lakh per cell and ₹100–200 lakh
   at the centre): ₹13–26 crore. With them the planning case is ₹308–707 crore to
   implement and ₹51–134 crore a year to operate (`reports/capacity_model.json:cost_table`,
   HLD §20.8).
5. **Operations per year.**
   - WAN: 40 × 70 Mbps plus a 2 Gbps state link, ₹3.1–8.6 crore/yr (HLD ≈ ₹1.2–3.3
     crore for 30 Mbps per district and 1 Gbps at the centre).
   - AMC at HLD's 8–12% of hardware.
   - Power and people at HLD's rates.
6. **The bill is still set by S.** At S = 20 (A) the GPU line halves. At the measured
   laptop S = 2.04 it is about five times larger. The Phase 1 benchmark replaces S
   before any figure is signed (HLD §17.4).

**Cost avoided (HLD §20.9, unchanged).** Central video storage for 30 days (~52 PB) and
160 Gbps of central bandwidth (₹58–154 crore a year on HLD's rates).

## 15. Phased rollout with gates

| Phase | Scope | Exit gate (all must pass; each is a measurement written to `var/reports/`) |
|---|---|---|
| 0 — PoC (done) | 30 government + 2 own-feed + 18 synthetic-control cameras, one host | As submitted: designated-vehicle search, alert, sealed evidence, audit chain verified |
| 1 — First cell | One district, ≤ 2,500 cameras, at least one Model 2 department and one Model 3 VMS department | (a) **S measured on the tendered GPU** with `tools/bench/detector_device.py`, GPU count re-solved. (b) Observations per camera-hour measured on the real estate. (c) Compression ≥ 4× on production rows. (d) PostgreSQL batched COPY ≥ 4,000 rows/s sustained with synchronous standby. (e) 24 h WAN-cut drill: zero loss, zero duplicates, drain ≤ 4 h. (f) Patroni failover ≤ 60 s. (g) Read → incident p95 ≤ 5 s. (h) Gateway sessions per node and JetStream msg/s measured. (i) Every §11 panel ≥ 2× headroom. |
| 2 — First region | 3–6 cells + regional hub + state core (Kafka, plate index, lake) | Cross-cell designated-vehicle route; 24 h state-outage drill with catch-up ≤ 4 h; region-isolation drill; SFU/TURN at 500 tiles; Kafka broker kill with no loss |
| 3 — Statewide, in waves by department | Home/Police first, then RTO and GSRTC, Municipal corporations, Health and Panchayat, Food & Civil Supplies, then private view-only | Per wave: registry fields supplied by the department (not inferred) for ≥ 95% of cameras; capability graded; capacity panels ≥ 2×; quarterly DR restore drill passed |

## 16. Department-wise information requirements

**Common to every department.** Supplied per camera, in the registry CSV (built import):

- camera id, site, coordinates or a surveyed location, mount height and direction;
- make and model, analog or IP;
- main and sub-stream codec, resolution, fps and bitrate;
- whether the camera accepts a second session;
- NVR/VMS vendor and version, and the RTSP/ONVIF export per channel;
- recording location and retention;
- network path and uplink Mbps per site;
- a contact person and a maintenance (AMC) window.

| Department (FAQ Q6, Q39) | Specific requirements |
|---|---|
| Home / Police (traffic, city surveillance, law & order) | ANPR camera list with lane geometry; eGujCop/CCTNS interface and authority for vehicle-keyed alerts; control-room locations and wall sizes (sets §11 viewing budgets); zone rules with authority |
| RTO / Transport | Checkpoint and testing-track cameras; VAHAN and SARATHI API access, data-sharing approval and purpose-limitation agreement (the requirements the stubs already name: `watchlist/service.py:376-383`) |
| GSRTC | Depot and bus-stand cameras; VMS vendor and API if centralised; on-bus cameras (if any) and their offload method |
| Municipal corporations | City VMS (usually Model 3), fibre ring capacity to the cell, junction ANPR cameras |
| Health | Hospital campus cameras; privacy-sensitive zones to exclude from analytics |
| Panchayat | Village and road cameras; link type (often thin) → edge-box candidates; power availability |
| Food & Civil Supplies | Godown and PDS-shop cameras (FAQ Q6); site uplinks (often thin) |
| Private public-facing (FAQ Q7) | Owner consent document and expiry; view-only scope; contact for revocation; outbound connectivity for the connector |
| All with a VMS (Model 3) | Vendor, version, SDK/API documentation, event types, service account, the number of concurrent exports the VMS allows |
| All | NVR egress limit (Mbps) and camera session limit. Pull placement depends on them (§11 site uplinks). |

## 17. Built today vs designed

| Capability | Status | Evidence |
|---|---|---|
| Registry, CSV/JSON onboarding, gap analysis, capability grades | BUILT+TESTED | `api/routes_registry.py:193-236`, `capability/grader.py:210`; `tests/unit/test_registry_onboarding.py`, `tests/unit/test_capability.py` |
| PostGIS store, same schema as SQLite | BUILT, MEASURED | `var/reports/store_engines.json`, `var/reports/gis_postgis.json` |
| Direct RTSP ingest, one session per camera, on-demand hub | BUILT+TESTED | `live/hub.py`, `ingest/stream.py`; `tests/unit/test_media_hub.py` |
| Detector, tracker, tiled plate detection, Indian OCR, per-track voting | BUILT, MEASURED | `analytics/*`; `var/reports/detector_device.json`, `var/reports/pipeline_device.json`, `var/reports/ocr_indian_eval.json` |
| 4 deep-inference slots by measured grade; cadence by priority mode | BUILT+TESTED | `analytics/worker.py:363-371`, `runtime/inference_scheduler.py` |
| Edge store-and-forward, idempotent replay, fail-closed watchlist bundles | BUILT+TESTED | `edge/queue.py`, `edge/node.py`; `tests/e2e/test_offline_mode.py` |
| Watchlist near-match, incidents, alerts workflow | BUILT+TESTED | `watchlist/service.py:230`, `watchlist/incidents.py:334` |
| Camera Link Model, typed-leg trajectories, trace report | BUILT+TESTED | `intelligence/graph.py`, `intelligence/trajectory.py`, `reports/vehicle_trace.py` |
| Four authorisation gates, purpose binding, hash-chained audit, evidence chain | BUILT+TESTED | `security/access.py`, `store/repository.py:1363-1408`, `evidence/manifest.py` |
| Model 3 VMS adapter contract | DEMO | `federation/adapters.py` (synthetic systems only) |
| ONVIF discovery, vendor SDK clients | DEMO (seams) | `ingest/adapters.py:72-110` |
| VAHAN / SARATHI / eGujCop / AFIS / NAFIS | DEMO (refusing stubs) | `watchlist/government.py`, `watchlist/service.py` |
| NATS JetStream, Kafka, lake, Trino | DESIGNED | this document §6 |
| Cells as Kubernetes clusters, Triton batching, GitOps rings | DESIGNED | §2, §9 |
| Rollups for `/overview` and camera pages | DESIGNED | §6 (needed: 965 ms and 183 ms at 1.16 M rows, M) |
| Day partitioning, retention enforcement | DESIGNED | `docs/HLD.md` §20.5 says no partitioning code ships |
| Hashed watchlist keys, delta bundles | DESIGNED | §11 |
| Audit-head anchoring outside the database | DESIGNED | §7 (HLD §18.6 names the gap) |
| mTLS / SPIFFE, OPA, Keycloak, encryption at rest | DESIGNED | §7; HLD §18 marks them SPECIFIED |
| Regional SFU / TURN | DESIGNED | §4 |
| Appearance re-ID | DESIGNED (baseline rejected) | §5 |
| Face recognition | Not in scope; gated by decision | HLD §11.2 |

## 18. Diagram spec

### 18a. Statewide architecture (rendered by `tools/demo/render_diagrams.py`)

Nodes (`id | tier | label | body`):

| id | tier | label | body |
|---|---|---|---|
| cam_ip | camera | IP cameras | 26 departments; RTSP/ONVIF main + sub-stream; keep recording to their NVR |
| cam_an | camera | Analog + encoders | ONVIF encoder at the site turns analog into RTSP |
| nvr | camera | Department NVR / VMS | 7/15/30-day video stays here; Profile G / VMS export for clips |
| pvt | camera | Private public-facing | view-only with consent; outbound connector |
| edge | site | Site edge box | thin-backhaul sites; T0/T1; SQLite + durable queue; metadata only leaves |
| c_ing | cell | Ingest + decode | one session per camera; sub-stream, main on ANPR-grade |
| c_gpu | cell | GPU pool (Triton) | T1 detect+track, T2 plate/OCR/attributes, batched |
| c_bus | cell | NATS JetStream | per-camera subjects; priority lanes; store-and-forward |
| c_db | cell | PostgreSQL + PostGIS | 30-day hot observations; Patroni sync standby; rollups |
| c_media | cell | Media gateway | MediaMTX WHEP; copy or transcode; district wall |
| c_fed | cell | Federation adapters | Model 3: one adapter per departmental VMS |
| c_api | cell | Cell API + control room | district users; local alerts and evidence |
| r_sfu | region | SFU + TURN | pulls once per camera, fans out to remote viewers |
| r_gpu | region | Forensic GPU pool | T3 re-processing of NVR clips (selected Model 4) |
| r_obj | region | Backup object store + OCI mirror | cell WAL/base backups; images and model weights |
| s_kafka | state | Kafka | plate-reads (key: folded plate), alerts, health, audit heads, registry, watchlist |
| s_plate | state | Plate index | 64 virtual hash shards on 4 PostgreSQL hosts |
| s_reg | state | Model 1 registry + GIS | source of truth for 80,000 cameras |
| s_lake | state | Observation lake | S3-compatible, erasure-coded; Trino |
| s_api | state | State API + command centre | statewide search, routes, designated vehicle |
| s_sec | state | Identity and policy | Keycloak OIDC, OPA, SPIRE, KMS |
| s_ext | state | Government DB adapters | VAHAN, SARATHI, eGujCop, AFIS, NAFIS (enrichment / vehicle-keyed alerts) |
| s_obs | state | Observability | Thanos, logs, SLOs, capacity panels |
| s_worm | state | Evidence WORM + audit anchor | object lock; daily Merkle root of cell chain heads |
| dr | state | DR data centre | Kafka mirror, async replicas, lake replica |

Edges (`from → to | label`):

| from | to | label |
|---|---|---|
| cam_ip | c_ing | RTSP pull, 1 session (LAN / district network) |
| cam_an | c_ing | via encoder, RTSP |
| cam_ip | edge | RTSP on site LAN |
| nvr | c_fed | VMS API / SDK (Model 3) |
| nvr | r_gpu | clip pull on request (Profile G) |
| pvt | c_media | consented view-only tunnel |
| edge | c_bus | metadata only, compressed |
| c_ing | c_gpu | decoded frames |
| c_gpu | c_bus | observations, plates |
| c_bus | c_db | batched COPY |
| c_bus | s_kafka | real-time lanes (alerts, plates, health, audit heads) |
| c_db | s_lake | compressed micro-batches ≥ 1 min |
| c_ing | c_media | shared session fan-out |
| c_media | r_sfu | one pull per viewed camera |
| r_sfu | s_api | remote viewing (WebRTC) |
| c_db | r_obj | WAL + base backup |
| s_kafka | s_plate | consumers by partition |
| s_kafka | c_bus | watchlist and registry deltas (compacted) |
| s_reg | c_db | registry replica |
| s_ext | s_kafka | vehicle-keyed entries → hashed watchlist |
| s_api | s_plate | route and plate search |
| s_api | c_api | scatter-gather attribute search |
| c_api | s_worm | evidence and chain heads |
| s_kafka | dr | MirrorMaker 2 |
| s_plate | dr | async replication |

### 18b. Data flow (one vehicle, one read)

Nodes: `f1 frame (sub/main stream)` → `f2 T0 motion gate` → `f3 T1 detect + track` →
`f4 T2 plate crop + OCR, vote ≥ 2` → `f5 observation (dedup_key, 1,331.7 B)` →
`f6 cell DB + local hashed-watchlist match` → `f7 incident (grouped)` →
`f8 alert to control room` → `f9 evidence sealed (hash chain)`. From f5 two further
paths run: `f10 plate lane → Kafka plate-reads (key folded plate)` →
`f11 plate-index shard` → `f12 route builder (Camera Link Model, typed legs)` →
`f13 designated-vehicle route + trace report`; and `f14 bulk lane → micro-batch →
lake`. Separately, `f15 watchlist entry (state)` → `f16 hashed delta` → f6.

Edge labels:

| from | to | label |
|---|---|---|
| f2 | f3 | only if motion |
| f4 | f5 | at track close |
| f6 | f7 | hit |
| f5 | f10 | if plate confirmed |
| f5 | f14 | always |
| f12 | f13 | typed legs |
| f16 | f6 | < 1 min WAN up; last valid bundle if down |

## 19. Deck content — three slides (in `tools/demo/render_submission_deck.py`)

**Slide 1 — "80,000 cameras: only compute grows with cameras analysed"**

- Video stays with the department. Only metadata crosses the WAN: 82 Mbps statewide
  compressed at a pessimistic rate, against 160 Gbps for central video (modelled).
- A cell holds at most 2,500 cameras or 4,000 observations/s and runs detection, ANPR,
  alerts and evidence locally.
- Plates are partitioned by plate. A designated-vehicle route touches one shard.
- Camera-driven non-compute resources keep ≥ 5× headroom on throughput and ≥ 2.2× on
  hot storage at 100% analysed. The 3-year lake (1.5×) is bought per retention year.
- Unit costs measured on this project: 1,331.7 B per observation, 8× compression,
  14,187 rows/s PostgreSQL, 1.3 ms PostGIS viewport on 80,000 cameras.

Table: the growth table from §11 (analysed cameras → GPUs, cell WAN, state bus, DB
rows/s).

**Slide 2 — "Three tiers, and what survives each failure"**

- Camera/site: nothing new at most sites; edge boxes only where the link is thin.
- Cell (40): GPU pool, bus, PostgreSQL, media gateway, federation adapters. It keeps
  working with the WAN down.
- Region (6): SFU/TURN, backups, forensic GPUs. State + DR: Kafka, plate index,
  registry, lake, identity.
- Model 1 everywhere, Model 2 direct, Model 3 for VMS departments, Model 4 selected
  only.

Table: the §8 degradation table (what fails / keeps working / degrades).

**Slide 3 — "Binding-constraint check (pessimistic)"**

- Every resource's demand is compared with its capacity at 80,000 cameras, all
  analysed.
- Would-be bottlenecks found and removed: uncompressed WAN (0.85×), all observations on
  Kafka (1.13×), highway-heavy cells (0.91× on DB at half the measured write rate).
- Inference compute binds first. S is measured on tendered hardware before purchase.
- Capacities of Kafka, JetStream, gateway and TURN are assumed and are Phase 1 gates.

Table: the §11 rows for WAN, bus, DB, storage, media, API and watchlist (resource,
demand, capacity, headroom).

## 20. HLD insertion note (applied: `docs/HLD.md` §21 and the sections below)

| HLD section | Action |
|---|---|
| §3 Logical architecture | **Extend**: add the cell / region / state tiers and the Model 1–4 hybrid split table from §3 here |
| §6 Deployment | **Replace**: "33 district nodes" becomes "40 cells (≤ 2,500 cameras or ≤ 4,000 obs/s) + 6 regions + state/DR" |
| §12 Statewide operations table | **Replace rows** Central/regional/edge, Bandwidth, Storage, HA with pointers to §10–§13 here |
| §13 Prerequisites | **Extend** with the §16 department table |
| §15 DR | **Extend** with the §8 RPO/RTO and degradation tables |
| §16 Rollout | **Replace** the gates with §15's measured gates |
| §17 Cost model | **Keep** the S-solved model; **extend** with the ANPR 5 fps case; note that the 5.6 fps baseline has no JSON key (C4). The §7/§17.1 wording of the 11.4 fps run has already been corrected in the main tree. |
| §18 Cybersecurity | **Extend** with SPIFFE/SPIRE, OPA, audit-head anchoring and hashed watchlists (§7) |
| §20.1–20.7 | **Replace** the sizing with §10 and the storage sizes with §13. Hot metadata per district was 1.2 TB and becomes 14.4 TB pessimistic / 4.3 TB mean per cell. |
| §20.8–20.9 | **Keep** the unit rates; **add** §14's reconciliation table |
| New §21 | **Insert** §11 Binding-constraint analysis in full |

---

## Self-check (§11 attacked as a hostile reviewer)

Each row was recomputed with pessimistic assumptions
(`reports/capacity_model.json:hostile`).

| Attack | Recomputed | Result | What changed in the design |
|---|---|---|---|
| "Your 8× compression is optimistic." Assume 4×. | Cell WAN 6.82 Mbps vs 20 | 2.9× | None needed. Compression stays mandatory, and a Phase 1 gate (≥ 4×) was added. |
| "Uncompressed, on HLD's link?" | 23.46 Mbps vs 20 | **0.85× — binds** | Compression made a requirement, not an optimisation; the cell link planned at 50 Mbps with a 30 Mbps viewing budget. |
| "Put everything on Kafka like everyone does." | 88.8 MB/s vs 100 | 1.13× | Bulk observations moved off Kafka to micro-batches into the lake. The state bus carries 5.73 MB/s. |
| "Kafka brokers do 10 MB/s, not 50." | 5.73 vs 20 MB/s | 3.5× | None; the scaling axis is brokers. |
| "PostgreSQL on a server with synchronous standby writes half your laptop figure." | 7,094 vs 2,083 rows/s | 3.4× | None for an average cell. Batched-COPY rate made a Phase 1 gate. |
| "A cell full of highway cameras at cam04's peak hour." | 7,800 obs/s: DB 1.8× at the measured rate, **0.91× at half**; hot 30 d 53.9 TB on the 2× row (15.7 TB on the measured SQLite size) vs 32 TB | **would bind** | **Cells are sized by observation rate as well as camera count: at most 4,000 obs/s** (1,282 such cameras). At the cap: DB 1.8× at half the measured rate; WAN 3.2×; hot store 1.16× on the 2× row, 4× on the measured size. The hot window is a setting that auto-shortens at 70% fill, with older days in the lake. |
| "Half the estate is ANPR-grade and every observation carries a plate." | 33,333 plates/s: 4 shards 1.7×; Kafka 12.7 MB/s (7.9×); plate index 83 TB for 90 days | 1.7× | 64 virtual shards from day one, so moving to 8 hosts is a shard move (3.4×). GPU count would rise to 4,286. That is compute. |
| "10,000 users at 2 req/s on the state API." | 20,000 vs 12,331 req/s | **0.62× — binds** | Stated plainly: the API is user-driven, not camera-driven. District users go to cell APIs, and the state API scales out; 416 workers give 2×. |
| "5,000 remote preview tiles." | 2.5 Gbps vs 2 Gbps | **0.8× — binds** | Per-role tile budgets and the regional SFU; beyond budget, 1 Hz 15 KB thumbnails (600 Mbps for 5,000). Viewer-driven, not camera-driven. |
| "A 72 h state outage." | Plate backlog drains in 9.6 h | fine | Kafka retention set to 7 days (D), so a 72 h outage loses nothing. |
| "7-day WAN outage at a cell." | 194 GB compressed queue | fine | Queue disk sized at 7 days on the pessimistic rate. |
| "HLD's hot storage is too small." | 14.4 TB pess vs HLD's ~1.2 TB per district | HLD under-provisioned | 32 TB NVMe per copy per cell; reconciled in §14. |
| "Your observations/hour is inflated or deflated." | Active-hour mean 902.6 counts only hours with data, which inflates it. The pessimistic 3,000/h is 3.3× that and above the busiest camera's average. | conservative | Phase 1 gate (b) measures it on the real estate. |
| "RAM and decode are not 'inference'." | 20,000 cores, 7.85 TB RAM | — | Stated plainly as compute: they sit inside the compute servers and are sized per analysed camera. The claim is "compute", not "GPU only". |
| "Camera or NVR sessions." | not measured | unknown | Department requirement (§16). The placement rule prefers direct camera sub-streams; NVR egress limits are recorded in Model 1. |

**What remains unmeasured and could still surprise.**

- Data-centre GPU throughput (S).
- Kafka and JetStream on real hardware.
- MediaMTX copy-session density.
- NVR egress limits.
- Real GSWAN link rates.
- The share of ANPR-grade cameras in the real estate.

Each is either a Phase 1 gate or a department requirement. None is quoted as measured.
