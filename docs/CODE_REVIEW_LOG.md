# Code Review Log

Historical planning / measurement record. For the current submission use
[FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Current roles: government
`GJ11S7924` on cam06 is SINGLE-CAMERA evidence; own-feed `GJ18JX7786` on
C-014 then C-021 is a CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). Earlier rehearsal plate names,
screenshot counts, timings and dates below belong to their recorded run.
Current wall policy: CONTROL ROOM up to 30 direct WHEP sessions, 400 ms apart;
OPTIMIZED VIEW at most 12, 600 px prefetch, released after 15 s off screen
(`ui/app.js`). Old still-wall descriptions below are historical.


Second-pass review after each substantial change, per the high-assurance
directive. Severity: **P0** catastrophic · **P1** major correctness/security ·
**P2** important · **P3** polish · **NIT** optional.

---

## CR-069 — Object mix on Overview/Analytics (A5 detector classes)
**Date:** 2026-09-06

The live store already held cars, trucks, buses, motorcycles, bicycles and
people from the same detector pass. Overview and Analytics only counted
persons and plates, so A5 "object detection" looked like a missing feature.
It was a missing *display*.

**Fix:** `store.stats()` groups `object_type`; Overview Estate and Analytics
yield print the mix as detector labels, not identity. Quote sheet and
`make daily-live-score` carry the same row. A bicycle or a long stay is not
an intrusion and not a face. Cache-bust `cr069`. Do not restart ingest.

---

## CR-068 — Person long-stay on Overview/Analytics; honest ingest health
**Date:** 2026-09-06

Person dwell was already written (`dwell_exceeded` at 12 s) and shown on a
search row, but Overview and Analytics never counted it, so the estate looked
vehicle-only. `camera_health` persisted STREAMING whenever a worker had ever
decoded a frame, so Overview showed a full wall while the ingest log said
25/30. `last_seen_us` was the health-write clock, not the last frame.

**Fix:** store stats count person long-stay; Overview shift picture and
Analytics yield print it as duration on one camera, never intrusion. Ingest
persists STREAMING only while `stats.state == STREAMING`, and `last_seen_us`
from `last_frame_at`. Status lines name quiet cameras. `make daily-live-score`
reports cross-camera marks. Cache-bust `cr068`. Do not restart ingest to apply
health persist — that waits for the next start. Do not claim a live
multi-camera trail while cross-camera plates remain 0.

---

## CR-065 — Real street map under the estate GIS
**Date:** 2026-09-05

The estate map was a measured graticule. Judges asked to see Gujarat on a
real map. Official Google Maps JS is the preferred basemap when
`SAAKSHYA_GOOGLE_MAPS_KEY` is in the process environment (never the repo).
Without a key, `SAAKSHYA_MAP_TILES` raster tiles (OpenStreetMap for this
demo) are the street layer. Markers, uncertainty rings and trajectories stay
on our canvas. Eleven unlocated cameras are still not invented onto the map.

**Fix:** config advertises `map.google`; CSP widens only when a key is set;
MapView overlays Google or draws OSM tiles; Makefile `live-serve` defaults
OSM tiles. Cache-bust `cr066`. A missing `+` between two string
literals in the evidence loader had made `app.js` unparseable, so the
workspace never booted. Do not restart ingest.

---

## CR-063 — Paper console: first paint, contrast, and populated shots
**Date:** 2026-09-05

The Console v2 chrome was on the live workspace, but Overview, Cameras,
Analytics, Evidence and System screenshots were empty cards: capture waited
for the panel title, not the store, and the first view sat behind GIS extent.
Active sub-nav was white on cream. Live placeholders used ink-faint on a black
frame.

**Fix:** Overview starts without waiting for maps. Empty panels say they are
loading. Sub-nav and still placeholders read on paper. Capture waits for the
shift picture, a searched plate, table rows, ingest stills, the stolen-vehicle
alert, chain verification, and the hybrid-model copy. Cache-bust `cr063`.
Evidence first-paints the health component so the page is not blank while
`/evidence/chain/verify` waits on the live writer (`cr064`).
Do not restart ingest.

---

## CR-062 — Paper console: the briefing-room language
**Date:** 2026-09-05

The workspace opened as a navy engineering surface. The Console v2 brief is
warm paper, terracotta, the Gujarat Police crest the team supplied, a
split-screen sign-in, and pill navigation — a command room, not an IDE.

**Fix:** light theme tokens and chrome follow that brief. Dark theme restores
the navy frame. Sign-in is a full-page gate; Change token keeps the dialog.
Live stills, search, and every number remain the live store. Cache-bust
`cr062`. Do not restart ingest.

---

## CR-061 — Live wall showed "30 cameras" over an empty grid
**Date:** 2026-09-04

`loaders.live` set the camera count from `/gis/cameras`, then awaited
`/gis/health` and `/system/health` before appending a single tile. On the
live store those enrichments are slow. The walkthrough timed out on a
blank LIVE GRID whose header already said 30 cameras. GIS cameras already
carry `state` and `published_marks`.

**Fix:** paint tiles from the GIS list immediately, queue ingest stills,
and apply health / grid-access as they return. Cache-bust `cr061`. Do not
restart ingest.

---

## CR-060 — Overview health waited behind the slow /overview call
**Date:** 2026-09-04

CR-059 added the Shift picture. Health, cases, activity and the map still
started only after `/overview` returned. On the live store that call is
~20 s, so first paint showed a filled Shift picture and empty System
health — and the walkthrough timed out waiting for `.health-row`.

**Fix:** those four panels start with the overview payload, not after it.
Cache-bust `cr060`. Do not restart ingest.

---

## CR-059 — Overview opened as an ops dashboard, not a shift picture
**Date:** 2026-09-04

The landing already asked the right three questions, but a judge's first
paint was six equal cards of machinery. The stolen-vehicle alert, the seven
cameras that published a mark, and "0 ANPR GOOD" were in the cards; they
were not the sentence you could read without hunting.

**Fix:** a Shift picture panel, first and full-width, built only from the
existing `/overview` payload. It names the open alert, how many cameras
published a mark versus how many are graded GOOD for ANPR, and the camera
states (streaming / observed). It does not invent a cross-camera identity
from graph seeds. Cache-bust `cr059`. Do not restart ingest.

---

## CR-057 — Cameras and Live hid published plates behind ANPR UNSUITABLE
**Date:** 2026-09-04

CR-042 split Overview: "cameras that published a mark" vs "cameras graded
GOOD for ANPR". Cameras and the live wall still showed only the grade.
Every tile on this grid is ANPR UNSUITABLE, including cam07 which holds
`GJ1VV0119` and cam06 which loops `GJ32AG0028`. A judge who opens Live
then Find is entitled to see that those cameras published a mark, not to
infer the store is empty of plates.

GIS health had the same class of miss as CR-056: a missing `camera_health`
row was UNKNOWN and the live-tile placeholder said "never ingested".
Cameras with observations are now `OBSERVED`. `/gis/capability` and
`/gis/cameras` carry `published_marks` / confirmed / leads from the live
store, not the capability sample. Cameras gains a "Marks in store"
column; Live chips "N plates in store" next to the grade.

Cache-bust `cr058`. Browser-verified 4 Sep 2026 17:52 UTC against the live
API: Cameras cap-note "7 cameras published a mark in the store"; cam07
shows 12 distinct · 11 confirmed / 4 leads beside ANPR UNSUITABLE; Live
chips "12 plates in store" on cam07 and "7 plates in store" on cam06.
API restart required; do not restart ingest.

Pinned by `test_unsuitable_camera_still_reports_published_marks`,
`test_missing_health_with_observations_is_observed_not_unknown`.

Walkthrough re-recorded 4 Sep 2026 17:56 UTC against `?v=cr058` (13/13
steps driven). Shot 04 shows the Marks in store column; shot 07 chips
plates next to ANPR UNSUITABLE. Silent `var/demo/walkthrough_live.mp4`
(1 min 44 s); narrated `var/demo/walkthrough_live_narrated.mp4` (3 min
35 s, Rishi). Overview Shift picture (CR-059) is not in that film.

---

## CR-056 — "Never ingested" for cameras that have thousands of observations
**Date:** 2026-09-04

Overview System health said **15 never ingested** while those same cameras
held observations (cam07, the designated `GJ1VV0119` camera, among them).
`camera_health` was written only when ingest closed. An unbounded
`--minutes 0` run never closes, so leftover rows from a previous close
stayed STREAMING and the other fifteen were labelled unseen.

**Fix:** `_feed_health` counts observations separately. "Never ingested"
is reserved for cameras with neither a health row nor an observation.
Cameras with observations and no health row are `health_pending` /
Overview `OBSERVED`. Ingest now persists health on the 30 s report as
well as at close — the running process will not pick that up until it is
replaced. Do not restart ingest.

Pinned by `test_feed_health.py`.

---

## CR-055 — Analytics hid plate yield and timebase behind a serial fetch
**Date:** 2026-09-04

Analytics has three panels: capability grades, what the store actually
produced (distinct marks, leads, persons, forensic OCR), and timebase
clusters. The loader awaited `/gis/capability`, then `/overview`, then
`/gis/timebase`. On the live store `/overview` is the slow call. The
walkthrough waited 1.8 s after the click; capability had painted, yield
and clusters were still empty. A judge clicking Analytics sees the same
blank: 0 ANPR GOOD with no 34 marks / 8 leads beside it, and no
GRID cluster even though twelve cameras share a measured window.

**Fix:** the three reads start together. Capability and timebase paint as
each call returns. Yield waits only on the two payloads it uses. The
walkthrough waits for "distinct marks" and a `GRID-` cluster (or the
honest "No cluster established" notice). Cache-bust `cr055`.

Do not restart ingest. `plate_reads` on this process remains 0; the
yield panel still says so.

---

## CR-054 — Walkthrough was a 3 September film of a 4 September product
**Date:** 2026-09-04

`var/demo/walkthrough_live_narrated.mp4` was recorded 3 Sep — before LIVE/STALE
ingest stills, the 19+11 registry strip, forensic OCR on Overview, and the
sixteen-tool copilot. A judge watching the film would not see the product on
the day.

Re-recorded against the live API (13 driven steps, all succeeded): Overview
waits for the observation count and `.health-row`; Analytics waits for
distinct marks and a `GRID-` cluster (CR-055); Live waits for LIVE/STALE
badges; map and copilot are in the film; copilot is last. Silent 1 min 44 s;
narrated 3 min 28 s (Rishi, en_IN, offline). Token from a file, never logged.

---

## CR-053 — `plate_reads` was a table nobody wrote
**Date:** 2026-09-04

Overview's `raw_ocr_read_records` and the forensic schema (`plate_reads`:
every OCR attempt, including rejected format) existed. `Store.add_plate_reads`
existed. Nothing called it. Voted plates landed on observations; the losing
reads died with the `PlateVoter`. The live store correctly showed **0** raw
OCR rows next to dozens of published marks — honest, and incomplete.

**Fix:** on track close, every remaining OCR attempt becomes a forensic row
(valid and rejected). Ingest drains those rows onto the same consumer queue
as observations. Seed, e2e, corpus, intake and load-test persist them too.
The running 30-camera ingest predates the write; the live table stays 0
until that process is replaced. Do not restart ingest for this.

Pinned by `test_forensic_rows_keep_rejected_ocr`,
`test_pipeline_records_rejected_ocr_even_when_no_observation`,
`test_plate_reads_are_stored_and_invalidate_stats`.

---

## CR-050 — Submission report was a 20k slice; looping plates looked like a fleet
**Date:** 2026-09-04

Two jury-visible honesty faults, both the class of miss that disagrees with
Overview on the day:

1. **`detection_report.py` defaulted to 20,000 rows.** `make detection-report`
   would export a newest-first slice of a 440k-row live store and print that
   slice's length as the estate. Summary counts now come from SQL over the
   whole store; CSV default is every observation (`--limit 0`). ANPR
   UNSUITABLE is taken from the ALL time band — listing every band let a
   later NIGHT UNKNOWN overwrite a whole-day UNSUITABLE, so five cameras
   were listed of twenty-eight. Looping reads of one mark collapse to one
   row per camera in the Markdown, with a hit count.

2. **Search treated N hits of one mark as N observations and stopped.** On
   this grid that is looping footage (`GJ32AG0028` on cam06). The payload
   now carries `sighting`: `SINGLE_CAMERA` or `MULTI_CAMERA`. The Find
   panel says "one camera only" rather than looking like a fleet.

Pinned by `test_detection_report.py` and `test_search.py` (single-camera
repeats vs two-camera identity).

---

## CR-051 — Looping plate was a coverage gap from a camera to itself
**Date:** 2026-09-04

`GJ32AG0028` is 38 confirmed reads, all cam06, span 1048 s. Fragment
coalesce (120 s) merged them to two "passes" because one inter-read gap
was 125 s. The remaining cam06→cam06 leg was classified `COVERAGE_GAP` —
"no camera on record could have observed the vehicle" — and scored
LIKELY. That is the opposite of looping footage at one mount.

**Fix:** a same-camera pair is never a coverage gap. If every remaining
sighting is one camera, the hypothesis collapses to that camera; duration
is the window of reads; the note says looping or repeated passes, not a
route.

Pinned by `test_a_single_camera_loop_is_not_a_coverage_gap`.

---

## CR-049 — Live wall at ingest rate; Overview no longer scans the store cold
**Date:** 2026-09-04

Two jury-visible stalls:

1. **Live tiles refreshed every 20 s** from a 20 s snapshot cache, so a wall
   fed by 1 Hz ingest JPEGs looked recorded. TTL is now 1 s; the UI polls
   ~1.5 s and badges LIVE when the frame is under 2.5 s old. Thirty parallel
   file reads, not thirty RTSP sessions. Click-to-play WebRTC is unchanged.
2. **Overview took ~10 s** because `Store.stats()` issued a dozen COUNT scans
   on a 430k-row live SQLite while ingest was writing. Duplicate plate
   queries removed; the result is cached 3 s and invalidated on write.

Pinned by `test_stats_cache_invalidates_on_write`.

---

## CR-048 — Live wall hid cameras whose ingest JPEG was older than 10 minutes
**Date:** 2026-09-04

CR-046 served ingest stills and refused a second RTSP session, with a 600 s
stale window. Under the fps budget some workers went tens of minutes between
JPEGs (preview interval was 1 s of PTS, so a looping or slow clock starved
the file). The wall then reported "waiting for ingest" for cameras whose last
frame was sitting on disk.

**Fix:** while ingest is publishing any camera, serve that camera's last JPEG
regardless of age, labelled `ingest-stale` with `X-Frame-Age-Seconds`. Preview
writes are now one per wall-clock second. A missing file still does not open
RTSP.

Pinned by `test_a_half_hour_ingest_preview_is_served_while_ingest_is_publishing`.

---

## CR-047 — Hard plates: one-frame leads now live; OCR lookalikes in search
**Date:** 2026-09-04

CR-040 published leads in the pipeline; the accumulated store still showed
0 leads because it predated that ingest. After restarting 30-camera ingest
against `var/live.db`, **leads are MEASURED** (votes = 1) alongside confirmed
marks. Still **0 cross-camera repeats**.

Two further plate-path gaps, both the class of miss that loses the designated-
vehicle test when the panel types a mark the OCR almost got:

1. **Search was exact-or-fuzzy only.** `GJO5AB1234` against a stored
   `GJ05AB1234` returned nothing unless the officer ticked near-match.
   `repair_candidates` existed in `plates.py` and was unused in search.
   Exact-empty now also looks up format-valid one-confusion neighbours of the
   *query*. Hits are `REQUIRES_VERIFICATION` and say the stored read was not
   edited.
2. **OCR crops under ~48 px** were sent to the backbone at native height.
   Detection already maps boxes to full resolution; government mounts still
   yield 20–40 px plates. The crop is bicubic-stretched to `ocr_min_height`
   before OCR — same pixels, larger; characters are not hallucinated.

Pinned by `test_search.py` (O/0 query), `test_plates.py` (lookalikes not
applied), `test_ocr_crop.py`.

---

## CR-044 — Discovery still opened the grid anonymously
**Date:** 2026-09-04

The stream access key is injected at socket open by ingest, the snapshot
service, and the stream worker. `probe_stream` — the path used when the
catalogue is unreachable — still called `av.open` on the clean URL. Against a
grid that authenticates, that is a 401 per candidate id, then a report that the
estate is empty.

Fixed: the probe fails immediately if the government host is reached without
`SENTINEL_GRID_EMAIL`/`PASSWORD`, injects the same credentialed URL everyone
else uses, and redacts PyAV's exception. `profile_grid.py` and the live
measurement tools (`bandwidth`, `read_overlays`, `read_landmarks`) were the
same class of miss and are wired the same way.

