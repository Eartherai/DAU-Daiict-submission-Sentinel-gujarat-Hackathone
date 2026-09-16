# Final evidence matrix

Status vocabulary is intentionally limited to **GREEN**, **AMBER**, and
**RED**.

| Requirement | Implementation | Test/evidence | Status |
|---|---|---|---|
| Dynamic camera onboarding | Catalogue-driven importer and registry | Catalogue/import tests; 30 reachable cameras recorded | GREEN |
| Approximately 50-camera target | N-camera execution path and logical target benchmarks | `benchmark-50`; local logical path measured | AMBER |
| 50 simultaneous government analytics | Same catalogue-driven path | Authenticated environment exposes 30; no 50-government run | AMBER |
| Mixed RTSP/H.264/H.265/PTSs | PyAV stream gateway, TCP transport, discontinuity handling | Ingest tests and live evidence | GREEN |
| Adaptive analytics | Four modes, sampling/OCR/re-ID cadence, bounded admission | Scheduler tests; baseline/adaptive benchmark artifacts | GREEN |
| Vehicle detection | Registered detector backends | Detector latency benchmark; no box ground truth | AMBER |
| OCR/ANPR | Plate normalization, voting, forensic reads | Plate/ANPR tests; labelled crop benchmark unavailable | AMBER |
| Temporal OCR | Conservative `PlateVoter`-backed consensus | Temporal OCR tests | GREEN |
| Tracker | PTS-aware in-tree ByteTracker | Tracker benchmark; competing packages unavailable | AMBER |
| Watchlist correlation | Persistent watchlist, alerts, audit | Watchlist/security/E2E tests | GREEN |
| Follow Vehicle | Ranked subsequent cameras, time/geography/appearance terms | Follow Vehicle tests and API endpoint | GREEN |
| Contradiction handling | Explicit route contradiction payload with speed evidence | Impossible-transition test | GREEN |
| Route/GIS | Trajectory solver, map geometry, timeline | Trajectory/GIS tests and E2E chain | GREEN |
| Evidence | Sealed frame manifests and hash-chain verification | Evidence/security tests | GREEN |
| Frontend video wall | Lazy 4/9/16/30 modes, priorities, focus, cache | `node --check ui/app.js`; browser telemetry not measured | AMBER |
| Model 4 central analytics | Selected-camera central analytics architecture/PoC path | Own-feed architecture and investigation chain | AMBER |
| 80,000-camera scale | Hybrid edge/regional/core design | Architecture arithmetic/model | AMBER |
| Security/RBAC/audit | Auth, jurisdiction, purpose binding, evidence protection | Security suite and adversarial controls | GREEN |
| Government cross-camera repeat | Search/route engine supports it | Current government evidence has zero exact repeats | AMBER |

## Interpretation

The strongest verified story is the complete own/demo investigation chain:

```text
camera -> detection -> tracking -> ANPR -> watchlist -> alert
       -> evidence -> Follow Vehicle -> route -> GIS -> investigation
```

The main remaining amber gates are data/environment dependent: authenticated
approximately-50-camera access, labelled real plate crops/vehicle boxes, and
browser resource telemetry. No amber item is presented as a completed
government result.
