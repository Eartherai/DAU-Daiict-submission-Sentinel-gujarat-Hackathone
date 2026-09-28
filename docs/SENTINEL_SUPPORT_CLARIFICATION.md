# Sentinel support clarification

Sanitised record of the organisers’ written answer, checked against the
integration record in `docs/SENTINEL_SANDBOX.md` (Concurrent access). This is
support guidance, not a benchmark. No participant identity or access details
are reproduced.

| Organisers’ guidance | Platform response (VERIFIED in the cited code) |
|---|---|
| No fixed participant-facing concurrent RTSP limit per team | Per-worker camera assignments; no team quota inferred (`analytics/worker.py`) |
| No fixed participant-facing concurrent RTSP limit per network address | Source failures are recorded per camera (`ingest/stream.py`) |
| No fixed participant-facing concurrent RTSP limit per camera | Shared hub capture avoids redundant still sessions (`live/hub.py`, `live/snapshot.py`) |
| No fixed participant-facing aggregate session or rate limit | Local budgets are labelled as local policies (`ui/app.js`, `live/relay.py`) |
| Availability varies with overall sandbox usage and gateway load | Health and reconnect states stay visible; no promise of every tile being live (`command/summary.py`) |
| The supplied development/test set has 30 cameras | Registry intake preserves source identity; the evaluation composition is separate (`command/domain.py::enforce_evaluation_50`) |
| Architecture should be independent of that camera count | Registry-driven intake and selected worker assignments; synthetic registry/GIS load is reported separately (`reports/SCALE_80K_LOAD_TEST.md`) |
| Open only streams actively required; avoid unnecessary long-lived or repeated connections | On-demand hub and opt-in relay (`live/hub.py`, `live/relay.py`); operator-selected wall policy (`ui/app.js`) |
| Stagger connections, isolate cameras, reconnect with backoff | Staggered browser/hub/relay starts and per-camera retry with jitter (`ui/app.js`, `ingest/stream.py`, `live/relay_publisher.py`) |
| Large-fan-in variation must not automatically be attributed to a local bridge limit | Keep each test window’s observed count and errors; separate source availability from local decode/encode measurements |
| No participant-specific `/api/ingest` catalogue is provided | Probe-derived records are labelled as such; departmental CSV/API onboarding remains available (`docs/SENTINEL_SANDBOX.md`, `api/routes_registry.py`) |

**Measured during a test window ≠ sandbox limit.** A successful or failed
concurrency run does not establish an upstream quota, admission threshold or
session-reaping mechanism.

The browser has two explicit policies (`ui/app.js::tileWhepBudget`):
CONTROL ROOM (Dense 6×5), up to 30 direct WHEP sessions, opened 400 ms apart;
OPTIMIZED VIEW, at most 12 near the viewport, with 600 px prefetch and release
after 15 s off screen. `#media-policy` states which is active. Signalling uses
SAAKSHYA’s authenticated proxy; browser clients never hold Sentinel credentials.
AI workers independently consume selected RTSP/TCP streams.

The optional local relay defaults to a **local** government-camera cap of 15
(`src/saakshya/live/relay.py`, `MAX_CAMERAS`).
`SAAKSHYA_RELAY_MAX_CAMERAS` changes it; a positive value slices the selected
government list, and 0 disables that cap. Own feeds are added separately.
The default reflects the ramp recorded in `reports/CLAUDE_LIVE_WALL_RESULT.md`
on that machine during that test window, not a limit of Sentinel or a measured
maximum of every relay deployment.
