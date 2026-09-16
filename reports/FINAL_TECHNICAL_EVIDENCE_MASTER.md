# Final technical evidence master

Timestamp UTC: consolidation from Phases 9–16 (hackathon evidence package).

This document is the **authoritative claim index**. Every claim carries exactly one label. Labels are never merged.

| Label | Meaning |
|---|---|
| **MEASURED_REAL** | Observed on real Sentinel/government endpoints or real upstream RTSP with env credentials |
| **MEASURED_SYNTHETIC** | Observed on local/synthetic publishers isolating the browser/media plane |
| **DESIGNED** | Architecture/scheduler intended for production; not a 50-government-feed measurement |
| **ESTIMATED** | Extrapolation / capacity model; not a soak result |
| **BLOCKED_BY_EXTERNAL_ACCESS** | Could not complete because Sentinel session/catalogue or upstream session access was unavailable |

Catalogue note: camera IDs `cam01`–`cam30` used in real soaks are **NOT_AUTHORITATIVE** probe IDs (no `/api/ingest` session cookie in this environment).

---

## 1. Key measured facts (required set)

| # | Claim | Label | Cite |
|---:|---|---|---|
| 1 | 30/30 documented cameras produced RTSP frames during the source census | MEASURED_REAL | `PHASE14_REAL_CAMERA_SOURCE_CENSUS.md` |
| 2 | 15/30 produced direct Sentinel WHEP browser frames | MEASURED_REAL | `PHASE14_REAL_CAMERA_SOURCE_CENSUS.md` |
| 3 | 15 concurrent local RTSP→H.264 bridge previews measured when sources were healthy | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` (scale n=15 PASS) |
| 4 | Real hybrid wall achieved **19** browser-visible cameras in the measured 60s run | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 5 | Of those 19: **15** were direct Sentinel WHEP | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 6 | Of those 19: **4** were bridged PREVIEW | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 7 | **11** remained RTSP-only AI on that soak | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 8 | **NO_SIGNAL** remained **0** on hybrid 30/60/120s soaks | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 9 | Warm bridge promotion p50 = **35.75 ms** | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 10 | Cold bridge promotion = **721.7 ms** | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 11 | H.264 B-frame **copy** path fails under MediaMTX WebRTC | MEASURED_REAL | `PHASE15_BROWSER_COVERAGE_CERTIFICATION.md`, `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 12 | VideoToolbox baseline transcode works for browser WHEP | MEASURED_REAL | `PHASE15_BROWSER_COVERAGE_CERTIFICATION.md`, `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 13 | Direct Sentinel WHEP is the primary browser path | MEASURED_REAL | `PHASE11_DIRECT_WHEP.md` |
| 14 | AI remains on RTSP/TCP (decoupled from browser WHEP) | MEASURED_REAL / DESIGNED | `PHASE11_DIRECT_WHEP.md`, operator cert |
| 15 | One-camera failure must not / did not destabilize peers (independent negotiation) | MEASURED_REAL | `REAL_30_CAMERA_WHEP_CERTIFICATION.md`, gov failure-isolation certs |
| 16 | 50-camera architecture is **designed**, not measured with 50 government sources | DESIGNED | `50_CAMERA_SCALING.md` |

---

## 2. Bottleneck statement (authoritative wording)

> Under controlled source conditions, the local media/bridge layer scaled to 15 concurrent preview bridges. During the real mixed-camera wall, large concurrent upstream Sentinel RTSP fan-in produced authentication/time-out/source-availability failures that reduced the number of ready bridges. The remaining limitation is therefore observed at the upstream source/session layer rather than demonstrated as a local VideoToolbox encode-capacity limit.

**Cite:** `PHASE16_30_CAMERA_BROWSER_COVERAGE.md`

Do **not** restate as system failure, impossibility of a 30-tile wall, or a completed 50-feed government measurement.

---

## 3. Phase dossier (what each phase proved)

### Phase 9 — Headed Metal + AI + scaling architecture

| Claim | Label | Notes / cite |
|---|---|---|
| Headed Chromium with ANGLE Metal on Apple Silicon used for wall certification | MEASURED_REAL / MEASURED_SYNTHETIC | Browser GPU path; see `BROWSER_HARDWARE_ACCELERATION.md`, Phase 10 |
| AI runtime on government cam path certified | MEASURED_REAL | `GOV_CAM01_AI_RUNTIME_CERTIFICATION.md` |
| 30-camera adaptive wall architecture (FULL / PREVIEW / inactive) | DESIGNED + partial MEASURED_REAL | Scheduler + operator wall |

### Phase 10 — Synthetic media scaling + prewarm + GPU

| Claim | Label | Cite |
|---|---|---|
| Synthetic concurrent full WHEP: n=16 → 16 PASS | MEASURED_SYNTHETIC | `PHASE10_MEDIA_PERFORMANCE.md` |
| Synthetic n=20 → 19 PASS / 1 FAIL | MEASURED_SYNTHETIC | same |
| Synthetic n=24 / n=30 partial PASS band | MEASURED_SYNTHETIC | same |
| Prewarm promotion ~7.74× faster (337 ms → 44 ms) on synthetic/local path | MEASURED_SYNTHETIC | same — **do not reuse as real bridged warm** |
| VideoToolbox preferred encode (~2× lower CPU/frame vs libx264 in bench) | MEASURED_SYNTHETIC / MEASURED_REAL | same |
| Live PREVIEW HLS MEDIA-SEQUENCE advances | MEASURED_REAL / MEASURED_SYNTHETIC | same |
| Government RTSP auth periods of 401 | BLOCKED_BY_EXTERNAL_ACCESS | same (intermittent) |

### Phase 11 — Direct Sentinel WHEP primary

| Claim | Label | Cite |
|---|---|---|
| cam01 direct WHEP 30s and 60s PASS (1920×1080) | MEASURED_REAL | `PHASE11_DIRECT_WHEP.md` |
| Direct 4-camera wall PASS (4/4) | MEASURED_REAL | same |
| Direct first-frame p50 slower than local relay in compare; direct still primary for production path | MEASURED_REAL | same |
| AI stays on RTSP/TCP | MEASURED_REAL / DESIGNED | same |
| Catalogue session external dependency | BLOCKED_BY_EXTERNAL_ACCESS | same |

### Phase 12 — Real Sentinel WHEP scale 1…30

| Claim | Label | Cite |
|---|---|---|
| Progression 1/4/8 all-PASS; higher N AMBER with peer isolation | MEASURED_REAL | `REAL_30_CAMERA_WHEP_CERTIFICATION.md` |
| Peak simultaneous PASS tiles (real, that progression) ≈ 10 | MEASURED_REAL | same |
| Best all-PASS real wall n=8 | MEASURED_REAL | same |
| Adaptive 30-camera wall with FULL_WHEP budget seeded from measured peak | MEASURED_REAL + DESIGNED | same |
| Probe IDs not authoritative catalogue | NOT_AUTHORITATIVE / BLOCKED_BY_EXTERNAL_ACCESS | same |

### Phase 13 — Operator wall + modes + prewarm UX

| Claim | Label | Cite |
|---|---|---|
| Operator 30-tile wall with LIVE/PREVIEW/NO_SIGNAL UX | MEASURED_REAL | `FINAL_30_CAMERA_OPERATOR_CERTIFICATION.md` |
| Warm promotion p50 ≈ 28 ms (operator path, that cert) | MEASURED_REAL | same |
| AI-FIRST / VIDEO-FIRST mode plan | DESIGNED | same |
| Panel opens (AI/alert/evidence/GIS) without wall stall | MEASURED_REAL | same |
| Early NO_SIGNAL=20 on operator wall was largely selection/WHEP pressure — corrected by Phase 14 census | MEASURED_REAL | Phase 13 cert + Phase 14 correction |

### Phase 14 — Source census

| Claim | Label | Cite |
|---|---|---|
| RTSP frames OK: **30/30** | MEASURED_REAL | `PHASE14_REAL_CAMERA_SOURCE_CENSUS.md` |
| Direct WHEP browser OK: **15/30** | MEASURED_REAL | same |
| Source-down: **0** | MEASURED_REAL | same |
| Correct classification: RTSP-only ≠ NO_SIGNAL | MEASURED_REAL | same |
| Catalogue `/api/ingest` unavailable without session | BLOCKED_BY_EXTERNAL_ACCESS | same |

### Phase 15 — Compatibility bridge

| Claim | Label | Cite |
|---|---|---|
| RTSP-only H.264 → VT baseline → local MediaMTX/WHEP works (cam07 proof) | MEASURED_REAL | `PHASE15_BROWSER_COVERAGE_CERTIFICATION.md` |
| Copy remux FAIL (B-frames) | MEASURED_REAL | same |
| Hybrid browser-visible raised to **19** (15 direct + bridged); bridge budget ≈ **6** | MEASURED_REAL | same |
| DIRECT_SENTINEL_WHEP path unchanged for WHEP-capable cams | MEASURED_REAL | same |
| NO_SIGNAL = 0 | MEASURED_REAL | same |

### Phase 16 — Bridge scale + hybrid wall

| Claim | Label | Cite |
|---|---|---|
| Bridge concurrency 1→15 PASS when upstream RTSP healthy; chosen budget **15** | MEASURED_REAL | `PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| Hybrid 30/60/120s: **19** browser-visible; 15 direct + 4 bridged; 11 RTSP_ONLY_AI; NO_SIGNAL 0 | MEASURED_REAL | same |
| Warm bridge promote p50 **35.75 ms**; cold **721.7 ms** | MEASURED_REAL | same |
| Remaining limit: upstream session/auth/timeout under large RTSP fan-in | MEASURED_REAL | same (bottleneck statement) |
| Solo 720p PREVIEW cost profile measured; concurrency path uses VT baseline @500k | MEASURED_REAL | same |
| 50-cam regional pools | DESIGNED | same / `50_CAMERA_SCALING.md` |

