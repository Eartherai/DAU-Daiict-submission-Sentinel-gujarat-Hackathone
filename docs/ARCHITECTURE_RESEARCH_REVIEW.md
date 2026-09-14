# Architecture Research Review

**Date:** 1 September 2026
**Status:** research phase complete; implementation gate is `FINAL_ARCHITECTURE_DECISION.md`
**Instruction:** attempt to disprove the current architecture, not defend it

---

# EXECUTIVE VERDICT

**SAAKSHYA survives the review, but three of its claims do not.** The thesis —
keep video at the edge, centralise intelligence and evidence — is confirmed by
production precedent and by arithmetic. What research kills is the *novelty
framing* around three components, and one of those kills is severe enough to
change the demo.

| Claim | Verdict | Evidence |
|---|---|---|
| Metadata-first federation | **Confirmed, not novel** | UK NAS runs ~90M reads/day on exactly this shape |
| Model 1 + Model 3 + Model 2 fallback | **Confirmed** | Model 1 is mandatory; Model 3 matches the 26-department political reality |
| Ingest reliability as the scoring lever | **Confirmed and strengthened** | 4 of 7 evaluation areas depend on surviving their feeds |
| **Re-ID recovers identity when the plate fails** | **DISPROVEN as stated** | Vehicle Re-ID drops **20–40% cross-dataset**; our estate is the worst case for this |
| **Capability-aware analytics scheduling is our innovation** | **DOWNGRADED N4 → N3** | Chameleon (MSR) and VideoStorm already do adaptive per-camera configuration |
| **Learned camera transition graph is novel** | **DOWNGRADED to N1** | "Camera Link Model" is standard in AI City Challenge literature since ~2019 |
| **Self-healing video fabric is novel** | **DOWNGRADED to N1/N2** | Self-healing GStreamer cascades for 100+ CCTV cameras are already published practice |
| BSA s.63 evidence preparation | **Holds — N4** | Legally required in India since 1 Jul 2024; no VMS vendor implements it |

**The single most important finding:** the hard-case demo as designed —
"plate unreadable at C-033, recover the vehicle by appearance" — rests on a
capability that the 2026 literature says degrades 20–40% when moved to an unseen
camera network. Gujarat's estate *is* an unseen camera network, and a
particularly hostile one. **The demo must be reframed from identity recovery to
candidate narrowing with explicit human verification.** That is both more honest
and, in front of a police jury, more persuasive.

**Nothing must be thrown away.** The existing build is ~3,100 lines and every
line of it is in the surviving architecture.

---

## 1. What the current build gets right

| Component | Assessment |
|---|---|
| PyAV over `cv2.VideoCapture` | **Correct and load-bearing.** Only PyAV exposes real PTS. This decision cannot be revisited without breaking everything downstream. |
| Dual-signal discontinuity detection | **Correct, and validated by measurement** that PTS alone misses a looping publisher's scene cut. |
| Warm-up GOP suppression | **Correct.** Directly targets a documented sandbox failure mode. |
| One capture per camera, internal fan-out | **Correct.** The guide warns each client gets its own stream copy. |
| Canonical event schema at 883 B | **Correct.** Matches the scale model and keeps the WAN argument honest. |
| Model registry with licence gating in code | **Correct and unusually strong.** Most teams handle licences by intention; we handle them by test. |
| Runtime profiles | **Correct.** Refusing to fake a GPU profile is the right call. |
| Declining on incapable cameras | **Correct, and this is the actual differentiator** (see §12). |

## 2. What is weak

1. **The intelligence layer does not exist yet.** Detector, tracker, store,
   search, graph, trajectory, watchlist, alert, evidence — none built. The
   mandatory test case is not demonstrable. This is the only genuinely serious
   problem in the project.
2. **Re-ID expectations are miscalibrated** (§6, §11).
3. **The synthetic corpus is too easy.** Rectangular vehicles, fronto-parallel
   high-contrast plates. It is a fine regression harness and a poor accuracy
   proxy. It systematically *overstates* what will happen on real feeds.
4. **No persistence.** Events are produced and discarded.
5. **`opencv` / PyAV native conflict** unresolved (one observed crash).
6. **Capability grading is specified but not measured from live streams.**

