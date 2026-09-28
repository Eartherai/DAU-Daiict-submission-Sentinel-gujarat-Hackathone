# SAAKSHYA — authoritative final submission index

Upload `var/demo/SUBMIT/`, assembled by `tools/demo/build_submission_pack.py`.
This index supersedes older submission/upload pages. File names and required
status below follow that builder’s `ITEMS`; optional files must be checked for
presence in its build output. Do not infer that an index entry proves a file
has been rebuilt.

`07_LIVE_INTEGRATION_STORY.md` (in this pack) — what integrating the shared live grid took: measurements reported to Sentinel, the question we sent and its answer, the implementation we rebuilt in response, and the 28 September recording session.

## What to upload and what it proves

| Pack file | Status | Evidence / purpose |
|---|---|---|
| `00_SUBMISSION_INDEX.md` | Required | This authoritative index |
| `01_SAAKSHYA_deck.pptx`, `01_SAAKSHYA_deck.pdf` | Required | Model justification, workflow, analytics, watchlist, technologies, deployment and benefits |
| `02_HLD.md` | Required | Technical proposal; portal headings mapped to HLD sections |
| `02_HLD_diagrams.pdf` | Required | Architecture, authorisation, evidence and capability diagrams, plus the statewide architecture and one-read data flow (HLD §21) |
| `02_SECURITY.md` | Optional in builder; include when present | Application controls and deployment security boundaries |
| `02_STATEWIDE_ARCHITECTURE.md` | Required | DESIGNED statewide target architecture (40 cells, 6 regions, state + DR) with its MODELLED capacity and binding-constraint analysis; summarised in HLD §21, reproduced by `tools/sizing/capacity_model.py` |
| `03_own_feed.mp4` | Required | **2 m 43 s** (163.0 s) · 2560×1440 · narrated and captioned (`var/demo/own_feed.mp4`, ffprobe); recorded 28 Sep 2026. From the masked sign-in gate: registry-form onboarding validated before write, the administrator → officer handoff, both licensed Mumbai feeds with the pipeline's per-frame boxes (plates drawn only when the vote holds; heads blurred), an ANPR search, a fictional-plate watchlist alert with its map, route and trace report (SYNTHETIC RENDERED TEST CORPUS, labelled on screen), and the evidence chain. The recorder refuses a take if either video stalls for a second or its boxes stop drawing |
| `04_government_feed.mp4` | Required | **5 m 40 s** · 2560×1440 · encoded 30 fps (screen captured at 6.2 fps, `var/demo/gov_take7/capture.json`) · narrated and captioned; recorded on the live government grid on 28 Sep 2026, 12:41–12:47 IST. Opens on the OPTIMIZED VIEW wall with the live count measured on screen (8 of 30 at the opening, 6–13 across the wall beats), then the thirty-tile CONTROL ROOM layout (12 of 30 live in this recording), a focused live government camera with its intelligence panel, analytics, cam12 person detections and the demonstration restricted-zone rule, the government ANPR gallery, team-chosen stand-in `GJ11S7924` (SINGLE-CAMERA, cam06), GIS, the trace report, the ANPR CSV, evidence, system status and the Model 1 registry as estate administrator. This shows the result of government onboarding, not an onboarding action; bulk-validation, administrator-refusal and handoff beats were not filmed in this live take. The own-feed film shows single-camera form onboarding and the administrator → officer handoff; the full tour (`04b`) shows bulk validation, the refusal and the handoff on recorded footage. |
| `04_government_feed_1080p.mp4` | Optional | The same take re-encoded to 1920×1080 |
| `04_government_feed_anpr_report.csv` | Required | 1,101 government reads · 264 distinct plates · 9 cameras, government cameras only (`/reports/anpr.csv?reads=all&domain=GOVERNMENT`): 901 reads to the 24 Sep snapshot (earlier recogniser) and 200 read live on cam06 during the 28 Sep session (11:15–12:53 IST) by the current recogniser. The appended CSV `ocr_model` column uses each observation's `model_versions.ocr`, or `earlier` when absent; the session rows have `awiros-anpr-ocr`. Columns: plate, camera, UTC/IST timestamps, votes, confidence, confirmation, observation and evidence ids. |
| `04b_government_tour.mp4` | Optional in builder; include when present | **15 m 04 s** (903.9 s) · 1920×1080 (2560×1440 master `var/demo/government_tour.mp4`) · narrated and captioned; recorded 28 Sep 2026 on a copy of the government store. **Every feature, from the masked sign-in gate:** the wall in CONTROL ROOM and OPTIMIZED VIEW, a focused camera with its intelligence panel and analytics, cam12 person detections and the demonstration zone rule, the ANPR gallery and both CSVs, watchlist categories, the alert queue (open → acknowledge → investigate → resolve), exact, partial, fuzzy and attribute searches, the single-camera trajectory, GIS, evidence with a fresh chain verification, the trace report, cases and case export, the Gemini copilot, the audit hash chain, Model 1 grades, gap analysis, form and bulk validation (nothing imported), the capability layer and camera search on the estate map, Model 3 connected systems, Model 4 analytics, system status, the administrator's refused search and the handoff. **The wall and focus play RECORDED GOVERNMENT FOOTAGE** — 14 government cameras' 12-second clips downloaded on 15 Sep 2026, replayed with the production pipeline's per-frame boxes, labelled `RECORDED · captured 2026-09-15` on every tile and never called live (`07_LIVE_INTEGRATION_STORY.md`, last section). The copilot is asked where the designated stand-in `GJ11S7924` was seen; its answer (57 reads, one camera) is grounded in stored results, and its word "strong" is the model's: the older-still caution below still applies. Named skips, stated on the beat record (`var/demo/government_tour_20260928_214832/beats.json`): no watchlist add or revoke form exists in the UI. |
| `04b_government_tour_replay_reads.csv` | Optional in builder; include when present | The replay's plate reads, kept out of the government CSV: 7 reads of 4 plates, all `GOVREC-cam06`, source domain `ARCHIVAL_REPLAY`, current recogniser. Timestamps are the 15 Sep download window, not the scene time. By eye, 3 of the 4 plates match the picture; `RJ12J8713` is unverified |
| `05_MODEL1_GAP_ANALYSIS.md` | Required | Measured registry completeness; count belongs to that report’s snapshot |
| `05_REGISTRY_API.md` | Required | Registry API contract |
| `05_sample_camera_metadata.csv` | Required | Exported camera metadata sample, not proof of live sessions |
| `05_SCALE_80K_LOAD_TEST.md` | Required | MEASURED synthetic registry/GIS load; no statewide live video or AI test |
| `05_ADAPTERS.md` | Required | Model 3 adapter protocol, implementations and limits |
| `05_FEDERATED_ANALYTICS_REPORT.md` | Required | Federated metadata analysis with source/truth labels; DEMO adapters distinguished |
| `06_designated_vehicle_trace_report.html` | Required | `GJ11S7924` on cam06 only: government SINGLE-CAMERA evidence |
| `06_own_feed_trace_report.html` | Optional in builder; include when present | `GJ18JX7786`, C-014 then C-021: SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage |
| `07_LIVE_INTEGRATION_STORY.md` | Required | The live-grid integration timeline: 19 Sep measurements reported to Sentinel, the question sent and Sentinel's answer (sanitised, no names or addresses), the rebuild it prompted, and the 28 Sep session (eight attempts, the 5:40 take, 401 from 12:57 IST) |

