# Scale model

**MEASURED:** government registry snapshot (`docs/MEASURED_RESULTS.md`),
local stream load (`var/reports/camera_load.json`), and synthetic registry/GIS
load (`reports/SCALE_80K_LOAD_TEST.md`). **DESIGNED:** statewide live media and
inference. These are separate workloads, not interchangeable camera counts.

The statewide target architecture and its full capacity model are in
`docs/STATEWIDE_ARCHITECTURE.md` (HLD §21), produced by
`tools/sizing/capacity_model.py`. This file keeps the arithmetic that declines
central recording and the earlier gated metadata model, and states which one
sizes the design.

---

## The arithmetic that shapes everything

Statewide central recording is declined on the following **MODELLED**
assumptions; selected-camera Model 4 analytics remains part of the hybrid.

| Assumption | Per camera | × 80,000 |
|---|---:|---:|
| H.264, 720p, 15 fps | 2 Mbps | **160 Gbps** sustained |
| H.265 alternative | 1 Mbps | **80 Gbps** sustained |
| 30-day retention at 2 Mbps | 648 GB | **51.84 PB** |

These are sizing assumptions in this file, not a measurement of the state's
network or procurement budget.

**Metadata payloads.** ~400 B is a **MODELLED optimised payload**, not what the
build currently serialises. `var/reports/bandwidth.json` **MEASURED 1,331.7 B**
per serialised observation. At an assumed 20 observations per camera-minute,
80,000 × 20 × 1,440 = 2,304,000,000 observations/day. Gating below assumes
10–20% of that activity; it is not measured against a statewide estate.
Decimal GB/TB are used throughout.

**Earlier gated model — kept for reference, no longer the sizing basis.**

| MODELLED volume | 400 B optimised payload | 1,331.7 B measured row basis |
|---|---:|---:|
| Statewide raw / day | 921.60 GB | 3,068.24 GB (3.068 TB) |
| Statewide gated / day | 92.16–184.32 GB | 306.82–613.65 GB |
| District of 2,500, raw / day | 28.80 GB | 95.88 GB |
| District gated / day | 2.88–5.76 GB | 9.59–19.18 GB |
| Statewide gated, 30 days, ×2 assumed index overhead | 5.53–11.06 TB | 18.41–36.82 TB |
| Statewide gated, 365 days, ×2 assumed index overhead | 67.28–134.55 TB | 223.98–447.96 TB |
| District gated, 30 days, ×2 assumed index overhead | 0.173–0.346 TB | 0.575–1.151 TB |
| District gated, 365 days, ×2 assumed index overhead | 2.10–4.20 TB | 7.00–14.00 TB |

The 19.3× video/metadata ratio in `bandwidth.json` used the measured row and
the event rate during that test window; it does not describe the 400 B model.

**Planning basis (supersedes the gated model for sizing).** The government
store measures 902.6 observations per active camera-hour (1,155,325
observations over 1,280 camera-hours with at least one; VERIFIED read-only on
`var/live.db`), and its busiest camera averages 2,529 per active hour. The
design sizes on a pessimistic **3,000 observations per camera-hour** (ASSUMED,
above that camera) on the measured 1,331.7 B row, and ships metadata in
compressed batches. The separate sample in `reports/measure_compression.json`
averages 1,230.6 B and compresses 8.0× to 154.0 B in batches of 100. Using
154.0 B against the 1,331.7 B raw base implies an effective 8.65×; transferring
that compressed size is ASSUMED, not measured on the larger row. At 8.0× on
1,331.7 B, the result would instead be 166.5 B, about 89 Mbps statewide bulk
and 4.04 Mbps/cell (4.95× WAN headroom); see HLD §20.4. All MODELLED
(`reports/capacity_model.json`):

| MODELLED at 3,000 observations per camera-hour | Per full cell (2,500 cameras) | Statewide (80,000) |
|---|---:|---:|
| Observations/s | 2,083 | 66,667 |
| Metadata off the cell, raw | 22.2 Mbps | 710 Mbps |
| Metadata off the cell, compressed, with plate and health lanes | 3.83 Mbps | 82 Mbps compressed bulk |
| Hot store, 30 days, ×2 assumed index overhead | 14.4 TB (4.3 TB at the measured mean rate) | — |
| Compressed lake, per year | — | 324 TB (97.4 TB at the measured mean rate) |

The earlier gated model put 30 days of a district's metadata at 0.575–1.151 TB
(the "~1.2 TB per district" HLD §20.5 used to provision). At the measured rate
and row that was 3–12× too small; the cell now provisions 32 TB of NVMe per
copy. Replicas, queue copies, audit and evidence need separate allowance.

---

## Layout

```
80,000 cameras
   │
   ├── site edge boxes               only where a site's uplink is too thin
   │
   ├── 40 district cells             each: ≤ 2,500 cameras or ≤ 4,000 obs/s
   │      ingest · analytics · local store · durable queue
   │      local watchlist · local alerts · local evidence
   │      — continues with the uplink down —
   │
   ├── 6 regions                     viewing fan-out, backups, forensic GPUs
   │
   └── state + DR                    registry and GIS, plate index, lake,
          cross-district search, evidence chain, audit
```

