# Live feed findings — Sentinel Camera Grid

**Provenance:** `GOVERNMENT_LIVE`. Every figure here was measured on the
organiser's grid on **2 September 2026, 00:15–01:30 IST**, on a 10-core Apple
Silicon Mac with no NVIDIA GPU.

These figures are not comparable with the local synthetic corpus and are never
merged with it. The corpus remains **regression**; this grid is **evaluation**.

Reproduce with `make live-profile` and `make live-ingest`.

---

## Access

| Endpoint | Status | Notes |
|---|---|---|
| RTSP `103.250.160.189:8554` | **Working** | TCP forced. Authenticates the URL authority with `SENTINEL_GRID_EMAIL` / `SENTINEL_GRID_PASSWORD` (environment only). **MEASURED 4 Sep 2026:** cam21 opened H.264 1920×1080 in 9.5 s with the issued access key. |
| WHEP `103.250.160.189:8889` | Port open | Browser preview; not used for analytics. Same authority authentication. |
| Catalogue `cctv.corp8.cloud/cameras.json` | **Blocked** | Redirects to `/auth/login`. Stream password as HTTP basic does not unblock it. Needs a signed-in session cookie. |
| Catalogue `http://103.250.160.189/api/ingest` | **Missing** | Documented in the integrator guide. **MEASURED 404** on the RTSP host. |
| HLS `cctv.corp8.cloud/<id>/index.m3u8` | **Blocked** | Same CDN session. Fallback transport only. |
| HLS `http://103.250.160.189/live/stream/<id>/index.m3u8` | **Missing** | Documented path. **MEASURED 404**. |

**Consequence of the blocked catalogue:** the camera set is **discovered by
probing the documented id pattern**, not read from the authoritative catalogue,
and every report says so. More importantly, **no camera has surveyed
coordinates** — location is a catalogue field. Thirty cameras are reachable,
analysed and graded; none can be placed from the catalogue, and nothing is
invented to fill it.

Supplying `SENTINEL_GRID_EMAIL` and `SENTINEL_GRID_PASSWORD` in the process
unblocks RTSP/WHEP. Supplying `SENTINEL_GRID_COOKIE` (or `_TOKEN`, or `_BASIC`)
unblocks the CDN catalogue and HLS. No credential is written to any file in
this repository. See `docs/SENTINEL_SANDBOX.md`.

The 2 September profile below was taken **before** the stream key was issued;
those RTSP samples connected without an authority. The 4 September capture
requires the key. Both are the same host.

---

## The estate

30 of 30 cameras reachable. Genuinely heterogeneous, which is the point:

| Property | Spread |
|---|---|
| Codec | 24 × H.264, **6 × HEVC** |
| Resolution | 960×576, 1280×720, 1280×960, 1920×1080, **2560×1440** |
| Declared rate | 10, 12, 20, 25, 30 fps — two cameras declare nothing |
| Measured rate | **4.0 – 30.0 fps** |

### The declared rate is wrong on 4 of 30

| Camera | Declared | Measured (PTS) | |
|---|---:|---:|---|
| cam01 | 30 | **15.04** | 50% |
| cam15 | 10 | **4.01** | 40% |
| cam03 | 30 | 25.04 | 83% |
| cam30 | 25 | 21.83 | 87% |

The guide warns about this and it is true. Every timing decision in this system
uses PTS; the declared rate is recorded and never used.

cam15 additionally advances its PTS at **0.396× wall time** — it is not keeping
up with real time, so periods of it are simply not delivered. Graded DEGRADED
for presence on the ratio, not on the rate.

---

## Half the estate is infrared

**16 of 30 cameras deliver monochrome / infrared frames at night.**

They still deliver three channels, so nothing upstream notices — but every
channel carries the same value. A colour estimator asked to read a vehicle from
one returns a confident answer that is **pure fabrication**.

| | Cameras |
|---|---|
| Monochrome / IR | cam02 cam03 cam06 cam07 cam09 cam13 cam15 cam16 cam18 cam19 cam22 cam24 cam25 cam28 cam29 cam30 |
| Colour | cam01 cam04 cam05 cam08 cam10 cam11 cam12 cam14 cam17 cam20 cam21 cam23 cam26 cam27 |

Detected by measuring **mean channel spread** (`mean_chroma`); IR cameras sit
near 0.005–0.02, colour cameras at night an order of magnitude above. Appearance
is graded UNSUITABLE on those cameras. Detection and presence are unaffected —
an IR camera still sees vehicles perfectly well.

This is the single most consequential thing the live feed revealed, and it is
invisible to any metric that only looks at brightness.

---

## Camera clocks: most of the grid is synchronised, a minority is not

**Corrected after reading all thirty.** An earlier pass sampled twelve cameras,
found `02:55`, `04:43` and a different date among them, and concluded the grid
was unsynchronised. That conclusion was wrong, and the error was sampling: the
outliers happened to be over-represented in the twelve.

Reading the burned-in overlay of all thirty:

