# Alignment with the published test scenario

Historical planning / measurement record. For the current submission use
[FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Current roles: government
`GJ11S7924` on cam06 is SINGLE-CAMERA evidence; synthetic `GJ18JX7786` on
C-014 then C-021 is a SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). Earlier rehearsal plate names,
screenshot counts, timings and dates below belong to their recorded run.
Current wall policy: CONTROL ROOM up to 30 direct WHEP sessions, 400 ms apart;
OPTIMIZED VIEW at most 12, 600 px prefetch, released after 15 s off screen
(`ui/app.js`). Old still-wall descriptions below are historical.


The organisers' Resources page states the scenario the solution is evaluated
against. This maps each stated requirement and expected output to what this
system actually does, with the evidence and its status label —
**MEASURED / MODELLED / SIMULATED / DESIGNED / UNTESTED** — as defined in
[EVALUATION_PLAN.md](EVALUATION_PLAN.md).

Nothing here is aspirational. Where a requirement is only partly met on the live
grid, that is stated with the measurement that shows it.

---

## The stated scenario

> ~50 geographically distributed cameras … across different departments … various
> technologies, formats, VMS platforms, and storage mechanisms. Teams must onboard
> the available cameras onto one integrated platform.

| What we do | Status |
|---|---|
| 30 cameras discovered on the live grid and onboarded into one registry. All 30 reachable over authenticated RTSP/TCP (`SENTINEL_GRID_EMAIL` / `PASSWORD` in the process environment, never in the repo). The documented catalogue and HLS endpoints redirect to `/auth/login`, so the camera set was found by enumerating the documented id pattern and **every record is labelled `source="probe"`** rather than presented as a catalogue import. | **MEASURED** |
| Heterogeneity is handled as data, not assumed away: mixed codecs (h264 and hevc), mixed resolutions (640×576 to 2560×1440), 16 of 30 monochrome/IR — detected by `mean_chroma`, not by configuration. | **MEASURED** |
| **Department attribution: 3 of 30.** The dataset spans five departments (Health, Police, GSRTC, Panchayat, Municipal Corporation) but the mapping is not published. Only three cameras state it themselves — cam17 "Rajkot Bus Port" (GSRTC), cam19 "Khaparia Gram Panchayat", and cam25 whose own signage reads "GRAM PANCHAYAT". A traffic junction in Gujarat could belong to either Police or Municipal Corporation, so the rest are recorded as unknown rather than guessed. The catalogue endpoint would settle every one of them and is not reachable. | **MEASURED** |
| Onboarding is metadata-first (Model 1), with Model 2 as ingest stills (not a second RTSP copy) and Model 3 as the observation bus. Selected Model 4 analytics is retained; statewide central recording is declined on MODELLED arithmetic: 160 Gbps and 52 PB. See [SCALE_MODEL.md](SCALE_MODEL.md). | **MODELLED** |
| Capacity beyond the 30 available: 50 concurrent streams exercised on one host. | **MEASURED**, `var/reports/camera_load.json` |

> The solution must enable centralised monitoring and AI-powered video analytics.

| What we do | Status |
|---|---|
| **Output report showing detected vehicles with timestamps.** Rendered from the same rows drawn on the demonstration video, so report and video cannot disagree. On the government grid: 6 of 7 cameras decoded, **363 vehicles, 8,116 timestamped rows**. | **MEASURED** |
| **Registration marks read, with cross-camera repeats.** On the local synthetic corpus, whose marks are known in advance: **14 distinct marks**, two of them (`GJ01CD5678`, `GJ35BV6925`) read on **two different cameras**. On the government grid, **0** — the geometry at those mountings, not the reader. | **MEASURED** |
| **A restriction is never reported as an absence.** A match on a camera outside the officer's jurisdiction is withheld *and said to be withheld* — count, districts and reason — because reporting it as "no observation matched" is a confident denial of evidence the system holds. | **MEASURED** |
| **A sealed record that overstates itself is flagged, not edited.** Six records sealed before a generator fix assert a retained frame that was never retained. `capture_method` is inside the hashed manifest, so correcting the wording would break the chain — the records stand and verification raises a caution naming the defect. Integrity and truthfulness are reported separately. | **MEASURED** |
| One operational picture: estate map on a real basemap, stream health, capability grading, alerts, audit. | **MEASURED** |
| **Live and recorded viewing** — the wall lists every onboarded camera (30/30), including eleven without coordinates. Stills are the JPEG ingest already decoded, badged `STILL` with age — **not a second RTSP copy**. Click-to-play WebRTC is optional. | **MEASURED**, 4 September 2026 evening |
| Analytics: vehicle detection (RT-DETRv2), tracking, per-track ANPR with voting, colour and type attributes, motion and quality scoring. Every model passes an eight-check activation gate before use, including a **WEIGHTS** check that compares the live task head against the checkpoint at the pinned commit — `51/51` and `99/99` tensors bit-identical. | **MEASURED**, `var/reports/model_activation.json` |

