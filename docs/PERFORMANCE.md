# Performance

Every number here is **MEASURED** on the machine and dataset it names. Nothing
in this document is extrapolated, and where a figure is a design target rather
than a measurement it says `MODELLED` and is kept in its own section.

Regenerate with `make perf`, `make queryplan`, `make loadtest`.

---

## Method

`tools/perf/api_latency.py` drives the real application in-process through
FastAPI's test client. That boundary is deliberate: it **excludes** network
latency, which belongs to the deployment, and **includes** routing,
authentication, the four authorisation gates, the service layer and the
database, which belong to us.

Nearest-rank percentiles over the retained window. No interpolation — an
interpolated p99 reports a latency that was never observed.

One warm-up call per endpoint is discarded: the first call pays for lazy imports
and connection setup, and reporting that as p99 would be misleading.

---

## API latency

Measured on the demonstration store. The scale line is part of the result — a
latency figure without the row count behind it is not a measurement.

**Host:** Apple Silicon, macOS 15.6, Python 3.12, SQLite (WAL).
**Scale:** 6 cameras · 121 observations · 3 evidence records · SQLite.

Latest run: `var/reports/api_latency.json`. Representative figures:

| Endpoint | p50 | p95 | p99 |
|---|---:|---:|---:|
| `GET /overview` | 2.9 ms | 6.4 ms | 18.9 ms |
| `GET /search?plate=` | 3.5 ms | 19.3 ms | 26.5 ms |
| `GET /search` (attributes) | 3.3 ms | 4.4 ms | 5.6 ms |
| `GET /trajectory/{plate}` | 3.8 ms | 6.1 ms | 9.7 ms |
| `GET /gis/cameras` | 2.8 ms | 5.2 ms | 6.3 ms |
| `GET /gis/coverage` | 3.3 ms | 4.1 ms | 5.4 ms |
| `GET /cameras/{id}/next` | 1.7 ms | 1.9 ms | 2.3 ms |
| `GET /audit?limit=200` | 9.6 ms | 12.8 ms | 26.5 ms |
| `GET /evidence/chain/verify` | 3.3 ms | 3.8 ms | 6.4 ms |

**This is a small dataset**, and that is the honest caveat: these numbers
establish that no endpoint has an accidental O(n²) or an N+1 at this scale. They
do **not** establish behaviour at statewide volume. The next section is what
protects that.

### Slowest paths, and why

1. **`/audit`** — the only endpoint that reads a table which grows without
   bound and is never pruned. It is also the one whose latency matters least.
2. **`/search?plate=`** — the p95 outlier is first-touch of the plate index;
   the p50 is the steady state.
3. **`/gis/coverage`** — nearest-neighbour is O(n²) *within the viewport*. The
   viewport bounds it today; a k-d tree is the obvious change if a single
   viewport ever returns tens of thousands of cameras. Flagged, not fixed,
   because fixing it now would be optimising against an unmeasured load.

---

## Query plans

`make queryplan` runs `EXPLAIN QUERY PLAN` over the ten hot queries and writes
`var/reports/query_plans.json`. Every index in the schema traces to a plan here;
an index that never appears is one that should be dropped.

**10 of 10 hot queries use an index.**

| Query | Index |
|---|---|
| Plate search, time-bounded | `ix_obs_plate_time` |
| Camera timeline | `ix_obs_camera_time` |
| District-scoped window (the access-control path) | `ix_obs_district_time` |
| Trajectory candidate fetch | `ix_obs_plate_time` |
| Camera graph edges | `ix_trans_from` |
| Watchlist lookup (hottest query in ingest) | `ix_watchlist_plate` |
| Open alerts, newest first | `ix_alerts_status_time` |
| Camera viewport (bbox) | `ix_cameras_geo` |
| Audit trail for a case | `ix_audit_case` |
| Edge queue drain | `uq_edge_seq` |

`ix_audit_case` exists because this harness found the case-file export doing a
full scan of the audit log. That is the point of running it: the index was added
on evidence, and the before/after is in the report.

**PostgreSQL note.** These are SQLite plans. On the deployment store the
equivalent check is `EXPLAIN (ANALYZE, BUFFERS)`, and the plans will differ —
particularly the bbox query, where PostGIS `GIST` replaces the composite B-tree.
Claiming these plans hold on PostgreSQL would be unfounded.

---

## Concurrent camera simulation — MEASURED

`make loadtest` republishes the corpus under 50 distinct RTSP paths and runs the
real ingest and analytics path against them, failing six mid-run to measure
recovery. Mixed codecs (h264 and h265), mixed frame rates (8–15 fps), mixed
resolutions (640×480 to 1920×1080), because a single-codec load test would prove
nothing about this estate.

**Host:** Apple Silicon, 10 cores, macOS 15.6, Python 3.12.
**Run:** 50 cameras · 90 s · analytics sampled at 1 fps per camera · 6 failed
mid-run. Full report: `var/reports/camera_load.json`.

| | Measured |
|---|---:|
| Paths publishing | 50 / 50 |
| Frames decoded | 52,637 |
| **Decoder errors** | **0** |
| PTS regressions / forward jumps | 0 / 0 |
| Warm-up frames suppressed | 193 |
| Cameras failed mid-run → streaming at end | 6 → 44 / 50 |
| Per-camera measured fps | min 8.0 · median 15.0 · max 15.0 |
| Observations written | 150 |
| Peak RSS (one process) | 4,903 MB |

Per-camera frame rate matching the declared rate across three different declared
rates is the result worth noting: the PTS-driven path is not quietly resampling.

### The bottleneck this found

**One analytics process sustained 11.4 frames/s — about 11 cameras at 1 fps.**