The official catalogue `GET /api/ingest` on the RTSP host is **MEASURED 404**.
`cameras.json` still redirects to sign-in. Parser coverage for the documented
record shape is in `tests/unit/test_sentinel_catalogue.py` so unblocking the
catalogue is configuration. Internal reference: `docs/SENTINEL_SANDBOX.md`.
The access password is not in this repository.

---

## CR-046 — Model 1 hid eleven cameras; the wall opened a 31st stream
**Date:** 2026-09-04

Two separate faults made the mandatory registry look incomplete.

1. **GIS.** `/gis/cameras` only returned located features. Eleven live-grid
   cameras have `NAME_INSUFFICIENT` coordinates by policy and were counted,
   not listed. `/gis/health` used the same bbox filter, so those eleven
   looked never-ingested on the live wall. Positions are still not invented.
2. **Live stills.** Snapshot fell through to RTSP when a preview was missing
   or older than the TTL. Ingest already held thirty sessions; the extra
   `av.open` hung 12–45 s and the wall showed 24 of 30. Ingest also wrote
   previews only on analysed frames, so a camera skipped by the fps budget
   never published a JPEG.

Fixed: `unlocated` is a list of feature dicts; health includes those
cameras; ingest writes a still at 1 Hz even when analysis is skipped;
snapshot serves a stale ingest JPEG (up to 10 min, labelled) and **does
not** open RTSP while any preview is being published; the estate map has a
registry strip of all thirty; the live wall loads `/gis/cameras` (CAMERA_READ)
and requests every tile, not only those in the viewport.

---

## CR-045 — Live wall must not open a second copy
**Date:** 2026-09-04

With the stream key in the API process, `/cameras/cam21/snapshot` opened a
new RTSP session while ingest already held thirty. The capture returned 503
after 45 s. The grid was up (`streaming=30/30`); the wall was the extra
consumer the guide tells us not to be.

Fixed: ingest writes one JPEG per camera per second under
`var/live_evidence/preview/`. The snapshot service serves that file when it
is fresher than the TTL and does not open the grid. RTSP capture remains the
fallback when ingest is not running.

---

## CR-043 — Thirty tiles waiting for a 401
**Date:** 2026-09-04

The live wall opens a snapshot per visible tile. Against the government grid
that connection is authenticated. With `SENTINEL_GRID_EMAIL` unset,
`credentialed()` returned the clean URL and PyAV waited twelve seconds for a
401 — times thirty. The wall looked broken. The cameras were not.

Fixed: a non-loopback RTSP URL without a configured credential is refused
immediately, in words, and `/system/health` reports `grid_access` so the
operator sees one notice rather than thirty hung tiles. Loopback MediaMTX
(the synthetic demonstration) is unchanged. Investigation over the store
does not depend on the credential.

---

## CR-042 — ANPR GOOD is not "able to read a plate"
**Date:** 2026-09-04

Overview labelled `capability_anpr.GOOD` as *"measured able to read a plate"*.
On this grid that count is zero — the GOOD threshold is 35% yield at ≥ 90 px —
while the store held 26 distinct marks on six cameras. Analytics then summed
`plate_reads` from **stale capability samples** (two cameras graded early) and
reported "2 registration marks read" next to 68 confirmed plates.

Three further faults in the grader, found on the same pass:

1. Person observations were in the ANPR/appearance denominator. The policy
   already says yield is per vehicle; people are never plated.
2. `grade_all` loaded 20,000 rows ordered by time. cam01 holds 62k. A window
   that drops later plates is how a camera that has published a mark grades
   as if it never has.
3. Cameras that produced most of the live marks (cam06, cam07, cam12) had
   never been re-graded, so they sat at UNKNOWN with 0 samples.

Fixed: persons are excluded from plate and appearance yield; a person-only
camera is UNKNOWN for ANPR, not UNSUITABLE; load limit 100,000; overview
separates "cameras that published a mark" from "cameras graded GOOD for
ANPR"; analytics leads with the live-store count. Re-grade the live store
from stored observations after this change.

---

## CR-041 — Person search must not talk like a vehicle ID
**Date:** 2026-09-04

Attribute search always returned the caveat *"they do not identify a vehicle"*,
even when the filter was `object_type=person`. The empty-result copy said the
*vehicle* was absent. A5 is vehicle **or** person; a person Find that talks
about vehicles is the same class of error as a lead wearing
`CONFIRMED_BY_PLATE`.

Fixed: a person-only filter states that position, time and dwell are reported
and identity is not. Mixed or vehicle filters keep the original wording. The
empty-result copy names the *target*.

---

## CR-040 — The lead never reached ingest
**Date:** 2026-09-04

CR-039 published a single confident plate read as a LEAD in `PlateVoter.resolve`.
The live pipeline never called `resolve`. It called `resolve_all`, which is the
camera-level evaluation path and skips anything with fewer than two agreeing
frames — by design, so C-033 cannot flood the ANPR eval with one-frame OCR
noise. On top of that, `_emit` discarded every track with `hits < 2`, which at
the measured 0.27 fps per camera is exactly a vehicle that crossed in one
analysed frame.

So the lead existed in a unit test and in a hand-forced proof, and vanished
the moment a real stream ran. A one-frame plate on the route panel was also
labelled `CONFIRMED_BY_PLATE` because trajectory hardcoded the status instead
of reading the vote count.

Fixed:

1. The pipeline emits from `resolve` (per track). `resolve_all` stays
   corroborated-only, which is what the ANPR eval needs so C-033 still
   declines.
2. A one-hit track with a plate is emitted; a one-hit track without one is
   still treated as noise.
3. Search, trajectory and alerts all derive status from the stored vote
   count via `plate_status`. A lead matching the watchlist still alerts —
   a stolen vehicle seen once must not vanish — and is flagged
   uncorroborated so it cannot look like a voted confirmation.

Pinned by new tests in `test_plate_voting.py`, `test_search.py`,
`test_watchlist_alerts.py` and `test_store.py`.

---

## CR-039 — Judging the whole thing, and fixing what would lose it
**Date:** 2026-09-04

With the deadline close, I evaluated the submission as a jury would against the
seven common areas, and probed the two things the live test case actually turns
on. Four defects surfaced, each of which would have cost real marks. All four
are fixed.

### 1 · Ingest could not run against our own onboarded estate (P0)

The grid's catalogue lives behind a browser session cookie. Ingest tried the
catalogue, then a slow per-id probe, and if both failed it **gave up** — even
though thirty cameras with valid stream URLs sat in the registry, reachable. A
Model-1 platform that calls the registry its spine, then cannot ingest from it,
is contradicting its own architecture. Added a registry fallback and an explicit
`--from-registry` mode; recorded as such, because a run from the registry cannot
confirm the catalogue still agrees with it.

### 2 · The ingest opener bypassed the credential module (P0)

`tools/live/ingest.py` opens streams with its own `av.open()` — a third opener
alongside the snapshot service and stream worker, and the one missed when the
credential injection was wired. Every ingest session connected anonymously to a
grid that authenticates, so `streaming` sat at 0. It also logged PyAV's raw
error, which carries the credential. Both fixed: `credentialed()` at the socket,
`redact()` on the error. **Three openers is two too many** — noted for a follow-up
that routes all stream opening through one place.

### 3 · ANPR published nothing from a single frame (P0 for the test case)

`min_votes = 2` requires a plate to be read identically in two frames. At the
per-camera frame rate a large estate can afford — the ingest itself warns of
**0.27 fps per camera** at thirty cameras — a vehicle frequently crosses in one
analysed frame, and every such crossing was discarded. On the live grid this was
the difference between a route and a blank screen.

A single valid read at a higher confidence bar (0.82 vs the voted 0.55) is now
published as a **LEAD**: `votes=1`, `provisional=True`, and every surface labels
it `REQUIRES_VERIFICATION` with a warning that it is uncorroborated. A
confirmation still needs two agreeing frames. The distinction rides on the
stored vote count, so search derives it without a schema change and no caller
can forget it. Two disagreeing reads never become a lead. Pinned by five tests
in `tests/unit/test_plate_voting.py`.

### 4 · Person detection was thrown away (P1 — named in evaluation area A5)

A5 asks for "vehicle **or person** detection, intrusion detection". The detector
is COCO-trained and returns people on every frame; one line discarded them. They
are now tracked in a separate pool from the same forward pass — no second
inference, so no extra GPU cost at scale — never fused with a plate, never
voted, and published with a position, a time, and a dwell duration. The word
"intrusion" is deliberately withheld: it is a judgement about permission this
system cannot make, so the dwell is reported and the officer decides. Measured
on cam04: **604 detections → 46 person observations**, with confidence, box and
dwell. `flush()` now drains both pools; draining only the vehicle pool discarded
every person still in frame at shutdown.

---

## CR-038 — Giving the walkthrough a voice
**Date:** 2026-09-03

The submission asked for the demonstration to be as complete as it could be, and
a film an evaluator watches without reading every caption is more complete than
one they must. `tools/demo/narrate.py` adds an Indian-English voiceover to the
recorded walkthrough and muxes it onto the existing frames.

Three decisions worth recording, each about not overstating:

**Offline, and stated as such.** The narration is generated with the system's
own `say` (voice Rishi, en-IN) and muxed with the ffmpeg bundled by
imageio-ffmpeg. No cloud service touches it — consistent with the standing rule
that government material is not sent to external services by default — and the
intro card says the voice is offline text-to-speech so no one mistakes it for a
recorded human narrator.

**Sync by construction, not by guess.** Each segment's audio is padded with
trailing silence to exactly its segment's on-screen duration, and the segments
are concatenated in the same order the frames are built. The voice cannot drift
from the screen because the audio timeline and the video timeline are the same
list of durations.

**Refuse rather than ship a lie.** On a host without `say`, the tool prints that
it cannot generate the voiceover and exits — it does not write a silent file
that would look narrated in a directory listing.

Both demo tools are declared under an optional `demo` extra, never as runtime
dependencies: the platform installs and runs on a machine with no browser and no
bundled ffmpeg, and nothing in the product imports either.

Measured: **3 min 12 s, 5.5 MB, thirteen narrated segments**, audio verified as
a 44.1 kHz stereo AAC track alongside the h264 video.

---

## CR-037 — A government interface, held to a government standard
**Date:** 2026-09-03

The interface was described as unacceptable and looking "very lame". Two rounds
of work followed: an institutional visual identity (CR-028), and this — holding
the result to the standard Indian government software is actually audited
against. That standard is **GIGW 3.0 and WCAG 2.2**, and the audit found the
interface failing several of its clauses in ways that would have been caught the
moment anyone ran an accessibility checker over it.

The reference points were the standards themselves, not a mood board: GOV.UK's
"make it simple to use, not simple to look at", the RTCC control-room literature
on reading the same screen at a desk and from across a room, and GIGW 3.0's
requirements for landmarks, bypass links and assistive-technology support.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | No `aria-live` regions anywhere. A screen-reader operator clicked "Investigate" or watched the camera wall fill and was told nothing — the result count, the wall progress and the handling strip all changed silently. | The workspace, the result count, the live-wall progress and the handling strip are polite live regions. The wall now announces "6 of 30 showing a frame" as it fills. |
| 2 | **P1** | No heading structure and no landmarks — a screen reader's outline was a flat run of text. | One `h1` (the wordmark, with the Devanagari name for AT), `role="banner"` on the masthead, a labelled `nav`, and a focusable `main` that is the target of a new skip link. |
| 3 | **P1** | A single ad-hoc `:focus` rule. WCAG 2.2 requires a focus indicator at 3:1 contrast; a keyboard-driven evaluation would have lost the caret repeatedly. | One `:focus-visible` treatment across every control, in the seal colour (which is a state nowhere else), switched to the light variant on the navy rail so it meets contrast on both grounds. |
| 4 | **P2** | Count badges read as bare numbers — "3" with no idea what it counted. | Each is labelled: "3 alerts open", "30 cameras on the wall". |
| 5 | **P2** | Nothing for `prefers-reduced-motion` or `forced-colors`. In Windows High Contrast the author colours vanish and status carried by colour alone disappears. | Motion is collapsed under reduced-motion; under forced-colors the state-bearing components regain a border so their shape survives. Every state already carries a word as well as a colour, so nothing depends on the colour alone. |
| 6 | **P1** | A density control scaled `:root` font-size, which enlarged the fixed-height masthead and handling strip until they overflowed and lapped the row below. | Scale is scoped to the workspace (`main`) against a `--content` variable — a thirty-tile wall gets larger labels in the same grid while the chrome stays exactly as designed. Three steps: comfortable, large, wall, remembered per operator. |
| 7 | **P2** | The chrome bands had fixed heights, so a masthead that wrapped at a narrow width overlapped the handling strip. | The bands are `minmax(54px, auto)` — exactly 54/22 on a control-room display, growing rather than overlapping when they must wrap. |

The density control answers a real control-room finding: the same screen is read
at a console and from across the room, and an operator eight hours into a shift
is not reading 11px. One button, three sizes, remembered.

Verified on the running interface against the live government grid: heading
count 1, skip link present, `main` a polite live region, four live regions, all
landmarks resolved, and the camera-wall badge announcing "30 cameras on the
wall". The live wall itself shows four real Sentinel cameras streaming.

---

## CR-036 — The grid had not revoked us; it had started asking
**Date:** 2026-09-03

CR-031 recorded that the grid was refusing every connection with 401, and left
the cause open. The cause was in the integrator's guide: **RTSP and WHEP now
authenticate every connection with a registered email and access password
embedded in the URL authority** — `rtsp://email:password@host/…`. Our stored
URLs carried no authority, so every connection was anonymous and every
connection was refused.

Two details that each cost a round of 401s:

* **The email must be percent-encoded.** An unencoded `@` splits the authority
  at the wrong place, the grid reads a truncated username, and the refusal looks
  exactly like a wrong password.
* **The registered email is not always the obvious one.** Only addresses on the
  approved list connect at all.

Verified: `cam01` opens **1920×1080 h264 in 2.5 s**, and the wall fills with
live frames.

### Where the credential is allowed to be

The grid's design puts a secret in a URL, and URLs go everywhere — logs,
exception messages, database rows, exports, screenshots of a camera table. So
the registry keeps the **clean** URL and `saakshya.live.credentials` adds the
authority in the moment before the socket opens.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | Stream connections were anonymous against a grid that had begun authenticating them. | `credentialed()` injects the authority at `av.open()` in both the snapshot service and the stream worker. Nothing else sees it. |
| 2 | **P0** | PyAV puts the URL it tried into its exception text, and that text was being logged verbatim. A 401 would have written the password into the server log. | `redact()` is applied at every exit that can quote a URL, and it matches any authority — not only ones we added. |

Pinned by eight tests in `tests/security/test_grid_credentials.py`, covering the
percent-encoding, redaction of a credential this code never created, the
unauthenticated deployment (URL unchanged, no special case), and the refusal to
inject a password into an `https` URL — the CDN uses a session cookie, and
sending the password there would put it in someone else's access log.

The credential lives in `SENTINEL_GRID_EMAIL` and `SENTINEL_GRID_PASSWORD`, read
from the environment only, and is in no file in this repository. Confirmed
against the running server's log after a full wall load: zero occurrences.

---

## CR-035 — A film of the product, not of its output
**Date:** 2026-09-03

The two required demonstration videos show what the analytics produced: boxes
and registration marks drawn on the frames they came from. Neither shows the
thing an officer actually uses. A submission judged on whether a police force
would adopt this needs a film of the interface.

`tools/demo/record_walkthrough.py` drives the real interface in a real browser
against a real server and screenshots each step. Nothing is mocked and no screen
is staged — every frame is Chrome displaying the served page. **If a panel is
empty in the film, it is empty in the product.**

Eleven steps, in the order the work happens: Overview, purpose binding, Find,
Trace, Cameras, Analytics, Live, Alerts, the case file, Evidence, Audit. Each
holds long enough to read its caption, because the caption is the reason the
step is in the film at all.

Two decisions worth recording:

**A step that cannot be driven is reported, not skipped.** The first run failed
on the case file — `text=FIR-214/2026` matched the masthead's purpose-binding
field as well as the record, so Playwright timed out on an ambiguous locator.
Had the recorder swallowed that, the film would simply have been missing a
screen and nobody would have known which. It printed the failure, named the
step, and the closing card counts how many steps could not be driven.

**The token is passed on the command line and never written to disk by the
tool.** It is a real token and every request the recording makes is audited like
any other; the walkthrough authenticates the same way an officer does, through
session storage, and bypasses nothing. Mint a short-lived one to record, then
revoke it.

Measured: **11 steps, 1 min 29 s, all driven**, against the demonstration store
with a basemap configured.

---

## CR-034 — "0 registration marks read", on an estate that had read 109
**Date:** 2026-09-03

