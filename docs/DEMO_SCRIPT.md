# Demonstration script

Historical planning / measurement record. For the current submission use
[FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Current roles: government
`GJ11S7924` on cam06 is SINGLE-CAMERA evidence; own-feed `GJ18JX7786` on
C-014 then C-021 is a CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). Earlier rehearsal plate names,
screenshot counts, timings and dates below belong to their recorded run.
Current wall policy: CONTROL ROOM up to 30 direct WHEP sessions, 400 ms apart;
OPTIMIZED VIEW at most 12, 600 px prefetch, released after 15 s off screen
(`ui/app.js`). Old still-wall descriptions below are historical.


Two recordings are required by the portal: **own feed, 2–3 minutes (hard cap)**
and **government feed, plus an output report** of detected vehicles and plates
with timestamps.

Mock-ups, animations and concept videos are explicitly not accepted. Everything
below is the working system.

> **Read [TEST_SCENARIO_ALIGNMENT.md](TEST_SCENARIO_ALIGNMENT.md) first.** It maps
> each of the organisers' four expected outputs to what this system does and to
> the measurement behind it. This script is how to *show* that; that document is
> what is being shown.

---

## Government-feed recording · the four expected outputs

The panel supplies a registration number during the evaluation. The flow below
is rehearsed end to end on the live grid. The launch film
(`var/demo/SAAKSHYA_launch.mp4`) drives every surface for 15+ minutes.

### 1 · Onboarding — "one integrated platform"

Open **Cameras**. Thirty government cameras in one registry, discovered over the
documented RTSP interface and every record labelled `source="probe"` because the
catalogue endpoint requires a session we were not given. Mixed h264 and hevc,
resolutions from 640×576 to 2560×1440, and sixteen monochrome — detected from
the imagery, not read from a config file.

Point at the ANPR column. Most cameras read **UNSUITABLE** or **UNKNOWN**.

> This is the honest position and it is the whole thesis. Plate capability here
> is geometry and light, not traffic. cam04 sees three thousand vehicles and
> reads no plate — median plate width forty-six pixels. The system measures that
> per camera and says so, instead of claiming ANPR everywhere and failing
> quietly on the day.
>
> Open **Overview**. The estate row is the current store: observations in the
> hundreds of thousands, persons from the same detector pass, confirmed plates
> and **leads** (one-frame reads, labelled requires verification). Then **Live**:
> 30 of 30 stills from ingest, not a second RTSP copy. Then **Estate map**: 19
> markers, 11 in the registry strip without coordinates. Then **Find**: type
> `person`, camera `cam28`, and search. Dwell is printed; the caveat says identity
> is not. People are never plated.
>
> If the panel types a mark with an O/0 confusion, search still finds the stored
> read and labels it an OCR lookalike — the stored mark is not edited.

### 2 · The designated vehicle

Paste the panel's registration mark into **Target search**. Then:

1. **Watchlist** — add it with authority and reason. Both are mandatory; an
   entry with no stated authority cannot be created.
2. **Search** — every stored observation, with the cameras considered and the
   ones pruned, and why. If the panel types an O/0 or G/6 confusion, the stored
   read still appears as an OCR lookalike labelled `REQUIRES_VERIFICATION`; the
   stored mark is not edited. If every hit is on one camera (`GJ32AG0028` on
   cam06), Find says **one camera only** — looping footage, not a fleet.
3. **Route** — hypotheses with a **timebase verdict at the top**.

Rehearsed 4 September 2026 evening on the live grid (**MEASURED**): `GJ1VV0119`
on cam07 (watchlist + exact search + lookalike `6J1VV0119` + sealed evidence);
`GJ38BH5815` on cam21 already has the OPEN alert; `GJ32AG0028` is looping
reads on cam06, not a fleet. As of 6 Sep 20:54 UTC the live store also holds
one OCR-lookalike pair, `GJ32K5587` / `GJ3ZK5587` on cam07 (2 vs Z, seconds
apart) — two stored marks, not merged. Cross-camera identity is the
LOCAL_SYNTHETIC pair `GJ05AB1234` / `GJ35BV6925` on port 8081 — the government
grid has 0 repeats.

### 3 · The timebase verdict — the part that matters

This is the strongest single moment in the demonstration. Show the amber banner.

> The grid is thirty replayed windows, not a synchronised estate. We read the
> cameras' own burned-in clocks with a vision model running **on this machine**.
> Thirteen cameras — cam01 to cam05 and cam07 to cam14 — sit inside six minutes
> of each other. Those we will correlate. cam21 is at 15:03, cam24 is in August.
> Joining those would draw a journey that never happened, so the system refuses
> and tells you why.

Then show the opposite case: a single-camera route reports that there is no
interval to reason about, rather than claiming a shared timebase vacuously.

> A system that will not draw the line it cannot support is worth more than one
> that always draws something.

### 4 · Watchlist alert, continuously

