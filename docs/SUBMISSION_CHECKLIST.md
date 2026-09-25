# Final submission checklist

Written 22 September 2026. Every figure on this page was read off the file it
describes, not carried over from an earlier draft.

Two older pages — `docs/PORTAL_UPLOAD.md` and `docs/SUBMISSION.md` — describe
the artifacts as they were on 14 September and are **superseded by this one**.
They say 54 slides, a 2:47 own-feed film at 1080p, and a government film of
1:37 with zero plates read. None of those three numbers is still true. Do not
quote them on the portal.

## 1 · The four required items

| # | What the challenge asks for | File | Verified |
|---|---|---|---|
| 1 | Solution presentation | `var/demo/SAAKSHYA_deck.pptx` and `var/demo/SAAKSHYA_deck.pdf` | **37 slides**, 16:9, rendered from the repository (`tools/demo/render_submission_deck.py`) so no claim lives only on a slide. Adds the measured GPU speed-up with its parity check, the vehicle trace report, the evidence chain and own-feed screens from the current build; the films page reads each film's length off the file. Upload the PPTX if the field wants PowerPoint; attach the PDF as well. |
| 2 | Technical proposal / high-level design | `docs/HLD.md` (§1–19) plus `var/demo/diagrams/` | §4.2 the models and why each (tiled plate search, on-device OCR, position typing, restricted-zone rules), §4.5 the printable trace, §4.9 the Gemini copilot over all four models with its gates, §15 disaster recovery, §16 statewide rollout with exit gates, §17 the cost model with **S measured** (2.0× whole pipeline on a laptop GPU, 3.4× detector, identical outputs), §18 the cybersecurity architecture, §19 the claims this proposal declines to make. |
| 3 | Demo video — own feed, **maximum 2–3 minutes** | `var/demo/own_feed.mp4` | **2 m 53 s** · 2560×1440 · 98 MB · narrated, captioned. Eleven beats, all driven cleanly. Licensed Mumbai street footage with heads blurred. An estate administrator onboards a camera through the portal form (validated before it writes) and hands over to the investigating officer. Both feeds play at 30 fps with this platform's boxes on every frame and plates drawn once the vote holds; the live AI worker analyses them on the GPU during the take (AI ACTIVE · OCR ACTIVE, measured inference figures on screen). MH02GB4920, read off the footage and agreed across 267 frames, is searched and shown CONFIRMED BY PLATE. The watchlist hit and its trace report are on fictional plates. |
| 4 | Demo video — government feed, **with a report of detected vehicles / plates and timestamps** | `var/demo/government_feed.mp4` + `var/demo/government_feed_anpr_report.csv` | Video **8 m 10 s** · 2560×1440 · 67 MB · narrated, captioned (1080p copy: `government_feed_1080.mp4`, 32 MB). Twenty-two chapters on the organisers' own cameras and store: registry and bulk onboarding validated before it writes, the gap report asked of Gemini, GIS, the administrator refused a plate search, the live wall over direct WebRTC (23 of 30 tiles showing a frame), one camera with the overlay, analytics with a restricted-zone rule, marks with timestamps, the designated vehicle GJ11S7924 traced, followed and printed, alerts, evidence, Gemini over Models 2 and 4, its refusal to fabricate, system health with the federated VMS, the audit log. **One splice, stated:** chapters 18–20 (the three Gemini beats, 55 s) come from the take recorded 80 minutes earlier on the same build, because in the final take the suggestion chips had not drawn when clicked (fixed since). Report: **901 government reads, 178 distinct marks, 9 government cameras, 474 confirmed across frames**, each with UTC and IST time, camera, district, confidence, format check and evidence id. Own-feed rows that the live store also held are excluded. |

The recorder refuses to finish an own-feed film over three minutes rather than
producing something an assessor will have cut off. That check passed.

## 2 · Model 1 deliverables