---

## Expected output 1 — trace the designated vehicle

> Demonstration of the solution's capability to identify and trace the designated
> vehicle across the integrated CCTV network using the vehicle registration number
> provided during the evaluation.

The flow a panel-supplied mark takes, rehearsed end to end on the live grid:

1. **Add to the watchlist.** `POST /watchlist` with plate, category, authority and
   reason. Authority and reason are mandatory — an entry with no stated authority
   cannot be created.
2. **Continuous cross-referencing.** `tools/live/ingest.py --minutes 0` runs the
   grid open-endedly, matching every plate read against the active watchlist.
3. **Alert.** A match raises an alert with a decomposed confidence.
4. **Search.** `GET /search?plate=…` returns every stored observation.
5. **Route.** `GET /trajectory/…` builds hypotheses with a timebase verdict.
6. **Evidence.** Any sighting can be sealed into a hash-chained manifest.

Rehearsed on the live API against `sqlite:///var/live.db` on 4 September 2026
evening (**MEASURED**):

| Step | What ran | Result |
|---|---|---|
| Watchlist | `POST /watchlist` `GJ1VV0119` as `investigation_target`, authority and reason mandatory | 201, version 1, ACTIVE. Provenance states entries are REPRESENTATIVE — no government watchlist is integrated. |
| Search exact | `GET /search?plate=GJ1VV0119` | 2 hits on cam07: `CONFIRMED_BY_PLATE` (votes=2) plus a one-frame lead (`REQUIRES_VERIFICATION`) |
| Search lookalike | `GET /search?plate=6J1VV0119` (G/6) | `stage_counts.ocr_repair=2`, status `REQUIRES_VERIFICATION`, warning that the stored mark was not edited. Exact search of `GJ1VV0119` is not diluted (`exact: 2`). |
| Search looping | `GJ32AG0028` | 38 exact hits, **all cam06** — `SINGLE_CAMERA`. Trajectory is one camera, **not** a cam06→cam06 coverage gap |
| New one-frame lead | `GJ31T1460` on cam21 | votes=1, `REQUIRES_VERIFICATION`; same camera as the stolen-vehicle alert, not a second camera |
| Prior designated | `GJ38BH5815` on cam21 | quality 0.962, OPEN alert confidence 0.983 from an earlier ingest match |
| Route | `GET /trajectory/GJ1VV0119` (and the looping / prior marks) | Single-camera **RESTRICTED**. `GJ32AG0028` is cam06 only — **not** a cam06→cam06 coverage gap (CR-051) |
| Timebase pairs | `GET /gis/timebase/check` | `cam01+cam04` **ALLOWED** (`GRID-13JUN-2137`); `cam01+cam21` **REFUSED** (cam21 UNRELIABLE, 140 PTS regressions) |
| Purpose binding | `GET /search` without `X-Case-Id` | 400 `PURPOSE_REQUIRED` before any data is read |
| Evidence | `POST /evidence/from-observation/…` then verify | Chain **VERIFIED**. Media retained: none — this path attests metadata, not a copy of government video |
| GIS / stills | `/gis/cameras?zoom=16`, `/cameras/cam07/snapshot` | 19 located + 11 unlocated listed, `registry_total` 30. Snapshot from ingest preview, age ~5 s, not a second RTSP copy |