```bash
python tools/live/ingest.py --db sqlite:///var/live.db     --only cam01,cam02,cam04,cam05,cam13,cam14 --tier T2 --minutes 0
```

`--minutes 0` runs until stopped — continuous cross-referencing against the
active watchlist, which is what the scenario asks for. Leave it running in a
second window and let the alert arrive on the **Alerts** screen while you talk.

### 5 · Evidence

Seal an observation. Show the manifest, then **Verify evidence**:

> Record exists. Manifest hash matches. And this line — *media retained: none;
> its integrity checks cover the manifest and the chain, and cover no image*.
> We do not retain government footage, so this record attests what the system
> observed, not a copy of the video, and it says so rather than letting you
> assume otherwise.

Finish on **Evidence chain → verified**, and the **Audit log**, which shows every
search with its case, purpose and actor.

---

## Before recording

```bash
make demo          # seeds an isolated store; prints sign-in tokens once
make serve         # http://127.0.0.1:8080
```

`make demo` writes to `var/demo.db`. It **refuses** to write to the evaluation
store — a demonstration must never be able to improve a measured result.

Sign in as `supervisor.demo`. Note the target plate and the two UNKNOWN-capability
cameras it prints; the script below refers to them.

---

## Own-feed recording · 2:45

### 0:00 — 0:20 · The problem, on screen

Open **Cameras**. Do not narrate a slide; point at the table.

> Six cameras, five departments. Three can read a registration number. Three we
> have not measured enough to say — and the system says *UNKNOWN*, not *bad*.
> A camera pointed at a quiet compound is not a broken camera.

This establishes the thesis in twenty seconds: **the estate is heterogeneous and
the system knows it.**

### 0:20 — 0:35 · Purpose binding

Clear the Purpose field at the top. Run a search. It is refused:

> `PURPOSE_REQUIRED — supply a case id and a stated purpose. It is recorded in
> the audit log.`

> Authentication tells us who is asking. It does not establish entitlement to
> somebody's movement history. Every vehicle search here carries a case and a
> written reason, or it does not run.

Restore the case and purpose.

### 0:35 — 1:10 · Find

Enter the target registration mark. Search.

Point at one result row and then at the right-hand panel:

> Every match decomposes. Plate 1.00 at weight 0.45; source quality 0.93 at
> 0.10. The weakest signal is named. There is no screen in this product that
> shows you 94% and nothing else.

### 1:10 — 1:45 · Trace

The map already shows the route; the strip below shows the legs.

> Four cameras. The solid legs are OBSERVED. This dotted one is a COVERAGE GAP —
> no camera on record could have seen the vehicle between those two points.
>
> That is absence of evidence. It is not evidence that the vehicle was
> elsewhere, and the system says so in words, because under time pressure that
> distinction is the one people lose.

If the corpus produced a track-fragment merge, point at the note:

> Four track fragments at one camera inside three seconds — one pass, not four.
> Merged, and the merge is stated.

### 1:45 — 2:05 · The hard case

Point at the gap candidates.

> This camera could not read the plate. It is offered as a candidate requiring
> verification — never as an identification. The plate term in its score is
> exactly zero, and the panel says which signal is weakest.

### 2:05 — 2:30 · Verify

Select an observation with evidence. Press **VERIFY EVIDENCE**.

> That ran the real check: the frame digest, the clip digest, the manifest hash,
> and the chain link. Not a simulated one — there is no simulated path.
>
> The s.63 certificate is a draft with both signature blocks empty. We never say
> "legally admissible"; a test asserts that phrase appears nowhere in any
> export. Admissibility is for a court.

### 2:30 — 2:45 · Audit

Open **Audit log**.

> Every search just performed, with the officer, the case and the purpose,
> hash-chained. A deleted or altered entry breaks the chain, and the chain is
> verified every time this page loads.

**Stop at 2:45.** The cap is hard.

---

## Government-feed recording

The grid is live and profiled. What can honestly be shown on it is bounded by
what is in it, and the boundary is worth stating on camera rather than working
around.

```bash
make live-profile           # characterise every reachable camera
make live-ingest            # staged 5 -> 10 -> 20 -> 30, capability-aware
make live-serve             # workspace over the live store
```

### Phase 6 live-video path

Use `config/demo_live.yaml` as the single operator configuration. The wall
remains ingest stills by default; select one camera for the preferred
WHEP/WebRTC path. If negotiation fails or the source is a file-view, the
selected stage falls back to the fresh ingest snapshot rather than displaying a
black rectangle. Open the expandable **Telemetry** drawer to show only browser-
observed decoded frames, dropped frames, packets, jitter, codec, startup, and
reconnect state. CPU/GPU utilisation is explicitly unavailable.

Do not claim a measured WebRTC/HLS winner until the authenticated venue run has
populated `reports/LIVE_FEED_FINAL_BENCHMARK.md`. The current path decision is
provisional and is documented in `reports/LIVE_FEED_PATH_DECISION.md`.