| Named deliverable | File | What it actually contains |
|---|---|---|
| Registry gap analysis | `reports/MODEL1_GAP_ANALYSIS.md` | 34 cameras onboarded, 18 capacity slots, six departments. Counted in SQL across the whole registry — not sampled. Names five fields at 94.1% unpopulated and says what each one blocks. |
| Registry API documentation | `reports/REGISTRY_API.md` | Generated from the running service's own OpenAPI schema, so it cannot document an endpoint the platform does not serve. |
| Sample onboarded camera-metadata dataset | `reports/sample_camera_metadata.csv` | 34 rows, 27 columns — the registry's own export, which round-trips back into `POST /registry/cameras/import.csv`. |
| Scalability and load test, ~80,000 cameras | `reports/SCALE_80K_LOAD_TEST.md` | Measured, not modelled: 80,000 cameras onboarded in 0.697 s (114,742/s), gap analysis over all of them in 85 ms, single lookup 0.46 ms, 58.01 MB on disk. Followed by a section on what those numbers do **not** prove. |

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
00_CHECKLIST.md
01_SAAKSHYA_deck.pptx                    01_SAAKSHYA_deck.pdf
02_HLD.md   02_HLD_diagrams.pdf   02_SECURITY.md
03_own_feed.mp4                          2 m 53 s · 2560×1440
04_government_feed.mp4                   8 m 10 s · 2560×1440
04_government_feed_1080p.mp4             8 m 10 s · 1920×1080
04_government_feed_anpr_report.csv       901 reads · 178 marks · 9 cameras
05_MODEL1_GAP_ANALYSIS.md   05_REGISTRY_API.md
05_SCALE_80K_LOAD_TEST.md   05_sample_camera_metadata.csv
06_designated_vehicle_trace_report.html  GJ11S7924: 52 reads, 24 sealed stills re-verified
06_own_feed_trace_report.html            GJ18JX7786: C-014 then C-021
```

Ignore the older `var/demo/PORTAL_PACK/` and `PORTAL_PACK.zip` — they are the
14 September artifacts.

## 3 · Before you upload

- [ ] **Revoke the live supervisor token — after your last live demo, not
      before it.** A working token was pasted into
      `tools/recorder/record_full_demo.py` during development. It is gone from
      the working tree and from history — `tools/verify/secret_scan.py` passes
      across 976 tracked files and the full history — but the credential is
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
- [ ] **Confirm the portal dates yourself.** This repository records
      submission closing 15 September 2026 and the on-site event 22–23
      September 2026, read off the official site on 6 September. That is old
      enough to re-check before you rely on it.
- [ ] **Do not attach** `.env.local`, any `*-token.raw`, or anything under
      `var/run/`.

## 4 · What to say plainly if asked

These are the honest limits. Stating them first is cheaper than being caught
by them in questions.

- **The AI plane runs on one laptop.** The detector and the plate recogniser
  use the machine's GPU (Apple MPS); plate detection stays on CPU. Measured on the same
  2560×1440 frames, before the Indian recogniser replaced the CPU one: the
  whole per-frame pipeline 598 → 293 ms (2.0×), the detector alone
  448 → 133 ms (3.4×), with identical outputs
  (`var/reports/pipeline_device.json`, `detector_device.json`). The recogniser
  on its own takes 6.6 ms a plate batched on the GPU against 50 ms on one CPU
  core (`var/reports/ocr_indian_eval.json`); the whole-pipeline figure has not
  been re-measured with it. In the own-feed
  film the live worker analyses both feeds at about 2 frames per second each —
  a sampling policy, not a ceiling. The earlier four-camera government figure
  (~1.4 fps each, P50 ~170 ms) was CPU-only. Statewide inference needs
  data-centre GPU capacity; HLD §17 shows how the target accelerator's speed-up
  is measured with the same command, and does not quote a rupee figure.
- **94% of registry metadata is unpopulated** on five fields. That is the point
  of the gap report rather than a defect in it: the platform holds what
  departments have supplied and names what they have not, and it does not
  invent a value to fill a column.
- **The 178 plates are 178 distinct marks on 9 cameras, with zero exact
  cross-camera repeats.** A vehicle traced from one government camera to
  another is not something this estate has yet shown; the cross-camera trace
  in the own-feed film is on our own corpus, and the film says so. `docs/HLD.md`
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
  platform. Cross-camera tracing is shown on the own/synthetic store and
  labelled as such. On the own footage, marks are read by an on-device text
  recogniser and voted across frames; the ones checked by eye are right, and
  misread duplicates of the same car on a fragmented track exist (MN22GB4920
  beside MH02GB4920, with 3 votes against 267).
- **The local relay can crash-loop.** On this laptop the relay's per-camera
  transcode hit decoder errors and reconnected fast enough that the grid
  counted the dead sessions and refused the account for a while. The
  government film uses direct WebRTC from the grid through the proxy, which
  opens one session per visible tile and decodes nothing locally.
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
- **The upstream grid meters WHEP sessions.** After repeated recording it
  refuses new sessions for roughly 45–60 minutes. If you intend to show the
  live wall on stage, do not re-record beforehand.
- **Nothing here is production ready, legally admissible, or tested at 80,000
  cameras end to end.** The registry plane was tested at 80,000. The video and
  inference planes were not, and saying otherwise would be false.

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
