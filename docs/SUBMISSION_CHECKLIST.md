# Internal final submission checklist

Operator-only source document; excluded from the submission pack.

Last reconciled 28 September 2026. The authoritative upload inventory and
commands are in [FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Counts below belong
to their named snapshot, not the current runtime estate. The government film
was recorded live on 28 September 2026 (5 m 40 s).

## 1 · The four required items

| # | What the challenge asks for | File | Verified |
|---|---|---|---|
| 1 | Solution presentation | `var/demo/SAAKSHYA_deck.pptx` and `var/demo/SAAKSHYA_deck.pdf` | Generated deck, 16:9, rendered from the repository (`tools/demo/render_submission_deck.py`) so no claim lives only on a slide. Adds the measured GPU speed-up with its parity check, the vehicle trace report, the evidence chain and own-feed screens from the current build; the films page reads each film's length off the file. Upload the PPTX if the field wants PowerPoint; attach the PDF as well. |
| 2 | Technical proposal / high-level design | `docs/HLD.md` (§1–21) plus `var/demo/diagrams/` | §4.2 the models and why each (tiled plate search, on-device OCR, position typing, restricted-zone rules), §4.5 the printable trace, §4.9 the Gemini copilot over all four models with its gates, §15 disaster recovery, §16 statewide rollout with exit gates, §17 the cost model with **S measured** (2.0× whole pipeline on a laptop GPU, 3.4× detector; equal observation counts but no plates in the pipeline sample), §18 the cybersecurity architecture, §19 the claims this proposal declines to make. |
| 3 | Demo video — own feed, **maximum 2–3 minutes** | `var/demo/own_feed.mp4` | **2 m 53 s** · 2560×1440 · 98 MB · narrated, captioned. Eleven beats, all driven cleanly. Licensed Mumbai street footage with heads blurred. An estate administrator onboards a camera through the portal form (validated before it writes) and hands over to the investigating officer. Both feeds play at 30 fps with this platform's boxes on every frame and plates drawn once the vote holds; the live AI worker analyses them on the GPU during the take (AI ACTIVE · OCR ACTIVE, measured inference figures on screen). MH02GB4920 (historical Apple Vision output), read off the footage and agreed across 267 frames, is searched and shown CONFIRMED BY PLATE. The watchlist hit and its trace report are on fictional plates. |
| 4 | Demo video — government feed, with plate/timestamp output report | `var/demo/government_feed.mp4` + `var/demo/government_feed_anpr_report.csv` | **5 m 40 s** · 2560×1440 · encoded 30 fps (screen captured at 6.2 fps, `var/demo/gov_take7/capture.json`) · narrated and captioned; recorded on the live government grid on 28 Sep 2026, 12:41–12:47 IST. Opens on the OPTIMIZED VIEW wall with the live count measured on screen (8 of 30 at the opening, 6–13 across the wall beats), then the thirty-tile CONTROL ROOM layout (12 of 30 live in this recording), a focused live government camera with its intelligence panel, analytics, cam12 person detections and the demonstration restricted-zone rule, the government ANPR gallery, team-chosen stand-in `GJ11S7924` (SINGLE-CAMERA, cam06), GIS, the trace report, the ANPR CSV, evidence, system status and the Model 1 registry as estate administrator. This shows the result of government onboarding, not an onboarding action; bulk-validation, administrator-refusal and handoff beats were not filmed. The own-feed film shows single-camera form onboarding and the administrator → officer handoff. CSV: 1,101 government reads · 264 distinct plates · 9 cameras, government cameras only (`/reports/anpr.csv?reads=all&domain=GOVERNMENT`): 901 reads to the 24 Sep snapshot (earlier recogniser) and 200 read live on cam06 during the 28 Sep session (11:15–12:53 IST) by the current recogniser. The appended CSV `ocr_model` column uses each observation's `model_versions.ocr`, or `earlier` when absent; the session rows have `awiros-anpr-ocr`. Team-chosen stand-in `GJ11S7924` (not organiser-issued), cam06 only: SINGLE-CAMERA evidence (`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). The prior take used earlier recognisers; do not attribute its reads to the current Indian recogniser. |

The recorder refuses to finish an own-feed film over three minutes rather than
producing something an assessor will have cut off. That check passed.

## 2 · Model 1 deliverables

| Named deliverable | File | What it actually contains |
|---|---|---|
| Registry gap analysis | `reports/MODEL1_GAP_ANALYSIS.md` | Historical registry snapshot in that report; evaluation baseline and operator additions are separate (`FINAL_SUBMISSION.md`). Counted in SQL across the whole registry — not sampled. Names the missing fields and says what each one blocks; use that report’s dated denominator. |
| Registry API documentation | `reports/REGISTRY_API.md` | Regenerated offline from this worktree’s OpenAPI schema; verifies the declared contract without running a server or exercising live endpoints. |
| Sample onboarded camera-metadata dataset | `reports/sample_camera_metadata.csv` | Snapshot rows and columns from the registry's own export, which round-trips back into `POST /registry/cameras/import.csv`. |
| Scalability and load test, ~80,000 cameras | `reports/SCALE_80K_LOAD_TEST.md` | Measured, not modelled: 80,000 synthetic camera rows onboarded in 1.388 s (`reports/SCALE_80K_LOAD_TEST.md`) (57,647/s), gap analysis over all of them in 181.7 ms, single lookup 0.69 ms, 58.05 MB on disk. Followed by a section on what those numbers do **not** prove. |

## 2b · A folder you can drag to Drive

`var/demo/SUBMIT/` holds every file named above, numbered in submission order.
Rebuild it with:

```
python tools/demo/build_submission_pack.py
```

Everything is hardlinked, so a regenerated report cannot leave a stale copy
behind and the folder costs no extra disk. It refuses with a non-zero exit if a
required artifact is missing, because a pack quietly missing the
government-feed report is worse than no pack. It was assembled by hand once and
drifted the first time a report was regenerated.

```
00_SUBMISSION_INDEX.md
01_SAAKSHYA_deck.pptx                    01_SAAKSHYA_deck.pdf
02_HLD.md   02_HLD_diagrams.pdf   02_SECURITY.md
02_STATEWIDE_ARCHITECTURE.md
03_own_feed.mp4                          2 m 53 s · 2560×1440
04_government_feed.mp4                   5 m 40 s · 2560×1440 · encoded 30 fps, captured 6.2 fps
04_government_feed_1080p.mp4             5 m 40 s · 1920×1080 (same take)
04_government_feed_anpr_report.csv       1,101 government reads · 264 plates · 9 cameras
05_MODEL1_GAP_ANALYSIS.md   05_REGISTRY_API.md
05_SCALE_80K_LOAD_TEST.md   05_sample_camera_metadata.csv
05_ADAPTERS.md   05_FEDERATED_ANALYTICS_REPORT.md
06_designated_vehicle_trace_report.html  GJ11S7924: cam06 only, SINGLE-CAMERA (57 reads through the 28 Sep session)
06_own_feed_trace_report.html            GJ18JX7786: C-014 then C-021; SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage
```

Ignore the older `var/demo/PORTAL_PACK/` and `PORTAL_PACK.zip` — they are the
14 September artifacts.

## 3 · Before you upload

- [ ] **Revoke supervisor/admin tokens after the last live demo.** A working token was pasted into
      `tools/recorder/record_full_demo.py` during development. It is gone from
      the working tree and from history — `tools/verify/secret_scan.py` passes
      on its recorded scan; run it again on the final tree — but the credential is
      valid until the account that issued it is disabled. Disabling kills
      *every* token for that user, including the one the recorders use, so
      sequence it last:

      ```
      .venv/bin/python tools/admin/users.py --db sqlite:///var/live.db disable --user supervisor.live
      .venv/bin/python tools/admin/users.py --db sqlite:///var/live.db add     --user supervisor.live --role SUPERVISOR --name "Supervisor (live grid)"
      .venv/bin/python tools/admin/users.py --db sqlite:///var/live.db token   --user supervisor.live --days 7
      ```

      `add` re-enables the account; `token` prints the replacement once and
      stores only its SHA-256. Put it in a file outside the repository.
- [ ] **Rotate the Sentinel grid credentials.** They were typed into a chat
      transcript. They live only in `.env.local` (mode 600, gitignored), but a
      credential that has been pasted anywhere should be treated as exposed.
- [ ] **Run the secret scan once more** on whatever you are about to attach:
      `python tools/verify/secret_scan.py`
- [ ] **Host the two films.** Unlisted YouTube, or Drive/OneDrive with "anyone
      with the link can view". Nothing in this repository can do this for you,
      and nothing in it has been given portal credentials.
- [ ] **Confirm the current portal deadline through the organisers.**
- [ ] **Do not attach** `.env.local`, any `*-token.raw`, or anything under
      `var/run/`.

## 4 · What to say plainly if asked

These are the honest limits. Stating them first is cheaper than being caught
by them in questions.

- **The AI plane runs on one laptop.** The detector and the plate recogniser
  use the machine's GPU (Apple MPS); plate detection stays on CPU. Measured on the same
  2560×1440 frames, before the Indian recogniser replaced the CPU one: the
  whole per-frame pipeline 598 → 293 ms (2.0×), the detector alone
  448 → 133 ms (3.4×), with matched detector boxes; the pipeline sample
  had the same 67 observations and no plates on either device
  (`var/reports/pipeline_device.json`, `detector_device.json`). The recogniser
  on its own takes 6.6 ms a plate batched on the GPU against 50 ms on one CPU
  core (`var/reports/ocr_indian_eval.json`); the whole-pipeline figure has not
  been re-measured with it. In the own-feed
  film the live worker analyses both feeds at about 2 frames per second each —
  a sampling policy, not a ceiling. The earlier four-camera government figure
  (~1.4 fps each, P50 ~170 ms) was CPU-only. Statewide inference needs
  data-centre GPU capacity; HLD §17 shows how the target accelerator's speed-up
  is measured with the same command, with MODELLED/SIZED GPU pools and assumed unit prices in HLD §20.8.
- **94% of registry metadata is unpopulated** on five fields. That is the point
  of the gap report rather than a defect in it: the platform holds what
  departments have supplied and names what they have not, and it does not
  invent a value to fill a column.
- **The 264 plates in the delivered CSV are distinct marks on 9 cameras, with zero exact
  cross-camera repeats.** A vehicle traced from one government camera to
  another is not something this estate has yet shown. The separate route-logic
  example is a SYNTHETIC RENDERED TEST CORPUS, not camera footage. `docs/HLD.md`
  §19 states the same thing.
- **Footage published here has heads blurred, without a face detector.** The
  person detector's boxes, found on the whole frame and on overlapping tiles,
  have their top quarter pixelated and held for three frames either side.
  Checked by eye; a person the detector never found is not blurred, and at the
  distances in these clips such a figure is a few pixels high.
- **Plates on the government grid are hard.** Every government view is graded
  unsuitable or unknown for plate reading from its own stream, and no plate in
  the replayed window repeats across two government cameras, so a
  cross-camera government route cannot be shown - that is the data, not the
  platform. Route logic is shown only on the SYNTHETIC RENDERED TEST CORPUS,
  not camera footage; no real multi-camera trace is available. On the own footage, marks are now read by an
  Indian-trained recogniser and published only when a track's frames agree.
  On the 57-second queue clip the final pipeline publishes 56 marks: 40 checked
  correct by eye, 4 wrong (each one character from a real plate), 12 not
  settled by a crop. **The own-feed film and prior government take were recorded on 24 September
  with the previous recogniser (Apple Vision)**; their plates come from that run, where
  misread duplicates of one car on a fragmented track existed (MN22GB4920
  beside MH02GB4920, 3 votes against 267).
- **Relay policy is local.** The relay is opt-in. Its government-camera cap
  defaults to 15, configurable through `SAAKSHYA_RELAY_MAX_CAMERAS`; 0 disables
  the cap (`src/saakshya/live/relay.py`). That default reflects one test window,
  not a Sentinel limit or universal bridge maximum. Current viewing has two
  policies: CONTROL ROOM up to 30 / OPTIMIZED VIEW at most 12. See
  `docs/SENTINEL_SUPPORT_CLARIFICATION.md` for the organisers’ clarification.
- **The restricted-zone rule on the government grid is a demonstration rule**,
  set by the estate administrator for this evaluation and labelled so. The
  entries it reports are real sightings on that camera.
- **The films were recorded on SQLite.** PostgreSQL 18 + PostGIS 3.6 is
  exercised, not only designed: the government store (1.19M rows) was copied
  with every table's count matching and both hash chains verifying, the API
  served it (`var/reports/store_engines.json`), and `tests/postgres/` runs the
  main flows there. What is not claimed is a PostgreSQL deployment at district
  scale, replication, or failover.
- **ONNX Runtime had been sending Microsoft usage telemetry** from the
  development machine (it is on by default in 1.29, and it was found from a
  crash report). It is switched off at import now; say so if asked about
  outbound calls, and say a deployment should also deny egress at the host.
- **Two government cameras show corrupted colour** in the film — Dethali Char
  Rasta green, O.N.G.C. Office orange. Both artifacts are present in the
  upstream feed; they are not produced by anything here.
- **The shared sandbox's availability varies with load.** After repeated
  back-to-back recordings it refused new sessions for roughly 45–60 minutes.
  The organisers have confirmed in writing that there is no fixed
  participant-facing session or rate limit, that availability depends on
  overall sandbox usage and gateway load, and that this variation is not a
  limitation of our bridge; they recommend opening only the streams actually
  needed, with backoff, per-camera isolation and staggered connections, which
  is what the platform does (`docs/SENTINEL_SANDBOX.md`, "Concurrent access").
  The media hub now opens a government camera only while something needs it,
  where it used to hold all thirty. If you intend to show the live wall on
  stage, do not re-record beforehand.
- **Nothing here is production ready, legally admissible, or tested at 80,000
  cameras end to end.** The registry/GIS plane was load-tested with 80,000 synthetic camera rows
  (`reports/SCALE_80K_LOAD_TEST.md`). The video and
  inference planes were not, and saying otherwise would be false.

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
surfaces, subject to source availability. `AdaptiveInferenceScheduler` implements
priority cadence and is VERIFIED in the certification harness; `AnalyticsBudget` tier selection is unit-tested. Neither
is wired into the live worker (DESIGNED integration). The worker samples at a
fixed interval (`SAAKSHYA_AI_SAMPLE_S`, default 0.20 s); it does not rotate cameras.
GPU pool capacities in this proposal are **MODELLED/SIZED**, not measured cluster throughput.

**Older sealed-still limitation.** A content hash verifies unchanged bytes,
not that the image shows the vehicle named by its plate record. The older
worker sealed the frame in hand when a track closed; that frame can show a
different vehicle. Treat older stills as requiring visual/source verification,
including those in historical trace reports and films. Since the worker session starting 28 Sep 2026 11:15 IST (commit `672a2a0`), the worker
seals the frame each plate was best read from, so new captures show the read
vehicle's frame; stills sealed before it are unchanged. See `reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`.

## 5 · How to regenerate any of it

```
python tools/demo/record_own_feed.py        --base http://127.0.0.1:8083 --token-file tok.raw
python tools/demo/record_government_feed.py --base http://127.0.0.1:8083 --token-file tok.raw
python tools/reports/gap_analysis.py        --out reports/MODEL1_GAP_ANALYSIS.md
python tools/reports/registry_api_doc.py    --base http://127.0.0.1:8083 --token-file tok.raw
python tools/reports/scale_load_test.py     --n 80000
```

Every artifact in section 1 and 2 is produced by one of these commands. None
was assembled by hand, so none can quietly drift from what the code does.