### 0:00 — 0:25 · The real estate

Open **Cameras** over the live store. Thirty government cameras.

> Thirty cameras, live, from the organiser's grid. Six are HEVC, the rest H.264.
> Resolutions from 960×576 to 2560×1440. Four of the thirty report a frame rate
> that does not match what they deliver — cam01 declares 30 and delivers 15.
>
> This is the estate. Nothing here is configured; it is all measured from the
> streams.

### 0:25 — 0:55 · Sixteen cameras cannot do colour

Point at the appearance column.

> Sixteen of thirty are graded UNSUITABLE for appearance. They are in infrared.
>
> They still deliver three-channel frames, so nothing upstream notices — but
> every channel carries the same value. Ask a colour estimator to read a vehicle
> from one and it gives you a confident answer that is pure fabrication.
>
> We measure the channel spread and refuse. Detection and presence are
> unaffected — an infrared camera sees vehicles perfectly well.

### 0:55 — 1:20 · Thirty at once

Show the ingest report.

> All thirty running simultaneously through the production pipeline: 16,913
> frames delivered, 590 observations, 11 reconnects handled, 79 scene
> discontinuities handled, on a laptop with no GPU.
>
> What made thirty fit: sixteen of them decode keyframes only, because we
> measured that their keyframes arrive at 0.56 frames a second — almost exactly
> the sampling rate their tier needs. That is capability-aware scheduling
> earning its place, not describing itself.

### 1:20 — 1:45 · What we will not claim

This is the most important twenty-five seconds of the recording.

> Plate reading on this grid is sparse, not zero, and we are not going to
> inflate it.
>
> The replayed night window is wide views in infrared, where a plate at
> junction distance is a handful of pixels. The accumulated store still found
> 38 distinct marks — 70 corroborated, 11 leads, **none on a second camera**. GJ32AG0028
> appears 38 times on cam06 because that camera is looping; that is not 38
> vehicles and we will not present it as a route.
>
> The 4-minute simultaneous run that produced 590 observations is a different
> measurement from the accumulated live store (481,494 observations at 18:23 UTC
> in `docs/MEASURED_RESULTS.md`; still growing — quote Overview on the day).
>
> And the cameras do not all share a clock. Twelve of the thirty sit within
> three minutes of each other; four are hours apart, four are on entirely
> different dates, and ten show no clock at all.
>
> So a route across those twelve would be a real journey — and a route from
> cam01 to cam20 would join scenes seven weeks apart. Our system is unaffected
> either way, because nothing in it reads the burned-in clock; ordering comes
> from presentation timestamps.
>
> What still blocks the live chain is not the clocks, it is shared identity.
> The graph learns transitions from plate matches across cameras, and none of
> the 34 marks left its camera. The corridor is there and the vehicles are
> there; the live multi-camera identity is not. Show that on LOCAL_SYNTHETIC
> (`GJ05AB1234`, `GJ35BV6925`) and say so.

If the organisers supply a target and an expected route, that implies a coherent
window we have not found — the first step is to re-read the overlay clocks and
ask which cameras share one.

### Output report

Required deliverable: detected vehicles **or** persons, with timestamps, and
plates where a plate was read. Two artefacts, **not interchangeable**:

- The government-feed **video** ships with its own CSV/JSON from that render.
- The **full live-store report** is `var/reports/detections/` (Markdown/JSON
  6 Sep 2026 10:54 UTC: 552,889 observations, 145,868 persons, 44 marks).
  The CSV beside it is an earlier snapshot — do not quote both as one run.
  Quote Overview or `docs/MEASURED_RESULTS.md` for the current store. People
  are never plated. Dwell is reported; "intrusion" is not claimed.

## The offline demonstration

Worth 40 seconds if the recording has room. `make test-e2e` runs it; the
narration is:

> The central link is down. The node keeps detecting, keeps matching its local
> watchlist, keeps raising alerts, keeps sealing evidence.
>
> Link restored: the queue replays, the central timeline reconstructs, no
> duplicates and no loss — including the case where delivery was only partial.

---

## What not to do

- **Do not zoom the browser to hide an empty panel.** An empty panel is a true
  statement about the data.
- **Do not quote 80,000.** Say "measured at six cameras, designed for eighty
  thousand" and mean both halves.
- **Do not say "AI-powered".** Say what it does: it reads plates, learns travel
  times between cameras, and refuses to guess.
- **Do not demonstrate the copilot before the deterministic chain.** The order
  is the argument: the system works without it. After the chain, open Copilot
  and run, in this order: infrared cameras (stills pin from tool results) →
  `May cam01 and cam21 share a timeline?` (REFUSED) → `May cam01 and cam04
  share a timeline?` (ALLOWED) → `Enhance this still and sharpen the plate`
  (refused as evidence fabrication) → optional Describe still only if vision
  is on, and say the frame left the host.
