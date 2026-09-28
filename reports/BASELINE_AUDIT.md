# SAAKSHYA baseline audit

Generated from the repository at the start of `hackathon-winning-upgrade`.
Claims below are classified as **VERIFIED**, **PARTIAL**, **CLAIMED**, or
**UNAVAILABLE**. Existing measurements are not retyped as new measurements.

## Architecture

**VERIFIED.** Python 3.12 package using FastAPI, SQLAlchemy Core, SQLite for
local operation, PyAV for PTS-aware decoding, MediaMTX for the local stream
replica, and a static browser workspace. The implementation is split into
ingest, analytics, registry, store, intelligence, evidence, watchlist,
security, observability, runtime, edge, and API packages
(`src/saakshya/`). The architecture and technology decisions are documented in
`docs/HLD.md`, `docs/ARCHITECTURE.md`, and the ADRs.

## Current capabilities

**VERIFIED.** The repository contains:

- a camera registry and catalogue import path;
- one PyAV decoder per camera with internal fan-out, bounded consumer queues,
  PTS normalization, segment/discontinuity handling, codec metadata, and
  reconnect backoff;
- detection/tracking/attributes/plate voting interfaces;
- searchable observations, camera transitions, trajectory hypotheses, route
  feasibility checks, watchlists, alerts, evidence manifests, and hash-chained
  audit entries;
- GIS camera/alert/route APIs and a working static operator UI;
- bearer authentication, role and jurisdiction checks, purpose binding,
  request IDs, CSP/security headers, bounded search/export admission, and
  stream-credential redaction;
- offline edge queue/synchronization and a deterministic demo store;
- unit, integration, E2E, evaluation, and security tests plus release and
  measurement tools.

## Measured operating evidence

**VERIFIED.** `docs/MEASURED_RESULTS.md` and `docs/SCALE_MODEL.md` report 30
government cameras onboarded, a mixed H.264/H.265 estate, 50-camera decode
load with zero decoder errors in the recorded run, 11.4 frames/s analytics
throughput in one CPU process, indexed search/trajectory timings, 14/14
security controls refused when attacked, and the test suite recorded at the time
of the baseline documentation. These figures are run artifacts, not a promise
that every environment will reproduce them.

## Mandatory live-test chain

**PARTIAL.** The official evaluation target is approximately 50 cameras. The
currently accessible/probed sandbox estate contains 30 cameras. Catalogue
discovery, live connection, observations, search,
watchlist, alerts, evidence, GIS, and route reconstruction exist. The live
government run has 0 exact cross-camera repeats in the recorded store, so a
multi-camera government route is not demonstrated by that evidence. The
cross-camera route is demonstrated on the local synthetic corpus only.

## Important limitations

**VERIFIED.** The following are explicitly documented rather than hidden:

- 80,000-camera operation is an architecture and cost model, not a measured
  video run.
- SQLite is suitable for an edge/demo node, not a statewide central writer.
- One CPU analytics process sustains roughly 11 cameras at 1 fps in the
  recorded benchmark; inference, not decode, is the first bottleneck.
- Most profiled government cameras are unsuitable or unknown for ANPR because
  of scene geometry and plate pixels.
- The repository does not claim that an uncertain OCR read is an identity.
- Government-feed credentials and private footage are not committed.
- PostgreSQL/PostGIS/pgvector deployment is designed and has DDL/interface
  support, but is not a locally executed production-scale deployment test.

## Bugs and technical debt found by inspection

**PARTIAL.** The primary remaining engineering debt is operational rather than
conceptual: the required competitor evidence pack and judge score were not
previously generated in `reports/`; the 50-camera measurement is a decode/load
test rather than a 50-camera full analytics run; and the government-feed report
needs an explicit current run status whenever credentials are unavailable.
These gaps are addressed by the report/tool additions in this branch.

## Demo workflow

**VERIFIED.** `make demo` seeds an isolated store and `make serve` starts the
API/UI. `make live-profile`, `make live-ingest`, and `make live-serve` provide
the government-feed path. `docs/DEMO_SCRIPT.md` describes the own-feed and
government-feed flows and calls out where the evidence is synthetic,
government-derived, or modeled.

## Government-feed readiness

**PARTIAL.** The live catalogue/RTSP path, credentials handling, codec
variation, PTS behavior, reconnect logic, and health persistence are
implemented. A current environment-specific government-feed result is not
assumed by this audit; the report records the last repository evidence and the
conditions needed to rerun it.

## UI/UX

**VERIFIED/PARTIAL.** The UI includes overview, live, find, map, alerts,
evidence, audit, and health workflows and uses real API data. Visual assets and
recorded walkthroughs exist. Browser E2E coverage is present, but the UI is a
static application rather than a separately built component system, and live
browser video depends on the configured WHEP/HLS deployment.

## Security and observability

**VERIFIED.** `docs/SECURITY.md`, `tests/security/`, and
`var/reports/security_scorecard.json` document authentication,
authorization/purpose/jurisdiction gates, path and injection defenses,
credential redaction, audit/evidence integrity, metrics, health/readiness, and
request correlation. Database-file and host compromise remain explicitly out
of scope.

## Highest-risk weaknesses

1. The official test target is approximately 50, while current authenticated
   access has exposed only 30; no 50-camera government end-to-end analytics run
   exists in the evidence.
2. No exact cross-camera government-feed repeat in the recorded evidence.
3. Central PostgreSQL/PostGIS deployment and failover are designed but not
   exercised on this machine.
4. ANPR quality is highly camera-dependent; most government cameras are not
   plate-readable.
5. Competitor implementation evidence is external and can be unavailable,
   stale, or license-incompatible.

## Highest-impact opportunities

1. Keep the mandatory demo honest and deterministic while making the
   government-feed conformance report executable.
2. Make 50-camera mode explicitly distinguish decode, analytics, and end-to-end
   stages.
3. Preserve the timebase/route contradiction UX as the core differentiator.
4. Publish a competitor matrix with verification status and license evidence.
5. Measure every new claim through an artifact-generating command.