## 3. What must be thrown away

**Nothing in code.** Three *claims* must be thrown away:

- "We recover vehicle identity when the plate is unreadable" → replace with
  "we narrow the candidate set and hand the officer a ranked, evidenced choice".
- "Capability-aware scheduling is our innovation" → replace with "capability as
  a published, auditable property that gates analytics and discounts confidence"
  (the scheduling itself is Chameleon-lineage prior art).
- "Self-healing video fabric" as a headline → demote to an engineering quality,
  which is what it is.

## 4. What should remain

Everything built. Plus the four planes already specified: integration, edge
analytics, intelligence, evidence. The architecture shape is right; the
*claims* around it needed correction, and one capability needed demotion.

---

## 5. Global production benchmark

Full detail in `PRODUCTION_BENCHMARK.md`. The decision-relevant extract:

| System | Scale | Video plane | Metadata plane | Weakness for our purposes |
|---|---|---|---|---|
| **UK National ANPR Service** | ~90M reads/day | **Not centralised** | Central read store, 12-month retention, DVLA make/model/colour enrichment | ANPR-only; purpose-built readers |
| **Singapore PolCam** | 90,000+ cameras (2012→), 200,000 by mid-2030s | Centralised to POCC | Analytics for missing persons, suspect tracking | **Purpose-installed estate.** Every camera was chosen and sited by police |
| **NYPD DAS** | City-scale | Centralised | Federated data fusion | US legal context; not portable |
| **Genetec / Motorola / Axon** | Enterprise | Federated | Vehicle-centric investigation incl. partial/no plate | Assumes you deployed *their* readers |
| **Gujarat VISWAS / TRINETRA / NETRAM** | 7,000 → +12,500 cameras, 34 district centres, ~80 interstate points | District + state command | ITMS/ANPR → e-challan, ICCC–VAHAN integrated | **This is the incumbent.** We complement it or we are redundant |

**The insight that survives contact with all five:** every one of these was built
on an estate whose cameras were *chosen for the job*. PolCam sited 90,000
cameras for policing. UK NAS reads come from ANPR cameras. Genetec assumes
AutoVu readers.

Gujarat's challenge is the opposite: **26 departments of cameras installed for
something else entirely** — hospital gates, bus depots, godowns, panchayat
offices, PDS shops. The organiser's own dataset says so (Health, Police, GSRTC,
Panchayat, Municipal). No benchmarked system solves *that* problem, because no
benchmarked system had to.

## 6. Research SOTA — what changed our mind

Full detail in `RESEARCH_SOTA_2025_2026.md`. Three findings that altered the design:

### 6.1 Vehicle Re-ID does not generalise (the important one)

*Generalization Limits in Vehicle Re-Identification* (arXiv 2606.01981, 2026)
finds cross-dataset performance degradation of roughly **20–40%**, driven by
dataset bias, illumination, viewpoint and domain gap, and concludes that
deployment on a new network requires fine-tuning and site-specific labelled data.

**Consequence.** A Re-ID model trained on VeRi-776 or VehicleID, dropped onto
Gujarat's Panchayat and GSRTC cameras, should be expected to perform *materially
worse* than any published number. Any architecture that treats appearance
matching as an identity assertion is unsound.

**What we do instead:** appearance becomes one term in a candidate-ranking
score, never an identity claim; the physical graph does the pruning; the officer
does the deciding. This is a weaker technical claim and a stronger product.

### 6.2 The best MTMC methods assume calibration we will not have

*Spatial-Temporal Multi-Cuts* (arXiv 2410.02638) is the strongest online
multi-camera vehicle tracker found — a single combined min-cost multicut over
appearance and position, +14% IDF1 on CityFlow, +25% on Synthehicle, GPU RAMA
solver, genuinely online. **But it requires bird's-eye-view ground-plane
positions**, i.e. calibrated cameras.

Gujarat has no calibration for these cameras, and obtaining it for 80,000
cameras across 26 departments is not a hackathon activity — it is a multi-year
survey programme.

