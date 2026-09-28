# Final submission certification — 28 September 2026

What was checked before upload, and what each claim rests on. Categories are
kept apart: **MEASURED** (a file or query produced the number), **VERIFIED**
(checked in code or tests), **MODELLED** (arithmetic from stated inputs),
**DEMO** (controlled or synthetic material, labelled as such), **DESIGNED**
(specified, not built or not run at scale), **RECORDED** (government footage
downloaded earlier and replayed, never presented as live) and **EXTERNAL
SANDBOX VARIABILITY** (the shared Sentinel sandbox, outside this project's
control).

## Submission directory

`var/demo/SUBMIT/` — 22 files, 456 MB, built by
`python tools/demo/build_submission_pack.py`. The index is
`00_SUBMISSION_INDEX.md` (source `docs/FINAL_SUBMISSION.md`). The repository's
`submission/` folder carries the same deck, diagrams, reports and CSVs, and
1080p copies of the three films (the 2560×1440 masters stay out of git).

| File | Size |
|---|---|
| `00_SUBMISSION_INDEX.md` | 19K |
| `01_SAAKSHYA_deck.pdf` | 14M |
| `01_SAAKSHYA_deck.pptx` | 18M |
| `02_HLD.md` | 112K |
| `02_HLD_diagrams.pdf` | 721K |
| `02_SECURITY.md` | 12K |
| `02_STATEWIDE_ARCHITECTURE.md` | 58K |
| `03_own_feed.mp4` | 158M |
| `04_government_feed.mp4` | 159M |
| `04_government_feed_1080p.mp4` | 63M |
| `04_government_feed_anpr_report.csv` | 223K |
| `04b_government_tour.mp4` | 63M |
| `04b_government_tour_replay_reads.csv` | 1.8K |
| `05_ADAPTERS.md` | 18K |
| `05_FEDERATED_ANALYTICS_REPORT.md` | 2.8K |
| `05_MODEL1_GAP_ANALYSIS.md` | 3.0K |
| `05_REGISTRY_API.md` | 7.3K |
| `05_SCALE_80K_LOAD_TEST.md` | 2.6K |
| `05_sample_camera_metadata.csv` | 9.5K |
| `06_designated_vehicle_trace_report.html` | 418K |
| `06_own_feed_trace_report.html` | 9.8K |
| `07_LIVE_INTEGRATION_STORY.md` | 12K |

## Films (MEASURED, ffprobe, freezedetect and extracted frames)

| Film | Duration | Format | Checked |
|---|---|---|---|
| `03_own_feed.mp4` | 2:43 (163.0 s, 4,890 frames) | H.264 2560×1440, 30 fps, narration | Recorded 28 Sep. No freeze in the detection beat (42–76 s); the other freezes are static UI screens under narration. The recorder refuses a take if either video stalls for ≥ 1 s or its boxes stop drawing. Heads blurred; street basemap under the route. |
| `04_government_feed.mp4` | 5:40 (339.97 s) | H.264 2560×1440, 30 fps, narration + captions | Recorded **live** 28 Sep 12:41–12:47 IST. Unchanged since the previous certification. |
| `04b_government_tour.mp4` | 15:04 (903.9 s, 27,117 frames) | 1920×1080 in the pack; 2560×1440 master `var/demo/government_tour.mp4` | Recorded 28 Sep on `var/govfilm.db`, a copy of the government store, with Sentinel credentials unset. 49 filmed beats, 2 named skips (no watchlist add/revoke UI), 0 failures (`var/demo/government_tour_20260928_214832/beats.json`). No black segment; freezes only in the first 40 s (sign-in and overview). The wall and focus play **RECORDED** footage labelled `RECORDED · captured 2026-09-15` on every tile. |

## Recorded government footage (RECORDED, MEASURED)

- Source: 12-second clips captured 15 Sep 2026 by
  `tools/demo/capture_live_clips.py` (`var/demo/live_clips/scores.json`).
  15 of them are byte-identical to the capture record; 4 were damaged later
  and 2 were scored unusable at capture; 9 cameras produced no clip.
- `tools/demo/import_gov_clips.py` re-timed each clip at its measured rate
  (frames / 12 s, every frame kept), blurred heads with the production person
  detector, and registered it as `GOVREC-camNN` with source domain
  `ARCHIVAL_REPLAY` in the film store only. The capture date is the download
  date; the cameras' own overlays show June 2026.
