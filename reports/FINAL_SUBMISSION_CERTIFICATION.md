# Final submission certification — 28 September 2026

What was checked before upload, and what each claim rests on. Categories are
kept apart: **MEASURED** (a file or query produced the number), **VERIFIED**
(checked in code or tests), **MODELLED** (arithmetic from stated inputs),
**DEMO** (controlled or synthetic material, labelled as such), **DESIGNED**
(specified, not built or not run at scale), and **EXTERNAL SANDBOX
VARIABILITY** (the shared Sentinel sandbox, outside this project's control).

## Submission directory

`/Users/earther/Desktop/Gujarat CCTV/saakshya/var/demo/SUBMIT/` — 19 files,
337 MB, built by `python tools/demo/build_submission_pack.py`. The index is
`00_SUBMISSION_INDEX.md` (source `docs/FINAL_SUBMISSION.md`). The internal
operator checklist is no longer shipped.

| File | Size |
|---|---|
| `00_SUBMISSION_INDEX.md` | 15K |
| `01_SAAKSHYA_deck.pdf` | 13M |
| `01_SAAKSHYA_deck.pptx` | 17M |
| `02_HLD.md` | 110K |
| `02_HLD_diagrams.pdf` | 704K |
| `02_SECURITY.md` | 12K |
| `02_STATEWIDE_ARCHITECTURE.md` | 57K |
| `03_own_feed.mp4` | 94M |
| `04_government_feed.mp4` | 152M |
| `04_government_feed_1080p.mp4` | 60M |
| `04_government_feed_anpr_report.csv` | 218K |
| `05_ADAPTERS.md` | 17K |
| `05_FEDERATED_ANALYTICS_REPORT.md` | 2.7K |
| `05_MODEL1_GAP_ANALYSIS.md` | 2.9K |
| `05_REGISTRY_API.md` | 7.1K |
| `05_SCALE_80K_LOAD_TEST.md` | 2.5K |
| `05_sample_camera_metadata.csv` | 9.3K |
| `06_designated_vehicle_trace_report.html` | 408K |
| `06_own_feed_trace_report.html` | 9.6K |

## Films (MEASURED, ffprobe and extracted frames)

| Film | Duration | Format | Checked |
|---|---|---|---|
| `03_own_feed.mp4` | 2:53 (173.5 s, 5,205 frames) | H.264 2560×1440, 30 fps, narration | Under the 3-minute cap. Video beats move; full-frame freezes are static UI screens. Heads blurred (frames inspected). |
| `04_government_feed.mp4` | 5:40 (339.97 s, 10,199 frames) | H.264 2560×1440, 30 fps encode, narration + captions | Recorded live 28 Sep 12:41–12:47 IST. No black segments; the first 175 s (live government video) contain no freeze ≥ 8 s. Opens on moving government tiles with the measured count on screen. |
| `04_government_feed_1080p.mp4` | 5:40 | H.264 1920×1080 | Same take. |

The government film shows: the OPTIMIZED VIEW wall (8 of 30 live at the
opening, 6–13 across the wall beats), all thirty in the CONTROL ROOM, a
focused live camera with its intelligence panel, analytics, cam12 person
detections and the demonstration restricted-zone rule, the government ANPR
gallery, the designated stand-in `GJ11S7924` (SINGLE-CAMERA), GIS, the trace
report, the ANPR CSV, evidence, system status and the Model 1 registry as the
estate administrator. It does **not** show an onboarding action, the
administrator's refused search or the handoff; the own-feed film shows form
onboarding and the handoff. The screen was captured by CDP screencast and
encoded at 30 fps.

## Measured government result

- **Live session, 28 Sep 11:15–12:53 IST (MEASURED, read-only SQL):** the four
  deep-inference slots (cam06, cam12, cam10, cam08) wrote 4,465 government
  observations; 200 plate reads (124 distinct plates), all cam06, by the
  current recogniser (`ocr_model = awiros-anpr-ocr` in the CSV). 21 of the 200
  fall inside the filmed take.
- **Snapshot to 24 Sep 16:10 IST (MEASURED):** 1,155,325 government
  observations; persons on all 30 cameras, vehicles on 29; 901 plate reads,
  178 distinct plates, 97 confirmed (≥ 2 agreeing frames), 9 cameras.
- **Film CSV (MEASURED):** 1,101 government reads = 901 + 200; 264 distinct
  plates; 9 cameras; no own-feed or synthetic rows (`domain=GOVERNMENT`).
- **Designated stand-in:** `GJ11S7924`, chosen by the team from its own cam06
  reads on 20 Sep (not organiser-issued); 57 reads, all cam06. No plate was
  read on two government cameras: government evidence is single-camera.
- **Live availability (EXTERNAL SANDBOX VARIABILITY, measured during the test
  window):** 6–13 of 30 government cameras delivered advancing video at once;
  18 advanced at some point in one five-minute preflight. The organisers state
  there is no fixed participant-facing session limit; these are measurements,
  not a limit.

## AI result

- Deep inference runs in 4 slots (`SAAKSHYA_AI_CAMERA_LIMIT`), assigned at
  worker boot by measured ANPR grade or by an explicit camera list, not rotated;
  the live worker samples at a fixed interval (VERIFIED). The adaptive
  scheduler is built and tested in the certification harness; live-worker
  wiring is DESIGNED.
- Statewide sizing is MODELLED from measured unit costs
  (`tools/sizing/capacity_model.py`, `reports/capacity_model.json`): inference
  compute is the only resource bought in proportion to cameras analysed; the
  camera-driven non-compute resources keep ≥ 5× throughput headroom at 80,000
  cameras, with the exceptions and pessimistic cases stated in
  `docs/STATEWIDE_ARCHITECTURE.md`. Kafka, gateway-session, TURN and
  data-centre GPU capacities are ASSUMED and are Phase 1 gates.
- The multi-camera route `GJ18JX7786` (C-014 → C-021) is a **SYNTHETIC
  RENDERED TEST CORPUS** — route logic on computer-rendered clips, not camera
  footage (DEMO).

## Tests and scans

- Full suite after every merge, at `1313905` (`python -m pytest -q`, whole
  `tests/`): **1,493 passed, 20 skipped, 0 failed**, 28 min. The takeover
  baseline at `b5a21c8` was 1,375 passed; the 118 added tests pin this
  session's fixes.
- Secret scan (`tools/verify/secret_scan.py`): **PASS**, 1,058 tracked files
  and full history. The pack's text files contain no token, key, bearer or
  private-key pattern and no personal e-mail address. `auto.key` (untracked,
  gitignored, mode 600) and `.env.local` are not in the pack.
- The sandbox host appears in `05_sample_camera_metadata.csv` stream URLs,
  without credentials.

## Red team (four lenses; claims, consistency, coverage by agents; security by the primary)

48 findings. Verified and fixed: the synthetic route mislabelled as own-feed;
stale index text about a replacement take; "200 reads in the film" (21);
the stand-in's attribution; older sealed stills shown as verified in the trace
report (now cautioned, post-fix stills first); "never filed as stolen" (one
representative stolen-vehicle entry exists); a 30/30 screenshot of cached
stills (replaced by the dated 28 Sep control-room still); adaptive-cadence
wording; compression and spatial-query figures; the government CSV's missing
provenance column (`ocr_model` added); the Model 3 report built from the demo
store (regenerated from the government store); the internal checklist shipped
to judges (removed). Open, stated rather than fixed: the government film has
no onboarding action; the pack does not carry the raw evidence JSON files (the
repository does — supply its link, FAQ Q34); the deck is raster-only.

## Known external limitations

- From 28 Sep 12:57 IST the sandbox returned `401 Unauthorized` to this
  project's grid credentials (RTSP and WHEP). No further live recording was
  possible after the submitted take.
- Sandbox fan-in varies with shared load (above).

## Before upload — for the team

1. Host the films (unlisted YouTube or Drive/OneDrive "anyone with the link").
2. Supply the repository link if you want judges to see the cited evidence files.
3. Rotate the Sentinel grid credentials if not already done, and revoke or let
   expire the three one-day API tokens minted on 28 Sep for the recordings
   (`adm.live`, `insp.live`, `sup.live`; `tools/admin/users.py`).
4. Re-run `python tools/verify/secret_scan.py` on anything attached outside
   the pack.