The own-feed film was recorded on 28 September. Its boxes and plates are the
per-frame sidecars the production pipeline wrote over each file on 28 Sep
(00:55 and 01:17 IST) with the Indian-trained recogniser, replayed against
the video clock: analysis replay, not a live-inference speed claim. On the
queue clip that vote published 56 marks: 40 checked correct by eye, 4 wrong
and 12 not settled by a crop (`var/reports/ocr_indian_eval.json`,
`final_pipeline`). The film's ANPR search returns the 23 stored `MH02GB4920`
reads, written on 24 Sep by the previous recogniser (Apple Vision); the final
pipeline's sidecar publishes the same mark on the same clip. The separate synthetic route uses
computer-rendered clips from `tools/sandbox/make_media.py`, not licensed Mumbai
footage. Its legacy report filename does not describe its source domain.

The delivered government CSV contains **1,101 reads, 264 distinct plates and
9 cameras**: 901 reads from the 24 Sep snapshot plus 200 from the 28 Sep
session (11:15–12:53 IST). Only 21 session reads fall within the filmed take
(12:40:59–12:47:22 IST). The snapshot alone contains 474 confirmed read rows
representing 97 distinct confirmed plates (at least two agreeing frames).
These counts were checked with `csv.DictReader` on
`var/demo/government_feed_anpr_report.csv` and read-only SQL on `var/live.db`.
No plate repeats across government cameras; no government observation carries
an appearance embedding. The film's analytics totals include own-feed data in
the same store. The delivered CSV is government-only and was exported at the
end of the session, adding 36 rows to the 1,065-row CSV shown in the film.

**Older sealed-still limitation.** A content hash verifies unchanged bytes,
not that the image shows the vehicle named by its plate record. The older
worker sealed the frame in hand when a track closed; that frame can show a
different vehicle. Treat older stills as requiring visual/source verification,
including those in historical trace reports and films. Since the worker session starting 28 Sep 2026 11:15 IST (commit `672a2a0`), the worker
seals the frame each plate was best read from, so new captures show the read
vehicle's frame; stills sealed before it are unchanged. See `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`.