| Group | Cameras | Clock |
|---|---|---|
| **Synchronised** | cam01–05, cam07–11, cam13, cam14 — **12 cameras** | `14-06-2026 03:53`–`03:56` |
| Offset, same date | cam15 (`00:08`), cam18 (`04:16`), cam17 (`04:47`) | 14-06-2026, up to ~3¾ h apart |
| Different date | cam06 (`18-06`), cam20 and cam25 (`2026-08-04`), cam24 (`08-07`) | weeks apart |
| No visible clock | cam12, cam16, cam19, cam21–23, cam26–29 | — |

The spread across the synchronised twelve is under three minutes, and the
captures themselves were taken sequentially over about that long — so they are
effectively on one timeline.

### What this means

- **Cross-camera correlation is physically meaningful across those twelve.** A
  vehicle passing cam01 and later cam04 is the same journey. The corridor
  exists.
- **It is not meaningful across the whole grid.** Anything linking cam01 to
  cam20 would be joining scenes seven weeks apart, and the system must not be
  asked to.
- **The design is unaffected either way**, which is the point of it. Every
  timing decision comes from PTS and normalised arrival; nothing reads the
  burned-in clock. A system that had trusted the overlay would have produced
  journeys spanning weeks and presented them as evidence — and one that assumed
  a common clock would have done the same.

### What still blocks the live chain

Synchronised clocks are necessary and not sufficient. The camera graph learns
transitions from **plate matches**, and at 03:53 in infrared there are no plate
reads at all. So the corridor is there and the vehicles are there; what is
missing is a shared identity to link them by.

When the replayed window reaches daylight, the synchronised twelve are the
cameras to point the chain at, and this table says which they are.

**Addendum, 4 September 2026.** Later ingest on the same 30 cameras accumulated
**444,073 observations** including **116,678 persons**, and **34 distinct
plates** (detection report, 15:15 UTC; store still growing — quote Overview on
the day). Every mark is still confined to a single camera (GJ32AG0028 ×38 is
cam06 looping). A read-only scan of those 34 marks found **0 exact
cross-camera repeats and 0 one-character OCR-lookalike pairs** (16:40 UTC).
Successful plated observations average 116 px wide; three of 77 are under 48 px.
The block above remains: no live multi-camera identity. Do not quote the 03:53
"no plates" finding as the current store.

## Capability, measured

From a 25-second real-time sample per camera:

| Dimension | GOOD | DEGRADED | UNSUITABLE | UNKNOWN |
|---|---:|---:|---:|---:|
| Presence | 28 | 2 | — | — |
| Vehicle detection | 29 | 1 | — | — |
| Vehicle appearance | 14 | — | **16** | — |
| Tracking | 28 | 1 | 1 | — |
| Forensic | 20 | 10 | — | — |
| ANPR | — | — | — | **30** |

**Tiering from measurement: 14 cameras at T1, 16 at T0** — the analytics cost
halved before a single expensive inference ran.

**cam22 delivered one frame in 25 seconds** on the first pass and 25 fps on the
second. Graded UNKNOWN with `evidence_confidence: NONE` the first time. A single
sample is not a verdict, and the report says so rather than calling a camera
broken.

---

## Ingest through the production pipeline

Staged, capability-aware, RTSP/TCP, all through ordinary production code.

| | 5 cams | 10 cams | 20 cams | **30 cams** |
|---|---:|---:|---:|---:|
| Duration | 3 min | 3 min | 3 min | 4 min |
| Streaming at end | 5/5 | 10/10 | 20/20 | **30/30** |
| Frames delivered | 22,121 | 10,250 | 9,591 | 16,913 |
| Frames analysed | 711 | 553 | 1,175 | 1,725 |
| **Observations** | 396 | 173 | 458 | **590** |
| Reconnects (handled) | 2 | 3 | 0 | 11 |
| Decoder warnings | 0 | 0 | 0 | 2,007 |
| Scene cuts handled | 0 | 1 | 55 | 79 |
| Peak RSS | 1.15 GB | 1.69 GB | 2.68 GB | **3.15 GB** |

**All thirty live government cameras ran simultaneously through the real
pipeline**, on a 10-core Apple Silicon Mac with no GPU.

The 5- and 10-camera columns are not directly comparable: keyframe-only decoding
for T0 was introduced between them, which is why 20 cameras deliver *fewer*
frames than 5 did while analysing more of them.

### Keyframe-only decoding for T0

The first 5-camera run decoded 22,121 frames to analyse 711 — **three per cent**.
Decoding is the cost, and the rest was thrown away.

Measured on these cameras: keyframes arrive at **0.56–0.57 fps** (a ~1.8 s GOP),
which is almost exactly the T0 sampling rate. So a T0 camera is now served by
`skip_frame = "NONKEY"` at roughly one twenty-fifth of the decode cost, and 16
of 30 cameras are T0. T1 and above still decode everything — they need frames
close enough together to associate a vehicle, and a track that sees a vehicle
twice two seconds apart is not a track.

This is capability-aware scheduling paying for itself: **it is what made 20 and
30 cameras possible on this machine at all.**

### Where it saturates — measured, not modelled

Per-camera delivery collapses as concurrency rises. At 30 cameras:

| Camera | Declared | Measured at 30 |
|---|---:|---:|
| cam08 | 25 | **3.73** |
| cam14 | 10 | 3.86 |
| cam11 | 25 | 5.44 |
| cam04 | 25 | 5.87 |
| cam27 | 25 | 25.25 |

The 2,007 decoder warnings appear only at 30 and are the same signal from the
other side: thirty concurrent TCP streams arriving faster than one process
consumes them. They were logged and survived, exactly as the guide says to
expect, and the run finished with 30/30 still streaming.

**Live-tested at 30 cameras. Statewide scale remains architecturally designed
and modelled, and the two are not the same claim.**

## ANPR on the live grid — night, then daylight

The replayed window advances in real time. It reached daylight at roughly
`14-06-2026 08:00`, and the answer changed completely.

### At night (02:00–04:00)

**Zero valid reads** across 124 sampled frames. Diagnosed rather than assumed:
the plate model reads the synthetic corpus, 42–64 tracks formed per camera,
cropping was correct. Near-empty junctions, infrared, wide views. A source
condition, and no threshold change would have altered it.

### In daylight (08:00)

Plates are detected and **read**. Through the production pipeline — vehicle
detection → tracking → per-track voting — at 3 fps on one camera at a time:

| Camera | Frames | Vehicle detections | Plate detections | Median plate width | Plated observations |
|---|---:|---:|---:|---:|---:|
| cam21 | 160 | 459 | **33** | **75 px** | **2** |
| cam04 | 167 | 3,249 | 5 | 46 px | 0 |
| cam01 | 155 | 3,194 | 3 | 88 px | 0 |

The discriminator is **plate geometry, not traffic volume**. cam04 sees seven
times as many vehicles as cam21 and reads no plates: its vehicles are too far
from the camera. This is precisely what capability grading exists to measure,
and it cannot be inferred from resolution, codec or any catalogue field.

### Registration marks read from the government feed

```
GJ38BH5815   cam21   2 agreeing frames   confidence 0.99   quality 0.96
GJ21T4831    cam20   2 agreeing frames   confidence 0.92   quality 0.97
```

Raw OCR from the same window shows the shape of the problem and the discipline
around it — `GJ24AA2127` at confidence 1.00 alongside `GJ2AA4472` and
`GJ2UA447` from poorer frames of what is likely the same vehicle. Per-track
voting is what turns that into one answer or none.

### Yield is low, and the reason is measured

**2 plated observations from 447**, on four cameras over seven minutes.

The cause is not the model. At ten concurrent T2 cameras this machine delivered
3,747 analysed frames in six minutes — about **0.6 fps per camera**, against the
2.0 the tier asked for. A registration mark is legible for a second or two as a
vehicle passes; at 0.6 fps it gets one frame, and per-track voting never
accumulates.

**A tier is a promise the host has to be able to keep.** Asking for T2 on ten
cameras when the machine can serve three is how a system produces no plate reads
and blames the model. The ingest now checks the demanded frame rate against a
stated budget and says so up front rather than letting it surface as a yield of
zero.

On a GPU, or across more analytics processes, the same code has more frames to
vote over. That is the argument for the deployment target, and it is now an
argument from measurement rather than from architecture.

## The mandatory chain, on government data

Run against `var/live.db` with the target read from the live feed:

```
1. watchlist   GJ38BH5815 v1 [REPRESENTATIVE]
2. search      1 observation · cam21 · CONFIRMED_BY_PLATE · quality 0.962
3. trajectory  1 hypothesis · timebase ALLOWED
4. alert       raised · confidence 0.983
               plate 0.995 · quality 0.962 · category 1.0
               action: VERIFY and notify the district control room
5. evidence    sealed · verification PASS
               s.63 DRAFT_PENDING_SIGNATURE, both signatures empty
6. evidence chain  VERIFIED
7. audit chain     VERIFIED
```

Ordinary production code throughout. No target-specific branch, no
camera-specific handling, and the plate was not chosen in advance — it is
whatever the grid gave us.

## What this feed found that the corpus could not

Three faults, each individually catchable, which together made the system
**incapable of detecting a vehicle** while every test passed:

1. `TransformersBackend.load` compared `record.task == "detect"`, a string
   matching no task in the registry. Every detector loaded as a bare backbone.
2. `enable_vehicle_detector` defaulted to `False`, so that path never ran.
3. A broad `except Exception` reported the resulting crash as "no vehicles".

The synthetic corpus could not have found it: its plates were legible, so plate
detection carried the pipeline and the vehicle detector was never needed. It
took footage where plates are *unreadable* for the absence to become visible.

Full detail in `docs/CODE_REVIEW_LOG.md`, CR-006.

---

## Outstanding

| Item | Blocker |
|---|---|
| Camera coordinates, GIS, map | **Catalogue session** — stream key does not unblock `cameras.json` |
| ANPR baseline, plate search, graph, trajectory | **Daylight in the recorded loop** |
| Sustained 30-camera operation | Runs, but per-camera delivery degrades; needs a second analytics process or GPU inference |
| Appearance benchmark on real vehicles | Needs colour daylight footage |