---

## 4. Plane separation (contract)

```
Sentinel Grid
 ├── RTSP/TCP  → AI plane (persistent ingest / inference)
 └── WHEP + Authorization: Basic → Chromium Metal → <video>   [preferred browser]
         └── optional: RTSP → VT baseline H.264 → local MediaMTX/WHEP   [compatibility]
```

| Plane | Transport | Label |
|---|---|---|
| Browser primary | Direct Sentinel WHEP | MEASURED_REAL |
| Browser compatibility | Local VT bridge | MEASURED_REAL |
| AI | RTSP/TCP | MEASURED_REAL / DESIGNED |
| Catalogue identity | `/api/ingest` session | BLOCKED_BY_EXTERNAL_ACCESS |

---

## 5. Scalability scoreboard (do not mix labels)

| Capability | Result | Label | Cite |
|---|---|---|---|
| 1 real camera direct WHEP | PASS | MEASURED_REAL | Phase 11/12 |
| 4 real camera direct WHEP | PASS | MEASURED_REAL | Phase 11/12 |
| 8 real camera direct WHEP | PASS | MEASURED_REAL | Phase 12 |
| ~10 peak simultaneous real PASS tiles | observed band | MEASURED_REAL | Phase 12 |
| 15 concurrent local bridges (healthy sources) | PASS | MEASURED_REAL | Phase 16 |
| 19 real browser-visible hybrid wall | PASS soaks 30/60/120s | MEASURED_REAL | Phase 16 |
| 30/30 RTSP source census | OK | MEASURED_REAL | Phase 14 |
| 30 adaptive operator wall | UX + budgeted FULL_WHEP | MEASURED_REAL + DESIGNED | Phase 12/13 |
| Synthetic browser ceiling 16 full WHEP | 16 PASS | MEASURED_SYNTHETIC | Phase 10 |
| 50 logical / regional architecture | plan only | DESIGNED | `50_CAMERA_SCALING.md` |