The Analytics screen reported:

> **0** registration marks read — *0.00% of observations*

The store held **109 plate reads across 140 observations**, 85 of them distinct.
Three screens away, the same platform was drawing a three-camera route built on
those very reads.

Two causes, and the second is the one that matters.

**The data.** `camera_capability.plate_reads` was added after those rows were
graded — the *rate* was kept, the *count* was not — so the column held NULL.
Re-grading from stored observations populates it (C-014 → 20, C-021 → 35,
C-047 → 29). That is a stale-row problem and the re-grade action already exists
to fix it.

**The rendering.** The panel summed `f.plate_reads || 0` across cameras, which
turns every NULL into a measured nought and then divides by the full sample
count to produce a confident `0.00%`. This panel's entire purpose is to
distinguish "this camera cannot read plates" from "we have not measured this
camera", and it was collapsing the second into the first — the same defect it
was built to expose, in its own arithmetic.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | A missing count rendered as `0` and a missing rate as `0.00% of observations`, asserting the estate had read no plates when it had read 109. | Cameras without a recorded count are excluded from the sum, not counted as zero. With none recorded the figure reads `—` and says *"not recorded — re-grade from stored observations to count them"*; with some, the percentage is over the cameras that actually carry a count and names how many that is. |

Measured after the fix: **109 marks read, 77.86% of observations** — the
database's own numbers.

This is the third defect of the same shape found today, after a search that
reported a withheld match as no match and a wall that reported an unrequested
tile as connecting. Absence rendered as a confident value is this interface's
characteristic failure, and it is worth naming as one.

A sweep for the same signature across the interface found the remaining
`|| 0` sites to be grade tallies, where a missing key genuinely does mean a
count of nought, and server-computed totals that were checked against the
database directly (140 observations, 109 with a plate — the API's figures match
the store exactly). One further ambiguity did turn up, in the System panel.

**`PLATE READS 0` beside `OBSERVATIONS WITH PLATE 109`.** Both numbers were
correct: `plate_reads` is the raw-OCR table, holding every read attempt
including the rejected ones with their reasons, and it is genuinely empty in
that store. Printed under that label beside the other, it reads as the system
contradicting itself. The stat is now `raw_ocr_read_records`, which cannot be
mistaken for "how many plates were read".

---

## CR-033 — A sealed record that overstated what it held
**Date:** 2026-09-03

Opening the evidence panel for the one watchlist hit on the government grid
showed `capture_method`:

> automated capture from live RTSP; no manual editing of **the retained frame**

alongside `frame_path: null` and `frame_sha256: null`. There is no retained
frame. The record asserts one.

The generator was corrected earlier — `_capture_method()` now derives the
string from what was actually stored. The records sealed before that fix were
not corrected, **and cannot be**: `capture_method` is inside the hashed
manifest, so editing it to read truthfully would break the entry hash and would
be precisely the tampering this system exists to detect. Six such records exist
across two stores.

So the record stands, unaltered, and the verification says what is wrong with
it.

### Integrity and truthfulness are separate tests

`VerificationResult` had two outcomes. That is one too few. A record can be
exactly what was sealed — every hash matching, the chain unbroken — and still
contain a statement that is false. Collapsing that into **failed** reports a
broken chain where none exists, and an operator shown "EVIDENCE CHAIN BROKEN"
over an intact chain learns to disregard the warning. Collapsing it into
**passed** hides a defect a court would find.

A **caution** is neither: integrity holds, and something needs saying.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | Six sealed records assert a retained frame that was never retained, and nothing detected it. | `verify()` compares a record's own words against its hashes and raises a caution naming the defect, with the instruction not to offer the record as a sealed copy of footage. |
| 2 | **P1** | Cautions raised on a single record did not survive into `verify_chain()`. A defect visible only when verifying one record at a time is a defect nobody will see: the chain is what gets checked before a record is relied on. | Cautions travel up with the record they belong to. |
| 3 | **P2** | The interface rendered any non-pass as `VERIFICATION FAILED`. It also has **two** verification screens — the single-record panel and the chain view — and fixing one left the other silent. The chain view is the one an officer opens before relying on a record, so that was the worse of the two to miss. | Three states: verified, *"integrity intact — read the cautions"*, and failed. The caution panel says first that every hash matches and the chain is unbroken, so a reader is never left guessing whether the record was altered. |

Pinned by a test that seals a record the way the old generator did — so the
entry hash covers the overstating string, as it does in the real records —
rather than editing one afterwards, which is tampering and correctly fails on
the manifest hash instead.

---

## CR-032 — A search that found the vehicle and said it had not
**Date:** 2026-09-03

Searching `GJ38BH5815` as an investigator returned **`result_count: 0`** while
the same response carried **`stage_counts: {"exact": 1}`**. The index had found
the registration mark. The interface said no observation matched.

The cause was jurisdiction filtering, working correctly and reporting nothing:

```python
cands = [c for c in res.candidates
         if c.observation.camera_id in allowed][:limit]
```

The match was on `cam21`, whose district is recorded as
`Gujarat (town not confirmed)` — a placeholder that is in no officer's scope.
The candidate was dropped, the count was recomputed, and nothing anywhere said
a thing had been removed.

**This is the most dangerous wrong answer this platform can give.** Not a
refusal — an investigator understands a refusal — but a confident denial. The
interface went further and explained itself: *"no camera in the searched set
recorded a matching observation."* A camera had. An investigator reading that
screen would close the line of enquiry.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | Out-of-jurisdiction matches were dropped silently while `stage_counts` still reported them, producing "0 results" for a mark the system had seen at 0.995 confidence. | The response carries `withheld`: the count, the districts, and the reason. The refusal is audited as `search_withheld`. |
| 2 | **P0** | The empty state asserted that no camera recorded a match — false whenever something was withheld. | With a withholding it reads *"Nothing shown to you — every match for this target is on a camera outside your jurisdiction. The vehicle was recorded; you are not permitted to see where."* |

What is disclosed is deliberately bounded: **the count and the districts, never
the observations**. That is what an investigator needs in order to ask the right
force for access, and no more. Verified both ways — a state-scoped supervisor
sees the same mark as `CONFIRMED_BY_PLATE` at 0.995 on cam21.

---

## CR-031 — A wall of black tiles, and what it was actually saying
**Date:** 2026-09-03

The live wall was shown as unacceptable, and it was: thirty tiles, six with
pictures, the rest black and reading "connecting…" indefinitely. Every word of
that was misleading, and underneath it was a fact the platform should have been
shouting.

### The fact underneath

**The organiser's grid has revoked our access.** Verified outside the
application, straight from PyAV: RTSP returns **401 Unauthorized** and HLS
returns **403 Forbidden**, on every camera, in 0.1 s. The same URLs captured
343 vehicles about an hour earlier. Nothing in this repository changed in
between.

This is recorded as an operational fact with a caveat we should hold: our own
usage in that window was heavy — several multi-camera renders plus a
thirty-tile wall — and a rate limit or a connection cap is one plausible cause
among several. We do not know which, and the honest position is that access
stopped, not why.

### What the interface was doing wrong

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | A refusal by the grid was reported as `503 · grid busy — retrying (1 of 3)`. That sends an operator hunting a fault on a camera that is working perfectly and simply will not let us in — and it retries, three times, against an answer that will never change. | Failures are classified. An upstream refusal is **502 `UPSTREAM_REFUSED`** and is not retried; the tile prints the grid's actual answer: *"the camera grid refused this connection (401 unauthorised) — our access, not the camera."* |
| 2 | **P0** | Every tile said **"connecting…"** from the moment the wall opened, including twenty-four that nothing had tried to connect to. A tile that has not been requested is not connecting, and a page of tiles all claiming to connect while nothing happens is indistinguishable from a broken system. | A tile states where it actually is: *not requested*, *waiting for a capture slot*, *capturing*, or the reason it failed — and carries what the registry already knows underneath (`streaming · 9,924 frames seen`, or `never ingested`). |
| 3 | **P1** | Nothing said what the wall as a whole was doing. Thirty cameras at one to ten seconds each cannot all load at once, and with no progress the operator sees only dark tiles. | A running line above the grid: *"6 of 30 showing a frame · 4 capturing · 16 queued · 2 unavailable."* |
| 4 | **P1** | A tile scrolled into view joined the **back** of the queue, behind cameras that had already scrolled away. The wall filled everywhere except where the operator was looking. | A newly visible tile goes to the front. |
| 5 | **P2** | The browser capped captures at 3 while the snapshot service already caps at 4 and caches each still for twenty seconds. The second, stricter limit throttled nothing the server was not already throttling — it only made the wall fill more slowly, which is how it came to look broken. | Matched to the server's own limit. |

### A mistake of mine, in the user's screenshot

The handling strip read `demo.db · DEMONSTRATION` while the grid showed thirty
live government cameras — a provenance indicator contradicting the data beside
it. That was **not a bug in the platform**: it was a value I injected into the
DOM by hand while testing that element and never cleared. Verified afterwards
against a real server: it reads `live.db · LIVE CAPTURE`, from the API.

Leaving test state in a running interface is how a false reading ends up in a
screenshot, and this one landed in exactly the place where a false reading does
the most damage.

---

## CR-030 — The deck, the diagrams, and reading your own output
**Date:** 2026-09-03

`docs/PPT_CONTENT.md` and the ASCII diagrams in `docs/HLD.md` are right for
files that must stay diffable in review. They are not what gets projected. Both
are now rendered — the deck to a 19-page PDF, the HLD to four drawn diagrams —
from those same sources, so a claim still lives in exactly one place.

Every defect below was found by opening the output and looking at it. None
would have been caught by a test, and all four were plainly visible on the
first page rendered.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | Inline emphasis is free to straddle a source line break, and the renderer parsed line by line. `**` printed literally — on the slide carrying the capability numbers, turning the headline figure of the deck into visible asterisks. | Source lines are joined into blocks before anything is parsed. |
| 2 | **P1** | This source nests bullet lists inside blockquotes. A parser that only stripped the `>` ran three separate findings together into one wall of prose with stray hyphens in it. | The inside of a quote is parsed the same way as the outside. |
| 3 | **P1** | A long slide ran off the bottom of the page, under the footer rule and past the edge. Text overflowing a footer is the clearest possible signal that nobody looked at the output. | Blocks are measured before they are committed; a slide that will not fit continues on a `(cont.)` page. The deck went from 17 pages to 19. |
| 4 | **P2** | The footer printed the *slide* number against the *page* count, so two consecutive sheets both read "14 / 19". | The marker beside the title is the slide; the footer is the page. |
| 5 | **P2** | Two edges leaving one box were both drawn at that box's centre line, so they overlapped exactly and neither visibly reached its target — on the diagram showing a search fanning out to four authorisation gates. | An elbow route: out, across, in. |
| 6 | **P2** | The watchlist return path was drawn before the nodes and ended up hidden behind a box, along with its label. | Routed below the box it was passing under. |

Arial carries no Devanagari, so **साक्ष्य** rendered as tofu boxes on the cover,
in the product's own name. macOS ships a Devanagari face; it is asked for by
name, and the cover falls back to the Latin transliteration on a host without
one.

### A process note

Two release gates were started against the same log file while the first was
still running, and their output interleaved. The summary table read PASS on a
gate whose failure detail was printed below it, which is a contradiction that
took a while to resolve and was entirely self-inflicted. `release_check.json`
is the authoritative record precisely because it is written once, at the end,
by one run: **14 of 14 gates, no blocking or advisory failures**.

---

## CR-029 — The demonstration video, and a label that was not true
**Date:** 2026-09-03

Two deliverables the submission asks for and this repository did not have: a
demonstration on the organiser's feed with **"an output report showing detected
vehicles or number plates with corresponding timestamps"**, and a demonstration
on our own footage.

`tools/demo/render_demo_video.py` renders both. Frames are decoded live, run
through the same `CameraPipeline` the platform uses, and drawn with the boxes
the tracker actually held at that frame. There is no replay path and no
saved-detection path: if the video shows a box, the detector produced it during
that run. The CSV is written from the same rows that were drawn, so the report
and the video cannot disagree.

**Measured, government grid** — 7 cameras, 32 s each: 6 opened, **363 vehicles
tracked, 8,116 report rows**, 114 s of video, analysis at **4.2–5.4 frames per
second of stream time**. **0 registration marks**, which is the honest result at
these mountings.

**Measured, local synthetic corpus** — 6 clips: **40 vehicles, 14 distinct
registration marks**, two of which (`GJ01CD5678`, `GJ35BV6925`) were read on
**two different cameras**. That contrast is the point: ANPR is not weak, the
geometry on the government estate is.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | The frame composer **hard-coded `LIVE GOVERNMENT FEED · NOT A REPLAY`**, so the own-feed video stamped that banner across the local synthetic corpus. A submission video asserting that generated frames are live government material is the single most damaging thing in this repository — it is false, it is prominent, and it is on the artefact a judge watches. | Provenance travels with the run and has **no default that is safe to leave**: the field reads `PROVENANCE NOT STATED` unless a caller sets it. Government runs say so; corpus runs say `LOCAL SYNTHETIC CORPUS · NOT GOVERNMENT DATA`. |
| 2 | **P1** | The own-feed cards called the corpus "our own recordings". It is generated, not filmed. | Named as the local synthetic corpus, on the card, on every frame and in the report — with *why* it is synthetic: its marks are known in advance, so a read can be scored right or wrong. On real footage nobody can say what the correct answer was. |
| 3 | **P1** | A 3 s frame timeout refused three of five cameras. Capture on this estate was measured at **1.3–10.4 s**; the wait for a *first* frame is nothing like the wait for the next one. Conflating them discarded cameras that were merely still connecting. | Split: 30 s to open, 6 s between frames. Decode went from 2/5 cameras to **6/7**. |
| 4 | **P1** | Detection runs far below stream rate, so drawn frames are a sparse sample. Encoded back to back, the scene played many times too fast — and speed is what a viewer reads off a CCTV video without being told to. | Each frame is held for the stream time it covers, so a vehicle takes as long to cross the frame as it did on the road. A hold is capped at 3 s: a stalled stream should look like a stall, not a frozen minute. |
| 5 | **P2** | Cameras here carry burnt-in clocks reading **June** while the normalised timeline reads September. On screen with no explanation, that reads as a fault in this platform. | The measured **time cluster** is drawn on every frame (`GRID-13JUN-2137 · MEASURED`). The disagreement is a finding about the grid, and the video now says so. |

Credentials never reach the frame, the log or the console: stream URLs are
redacted at every exit from the module, because a redaction applied at one exit
and not another is the same as no redaction at all.

---

## CR-028 — It looked like a developer tool, not a government system
**Date:** 2026-09-03

The interface worked and read as a side project. Uniform 11px text, no
institutional identity, and a rail that was a list of words — everything was
legible and nothing carried any authority. For a platform proposed to a police
department, that is a real defect: the people who decide whether to trust it
will read the frame before they read a single number.

### What changed

The **frame** is now institutional and fixed in both themes — a deep navy
masthead and rail with one warm accent. The frame stays that colour whichever
theme the page renders in, so an officer's eye learns one shape for "where am
I" and it does not move when the theme changes or a projector washes the page
out.

A **handling strip** under the masthead, which is the piece doing the most
work. It carries `OFFICIAL · SENSITIVE`, the reminder that every query is
attributed and audited, and — the part that matters operationally — **which
store is open and whether it holds live capture or demonstration state**.

That last field exists because mistaking demonstration state for live
government data is the easiest error to make while watching a demonstration,
and the person most likely to make it is the one being shown the screen. The
platform already refuses to write live observations into a demonstration store;
it now also says which one you are looking at, on the frame, at all times.

The overview panels became **cards with edges**. Before, four columns of grey
text sat on one flat ground: everything was readable and nothing was separable,
so the eye had no way to take one question at a time.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P2** | Panels were cards with clipped corners, so a table wider than its column was cut off mid-cell with no way to reach the rest. | Wide content scrolls inside its own panel. The workspace itself never scrolls sideways. |
| 2 | **P3** | Masthead controls kept the page's surface colours and vanished against navy. | The masthead's own controls are styled for their ground. |

No web font is loaded, which is a decision worth restating: the deployment
target may have no internet route, and a font that silently falls back is worse
than one never requested. The hierarchy is carried by scale, weight and
letter-spacing on faces that are already present.

---

## CR-027 — A CCTV platform that could not show you a camera
**Date:** 2026-09-03

Evaluation area A1 requires *"live or recorded viewing"*; submission
requirement 4 repeats it. **The interface displayed no video and no imagery at
all.** It could ingest thirty government feeds, detect vehicles, read plates,
build routes and seal evidence — and never show an operator a single camera.

The largest gap in the submission, and it had been invisible because every
screen that existed worked well.

