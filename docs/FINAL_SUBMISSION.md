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
| `02_HLD_diagrams.pdf` | Optional in builder; include when present | Architecture, authorisation, evidence and capability diagrams |
| `02_SECURITY.md` | Optional in builder; include when present | Application controls and deployment security boundaries |
| `03_own_feed.mp4` | Required | Onboarding, own-feed detection, representative watchlist, automatic alerts and evidence; 2:53 (`var/demo/own_feed.mp4`, ffprobe) |
| `04_government_feed.mp4` | Required | Government viewing, selected-camera analytics and designated-vehicle SINGLE-CAMERA evidence; **re-recorded — duration stamped at pack build** |
| `04_government_feed_1080p.mp4` | Optional | Alternate government film encode; verify it is from the final take |
| `04_government_feed_anpr_report.csv` | Required | Detected marks with camera, UTC/IST timestamps, votes, confidence and evidence ids; verify against the final film/store |
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
before upload. Government evidence does not establish a cross-camera route.

## Claims to keep separate

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
  Sizing uses the measured row; both daily/storage cases are in `docs/SCALE_MODEL.md`.
- **MEASURED:** laptop GPU benchmark had matching observation counts but no
  plates on either device (`var/reports/pipeline_device.json`); it predates
  the current recogniser. GPU pool capacities and district deployment are
  **MODELLED/SIZED**, not measured cluster results.
- **DESIGNED:** statewide rollout, distributed HA/DR, retention tiers and
  authorised government database integrations. FRS is designed and gated.

Current demonstration hardware limits simultaneous deep-inference concurrency.
Analytics workers scale horizontally, so additional GPU nodes raise concurrent
inference throughput without redesigning ingest, event, watchlist, GIS or
investigation services. Adaptive scheduling changes cadence, not which cameras
receive inference (`runtime/inference_scheduler.py`). Coverage is “N of M
camera(s) with a stream under analysis” (`command/summary.py`).

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