Cells follow districts because districts match how the estate is actually
administered and how connectivity actually fails; a large district splits
into two cells. A cell's failure removes one district's *reporting*, never
its detection.

---

## What each tier must sustain

**Per full district cell — 2,500 cameras:**

| | Requirement | Basis |
|---|---|---|
| Decode | 2,500 streams, ~625 cores | 0.25 core per stream, ASSUMED from the 50-stream load run |
| Analytics | Every camera at 1 fps; ANPR-grade cameras (20%, ASSUMED) at 5 fps | Two agreeing frames confirm a plate; T0 gating would reduce this but is not counted |
| Metadata out | 3.83 Mbps compressed at 3,000 observations per camera-hour | MODELLED on the measured row and compression |
| Local storage | 30 days of metadata (14.4 TB) + sealed evidence | Video stays where it already is |

**State:**

| | Requirement |
|---|---|
| Ingest | 66,667 observations/s pessimistic, as compressed micro-batches to the lake; plates, alerts and health on the event bus |
| Query | Plate lookup on one shard keyed by plate; district-scoped windows on a composite index |
| Storage | Partition by day; observations are append-only |

All **MODELLED**. None measured.

---

## What is actually measured

| | Value | Where |
|---|---|---|
| Local streams initially / at end | **50 initially; 44 streaming / 6 down at end** | `var/reports/camera_load.json` |
| Frames decoded, decoder errors | 52,637 · **0** | `var/reports/camera_load.json` |
| Cameras failed mid-run, not recovered / open failures | 6 / 36 | `var/reports/camera_load.json` |
| Single-process local-load throughput | **11.4 frames/s** | `var/reports/camera_load.json`; size full pipeline on the historical 5.6 fps baseline in `reports/SCALE_80K_LOAD_TEST.md` |
| Peak RSS, 50 decoders in one process | 4.9 GB | `make loadtest` |
| Cameras ingested in the demonstration | 6 | `make demo` |
| Observations | 140 over 240 s | `var/logs/demo_seed.log` |
| API latency, DEMO store | p50 2.0–23.1 ms, p99 ≤44.7 ms | `var/reports/api_latency.json`; 6-camera, 140-observation demo store |
| Hot queries using an index | 10 of 10 | `var/reports/query_plans.json` |
| Offline replay | no duplicates, no loss | `tests/e2e/test_offline_mode.py` |

These are from a run actually performed on a 10-core Apple Silicon host. A figure
from another machine is not a result for this one.

---

## Where this breaks first

Named honestly, because knowing the next bottleneck is worth more than claiming
there isn't one.

1. **Coverage-gap computation is O(n²) within a viewport.** Bounded by the
   viewport today. A k-d tree is the fix; it is not written, because writing it
   now would be optimising against an unmeasured load.
2. **The audit log grows without bound and is never pruned.** It is also the
   table that must never lose a row. Partitioning is the answer; retention is a
   policy decision we do not get to make.
3. **SQLite has one writer.** Fine per node, wrong centrally. PostgreSQL is the
   deployment store and the repository already speaks to both, with the government-store migration measured in
   `var/reports/store_engines.json`. District-scale replication remains untested.
4. **Exact vector scan is linear.** Sub-millisecond at 10⁴–10⁵ observations and
   *more accurate* than an ANN index at that size. pgvector sits behind the same
   interface for when it is not.
5. **Deep inference concurrency is hardware-bound.** The historical full-pipeline
   baseline is ~5.6 fps (`reports/SCALE_80K_LOAD_TEST.md`); the 11.4 fps
   component run must not size the whole worker. A 2,500-camera district at
   1 Hz therefore needs ceil(2,500 / (5.6 × S)) inference units (**MODELLED**);
   with ANPR-grade cameras at 5 fps the statewide planning case is 2,652 GPUs at
   an ASSUMED S = 10 (HLD §17.6).
   S = 2.0 was measured on a laptop GPU (`var/reports/pipeline_device.json`),
   before the current recogniser; target accelerators must be benchmarked.
   Adaptive scheduling changes cadence, not camera selection. Current
   demonstration hardware limits simultaneous deep-inference concurrency.
   Analytics workers scale horizontally, so additional GPU nodes raise
   concurrent inference throughput without redesigning ingest, event,
   watchlist, GIS or investigation services.
6. **Memory before CPU in a single process.** 4.9 GB for 50 concurrent decoders,
   ~98 MB per camera at these resolutions. A single-process deployment runs out
   of memory before it runs out of cores.

---

## Rules for quoting scale

Written down because it is the easiest place to lose credibility with a judge:

- State the workload: synthetic registry/GIS rows, local decode streams, or
  selected government analytics. No statewide live-video test is claimed.
- **Never** quote a modelled figure as a benchmark.
- **Always** quote the row count and the host beside a latency.
- When asked how it scales, give the architecture and then the measurement —
  in that order, and say which is which.