Repository paths cited below are source references, not additional pack files.
The current builder does not include `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`,
`docs/SCALE_MODEL.md`, `docs/MEASURED_RESULTS.md`,
`docs/SENTINEL_SUPPORT_CLARIFICATION.md`, `docs/PRIVACY.md` or `docs/API.md`.
Their inclusion remains a pack-assembly gap; the essential counts and limits
are stated here and in the supplied HLD, without assuming repository access.

## Requirement coverage (official FAQ Q24, Q29–Q36)

| Requirement | Where the judge can inspect it |
|---|---|
| Model justification, overview, features (Q29) | Presentation; `02_HLD.md` §§1–3; hybrid source paths below |
| Architecture and diagrams (Q24/Q30) | `02_HLD.md` §§3–4, §6, §21; `02_STATEWIDE_ARCHITECTURE.md`; `02_HLD_diagrams.pdf` |
| IP/analog, multi-vendor cameras/VMS (Q30) | HLD §10, §13; `05_ADAPTERS.md` — distinguish direct integration from federation |
| Dispersed sites, edge/central split, low bandwidth (Q30/Q35) | HLD §§6, 20.1, 20.4, 21 |
| ANPR and cross-camera tracking (Q24/Q30) | HLD §§4.2–4.5, 11; government SINGLE-CAMERA and synthetic route-logic reports above |
| Privacy, RBAC, audit and security (Q24) | HLD §§4.8, 18; `02_SECURITY.md` |
| Department technical inputs (Q24/Q30) | HLD §13, including Home/Police, Food & Civil Supplies, RTO and sandbox departments |
| Compute/GPU sizing and costs (Q24/Q35) | HLD §§17, 20.2–20.3, 20.8–20.9, 21; synthetic registry load report |
| Hot/warm/cold retention, scaling, monitoring, HA/backup/DR (Q35) | HLD §§15, 20.5–20.7, 21; assumptions and untested deployment work labelled |
| Phased statewide rollout (Q35) | HLD §§14, 16 |
| Working software films and timestamped output (Q31–Q33) | Own-feed film, the live government film and its ANPR CSV, and the full-feature tour on recorded government footage (labelled as such) above; no mock-ups, animations or concept films |
| Delivery and completeness (Q34/Q36) | Pack inventory above; signed-out viewer-link checks below |

Government analytics evidence is summarised in
`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`: vehicle and person detection were
measured across historical government observations; restricted-zone reporting
uses an administrator-created demonstration rule on cam12. There are no
government appearance embeddings or government cross-camera plate matches.
This does not establish completion of the moving-vehicle test across multiple
government cameras (FAQ Q27–Q28); there is no real multi-camera evidence. Route logic is shown only on the
synthetic rendered test corpus, which does not satisfy the real-footage requirement.

## Claims to keep separate

Model 1 is compulsory: both source paths register identity, GIS and governance
there. **Model 2 connects directly** to reachable cameras/NVRs or departmental
systems over RTSP/ONVIF, without a federation middleware layer. **Model 3 uses
VMS federation middleware** between departmental VMS APIs/SDKs and the unified
platform. Transport adapters alone do not prove departmental VMS federation.
The connector contract and DEMO/TEST implementations are in `docs/ADAPTERS.md`;
the adapter contract and DEMO/TEST connectors are built; no vendor SDK client
or ONVIF discovery exists, and live departmental federation is DESIGNED. Selected central analytics
is the Model 4 part of this hybrid (official FAQ Q12–Q23).


- **VERIFIED:** Models 1 (registry/GIS/governance), 2 (unified viewing and
  metadata search), 3 (VMS federation/adapter middleware), and 4 (selected
  central analytics) form the hybrid. Statewide central recording is declined
  on the MODELLED arithmetic in `docs/SCALE_MODEL.md`.
- **VERIFIED:** evaluation baseline 30 GOVERNMENT + 2 OWN_FEED + 18
  SYNTHETIC_CONTROL = 50; operator additions remain in the registry
  (`src/saakshya/command/domain.py::enforce_evaluation_50`).
- **VERIFIED:** CONTROL ROOM permits up to 30 direct WHEP tile sessions;
  OPTIMIZED VIEW permits at most 12 near the viewport (`ui/app.js`).
  Browser signalling uses the authenticated proxy; AI workers use selected
  RTSP/TCP streams separately. Session policy is not measured AI coverage.
- **MEASURED:** team-chosen stand-in `GJ11S7924` has 57 stored reads
  on cam06 (52 to the 24 Sep snapshot + 5 during the 28 Sep session); `GJ38BH5815` is `evaluation_designated`, not stolen. Read-only SQL
  and the active watchlist snapshot are in `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`.
- **MEASURED:** local load began with 50 streams and ended with 44 streaming
  and 6 down, with 36 open failures and no decoder errors
  (`var/reports/camera_load.json`). No recovery is claimed.
