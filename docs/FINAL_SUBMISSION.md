# SAAKSHYA — authoritative final submission index

Upload `var/demo/SUBMIT/`, assembled by `tools/demo/build_submission_pack.py`.
This index supersedes older submission/upload pages. File names and required
status below follow that builder’s `ITEMS`; optional files must be checked for
presence in its build output. Do not infer that an index entry proves a file
has been rebuilt.

## What to upload and what it proves

| Pack file | Status | Evidence / purpose |
|---|---|---|
| `00_SUBMISSION_INDEX.md` | Required | This authoritative index |
| `00_CHECKLIST.md` | Required | Final checks and limitations |
| `01_SAAKSHYA_deck.pptx`, `01_SAAKSHYA_deck.pdf` | Required | Model justification, workflow, analytics, watchlist, technologies, deployment and benefits |
| `02_HLD.md` | Required | Technical proposal; portal headings mapped to HLD sections |
| `02_HLD_diagrams.pdf` | Optional in builder; include when present | Architecture, authorisation, evidence and capability diagrams, plus the statewide architecture and one-read data flow (HLD §21) |
| `02_SECURITY.md` | Optional in builder; include when present | Application controls and deployment security boundaries |
| `02_STATEWIDE_ARCHITECTURE.md` | Required | DESIGNED statewide target architecture (40 cells, 6 regions, state + DR) with its MODELLED capacity and binding-constraint analysis; summarised in HLD §21, reproduced by `tools/sizing/capacity_model.py` |
| `03_own_feed.mp4` | Required | Onboarding, own-feed detection, representative watchlist, automatic alerts and evidence; 2:53 (`var/demo/own_feed.mp4`, ffprobe) |
| `04_government_feed.mp4` | Required | **5 m 40 s** · 2560×1440 · 30 fps · narrated and captioned; recorded on the live government grid on 28 Sep 2026, 12:41–12:47 IST. Opens on the OPTIMIZED VIEW wall with the live count measured on screen (8 of 30 at the opening, 6–13 across the wall beats), then all thirty in the CONTROL ROOM, a focused live government camera with its intelligence panel, analytics, cam12 person detections and the demonstration restricted-zone rule, the government ANPR gallery, designated vehicle `GJ11S7924` (SINGLE-CAMERA, cam06), GIS, the trace report, the ANPR CSV, evidence, system status and the Model 1 registry as estate administrator. The administrator → officer handoff is shown in the own-feed film. |
| `04_government_feed_1080p.mp4` | Optional | The same take re-encoded to 1920×1080 |
| `04_government_feed_anpr_report.csv` | Required | 1,101 government reads · 264 distinct plates · 9 cameras, government cameras only (`/reports/anpr.csv?reads=all&domain=GOVERNMENT`): 901 reads to the 24 Sep snapshot (earlier recogniser) and 200 read live on cam06 during the 28 Sep recording session by the current recogniser (`ocr: awiros-anpr-ocr` in each row's model provenance). Columns: plate, camera, UTC/IST timestamps, votes, confidence, confirmation, observation and evidence ids. |
| `05_MODEL1_GAP_ANALYSIS.md` | Required | Measured registry completeness; count belongs to that report’s snapshot |
| `05_REGISTRY_API.md` | Required | Registry API contract |
| `05_sample_camera_metadata.csv` | Required | Exported camera metadata sample, not proof of live sessions |
| `05_SCALE_80K_LOAD_TEST.md` | Required | MEASURED synthetic registry/GIS load; no statewide live video or AI test |
| `05_ADAPTERS.md` | Required | Model 3 adapter protocol, implementations and limits |
| `05_FEDERATED_ANALYTICS_REPORT.md` | Required | Federated metadata analysis with source/truth labels; DEMO adapters distinguished |
| `06_designated_vehicle_trace_report.html` | Optional in builder; include when present | `GJ11S7924` on cam06 only: government SINGLE-CAMERA evidence |
| `06_own_feed_trace_report.html` | Optional in builder; include when present | `GJ18JX7786`, C-014 then C-021: CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION |

The own-feed film was recorded on 24 September with Apple Vision. Its footage
read is historical recogniser output; the controlled multi-camera trace uses
the separate fictional plate above. Submitted code now uses the Indian-trained
recogniser; its evaluation is `var/reports/ocr_indian_eval.json`, not the film.

The earlier government take was also recorded on 24 September with earlier
recognisers; the existing CSV contains reads from 2–21 September. It currently
has 901 reads, 178 distinct marks and 9 cameras (counted with `csv.DictReader`
from `var/demo/government_feed_anpr_report.csv` on 28 September). These are
historical report statistics, not claims about the replacement take. Confirm
the replacement film’s recogniser provenance and rebuild its output report
before upload. Government evidence does not establish a cross-camera route. The snapshot has
474 confirmed read rows representing 97 distinct confirmed plates (at least
two agreeing frames); see `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md` for SQL.

**Older sealed-still limitation.** A content hash verifies unchanged bytes,
not that the image shows the vehicle named by its plate record. The older
worker sealed the frame in hand when a track closed; that frame can show a
different vehicle. Treat older stills as requiring visual/source verification,
including those in historical trace reports and films. Since commit `672a2a0` the worker
seals the frame each plate was best read from, so new captures show the read
vehicle's frame; stills sealed before it are unchanged. See `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`.

## Requirement coverage (official FAQ Q24, Q29–Q36)

| Requirement | Where the judge can inspect it |
|---|---|
| Model justification, overview, features (Q29) | Presentation; `02_HLD.md` §§1–3; hybrid source paths below |
| Architecture and diagrams (Q24/Q30) | `02_HLD.md` §§3–4, §6, §21; `02_STATEWIDE_ARCHITECTURE.md`; `02_HLD_diagrams.pdf` — include the diagram PDF even though the builder treats it as optional |
| IP/analog, multi-vendor cameras/VMS (Q30) | HLD §10, §13; `05_ADAPTERS.md` — distinguish direct integration from federation |
| Dispersed sites, edge/central split, low bandwidth (Q30/Q35) | HLD §§6, 20.1, 20.4, 21 |
| ANPR and cross-camera tracking (Q24/Q30) | HLD §§4.2–4.5, 11; government SINGLE-CAMERA and controlled own-feed trace reports above |
| Privacy, RBAC, audit and security (Q24) | HLD §§4.8, 18; `02_SECURITY.md` |
| Department technical inputs (Q24/Q30) | HLD §13, including Home/Police, Food & Civil Supplies, RTO and sandbox departments |
| Compute/GPU sizing and costs (Q24/Q35) | HLD §§17, 20.2–20.3, 20.8–20.9, 21; synthetic registry load report |
| Hot/warm/cold retention, scaling, monitoring, HA/backup/DR (Q35) | HLD §§15, 20.5–20.7, 21; assumptions and untested deployment work labelled |
| Phased statewide rollout (Q35) | HLD §§14, 16 |
| Working software films and timestamped output (Q31–Q33) | Own-feed film, final government film and ANPR CSV above; no mock-ups, animations or concept films satisfy these requirements |
| Delivery and completeness (Q34/Q36) | Pack inventory above; signed-out viewer-link checks below |

Government analytics evidence is summarised in
`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`: vehicle and person detection were
measured across historical government observations; restricted-zone reporting
uses an administrator-created demonstration rule on cam12. There are no
government appearance embeddings or government cross-camera plate matches.
This does not establish completion of the moving-vehicle test across multiple
government cameras (FAQ Q27–Q28); the multi-camera evidence is controlled own feed.

## Claims to keep separate

Model 1 is compulsory: both source paths register identity, GIS and governance
there. **Model 2 connects directly** to reachable cameras/NVRs or departmental
systems over RTSP/ONVIF, without a federation middleware layer. **Model 3 uses
VMS federation middleware** between departmental VMS APIs/SDKs and the unified
platform. Transport adapters alone do not prove departmental VMS federation.
The connector contract and DEMO/TEST implementations are in `docs/ADAPTERS.md`;
no live departmental VMS integration is claimed. Selected central analytics
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
- **MEASURED:** government designated vehicle `GJ11S7924` has 52 stored reads
  on cam06; `GJ38BH5815` is `evaluation_designated`, not stolen. Read-only SQL
  and the active watchlist snapshot are in `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`.
- **MEASURED:** local load began with 50 streams and ended with 44 streaming
  and 6 down, with 36 open failures and no decoder errors
  (`var/reports/camera_load.json`). No recovery is claimed.
- **MEASURED:** 1,331.7 B per serialised observation
  (`var/reports/bandwidth.json`). **MODELLED:** ~400 B compact payload.
  Sizing uses the measured row at a pessimistic 3,000 observations per
  camera-hour, batch-compressed 8.0× (`reports/measure_compression.json`);
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
investigation services. Adaptive scheduling changes cadence, not which cameras
receive inference (`runtime/inference_scheduler.py`). Coverage is “N of M
camera(s) with a stream under analysis” (`command/summary.py`).

The default is **4 deep-inference slots, prioritised by measured capability**
(VERIFIED in `src/saakshya/analytics/worker.py`, `SAAKSHYA_AI_CAMERA_LIMIT`).
At worker boot, stream-capable enabled cameras are ranked GOOD > DEGRADED >
UNKNOWN > UNSUITABLE by ANPR grade; ties use camera id. Assignments do not
rotate at runtime. This configured default is separate from the historical
four-camera measurement in `reports/SCALE_80K_LOAD_TEST.md`.
`command/summary.py` reports “N of M camera(s) with a stream under
analysis”.

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
