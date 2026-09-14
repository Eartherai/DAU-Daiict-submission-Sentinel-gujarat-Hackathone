# SAAKSHYA

**साक्ष्य — *evidence***

A federated CCTV intelligence and evidence fabric for a camera estate that was
never built to be one.

Gujarat Police Innovation Challenge 2026 · Models 1 + 3, with Model 2 as
fallback.

---

## The problem

Gujarat operates tens of thousands of cameras installed by Home, Health, GSRTC,
Panchayat and Municipal bodies, over two decades, for local supervision — a
gate, a ward, a bus stand. Most were never installed to read a registration
number, and **nobody has a list of which ones can**.

An investigator's question is *"where did this vehicle go?"*. Two facts shape
every answer:

- **Video cannot be centralised.** 80,000 cameras at 2 Mbps is 160 Gbps
  sustained and ~52 PB for 30 days. Metadata is ~400 bytes per observation.
- **Capability is unknown and unequal.** A system that assumes otherwise returns
  nothing from half the estate and never says why.

## What it does

```
ingest → observations → plate search → camera graph → trajectory
       → watchlist → alert → evidence → verification
```

That chain runs end to end with **no language model in the loop** — a test fails
if one is even imported while it runs.

On top of it: a GIS layer, an investigation workspace, case files with audit
trails, measured per-camera capability, offline operation that loses nothing,
and an optional read-only copilot.

## The three ideas worth arguing about

**Capability is measured, not assumed.** Three independent grades per camera —
can it read a plate, can it tell one vehicle from another, can it tell us
something passed — measured from the camera's own stream, with the evidence
stored beside the grade. A camera with too little evidence is `UNKNOWN`, never
`UNSUITABLE`: silence is not failure, and slandering working equipment teaches
operators to distrust the grades that are real.

**Absence of evidence is not evidence of absence.** Trajectory legs are typed
`OBSERVED` / `UNOBSERVED` / `COVERAGE_GAP` / `CONTRADICTION`. A gap says the
system could not observe; it never says the vehicle was elsewhere, and the
product says so in words, because under time pressure that is the distinction
people lose.

**Intrusive queries are accountable.** A vehicle search requires a case
identifier and a written purpose, refused at the authorisation gate before any
data is read, both written into a hash-chained audit log. Authentication
establishes who is asking; it does not establish entitlement to a person's
movement history.

## Run it

```bash
make install     # uv venv + editable install
make media       # render the synthetic corpus from a fixed seed
make demo        # seed an isolated store; prints sign-in tokens once
make serve       # http://127.0.0.1:8080
```

Demonstration state lives in `var/demo.db`. The seeder **refuses** to write to
the evaluation store — a demo must never be able to improve a measured result.

```bash
make verify         # every blocking gate
make release-check  # everything, blocking and advisory
make loadtest       # concurrent camera simulation
make queryplan      # EXPLAIN over the hot queries
```

## Against the real feed

No government feed has been touched; portal registration is outstanding. The
code is ready for it — the catalogue is the contract, and no camera id,
department or endpoint is hard-coded anywhere:

```bash
make government-profile CATALOGUE=http://<host>/api/ingest   # profile first
make government-run     CATALOGUE=http://<host>/api/ingest
```

See [`docs/GOVERNMENT_DATA_ACCESS_CHECKLIST.md`](docs/GOVERNMENT_DATA_ACCESS_CHECKLIST.md)
and [`docs/SENTINEL_SANDBOX.md`](docs/SENTINEL_SANDBOX.md).

## Measured, and modelled

Kept apart everywhere, including here.

| | |
|---|---|
| **MEASURED** | 50 concurrent cameras, mixed codecs — 52,637 frames, **0 decoder errors**, 6 failed mid-run and recovered |
| **MEASURED** | One analytics process sustains 11.4 frames/s (~11 cameras at 1 fps) |
| **MEASURED** | 10 of 10 hot queries use an index; API p50 1.7–9.6 ms |
| **MEASURED** | Offline replay: no duplicates, no loss. 5 of 5 tamper tests detected |
| **MEASURED** | DINOv2 appearance baseline **rejected**: margin −0.541 |
| **MODELLED** | 80,000 cameras across ~33 district nodes |

We do not say "tested at 80,000". Measured at fifty, designed for eighty
thousand.

## What it is not

- **Not production-ready.** No PKI, no encryption at rest, no rate limiting per
  principal, no retention job, no formal penetration test.
- **Not validated on real data.** Every accuracy figure is from a synthetic
  corpus and labelled as such.
- **Not calibrated.** Scores are ordering scores, and every response carrying
  one says so.
- **No face recognition.** A decision, not a gap — see
  [`docs/PRIVACY.md`](docs/PRIVACY.md).
- **Not a claim about admissibility.** Evidence is prepared to support a BSA
  s.63 certificate; signing and admissibility are for a person in charge, an
  expert, and a court. A test asserts the phrase "legally admissible" appears
  nowhere in any export.

## Documentation

| | |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built, and why |
| [HLD.md](docs/HLD.md) | Technical proposal |
| [API.md](docs/API.md) | 37 endpoints; OpenAPI at `/openapi.json` |
| [DATA_MODEL.md](docs/DATA_MODEL.md) | 18 tables, one schema, two dialects |
| [SECURITY.md](docs/SECURITY.md) | Threat model and four authorisation gates |
| [PRIVACY.md](docs/PRIVACY.md) | Purpose limitation, minimisation, why no faces |
| [PERFORMANCE.md](docs/PERFORMANCE.md) | Measured latency, query plans, load |
| [SCALE_MODEL.md](docs/SCALE_MODEL.md) | Where it breaks first |
| [EVALUATION_PLAN.md](docs/EVALUATION_PLAN.md) | How every number was obtained |
| [FINAL_RED_TEAM.md](docs/FINAL_RED_TEAM.md) | Attacks we ran on ourselves |
| [CODE_REVIEW_LOG.md](docs/CODE_REVIEW_LOG.md) | Every defect found, with severity |
| [SENTINEL_SANDBOX.md](docs/SENTINEL_SANDBOX.md) | How we consume the live camera grid |
| [JUDGE_QA.md](docs/JUDGE_QA.md) | The hard questions, answered |
| [RELEASE_READINESS.md](docs/RELEASE_READINESS.md) | Gates, known defects, what is missing |

## Licence and credentials

Dependencies are permissively licensed and the policy is enforced in code — the
model router refuses a non-permissive licence and `make verify` fails on one.

**No credential is in this repository**, and a secret scan over tracked files
*and full git history* runs in `make verify`.
# DAU-Daiict-submission-Sentinel-gujarat-Hackathone