### What was added

A **Live** view: a wall of every onboarded camera, each tile carrying its name,
district, codec, resolution and measured ANPR and appearance grades. Two ways to
see a camera, and the tile says which it is showing:

* **Cached stills**, refreshed on a timer, badged `STILL` with the frame's age.
  One capture is shared by every viewer.
* **Live video over WebRTC (WHEP)**, badged `LIVE`, opened only for the camera
  an operator has actually clicked. The browser negotiates directly with the
  media server: **this platform never proxies or transcodes video**, because
  doing so would place a second analytics-sized workload in the path for no
  investigative gain.

`SAAKSHYA_WHEP_BASE` enables it and widens `connect-src` for exactly that
origin. Unset, the wall still works on stills and the interface says live video
is not configured rather than offering a control that does nothing.

Verified on the live grid: cam01 playing live WebRTC video with a `LIVE` badge,
alongside five neighbours showing timestamped stills.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | Every tile read "no frame". An `<img src>` cannot carry a bearer token, so all thirty requests were unauthenticated. The obvious fix — the token in a query string — is exactly what must not be done: it would land in server logs, browser history and any screenshot of the demonstration. | Stills are fetched with the same headers as every other request and handed to the tile as a blob. `authHeaders()` is now shared, so any non-JSON fetch authenticates the same way. |
| 2 | **P1** | Loading thirty tiles at once made thirty capture requests, and the grid refused nine of them. The integrator's guide is explicit that each client receives its own copy of a stream and that only cameras being processed should be opened. A viewing wall must never compete with analytics for the government's stream capacity. | Captures are lazy — only tiles actually on screen — and bounded to three in flight. |
| 3 | **P1** | Error messages were written to a frame looked up from a **detached** image element, so `closest()` returned null and nothing rendered. The wall sat on "connecting…" while the console filled with 503s. | The tile is found by camera id. Every state now shows: capturing, retrying with the attempt count, live with the frame's age, or the reason it failed. |
| 4 | **P2** | A 503 was treated as a dead camera. On this estate a capture takes **1.3 to 10.4 seconds**, so under a full wall that answer is common and temporary. | Retried three times with backoff, and the tile says which attempt it is on. Only after three does it report the camera may be down. |

The measured capture cost is worth recording on its own: **1.3 s to 10.4 s per
camera**. A thirty-tile wall fills progressively rather than at once, which is
the honest behaviour for a grid that hands each client its own stream.

---

## CR-026 — A route at 4,138 km/h, scored LIKELY
**Date:** 2026-09-03

The evaluation's central output is *"the complete route traversed by the
designated vehicle, including timestamped and location-wise movement history"*,
and the system had never been shown producing one on live infrastructure. Plate
yield here is a measured property of the estate — two marks in 13,745
observations — so the demonstration drives the chain with real frames from two
cameras **measured** to share a timebase, and stamps one mark onto the
observations they produce. Cameras, frames, detections, tracking, timestamps,
positions, timebase, watchlist, alert, solver and evidence are all real; the
plate string is the only injected element, and the tool prints that at every
step.

It worked, and it immediately exposed a **P0**.

```
2026-09-03T03:30:19  cam04  Paldi Circle          23.0169,72.5668
2026-09-03T03:30:23  cam01  Chiman bhai Bridge    23.0296,72.5219
timebase : ALLOWED
route    : LIKELY  score 0.685  cam04 -> cam01
```

**4.81 km in 4.2 seconds. 4,138 km/h, presented as LIKELY.**

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | Physical feasibility was checked only when `edge.trusted` — which requires **three observed samples** of that transition. On a first sighting no feasibility test ran at all, so the most implausible possible route was scored as the most likely. A judge would see a car doing Mach 3 on the first slide. | A geometric check that runs **before** anything learned, wherever both cameras have positions. Physics does not need three samples. Straight-line distance is used deliberately — it understates road distance, so it is the most generous reading of the pair: if even the direct line is impossible, the road route certainly is. |

The route now reports **REQUIRES_VERIFICATION at 0.35** with the reason on its
face:

> 4.81 km in 4.2 s implies 4,138 km/h, above the 200 km/h ceiling for a road
> vehicle. These two sightings are not one journey.

and four things that could explain it: an OCR error, a cloned mark, clock drift
or two cameras on different timebases, or two distinct vehicles associated in
error. The ceiling is 200 km/h — generously beyond any Indian road vehicle in
traffic, because the purpose is to catch the impossible, not to police the brisk.

Nine tests, including that a 96 km/h leg is **not** flagged, that a camera with
no position produces no speed claim rather than a guess, and that sightings a
moment apart say the timestamps are too close to separate rather than that the
vehicle teleported.

### A third, uncovered by the fix

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 3 | **P2** | The synthetic fixture that ten trajectory tests were built on described a route that was **never physically possible**: C-021 to C-033 is 29.07 km and the fixture allowed 400 seconds — **262 km/h** — with the next leg at exactly 200 km/h. The test asserting `not h.contradictions` was named "clean route scores well". Nothing checked, so nothing complained, and every trajectory test had been passing against an impossible journey. | Travel times recomputed from the real distances at ordinary road speeds (40–60 km/h), and the legs are now defined once and used by both the fixture and the assertion so they cannot drift apart. The assertion also names the contradictions when it fails. |

The fixture failing was the check working. It is worth noting how long an
impossible route sat unremarked in the tests that were supposed to validate
route-building.

### A second finding, from the same run

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 2 | **P2** | The provenance guard that keeps live observations out of the demonstration store matched a **substring** of the database URL, so `var/route_demo.db` — which is not the demo store — was refused. A guard that fires on names it does not mean gets worked around, and then it protects nothing. | Matches the file name. Moved into `saakshya.store.provenance` so the tool and its tests share one definition instead of the test grepping the tool's source. |

---

## CR-025 — Two-stage ANPR: measured, and declined
**Date:** 2026-09-03

The core deliverable is a route across cameras, and its blocker is plate yield.
The geometry is unambiguous: the plate detector currently sees a 1920px frame
downscaled to 1280, then downscales again to its own 640 input, so a plate
measured at **46 px** on this estate reaches the detector at roughly **15 px**.

The standard fix is two-stage — detect vehicles first, then run the plate
detector on each vehicle crop at native resolution, where the same plate fills a
far larger share of the input (~38 px rather than ~14 px). It was measured
rather than assumed.

**Detections**, same ten frames of cam04: whole frame **1**, per vehicle **7**.
Encouraging.

**Reads**, 70 frames per camera, vehicles ≥90 px only:

| camera | vehicles | whole frame | per vehicle | cost |
|---|---|---|---|---|
| cam04 | 79 | 0 OCR, 0 marks | 0 OCR, 0 marks | 6.3s → 17.3s |
| cam21 | 15 | 0 OCR, 0 marks | **4 OCR, 1 well-formed** | 5.3s → 12.9s |
| cam16 | 55 | 0 OCR, 0 marks | 0 OCR, 0 marks | 5.4s → 15.2s |

The single well-formed read is **`WA3111` at confidence 0.48** — not a valid
Gujarat mark, and below the 0.55 publish floor. The other three were rejected as
malformed: `LJ811E9`, `131`, `W3301`.

**Not enabled.** Two-stage genuinely recovers candidate text the single-stage
path misses entirely — that part is real. What it recovers on this estate is not
of publishable quality, at roughly **three times the cost**. Turning it on would
increase the volume of low-confidence malformed reads flowing into per-track
voting, and a garbage string that repeats across frames can pass a vote that a
single garbage string cannot. The failure mode of shipping it is a **confidently
wrong registration mark**, which is the worst output this system can produce.

The measurement is worth keeping because the conclusion is estate-specific, not
universal. On a camera mounted for ANPR — where plates are 100 px rather than
46 — the same change would help substantially, and it would be enabled per
camera by capability grade rather than globally.

### Two features measured and declined in two days

Wrong-way detection (CR-022) and two-stage ANPR, both on evidence, both
recorded. The discipline is the point: a junction detector firing on lawful
turns and an ANPR path emitting `WA3111` at 0.48 would each look like capability
in a demonstration and be a liability in use.

---

## CR-024 — Government integration, and the alerts a camera cannot raise
**Date:** 2026-09-03

The challenge FAQ names five systems — VAHAN, SARATHI, eGujCop (CCTNS), AFIS,
NAFIS — and six alert categories: arrested persons, stolen vehicles, wanted
criminals, missing persons, unidentified bodies, fingerprint matches.

Listing eleven things is easy. The work worth doing is saying which of them a
**camera** can trigger, because they are not equivalent:

| Category | Keyed on | A camera can raise it |
|---|---|---|
| stolen_vehicle | registration mark | **yes** — this is what ANPR reads |
| vehicle_of_interest | registration mark | **yes** |
| wanted_person | face | no — this system does not perform face recognition |
| missing_person | face | no — same |
| unidentified_body | record | no — an investigator matches these, not a camera |
| fingerprint_match | fingerprint | **no camera on any estate captures one** |

**Two of six.** A platform claiming all six would be claiming something
physically impossible, and the last row is the clearest case: AFIS and NAFIS are
named in the requirement, are genuinely useful for *enrichment* of a person
already identified, and cannot be driven by CCTV under any configuration. Saying
so precisely is worth more than an integration diagram with five boxes.

`saakshya.watchlist.government` carries a typed contract per source — what it
provides, what it keys on, its record shape, its refresh expectation, and
exactly what is required before it can be connected. `GET /system/integration`
reports the position, and `connected` is `[]`.

The adapters **raise rather than returning an empty list**. An empty list is
indistinguishable from a working integration over an empty registry, and would
let a demonstration show one that does not exist. Each refusal names what is
missing, so an integration conversation with a department starts from a list
rather than a demand.

Fourteen tests, including that face-keyed and fingerprint-keyed categories are
never actionable, that a configured endpoint without a client still refuses, and
that representative records are labelled `REPRESENTATIVE` at the point of load.

---

## CR-023.1 — The output report the submission requires
**Date:** 2026-09-03

FAQ Q33 asks for "an output report showing detected vehicles or number plates
with corresponding timestamps". `tools/verify/detection_report.py` produces it
from the live store as CSV, Markdown and JSON.

**13,745 detections across 12 cameras, 2 carrying a registration mark**, over a
window from 01:24 to 13:21 UTC. Seventeen columns: timestamp, camera, name,
district, position, object type, colour, mark, plate confidence, votes, quality,
time band, observation and evidence ids, model version.

It reports **vehicles as well as marks**, deliberately. A report of plates alone
would show two rows and imply the system saw almost nothing; it saw thousands of
vehicles, and what it could not do on most cameras is read their registration
marks. The report names the cameras graded UNSUITABLE for ANPR so a reader
attributes the gap correctly.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P3** | The `time_band` column was always empty — there is no stored band, and an always-blank column reads as data the system failed to capture rather than a field that does not exist. | Derived from stored luminance the way the grader bands it, and the derivation is stated. **10,727 DAY, 2,656 LOW_LIGHT, 189 NIGHT.** |

---

## CR-023 — Every presentation number, traced to its run
**Date:** 2026-09-03

`make measured-results` assembles `docs/MEASURED_RESULTS.md` — **54 figures
across nine sections, none typed by hand**, each read from a report file or the
live store and each carrying the artefact it came from. A figure with no source
is printed as **not measured** rather than dropped, so a gap stays visible.

§77 requires live metrics and forbids substituting synthetic ones. This reads
only from the live store and from live-run reports.

### Three aggregation faults in my own tool, all found by reading its output

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | `(c.get("mean_chroma") or 1.0) < 0.04` counted monochrome cameras as colour. A perfectly monochrome camera measures **exactly 0.0**, which is falsy, so the `or` replaced it with 1.0 — the idiom mishandles precisely the cameras being counted. Reported **8 of 29** where the truth is **13 of 29**. | Explicit `is not None`. |
| 2 | **P1** | Capability was counted **per camera per time band**, so an estate of thirty reported "94 UNKNOWN". Anyone reading it would take it as ninety-four cameras. | Collapsed to the whole-day band and counted cameras: **20 UNKNOWN, 10 UNSUITABLE** for ANPR. |
| 3 | **P2** | Each ingest report was labelled by what the file was once called and summarised from its **last** stage, so a run whose final stage was four cameras printed as "30-camera run: 4 for 7.0 min". | The label comes from the run — largest stage by cameras then frames — and reads "8 cameras, 5.0 min". |

The first would have put a wrong count on a slide with a plausible-looking
source beside it, which is worse than having no number at all. All three are the
same failure this project keeps meeting: **a line that reports what the code
meant to compute rather than what it computed.**

---

## CR-022 — Wrong-way detection: measured, and declined
**Date:** 2026-09-03

§62 permits additional analytics once the mandatory path is strong, and asks for
the best two or three from wrong-way, stopped vehicle, restricted zone, traffic
anomaly and intrusion. **Do not demo unreliable analytics** is part of the same
instruction, so the first question was whether this grid supports any of them.

Wrong-way looked the most attractive: it needs no zone configuration, because the
dominant flow can be learned from the traffic itself. That is exactly the kind of
self-calibrating feature this estate rewards.

**It is not supportable here, and the data says so plainly.** Directional
concentration across 13,658 real observations on eight cameras:

| camera | observations | R | verdict |
|---|---|---|---|
| cam05 | 3,170 | 0.33 | too scattered |
| cam16 | 2,142 | 0.27 | too scattered |
| cam01 | 2,143 | 0.26 | too scattered |
| cam21 | 406 | 0.26 | too scattered |
| cam13 | 1,467 | 0.17 | too scattered |
| cam14 | 2,001 | 0.07 | too scattered |
| cam02 | 1,528 | 0.07 | too scattered |
| cam04 | 716 | **0.04** | essentially uniform |

Median **R = 0.22**. A usable flow model needs roughly 0.6; a two-way road shows
two tight lobes about 180° apart. These show a broad smear across most of the
circle.

Two causes, and both matter:

- **`direction_deg` is a smoothed frame-to-frame velocity**, not a track's net
  displacement. Its own docstring calls it *"a weak association signal"*, and the
  measurement agrees. It is used to reject implausible transitions, which it is
  good enough for.
- **These cameras are at junctions** — Chimanbhai Bridge, Paldi Junction, Visat T
  Junction, Char Chowk. Traffic there legitimately travels in many directions. A
  wrong-way detector assumes a dominant flow that a junction does not have.

**Nothing was built.** A feature that fires on lawful turning traffic at a
four-way junction would produce alerts an operator learns to ignore, and every
other alert in the system would be devalued with it. The measurement is recorded
so the decision can be revisited if cameras on straight carriageways are added —
where the same model would likely work well.

An arterial-road camera would be the test. This estate does not currently have
one in the observed set.

---

## CR-021 — One command for the whole evaluation
**Date:** 2026-09-03

`make live-evaluation PLATE=…` takes a panel-supplied registration mark through
every stage the scenario asks for, against the live store, and reports what
actually happened at each. Ten stages: estate, capability, case, watchlist,
search, timebase, trajectory, alert, evidence, audit.

**Measured on `GJ38BH5815`, 0.02s end to end:**

```
estate       30 cameras onboarded, 19 with a position, 13 streaming
capability   ANPR grades: 25 UNKNOWN, 5 UNSUITABLE
watchlist    1 active entry, authority named — an entry with none cannot be created
search       1 observation                                            3.4 ms
timebase     seen on cam21 only; a single sighting has no interval to reason about
trajectory   1 hypothesis, CONFIRMED at 0.767, timebase RESTRICTED    1.4 ms
alert        1 raised; 0 suppressed as too weak, 1 deduplicated
evidence     1 record sealed; hash chain VERIFIES
audit        7 actions: case_open, search_plate, trajectory_build
```

It is deliberately willing to report failure. On a mark never seen it produces a
complete report saying so — *"no stored observation carries GJ07XZ4409. That is
an absence of evidence, not evidence the vehicle was absent"* — with trajectory
*not attempted*, no alert, and the two audit entries that search still generated.
A harness that could not produce that would be worthless for judging the runs
that do find something.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P2** | The audit stage guarded its lookup with `hasattr` for an accessor that does not exist, found nothing, and printed **"0 action(s) recorded … each with actor, role, purpose and result count"** — a description of the contents of an empty list. It would have reported a broken audit path as a clean run. | Reads `audit_log` directly and names the actions found. An empty result now reports itself as *a fault in the audit path, not a quiet pass*. |
| 2 | **P2** | For a single sighting it printed "no two of them were shown to share a timebase" — stating a failure that does not arise, and reading as a defect in the estate rather than as arithmetic. The same mistake was fixed in the trajectory panel two days ago and reappeared here. | Three distinct summaries for none, one, and several cameras. |

