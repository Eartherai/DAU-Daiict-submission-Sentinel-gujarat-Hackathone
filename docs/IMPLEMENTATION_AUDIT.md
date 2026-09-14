# Implementation Audit

**Date:** 31 August 2026
**Auditor:** principal engineer
**Scope:** `/Users/earther/Desktop/Gujarat CCTV`

---

## 1. Headline finding — there was no repository

The audit brief assumed an existing codebase to inspect, refactor and selectively
retain. There was none.

```
/Users/earther/Desktop/Gujarat CCTV/
└── 17 PNG screenshots of the hackathon website   (16 unique, 1 duplicate pair)
```

- `git status` → *not a git repository*
- No source files of any language, no `package.json`, no `pyproject.toml`,
  no schema, no Dockerfile, no docs, no tests, no CI.

**Consequence:** sections of the brief covering "what works / partially works /
is broken / should be deleted / technical debt / dead code" have no subject.
There is no legacy to retain and nothing to delete. This is a greenfield build,
and the audit's real value is the *environment* assessment below, which did
change the plan.

## 2. The referenced dossier

The brief instructs: *"A Claude research/strategy dossier has been supplied in
this conversation as `Pasted markdown(8).md`. READ THE FILE FULLY."*

No such file exists on disk (searched `Desktop`, `Downloads`, `Documents`), and
no file by that name was attached to the conversation. The strategic content it
describes is the dossier produced in the immediately preceding turn of this same
conversation and published as an artifact; its substance is therefore already in
working context and is treated as the research baseline here.

Stating this rather than silently proceeding matters, because the brief also
instructs that dossier claims must be *verified, not inherited*. Several were,
and two were corrected — see §5.

## 3. Environment assessment — this materially changed the plan

| Tool | Status | Consequence |
|---|---|---|
| Python | **3.9.6 only** (Xcode system) | Too old for the target stack |
| `uv` | **0.11.30 present** | Bootstrap path; Python 3.12.13 already installed |
| git | 2.50.1 | Fine |
| make | GNU Make 3.81 | Fine |
| Docker | **absent**, daemon not running | No containers; no `docker compose` deployment on this machine |
| Homebrew | **absent** | Cannot install system packages |
| ffmpeg / ffprobe | **absent** | Needed for media + streaming |
| GStreamer | **absent** | DeepStream/GStreamer path unavailable locally |
| Node / npm | **absent** | No JS frontend build on this machine yet |
| PostgreSQL / psql | **absent** | Postgres+PostGIS+pgvector not runnable locally |
| Platform | macOS 26.6.2, arm64 | No NVIDIA GPU — no CUDA, no TensorRT, no DeepStream |

### Decisions forced by the environment

1. **Python 3.12 via `uv`**, not system Python. Done.
2. **ffmpeg via `imageio-ffmpeg`** (BSD-2 packaging of a static FFmpeg 7.1
   binary, GPL build with libx264/libx265). Avoids needing Homebrew. Verified
   working, including `drawtext`/`libfreetype` and both encoders.
3. **MediaMTX as a standalone binary**, not a container. v1.20.1 darwin/arm64
   pulled from the official release. Removes the Docker dependency entirely for
   the sandbox replica.
4. **No GPU on this machine.** All CV work must be CPU-viable for development,
   with the GPU path documented and configuration-selected rather than assumed.
   Any GPU throughput figure in our documents is therefore *modelled and
   labelled as such* until measured on real hardware — it must never be
   presented as measured.
5. **Datastore:** Postgres+PostGIS+pgvector is not installable here. The plan is
   a repository abstraction with SQLite for local development and Postgres for
   deployment, with the Postgres DDL maintained in-tree so the migration path is
   visible in the HLD rather than asserted. *Not yet implemented — see §6.*

## 4. What now exists (built during this session)

```
saakshya/
├── Makefile                         # install / media / sandbox / smoke / chaos / test
├── pyproject.toml                   # Python 3.12, pinned permissive deps
├── src/saakshya/
│   ├── common/{ids,clock}.py        # ULID-ish ids; PTS→normalised timeline, drift measurement
│   ├── events/schema.py             # CCTV-EVENT v1 (measured 883 B/event)
│   └── ingest/
│       ├── frame.py                 # the single internal Frame interface
│       ├── stream.py                # StreamWorker + StreamManager (the reliability layer)
│       └── discontinuity.py         # block-grid scene-cut detector
├── tools/
│   ├── sandbox/{scene,make_media,smoke}.py
│   └── chaos/harness.py
├── var/
│   ├── bin/mediamtx                 # v1.20.1 (MIT)
│   ├── media/*.mp4 + catalogue.json # 6-camera corpus, 23.9 MB
│   └── mediamtx.yml                 # generated grid config
└── tests/evaluation/ground_truth.json
```

### Verified working (measured, not asserted)

> **All figures below are MEASURED on the `LOCAL SYNTHETIC CORPUS`, on `DEV_CPU`
> (Apple Silicon, no GPU).** They are regression and comparison numbers. They are
> **not** real-world accuracy and must never be presented as such. No number here
> was obtained on the organiser's sandbox, and no GPU figure exists anywhere in
> this project — every GPU figure is MODELLED.

