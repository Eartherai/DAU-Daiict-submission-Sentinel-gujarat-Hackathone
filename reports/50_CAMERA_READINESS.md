# 50-camera readiness

This report separates the official evaluation target from the evidence
available in the current environment.

| Class | Result | Meaning |
|---|---:|---|
| **REAL GOVERNMENT** | 30 cameras | 30 currently reachable/authenticated cameras were onboarded and measured |
| **VERIFIED LOGICAL** | 50 logical streams | Mixed-codec decoder/fan-out load was measured; the complete local pipeline benchmark is available through `make benchmark-50` |
| **UNVERIFIED** | 50 simultaneous government analytics | The authenticated catalogue available in this environment has not exposed approximately 50 feeds |
| **OFFICIAL TARGET** | approximately 50 | Required by the challenge test case; authoritative count comes from `/api/ingest` after Resources-page authentication |

## What is implemented

The execution path is catalogue-sized rather than ID-sized:

```text
authoritative catalogue
  -> dynamic registry/import
  -> N stream workers
  -> bounded adaptive inference scheduler
  -> analytics pipeline
  -> events, watchlist, alerts, GIS, evidence
```

The scheduler supports `NORMAL`, `HIGH_PRIORITY`, `ALERT`, and `FORENSIC`
modes. It controls source-frame sampling, detector cadence, OCR cadence,
re-identification/appearance cadence, and bounded priority admission. Existing
callers retain the previous every-frame behavior when no scheduler is
configured.

Run the complete local pipeline benchmark with:

```bash
make benchmark-30
make benchmark-50
```

Each command writes a JSON and Markdown artifact containing catalogue count,
available media count, processed camera count, frames received/processed,
detections, tracks, OCR reads, observations, errors, and throughput. The
measurement class is recorded as `GOVERNMENT CATALOGUE` or `SYNTHETIC
CATALOGUE`; the tool does not fill missing cameras with fabricated results.

## What remains to close the official gate

1. Obtain the authenticated Resources-page catalogue and preserve the exact
   `/api/ingest` response used for the run.
2. Run the same benchmark with `--source government` and the authoritative
   catalogue.
3. Record simultaneous government analytics for the returned camera count,
   including decoder errors, dropped frames, OCR throughput, alert latency,
   CPU/GPU/memory, and camera health.
4. If the catalogue still exposes 30, report `30 accessible / approximately 50
   target` to the organizers. Do not relabel the 30-camera result as a
   completed 50-camera government test.

The 50-camera logical result validates the application architecture and local
capacity path. It is not evidence that 50 government feeds were available.
