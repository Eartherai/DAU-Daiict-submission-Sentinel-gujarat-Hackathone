# Government-feed test report

## Status

**PARTIAL / environment-dependent.** The repository contains a real
government-feed ingest path and prior government-derived run artifacts. This
report does not imply that credentials or live reachability exist in every
checkout. A run is only marked current after `make live-profile` or
`make live-ingest` produces a new artifact.

## Last recorded evidence

- 30 cameras were onboarded in the live store.
- The recorded estate contained H.264 and H.265 streams and mixed resolutions.
- PTS-aware ingest, reconnects, health persistence, capability grading, search,
  watchlist, evidence, and route APIs were exercised in the recorded workflow.
- The recorded government store had zero exact cross-camera plate repeats.
  Cross-camera route evidence therefore remains synthetic/local, not a
  government-feed claim.

Sources: `docs/MEASURED_RESULTS.md`, `var/reports/live_ingest.json`,
`var/reports/live_evaluation.json`, and `docs/DEMO_SCRIPT.md`.

## Required current run

```bash
make live-profile
make live-ingest LIVE_DB=sqlite:///var/live.db
make live-evaluation PLATE=GJ38BH5815 LIVE_DB=sqlite:///var/live.db
```

Record date/time, camera IDs, protocols, codecs, resolutions, reconnects,
decoder errors, PTS anomalies, observations, alerts, evidence IDs, and
limitations in the generated artifacts. Never copy credentials or private
footage into the repository.