A new watchlist entry raises an alert on the **next** matching ingest observation.
`GJ38BH5815` already has that alert. `GJ1VV0119` is on the live watchlist awaiting
a further cam07 read (last plated sighting this ingest: 14:18 UTC).

Cross-camera identity on **LOCAL_SYNTHETIC** (`var/demo.db`): `GJ05AB1234` and
`GJ35BV6925` each on C-014 and C-021. The government grid still has **0**
cross-camera plate repeats (69 marks, 1 OCR-lookalike pair
`GJ32K5587`/`GJ3ZK5587` as of 21:02 UTC
6 Sep 2026), so a panel mark seen on one camera will not invent
a multi-camera journey.

### A camera can be broken while every counter says it is healthy

cam21 delivered 1,628 frames, 777 of them analysed, and produced **zero
observations** — with **zero decoder errors** reported. The frames were decoder
concealment: when reference frames go missing on a lossy link, H.264 builds a
plausible-shaped picture from stale data rather than failing. Frames arrived,
decode succeeded, no warnings.

An investigator told "cam21 saw no vehicles" would conclude the road was clear.
The camera could not be seen through at all. **Those are opposite findings**, and
the system now separates them: decode quality is sampled on the live path and
reported per camera, as a rate over frames rather than a judgement on one.

Measured on the live grid, same run:

| camera | analysed | observations | decode |
|---|---|---|---|
| cam01 | 599 | 640 | **OK** |
| cam16 | 427 | 444 | **DEGRADED** — 38% of 53 sampled frames carry artefacts; usable, with losses |
| cam21 | 281 | **1** | **CORRUPT** — 94% of 35 sampled frames are concealment |

The middle band matters as much as the extremes. Occasional macroblock loss is
ordinary on a live RTSP link; an early version of this check declared cam16
corrupt while it was producing 444 usable observations, and that false alarm is
recorded in [CODE_REVIEW_LOG.md](CODE_REVIEW_LOG.md) CR-015. **MEASURED**.

### What the panel should know about yield

Plate capability on this grid is **geometry and lighting, not traffic volume**,
and the system measures it per camera rather than claiming it uniformly:

| Camera | Vehicles seen | Plate reads | Why |
|---|---|---|---|
| cam04 Paldi Junction | 3,249 in 167 frames | 0 | median plate width 46 px |
| cam21 Dethali Char Rasta | 459 | 33 detections, 1 read | median plate width 75 px |

At the time of writing the replay window places most cluster cameras at
**00:57–21:43 — night**, with predominantly two-wheelers and auto-rickshaws.
cam04's own frame is timestamped `14-06-2026 00:57:57`. Under those conditions
ANPR is graded **UNSUITABLE** for those cameras, and the system says so on the
capability screen rather than failing quietly. Presence and appearance remain
**GOOD** on the same cameras, which is the capability a real mixed estate
actually has.

This is the honest position: **ANPR yield on this grid is low and measured, not
assumed.** The system is built so that a camera which cannot read plates still
contributes presence and appearance evidence to a route.

---

## Expected output 2 — complete route, timestamped and location-wise

> Complete route traversed by the designated vehicle, including timestamped and
> location-wise movement history.

Two things are required for this to be *true* rather than merely rendered, and
both are handled explicitly.

**Timestamps must be comparable.** The grid is a set of replayed windows, not a
synchronised estate. Measured from the cameras' own burned-in clocks, read by
the local vision-language model over three frames each with two frames required
to agree:

- **13 cameras share a timebase** — cam01–05, cam07–14 — all within six minutes
  (21:37:55 to 21:43:44 on 13-06-2026). Declared as cluster `GRID-13JUN-2137`,
  basis **MEASURED_OVERLAY**.
- The remaining cameras sit hours or weeks apart — cam21 at 15:03, cam24 at
  08-08, cam26 at 09-08. Correlating across them would produce a journey that
  never happened, and the system **refuses** rather than drawing it.
- 26 of 30 clocks were read. Four cameras show no clock and are `RESTRICTED`.

Evidence: `var/reports/overlays.json`. **MEASURED**.