- The production pipeline analysed every frame: 3,159 frames, 1,319 tracks,
  1,548 observations, 4 plates in 7 reads, all cam06. By eye, 3 of the 4
  match the plate in the picture; `RJ12J8713` is unverified. cam08's clip is a
  source decode mosaic and is not shown on the wall.
- Replay reads never enter `04_government_feed_anpr_report.csv`; they are in
  `04b_government_tour_replay_reads.csv` with `source_domain = ARCHIVAL_REPLAY`.

## Measured government result (unchanged)

- **Live session, 28 Sep 11:15–12:53 IST:** 4,465 government observations
  from the four deep-inference slots; 200 plate reads (124 distinct plates),
  all cam06, current recogniser; 21 inside the filmed take.
- **Snapshot to 24 Sep 16:10 IST:** 1,155,325 government observations;
  persons on all 30 cameras, vehicles on 29; 901 plate reads, 178 distinct,
  97 confirmed, 9 cameras.
- **Film CSV:** 1,101 government reads = 901 + 200; 264 distinct plates;
  9 cameras; the tour's own export of the same store has the same 1,101 rows.
- **Designated stand-in:** `GJ11S7924`, team-chosen from cam06 reads (not
  organiser-issued); 57 reads, all cam06. No plate was read on two government
  cameras: government evidence is single-camera.
- **Live availability (EXTERNAL SANDBOX VARIABILITY):** 6–13 of 30 advancing
  at once during the test window. Not a limit.

## Defects found and fixed in this final round (VERIFIED, with tests)

- `make serve` sent a broken basemap template (`{z/{x}/{y}.png}`): sh ends
  `${VAR:-default}` at the first `}`. Every map drew over a blank canvas.
- Recorded government tiles decoded but stayed transparent on the wall (the
  WHEP readiness flag was never set for file playback): boxes over black.
- The estate map's "search camera" box had no handler; it now filters the
  map and the registry strip.
- The estate administrator saw an error toast on the estate map: the alert
  layer (no `alert:read` for ADMIN) returned 403 and was toasted as a failure.
- Recorder races (a re-rendered alert queue, a busy search form, hash-only
  role handoffs, a pattern-result selector, the evidence verdict key) and a
  copilot question that exceeded the coordinator's six-step limit.

## AI result

- Deep inference runs in 4 slots, assigned at boot, not rotated (VERIFIED).
- Own-feed plates in the film come from the final pipeline's sidecars
  (Indian-trained recogniser). On the 57 s queue clip the vote published 56
  marks: 40 correct by eye, 4 wrong, 12 unsettled
  (`var/reports/ocr_indian_eval.json`). The film's search returns 23 stored
  `MH02GB4920` reads from the 24 Sep Apple Vision run.
- Statewide sizing is MODELLED (`tools/sizing/capacity_model.py`).
- `GJ18JX7786` (C-014 → C-021) is a **SYNTHETIC RENDERED TEST CORPUS** (DEMO).

## Tests and scans

- Full suite (`python -m pytest -q tests`): **1,582 passed, 20 skipped, 0 failed** (27 min 28 s), 28 Sep 2026, on the code committed with this certification.
- Secret scan (`tools/verify/secret_scan.py`): **PASS**, 1,113 tracked files (including `submission/`) and full history.
- No e-mail address, token or credential pattern in `submission/` or the
  pack's text files (grep, 28 Sep 22:20 IST).

## Known external limitations

- From 28 Sep 12:57 IST the sandbox returned `401 Unauthorized` to this
  project's grid credentials. No live stream was opened after that; the tour
  was made offline from recorded footage.
- Sandbox fan-in varies with shared load.

## Before upload — for the team

1. Host the films (the repository's `submission/films/` has 1080p copies;
   the 1440p masters are in the pack).
2. Rotate the Sentinel grid credentials: a password was pasted into a chat
   on 28 Sep.
3. Revoke or let expire the one-day API tokens minted on 28 Sep:
   `adm.live`, `insp.live`, `sup.live` (live store), `admin.demo`,
   `supervisor.demo` (`var/ownfilm.db`) and `sup.live`, `adm.live`
   (`var/govfilm.db`).
4. Re-run `python tools/verify/secret_scan.py` on anything attached outside
   the pack.