---

## 6. Judging language (approved framing)

Use:

- “Measured and pushed the local browser/media stack through controlled concurrency limits, then isolated remaining constraints at the external live-source/session layer.”
- “Adaptive media architecture prevents weak cameras from destabilizing the wall.”
- “Direct WHEP is preferred where supported; compatibility bridging is applied selectively.”
- “AI and video planes are decoupled.”
- “Architecture is designed for regional media/AI pools rather than a monolithic central decoder.”

Avoid unsupported superlatives, latency absolutes, and presenting the 50-feed regional design as a completed government measurement.

---

## 7. Artifact map

| Deliverable | Path |
|---|---|
| This master index | `reports/FINAL_TECHNICAL_EVIDENCE_MASTER.md` |
| PPT-ready slides | `reports/FINAL_PPT_TECHNICAL_CONTENT.md` |
| Limitations / external deps | `reports/FINAL_LIMITATIONS_AND_EXTERNAL_DEPENDENCIES.md` |
| Phase 10 | `reports/PHASE10_MEDIA_PERFORMANCE.md` |
| Phase 11 | `reports/PHASE11_DIRECT_WHEP.md` |
| Phase 12 | `reports/REAL_30_CAMERA_WHEP_CERTIFICATION.md` |
| Phase 13 | `reports/FINAL_30_CAMERA_OPERATOR_CERTIFICATION.md` |
| Phase 14 | `reports/PHASE14_REAL_CAMERA_SOURCE_CENSUS.md` |
| Phase 15 | `reports/PHASE15_BROWSER_COVERAGE_CERTIFICATION.md` |
| Phase 16 | `reports/PHASE16_30_CAMERA_BROWSER_COVERAGE.md` |
| 50-cam design | `reports/50_CAMERA_SCALING.md` |

JSON soaks (examples): `var/reports/phase10/performance/phase16_*.json`, Phase 14/15 hybrid wall JSONs under the same tree.