A route carries its verdict — ALLOWED, RESTRICTED or REFUSED — with the reason.
A single-camera route reports that there is no interval to reason about, rather
than claiming a shared timebase vacuously.

**Locations must be real.** 19 of 30 cameras are placed, each carrying its
precision (`LANDMARK` ~150 m, `LOCALITY` ~1.5 km, `CITY` ~6 km) and its basis
(`DERIVED_FROM_NAME`). The map draws the uncertainty to scale, so a position
derived from a name never renders identically to a surveyed one. The remaining
11 are recorded as `NAME_INSUFFICIENT` — listed on the capability screen with
the reason, never silently dropped.

Positions are corroborated against the cameras' **own imagery**. The local VLM
reads street and shop signage from each view and reports whether it agrees with
the recorded label. Measured across the estate:

| Verdict | Cameras |
|---|---|
| **CORROBORATED** | **8** — cam01 Chiman bhai Bridge, cam03 O.N.G.C. Office, cam04 Paldi Circle ("PALDI JUNCTION", "V.S. Hospital"), cam05 Visat teen Rasta, cam10 Char Chowk, cam13 CN Vidhyalaya, cam15 Suvidha Park, cam16 Visat T Junction |
| **NO OVERLAP** — worth a human look | 5, including cam06 labelled *Timbavadi Gate* whose view names "Madhuram Bypass Road" |
| **NO SIGNAGE READ** | 13 |
| Unreachable in both passes | 4 |

Two cameras with **no recorded name at all** gained their first positional
evidence: cam25 reads "GRAM PANCHAYAT", cam30 reads "Cafe Coffee Day, Hiralal,
Parakh".

Corroboration never *moves* a camera — turning a hoarding into coordinates
without a gazetteer would be inventing precision. The finding is recorded beside
the coordinates and shown in the camera panel, so anyone relying on a position
sees what it rests on:

> **cam01 · Chiman bhai Bridge · Ahmedabad** — STREAMING, ANPR UNSUITABLE,
> appearance GOOD, 609 observations, 9 evidenced neighbours
> **position LANDMARK, derived from name**
> *Signage in this camera's own view names Chiman bhai Bridge — corroborates the
> recorded position. Read locally by Qwen/Qwen3-VL-4B-Instruct.*

Evidence: `var/reports/landmarks.json`. **MEASURED**.

---

## Expected output 3 — watchlist and real-time alerts

> Demonstration of a working watchlist database integrated with the solution,
> showcasing continuous cross-referencing between live CCTV feeds and
> representative watchlist records, along with automated real-time alert
> generation upon detecting a match.

| What we do | Status |
|---|---|
| Versioned watchlist with mandatory authority and reason, jurisdiction scope and expiry. Entries are labelled `REPRESENTATIVE` — this is our own representative database, as the scenario permits, and it is never described as a live government record. | **MEASURED** |
| Continuous cross-referencing while the grid runs: `--minutes 0` holds the cameras open and matches every read. | **MEASURED** |
| Alerts carry a decomposed confidence (plate confidence × observation quality × category weight), a recommended action, and the observation ids they rest on. Low-confidence matches are suppressed and counted, not hidden. | **MEASURED** |
| Alerts are acknowledgeable and clearable, and every transition is in the audit chain. | **MEASURED** |

---

## Expected output 4 — integration, analytics, interoperability, scalability, performance

| Claim | Evidence | Status |
|---|---|---|
| CCTV integration | 30/30 cameras streaming concurrently; 16,913 frames, 590 observations, 11 reconnects, 79 scene cuts, 3.15 GB in one run | **MEASURED** |
| AI analytics | 8-check model activation gate; 4 models ACTIVE with head binding verified against pinned commits; 2 registry candidates FAILED with the blocker recorded rather than the model quietly removed | **MEASURED** |
| Interoperability | RTSP/TCP, HLS and WHEP endpoints handled; mixed h264/hevc; ONVIF-style metadata-first onboarding; edge bundle export for disconnected nodes | **MEASURED** |
| Scalability | 50 concurrent streams on one host; ingest capacity and analytics capacity reported **separately**, because a single process polling N queues is the analytics bottleneck and the architectural answer is more processes, not a faster loop | **MEASURED** |
| End-to-end performance | 43 API routes verified against the live store; 10 authorisation refusals fire as specified | **MEASURED**, `var/reports/api_surface.json` |
| Offline operation | The mandatory chain executes with **every non-local socket blocked** — nothing reaches out. Verified by enforcement, not by inspection, because "designed to work offline" is how a twelve-minute hang got shipped | **MEASURED** |
| Fault tolerance | A live capture survived **153 database write failures across a 50-second outage** with 885 observations persisted and none lost | **MEASURED** |
| Security and privacy | Four gates — authentication, role permission, jurisdiction scope, purpose binding. ADMIN holds no search permission; AUDITOR resolves camera identity but not what cameras saw. Pinned by assertions and negative tests. | **MEASURED** |

