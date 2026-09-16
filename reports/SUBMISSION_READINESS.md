# Submission readiness

Phase 5 uses conservative labels. `READY` means the repository contains the
implementation or evidence artifact; it does not mean an external service is
running. `WARNING` means a capability is optional, unavailable, or only
modeled. `BLOCKER` means a required local artifact or configuration is absent.

## What is evidenced

- Backend, frontend, database schema, analytics, watchlist, GIS, evidence,
  model registry, and submission files are present in the repository.
- The complete own/demo chain is covered by tests and recorded evidence:
  ingest → detection/tracking → ANPR → watchlist → alert → evidence →
  follow-vehicle → route/GIS → investigation.
- The available government evidence is **30 accessible cameras**.
- The official challenge target is **approximately 50 cameras**. It is not
  claimed as available here.
- The logical **50-camera** benchmark validates a bounded execution path with
  local/synthetic media; it is not a government run.
- **80,000 cameras are modeled only**, using the edge/regional/core design.

## Remaining warnings and gates

Live stream gateway health, Sentinel authentication, external map tiles, and
browser telemetry are environment-dependent. An unset credential or absent
service is reported as unavailable, never as healthy. Before submission,
provide the authenticated catalogue and run the same benchmark against it;
preserve the response and report decoder errors, dropped frames, resource
ceilings, throughput, and alert latency.

Run the bounded check from the repository root:

```bash
python tools/pre_demo_check.py
```

It performs no network calls and prints `READY`, `WARNING`, or `BLOCKER`.
