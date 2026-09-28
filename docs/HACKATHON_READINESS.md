# Readiness against the evaluation criteria

Historical planning / measurement record. For the current submission use
[FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Current roles: government
`GJ11S7924` on cam06 is SINGLE-CAMERA evidence; own-feed `GJ18JX7786` on
C-014 then C-021 is a CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). Earlier rehearsal plate names,
screenshot counts, timings and dates below belong to their recorded run.
Current wall policy: CONTROL ROOM up to 30 direct WHEP sessions, 400 ms apart;
OPTIMIZED VIEW at most 12, 600 px prefetch, released after 15 s off screen
(`ui/app.js`). Old still-wall descriptions below are historical.


Every row states **implemented · tested · demonstrated · documented** and points
at the evidence. Where something is not done, the row says so rather than
softening it — a scorecard that only records strengths is a marketing document.

**Provenance labels used throughout:** `GOVERNMENT_LIVE` (the organiser's grid),
`LOCAL_SYNTHETIC` (our corpus, used for regression), `MODELLED` (calculated, not
measured).

Last updated: 6 September 2026 (quote sheet 21:02 UTC).

---

## Mandatory criteria

### A1 · Successful test case

| | |
|---|---|
| **Implemented** | Full chain: ingest → observation → plate search → camera graph → trajectory → watchlist → alert → evidence → verification |
| **Tested** | 31 end-to-end tests, 13 on the chain and 18 on offline operation. `make test-e2e` |
| **Demonstrated** | `make demo && make serve` — the whole chain from a registration mark |
| **Documented** | `docs/DEMO_SCRIPT.md` |
| **On live data** | Single-camera analytics: **yes**. Cross-camera chain: **not yet** — plates were read, none on more than one camera, so there is no shared identity to link cameras by. Designated-vehicle path rehearsed 4 September evening: watchlist + search + lookalike + trajectory + evidence on `GJ1VV0119`; prior alert on `GJ38BH5815`; timebase ALLOWED/REFUSED on `cam01+cam04` / `cam01+cam21` |

**Honest position:** the chain is demonstrated end to end on `LOCAL_SYNTHETIC`,
where a coherent timeline and legible plates exist by construction. On
`GOVERNMENT_LIVE` every stage up to plate identity runs and is measured; the
cross-camera stages await daylight in the replayed window.

### A2 · Solution presentation

| | |
|---|---|
| **Implemented** | `docs/PPT_CONTENT.md` — slide-by-slide, every figure labelled MEASURED or MODELLED |
| **Documented** | `docs/JUDGE_QA.md` answers the seventeen hardest questions with evidence |
| **Demonstrated** | `var/demo/SAAKSHYA_deck.pdf` — generated from `docs/PPT_CONTENT.md`. Launch film `var/demo/SAAKSHYA_launch.mp4` (15 min 03 s, live grid, boxed stills, map, Gemini on/off). |

The deck's permitted-numbers table lists exactly which figures may be quoted and
which phrases are forbidden — "production ready", "legally admissible", "tested
at 80,000".

### A3 · Solution architecture

| | |
|---|---|
| **Implemented** | `docs/ARCHITECTURE.md` (engineering), `docs/HLD.md` (proposal — hybrid Models 1+2+3; M2 is ingest stills), `docs/DATA_MODEL.md` (20 tables), 10 ADRs |
| **Tested** | The architecture's load-bearing claims are tests: no LLM in the chain, abstention, purpose binding, evidence integrity |
| **Documented** | `docs/FINAL_ARCHITECTURE_DECISION.md` records what was rejected and why, including Model 4 on arithmetic. HLD and the System page state the same hybrid. |

### A4 · Working platform and demonstration

| | |
|---|---|
| **Implemented** | 39 API endpoints, OpenAPI generated from routes; investigation workspace with no third-party asset |
| **Tested** | 55 adversarial security tests; every endpoint behind four authorisation gates |
| **Demonstrated** | `make serve` (synthetic) · `make live-serve` (government grid) |
| **Outstanding** | The investigation workspace is functional and dense. Overview now opens on a Shift picture (open alert, cameras that published a mark, ANPR GOOD vs emptiness) before the six evidence panels. The rest of the workspace is still an engineering surface |

### A5 · Video analytics output

| | |
|---|---|
| **Implemented** | Vehicle detection and classification, tracking, per-track ANPR with voting, **person detection from the same forward pass**, colour and attributes with abstention, quality scoring, six-dimension capability grading |
| **Tested** | 5 ML regression tests against corpus ground truth; model activation gate proves each model loads and infers; plate-voting tests pin lead vs confirmed, and forensic OCR rows now persist even when no observation is emitted |
| **Measured — `GOVERNMENT_LIVE`** | **689,502 observations** across 30 cameras, including **178,757 persons** (`docs/MEASURED_RESULTS.md`, 6 Sep 2026 21:02 UTC). Object mix from the same pass: car, truck, bus, motorcycle, bicycle, person — labels, not identity. **42,089** person long-stay reports (≥ 12 s); not intrusion. Detection-report Markdown in the pack may lag this sheet; do not quote `detections.csv` as the same run. People are tracked in a separate pool, never fused with a plate |
| **Measured — `GOVERNMENT_LIVE`** | **69 distinct registration marks**, **74** corroborated observations (votes ≥ 2), **43 leads** (votes = 1). **0 cross-camera repeats** and **1 OCR-lookalike pair** (`GJ32K5587`/`GJ3ZK5587`, 2 vs Z, both cam07) across those marks (6 Sep 2026 21:02 UTC, live store). **3,380** forensic OCR attempts stored. **9** cameras published a mark. Every mark is on a single camera. A one-frame plate is a LEAD labelled `REQUIRES_VERIFICATION`. Repeated reads on one camera are `SINGLE_CAMERA` (looping), not a fleet |
| **Implemented** | Forensic `plate_reads` (every OCR attempt, including rejected) is written from the pipeline. The live store holds **3,380** raw OCR rows (`docs/MEASURED_RESULTS.md`, 6 Sep 2026 21:02 UTC). Do not treat that as a second detection campaign — it is the same estate, now logging attempts. |

### A6 · Scalability and PoC readiness

| | |
|---|---|
| **Measured — `GOVERNMENT_LIVE`** | **30 of 30 cameras simultaneously**, 4 min: 16,913 frames, 11 reconnects and 79 scene cuts handled, 3.15 GB |
| **Measured** | 50 concurrent replica cameras, 52,637 frames, 0 decoder errors |
| **Measured** | 10 of 10 hot queries indexed; API p95 1.8–4.4 ms |
| **Measured** | Analytics saturates at ~11 cameras per CPU process; keyframe-only decoding for T0 is what made 30 fit |
| **`MODELLED`** | 80,000 cameras across 40 district cells, 6 regions and a state tier (HLD §21). **Never quoted as tested** |
| **Documented** | `docs/SCALE_MODEL.md` names where it breaks first |

### A7 · Submission completeness

| Item | Status |
|---|---|
| Solution presentation | `var/demo/SAAKSHYA_deck.pdf` — 54 pages, generated from `docs/PPT_CONTENT.md`. Full-page live UI. |
| Launch demonstration (live grid) | `var/demo/SAAKSHYA_launch.mp4` — 15 min 03 s, every surface, Gemini on in the masthead, boxed government stills |
| Designated-vehicle UI on own-feed corpus | `var/demo/SAAKSHYA_designated.mp4` — `GJ05AB1234` / `GJ35BV6925` on C-014 + C-021; labelled LOCAL SYNTHETIC |
| Technical proposal / HLD | `docs/HLD.md` + `var/demo/diagrams/` |
| Own-feed demonstration video (2–3 min) | `var/demo/own_feed.mp4` — 2 min 47 s · 1920×1080 · 25 fps, plus CSV/JSON report |
| Government-feed demonstration + output report | Video: `var/demo/government_feed.mp4` + that render's CSV/JSON. **Full live-store report:** Markdown/JSON in `var/reports/detections/` refreshed from SQL on 6 Sep 2026 21:02 UTC (store still growing — quote Overview or `docs/MEASURED_RESULTS.md` on the day). The CSV beside it is an earlier snapshot — do not quote CSV and Markdown as one run, and do not quote the video CSV as the live store |
| Repository | Ready |
| **Portal registration** | **NOT DONE — https://sentinel.gujarat.gov.in/register — last date 15 September 2026** |

---

## Bonus criteria

### B1 · Innovative hybrid / custom architecture

**Claimed narrowly and defensibly.** Not a novel algorithm — an integrated
operational architecture for a specific, badly-behaved estate:

- **Capability-gated, quality-weighted, graph-first retrieval.** Structure and
  physics prune before the fragile signal ranks anything, because the appearance
  baseline was *measured and rejected* (DINOv2 margin −0.541).
- **BSA s.63 evidence preparation** with signature blocks deliberately empty.

Three earlier novelty claims were **withdrawn** after finding prior art —
Chameleon/VideoStorm, the Camera Link Model, self-healing pipelines. That
withdrawal is in `docs/ARCHITECTURE_RESEARCH_REVIEW.md`.

### B2 · Cross-camera vehicle movement and correlation

| | |
|---|---|
| **Implemented** | Camera Link Model learning travel-time distributions from observed traversals; trajectory with typed legs; next-best-camera ranking; **time clustering** |
| **Tested** | 10 timebase tests, plus trajectory and graph suites |
| **Measured — `GOVERNMENT_LIVE`** | Twelve cameras confirmed on one window (`GRID-14JUN-0353`, basis MEASURED_OVERLAY); others hours or weeks apart |

**The distinctive part:** whether two observations may share a timeline is a
per-pair decision — ALLOWED, RESTRICTED or REFUSED — and the default absent
evidence is RESTRICTED. On this grid, permitting by default is exactly how a
seven-week route gets presented as a journey.

### B3 · Additional reliable analytics beyond ANPR

| | |
|---|---|
| **Implemented** | Vehicle classification, colour with abstention, presence (T0 motion), **person detection and dwell**, **camera capability grading**, infrared detection |
| **Measured** | 16 of 30 live cameras are infrared and are refused for colour reasoning — detection and presence unaffected. **178,757 person observations** on the live grid, from the same detector pass as vehicles (`docs/MEASURED_RESULTS.md`, 6 Sep 2026 21:02 UTC) |
| **Outstanding** | Wrong-way, stopped-vehicle and restricted-zone analytics are **not built**. Deliberate: the mandatory chain and live integration came first. Dwell is reported; "intrusion" is not claimed |

### B4 · Edge processing, bandwidth, low connectivity

| | |
|---|---|
| **Implemented** | Durable local queue with acknowledgement-not-deletion; idempotent replay; watchlist bundles that fail closed; keyframe-only decoding by tier |
| **Tested** | 18 end-to-end offline tests: detection, watchlist, alert and evidence all continue with the link down; replay reconstructs the timeline with no duplicates and no loss, including partial delivery |
| **MODELLED / MEASURED** | ~400 B optimised payload model vs 1,331.7 B measured serialised row (`var/reports/bandwidth.json`); sizing uses the measured row. Daily/storage arithmetic for both: `docs/SCALE_MODEL.md`. |
| **Outstanding** | Bandwidth measured under all three modes (raw / metadata / event-triggered) is **not done** |

### B5 · Cybersecurity, privacy, auditability, RBAC

| | |
|---|---|
| **Implemented** | Four independent gates — authentication, role, jurisdiction, **purpose binding**; hash-chained audit; hash-chained evidence; no credential-issuing endpoint |
| **Tested** | 55 adversarial tests. A deliberate mutation of the scope check was confirmed to fail two of them |
| **Documented** | `docs/SECURITY.md`, `docs/PRIVACY.md` |

**The distinctive part:** a vehicle search is refused without a case identifier
and a written purpose, before any data is read. And **ADMIN holds no search
permission** — running the estate and investigating people are different jobs,
enforced by the permission table, asserted at import, and served at
`/admin/roles` so it can be checked rather than trusted.

### B6 · Operational dashboards, alerts, health, APIs

| | |
|---|---|
| **Implemented** | Overview, alerts with acknowledge/clear, camera capability inventory, audit view, evidence chain view, Prometheus metrics, `/healthz` and `/readyz` |
| **Tested** | Endpoint coverage in the security and unit suites |
| **Measured** | Live health persisted for all 30 government cameras |
| **Outstanding** | Live stills work when `SENTINEL_GRID_EMAIL`/`PASSWORD` are in the API process; without them the wall says so in one notice rather than hanging on 401s. Overview now opens on a Shift picture; Investigate / System remain the denser engineering surface |

---

## Where we are weakest

Stated plainly, because a judge will find these anyway:

1. **No government-feed demonstration of the cross-camera chain.** 69 plates
   were read on the live grid; **none** repeats across cameras. One OCR-lookalike
   pair (`GJ32K5587`/`GJ3ZK5587`) sits on the **same** camera, so it is not a
   shared identity. The chain is demonstrated end to end on `LOCAL_SYNTHETIC`,
   where two marks are read on two cameras by construction.
2. **Catalogue coordinates are still blocked.** Nineteen cameras are placed
   from their names (`DERIVED_FROM_NAME`) with stated precision; eleven are
   `NAME_INSUFFICIENT`. Surveyed catalogue coordinates need a signed-in session
   we do not hold. Nothing is invented to fill the map.
3. **The interface is functional, not polished.** Overview now opens on a
   Shift picture. Investigate and System remain dense engineering surfaces.
4. **Wrong-way, stopped-vehicle and restricted-zone analytics are not built.**
   Person detection and dwell are. "Intrusion" is not claimed.
5. **Confidence is not calibrated**, and every response carrying a score says so.
6. **Portal submission upload is outstanding** and is the critical path to the
   15 September deadline. Stream access is issued; the CDN catalogue session is
   not.

## Where we are strongest

1. **The live grid found three faults in our own code that no synthetic test
   could have** — a detector that had never produced a detection. That is the
   best argument that this system has met reality.
2. **Abstention is real.** Zero cameras graded GOOD for ANPR (28 UNSUITABLE,
   2 UNKNOWN — cam22 too few vehicles, cam28 persons only) while **nine
   cameras still published 69 marks**. The grade is yield at this geometry,
   not existence of a read. Sixteen infrared cameras are refused for colour.
3. **Every threshold is defensible** and several were corrected *against* our
   own interest when measurement contradicted them.
4. **Evidence and audit are hash-chained and verified**, with the s.63
   certificate deliberately unsigned.
5. **Purpose binding** makes the reason for every intrusive query survive the
   officer who ran it.