---

## Shown in the launch film (7 Sep 2026)

`var/demo/SAAKSHYA_launch.mp4` — 15 min 03 s, live government grid. Each expected
output is a timestamp, not a claim that the live grid grew a multi-camera route.

| Expected output | Film | What is on screen |
|---|---|---|
| Onboard ~50 cameras onto one platform | 2:10 Live wall; 5:15 Cameras | 30 of 30 issued cameras. Ingest stills with vehicle boxes, not a second RTSP copy. ANPR graded per camera. |
| Identify the designated vehicle by mark | 6:04 Find `GJ1VV0119` | Exact search, one-camera honesty, match basis. |
| OCR confusion must not rewrite the store | 6:58 Lookalike `6J1VV0119` | Stored mark unchanged; labelled requires verification. |
| Person detection | 6:58 cam28 `person` | Same detector pass as vehicles; never plated. |
| Watchlist + automated alert | 7:43 `GJ38BH5815` | Representative watchlist. Stolen-vehicle HIGH OPEN on cam21. |
| Route with timestamps | 6:04 trajectory panel | Single-camera **RESTRICTED**. Cross-camera identity is **0** on this store. Two-camera routes: `var/demo/SAAKSHYA_designated.mp4` on the local corpus (`GJ05AB1234`, `GJ35BV6925`). |
| Timebase honesty | 12:22 Copilot | cam01+cam21 **REFUSED**; cam01+cam04 asked next. |
| Integration / architecture / scale honesty | 9:13 System | Hybrid 1+2+3 with selected Model 4 analytics; statewide central recording declined on modelled 160 Gbps / 52 PB. Synthetic registry load is separate from live video. |
| Copilot (bonus, not mandatory) | 10:06–13:00 | Gemini on in the masthead (16 tools). Enhance-still refused. |

### Shown in the designated-vehicle film (own feed, 6 Sep 2026)

`var/demo/SAAKSHYA_designated.mp4` — 3 min 13 s, `var/demo.db`. Slate labelled
LOCAL SYNTHETIC. Do not present this as the government grid.

| Expected output | Film | What is on screen |
|---|---|---|
| Identify designated vehicle | 0:49 Find `GJ05AB1234` | Two observations, C-014 and C-021, CONFIRMED_BY_PLATE |
| Complete route with timestamps | 1:19 Movement | C-014 → C-021, 313 s, timebase **RESTRICTED** (honest) |
| Watchlist + automated alert | 1:45 Alerts | `GJ05AB1234` MEDIUM OPEN; `GJ15NT6564` HIGH OPEN |
| Second cross-camera mark (own-feed overlay) | 2:17 `GJ35BV6925` | Same two cameras as `own_feed.mp4` |

---

## What this system does not claim

- **Not** that ANPR works on every camera. It is graded per camera per time band,
  and on this grid most cameras are graded UNSUITABLE for plates with the
  measurement that shows why.
- **Not** that the evidence chain proves origin. It detects modification and
  truncation; it does not authenticate against an adversary able to rewrite the
  chain, which would need a signing key and trusted timestamping this deployment
  does not hold. The caveat travels inside every manifest.
- **Not** that a s.63 certificate is admissible. It is generated as
  `DRAFT_PENDING_SIGNATURE` and requires a human signatory.
- **Not** that cameras outside cluster `GRID-13JUN-2137` can be correlated. They
  cannot, and the system refuses instead of drawing a plausible line.
