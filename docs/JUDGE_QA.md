# Judge questions

Every answer here is grounded in code that exists or a measurement that was
taken. Where the honest answer is "we don't know" or "not yet", it says that.

---

## "You're supposed to trace a vehicle across the network. Show me the route."

We will, and the first thing on that screen is a **timebase verdict**, because
on this grid a route is not automatically meaningful.

The thirty cameras are replaying recorded windows, and they are not replaying
the *same* window. We read the cameras' own burned-in clocks — with a vision
model running on this machine, three frames per camera, two frames required to
agree — and measured it:

- **13 cameras share a timebase**: cam01–05 and cam07–14, all within six minutes
  of each other (21:37:55 to 21:43:44 on 13-06-2026). Across those, travel times
  are meaningful and we correlate.
- cam21 is at 15:03. cam24 is in August. cam26 is a different August day.
  Joining any of those to the cluster would draw a journey that never happened,
  so the system **refuses** and tells you which pair and why.

A system that will not draw the line it cannot support is worth more than one
that always draws something. Ask us to trace across cam01 and cam21 during the
demonstration — the refusal is the feature.

## "Why can't most of your cameras read number plates?"

Because most cameras on a real government estate cannot, and we measured it per
camera rather than claiming it uniformly.

cam04 at Paldi Junction sees 3,249 vehicles across 167 frames and reads **no**
plate. Median plate width in that view: **46 pixels**. cam21 sees 459 vehicles
and produces 33 plate detections at a median of **75 pixels**. It is geometry
and light, not traffic volume — and at the time of writing the replay places
most of the cluster at night, with predominantly two-wheelers and
auto-rickshaws. cam04's own frame is stamped `14-06-2026 00:57:57`.

So those cameras are graded **UNSUITABLE** for ANPR, and **GOOD** for presence
and appearance, which is the capability they actually have. An investigator is
told which cameras can answer "what was its number" and which can only answer
"was it here" — before they rely on either.

We also tested the obvious fix. Tiling the frame at native resolution instead of
downscaling to 1280 recovered nothing on these views. That is reported because
it did not work.

## "How do we know your camera positions are real?"

Nineteen of thirty are placed, each carrying its precision — LANDMARK ~150 m,
LOCALITY ~1.5 km, CITY ~6 km — and its basis, `DERIVED_FROM_NAME`. The map draws
the uncertainty **to scale**, so a position derived from a name never renders
identically to a surveyed one. The other eleven are recorded as
`NAME_INSUFFICIENT` and listed with the reason, never silently dropped.

Then we checked the names against the pictures. The local vision model reads
signage from each camera's own view: **8 cameras corroborated** — cam04's view
carries "PALDI JUNCTION" and "V.S. Hospital"; cam01's carries "Chiman bhai
Bridge". Five disagree and are flagged for a human, not corrected automatically:
cam06 is labelled *Timbavadi Gate* and its view names "Madhuram Bypass Road".

Two cameras that had no name at all now have their first positional evidence.
None of this moves a camera. Turning a place name on a hoarding into coordinates
without a gazetteer would be inventing precision, which is the failure this
system exists to avoid.

## "Does your AI copilot work without an internet connection?"

Yes, and by default nothing leaves the deployment at all.

With no language model configured the copilot runs on deterministic rules over
the same read-only tools the workspace uses. It answers plate lookups,
route traces, watchlist checks, camera capability, estate lists, timebase
checks and evidence verification, and says plainly when a question is outside
what it can plan. Every fact is checked against the tool results shown beneath
the answer, and the answer states that no language model was involved.

Setting `SAAKSHYA_GEMINI_KEY` (or `GEMINI_API_KEY`) enables free-form questions
via Gemini Flash as coordinator. It is off by default, because for government
CCTV the configuration where **no data leaves the system** should be the one
you get without asking. Detection, ANPR and evidence sealing never call it.

## "How do you know your models actually loaded correctly?"

Because we check the tensors, not the log.

Loading RT-DETRv2 prints a report marking `class_embed` and `bbox_embed` as
missing and "newly initialized" — which reads exactly like a detector with a
random head. It is benign: the checkpoint stores those under `model.decoder.*`
and the top-level names are aliases. But nothing in a five-check activation gate
could tell that benign case from the catastrophic one, because a randomly
initialised head still loads, still infers, and still returns well-formed boxes.
Only the numbers inside them are meaningless.

So the gate now has a **WEIGHTS** check that compares the live task head against
the checkpoint file at the revision the registry pins. Measured: **51/51**
tensors bit-identical for the vehicle detector, **99/99** for the plate
detector. Where the comparison cannot be made, it says so rather than passing
silently.