**Consequence — a new architectural principle: calibration-free by design.**
This is a constraint, not a weakness, and it should be stated explicitly to the
jury: any architecture that needs camera calibration cannot scale across this
estate. `CalibFree` (arXiv 2605.09245) confirms the research direction exists.
Usefully, the literature also notes vehicles have *lower appearance variance
than people*, which makes uncalibrated appearance matching more viable for
vehicles than for persons.

### 6.3 Adaptive per-camera configuration is prior art

Chameleon (Microsoft Research) and VideoStorm select per-camera configurations
(frame rate, resolution, model) adaptively, exploiting temporal and cross-camera
correlation, reporting 20–50% higher accuracy at equal resources or 2–3×
resource reduction at equal accuracy.

**Consequence.** Our `AnalyticsBudget` is a re-implementation of a known idea.
It stays — it is correct and necessary — but it is **N1/N2, and we will say so.**
The defensible remainder is described in §12.

### 6.4 Multi-query Re-ID is real but research-stage

*Multi-query Vehicle Re-identification: Viewpoint-conditioned Network* (TIP 2023,
arXiv 2305.15764) aggregates multiple viewpoints per identity. Sound direction,
no production implementation, and it inherits the generalisation problem above.
**Adopt the cheap 80%:** quality-weighted mean pooling over observations, which
needs no training and degrades gracefully. Defer learned aggregation.

## 7. Open-source landscape

Full audit of 55 repositories in `OPEN_SOURCE_LANDSCAPE.md`. Licence traps found:

| Repository | Licence | Consequence |
|---|---|---|
| `ultralytics/ultralytics` | **AGPL-3.0** | Rejected. Covers trained models per Ultralytics. |
| `mikel-brostrom/boxmot` | **AGPL-3.0** | Rejected. The default tracker toolkit. |
| `grafana/grafana` | **AGPL-3.0** | Usable as a *separate service*, never vendored. |
| `neo4j/neo4j` | **GPL-3.0** (Community) | Rejected — and we do not need a graph DB. |
| `redpanda-data/redpanda` | no SPDX (**BSL**) | Rejected for a government deployment. |
| `hashicorp/vault` | no SPDX (**BUSL**) | Flagged; prefer an Apache-licensed secret store. |
| `microsoft/autogen` | CC-BY-4.0, last push 138 days | Maintenance mode confirmed. Do not build on it. |
| `JDAI-CV/fast-reid` | Apache-2.0, **762 days stale** | Weights usable; do not depend on the framework. |
| `FoundationVision/ByteTrack` | MIT, **803 days stale** | Use a maintained reimplementation. |
| `Syliz517/CLIP-ReID` | MIT, **1,014 days stale** | Research reference only. |

## 8. Gujarat infrastructure reality

