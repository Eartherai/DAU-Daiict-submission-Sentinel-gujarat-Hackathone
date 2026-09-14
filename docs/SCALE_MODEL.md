# Scale model

**MEASURED at 6 cameras. DESIGNED for 80,000.** Those two statements are kept
apart everywhere in this project, including here.

---

## The arithmetic that shapes everything

Centralising video is not expensive — it is impossible.

| | Per camera | × 80,000 |
|---|---:|---:|
| H.264, 720p, 15 fps, conservative | 2 Mbps | **160 Gbps** sustained |
| H.265, 720p, 15 fps, optimistic | 1 Mbps | **80 Gbps** sustained |
| 30-day retention at 2 Mbps | 648 GB | **52 PB** |

No network Gujarat has carries 160 Gbps of continuous ingress, and no budget in
this challenge makes 52 PB of hot storage appear. This is why Model 4 was
rejected — arithmetic, not preference.

**Metadata, by contrast, is small.** One observation is roughly 400 bytes of
structured fields. At a generous 20 vehicles per camera-minute across 80,000
cameras:

| | |
|---|---:|
| Observations per day | 2.3 billion |
| Raw metadata per day | ~920 GB |
| **With T0 gating** (most cameras are quiet most of the time) | **~90–180 GB/day** |

That is an ordinary database problem. Video is not.

---

## Layout

```
80,000 cameras
   │
   ├── ~33 district nodes            each: 2,000–3,000 cameras
   │      ingest · analytics · local store · durable queue
   │      local watchlist · local alerts · local evidence
   │      — continues with the uplink down —
   │
   └── central                       aggregation, cross-district search,
          PostgreSQL + PostGIS + pgvector, evidence chain, audit
```

Districts are the unit because they match how the estate is actually
administered and how connectivity actually fails. A node's failure removes one
district's *reporting*, never its detection.

---

## What each tier must sustain

**Per district node — 2,500 cameras:**

| | Requirement | Basis |
|---|---|---|
| Decode | 2,500 streams | Not all at full rate: T0 gating samples quiet cameras at ~1 fps |
| Analytics | ~250 concurrent at T1+ | ~10% of cameras active at once, measured against no real estate |
| Metadata out | ~3–6 GB/day | 400 B × observations |
| Local storage | 30 days of metadata + sealed evidence | Video stays where it already is |

**Central:**

| | Requirement |
|---|---|
| Ingest | ~2.3 B rows/day worst case, ~10× less with T0 gating |
| Query | Plate lookup on an indexed column; district-scoped windows on a composite index |
| Storage | Partition by month; observations are append-only |

All **MODELLED**. None measured.

---

## What is actually measured

| | Value | Where |
|---|---|---|
| Cameras ingested concurrently | **50** | `make loadtest` |
| Frames decoded, decoder errors | 52,637 · **0** | `var/reports/camera_load.json` |
| Cameras failed mid-run and recovered | 6 | `make loadtest` |
| Analytics throughput, one process | **11.4 frames/s (~11 cameras at 1 fps)** | `make loadtest` |
| Peak RSS, 50 decoders in one process | 4.9 GB | `make loadtest` |
| Cameras ingested in the demonstration | 6 | `make demo` |
| Observations | 140 over 240 s | `var/logs/demo_seed.log` |
| API p50 across 18 endpoints | 1.7 – 9.6 ms | `var/reports/api_latency.json` |
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
   deployment store and the repository already speaks to both, but the migration
   is untested at scale.
4. **Exact vector scan is linear.** Sub-millisecond at 10⁴–10⁵ observations and
   *more accurate* than an ANN index at that size. pgvector sits behind the same
   interface for when it is not.
5. **Analytics is CPU-bound, and now measured.** One process sustains 11.4
   frames/s — about 11 cameras at 1 fps. Ingest held at 50 cameras with zero
   decoder errors, so the limit is analytics, not decode. At that rate a
   2,500-camera district node needs ~220 CPU process-equivalents, which is the
   argument for GPU inference at that tier. The runtime profiles
   (DEV_CPU / CLOUD_GPU / TARGET_GPU) and the `InferenceBackend` abstraction
   exist so that is a configuration choice rather than a rewrite.
6. **Memory before CPU in a single process.** 4.9 GB for 50 concurrent decoders,
   ~98 MB per camera at these resolutions. A single-process deployment runs out
   of memory before it runs out of cores.

---

## Rules for quoting scale

Written down because it is the easiest place to lose credibility with a judge:

- **Never** say "tested at 80,000". Say "designed for 80,000, measured at six".
- **Never** quote a modelled figure as a benchmark.
- **Always** quote the row count and the host beside a latency.
- When asked how it scales, give the architecture and then the measurement —
  in that order, and say which is which.
