# Hackathon requirements reconciliation

**Source documents reviewed**

1. Official challenge/test-case text supplied in
   `pasted-text-73e09777-9535-4106-9d3f-22d82ba57795.txt`.
2. Phase-2 engineering brief supplied in
   `pasted-text-e6ad0196-e0a8-481d-83ee-4fe44269dac4.txt`.
3. Repository evidence in `docs/SENTINEL_SANDBOX.md`,
   `docs/MEASURED_RESULTS.md`, and `var/reports/*`.

## The 30-versus-50 answer

There is **no contradiction in the official requirement**:

- The official technical evaluation says **approximately 50 heterogeneous
  cameras**.
- The official test scenario says teams will access approximately 50 cameras
  through the website Resources page.
- The official integration guide says the camera catalogue at
  `GET /api/ingest` is authoritative and that its camera set can change.
- Our current accessible/probed sandbox evidence contains **30 cameras,
  `cam01`–`cam30`**.

Therefore:

| Number | Meaning | Evidence/status |
|---:|---|---|
| 50 | Evaluation target and capacity gate | **OFFICIAL REQUIREMENT** |
| 30 | Current reachable/probed camera estate in this environment | **MEASURED CURRENT ACCESS**, not the official maximum |
| 80,000 | Statewide planning horizon | **OFFICIAL SCALE DIRECTION**, modeled by us, not a live test |

The current repository must be described as **30 cameras currently accessible,
50-camera evaluation target**. A 30-camera run is evidence of current
integration, not completion of the 50-camera test.

## Why only 30 are visible now

The repository's documented evidence says the catalogue endpoint currently
redirects to authentication and the RTSP host does not serve `/api/ingest`.
Until a valid catalogue session is available, the live tooling uses a clearly
labelled probe/registry path and has observed `cam01`–`cam30`.

This is an **access/discovery limitation**, not permission to hard-code 30.
The importer and live profiler already accept a catalogue URL and dynamically
reconcile the returned entries. When the authenticated Resources-page
catalogue returns approximately 50, the same path should import and process
the returned set without a code rewrite.

## What the hackathon actually requires

### Mandatory live evaluation

- onboard approximately 50 heterogeneous cameras;
- integrate live feeds;
- provide centralized monitoring and AI analytics;
- identify a designated vehicle;
- trace it across cameras and times;
- provide route, location-wise timestamped history, GIS visualization, and
  searchable events;
- continuously cross-reference a representative watchlist;
- generate an automated real-time alert;
- provide evidence of interoperability, scalability, and end-to-end operation.

### Submission deliverables

- solution presentation;
- HLD/technical proposal;
- functional own-feed demonstration of onboarding, analytics, watchlist
  correlation, and alerts;
- government-feed demonstration plus a timestamped vehicle/plate output report;
- accessible submission links and supporting technical information.

### Architecture obligations

The official material permits Model 1, 2, 3, 4, a hybrid, or a custom
architecture. Model 1 is the common registry/GIS foundation. The solution must
be modular, secure, interoperable, vendor-neutral, and designed toward roughly
80,000 cameras. The problem statement explicitly mentions RTSP, ONVIF, vendor
APIs/SDKs, VMS federation, analytics, storage, HA/DR, RBAC, and integration
readiness for authorized government databases.

## Correct positioning for SAAKSHYA

SAAKSHYA should present:

```text
Model 1 registry + GIS
        +
Model 2 unified viewing
        +
Model 3 federation/adapter middleware
        +
Model 4 selected central analytics PoC
        +
regional/edge processing for statewide scale
```

The selected central analytics path is appropriate for own-feed/selected
cameras and proves the central monitoring/analytics pattern. It must not be
described as a single centralized VMS permanently ingesting all 80,000 cameras.
For the government test, the platform must remain catalogue-driven and must
process whatever authenticated catalogue is returned, whether that is 30, 45,
or approximately 50 cameras.

## Current compliance status

| Requirement | Current status | Evidence / action |
|---|---|---|
| 30 currently reachable cameras | GREEN | `docs/MEASURED_RESULTS.md`, live store |
| Dynamic catalogue onboarding | AMBER | Implemented; authoritative catalogue access currently blocked |
| Approximately 50-camera evaluation | AMBER | 50 logical decode/load was measured locally; 50 government cameras have not been verified in this environment |
| Live heterogeneous feeds | GREEN/AMBER | Mixed H.264/H.265 and PTS/reconnect behavior measured; current catalogue access remains conditional |
| Designated vehicle search | GREEN on own/demo and recorded live evidence | Government cross-camera repeat remains unverified |
| Cross-camera route | GREEN on own-feed corpus; AMBER on government feed | Do not fabricate a government repeat |
| Watchlist and real-time alerts | GREEN on representative data | Use representative watchlist as explicitly permitted |
| GIS and searchable history | GREEN | API/UI/tests |
| 80,000-camera strategy | AMBER | Architecture/model only, not a physical test |
| Submission completeness | GREEN/AMBER | Core documents and demonstrations exist; refresh links/output report for the final run |

## Required final test statement

Use this wording with judges:

> “The challenge specifies approximately 50 cameras. Our current authenticated
> access exposed 30 cameras, which we onboarded and measured. The ingestion
> path is catalogue-driven rather than hard-coded; when the evaluation
> Resources catalogue exposes the remaining cameras, the same reconciliation
> and stream gateway process scales to the returned set. Separately, we have
> exercised 50 logical streams locally to validate decoder/fan-out behavior.
> We do not present that local load test as a 50-camera government analytics
> result.”

## Immediate P0 actions

1. Obtain the authenticated Resources-page catalogue or export and run
   `make government-profile CATALOGUE=<authoritative-source>`.
2. Run `make government-import` and verify the registry count against the
   catalogue count; do not assume it is 50.
3. Run the live benchmark for every returned camera and preserve the exact
   count, codecs, resolutions, errors, reconnects, and PTS results.
4. If the authenticated catalogue still returns only 30, report that exact
   fact to the organizers and retain the 50-camera requirement as the target,
   not as a fabricated result.
5. Demonstrate the complete cross-camera route on the own-feed corpus if the
   government footage does not contain a repeated designated vehicle.
