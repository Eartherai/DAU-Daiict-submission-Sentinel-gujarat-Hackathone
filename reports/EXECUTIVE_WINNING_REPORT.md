# Executive engineering report

## Where we started

The repository is a working Python/FastAPI CCTV intelligence fabric rather than
a blank prototype. It already had PTS-aware ingest, camera registry, analytics,
search, route reasoning, evidence, watchlists, security gates, a static
operator workspace, deterministic demo tooling, and recorded government-feed
artifacts.

## What the audit found

The strongest competitor ideas are geometry-aware route reconstruction,
MediaMTX/registry federation, visual command-center polish, suspicious-behavior
escalation, and audit-friendly route exports. Public implementation depth is
uneven: several repositories have no declared license, and several claims are
architecture or mock evidence rather than a demonstrated live path.

## Changes in this branch

- Added a baseline audit and scored evidence scorecard.
- Added government-feed, performance, security, and scalability evidence reports
  with explicit measured/partial/modeled boundaries.
- Added a conservative `tools/judge_score.py` and `make judge-score`; missing
  evidence scores zero.
- Added a 20-repository competitor comparison, license audit, conceptual
  learning record, and prioritized gap backlog.

## Why the architecture is stronger

The core differentiator is not a claim of universal ANPR. The system measures
camera capability, uses stream PTS rather than wall-clock/FPS assumptions,
shares one upstream decoder among consumers, labels timebase/coverage gaps,
rejects impossible transitions, and keeps uncertainty visible in alerts and
evidence. That is a more defensible operational story than a polished
dashboard with unverified identities.

## Remaining risks before judging

The most important unresolved items are a measured full-analytics 50-camera
run, a repeated designated vehicle on synchronized government cameras, and an
exercised central Postgres/HA deployment. They are documented as open rather
than presented as passes. Use the deterministic own-feed route for the
guaranteed demo and the government path to demonstrate onboarding, live health,
analytics output, search, and honest capability limits.

## Evidence index

Start with `reports/BASELINE_AUDIT.md`, `reports/PERFORMANCE_BENCHMARK.md`,
`reports/GOVERNMENT_FEED_TEST_REPORT.md`, `reports/SECURITY_AUDIT.md`,
`reports/SCALABILITY_VALIDATION.md`, and the generated
`reports/JUDGE_SIMULATION.md`.