Both are the same error the project keeps finding: **a sentence that describes
what the code meant to check rather than what it checked.** The first would have
been invisible in a demo — the line reads like a pass.

---

## CR-020 — Evidence that carries imagery
**Date:** 2026-09-03

Every evidence record this system had produced was `METADATA_ONLY`. Not a
shortcut — the government grid is live and not seekable, so by the time an alert
fires the moment is gone and cannot be fetched back. The record attested what the
system observed and when, said so on its face, and was not a copy of the footage.

`saakshya.evidence.rolling` closes that for the sightings that matter, without
retaining government video at large. The constraints are the design:

- **Bounded per camera, in bytes.** Thirty cameras at 1080p is 6 MB a frame raw;
  ten seconds of that is gigabytes and the next outage. Frames are held JPEG
  encoded and evicted by total size, not count, because frame size varies by an
  order of magnitude across this estate — a random 320×240 frame encodes to 75 KB
  and a flat one to 2.5 KB.
- **Only analysed frames.** Buffering every decoded frame multiplies memory by
  the decode rate for no evidential gain.
- **Nothing on disk without an event.** A camera that never triggers an alert
  never writes a byte of imagery.
- **Pre and post.** An investigator needs the approach as well as the moment.
  Post-event frames arrive after the trigger, so a capture stays open and
  completes as they land — an alert delayed to spare its evidence is the wrong
  trade.

### Measured on the live grid

```
[inject] stamped GJ38BH5815 onto live observation OB01M1J0MVEA6G5YA1RHGXM65Z0D from cam01
    ALERT  GJ38BH5815 on cam01 — stolen_vehicle, confidence 0.842
    EVIDENCE OB01M1J0MVEA6G5YA1RHGXM65Z0D: 12 frame(s) retained (6 before, 6 after)
```

**12 frames, PTS 2.811s to 7.215s — 4.4 seconds of stream time, 3.1 MB, each
SHA-256 hashed.** The frames, the watchlist match, the alert engine and the
retention are all real; only the plate string was injected, because **no plate
was read from these cameras during the window** — 826 observations, zero with a
mark. That is a property of this grid at this hour and it is stated in the
capture's own reason field rather than glossed.

The manifest carries its own caveat: frames are re-encoded to JPEG from the
decoded picture, so the hashes cover **what was retained, not the original
compressed bitstream**, and the window is what could be preserved rather than a
selection from a recording.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P2** | A run whose camera selection matched nothing sat for its **full duration** reporting `streaming=0/0` — which reads as a system working on an empty estate rather than a run that never started. Observed for five minutes against a transient probe failure. | Refuses to start, exits 2, and says which of the two it was: no camera answered, or none matched `--only`. |
| 2 | **P2** | A single empty probe produced a zero-camera run. The same enumeration a minute later returned all thirty — the grid refuses connections briefly under repeated probing. | Three attempts with backoff before concluding the estate is unreachable. |
| 3 | **P3** | My own test asserted the buffer bound as `budget`, when the buffer deliberately keeps the newest frame however large — an event arriving now needs the picture from now. | The real contract is **budget plus at most one frame**, now stated in the docstring and asserted, so a caller sizing memory for a large estate reckons on the frame. |

Fourteen tests in `tests/unit/test_rolling_evidence.py`, including that nothing
reaches disk without an event, that another camera's frames never enter a
capture, and that an event with an empty buffer returns **nothing** rather than
an empty record.

---

## CR-019 — "Runs offline" enforced rather than argued
**Date:** 2026-09-02

This system claims repeatedly that it runs with no route to the internet, and
that claim had been argued from design. It is now enforced: `tests/e2e/test_no_network.py`
**blocks every non-local socket connection and DNS lookup**, then runs the
mandatory chain — search, watchlist, alert, evidence, chain verification, the
assistant, and model loading. Anything that reaches out fails loudly instead of
quietly working on a developer laptop that happens to have a connection.

Eight tests, the first of which asserts **the block itself works**. Without it
every other test in the file could pass by doing nothing.

The reason for enforcement rather than inspection is on the record: a single
`from_pretrained` without `local_files_only` produced a twelve-minute hang at 0%
CPU with no error, on a machine that could open a socket to a host that never
answered. Design intent did not prevent that; a test that refuses the network
would have.

### Where the seven days stand

Fourteen of fourteen release gates pass — lint, typecheck, model activation,
secret scan, licence policy, unit, security, integration, ML regression,
end-to-end, query plans, API latency, clean install, ANPR evaluation — in 1,563s.

The live grid is unchanged at **30 of 30 cameras reachable**; nothing beyond
cam30 has appeared, so the ~50 cameras the scenario mentions are not yet
published.

**Not done, and not claimed:** the cloud-GPU model experiments of §23 and §55.
They need Google Cloud or Hugging Face inference credentials this deployment
does not hold, and the honest position is that stronger vehicle retrieval has
been *specified* and not *benchmarked*. The measurement that exists —
DINOv2 at 0.831 balanced accuracy with overlapping distributions — stands as the
reason appearance is used for ranking and never for identity.

---

## CR-018 — Red team: the database can fail and the capture must not
**Date:** 2026-09-02

Attacking the resilience claims of §44–§49 rather than writing a document about
them. The database was the one that broke.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | `store.add_observations()` in the live consumer loop had **no error handling**. A transient failure — the database locked by another writer, a full disk, a lock timeout — propagated out of the loop, stopped every camera, and ended the run. Two captures have already been lost whole to faults of this shape; this was a third waiting to happen, and §47 forbids it explicitly. | Observations are buffered and retried. A failure holds them for the next attempt instead of propagating. The buffer is **bounded at 20,000**, because an unbounded retry buffer in a process already holding thirty decoders is the next outage — when it fills, the oldest are dropped and counted. Losing the oldest few observations is recoverable; losing the run is not. |
| 2 | **P1** | Watchlist evaluation ran unguarded on the same path, so a fault in alerting would also have ended the capture. | Contained and logged. A fault in alerting loses one alert; a fault that propagates loses the capture. |
| 3 | **P2** | A run that lost data had no way to say so. | The stage report states write failures, observations still unwritten, and observations dropped after the buffer filled. |

### Measured against the live grid

A real capture of cam01 and cam04 with the store failing underneath it —
**153 injected write failures across a 50-second total outage**:

```
[fault] first write seen; injecting failures for 50s
    store write failed (RuntimeError: database is locked); 1 observation(s) held for retry
    streaming=2/2 frames=761 observations=1
[fault] window over after 153 injected failures
    streaming=2/2 frames=1,487 observations=260      <- the held observations land
    ...
    observations   : 885
    store          : 153 write failure(s), 0 still unwritten, 0 dropped
```

**885 observations persisted, nothing lost**, cameras never dropped, and the run
reported exactly what happened. Before this change the first failure would have
ended it.

### A note on the fault injector

The first version armed the fault on wall-clock time from launch and injected
**nothing** — model loading dominates start-up, so the window elapsed before the
stage began, and the test reported success having tested nothing. It now arms on
the first successful write. This is the third time today a test has passed while
exercising nothing; the pattern is worth naming, because each time the failure
looked exactly like a pass.

---

## CR-017 — Security demonstrated by attack, and a provider that took the app down
**Date:** 2026-09-02

`tools/verify/security_scorecard.py` performs the forbidden action for each of
the six properties in §66 and passes only when it is refused. **14 of 14.** A
control that has never been attacked is a claim, not a control.

| Property | Attempted | Refused with |
|---|---|---|
| Unauthorised search | no credential / operator role / no stated purpose | 401 NOT_AUTHENTICATED · 403 PERMISSION_DENIED · 400 PURPOSE_REQUIRED |
| Wrong jurisdiction | read a camera outside the caller's districts | 403 OUT_OF_JURISDICTION |
| Watchlist mutation | add an entry as investigator, operator, auditor | 403 on each |
| Watchlist integrity | add an entry with no stated authority | 422 — it cannot be created at all |
| Evidence access | read the chain as an auditor | 403 |
| Separation of duty | search as an administrator | 403 — running the system is not investigating people |
| Secret leakage | probe six endpoints, including an error path and a malformed query, for two planted canary values | none leaked |
| Prompt injection | four instruction-shaped payloads as if read from a plate | 4 of 4 reported as data |
| Prompt injection | ordinary plate reads and camera names | 0 false alarms |

The last line matters as much as the one above it: a scanner that flags
everything gets ignored, and then flags the real one into a wall of noise.

### The bug it found

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | An AI provider failure produced a **500 Internal Server Error**. An HTTP 401 from Anthropic propagated straight out of the request handler — the assistant's dependency became the application's failure, which is exactly what "no core feature depends on an external LLM" is supposed to rule out (§44). | Provider failures degrade to the deterministic rule backend over the same tools, so a question that can be answered without a model still is. Ten tests across four failure modes — HTTP error, timeout, connection failure, malformed response. |
| 2 | **P2** | After falling back, the answer still reported `backend: anthropic`. A reader would take an answer produced by rules as having come from a model. | The **answering** backend is reported: `rules (fallback)`. The warning names the provider, the failure type, and states that search, trajectory, watchlist, alerting and evidence are unaffected. Silently swapping the engine underneath a user is its own kind of dishonesty. |
| 3 | **P3** | The failure warning was appended once per reasoning step. | Deduplicated. |

**How it surfaced** is worth recording. Nothing in the injection test found it.
The scorecard plants decoy secrets to check for key leakage, and the decoy looked
enough like an API key that the provider gateway selected the external backend —
which then failed against the real endpoint. A test written for one property
exposed a fault in another, because it put the system into a configuration
nobody had tried.

Also confirmed in passing: the tokens minted eight hours earlier had expired, and
every request returned 401 until they were re-minted. Token TTL works.

---

## CR-016 — The cases where the right answer is "no"
**Date:** 2026-09-02

Most testing asks whether a system finds what is there. `tools/verify/wrong_cases.py`
asks what it does when it should find nothing, which is where a public-safety
system earns or loses trust. Eleven cases, all correct on the live store:

| Case | Refusal |
|---|---|
| A valid mark never seen | nothing found, and no claim about where the vehicle was |
| A malformed mark | nothing found, no error |
| An expired watchlist entry | no match — past its validity is not authority to act |
| A revoked watchlist entry | no match |
| A read too poor to act on | no alert, and the suppression **counted** rather than hidden |
| A camera graded able to read plates | only ever GOOD on measured samples |
| A camera never exercised | absent from grading, not good by default |
| Two cameras with no shared timebase | **RESTRICTED** — no invented clock |
| Two cameras in one measured cluster | **ALLOWED** — the refusal is not a blanket one |
| A camera whose own timing is unreliable | **REFUSED** — cam21, from its own 36 PTS regressions |
| A camera never observed | unknown, never healthy |

A refusal is only useful if it is *specific*. "No observations", "this camera
cannot read plates" and "these two cameras never shared a clock" are different
findings, and an investigator acts differently on each.

### Testing the tests (§75)

A harness that passes on a broken system is worse than none: it converts an
absence of checking into a claim of correctness. Nine tests break one safety
property each and assert the harness goes red — including the most dangerous
failure of all, a search that invents a sighting.

Writing them found that **two of my three mutations changed nothing**:

| Attempted mutation | Why it did nothing |
|---|---|
| Patch `VehicleOfInterest.is_valid` | Nothing on the matching path calls it. The seam is `active_at`. |
| Patch `AlertPolicy.min_confidence` on the class | A dataclass's generated `__init__` closes over the default, so `AlertPolicy()` still returned 0.55. The seam is the constructor. |

Both tests passed while proving nothing, which is exactly the failure mode being
guarded against — found only because the harness kept reporting PASS after the
system was supposedly broken.

A third mutation revealed something better than a bug: removing the SQL status
filter did **not** let a revoked entry match, because `match` asks each entry
`active_at` as well. Revocation is enforced twice. That is now asserted as
defence in depth, with a second test confirming the harness notices when *both*
layers fail.

One harness case was also wrong: it asserted that some camera happens to be
graded UNSUITABLE, which is a property of the data and fails on a fresh install
for a reason that says nothing about the system. It now asserts the property
that matters — no camera is graded able to read plates without samples behind it.

### Low-bandwidth, measured rather than modelled (§64)

`tools/live/bandwidth.py` demuxes packets off the wire — not decoded, so it
measures the link and not this host — against observation sizes taken from 400
real records carrying full provenance, because a stripped example would flatter
the result.

**Measured: 1.36 Mbps of video against 0.071 Mbps of observations — 19x.**

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | The first version reported **1,421x**. It averaged the event rate across everything in the store, which divides by the idle hours between capture runs — an order of magnitude of flattery, in precisely the quantity being measured, and a number that would have gone on a slide. | The event side is measured at the **busiest 60-second window**. Provisioning a link is decided by the busiest minute, not by the average including nights when nothing ran. |

19x remains a strong argument for metadata-first. It is one point, on three
cameras, at one hour of one night, and both sides move with scene activity — a
busy junction produces more events *and* more video.

---

## CR-015 — A stream that decodes into garbage, and a detector that cried wolf
**Date:** 2026-09-02

### The finding

cam21 delivered 1,628 frames over fourteen minutes, 777 of them analysed, and
produced **zero observations**. The decoder reported **zero errors**. Every
health counter said the camera was fine: frames arrived, decode succeeded, no
warnings. The frames were garbage — heavy macroblock artefacts and lost chroma,
the picture a decoder builds from stale data when reference frames go missing on
a lossy link. H.264 conceals rather than failing, by design.

**An investigator told "cam21 saw no vehicles" concludes the road was clear. The
truth was that the camera could not be seen through at all.** Those are opposite
findings, and nothing in the system could tell them apart.

It surfaced only because of the UNEVEN YIELD warning added earlier the same day,
which names a camera that decoded frames and produced nothing.

### A correction to the record

I reported that cam21 had "reached daylight" and ran a daylight ANPR validation
against it. **That was wrong.** The camera's overlay reads `14-06-2026 02:35` —
night. My daylight test was frame luminance, and the washed-out grey of the
corruption read as brightness. The heuristic measured the damage and called it
sunlight. The validation ran, and measured nothing about daylight.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | A stream can decode without a single error and deliver concealment. Nothing detected it, and its silence was indistinguishable from an empty road. | `saakshya.analytics.corruption` keys on two signals a real scene does not produce: discontinuity concentrated on the codec's 16px macroblock grid, and rows of saturated chroma with no scene detail. Measured on this grid — corrupt cam21 **2.22**, clean cam16 **1.00**, clean cam04 **1.00**. Sampled on the live path and reported per camera. |
| 2 | **P1** | **The detector condemned a working camera.** On its first live run it declared cam16 corrupt — a camera that produced **375 usable observations in that same run**. Reading a flagged frame settled it: a perfectly good picture of Visat T Junction with fifteen visible vehicles and localised damage on one auto-rickshaw. | A symptom in a frame and a verdict about a stream are different questions. A frame reports "macroblock artefacts present"; a stream gets a verdict from a **rate over ≥25 samples** — CORRUPT ≥80%, DEGRADED ≥35%, OK below — set with margin either side of the measured gap (cam21 **97%**, cam16 **27%**, cam01 **13%**). |
| 3 | **P1** | The false alarm rested on **10 of 15 samples** — an unlucky draw from a 27% rate. | Below the minimum, the verdict is **UNKNOWN and never OK**: "we did not look hard enough" and "it is fine" are different findings. |
| 4 | **P2** | With UNKNOWN correctly returned for small samples, a four-minute run yielded ~21 samples per camera and reported *nothing* — including the genuinely corrupt stream. A threshold that is right in principle and unreachable in practice protects nobody. | Sampling raised from one analysed frame in twenty to one in eight, chosen from what a real run yields rather than from what felt cheap. ~60 samples per camera per four minutes, at about 3 ms each. Decode quality now prints on **every** camera row, not only on warning: a reader comparing observation counts needs to know whether both cameras were seeing the road. |

### Three more, found by writing the tests

All in the direction of false alarms, all fixed before the detector went near the
live path:

- A smooth gradient measured **4.01** and would have condemned a camera pointed
  at a flat wall. The ratio's denominator can approach zero.
- Perfectly constant blocks measured **1.0** and read as *clean* — the very
  artefact being hunted, invisible to the metric.
- The chroma-band check measured spread **across colour channels**, so a
  uniformly green row scored as "detailed" and was rejected. The check could
  never have fired on the thing it was written for.

A ratio is now believed only alongside an absolute difference a person could
see. One fix belonged in the fixture rather than the thresholds: the "clean"
test frame was a noiseless sinusoid whose quantisation steps beat against the
16-pixel grid. No camera produces a noiseless image, and a detector calibrated
against imagery with no noise floor is calibrated against nothing real.

---

## CR-014 — P0: live capture died of a torch MPS data race
**Date:** 2026-09-02

