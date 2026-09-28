# Bonus scorecard

Historical scorecard. Current submission claims, wall policies and evidence limits
are in [FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Still-wall counts and old
render_deck.py references below describe earlier runs.

The challenge's six bonus criteria, mapped to what exists, with an honest status
per line. Three states, and they mean different things:

| | |
|---|---|
| **IMPLEMENTED** | the code exists and runs |
| **TESTED** | there is a test that fails if it breaks, or a measurement on record |
| **DEMONSTRATED** | it has been exercised **on the live government grid**, not on the synthetic corpus |

A line that is IMPLEMENTED but not TESTED is not a feature we would defend. A
line that is TESTED but not DEMONSTRATED works — on data we made.

---

## B1 · Hybrid architecture

| Item | Status | Evidence |
|---|---|---|
| Model 1 (camera registry) as the spine every plane reads from | DEMONSTRATED | 30 government cameras in one registry; 19 on the map, 11 listed without invented coordinates |
| Model 2 (unified viewing as ingest stills) | DEMONSTRATED | 30/30 JPEG wall at ~1 Hz; not a second RTSP copy per tile |
| Model 3 (federated metadata intelligence) | DEMONSTRATED | observations, graph and search over the live estate |
| Statewide central recording declined; selected Model 4 analytics retained | — | 160 Gbps / 52 PB, [SCALE_MODEL.md](SCALE_MODEL.md) |
| Heterogeneity handled as data | DEMONSTRATED | mixed h264/hevc, 640×576–2560×1440, 16 of 30 monochrome — all detected, none configured |

**The argument.** Gujarat does not need to replace what it has. The registry is
not a map screen; it is the thing that knows what each camera *is* and what each
camera can *do*, and every other plane reads from it.

---

## B2 · Cross-camera movement correlation

| Item | Status | Evidence |
|---|---|---|
| Camera graph with learned travel-time distributions | IMPLEMENTED, TESTED | edges become `trusted` only at ≥3 samples |
| Timebase clusters as a precondition for correlation | DEMONSTRATED | `GRID-13JUN-2137`, 13 cameras, basis MEASURED_OVERLAY |
| Per-pair correlation verdict ALLOWED / RESTRICTED / REFUSED | DEMONSTRATED | cam01+cam04 allowed; cam01+cam21 refused |
| Trajectory hypotheses with coverage gaps and contradictions | IMPLEMENTED, TESTED | hypothesis A/B/C with per-leg evidence |
| Next-best-camera ranking | DEMONSTRATED | 8 suggestions from cam01, weights exposed |
| Verdict shown to the investigator, not just computed | DEMONSTRATED | timebase banner leads the route panel |

**The argument, and the honest limit.** This grid is thirty replayed windows,
not a synchronised estate. Thirteen cameras were *measured* to share a timebase —
their own burned-in clocks, read by a vision model on this machine, three frames
each, two required to agree, all inside six minutes. The rest are hours or months
apart and are **refused**. A system that will not draw the line it cannot support
is worth more than one that always draws something.

Learned transitions on the live grid: **0**. 112 links are seeded from geography
and are labelled unproven. Learning them needs the same vehicle read on two
cameras, which needs ANPR yield this replay window does not currently offer.

---

## B3 · Analytics beyond ANPR

| Item | Status | Evidence |
|---|---|---|
| Vehicle detection, tracking, colour and type attributes | DEMONSTRATED | 4,636 observations from the live grid |
| Presence and appearance graded per camera per time band | DEMONSTRATED | 12 presence GOOD, 9 appearance GOOD, 0 ANPR GOOD |
| Monochrome/IR detection from imagery | DEMONSTRATED | `mean_chroma`, 16 of 30 cameras |
| Local VLM reading burned-in clocks | DEMONSTRATED | 26 of 30 clocks read |
| Local VLM corroborating camera location from signage | DEMONSTRATED | 8 of 30 positions corroborated |
| Appearance re-identification | MEASURED, **not adopted** | 0.831 balanced accuracy, distributions overlap — ranks, cannot confirm |
| Wrong-way detection | **MEASURED, declined** | directional concentration R=0.22 median across 13,658 observations; these are junction cameras and traffic legitimately turns. A detector here would fire on lawful traffic and devalue every other alert |
| Decoder-concealment detection | DEMONSTRATED | cam21 CORRUPT at 94%, cam16 DEGRADED at 38%, cam01 OK — a stream that decodes without error into garbage is named, not read as an empty road |

**The argument.** The estate's real capability is presence and appearance, not
plate reading, and the system is built so a camera that cannot read a plate still
contributes evidence. The two VLM analytics run **on-device**: no frame leaves
the deployment.

---

## B4 · Edge and low-bandwidth operation

| Item | Status | Evidence |
|---|---|---|
| Metadata-first: observations move, video does not | DEMONSTRATED | the live pipeline transports no video |
| Edge node bundle export and ordered replay | IMPLEMENTED, TESTED | no duplicates, no loss on reconnect |
| Watchlist bundle for a disconnected node | IMPLEMENTED | `/edge/watchlist/bundle` |
| Keyframe-only decoding for the cheapest tier | DEMONSTRATED | what made 30 concurrent cameras fit |
| Runs with no route to the internet | DEMONSTRATED, **enforced** | the mandatory chain runs with every non-local socket blocked — search, watchlist, alert, evidence, chain verification, assistant, model loading. `tests/e2e/test_no_network.py`, including a test that the block itself works |
| Measured bandwidth saving | **MEASURED** | **19x** on three live cameras — 1.36 Mbps of video against 0.071 Mbps of observations at peak event rate |

---

## B5 · Security, privacy and RBAC

| Item | Status | Evidence |
|---|---|---|
| Four gates: authentication, role, jurisdiction, purpose | DEMONSTRATED, TESTED | **10/10 refusals fire as specified** |
| Separation of duty: ADMIN holds no search permission | TESTED | asserted at import |
| AUDITOR resolves camera identity, not what cameras saw | TESTED | three negative API tests |
| Purpose binding recorded in the audit chain | DEMONSTRATED | every search carries case and reason |
| Hash-chained audit and evidence | DEMONSTRATED | both verify on the live store |
| Secrets never in source, logs or responses | TESTED | secret scan over tree *and* history |
| Prompt-injection content treated as data | IMPLEMENTED, TESTED | scanned and reported, never followed |
| No external AI by default | DEMONSTRATED | `AI_PROVIDER` defaults to local rules |
| Gemini coordinator over named specialists (optional) | IMPLEMENTED, TESTED | Estate / Identity / Timebase / Evidence are the same read-only tools; grounding withholds invented cameras; `refuse_imagery` never fabricates a plate |
| Government stills not enhanced or generated | TESTED | `refuse_imagery` always refused; vision caption off unless `SAAKSHYA_GEMINI_VISION=1` and labelled FRAME LEFT THE DEPLOYMENT |

---

## B6 · Operational dashboards and APIs

| Item | Status | Evidence |
|---|---|---|
| Submission deck, generated from the repository's own source | DEMONSTRATED | `tools/demo/render_deck.py` → 17-page PDF from `docs/PPT_CONTENT.md`; status markings render as chips so measured and modelled numbers are distinguishable at a glance |
| HLD architecture diagrams | DEMONSTRATED | `tools/demo/render_diagrams.py` → four drawn diagrams: logical architecture, search path with its four gates, evidence chain, camera capability |
| Government-feed demonstration video + output report | MEASURED | 6/7 cameras, 363 vehicles, 8,116 timestamped rows, 114 s paced to real time |
| Own-feed demonstration video + output report | MEASURED | local synthetic corpus, 14 distinct registration marks, 2 read across two cameras each |
| Live camera wall with real imagery | DEMONSTRATED | thirty tiles with grades; cached stills badged STILL with frame age |
| True live video over WebRTC (WHEP) | DEMONSTRATED | cam01 playing live, badged LIVE; browser negotiates directly with the media server — no proxying or transcoding |
| Command overview: attention, investigations, estate, health, map | DEMONSTRATED | landing screen |
| System diagnostics across seven subsystems | DEMONSTRATED | `/system/health`, UNKNOWN never shown as healthy |
| AI provider health without exposing secrets | DEMONSTRATED | configured/not, location, role |
| Job and memory admission control | IMPLEMENTED, TESTED | four classes, 16 tests |
| Capability screen covering unlocated cameras | DEMONSTRATED | capability is a property of the camera, not its position |
| Documented HTTP API | DEMONSTRATED | **45 routes verified against the live store** |

---

### The bandwidth measurement, and how it was nearly overstated

Video packets are demuxed off the wire — not decoded, and not bitrate multiplied
by time — so the figure measures the link rather than this host. Observation size
is taken from **400 real records carrying full provenance**, because a stripped
example would flatter the result.

The event side is measured at the **busiest 60-second window**, not averaged
across the store. Averaging divides by the idle hours between capture runs and
produced **1,421x** — an order of magnitude of flattery, in exactly the quantity
being measured. Provisioning a link is decided by the busiest minute, so that is
what is reported: **19x**. Both sides move with scene activity, so this is one
point on this estate at this hour, not a constant.

---

## What is not claimed

- **Learned cross-camera transitions on the live grid.** Zero. The graph's 112
  links are geographic seeds, labelled unproven, and the home screen says so.
- **A general bandwidth saving.** 19x was measured on three cameras at one hour
  of one night. A busy daylight junction produces more events *and* more video.
- **Appearance as identity.** Measured at 0.831 balanced accuracy with
  overlapping distributions; it ranks candidates and does not confirm them, and
  no route leg rests on one.
- **ANPR across the estate.** Two marks read from the live grid. Most cameras
  are graded UNSUITABLE for plates, with the measurement that shows why.
