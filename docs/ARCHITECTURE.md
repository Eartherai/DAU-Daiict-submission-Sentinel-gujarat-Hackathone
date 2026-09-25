# Architecture

**Status:** implemented. Every component named here exists in `src/saakshya/`
and is covered by tests. Where something is designed but not built, it says so.

---

## The problem this shape answers

Gujarat's camera estate is not one system. It is tens of thousands of cameras
installed by Home, Health, GSRTC, Panchayat and Municipal bodies, over two
decades, for local supervision — a gate, a ward, a bus stand. Most were never
installed to read a registration number, and nobody has a complete list of which
ones can.

Two consequences drive every decision below.

**Video cannot move.** Centralising 80,000 streams is arithmetically impossible
on any network Gujarat has; the calculation is in
`docs/FINAL_ARCHITECTURE_DECISION.md`. So analytics run where the video already
is, and only metadata travels.

**Capability is unknown and heterogeneous.** A system that assumes uniform
capability will silently return nothing from half the estate and never say why.
So capability is measured per camera, and "we do not know" is a first-class
answer.

---

## Shape

Submitted architecture: **hybrid of Models 1 + 2 + 3**. Model 1 is the registry
and GIS spine. Model 2 is unified viewing as ingest stills. Model 3 is the
observation metadata bus across heterogeneous sources. Model 4 (central VMS
recording) is rejected on arithmetic, not left unfinished.

```
                       ┌─────────────────────────────────────────┐
   RTSP / HLS  ───────►│  INGEST          ingest/stream.py       │
   heterogeneous       │  PyAV · PTS-driven · one capture,       │
   codecs, fps         │  fan-out · GOP warm-up suppression      │
                       └──────────────────┬──────────────────────┘
                                          │ Frame(pts_s, t_norm, image)
                       ┌──────────────────▼──────────────────────┐
                       │  ANALYTICS       analytics/             │
                       │  motion T0 → track → ANPR T1/T2 →       │
                       │  attributes → quality → fusion          │
                       └──────────────────┬──────────────────────┘
                                          │ VehicleObservation
             ┌────────────────────────────▼────────────────────────────┐
             │  EDGE            edge/                                   │
             │  local store · durable queue · local watchlist · alerts  │
             │  — continues with the uplink down —                      │
             └────────────────────────────┬────────────────────────────┘
                                          │ replay, idempotent by dedup_key
                       ┌──────────────────▼──────────────────────┐
                       │  STORE           store/                 │
                       │  21 tables · SQLite ⇄ PostgreSQL+PostGIS│
                       └──────────────────┬──────────────────────┘
        ┌──────────────┬──────────────────┼───────────────┬────────────────┐
        ▼              ▼                  ▼               ▼                ▼
  intelligence/   capability/        watchlist/      evidence/       investigation/
  graph, search,  measured grades    VOI, alerts     hash chain,     the one facade
  trajectory      per time band                      s.63 draft      every caller uses
        └──────────────┴──────────────────┼───────────────┴────────────────┘
                                          ▼
                    ┌─────────────────────────────────────────┐
                    │  API  api/ · 83 operations · 4 gates    │
                    │  ui/  investigation workspace           │
                    │  copilot/ · read-only tools             │
                    └─────────────────────────────────────────┘
```

---

## Layers

### Ingest — `ingest/`

PyAV rather than `cv2.VideoCapture`, for one reason that turned out to matter
more than any other: **it is the only option that exposes real `pts` and
`time_base`.** Everything downstream orders by presentation timestamp. Nothing
orders by wall clock or frame count, because on a heterogeneous estate both lie.

- One capture per camera, fanned out to subscribers. A second connection to the
  same camera is a second load on a device that may barely manage one.
- Reconnect with exponential backoff and jitter, 2 s → 30 s.
- **Dual-signal discontinuity detection.** PTS regression alone is not enough:
  measurement showed a looping publisher advancing PTS across the loop (77 s of
  PTS on a 60 s clip, zero regressions). A block-grid scene-cut detector
  discriminates a vehicle crossing (0.08 of blocks changed) from a genuine cut
  (1.00).
- GOP-replay warm-up frames are suppressed and counted, not silently dropped.

### Analytics — `analytics/`

Four tiers, selected per camera from measured capability and current load:
**T0** motion presence · **T1** vehicle detection and tracking · **T2** plate
and attributes · **T3** forensic re-processing.

