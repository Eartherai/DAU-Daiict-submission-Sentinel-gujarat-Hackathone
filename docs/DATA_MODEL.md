# Data model

18 tables, one schema, two dialects. SQLite is the development store because
PostgreSQL cannot run on this machine; PostgreSQL + PostGIS + pgvector is the
deployment store. Everything above `saakshya.store` talks to the repository
interface and never to a dialect.

Three decisions run through the whole schema and are worth stating before the
tables:

**Times are epoch microseconds (INTEGER), not strings.** Ordering and range
scans are the hot path, and dialect-dependent timestamp parsing is a reliable
source of subtle, late-discovered bugs across SQLite and PostgreSQL.

**`observations.dedup_key` is UNIQUE.** Idempotent ingestion is not optional: an
offline district replays its queue on reconnect, and at-least-once delivery must
not duplicate observations. This one constraint is what makes the whole offline
story safe.

**District and department are denormalised onto every observation** at write
time. District scoping is an access-control path, not an analytics convenience,
so it must hit an index rather than a join.

---

## The spine — Model 1

### `cameras`
Identity, geometry, transport (RTSP/HLS/WHEP), declared codec and resolution,
storage and retention, compliance status, analytics tier.

`tier` defaults to `UNASSIGNED` and is **never** set from a catalogue. A
catalogue records what a camera *is*; it cannot know what a camera can *do*.

### `camera_health`
Measured, not declared: connects, reconnects, frames, decoder errors, PTS
regressions, PTS forward jumps, segment breaks, scene cuts, warm-up frames
suppressed, measured FPS, clock drift, last error.

`measured_fps` beside `cameras.declared_fps` is deliberate. The gap between them
is one of the more useful diagnostics on a heterogeneous estate.

### `camera_capability`
Primary key `(camera_id, time_band)` — capability is not one number. Carries
three independent grades (`anpr_grade`, `vehicle_reid_grade`, `presence_grade`),
the statistics behind them, sample counts, and an `evidence` JSON blob recording
the policy version and thresholds applied.

A grade without its evidence is an opinion, so the evidence is stored with it.

---

## The atom

### `observations`
One vehicle, seen once, by one camera, at one time. Everything — search,
trajectory, watchlist, evidence — is a function over this table.

Notable columns:

| Column | Why it exists |
|---|---|
| `pts_s` | Presentation timestamp. Ordering **always** uses PTS, never wall clock or frame count |
| `t_norm_us` | Normalised timeline, derived from PTS |
| `t_ingest_us` | Arrival time. Diagnostics only — never used for ordering |
| `plate` / `plate_raw` | Canonical form, and exactly what OCR returned. Both, always |
| `plate_votes` | Agreeing frames across the track |
| `colour_confidence` | Nullable: abstention is recorded, not guessed |
| `sharpness`, `luminance` | Normalised 0..1 quality factors |
| `mean_luma` | Brightness, 0..1. Separate from `luminance`, which is exposure *quality* — conflating them mislabelled every illumination band (CR-004) |
| `source_grade` | The camera's grade at the time of observation |
| `model_versions` | JSON. Which model produced this, so a result stays attributable after an upgrade |
| `embedding` | BLOB + dim + model name. Nullable and usually null |

Vectors are stored as bytes rather than a native vector type. At this scale an
exact numpy scan is sub-millisecond and *more* accurate than an ANN index; the
pgvector path exists behind the same interface.

### `plate_reads`
Every individual OCR attempt, including rejected ones with `reject_reason`.
Separate from `observations` because one observation is a vote over many reads,
and the losing reads are diagnostic evidence when a plate is disputed.

---

## Movement

### `camera_transitions` / `transition_samples`
The Camera Link Model. Samples are individual observed traversals; transitions
are the learned distribution (p05/p50/p95, mean, std, support count,
confidence, source).

`source` distinguishes `observed` from `gis_seed`. A seeded edge is a
plausibility prior; an observed one is evidence. An edge is `trusted` only at
≥3 samples.

---

## Watch and act

### `watchlist`
Versioned and superseding, never mutated: `version`, `status`, `valid_from_us`,
`valid_until_us`, `revoked_by`, `revoked_reason`. An alert raised last week must
stay explicable in terms of what the list said last week.

`authority` and `reason` are `NOT NULL`. A watchlist entry that cannot say who
authorised it and why is not an entry.

`source_system` defaults to `REPRESENTATIVE` and travels into every alert.

### `alerts`
One row per vehicle-per-watchlist-entry, escalating rather than duplicating.
`match_reason` holds the decomposition as JSON, so an alert can always explain
itself.

### `evidence`
Hash-chained: `prev_hash`, `entry_hash`, digests of frame and clip, pipeline and
model versions, capture method, device. `bsa_s63_status` defaults to
`DRAFT_PENDING_SIGNATURE`.

### `audit_log`
Hash-chained, append-only. Actor, role, action, **case id, purpose**,
jurisdiction, target, result count. The case and purpose columns are what make
the log answer an oversight question rather than just a debugging one.

---

## Access control

### `users`, `api_tokens`
`token_sha256` only — no plaintext token exists after mint. `districts` is a
JSON array; empty means statewide, and only statewide-eligible roles may hold it.

### `cases`, `case_items`, `case_notes`
`cases.purpose` is `NOT NULL`. `case_items.payload` holds a JSON **snapshot**,
so an attached finding does not silently change under a note that refers to it.

---

## Offline

### `edge_queue`
`event_id`, `node_id`, `sequence`, `dedup_key`, payload, state, attempts.
`UNIQUE (node_id, sequence)` gives a total order per node independent of any
clock.

Rows are **acknowledged, not deleted**, on send. A lost acknowledgement causes a
harmless replay rather than a silent loss — the correct way round.

### `edge_nodes`
Last sync, last acknowledged sequence, installed watchlist version, state.

---

## Indexes

17 indexes. Every one traces to a query plan in `var/reports/query_plans.json`;
see `docs/PERFORMANCE.md`. Indexes were added on evidence from `make queryplan`,
not on principle — `ix_audit_case` exists precisely because that harness caught
the case-file export doing a full scan.