The ingest side held comfortably: 52,637 frames decoded with zero decoder errors
and zero PTS anomalies. The consumer took only 1,510 of them; the fan-out queue
**counted 50,775 dropped frames** rather than silently losing them, which is why
the number is quotable at all.

This is a genuine finding and it is reported rather than tuned away. It is also
the number the architecture already assumed: a district node runs many analytics
processes against a shared ingest layer, and the runtime profiles
(`DEV_CPU` / `CLOUD_GPU` / `TARGET_GPU`) exist precisely so the per-process
figure is a deployment variable rather than a fixed property.

At 11 cameras per CPU process, a 2,500-camera district node needs roughly 220
process-equivalents on CPU — which is the argument for GPU inference at that
tier, not an argument that the design is wrong.

**Also measured:** 4.9 GB peak RSS for 50 concurrent decoders in one process
(~98 MB per camera at these resolutions). Memory, not CPU, is what would limit a
single-process deployment first.

---

## The cost of a working detector

Enabling the vehicle detector — the CR-006 P0, where it had defaulted to off and
had never once run — roughly **tripled per-frame pipeline cost**. Measured on
the suites, which are the most repeatable workload available:

| Suite | Detector off | Detector on |
|---|---:|---:|
| Integration (6 cameras × 90 s) | ~93 s | 267 s |
| ML regression | 221 s | 625 s |
| End-to-end, 240 s corpus | 350 s | **>1,500 s** |
| End-to-end, bounded to 120 s | — | **350 s** |

That cost is not optional: without the detector the T1 tier produces nothing on
footage where plates are unreadable, which is most of the real estate at night.

What *is* optional is making every suite pay it over the full corpus. The
end-to-end window is now bounded to the 120 seconds that contain the scripted
scenario and enough repeated transitions for the graph to trust an edge; the
integration suite is bounded to 90. **A gate that takes half an hour is a gate
people stop running.**

The same measurement drove the live-ingest design: 16 of 30 live cameras decode
keyframes only, which is what made 30 concurrent cameras fit on a laptop.

---

## Resource protection

Measured behaviour under refusal, not just documented policy:

| Limit | Value | At the limit |
|---|---|---|
| Concurrent searches | 8 | 5 s wait, then `503 BUSY` — refused, not queued |
| Concurrent exports | 2 | `503 BUSY` |
| Results per query | 2000 | Clamped |
| Time span | 400 days | `400 RANGE_TOO_LARGE`, before the database |
| Map features | 1500 | Server-side clustering |
| Edge queue depth | 250,000 | `QueueFull` raised — never a silent drop |
| Latency samples retained | 4096/metric | Bounded ring; ~32 KB |

A request that waits five minutes on a semaphore is indistinguishable from a
hung system to the person waiting. So the wait is bounded and the refusal says
what to do next.

---

## MODELLED — not measured

Kept separate on purpose. **None of this may be quoted as a test result.**

- **80,000 cameras is an architectural target**, not a tested figure. The
  metadata-first design means the central store carries observations, not video;
  the arithmetic behind that is in `docs/FINAL_ARCHITECTURE_DECISION.md`.
- **PostgreSQL + PostGIS + pgvector** is the deployment store. SQLite is the
  development store because PostgreSQL cannot run on this machine. The
  repository speaks one interface to both, but the migration is untested at
  scale.
- **Horizontal scale** is by district-level edge nodes with central
  aggregation. The queue and replay path are implemented and tested with two
  nodes; a hundred are modelled.

---

## Outstanding

Stated rather than omitted:

- 2-hour chaos soak (`make chaos-long`) — not yet run to completion.
- Retention enforcement — `retention_days` exists in the registry; no job
  enforces it.
- Memory profile under sustained ingest beyond the load-test window.


---

## Appearance re-identification on the live grid — MEASURED

Vehicle embeddings were dropped from the pipeline on a measurement taken against
the **synthetic** corpus, where a DINOv2 embedding did not separate vehicles.
Real government footage is a different question, and it decides whether
cross-camera re-identification is possible on this grid at all, so it was
re-measured directly.

**Method.** cam01 (Chimanbhai Bridge, Ahmedabad), 60 sampled frames from the
live RTSP feed. Vehicles detected with RT-DETRv2 at threshold 0.5, tracks formed
by IoU association at 0.35 — deliberately outside our own tracker, so the result
depends on as little of our code as possible. 68 tracks formed, 17 with three or
more crops. Crops embedded with `facebook/dinov2-base`, CLS token, L2-normalised,
compared by cosine similarity.

| | pairs | mean | tail |
|---|---|---|---|
| Same vehicle | 194 | 0.830 | p05 **0.640** |
| Different vehicles | 3,634 | 0.576 | p95 **0.791** |

**Separation: −0.152.** The distributions overlap: the 5th percentile of true
pairs sits *below* the 95th percentile of false ones. The best achievable
balanced accuracy is **0.831 at threshold 0.74**.

**What this licenses, and what it does not.** 83% balanced accuracy is well
above chance and would be a useful signal for *ranking* cross-camera candidates
for an investigator to review. It is nowhere near sufficient to assert that two
sightings are the same vehicle. Roughly one pair in six is misclassified at the
best threshold, and on a corridor with a hundred vehicles that is a route built
from confident mistakes.

The embedding is therefore **not stored as an identity signal**, and no route
leg rests on one. This is the same standard applied to plate reads, which
require agreeing votes across frames before they are published, and to the
timebase gate, which refuses a route rather than drawing a plausible line.

Reproduce: the measurement script and its output are recorded with this entry;
re-running it on a different camera or at a different point in the replay loop
will give different numbers, and the conclusion should be re-derived rather than
quoted from here.
