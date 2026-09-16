# Final judge package

## Executive summary

SAAKSHYA is a vendor-neutral CCTV intelligence platform that turns
heterogeneous camera feeds into searchable, auditable vehicle investigations:

```text
camera -> stream gateway -> adaptive inference -> detection -> tracking
       -> ANPR/OCR -> watchlist -> alert -> evidence
       -> Follow Vehicle -> route -> GIS -> investigation
```

The implementation is catalogue-driven and preserves PTS-based timing,
bounded fan-out, reconnect behavior, mixed codecs, security controls, and
evidence integrity.

## Verified capabilities

- 30 currently reachable/probed government cameras onboarded and measured.
- 50 logical-camera decoder/fan-out and catalogue-sized benchmark path.
- Adaptive `NORMAL`, `HIGH_PRIORITY`, `ALERT`, and `FORENSIC` inference modes.
- Plate normalization, temporal consensus, watchlists, alerts, evidence, GIS,
  route reconstruction, and Follow Vehicle.
- Explicit impossible-route contradiction handling.
- Lazy 4/9/16/30 camera wall with focus and stream priorities.
- Full security/RBAC/audit and evidence-chain regression coverage.

## Government feed status

The official test target is approximately 50 cameras. The current authenticated
environment exposes 30 cameras. Government evidence demonstrates onboarding,
heterogeneous streams, health, timestamps, detection, and searchable events.
No government cross-camera repeat is claimed.

## Own-feed status

Own/demo footage is used for the complete narrative: ANPR, watchlist,
alerting, evidence, Follow Vehicle, cross-camera route, GIS, and investigation.
This is explicitly labelled own-feed demonstration data.

## 50-camera status

The application path accepts dynamic `N`; `make benchmark-50` exercises the
logical target path on available local media. Simultaneous 50-camera
government analytics remains **AMBER — ENVIRONMENT DEPENDENT**.

## Model 4 status

Selected-camera central analytics is supported as a bounded own-feed PoC:

```text
own feeds -> central gateway -> analytics workers -> event store
           -> watchlist -> alerts -> GIS -> investigation
```

Statewide full-video centralization is not claimed; regional/edge federation
is the scale architecture.

## Analytics status

The measured short synthetic comparison was:

| Scenario | Baseline | Adaptive |
|---|---:|---:|
| Target 30, six local clips | 4.583 FPS | 8.181 FPS |
| Target 50, six local clips | 5.850 FPS | 10.606 FPS |

These numbers are not government-camera throughput or accuracy. The available
labelled OCR corpus is empty, so OCR accuracy remains unverified.

## Security status

Authentication, RBAC, jurisdiction scope, purpose binding, SQL-bound access,
path traversal defense, secret redaction, security headers, audit chaining,
and evidence integrity remain covered by the security and full test suites.

## Scalability

The statewide model is event-first and metadata-first:

```text
edge -> regional ingest/analytics -> state event core -> command centre
```

80,000-camera figures are architectural/cost assumptions, not a live test.

## Exact demo flow

1. Open the command center and show camera/alert/system state.
2. Show the live wall in the appropriate 4/9/16/30 mode.
3. Search the known own-feed vehicle.
4. Show normalized plate, watchlist match, alert explanation, and evidence.
5. Click **Follow Vehicle**.
6. Show ranked next-camera candidates and any contradiction explanation.
7. Select a route point to synchronize map, timeline, camera, and evidence.
8. Switch to the government feed and show onboarding, health, timestamp, and
   searchable event behavior.
9. Finish with the hybrid edge/regional/state architecture and the
   approximately-50-camera distinction.

## Exact judge claims

- “30 government cameras were accessible and measured in this environment.”
- “The platform processes a dynamic catalogue rather than hard-coded 30 IDs.”
- “The official evaluation target is approximately 50 cameras.”
- “50 logical validation exists; simultaneous 50-government-camera analytics is
  pending authenticated access to that catalogue.”
- “The complete cross-camera route is demonstrated on own-feed data.”
- “80,000-camera operation is an architectural scale model, not a physical
  test.”

## Claims we must not make

- Do not call 30 government cameras a completed 50-camera government test.
- Do not quote an OCR accuracy percentage without labelled crops.
- Do not claim a government cross-camera repeat that was not observed.
- Do not call the short six-clip FPS results 30- or 50-camera throughput.
- Do not claim statewide 80,000-camera central video processing.
- Do not claim production readiness or legal admissibility.