---

## Why hybrid rather than one model?

The challenge requires Model 1 (camera registry) plus at least one other. We
submit a **hybrid of Models 1 + 2 + 3**.

Model 1 is the **spine** — not a map screen, but the thing every other plane
reads camera identity, geometry, health and *capability* from. Nineteen cameras
are placed from their names; eleven without coordinates stay in the registry
strip and are not invented onto the map.

Model 2 is unified viewing as **ingest stills** (~1 Hz JPEG). The organiser's
guide gives each client its own stream copy; a thirty-tile live video wall would
be thirty extra RTSP sessions. Click-to-play is optional.

Model 3 is federated metadata intelligence: government RTSP plus local
MediaMTX, with the observation store as the bus.

Model 4 (full central video) was rejected on arithmetic, not preference. 80,000
cameras at even 2 Mbps is 160 Gbps of sustained ingress. No network Gujarat has
carries that, and no budget makes it appear.

## Why not a central VMS?

Same arithmetic, plus a second problem: a VMS answers "show me camera 47 at
14:02". An investigator's question is "where did this vehicle go", and no amount
of centralised video answers it without the metadata layer we would have to
build anyway.

## Why not just buy Genetec, Milestone, Axis?

They are good products and we say so. Three reasons they do not solve this:

1. **Licensing at 80,000 cameras** dwarfs the entire challenge budget.
2. **They assume a homogeneous, VMS-managed estate.** Gujarat's is neither —
   five departments, two decades, no common VMS.
3. **They do not measure per-camera capability.** They will happily run ANPR on
   a Panchayat camera that cannot resolve a plate, and report nothing found.

We are not claiming to out-engineer them. We are claiming that the specific
problem — *heterogeneous estate, unknown capability, no central video* — is not
the problem they were built for.

## Why graph-first retrieval instead of embedding search?

Because we measured the embedding and it failed. DINOv2 scored a decoy vehicle
at **0.941** similarity to the target while scoring the target against **itself**
at 0.412 — a margin of **−0.541**. Illumination normalisation made it worse
(−0.581).

An architecture that leads with appearance ranks by that signal. So structure
(indexed fields) and physics (learned travel times) prune first, and appearance
only reranks what physics already permits. The rejection is recorded in the
model registry with its evidence, and we did not quietly reverse it to make a
demo look better.

## Why is appearance a candidate rather than an identification?

Because that is what it is. A plate read is an identification — a registered
identifier with an authoritative source. An appearance match is "this could be
the same vehicle". Presenting the second as the first is how the wrong person
gets stopped.

The distinction is enforced in the data model (`CONFIRMED_BY_PLATE` vs
`REQUIRES_VERIFICATION`), in the API, and in the interface, and a test asserts
appearance candidates can never carry the confirmed status.

## Why measure camera capability at all?

Because on this estate it is the difference between a system that works and one
that appears to. Most of these cameras were installed to watch a gate. Running
ANPR on them and reporting "not found" tells an investigator nothing —
they cannot tell whether the vehicle was absent or the camera was never capable.

Three independent grades per camera per time band: ANPR, appearance, presence.
Measured from the camera's own stream, with the evidence stored beside the
grade. **In the current corpus: 3 GOOD for ANPR, 3 UNKNOWN.**

## Why is a camera "UNKNOWN" instead of "bad"?

Because silence is not failure. A camera that has produced no observations may
be pointed at an empty compound and working perfectly. Converting that into a
poor grade would slander working equipment and, worse, teach operators to
distrust the grades that *are* real.

Below the evidence floor (20 observations for ANPR), the answer is UNKNOWN with
the sample count attached.

## Why offline operation?

Because district connectivity fails, and outages correlate with incidents. An
edge node keeps ingesting, tracking, reading plates, matching its local
watchlist, raising alerts and sealing evidence with the uplink down. What is lost
is the centre's *view*, and that is recovered on reconnect.

Tested end to end: link down → detection, watchlist hit, alert, evidence; link
up → replay reconstructs the central timeline with **no duplicates and no loss**,
including the partial-delivery case.

## Why does evidence matter here?

Because an investigation that cannot be defended is wasted work. Frame, clip and
manifest are hash-chained; all five tamper tests fail as they must. The BSA s.63
certificate is prepared as a **draft** with both signature blocks empty.

We never say "legally admissible" — a test asserts the phrase appears nowhere in
any export. Admissibility is a judicial determination. What we can do is prepare
the material and the technical attestations a signatory would need.

## Why no face recognition?

The challenge concerns vehicles. Adding facial recognition would import a
substantially different legal, ethical and accuracy problem for no gain against
the stated task.