- ByteTrack, reimplemented rather than vendored: the upstream package is stale
  and is neither PTS-aware nor segment-aware, and both matter here.
- Velocity from **PTS deltas**, never frame counts.
- Motion differencing is **per colour channel**. Luma-only was measurably blind
  to a red car on grey tarmac (luma 58.8 vs 65.3).
- Plate and body detections are **fused** so the tracker sees one detection per
  physical vehicle, and attributes are read from the frame where the vehicle is
  largest and unclipped — not the last frame, which is systematically the worst.
- **Abstention is a first-class outcome.** Below a lit-fraction or
  colour-confidence floor, the answer is "no colour", not a guess.

### Store — `store/`

See `docs/DATA_MODEL.md`. The load-bearing constraint is
`observations.dedup_key UNIQUE`, which is what makes offline replay safe.

### Intelligence — `intelligence/`

**Graph-first hybrid retrieval**, and the ordering is the architecture:

```
structured prune  →  graph prune  →  candidate scoring  →  decomposed rerank
(indexed, exact)     (physics)        (weighted terms)      (explained)
```

Appearance ranks last because it was **measured and found unfit to lead**.
DINOv2 scored a decoy at 0.941 against the target while scoring the target
against itself at 0.412 — a margin of **−0.541**; illumination normalisation
made it worse. Recorded `REJECTED` in the model registry with the evidence.
Structure and physics prune before the fragile signal ranks anything.

The **Camera Link Model** learns travel-time distributions between cameras from
observed traversals. An edge is `trusted` only at ≥3 samples; below that it is a
prior, not evidence.

**Trajectory** returns ranked hypotheses with typed legs — `OBSERVED`,
`UNOBSERVED`, `COVERAGE_GAP`, `CONTRADICTION` — so absence of evidence stays
distinct from evidence of absence. Contradictions remain in the output with
their alternatives (OCR error, cloned mark, clock drift, mis-association) and
cap the score. The system never accuses.

### Capability — `capability/`

Three independent grades per camera per time band: **ANPR**, **appearance**,
**presence**. Independent because they fail independently, and the combination
"UNSUITABLE for plates, GOOD for presence" is genuinely useful — it places a
vehicle in a corridor without pretending to identify it.

Insufficient evidence is **UNKNOWN, never UNSUITABLE**. A camera that has
observed nothing may be pointed at a quiet compound.

### Edge — `edge/`

Loss of the uplink degrades reporting, never detection. Local processing, local
watchlist, local alerts, local evidence; a durable queue that acknowledges
rather than deletes, so a lost acknowledgement replays instead of losing data.

Watchlist bundles **fail closed** on integrity, issuer or version.

### Investigation — `investigation/`

One facade. The HTTP API, the copilot, the tests and the offline node all call
`InvestigationService`. That is what makes "the assistant cannot do anything you
cannot, and cannot skip an authorisation check" true by construction.

### API and UI — `api/`, `ui/`

Four authorisation gates (`docs/SECURITY.md`), 83 operations on 80 paths, OpenAPI generated
from the routes. The workspace is vanilla ES modules with a hand-written canvas
map — **no third-party asset of any kind**, which is what lets it run on a
network with no internet route and makes a strict CSP enforceable.

### Copilot — `copilot/`

Sixteen read-only tools over the same facade (search, trajectory, watchlist,
evidence, estate, timebase, `refuse_imagery`). Structural safety (no tool
mutates), injection detection on camera-derived text, and mechanical grounding
verification of every factual token. **The mandatory chain does not involve it**
— a test asserts no language-model library is even imported during the chain.
Gemini, when configured, coordinates named specialists over those tools; it
does not detect, OCR, or enhance a government still.

---

## What is designed but not built

- **NATS JetStream** as the event bus between edge and centre. The queue and
  replay semantics are implemented and tested; the transport is currently HTTP
  and in-process.
- **pgvector** for the appearance index. PostgreSQL 18 + PostGIS 3.6 is built
  and exercised (the government store copied and served, `tests/postgres/`);
  what is not built is a district-scale PostgreSQL deployment with
  replication and failover.
- **Retention enforcement.** `retention_days` is in the registry; no job acts on it.
- **PKI.** Evidence and watchlist integrity are content hashes, and every
  surface that reports them says so.