- **MEASURED:** 1,331.7 B per serialised observation
  (`var/reports/bandwidth.json`). **MODELLED:** ~400 B compact payload.
  Sizing uses 1,331.7 B for raw rows and assumes the separate government sample
  represents compressed payloads: 1,230.6 B → 154.0 B, 8.0× on its own base
  (`reports/measure_compression.json`). Applying 154.0 B to the larger raw-row
  base implies an effective 8.65×, not a measured ratio on that base;
  the capacity model is `tools/sizing/capacity_model.py` (HLD §21).
- **MEASURED:** laptop GPU benchmark had matching observation counts but no
  plates on either device (`var/reports/pipeline_device.json`); it predates
  the current recogniser. GPU pool capacities and the 40-cell deployment are
  **MODELLED/SIZED**, not measured cluster results.
- **DESIGNED:** statewide rollout, distributed HA/DR, retention tiers and
  authorised government database integrations. FRS is designed and gated.

Current demonstration hardware limits simultaneous deep-inference concurrency.
Analytics workers scale horizontally, so additional GPU nodes raise concurrent
inference throughput without redesigning ingest, event, watchlist, GIS or
investigation services. Priority cadence and tier selection are built and tested
in a harness/unit tests; live-worker integration is DESIGNED. The live worker
samples at a fixed interval and does not rotate cameras. Coverage is “N of M
camera(s) with a stream under analysis” (`command/summary.py`).

The default is **4 deep-inference slots, prioritised by measured capability**
(VERIFIED in `src/saakshya/analytics/worker.py`, `SAAKSHYA_AI_CAMERA_LIMIT`).
At worker boot, stream-capable enabled cameras are ranked GOOD > DEGRADED >
UNKNOWN > UNSUITABLE by ANPR grade; ties use camera id. Assignments do not
rotate at runtime. This configured default is separate from the historical
four-camera measurement in `reports/SCALE_80K_LOAD_TEST.md`.
`command/summary.py` reports “N of M camera(s) with a stream under
analysis”.

## Evaluation-day procedure

`GJ11S7924` was chosen by the team from its cam06 reads on 20 Sep as a
stand-in, not issued by the organisers. Its representative authority field is
not evidence of organiser designation. For the actual number issued on the day
(FAQ Q27), the officer enters the plate under a case and purpose, searches the
whole estate retrospectively, files it on the watchlist for live alerts, and
opens the trace report to review timestamped locations and evidence. Missing
locations remain gaps; a single-camera history is not a complete moving route.
Government time-to-onboard, time-to-first-analysed-frame and frame-PTS-to-alert
p50/p95 are **not measured** (Q28); the synthetic registry insert benchmark
cannot substitute for them (`02_HLD.md` §7).

The evaluation baseline is 50 cameras. The read-only 28 Sep registry has 56
rows with operator additions: 30 GOVERNMENT, 6 OWN_FEED, 18 SYNTHETIC_CONTROL
and 2 without an explicit stored domain (`var/live.db`, grouped by
`cameras.source_domain`). Gap-analysis reports exclude CTL capacity slots and
therefore have a different denominator.

## Live-demo and pack commands

These commands are for the authorised operator at the final demo. They were
not run as part of the offline documentation audit. Supply credentials through
the existing local environment/token files, never through documents or URLs.

```bash
# Local DEMO store and workspace
make demo
make serve

# Government workspace, after approved live access is available
make live-serve PORT=8083
# Separate terminal: selected government analytics only
PYTHONPATH="$PWD/src" .venv/bin/python -m saakshya.analytics.worker \
  --db sqlite:///var/live.db --cameras cam06

# Offline diagram/report regeneration and final pack assembly
PYTHONPATH="$PWD/src" .venv/bin/python tools/demo/render_diagrams.py --out var/demo/diagrams
PYTHONPATH="$PWD/src" .venv/bin/python tools/reports/scale_load_test.py --out reports/SCALE_80K_LOAD_TEST.md
PYTHONPATH="$PWD/src" .venv/bin/python tools/demo/build_submission_pack.py
```

Check the active media-policy label, selected AI coverage and source health
before presenting. Re-stamp scale figures in the HLD/checklist if the load test
is rerun. The pack builder prints film durations using ffprobe; retain that
build output and confirm every required file is present. Review the PDF and
films after rebuilding; the index alone is not a pack validation.

## Delivery and final checks

Upload the films as unlisted videos, or share the pack through Drive/OneDrive
with viewer access. Check links from a signed-out browser. Confirm the current
portal deadline separately. Any optional screening account should be scoped
read-only, with its credentials delivered separately.

After the **last live demo**, revoke supervisor/admin tokens and rotate the
Sentinel credentials. Never upload environment files, token files, database
connection secrets, cookies or stream credentials. The final operator must
complete revocation; this offline docs lane does not change credentials.