Concretely: a registration mark is a *registered* identifier with an
authoritative source and recourse when wrong. A face is a biometric with
neither. Error rates on CCTV-grade imagery are far worse than the controlled
benchmarks usually quoted, and the errors are not evenly distributed across the
population. India has no comprehensive data-protection framework in force for
this use.

There is no face pipeline in the codebase and no field for one.

## Why an LLM at all, and where is it?

Nowhere in the mandatory chain. A test asserts that no language-model library is
even imported while ingest → search → graph → trajectory → watchlist → alert →
evidence runs.

The copilot is an optional layer over the **same facade the UI calls**, with
read-only tools, **none of which writes**. It cannot reach anything the officer
could not, cannot skip an authorisation check, and cannot mutate state even if
fully compromised. Gemini, when configured, is a **coordinator** over named
specialists (Estate, Identity, Timebase, Evidence) that are those same tools —
not a swarm of agents that invent facts, and not a detector. It will not
enhance, generate, or invent a government still. Optional still-captioning is
off unless `SAAKSHYA_GEMINI_VISION=1`, and then the UI says the frame left the
deployment.

Every factual token in an answer — camera ids, plates, timestamps, statistics —
is checked against that turn's tool output. An answer that fails grounding is
withheld and the raw results are shown instead.

## Why not multi-agent?

Because we could not find a task here that a second agent does better than a
deterministic function. Multi-agent architectures multiply the number of places a
hallucination can enter and the number of places an authorisation check can be
skipped. One orchestrator, typed tools, verified output.

## How does it scale?

Honestly: **live-tested at 30 cameras on the organiser's own grid, designed for
80,000.** We will not conflate the two.

All thirty live government cameras ran simultaneously through the production
pipeline for four minutes: 16,913 frames delivered, 1,725 analysed, **590
observations**, 11 reconnects handled, 79 scene discontinuities handled, 3.15 GB
peak — on a 10-core Mac with no GPU. That is the simultaneous-run measurement.

The live store later accumulated **552,889 observations**, including
**145,868 persons**, from the same 30 cameras (`docs/MEASURED_RESULTS.md`,
6 Sep 2026 10:54 UTC; store still growing). Earlier snapshots (481,494 at
18:23 UTC 4 Sep; 516,849 at 09:22 UTC 6 Sep) must not be quoted as this run.
Do not quote 590 as the current store.

What made 30 fit was capability-aware scheduling doing real work rather than
being an architectural talking point. The first five-camera run decoded 22,121
frames to analyse 711 of them — three per cent. Keyframes on these cameras
arrive at 0.56 fps, almost exactly the T0 sampling rate, so 16 of 30 cameras now
decode keyframes only and pay about a twenty-fifth of the decode cost.

- Metadata-first: the centre carries observations, not video.
- District-level edge nodes with idempotent central aggregation.
- Every hot query indexed — 10 of 10, with the plans in
  `var/reports/query_plans.json`.
- Server-side clustering and viewport filtering so the map does not degrade into
  "send 80,000 rows and let the browser cope".
- Bounded admission: 8 concurrent searches, refused rather than queued.

Where it saturates is measured, not guessed: per-camera delivery collapses at
30 (cam08 delivers 3.73 fps against 25 declared), and 2,007 decoder warnings
appear only at that concurrency. The answer is more analytics processes per
node, or GPU inference — which is what the runtime profiles exist for.

## What happens if 30% of the cameras are poor?

That is the expected case, and it is what capability grading is for. Those
cameras are graded DEGRADED or UNSUITABLE for ANPR, keep their presence grade,
and are used for what they can do — placing a vehicle in a corridor. The
investigator sees the grade beside every result, and the map can filter to
ANPR-capable cameras directly.

## What happens if a camera is offline?

It is reported as `AVAILABILITY` coverage gap, its silence is excluded from any
inference, and the exclusion is listed in the search strategy with the words
*"absence of evidence, not evidence of absence"*. A trajectory leg through a
down camera is typed `COVERAGE_GAP`, not `UNOBSERVED`.

## What happens if OCR is wrong?

Several layers:

- Per-track voting across frames, with `plate_votes` recorded.
- `plate_raw` always stored beside the canonical form — what OCR actually
  returned is never discarded.
- Fuzzy matching is **opt-in** and every result is labelled
  `REQUIRES_VERIFICATION`.
- A physically impossible sequence produces a `CONTRADICTION` leg listing OCR
  error, cloned mark, clock drift and mis-association as alternatives —
  `"AMBIGUOUS — requires operator verification"`, never an accusation.
- The copilot **must not silently correct** a variant. Tested: given OCR
  `GJ05AB123B` against candidate `GJ05AB1234`, it must surface the difference
  rather than normalise it away.