- **34 districts**; camera sites up to **~1,000 km apart** (organiser's FAQ).
- **TRINETRA** state i3C at Gandhinagar; **34 NETRAM** district command centres;
  **VISWAS** ~7,000 cameras phase 1 plus ~12,500 in phase 2 across 54 cities;
  **~80 interstate entry/exit points**.
- **ITMS with ANPR and RLVD already in production** in Ahmedabad, Surat,
  Vadodara, Rajkot, integrated with VAHAN and SARATHI, issuing e-challans.
- Coastline **2,340.62 km** (Survey of India, 2025 revision), **40+ ports**.

**The operational conclusion:** Gujarat does not have an ANPR problem. It has an
ANPR *estate* and a much larger non-ANPR estate that contributes nothing. Any
proposal that demos ANPR on good cameras is demoing what the state already owns.

---

## 9. Architecture alternatives evaluated

Scored 1–5, higher better. "Eval fit" is fitness for the 50-camera live test.

| # | Architecture | Cost | Latency | Scale | Reliability | Security | Vendor-neutral | Eval fit | Build time | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| A | Central VMS (Model 4) | 1 | 3 | 2 | 3 | 3 | 2 | 2 | 1 | **17** |
| B | Federated VMS (Model 3 alone) | 4 | 4 | 4 | 4 | 4 | 5 | 3 | 4 | **32** |
| C | Edge-first | 5 | 5 | 5 | 3 | 4 | 4 | 3 | 3 | **32** |
| D | Metadata-first | 5 | 4 | 5 | 4 | 4 | 5 | 4 | 4 | **35** |
| E | **Hybrid intelligence fabric (SAAKSHYA)** | 5 | 4 | 5 | 4 | 5 | 5 | 5 | 4 | **37** |
| F | Event-driven lakehouse | 4 | 2 | 5 | 4 | 4 | 4 | 2 | 2 | **27** |
| G | Federated search (no central index) | 4 | 2 | 4 | 3 | 5 | 5 | 2 | 2 | **27** |
| H | Agent-centric | 2 | 1 | 2 | 1 | 2 | 3 | 1 | 2 | **14** |

**Alternatives seriously considered and rejected:**

- **(G) Federated search over departmental indexes.** Politically elegant —
  each department keeps its own index, the centre federates queries, nothing
  centralises. Rejected: query latency across 26 heterogeneous departments is
  unpredictable, it is far harder to demo in 3 minutes, and the challenge
  explicitly asks for a unified platform. **Documented as the privacy-maximal
  variant** for the roadmap, because a reviewer may ask.
- **(F) Event-driven lakehouse.** Wrong for the PoC (query latency, build time),
  **right for the statewide tier**. Adopted as the documented scale path: Iceberg-
  style tables on object storage for the cold/warm event history, with the hot
  window in an operational store. This is a genuine improvement on the previous
  "Postgres forever" implication.
- **(H) Agent-centric.** Rejected outright. Non-deterministic at a live
  government evaluation is indefensible.

## 10. Vehicle retrieval architecture — the redesign

Options A–J were compared. **Selected: I — hybrid candidate retrieval + reranking**, with a specific ordering forced by the generalisation finding.

```
QUERY (plate | appearance | attributes | time | area)
  │
  ├─1. STRUCTURED PRUNE      exact/fuzzy plate, time window, district,
  │                          camera set, vehicle class          [SQL, ~ms]
  │
  ├─2. GRAPH PRUNE           physically reachable cameras given
  │                          learned transition times           [recursive CTE]
  │                          ← does the heavy lifting, because it does not
  │                            depend on a model generalising
  │
  ├─3. ANN CANDIDATES        appearance embedding, top-K within the
  │                          surviving camera×time cells        [filtered ANN]
  │
  └─4. RERANK                quality-weighted fusion:
                             plate agreement, appearance cosine,
                             attribute match, transition plausibility,
                             direction consistency
                             × observation quality
                             → ranked candidates + decomposition
```

**Why this order matters.** The naive design puts ANN first and filters after.
Given that appearance embeddings lose 20–40% moving to a new network, leading
with ANN means leading with the weakest signal. Leading with *structure and
physics* — which do not degrade across domains — means the fragile signal only
ever ranks an already-plausible set. This is the single most important design
change in this review.

## 11. Observation quality vector

Capability grading moves from per-camera to **per-observation**. A camera graded
"B" still produces occasional excellent crops and frequent useless ones; scoring
them identically discards information.

```
observation_quality = f(
    plate_pixel_width,      # the dominant term for ANPR viability
    sharpness,              # variance of Laplacian, resolution-normalised
    illumination, glare,
    occlusion_fraction,
    view_angle_estimate,    # from bbox aspect + track direction
    motion_blur,
    compression_artefacts,
    source_health           # from the stream layer's real counters
)
```

Used three ways: to weight multi-observation pooling; to discount final
confidence; and to decide whether an observation is worth storing an embedding
for at all (a storage saving at 80,000 cameras).

## 12. What is actually novel — conservative assessment

Using the N0–N5 scale, and deliberately erring low:

| Capability | Novelty | Justification |
|---|---|---|
| Camera federation, unified map, ALPR, hotlists, video wall, vehicle search, evidence export, NL search | **N0** | All commoditised. See "NOT OUR INNOVATION" in `PRODUCTION_BENCHMARK.md`. |
| Camera link / transition model | **N1** | Standard in AI City Challenge literature. |
| Adaptive per-camera analytics configuration | **N1** | Chameleon, VideoStorm. |
| Self-healing stream recovery | **N1/N2** | Published practice. |
| Quality-weighted multi-observation pooling | **N2** | Known method, new application here. |
| Graph-before-ANN retrieval ordering | **N3** | Composition justified by the generalisation finding; I could not find this ordering argued in the CCTV-retrieval literature. |
| **Capability as a published, auditable property that gates analytics, discounts user-facing confidence, and appears in the evidence record** | **N3** | Each part is prior art. The *composition* — where the same measurement drives compute routing, confidence, and a procurement gap-analysis artifact — I could not find precedent for. |
| **BSA s.63 evidence certificate preparation** | **N4** | Legally required in India since 1 Jul 2024. Zero VMS vendors implement it. Directly useful. NFSU is a knowledge partner. |

**Primary technical innovation (one):** capability-gated, graph-first,
quality-weighted vehicle retrieval that **declines** rather than guessing, and
carries the reason into the evidence record.

**Secondary operational innovation (one):** BSA s.63 evidence package prepared
automatically for authorised signature.

That is two claims. Not ten. Both are demoable in under 60 seconds each, both
are hard to bolt on the night before, and neither requires us to claim a model
accuracy we have not measured.

## 13. The final test — against Genetec, Motorola, Axon, NVIDIA, elite teams

> *What do we have that they do not already commoditize?*
> Genetec assumes you deployed AutoVu readers. We assume you deployed nothing on
> purpose. The capability layer exists because the estate is accidental.

> *What can we realistically build before 7 September?*
> The mandatory chain plus capability grading plus s.63 evidence. Not more.

> *What will work on ugly government feeds?*
> Structure and physics. Plate format validation, transition feasibility,
> declining. Not embeddings — see §6.1.

> *What survives a 50-camera live test?*
> The ingest contract. It is already measured against fault injection.

> *What plausibly scales to 80,000?*
> 926 events/sec and ~103 Mbps aggregate. The arithmetic is the argument.

> *What can we defend technically and legally?*
> Declining to answer, with a stated reason. And a s.63 certificate we do not
> sign on anyone's behalf.

> *What will the judge remember?*
> A system that said "I cannot read this plate, here is what I can support
> instead, and here is how sure I am and why." Every other team will show a
> green box around a number plate.

---

# APPENDIX A — Gujarat innovation candidates

52 candidates, scored 1–5 on: **Rel** (policing relevance) · **Nov** (novelty,
N-scale mapped to 1–5) · **Feas** (buildable before 7 Sep) · **Demo** (visible in
3 minutes) · **Gov** (value to Gujarat Police) · **Scale** (survives 80k).
**Σ** out of 30. Class: **CORE** (build now) · **DEMO** (build for the demo) ·
**ROAD** (roadmap slide) · **REJ** (rejected).

| # | Idea | Rel | Nov | Feas | Demo | Gov | Scale | Σ | Class |
|---:|---|--:|--:|--:|--:|--:|--:|--:|:--|
| 1 | Cross-district vehicle continuity (34 districts, siloed NETRAM) | 5 | 3 | 4 | 5 | 5 | 5 | **27** | **CORE** |
| 2 | Per-camera ANPR viability grading on non-ANPR estate | 5 | 4 | 4 | 5 | 5 | 5 | **28** | **CORE** |
| 3 | BSA s.63 evidence certificate preparation | 5 | 5 | 5 | 4 | 5 | 5 | **29** | **CORE** |
| 4 | Declining rather than guessing, with stated reason | 5 | 4 | 5 | 5 | 5 | 5 | **29** | **CORE** |
| 5 | Interstate entry/exit continuity (~80 VISWAS checkpoints) | 5 | 2 | 3 | 5 | 5 | 5 | **25** | **CORE** |
| 6 | Camera Link Model bootstrapped with zero survey | 5 | 2 | 4 | 4 | 5 | 5 | **25** | **CORE** |
| 7 | Quality-conditioned confidence shown to the officer | 5 | 3 | 5 | 5 | 5 | 5 | **28** | **CORE** |
| 8 | Statewide camera gap analysis (Model 1 deliverable) | 4 | 2 | 4 | 3 | 5 | 5 | **23** | **CORE** |
| 9 | Cloned-plate / OCR-anomaly detection from graph infeasibility | 5 | 3 | 4 | 5 | 5 | 4 | **26** | **DEMO** |
| 10 | Low-connectivity district operation (Kutch, coastal, border) | 5 | 2 | 3 | 5 | 5 | 5 | **25** | **DEMO** |
| 11 | ER/STQC compliance register per camera (mandate live Apr 2026) | 3 | 5 | 5 | 2 | 5 | 5 | **25** | **DEMO** |
| 12 | Grid Health: real reconnect/PTS/codec counters | 4 | 1 | 5 | 4 | 4 | 5 | **23** | **DEMO** |
| 13 | Autonomous camera onboarding (discover→measure→grade→register) | 4 | 3 | 3 | 4 | 5 | 5 | **24** | **DEMO** |
| 14 | Next-best-camera active search routing | 4 | 3 | 3 | 4 | 4 | 5 | **23** | **DEMO** |
| 15 | GSRTC bus-depot cameras as a state-wide sensor network | 4 | 4 | 3 | 3 | 5 | 4 | **23** | **ROAD** |
| 16 | Pilgrimage surge mode (Somnath, Dwarka, Ambaji, SoU) | 4 | 2 | 2 | 4 | 5 | 4 | **21** | **ROAD** |
| 17 | Port/freight corridor vehicle flow (Mundra, Kandla) | 4 | 3 | 2 | 3 | 4 | 4 | **20** | **ROAD** |
| 18 | Missing-person vehicle association | 5 | 2 | 2 | 4 | 5 | 4 | **22** | **ROAD** |
| 19 | Stolen-vehicle network analysis (repeat co-travel) | 4 | 3 | 2 | 4 | 4 | 4 | **21** | **ROAD** |
| 20 | Disaster mode: blocked-road inference from camera outage map | 3 | 4 | 2 | 4 | 4 | 4 | **21** | **ROAD** |
| 21 | Officer-confirmation feedback loop into ranking | 4 | 3 | 2 | 3 | 5 | 5 | **22** | **ROAD** |
| 22 | Convoy / co-travel detection | 3 | 3 | 2 | 4 | 4 | 4 | **20** | ROAD |
| 23 | After-hours movement in industrial estates | 3 | 2 | 3 | 3 | 4 | 4 | **19** | ROAD |
| 24 | Restricted-zone geofence entry | 3 | 1 | 4 | 3 | 4 | 4 | **19** | ROAD |
| 25 | Wrong-way driving detection | 3 | 1 | 4 | 4 | 4 | 4 | **20** | ROAD |
| 26 | Stopped/abandoned vehicle detection | 3 | 1 | 4 | 3 | 4 | 4 | **19** | ROAD |
| 27 | Camera clock-drift register | 4 | 3 | 5 | 2 | 5 | 5 | **24** | **DEMO** |
| 28 | Route-deviation anomaly for freight | 3 | 3 | 2 | 3 | 4 | 4 | **19** | ROAD |
| 29 | Accident-precursor hotspot analytics | 3 | 3 | 1 | 3 | 4 | 4 | **18** | ROAD |
| 30 | Crowd accumulation at transport hubs | 3 | 1 | 2 | 4 | 4 | 4 | **18** | ROAD |
| 31 | Toll/checkpoint dwell-time anomaly | 3 | 2 | 2 | 3 | 3 | 4 | **17** | ROAD |
| 32 | Cross-department camera federation scorecard | 4 | 3 | 4 | 2 | 5 | 5 | **23** | **DEMO** |
| 33 | Night-vs-day capability split per camera | 4 | 3 | 3 | 4 | 5 | 5 | **24** | **DEMO** |
| 34 | Monsoon degradation monitoring | 3 | 3 | 2 | 3 | 4 | 5 | **20** | ROAD |
| 35 | Automatic re-grading after camera replacement | 3 | 3 | 3 | 2 | 5 | 5 | **21** | ROAD |
| 36 | Evidence chain verification endpoint | 4 | 2 | 5 | 3 | 5 | 5 | **24** | **DEMO** |
| 37 | Purpose-bound search with case ID enforcement | 5 | 2 | 4 | 3 | 5 | 5 | **24** | **CORE** |
| 38 | Per-query audit trail, inspectable without exposing results | 4 | 2 | 4 | 2 | 5 | 5 | **22** | **CORE** |
| 39 | Jurisdiction-scoped access (district default, state authorised) | 4 | 1 | 4 | 2 | 5 | 5 | **21** | **CORE** |
| 40 | Signed watchlist edge cache for offline districts | 4 | 3 | 2 | 4 | 5 | 5 | **23** | ROAD |
| 41 | Duplicate-alert suppression + cooldown | 4 | 1 | 4 | 2 | 5 | 5 | **21** | **CORE** |
| 42 | Rejected-candidate memory (cleared vehicle does not re-alert) | 4 | 3 | 4 | 3 | 5 | 5 | **24** | **CORE** |
| 43 | Multi-observation quality-weighted pooling | 4 | 3 | 3 | 3 | 4 | 5 | **22** | **DEMO** |
| 44 | Vehicle-attribute search (colour/type) as fallback | 4 | 1 | 3 | 4 | 4 | 4 | **20** | **DEMO** |
| 45 | Adaptive tiering by measured capability (T0–T3) | 4 | 2 | 4 | 3 | 5 | 5 | **23** | **CORE** |
| 46 | T3 trigger-rate as a published scalability metric | 3 | 3 | 4 | 3 | 5 | 5 | **23** | **DEMO** |
| 47 | Department onboarding scorecard (what we need from you) | 4 | 3 | 5 | 2 | 5 | 5 | **24** | **DEMO** |
| 48 | Prompt-injection resistance test with adversarial scene text | 3 | 4 | 4 | 3 | 4 | 4 | **22** | ROAD |
| 49 | Facial recognition | 3 | 1 | 1 | 3 | 2 | 3 | **13** | **REJ** — not mandatory; licence + legal exposure |
| 50 | Blockchain evidence ledger | 1 | 1 | 2 | 2 | 1 | 2 | **9** | **REJ** — hash chain solves it |
| 51 | 3D digital twin of the state | 2 | 2 | 1 | 4 | 2 | 2 | **13** | **REJ** — decorative |
| 52 | Citizen-facing reporting app | 2 | 1 | 2 | 3 | 2 | 3 | **13** | **REJ** — out of scope, opens privacy questions |

## Top 20 (Σ ≥ 23)
3, 4, 2, 7, 1, 9, 5, 6, 10, 11, 13, 27, 33, 36, 37, 42, 47, 8, 12, 32

## Top 5
| Rank | Idea | Σ |
|---:|---|--:|
| 1 | **BSA s.63 evidence certificate preparation** | 29 |
| 2 | **Declining rather than guessing, with stated reason** | 29 |
| 3 | **Per-camera ANPR viability grading on a non-ANPR estate** | 28 |
| 4 | **Quality-conditioned confidence shown to the officer** | 28 |
| 5 | **Cross-district vehicle continuity** | 27 |

## The winning combination

Ideas 2, 4 and 7 are one thing: **a system that measures what each camera can
do, refuses the work it cannot do honestly, and tells the officer how much to
trust what remains.** That is the primary innovation (N3).

Idea 3 is the secondary innovation (N4) and the Special Jury Award play.

Idea 1 is the mandatory test case, executed well.

Everything else is a roadmap slide.

---

# APPENDIX B — Risk register

| # | Risk | Sev | Mitigation | Owner |
|---|---|---|---|---|
| R1 | No sandbox credentials; all evidence is from our replica | **High** | Register immediately — registration and submission share the 7 Sep deadline | all |
| R2 | Mandatory chain not yet demonstrable | **High** | Implementation resumes at item 1 of the order in `FINAL_ARCHITECTURE_DECISION.md` | all |
| R3 | Re-ID underperforms on government feeds | **High** | Already mitigated architecturally: graph prunes first, appearance only ranks, officer verifies | CV |
| R4 | No GPU; throughput unmeasured | Med | All GPU figures labelled MODELLED; nothing enters PPT unmeasured | all |
| R5 | Synthetic corpus overstates accuracy | Med | Labelled LOCAL SYNTHETIC CORPUS everywhere; accuracy claimed only on government feed | docs |
| R6 | opencv/PyAV native conflict | Med | Split decode and inference into separate processes | infra |
| R7 | Time: 6 days to submission, research consumed one | **High** | No further research phases. Implementation only. | lead |
| R8 | Departmental clip retrieval may fail (retention expired, system unreachable) | Med | Stated in HLD as an operational dependency rather than hidden | docs |
