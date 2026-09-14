# Release readiness

**Assessment: release candidate for the challenge submission. Not production.**

Those are different claims and the difference is stated below rather than left
to interpretation. Regenerate the evidence with `make release-check`.

**Latest full run:** `make release-check` — **12 of 12 gates pass from clean.** Report: `var/reports/release_check.json`.

---

## Gates

| Gate | Severity | Status | Command |
|---|---|---|---|
| Lint (ruff, src + tools + tests) | Blocking | **PASS** | `make lint` |
| Secret scan (tracked files **and** git history) | Blocking | **PASS** | `make secrets` |
| Licence policy + SBOM | Blocking | **PASS** | `tools/verify/licence_check.py` |
| Unit tests (199) | Blocking | **PASS** | `make test-unit` |
| Security tests (47) | Blocking | **PASS** | `make test-security` |
| Integration tests (5) | Blocking | **PASS** | `make test-integration` |
| End-to-end: mandatory chain (13) | Blocking | **PASS** | `make test-e2e` |
| End-to-end: offline mode (18) | Blocking | **PASS** | `make test-e2e` |
| Typecheck (mypy) | **Blocking** | **PASS** — clean across 68 files | `make typecheck` |
| ML regression | Advisory | **PASS** | `pytest tests/evaluation` |
| Query plans (10/10 indexed) | Advisory | **PASS** | `make queryplan` |
| API latency | Advisory | **PASS** | `make perf` |
| 50-camera simulation | Advisory | **PASS — measured** | `make loadtest` |
| Clean install in a fresh environment | **Blocking** | **PASS** — 6/6 steps | `make rebuild-check` |
| 2-hour chaos soak | Advisory | **NOT RUN** | `make chaos-long` |

---

## Live government grid

**All 30 cameras of the organiser's Sentinel Camera Grid ran simultaneously
through the production pipeline.** Details in `docs/LIVE_FEED_FINDINGS.md`.

| | |
|---|---|
| Reachable | 30 / 30 over RTSP/TCP |
| Simultaneous ingest | **30 / 30**, 4 min, 590 observations, 3.15 GB |
| Reconnects, scene cuts handled | 11, 79 |
| Capability graded | 6 dimensions per camera, from measurement |
| Infrared cameras correctly refused for appearance | **16 / 30** |
| ANPR | **Not measurable** — the replayed window is overnight |
| Cross-camera trajectory | **Not meaningful** — camera clocks differ by hours and by date |
| Coordinates / GIS | **Blocked** — the catalogue needs a signed-in session |

The live feed found three faults in our own code that no synthetic test could
have: see CR-006. That is the strongest argument for having run it.

---

## What works, end to end

The mandatory chain, with **no language model in the loop** — asserted
structurally by a test that fails if one is even imported:

```
ingest → observations → plate search → camera graph → trajectory
       → watchlist → alert → evidence → verification
```

Plus: GIS with six stable endpoints, the investigation workspace, case files
with audit trails, measured camera capability, offline operation with lossless
replay, and a grounded read-only copilot.

---

## Reproducibility

```bash
make install        # uv venv + editable install
make media          # render the corpus from a fixed seed
make demo           # seed an isolated demonstration store, print tokens once
make serve          # API + workspace on 127.0.0.1:8080
make verify         # every blocking gate
make release-check  # everything, blocking and advisory
make rebuild        # delete the venv and generated state, then verify
```

`make rebuild-check` installs the package **non-editable, into a temporary
environment, from a different working directory** and imports every module from
outside the source tree. That catches the class of failure that first appears on
the evaluator's laptop: a package installed globally, a stale editable install,
an import that only resolves because the working directory happens to be the
repository root.

It is non-destructive on purpose — a check that costs a rebuild to run is a check
that gets skipped. `make rebuild` keeps the destructive form for when the working
environment itself is suspect.

Demonstration state lives in `var/demo.db` and the seeder **refuses** to write to
the evaluation store. A demo cannot improve a measured result.

---

## Known defects

| Sev | Defect | Impact | Status |
|---|---|---|---|
| P2 | opencv/PyAV `recursive_mutex` abort at interpreter shutdown | Noisy exit after some runs; no data loss | Open — fix is separate processes for ingest and analytics |
| P2 | `CameraPipeline.process` carries four responsibilities | Maintainability | Open, flagged since CR-003 |
| P2 | `InvestigationService.search_target` carries four responsibilities | Maintainability | Open, next extraction candidate |
| P3 | C-014 lost one of three plate reads after the CR-003 merge tightening | Slightly lower yield on one camera | Open |
| P3 | Track fragmentation under dense traffic | Coalesced at the trajectory layer; the tracker still fragments | Mitigated, not fixed |
| P3 | Motion segmentation merges vehicles under dense traffic | Attributes abstain on an implausible box and the abstention is counted; the merge itself remains | Mitigated, not fixed |

**No P0 or P1 is open.** Every P0 and P1 raised in CR-004 and CR-005 was fixed
and has a regression test — including a P0 in the decoder-error handler that no
test could have reached, because the corpus never produced a decoder error. It
was found by promoting the type check from advisory to blocking.

---

## What this is not

Stated plainly, because a release note that only lists strengths is not a
release note.

- **Not production-ready.** No PKI, no encryption at rest, no per-principal rate
  limiting, no retention-enforcement job, no formal penetration test, no HA.
- **Not validated on real data.** Every accuracy figure comes from a synthetic
  corpus and is labelled as such. No government feed has been touched.
- **Not calibrated.** Scores are ordering scores, and every response carrying one
  says so.
- **Not tested at scale.** Measured at 50 concurrent cameras on one 10-core
  host: ingest held with zero decoder errors, and analytics saturated at ~11
  cameras per CPU process. 80,000 is an architectural target, not a result.
- **Not a claim about admissibility.** Evidence is prepared to support a s.63
  certificate. Signing and admissibility are for a person in charge, an expert,
  and a court.

---

## Outstanding before submission

| Item | Owner | Blocking? |
|---|---|---|
| **Portal registration at `sentinel.gujarat.gov.in`** | Team — nobody else can | **Yes.** Shares the 07 September deadline |
| **Grid catalogue session** (`SENTINEL_GRID_COOKIE`) | Team | Unblocks camera coordinates, GIS and HLS fallback |
| **Daylight window on the live grid** | Organisers / time | Unblocks any ANPR measurement on real footage |
| Own-feed recording, 2–3 minutes | Team | Yes |
| Government-feed recording + output report | Blocked on registration | Yes |
| Solution presentation (PPT/PDF) with model justification | `docs/PPT_CONTENT.md` | Yes |
| Technical proposal / HLD | `docs/ARCHITECTURE.md` + `docs/HLD.md` | Yes |
| Unlisted video link with viewer access enabled | Team | Yes |
| 2-hour chaos soak | Optional | No |

The software cannot obtain portal access, and no credential may be guessed,
shared or worked around. That item is the critical path.