## What happens if timestamps are wrong?

Assume they are. Ordering is by **PTS**, never wall clock. `t_ingest` is stored
separately and used only for diagnostics. Clock drift is measured per camera and
surfaced in health. A drift large enough to make a route impossible produces a
CONTRADICTION with clock drift named as an alternative — not a discarded result.

## What happens if the LLM is unavailable?

Nothing of consequence. `/copilot/describe` reports it is unavailable, the
copilot returns a clear message, and every other part of the system is
unaffected — because the chain never depended on it.

## What did the real feed change?

More than we expected, and the most important thing it found was a fault in our
own code.

**Three faults, together, meant no detector in this codebase had ever produced a
detection.** The backend chose its model class by comparing `record.task ==
"detect"` — a string matching no task in the registry — so every detector loaded
as a bare backbone. The flag that would have exercised that path defaulted to
off. And a broad `except` reported the resulting crash as "no vehicles". Every
test passed throughout, because the synthetic corpus has legible plates and
plate detection carried the pipeline. It took a Gujarat junction at 2 a.m., where
plates are unreadable, for the absence to become visible.

**16 of 30 cameras are in infrared night mode.** They deliver three-channel
frames whose channels carry identical values. A colour estimator asked to read a
vehicle from one returns a confident answer that is fabricated. We now measure
channel spread and grade appearance UNSUITABLE there; detection and presence are
unaffected.

**Most of the grid shares a clock; a minority does not.** Reading all thirty
overlays: **twelve cameras sit within three minutes of each other** on
14-06-2026, four are offset by up to four hours, four are on entirely different
dates, and ten show no clock at all.

So cross-camera correlation is meaningful across those twelve and meaningless
across the whole grid — and the system is unaffected either way, because nothing
in it reads a burned-in clock. Every timing decision comes from PTS and
normalised arrival. A system that trusted the overlay, *or* one that assumed a
common clock, would have produced journeys spanning weeks and called them
evidence.

We got this wrong first time by sampling twelve cameras where the outliers were
over-represented, and corrected it by reading all thirty.

## What can you actually show me on the live feed?

Single-camera: capability grading across six dimensions, vehicle detection and
classification, tracking, observation quality, abstention, stream health,
reconnects, scene-discontinuity handling, evidence. All measured, all in
`docs/LIVE_FEED_FINDINGS.md`.

Cross-camera plate search, graph and trajectory stay on the synthetic corpus,
where one coherent timeline exists by construction. We would rather show that
honestly than fabricate a route across cameras replaying different weeks.

## Why is ANPR yield low on the live grid?

Because much of the estate is wide, distant, and — in the replayed night
window — infrared. cam04 sees thousands of vehicles and reads no plate:
median plate width 46 px. That is geometry and light, not a broken model.
The plate reader works on the synthetic corpus; tracking forms; cropping is
correct. Cameras that cannot resolve a plate are graded UNSUITABLE and
declined, not guessed (C-033).

The accumulated live store is **not** empty of plates. As of the evening of
4 September 2026 it holds **38 distinct marks**, **70 corroborated
observations** (votes ≥ 2) and **11 leads** (votes = 1). **None** of those
marks appears on a second camera, so there is still no live multi-camera
identity. The **4-minute simultaneous run** that produced **590
observations** is a different, earlier measurement — quote it only as that
run, never as the current store.

A one-frame plate is published as a lead labelled `REQUIRES_VERIFICATION`.
Leads are in this store. They are never labelled `CONFIRMED_BY_PLATE`.

## What is not finished?

- The 2-hour chaos soak: harness exists, run pending.
- No PKI — evidence and watchlist integrity are content hashes, and every
  surface that reports them says so.
- No retention-enforcement job.
- No erasure mechanism: deleting an observation would break the evidence chain,
  and that needs designing rather than improvising.
- Confidence is **not calibrated**. Without labelled ground truth from real
  feeds it cannot be, and we call it a score rather than a probability.
- **Surveyed catalogue coordinates are still blocked.** Nineteen cameras are
  placed from their names (`DERIVED_FROM_NAME`) with stated precision; eleven
  are `NAME_INSUFFICIENT`. Nothing is invented to fill the map.
- **No live multi-camera route.** 69 plates, 0 cross-camera repeats, 1
  OCR-lookalike pair (`GJ32K5587`/`GJ3ZK5587`) across those marks
  (`docs/MEASURED_RESULTS.md`, 6 Sep 2026 21:02 UTC). The chain is complete on
  `LOCAL_SYNTHETIC`.
- **Portal registration** is outstanding. Official last date **15 September 2026**.