| Capability | Evidence |
|---|---|
| Grid replica serves 6 paths | `6/6 ready`, tracks `['H264','H265',…]` via MediaMTX API |
| Mixed codec decode in one process | H.264 **and** H.265 frames decoded concurrently |
| Mixed resolution | 640×480, 960×540, 1280×720, 1920×1080 simultaneously |
| Measured vs declared fps | measured fps computed from PTS deltas, reported separately |
| PTS monotonic within segment | 0 regressions across 1,285 frames, 6 cameras |
| Warm-up GOP burst suppressed | 12 frames flagged `warmup` across 6 connects (2 each) |
| Scene-cut detector discriminates | vehicle entering = 0.08 blocks changed (no fire); scene cut = 1.00 (fires) |
| Survives fault injection | 12 faults landed → 4 reconnects, 4 segment breaks, 2,708 frames, 0 crashes |
| Plate legibility gradient | C-033 = 0.288 vs 0.86–0.90 for the rest — the hard case is *measured* |

## 5. Dossier claims: verified, corrected, or still open

| Claim | Verdict |
|---|---|
| Sandbox is MediaMTX (ports 8554 / 8888 / 8889 + `/whep`) | **Consistent.** Those are MediaMTX defaults; replica built on that basis and behaves the same. Still circumstantial — we have no sandbox credentials to confirm directly. |
| GOP replay on connect makes arrival-time tracking compute impossible velocities | **Confirmed as a real risk and handled.** Warm-up burst observed and suppressed on every connect. |
| Loop point produces a scene cut | **Corrected.** Measured on the replica: a looping publisher advances PTS *monotonically* across the loop (77 s of PTS on a 60 s clip, **zero** regressions, zero pixel anomaly). PTS-based detection alone would have missed it. This drove building `discontinuity.py` as a second, independent signal. **This was the most valuable correction of the session.** |
| `CAP_PROP_FPS` unreliable → don't use OpenCV capture | **Acted on.** PyAV chosen over `cv2.VideoCapture` specifically because the latter cannot expose real PTS. |
| Ultralytics AGPL-3.0 / BoxMOT AGPL-3.0 | **Not yet re-verified in-tree.** No detector or tracker dependency added yet, so no contamination exists today. Must be re-checked at the moment of adding — see MASTER_BUILD_PLAN Phase 3. |
| Awiros `anpr-ocr` Apache-2.0, 98.42% Indian plates | **Publisher's figure, unverified by us.** Must never be quoted as our result. |

## 6. Immediate risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **No sandbox credentials.** We have never connected to the real grid; all robustness evidence is against our replica. | **High** | Register on the portal immediately (registration and submission share the 07 Sep deadline). Until then, treat replica results as *indicative*, never as sandbox results. |
| R2 | **No GPU available locally.** Detector/ANPR throughput cannot be measured on target hardware. | **High** | Keep all throughput claims modelled-and-labelled. Design for CPU-viable dev path. Do not put an unmeasured fps number in the PPT. |
| R3 | **No detection/ANPR/Re-ID implemented yet.** The mandatory test case is not yet satisfiable end to end. | **High** | Phases 3–4 are the critical path; everything else is subordinate until the plate→route→alert chain runs. |
| R4 | **No persistence layer.** Events are produced but not stored or queryable. | **High** | Phase 2 (registry store) then Phase 3 event sink. |
| R5 | Synthetic corpus may be *easier* than real feeds (clean geometry, rectangular vehicles, high-contrast plates). | Medium | Corpus is for contract and regression testing, not for accuracy claims. Accuracy is only ever reported on the government feed. |
| R6 | Media generation depends on a GPL FFmpeg build (libx264/libx265). | Low–Medium | Used as a *build-time tool and an external binary*, never linked into the product. Record in THIRD_PARTY_LICENSES.md. |
| R7 | MediaMTX config uses relative paths because the repo path contains a space. | Low | Fixed and documented; `var/bin/ffmpeg` symlink keeps it portable. |

## 7. Defects found and fixed during the session

| Defect | How found | Fix |
|---|---|---|
| `StreamWorker._stop` shadowed `threading.Thread._stop`, so **every `join()` raised `TypeError`** — i.e. every clean shutdown crashed. | Smoke test traceback | Renamed to `_stopping` |
| `drawbox` does not evaluate per-frame `x` expressions in this FFmpeg build — the first corpus rendered **no vehicles at all**, silently. | Inspecting rendered pixels rather than trusting exit code 0 | Replaced filter-graph animation with Python/numpy/PIL scene synthesis |
| MediaMTX `runOnInit` silently failed because the absolute ffmpeg path contains a space. | Paths registered but never became `ready` | Relative paths + `var/bin/ffmpeg` symlink |
| Chaos harness reported **PASS while injecting nothing** — wrong path encoding (`~1` vs `%2F`), wrong verb (POST vs PATCH), non-existent kick endpoint. | Reading the fault counters instead of the summary line | Corrected API usage; added `_verify_restart`; pass now *requires* faults to have landed |

The last one is worth calling out: our own tooling was producing exactly the kind
of false confidence the product is designed to eliminate. It is now impossible
for a chaos run to report success without evidence that faults actually occurred.

## 8. Recommendation

Proceed on the greenfield plan in `MASTER_BUILD_PLAN.md`. The ingest and
reliability layer — the highest-scoring, highest-risk component — is built and
measured. The critical path is now detection → ANPR → event persistence → query,
because until that chain runs the mandatory test case cannot be demonstrated at
all, and no amount of architecture quality substitutes for it.