**The most consequential bug found on this project.** Two live captures of the
government grid — twenty-five and twenty-two minutes — died having produced
nothing. No Python traceback, no error, no partial results. The store was
unchanged and the log ended mid-way through building the second camera pipeline.

### What it actually was

Not memory pressure. I said memory pressure the first time, on the reasoning
that a VLM benchmark and the release gate had been running alongside — plausible,
and wrong. The second death happened with **nothing else running at all**, which
is what forced a proper diagnosis.

The macOS crash report says `SIGSEGV`, `EXC_BAD_ACCESS`, `KERN_INVALID_ADDRESS`,
and the faulting thread is unambiguous:

```
at::native::mps::MetalShaderLibrary::exec_unary_kernel
at::native::rsqrt_kernel_mps
at::_ops::rsqrt::call
torch::autograd::THPVariable_rsqrt
```

PyTorch's Metal backend keeps a lazily-populated shader cache that is **not
thread-safe**. Six camera workers calling MPS operations concurrently corrupt its
hash table and the process dies inside the allocator.

It is a race, which is exactly why it was so hard to see: **one camera always
worked, eight worked once, six died twice.** Every test passes, because the test
suite exercises one pipeline at a time.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | Concurrent MPS inference from camera worker threads segfaults the process. Two live captures lost; the failure is silent and leaves no artefact to diagnose from. | MPS inference is serialised at `_timed`, the single funnel every backend call already passes through, so no call site can forget. CPU and ONNX Runtime stay concurrent — both are thread-safe, and locking them would throw away real parallelism on a ten-core host. The GPU is a single serial resource; concurrent submission from Python threads buys nothing on this device and cost the process. |

**Measured after the fix**, on the exact capture that had died twice:
`streaming=6/6 frames=2,234 observations=272` and climbing, where the previous
two runs produced **zero**.

Five tests in `tests/unit/test_mps_serialisation.py`, including one that eight
concurrent MPS callers never overlap, one that CPU callers *do* overlap — so the
first cannot pass by nothing running concurrently at all — and one that a raising
frame releases the lock rather than wedging every camera behind it.

### The correction worth recording

I diagnosed this as memory pressure and wrote that into a status report. The
evidence at the time was circumstantial — three heavy jobs, a 24 GB machine, a
process that vanished — and I did not look for a crash report, which would have
settled it in a minute. The resource scheduler built on that diagnosis is still
worth having and prevents a real class of failure, but it was not the fix for
**this** failure, and for some hours the project had a plausible explanation
standing in place of the true one.

---

## CR-013 — Admission control, a command surface, and an explicit AI switch
**Date:** 2026-09-02

Three pieces of the final directive, and one bug I wrote and caught in the same
hour.

### Resource scheduling — so a live run is never lost again

A twenty-five minute capture of the government grid was killed without a
traceback while a VLM benchmark and the release gate ran beside it on a 24 GB
machine. It produced nothing, and the failure was invisible until the store was
inspected. Nothing in the system knew the three jobs coexisted, and they are
separate processes, so no in-process semaphore could have known.

`saakshya.runtime.scheduler` is a lease directory shared across processes. Four
classes, ordered by right to the machine:

| | |
|---|---|
| **A_LIVE** | live government ingestion — never refused, never displaced |
| **B_INTERACTIVE** | the API serving an operator — never blocked |
| **C_BENCHMARK** | model and VLM benchmarking |
| **D_VERIFY** | release tests and verification |

C and D refuse to start beside A and say so **in a second**, with exit code 75
and the name and pid of what holds the machine. Leases self-heal: one left by a
hard kill is reclaimed on the next check, so a crash cannot wedge the estate.
`make jobs`, `make live`, `make benchmark`, `make verify`, `make release-check`,
and `WAIT=<seconds>` to queue rather than be refused.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | I wrote the blocking relation **backwards** — mapping A to the classes it displaces rather than mapping each class to what refuses it — so a benchmark and a release gate started beside a live capture on the first run. Exactly the situation the scheduler exists to prevent, and it read plausibly either way. | Direction corrected and **asserted at import**, not merely commented. Sixteen tests, including one that the live class is blocked by nothing and one per heavy class that it yields to A. |
| 2 | **P2** | The memory rule applied to every class, so a fat benchmark could refuse a government evaluation run — inverting the priority the whole scheme exists to express. | A_LIVE is admitted over budget with a warning naming the jobs to stop. Refusing there is safer for the process and wrong for the deployment. |

### A command surface, not a camera wall

The product opened on a search box with a thirty-camera grid behind it. It now
opens on the question an officer actually arrives with. Seven places —
**Overview, Investigate, Alerts, Evidence, Cameras, Analytics, System** — and a
landing page ordered as the questions arrive: what needs attention, what is
being worked, the estate, whether the machinery is sound, the map, recent
activity. A health dot in the navigation makes a degraded subsystem visible from
every screen without anyone going to look for it.

New `/system/health` reports seven subsystems, each with the evidence its
verdict rests on. **UNKNOWN is never rendered as HEALTHY** — a dashboard that
shows green because it never checked converts ignorance into assurance. On the
live store it correctly reports DEGRADED: 12 of 30 cameras streaming, 18 never
ingested, so their state is unknown rather than good.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 3 | **P2** | The home screen claimed **"112 learned transitions"**. `edges_total` counts geography-seeded neighbours alongside observed ones; the graph had learned **nothing** — 0 observed, 0 trusted, 112 seeded. On the primary screen, that reads as evidence the system does not have. | Shows transitions learned from sightings, with seeded-but-unproven links stated separately. |
| 4 | **P2** | The overview map drew a bare graticule while the other two showed Gujarat, because basemap configuration was fetched once at boot and not kept for maps built later. It reads as a broken panel, not a deliberate offline mode. | Basemap options are held in state and given to every map. |

### AI_PROVIDER, stated rather than inferred

`AI_PROVIDER` is now the single switch: `disabled` / `local` / `anthropic` /
`gemini` / `auto`. A deployment states its choice instead of having one inferred
from whichever key happens to be set. A Gemini backend joins Anthropic, and both
translate a tool schema and a response shape and nothing else — every judgement
about what is safe to say stays in the orchestrator, where it is testable
without a network.

Neither is authoritative for plate identity, watchlist matching, trajectory or
evidence validity. The default remains **local rules**, because for government
CCTV the configuration where no data leaves the system should be what you get
without asking. A named provider whose key is missing degrades to local rules
with a warning rather than failing every question, and a misspelled value is
reported rather than silently enabling anything. Thirteen tests.

---

## CR-012 — Two ways a new column breaks a working system
**Date:** 2026-09-02

Both found by the release gate, after every unit, security and integration test
had passed. Neither is visible to a test suite run against a current database in
a fully provisioned environment — which is exactly why the gate builds a clean
one.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | Adding a nullable `cameras.location_note` broke `tools/perf/query_plans.py` with `OperationalError: no such column` — a raw driver error naming neither cause nor cure, raised inside a SELECT minutes into the gate. Five tools opened a store and queried it **without ever calling `create_all()`**, which is the migrator. They worked perfectly against a current database and broke against any older one — which is everybody's, later. | All five migrate on open; `create_all()` is additive and idempotent. A guard test walks every tool's AST and fails any that constructs a `Store` without migrating it, and includes a test that the guard itself can fail. |
| 2 | **P1** | `tests/unit/test_landmark_notes.py` imported a tool whose module scope imported `torch`, so **the clean-install gate broke**: it installs the package without ML extras and runs the unit tests. The pure text logic being tested — matching signage against a label, wording the resulting note — has nothing to do with torch. | Heavy dependencies (`torch`, `PIL`, `transformers`) are imported where they are used. Verified by importing both tools with `torch` and `transformers` blocked from `sys.meta_path` and exercising the pure functions. |

**A note on `pending_migrations()`.** It did not catch finding 1 and was not
wrong to miss it: by contract it reports only columns that *cannot* be added in
place. A nullable column is invisible to it. The lesson recorded here is that
**"no pending migrations" does not mean "schema is current"** — the two
questions are different, and the second one is answered by running the migrator,
not by asking.

---

## CR-011 — Cameras corroborate their own positions
**Date:** 2026-09-02

Nineteen cameras were placed from their names alone and recorded as
`DERIVED_FROM_NAME`. Honest, but weak: a name is a label someone typed, and
nothing had checked it against the picture. The picture often settles it — a
junction camera sees road signs, hospital boards and hoardings, in Gujarati and
English.

Read with the **local** vision-language model, two frames per camera, entirely
on this host:

| Verdict | Cameras |
|---|---|
| **CORROBORATED** | 8 — cam01 Chiman bhai Bridge, cam03 O.N.G.C. Office, cam04 Paldi Circle ("PALDI JUNCTION", "V.S. Hospital"), cam05 Visat teen Rasta, cam10 Char Chowk, cam13 CN Vidhyalaya, cam15 Suvidha Park, cam16 Visat T Junction |
| **NO OVERLAP** | 5 — including cam06, labelled *Timbavadi Gate*, whose view names "Madhuram Bypass Road"; and cam09, labelled *New Bypass Circle 2*, whose view names "Vadla Fatak" |
| **NO SIGNAGE READ** | 13 |
| Unreachable in both passes | 4 |

Two cameras with **no recorded name at all** gained their first positional
evidence: cam25 reads "GRAM PANCHAYAT", cam30 reads "Cafe Coffee Day, Hiralal,
Parakh".

**Nothing was moved.** Turning a hoarding into coordinates without a gazetteer
would be inventing precision, which is the failure this project exists to avoid.
The finding is recorded in a new `location_note` column beside the coordinates,
and shown in the camera panel with the position's precision and basis, so anyone
relying on a position can see what it rests on without leaving the screen.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | A stalled camera stopped the whole pass. `ThreadPoolExecutor.map` waits for every task, so one stream stuck inside `decode()` held the run indefinitely — observed at 0.3% CPU with no output, indistinguishable from a crash. | Each camera now bounds itself with its own deadline, and the pass abandons the pool rather than joining threads blocked in a C extension. A stalled camera is reported as stalled and the run finishes. |
| 2 | **P1** | The first bounded version used a **single global deadline** while cameras ran six at a time, so eighteen were reported as "no frames" when they were simply queued behind slower ones — a measurement about the scheduler presented as a measurement about the estate. Recovered fourteen of them on a second pass once the bound became per-camera. | Per-camera deadline; the pass-level budget now only covers the queue. |
| 3 | **P2** | Long-running tools **flushed nothing** when redirected to a file. Block buffering meant an operator saw no output at all until the end, which is indistinguishable from a hang — and cost real time diagnosing one that was not there. | Progress lines flush as they are written. |
| 4 | **P2** | The label matcher extracted only four-letter runs, so "O.N.G.C. Office" retained no distinctive token and a reading of "O.N.G.C. Office BS-103 B1" was reported as *disagreeing* with it. Tightening it to whole-token matching then broke "Suvidha Park" against "Suvidhapark". | Both tests, because either alone loses real matches: whole-token overlap after punctuation is stripped, **and** substring containment. Signage is written by whoever painted the board and does not agree with a registry on spacing. |
| 5 | **P2** | A camera with no recorded name was told its signage "does not match the recorded label" — asserting a conflict with a label that does not exist. | Three distinct wordings: corroboration, disagreement, and first-evidence-for-an-unnamed-camera. Eleven tests in `tests/unit/test_landmark_notes.py`. |

---

## CR-010 — Live-grid capability: timing, offline loading, honest verdicts
**Date:** 2026-09-02

Work driven by the organisers' published test scenario, which asks for a
*complete route traversed by the designated vehicle, including timestamped and
location-wise movement history*, and for *continuous* watchlist
cross-referencing.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | Model loading **hung indefinitely** with no route to huggingface.co. `from_pretrained` reaches for the hub before falling back to cache, and where a host can open a socket but nothing answers, that reach does not time out promptly. Observed directly: a tool at **0% CPU and 58 MB RSS for twelve minutes**, model never loaded, no error. This system is explicitly designed to run on a network with no internet route, so it is a deployment-blocking fault, not an inconvenience. | Cache first, everywhere: weights are pinned by revision, so the hub offers nothing the cache does not already hold. The network is now a deliberate fallback for a first fetch, and `SAAKSHYA_MODELS_OFFLINE=1` removes it entirely so an air-gapped deployment fails immediately with a clear message instead of hanging. Model load went from a twelve-minute hang to **4.6 s**. |
| 2 | **P1** | A **single-camera route reported "All cameras on this route share an established timebase"**. The pairwise loop never executes for one camera, so the verdict kept its ALLOWED default — vacuously true, and read by anyone as a positive finding about a camera that belonged to no cluster at all. | A route of one now states that there is no interval to reason about and therefore no shared timebase is claimed, and says separately whether that camera's own timing has been established. |
| 3 | **P1** | Timebase health was written **only** by the separate profiling pass. Long live ingests — the runs that actually exercise the grid — measured PTS regressions and threw the evidence away, so `usable_for_correlation` stayed false for every camera however much data was collected, and cross-camera correlation could never switch on. | Ingest records timebase health for every camera at the end of a stage, alongside stream health, carrying cluster membership forward untouched. `tools/admin/backfill_timebase_health.py` recovers the runs that happened before it did. |
| 4 | **P2** | The clock parser understood only `dd-mm-yyyy`, silently discarding three legible readings in other formats (`2026-06-13 10:34:19 PM`, `2026-08-04 08:56:55`). A camera whose clock cannot be read is excluded from every cluster, so a parser gap costs correlation directly. | Widened to `yyyy-mm-dd` and 12-hour AM/PM. Two cameras recovered without opening another stream — the raw text was already captured, so the fix was re-derived from it. |

### Capability unlocked, with its evidence

**Cross-camera correlation is now live and evidence-based.** The grid is a set of
replayed windows, not a synchronised estate, and the system refused every pair by
default because nothing had established otherwise. Burned-in clocks were read
from all thirty cameras by the **local** vision-language model — three frames
each, two required to agree — and the result is decisive:

- **13 cameras share a timebase**: cam01–05, cam07–14, all inside six minutes
  (21:37:55 to 21:43:44 on 13-06-2026). Declared as `GRID-13JUN-2137`, basis
  **MEASURED_OVERLAY**.
- The rest are hours or weeks apart — cam21 at 15:03, cam24 on 08-08, cam26 on
  09-08 — and remain refused. Joining them would draw a journey that never
  happened.
- 26 of 30 clocks read; the four with no clock stay RESTRICTED.

`cam01 + cam04` now correlates; `cam01 + cam21` is refused, with cam21 named
UNRELIABLE from its own 36 PTS regressions. Evidence: `var/reports/overlays.json`.

### A prior decision re-measured

The pipeline dropped appearance embeddings on a measurement against the
**synthetic** corpus. Re-measured on the live feed (cam01, 60 frames, 17 tracks,
IoU association deliberately outside our own tracker):

| | pairs | mean | tail |
|---|---|---|---|
| Same vehicle | 194 | 0.830 | p05 **0.640** |
| Different vehicles | 3,634 | 0.576 | p95 **0.791** |

Best balanced accuracy **0.831 at threshold 0.74**, but the distributions
overlap. The earlier claim — "did not separate vehicles" — is too strong for
real footage; the accurate statement is that an embedding can **rank**
cross-camera candidates and cannot **confirm** identity. About one pair in six is
misclassified at the best threshold, which on a busy corridor is a route built
from confident mistakes. It is therefore still not stored as an identity signal,
and the code comment now carries the real-data numbers instead of the synthetic
conclusion. Reproduce with `tools/benchmark_models/reid_separation.py`.

---

## CR-009 — Evidence layer and the API/UI contract
**Date:** 2026-09-02

Found by exercising the live investigation path end to end in the browser
rather than through the API alone. Every one of these is a case of the system
**claiming more than it held**, and three of the four failed on the success
path, which is why no test caught them.

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | Both evidence verification screens reported failure on success. The endpoints answer `{verified, checks:[{check, passed, detail}]}`; both readers were written against `{ok, checks:[{ok, name}]}`. Every field resolved to `undefined`, so the assurance screen displayed **"EVIDENCE CHAIN BROKEN"** over a chain that verified, with a ✗ against each intact record. | One `normaliseVerification()` adapter, tolerant of both spellings, used by both readers so a third cannot drift the same way. Verified against the live store: the screen now reads "Evidence chain verified" with ✓ per record. |
| 2 | **P1** | `capture_method` was a constant reading *"automated capture from live RTSP; no manual editing of the retained frame"* — written into every manifest, including the ones with `frame_path=None`. On the live grid, where footage is not retained, a record asserting a frame it does not hold was the **usual** case, not the exception. | `capture_method` is now derived from what was actually stored. A record with no media says so in terms that cannot be misread: *"metadata only … It is not a sealed copy of footage and must not be offered as one."* |
| 3 | **P1** | Verification skipped the media checks when there was no media, so a metadata-only record returned the same PASS as one whose frame had been hashed and re-checked. The reader could not tell which had happened. | Absence of media is now a stated check — *"media retained: none — its integrity checks cover the manifest and the chain, and cover no image"* — so the scope of a PASS is on the face of the result. |
| 4 | **P1** | `observations.evidence_ref` was never written. Search therefore reported `evidence_available: false` for sightings that **were** sealed; an investigator told nothing was sealed seals it again. That is how one sighting acquired two competing manifests sitting at different points in the hash chain. | The back-link is written in the same transaction as the manifest insert, so the two directions cannot disagree. Sealing is idempotent per observation and returns the existing record. `tools/admin/backfill_evidence_link.py` repairs existing stores; it **reports** duplicates rather than deleting them, because a chain is append-only and removing an entry from it is not a repair. |

