# Evaluation plan

Historical planning / measurement record. For the current submission use
[FINAL_SUBMISSION.md](FINAL_SUBMISSION.md). Current roles: government
`GJ11S7924` on cam06 is SINGLE-CAMERA evidence; synthetic `GJ18JX7786` on
C-014 then C-021 is a SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). Earlier rehearsal plate names,
screenshot counts, timings and dates below belong to their recorded run.
Current wall policy: CONTROL ROOM up to 30 direct WHEP sessions, 400 ms apart;
OPTIMIZED VIEW at most 12, 600 px prefetch, released after 15 s off screen
(`ui/app.js`). Old still-wall descriptions below are historical.


How this system is measured, and what each number is allowed to claim.

Vocabulary, used consistently and never interchangeably:

| Label | Meaning |
|---|---|
| **MEASURED** | Observed on a stated dataset and host. Reproducible with the named command |
| **MODELLED** | Derived by calculation from stated assumptions. Never quoted as a result |
| **SIMULATED** | Observed on synthetic data, which may not transfer |
| **DESIGNED** | Implemented but not yet exercised at the claimed scale |
| **UNTESTED** | Written, not run |

---

## 1. The corpus

`make media` renders six cameras, 240 seconds each, from a fixed seed. It is
**LOCAL SYNTHETIC CORPUS** and every result taken from it says so.

The camera mix deliberately mirrors the estate the organisers described — Home,
GSRTC, Panchayat, Municipal, Health — and includes one hard case (C-033: 640×480,
soft optics, low light, **measured plate legibility 0.27** against 0.80–0.88 for
the rest) and one decoy (a white car whose plate shares the target's prefix, on a
route the target never took).

Traffic is generated deterministically: corridor commuters that give the camera
graph repeated transitions to learn from, plus local traffic as the noise a
search must work through. The corpus was extended from 60 s to 240 s
specifically because capability grading refuses below 20 observations and the
graph refuses to trust an edge below 3 transitions — **the corpus grew rather
than the thresholds shrinking.**

Ground truth is emitted alongside: per-pass plate, colour, type, entry and exit
times, and per-camera measured plate legibility.

### What synthetic data cannot establish

Stated plainly. It cannot establish real-world accuracy, real domain shift, real
occlusion patterns, real weather, real plate-font variation, or real camera
faults. It establishes that the pipeline is correct, that thresholds behave, and
that failures are handled — not that the models are good.

---

## 2. Test pyramid

| Level | Count | Command | What it protects |
|---|---:|---|---|
| Unit | Run to count | `make test-unit` | Component behaviour, including every abstention rule |
| Security | Run to count | `make test-security` | Four auth gates, injection, traversal, leakage |
| Integration | Run to count | `make test-integration` | Pipeline over the corpus |
| ML regression | Run to count | `pytest tests/evaluation` | Attribute extraction against ground truth |
| End-to-end | Run to count | `make test-e2e` | The mandatory chain, and the offline demonstration |
| Chaos | — | `make chaos` | Fault injection against a live replica |
| Performance | — | `make perf`, `make queryplan` | Latency and query plans |
| Load | — | `make loadtest` | Concurrent cameras |

**A passing negative test proves nothing until you know it can fail.** Two
controls are maintained: a positive control asserting the same request succeeds
with the right role and scope, and a recorded mutation experiment — removing the
district check from `Principal.in_scope` was confirmed to fail two scope tests,
then reverted.

---

## 3. ANPR evaluation

`make eval` scores plate reading against ground truth. Three independent checks,
because an earlier harness reported PASS on a total collapse — "no wrong plates"
is trivially satisfied by detecting nothing:

1. **Coverage** — what fraction of ground-truth passes produced any detection.
2. **Correctness** — of the plates read, how many match ground truth.
3. **Correct declining** — on the camera measured to be ANPR-unviable, the
   system must abstain rather than guess.

A run that detects nothing fails, loudly.

---

## 4. Capability grading

`make demo` grades every camera from its own observations. The current corpus
produces **3 GOOD for ANPR and 3 UNKNOWN** — the UNKNOWNs being cameras below
the 20-observation evidence floor.

That distribution is the result, not a shortfall. A grader that produced six
confident grades from this data would be the failure.

Each grade stores the statistics behind it, the policy version, and the
thresholds applied, so any grade can be re-derived and disputed.

---

## 5. Performance

`make perf` (in-process, excludes network), `make queryplan` (EXPLAIN over the
ten hot queries), `make loadtest` (concurrent cameras with mid-run failures).

**10 of 10 hot queries use an index.** `ix_audit_case` was added because this
harness caught a full scan — the index exists on evidence, and the before/after
is in `var/reports/query_plans.json`.

Latency figures are always quoted with the row counts they were taken at. A
latency without a scale is not a measurement.

---

## 6. Government feed

**Nothing has been run against a government feed.** Portal registration is
outstanding and shares the 07 September deadline; see
`docs/GOVERNMENT_DATA_ACCESS_CHECKLIST.md`.

When access exists, the order is fixed and **profiling comes first**:

```bash
make government-profile CATALOGUE=http://<host>/api/ingest   # first 30 minutes
make government-import  CATALOGUE=...
make government-run     CATALOGUE=...
```

1. **Profile before touching anything.** Codec inventory, resolution and FPS
   distribution, timestamp health, brightness and sharpness, per-camera
   problems. Output: `REAL_DATA_READINESS_REPORT.{md,json}`.
2. **Baseline the current models unchanged.** A model tuned before it has been
   measured is a model tuned to a guess.
3. **Group the failures** — false OCR, missed vehicles, bad crops, domain shift,
   tracking failures, bad timestamps — before changing anything.
4. **Only then** consider alternatives, per camera tier where justified. The
   router supports different models for different tiers; there is no single-model
   commitment.

Without ground truth from the organisers, accuracy on real feeds can only be
reported as **per-camera yield** (detections, valid reads, abstentions), never as
accuracy against truth. Stated in advance so it cannot look like an excuse later.

---

## 7. Calibration

Scores are **ordering scores, not probabilities**, and every response carrying
one says so.

Calibration needs a labelled held-out set. If one becomes available, the
measurements would be expected calibration error, Brier score and a reliability
diagram — and only then would the word "probability" be used. Until then it is
not.

---

## 8. Reproducibility

```bash
make rebuild        # delete the venv and generated state, reinstall, verify
make release-check  # every gate, blocking and advisory, from clean
```

`make rebuild` exists to catch hidden machine-local dependencies — the class of
problem that only appears on the evaluator's laptop.

Reports are written to `var/reports/` as JSON so a claim can be traced to the run
that produced it.