Six regression tests in `tests/unit/test_evidence_linkage.py` pin all four.

**On why these survived.** Each of the four is invisible to a test that asserts
the happy path succeeds: the chain really did verify, the manifest really was
written, the search really did return the sighting. What was wrong was what the
system *said about* those results. That is only catchable by reading the output
the way a user would — which is the argument for driving the real UI against the
real store, not only the API.

---

## CR-008 — Live integration: curated data, model provenance, API surface
**Date:** 2026-09-02

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | A live ingest run **erased every curated camera fact**. `upsert_camera` overwrote all supplied columns, and the probe's `to_registry_row()` sent `name=camera_id`, `lat=None`, `lon=None` for cameras it knew nothing about. Nineteen surveyed positions, all names and all districts were replaced with nulls. The map emptied with no error, and the UI truthfully reported that no camera had a position. | Two layers. The store now treats `None` as "unknown" for curated columns and refuses to let it overwrite a stored value; deliberate clearing requires naming the field in `clear=`. Discovery now **omits** what it does not know instead of sending a fabricated value — `name=camera_id` is a real string that no null-guard can catch. Six regression tests in `tests/unit/test_camera_curation.py`. |
| 2 | **P1** | Loading RT-DETRv2 printed a LOAD REPORT marking `class_embed.*` / `bbox_embed.*` as MISSING — "newly initialized". Read plainly this says the detection head is random and every detection is noise. Nothing in the six-check activation gate could distinguish that from the benign case, because a random head loads, infers, and returns well-formed boxes. | Added a seventh check, **WEIGHTS**, which compares the live head tensors against the checkpoint file at the revision the registry pins. It does not reason about the warning; it establishes the fact. Measured: `51/51` bit-identical for the vehicle detector, `99/99` for the plate detector. Where the comparison cannot be made it reports so rather than passing silently. The banner is now suppressed at every entrypoint, since the claim it appears to make is tested instead of explained away. |
| 3 | **P2** | `uvicorn saakshya.api.app:app` — the first command anyone would try — failed with `TypeError: 'NoneType' object is not callable`, because a module-level `app = None` placeholder is read by uvicorn as an ASGI2 callable. | Removed the placeholder. The conventional invocation now fails with "Attribute 'app' not found", which names the fix; the correct `:build --factory` form is documented at the definition site. |
| 4 | **P2** | The `Role.AUDITOR` comment read "reads the audit log; reads nothing else", but the grant includes `CAMERA_READ`. In a security table, a comment that **overstates** a restriction is the dangerous direction to be wrong in — a reviewer trusts it and stops checking. | Comment corrected to state the actual grant and the reason for it: an audit entry naming cam21 cannot be reviewed without resolving what cam21 is. The line is drawn at observations, evidence and search, now pinned by four assertions and three negative API tests. |

**Verification added.** `tools/verify/api_surface.py` exercises the whole HTTP
surface as five roles and asserts both directions: 43 routes return their
documented shape, and **10 authorisation refusals fire as specified** —
authentication, role permission, jurisdiction scope, purpose binding. A suite
that only tests the happy path cannot tell a working access-control system from
one that has been switched off.

**A correction to my own record.** I first reported finding 2 as a confirmed P0
— "the detector emits noise" — on the strength of a synthetic test in which the
model scored random pixels above a clean image containing two solid rectangles.
That test could not distinguish a trained head from an untrained one, because
solid rectangles are not COCO objects and low scores on them are the correct
answer. On real frames from cam21 the detector returns `motorbike 0.77`, stably,
across frames. The claim was withdrawn within the same session and the WEIGHTS
check exists so that neither the alarming reading nor my reassuring one has to
be taken on trust again.

---

## CR-007 — Model activation, and camera time clusters
**Date:** 2 September 2026 · **Reviewer:** second-pass, independent-eyes mode

### Change
`models/validation.py`, `live/timebase.py`, `tools/verify/validate_models.py`,
`tools/live/clusters.py`, plus the trajectory timebase verdict.

### Findings

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | **Two more registry models cannot load at all.** `ocr-awiros-india` and `embed-vehicle-siglip2` both fail with "can't load image processor" — the first ships PaddleOCR artefacts, the second bare ONNX, and neither has a transformers-compatible processor. Both were sitting as CANDIDATE, available to be selected, and would have failed the moment anyone did. Same class as the CR-006 P0, found on the activation gate's **first run**. | Each blocker recorded in the registry entry's own notes, naming what adopting it would actually require — a PaddleOCR adapter, an ONNX adapter with hand-written preprocessing. Kept as candidates rather than quietly removed: the DINOv2 rejection means a working vehicle embedding is still an open question, and these are among the few permissively licensed answers. |
| 2 | **P2** | **The activation gate crashed on the simplest failure it exists to catch.** `registry.get` raises `KeyError` on an unknown key; the validator assumed it returned `None`, so validating a mistyped key raised instead of reporting FAILED. | Caught and reported. A gate whose purpose is to surface failures must not itself be one. |
| 3 | **P2** | A model recorded as **REJECTED** would have reported ACTIVE if it happened to load. The DINOv2 rejection came from a measurement — a −0.541 margin against a decoy — and a smoke test saying "it loaded fine" would have quietly undone it. | `STATUS` is now the second check and short-circuits before any inference runs. |

### Design assessment

**Activation is a gate, not a lookup.** The premise this module corrects is that
a registry entry was being treated as evidence a model works. Six checks —
RESOLVED, STATUS, LICENCE, LOADED, TASK, INFERENCE, OUTPUT — and the one that
would have caught the CR-006 P0 is `TASK`: a detection checkpoint loaded through
a bare backbone has no detection head, and the class it loaded through is itself
worth asserting.

The smoke frame is structured rather than noise on purpose. Pure noise gives a
detector nothing to latch onto, so zero detections would be ambiguous — broken
model, or genuinely nothing there? Shapes on a background make "returned a
well-formed output" checkable without asserting what the output should *contain*,
which would be testing the model rather than the wiring.

**Time clustering makes correlation a property of a pair.** The live grid has
twelve cameras on a common window and others weeks apart. Rather than a global
assumption in either direction, `may_correlate(a, b)` returns ALLOWED,
RESTRICTED or REFUSED with a reason, and the default absent evidence is
RESTRICTED. Cluster membership carries its basis, so an investigator relying on
a route can see whether the timing rests on a measurement or an assertion.

### Carried forward
Unchanged from CR-006, plus: the VLM has no smoke path and reports SKIPPED
rather than ACTIVE — correct, and it means the copilot's vision path is
unvalidated until one is written.

---

## CR-006 — Live Gujarat feed integration
**Date:** 2 September 2026 · **Reviewer:** second-pass, independent-eyes mode
**Provenance:** `GOVERNMENT_LIVE` — the organiser's Sentinel Camera Grid

### Change
`live/` (catalogue, discovery, endpoints), `tools/live/` (profiler, staged
ingest), chroma measurement through `analytics/quality`, and the fixes below.

### Findings

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | **Every detector in the registry was loaded as a bare backbone.** `TransformersBackend.load` chose its class with `record.task == "detect"` — a string that matches no task in the registry, where the tasks are spelled `vehicle_detect` and `plate_detect`. So `AutoModel` was used instead of `AutoModelForObjectDetection`: most weights initialised at random, the output object had no `logits`, and `detect()` raised on **every single frame**. | The set of detection tasks is now declared once in `models/registry.py` beside the enumeration, and the backend uses it. Three regression tests, including one asserting that no registered detector falls outside the set and one pinning the literal out of the loader. |
| 2 | **P0** | **`enable_vehicle_detector` defaulted to `False`.** The entire T1 tier was dead code. On the synthetic corpus, motion and plate detection covered for it and every test passed. On real night footage — where plates are unreadable and the vehicle detector *is* the tier — the system reported an empty road. | Enabled by default. Measured after the fix on live cam01: 794 vehicle detections, 64 tracks, **48 observations** in 40 s, where it had produced zero. |
| 3 | **P1** | **A broad `except Exception` reported the broken detector as "no vehicles".** Finding 1 raised on every frame and the caller logged a warning and returned an empty list, so a fault was indistinguishable from a quiet junction. This is CR-001 finding 2 reappearing in a different module — the lesson had been learned in `anpr.py` and not applied here. | Narrowed: `(ValueError, RuntimeError, IndexError)` counts a rejected frame; anything else is logged as a fault and re-raised. A test asserts both halves. |
| 4 | **P1** | **16 of 30 live cameras are in monochrome/infrared night mode**, and nothing in the system could tell. They deliver three-channel frames whose channels carry identical values; a colour estimator asked to read a vehicle from one returns a confident answer that is pure fabrication. | `mean_chroma` measured through `quality → observation`, `MONOCHROME_CHROMA` threshold set from the live distribution, appearance graded UNSUITABLE on those cameras. Detection and presence unaffected. Two regression tests, including one that a *dim but coloured* frame is not misread as monochrome. |
| 5 | **P2** | **A capability threshold was inert.** Appearance was gated on sharpness ≥ 100 while the live range is 221–9261 — below the observed minimum, so every camera passed and the test contributed nothing. Worse, raw Laplacian variance is scene-dependent: foliage scores high and clean tarmac low at identical focus, so an absolute threshold across cameras compares scenes, not optics. | Sharpness is recorded and no longer gated on. Appearance is graded on resolution, illumination and chroma — properties that are comparable between cameras. |
| 6 | **P2** | **The profiler crashed on its last line** when given a relative output path (`Path.relative_to` raises), turning a successful 105-second profiling run into a traceback. | Guarded. |
| 7 | **P3** | Declared frame rate is wrong on 4 of 30 cameras — cam01 declares 30 and delivers 15.04, cam15 declares 10 and delivers 4.01. Not a defect in our code; the guide warns about it and the system already uses PTS throughout. | Recorded as a measurement, with `realtime_ratio` added: cam15's PTS advances at 0.396× wall time, which now grades presence DEGRADED on the ratio rather than the rate. |

### What the live feed taught that the corpus could not

Findings 1, 2 and 3 form one story worth stating plainly. A detector that had
never once produced a detection sat in the codebase behind a disabled flag, a
mistyped task string and a broad exception handler — three independent faults,
each of which alone would have been caught, and which together produced a system
that passed every test while being incapable of detecting a vehicle.

The synthetic corpus could not have found it. Its plates were legible, so plate
detection carried the pipeline and the vehicle detector was never needed. It
took footage where plates are *unreadable* — a Gujarat junction at 2 a.m. in
infrared — for the absence to become visible.

### Design assessment
Capability-aware scheduling earned its place immediately: 16 cameras dropped to
T0 on measurement, halving analytics cost before a single expensive inference
ran. The abstention discipline held under real conditions — cam22 delivered one
frame in 25 seconds and was graded UNKNOWN with `evidence_confidence: NONE`
rather than being called broken.

### Second pass — after the staged live runs

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 8 | **P1** | **The ingest worker's queue put had no timeout.** A bounded queue and an unbounded wait is a decoder thread held hostage by a slow consumer — and that decoder is holding an RTSP session on the organiser's grid. Not theoretical: consumer saturation was *measured* at 30 cameras. | Bounded wait with a per-camera drop counter, reported in the stage summary. An observation lost silently is worse than a run that says it dropped some. |
| 9 | **P1** | **Capability was invisible in its own inventory.** `/gis/capability` filtered through a bounding box, so every camera without coordinates was excluded — on the live grid, all thirty. A working, fully graded estate rendered as an empty table. | Capability is a property of the camera, not of its position. The inventory now includes unlocated cameras and reports how many cannot be mapped. |
| 10 | **P1** | **Live stream health was never persisted.** The workers tracked state, reconnects, PTS regressions and measured fps, and wrote none of it down — so every camera graded UNKNOWN for presence. Health that only lives in a worker's memory cannot be the primary source for ACTIVE / DEGRADED / OFFLINE. | Written on stage completion, and grading now runs per illumination band so a night grade does not close the question for daylight. |
| 11 | **P2** | **A bare `catch {}` in the UI swallowed a `ReferenceError`.** The symptom was that a panel silently never appeared — twenty minutes of looking at the wrong thing. Same class as finding 3, in a different language. | Narrowed: an expected 401 before sign-in stays quiet, anything else surfaces to the console and a toast. |
| 12 | **P1** | **There was no schema migration at all.** `metadata.create_all` creates missing tables and never alters an existing one, so every column added to the schema silently broke every query against a database created before it. Found by the release gate, not by a test: two advisory checks failed with `no such column: observations.mean_chroma` against a store built the previous day. In development the answer had always been to delete the database. In a deployment that answer does not exist — an upgraded node would fail on its first observation query. | Nullable columns are now added in place at `create_all`, which is the only kind of change this schema makes and the only kind SQLite can apply without rewriting a table. Anything else — a rename, a type change, a new constraint — is **reported** by `pending_migrations()` rather than skipped, because those need a real tool with a downgrade path and pretending otherwise would be worse than the gap. Two regression tests. |
| 13 | **P2** | **The suites became too slow to run.** Enabling the detector tripled per-frame cost; end-to-end went from 350 s to over 1,500 s. | The end-to-end window is bounded to the 120 s containing the scripted scenario and enough transitions for the graph. 31/31 in 5 m 49 s. A gate that takes half an hour is a gate people stop running. |

Reviewed against the risks §52 names. No credential reaches a log or an
exception — only a boolean "present" flag leaves the module. The queue is
bounded, threads are daemon and joined with a timeout, and **the live path
writes no video frames to disk**.

### A conclusion I got wrong, and how

I sampled twelve cameras' burned-in clocks, found `02:55`, `04:43` and a
different date among them, and concluded the grid was unsynchronised — writing
that cross-camera tracking on it "is not physically meaningful". That went into
three documents and a commit message before it was checked.

Reading all thirty showed the opposite for the majority: **twelve cameras sit
within three minutes of each other**, and the outliers had simply been
over-represented in the sample. The corridor is real; what blocks the chain is
the absence of plate reads at 04:00 in infrared, not the clocks.

The failure was sampling, and it is the same failure this project criticises
elsewhere: a conclusion drawn from too little evidence, stated with more
confidence than the evidence carried. The capability grader refuses to grade a
camera on fewer than twenty observations for exactly this reason. I did not
apply the rule to myself.

Corrected in `docs/LIVE_FEED_FINDINGS.md`, `JUDGE_QA.md`, `DEMO_SCRIPT.md` and
the product's own timing caveat.

### Carried forward
- ANPR yield on the live grid is **zero** at 02:00 IST. Diagnosed as conditions,
  not model: near-empty junctions, infrared, wide views. Must be re-measured in
  daylight before any conclusion about the plate model is drawn.
- The grid loops a recorded window; the overlay clock reads ~02:00 regardless of
  wall time. Normalised time is therefore *when we observed it*, not when the
  scene occurred, and evidence must say so.
- The catalogue requires a signed-in session we do not hold; the camera set is
  discovered by probe and labelled as such.

---

## CR-005 — Grounding, administration, and a flake worth chasing
**Date:** 1 September 2026 · **Reviewer:** second-pass, independent-eyes mode

### Change
Numeric grounding in `copilot/grounding.py`, the read-only admin router, the
host-side user CLI, and integration-suite runtime.

### Findings

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | **Numeric grounding was substring matching, and therefore unsound.** A claimed "87% probability" was accepted as grounded if the digits `87` appeared *anywhere* in the serialised tool output — inside a generated identifier, inside an epoch microsecond, inside `0.874`. The grounding check is one of three defences against a model inventing a statistic, and this one was close to decorative. | Numbers are now collected by walking the result structure and compared as values, with a rounding tolerance so a displayed 79% still matches a 0.7863 score. Two regression tests, one of which is the exact payload that used to slip through. |
| 2 | **P1** | **The first fix reintroduced the same unsoundness one level down.** Extracting numbers from strings with `\b\d+\b` pulled `87` back out of `OB01M1EX87ZQ`, because `\b` treats a letter–digit boundary as a word boundary. Caught only because the regression test still failed. | Standalone numbers only: `(?<![A-Za-z0-9])…(?![A-Za-z0-9])`. Prose like "plausibility 0.62 over 4 samples" still counts; digits inside identifiers do not. |
| 3 | **P2** | **The suite was intermittently red — roughly one run in eight.** Easy to dismiss as environmental. It was the symptom of finding 1: whether `87` appeared in the payload depended on a generated observation id, so the unsound check passed or failed at random. | Fixed by 1 and 2. Ten consecutive clean runs of the 258-test suite. **The flake was the only visible evidence of a real security defect**, which is the argument against ever retrying a red suite and moving on. |
| 4 | **P2** | An admin test asserted the string `"token"` was absent from the whole `/admin/users` response, and failed on the explanatory note that legitimately says tokens are minted by CLI. A test that fails on correct behaviour trains people to weaken tests. | Rewritten to inspect the user *records* for credential-shaped fields, plus a check that nothing hash-shaped or `skv_`-prefixed appears anywhere. |
| 5 | **P0** | **The decoder-error handler named an exception that does not exist.** `except (av.error.InvalidDataError, av.error.ValueError, av.FFmpegError)` — there is no `av.error.ValueError`. Python evaluates an except tuple only when something is raised inside the `try`, so the mistake was invisible until a packet actually failed to decode, at which point the handler written to survive a bad packet would itself raise `AttributeError` and take the stream worker down. Every run to date recorded **zero** decoder errors, so no test ever reached it. On a real government feed the first malformed packet would kill the camera. | `except (av.FFmpegError, ValueError)` — `FFmpegError` is the base of every PyAV decode error and derives from the builtin. Found by mypy, not by testing. New `tests/unit/test_ingest_errors.py` raises through the tuple and an AST guard asserts every `av.error.X` this codebase names actually exists. |
| 6 | **P1** | **A yellow car was published as WHITE at 0.73 confidence.** Motion segmentation merged several vehicles and the road into one blob spanning the full 1280 px frame width, and colour was sampled from it. The lit-fraction and colour-confidence gates from CR-003 passed it happily — they ask "is this crop readable", and nothing was asking "is this crop a car". | A geometric plausibility gate on the body box (frame-width, frame-area and aspect bounds, deliberately generous). When nothing on a track is vehicle-shaped, attributes are **abstained** rather than guessed, and the abstention is counted per camera so a camera where it climbs is visible. The plate read still stands — it came from one plate on one vehicle, voted across frames. |
| 7 | **P2** | Six further latent `None` crashes found by mypy: `datetime | None` where `.isoformat()` was called (audit read, edge node list, case export, case notes), an unary minus on a possibly-None confidence, and an alert keyed on a possibly-None plate. Each would surface as a 500 at exactly the wrong moment — three of them while reading the audit log or exporting a case file. | Fixed individually; `from_us_required` added for NOT NULL timestamp columns so a corrupt row fails with the field name rather than propagating a None. |
| 8 | **P2** | **`make typecheck` was advisory and produced 47 errors**, of which 12 were pydantic false positives from a plugin that was never enabled. A gate that is mostly noise is a gate nobody reads — which is why findings 5, 6 and 7 sat there unnoticed. | Pydantic plugin enabled, numpy stub artefacts scoped to two modules with a stated reason, every genuine error fixed. **`src/` is now clean across 68 files and typecheck is a blocking gate.** |
| 9 | **P1** | **A case could be created and listed but never opened.** Every case route took `{case_id}`, which stops at a slash — and an Indian FIR number is `NNN/YYYY`, so a slash-bearing identifier is the *normal* case. Opening, attaching to, annotating or exporting a case returned 404 on an identifier the system had just issued. | Path converters on every case route, ordered so the suffixed routes are declared before the bare one. Two regression tests, including one that would catch a future reordering. **Found by clicking a case in the interface** — no test covered it, because every test used an identifier without a slash. |
| 10 | **P2** | **The estate map rendered nothing while reporting "6 in view".** The canvas rules were written as `#map { … }`, so they applied to the investigation map and not to `#map2`. An unstyled canvas takes its size from its width/height attributes — which the renderer sets from the measured box — so measuring and sizing fed each other and the canvas collapsed to 64×64 over a few ResizeObserver ticks. The header still said six cameras were in view, because the fetch had succeeded. | Canvas styled by class, `min-height: 0` on the flex container, and a guard in the renderer that refuses an implausibly small measurement and logs why. A fit computed while a view was hidden is now replayed when the canvas grows. |
| 11 | **P3** | A regression test's own payload was wrong: `0.874` was chosen as innocent noise, but it genuinely rounds to 87%, so accepting it was correct behaviour. | Payload corrected to `0.4187`. Worth recording — the test was asserting a falsehood about the code. |

### Design assessment
The admin surface is deliberately read-only, and the reason is worth stating:
minting a token is minting a credential, and requiring shell access on the host
is a materially higher bar than requiring an ADMIN session on the network. The
role table is *served* at `/admin/roles` with the separation-of-duty flags
computed live, so "ADMIN cannot search" is checkable rather than asserted.

Integration runtime went from ~50 minutes to ~95 seconds. The suite had a
function-scoped fixture re-running the whole pipeline once per test, so C-014
was decoded three times. Now ingested once, bounded to 90 s of the 240 s corpus;
`tests/e2e` still covers the whole thing. A suite nobody runs protects nothing.

The slash bug is worth a separate note. Every test in the suite used a case
identifier without a slash, so the suite was green while the feature was
unusable with real Indian identifiers. Fixtures that avoid the awkward shape of
real data test a system nobody has.

### Carried forward
Unchanged from CR-004, plus: **grounding verifies tokens, not claims** — a model
could assemble true tokens into a false sentence. Mitigated by routing route
questions through `build_trajectory` rather than free-form reasoning; not
eliminated, and named as the weakest guarantee in `docs/FINAL_RED_TEAM.md`.

---

## CR-004 — Phase 3/4: security, API, GIS, capability, offline, copilot, UI
**Date:** 2026-09-01 · **Reviewer:** second-pass, independent-eyes mode

### Change
`security/`, `api/` (37 endpoints), `gis/`, `capability/`, `investigation/`,
`edge/`, `obs/`, `copilot/`, the `ui/` workspace, and the perf/release tooling.
Roughly 6,000 lines. 246 unit + security tests, 18 offline E2E, 13 chain E2E.

### Findings

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | **Capability grading used an exposure-quality score as a brightness measurement.** `analytics.quality.luminance` peaks at mid-grey and falls off towards *both* crushed blacks and blown highlights — it answers "is this well exposed", not "is this dark". The band classifier read it as brightness, so a correctly exposed night scene and a correctly exposed day scene both scored ≈1.0 and were indistinguishable. | Added `mean_luma` (actual brightness, 0..1) through `quality → pipeline → observation`, and the band classifier now takes it. The parameter is named `mean_luma`, so passing the wrong field no longer type-checks by coincidence. |
| 2 | **P1** | **Unit mismatch made two thresholds unreachable.** `low_light_luminance = 45.0` and `vehicle_good_sharpness = 45.0` were raw-units values compared against measurements normalised to 0..1. Consequences were silent and opposite: *every* observation fell into the LOW_LIGHT band (45.0 > any 0..1 value), and *no* camera could ever be graded GOOD for appearance. Both looked like plausible output. | Thresholds renamed with explicit units (`low_light_mean_luma = 0.22`, `vehicle_good_sharpness_norm = 0.35`) and re-expressed in the measurement's own space. Two regression tests pin the units, including one asserting that no single brightness value collapses every sample into one band. |
| 3 | **P1** | **Map layers never loaded.** Two independent causes, both invisible: the canvas measured itself at 1×1 during layout and only re-measured on a *window* resize, which never came; and both maps shared one debounce timer, so the second map's fit cancelled the first map's pending fetch. | `ResizeObserver` on the canvas — the box changes for reasons the window never hears about. A pending fit is remembered and replayed once a real size arrives. Debounce timers are now per-map (`WeakMap`). |
| 4 | **P2** | **A `+` in a query string arrives as a space**, so `?seen_at=2026-09-01T08:00:00+00:00` failed to parse and `/cameras/{id}/next` returned 400 for a correct client. Found by the latency harness, which saw a 400 where it expected a 200. | The unambiguous transport artefact is repaired in `parse_time`; everything else stays strict. The harness now encodes its own parameters, which is the real fix on that side. |
| 5 | **P2** | **The audit trail for one case was a full table scan** — the one hot query with no index behind it, found by `make queryplan` rather than by guesswork. | `ix_audit_case (case_id, id)` added. All 10 hot queries now use an index, and the before/after is in `var/reports/query_plans.json`. |
| 6 | **P2** | **The corpus could not exercise the thresholds it was meant to validate.** Two to three vehicles per camera over 60 s: capability grading refuses below 20 observations, and the graph refuses to trust an edge below 3 transitions, so both correctly refused and neither was ever tested with data. | The corpus grew rather than the thresholds shrinking — 240 s with deterministic generated traffic: corridor commuters that give the graph repeated transitions, plus local traffic as the noise a search must work through. |
| 7 | **P2** | `SearchService.evidence_panel` executed a throwaway query before the one it needed. Harmless but real work on a hot path. | Removed. |
| 8 | **P3** | `CaseService.get` used a conditional expression purely for its side effect (`require_scope(...) if district else None`). | Rewritten as an `if`. |

### What the negative tests are worth
A suite of security tests that all pass proves nothing until you know it can
fail. Two controls were run:

* A **positive control** asserts the same request *succeeds* with the right
  role and scope, so a negative result cannot come from a broken fixture.
* A **deliberate mutation** — removing the district check from
  `Principal.in_scope` — was confirmed to fail
  `test_out_of_scope_results_are_filtered_not_leaked` and
  `test_camera_context_is_scope_checked`, then reverted.

### Design assessment
The single most consequential decision is that the copilot and the UI call the
same `InvestigationService`. It is what makes "the assistant cannot do anything
you cannot, and cannot skip an authorisation check" true by construction rather
than by discipline. The tool registry asserting that no tool mutates is a
second, independent guarantee that survives a fully compromised model.

Second: **purpose binding at the authorisation gate**, not at the UI. A search
without a case and a stated reason is refused before any data is read, so the
reason for every intrusive query survives the officer who ran it.

### Complexity
`InvestigationService.search_target` carries four responsibilities (permission,
scope resolution, dispatch, presentation) and is the next extraction candidate.
`CameraPipeline.process` remains flagged from CR-003. Neither is a defect
today; both are where the next one will hide.

### Carried forward
- **P2** opencv/PyAV native `recursive_mutex` abort at interpreter shutdown;
  fix is separate processes for ingest and analytics.
- **P3** C-014 lost one of three plate reads after the merge tightening in
  CR-003.
- **Outstanding, not defects:** 2-hour chaos soak, 50-camera measured run,
  retention-enforcement job.

---

## CR-003 — Day 2: attributes, camera graph, graph-first search
**Date:** 2026-09-01 · **Reviewer:** second-pass, independent-eyes mode

### Change
`analytics/attributes.py`, `analytics/motion.py` (colour differencing, blob
merge), `analytics/pipeline.py` (plate/body fusion, view scoring),
`intelligence/graph.py` (Camera Link Model), `intelligence/search.py`
(graph-first hybrid retrieval), plus 34 new tests.

### Findings

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P1** | **Colour reported `black` on every observation.** Attributes were sampled from plate boxes and motion fragments, not vehicle bodies. Unit tests all passed — each component was correct in isolation; the fault was *which region* the correct component received. | Fixed in four stages, each measured: (a) plate/body **fusion** so the tracker sees one detection per vehicle; (b) `_body_box` prefers the current fused box over "largest box ever seen" (an early oversized motion blob was winning); (c) **view scoring** — attributes read from the frame where the vehicle is largest and unclipped, because quality barely varies and `>=` gave ties to the last frame, systematically the worst view; (d) abstention. |
| 2 | **P1** | **Luma-only motion detection is blind to luma-matched vehicles.** Measured: red car luma 58.8 vs road 65.3 — only the bottom sliver triggered, producing a 72px-tall box. A red car on grey tarmac is an ordinary sight. | Motion now differences **per colour channel**, reduced by max. Verified on a synthetic case: box recovered exactly (120×60 vs truth 120×60). |
| 3 | **P1** | **Confident wrong colour.** An over-merged motion box covering a bus *and* surrounding road sampled 85% lit pixels with a road-grey median → `black` for an orange vehicle, at confidence **0.18**. The estimator knew it did not know; it was never asked. | Two gates: abstain when lit fraction < 0.25, and abstain when colour confidence < 0.30. Merge gap tightened 3→1 cells. **Result: 9 correct, 1 abstained, 0 wrong** (was 0 correct, 11 wrong). |
| 4 | **P1** | **Private key tracked in git.** `auto.key`, generated by MediaMTX for its TLS listener, was swept in by `git add -A`. | Untracked, gitignored, and purged from history. Disposable self-signed cert, so P2 by impact — but a tracked private key fails a security review regardless of value. |
| 5 | **P2** | **Licence scanners cannot see non-PyPI artefacts.** `imageio-ffmpeg` declares BSD-2-Clause for its wrapper while shipping a **GPL** FFmpeg binary. | `NON_PYPI_ARTEFACTS` enumerates binaries and model weights by hand with real licences and whether they ship. Gate verified to fail on an injected AGPL package (§AR). |
| 6 | **P2** | **Audit chain failed on its first entry.** `now_us()` was called twice, so the hashed timestamp differed from the stored one. | Single timestamp for both. Tamper-detection test added. |
| 7 | **P2** | Negative-stride arrays from `image[:, :, ::-1]` crash `torch.from_numpy`. Latent in shipped `TransformersBackend`, not only in the benchmark. | `np.ascontiguousarray` at both sites. |
| 8 | **P3** | Test keys collided with fixture keys, so idempotent ingest silently dropped scenario rows and a test failed confusingly. | Namespaced test keys. Idempotency was working correctly — the test was wrong. |

### Design assessment
Stage ordering (structure → graph → attributes → rerank) is the load-bearing
decision and is justified by measurement, not preference: DINOv2 scored the
decoy at 0.941 against the target while scoring the target against itself at
0.412 (margin **−0.541**), and illumination normalisation made it worse
(−0.581). Leading with ANN would rank by that signal. Recorded as `REJECTED` in
the model registry with the evidence.

### Complexity
`CameraPipeline.process` is now the longest method in the codebase and carries
four responsibilities (detect, fuse, track, attribute). **Flagged for extraction
before it grows further** — not done now because splitting it mid-Day-2 risks the
working chain for no functional gain.

### Testing
84 unit + 5 integration + 5 ML-regression. The regression suite exists precisely
because finding 1 was invisible to unit tests for three iterations; its
thresholds sit just below measured performance.

### Not addressed
- `opencv`/PyAV native conflict still produces a `recursive_mutex` abort at
  interpreter shutdown (observed again this session). **P2, carried forward** —
  fix is to split decode and inference into separate processes.
- C-014 lost one of three plate reads after the merge tightening. Target remains
  findable on two cameras and integration tests pass; **P3, carried forward.**

---

## CR-002 — Quality gates
**Date:** 2026-09-01

`make precommit` / `make verify`, secret scan over tracked files *and history*,
licence policy with SBOM. A gate that cannot run reports SKIPPED with a reason —
never a silent pass, because a green board that dropped three checks is worse
than a red one. Gates verified to have real detection power.

---

## CR-001 — Day 1: persistence, tracker, motion, per-track ANPR
**Date:** 2026-08-31

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | **P0** | `StreamWorker._stop` shadowed `threading.Thread._stop`; **every** `join()` raised `TypeError`, so every clean shutdown crashed. | Renamed to `_stopping`. |
| 2 | **P1** | Broad `except Exception` swallowed an `AttributeError` from a refactor as "bad crop" — zero detections across all six cameras, reported as a model problem. | Narrowed to `(ValueError, RuntimeError, IndexError)`. Programming bugs must not masquerade as bad input. |
| 3 | **P1** | Eval harness reported **PASS on that collapse**: "no wrong plates" is trivially satisfied by detecting nothing. | Three independent checks, including coverage and correct declining. |
| 4 | **P1** | Chaos harness reported PASS while injecting **nothing** (wrong path encoding, wrong verb). | Corrected API usage; pass now requires faults to have verifiably landed. |
| 5 | **P2** | `drawbox` does not evaluate per-frame expressions in this FFmpeg build — the first corpus rendered **no vehicles**, silently, exit code 0. | Replaced with Python scene synthesis; also yields bbox ground truth. |
