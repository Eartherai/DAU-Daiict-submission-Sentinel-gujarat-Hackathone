# Sentinel sandbox — integration reference

How this platform consumes the organiser's camera grid. Protocol behaviour is
taken from the official integrator guide. Host-specific measurements are labelled
**MEASURED**. Nothing in this file is a credential.

---

## What we are connecting to

Every camera is a live RTP/RTSP stream. One second of video takes one second to
arrive. Frames carry monotonic presentation timestamps (PTS). There is no
seeking, no byte-range fetch, and no way to run ahead of real time. Treat each
endpoint as a physical camera on an operational network.

| Protocol | Endpoint | Intended for |
|---|---|---|
| RTSP | `rtsp://<host>:8554/stream/<id>` | AI inference (OpenCV, GStreamer, FFmpeg, DeepStream, this platform) |
| WebRTC (WHEP) | `http://<host>:8889/stream/<id>/whep` | Low-latency browser preview |
| HLS | `http://<host>/live/stream/<id>/index.m3u8` | Dashboards, mobile, restricted networks |

The catalogue is the contract; the URL pattern is not. Camera ids and the set of
available cameras can change. Always start from the catalogue:

```
GET http://<host>/api/ingest
```

It is documented to return every camera with `id`, location, codec, live status,
stream properties, and all three URLs.

**MEASURED (4 September 2026), this sandbox:**

| Endpoint | Result |
|---|---|
| RTSP `rtsp://103.250.160.189:8554/stream/cam21` | Opens over TCP when `SENTINEL_GRID_EMAIL` and `SENTINEL_GRID_PASSWORD` are in the process. cam21 answered H.264 1920×1080 in 9.5 s, three decoded frames in 14 s. Join produces decoder warnings until the first IDR — expected, not fatal. |
| `http://103.250.160.189/api/ingest` | HTTP 404 (openresty). The documented catalogue path is not served from the RTSP host. |
| `http://103.250.160.189/live/stream/<id>/index.m3u8` | HTTP 404. HLS is not on the RTSP host. |
| `https://cctv.corp8.cloud/cameras.json` and `/api/ingest` | HTML sign-in page. HTTP basic with the stream access password does not unblock it. Catalogue coordinates still need a browser session cookie (`SENTINEL_GRID_COOKIE`). |
| WHEP `:8889/api/ingest` | MediaMTX: path not configured. |

Until the catalogue is reachable, this platform discovers cameras by probing the
documented id pattern (`cam01`…), labels every such record `source="probe"`, and
runs ingest `--from-registry` against the already-onboarded set. That is not the
authoritative estate. The parser already accepts the documented `/api/ingest`
JSON shape so unblocking the catalogue is configuration, not a rewrite.

This estate's reachable ids are `cam01`–`cam30`, not the guide's example
`/stream/1`. Use the catalogue (or the labelled probe set), never a hardcoded
id list.

---

## Stream authentication

The integrator guide does not describe authentication. On this sandbox **RTSP
and WHEP authenticate the URL authority** with the registered email and the
issued access password (`XXXX-XXXX-XXXX`):

```
rtsp://<email>:<password>@<host>:8554/stream/<id>
```

The `@` in the email must be percent-encoded or the authority splits and the
grid returns 401.

This platform never stores that URL. The registry keeps the clean host path.
`saakshya.live.credentials.credentialed()` injects the authority at socket open.
`redact()` is applied on every exit that can quote a URL (logs, exceptions,
health, reports). Configuration, environment only:

```
SENTINEL_GRID_EMAIL
SENTINEL_GRID_PASSWORD
```

Neither is read from a file, written to one, accepted from a request, or
committed. A missing pair is reported as `grid_access` DEGRADED on
`/system/health`; live stills fail immediately instead of waiting twelve seconds
per tile for a 401.

The CDN catalogue and HLS still use a **session cookie**, not this password.
Export `SENTINEL_GRID_COOKIE` (or `_TOKEN` / `_BASIC`) after a browser sign-in
if those endpoints are needed. Do not write the cookie into the repository.

---

## Connecting (this platform)

Analytics transport is **RTSP over TCP**. UDP is accepted by the grid but fails
across NAT; partial UDP delivery produces corrupt frames that look like model
bugs. If 8554 is blocked, the fallback is HLS — which on this sandbox still
needs the CDN session.

OpenCV / GStreamer / FFmpeg snippets in the official guide apply unchanged,
with TCP forced and the credential in the authority. This codebase uses PyAV:

```python
av.open(credentialed(url),
        options={"rtsp_transport": "tcp", "stimeout": "15000000"},
        timeout=20.0)
```

H.264 and H.265 both occur: the historical store snapshot recorded 23 h264
and 6 hevc, with one camera unobserved (`docs/MEASURED_RESULTS.md`).
Pipelines must not assume a single codec or a single resolution.

---

## Do's and don'ts — mapped to this codebase

| Guide | Here |
|---|---|
| **DO** force RTSP over TCP | `tools/live/ingest.py`, `snapshot.py`, `grid.probe_stream`, `profile_grid.py` |
| **DON'T** trust declared FPS | `declared_fps` is recorded and labelled; every timing decision uses `frame.pts * time_base` |
| **DO** drive timing from PTS, never arrival | OpenCV `CAP_PROP_POS_MSEC` equivalent: packet PTS. The gateway replays a buffered GOP on join, so the first second or two may arrive faster than real time. A tracker timestamped by arrival computes impossible velocities after every reconnect. |
| **DON'T** assume constant frame rate | Inter-frame gaps are tolerated; motion models use PTS deltas. cam15 was measured advancing PTS at 0.396× wall time. |
| **DO** reconnect with backoff (~2 s, cap ~30 s) | `LiveWorker.BACKOFF_INITIAL_S = 2`, `BACKOFF_CAP_S = 30`, with jitter so thirty cameras do not retry as a herd |
| **DON'T** treat join decode warnings as fatal | `av.logging.FATAL`. "Missing reference picture" / "Error constructing the frame RPS" until the first IDR is logged, not an abort |
| **DON'T** assume a uniform grid | Per-camera codec, resolution, rate from the profile / catalogue. No fixed-shape inference batch across the estate |
| **DO** expect a scene discontinuity | Each feed is a looping recording. A hard cut at the loop point. Tracks are flushed on PTS regression; `discontinuity.py` is a second, pixel-level signal because PTS can stay monotonic across the cut |
| **DON'T** plan on obtaining copies of the footage | There is no file download. `/stream/<id>` as a byte-range media URL is a player fallback; `curl`/`wget` of it is not a dataset |
| **DON'T** publish to the gateway | Consume only. No control API calls |
| **DO** pace load | Snapshot service: prefer ingest preview (one JPEG/camera/s) so the wall is not a second client. Max 4 concurrent RTSP captures as fallback. Ingest: `--fps-budget` (default 12 analysed fps). Open only cameras being processed; close captures that are finished |

---

## Concurrent access — what the organisers said, and what this platform does

We asked the organisers, with our measurements attached, for the sandbox's
concurrent-RTSP limits and the integration pattern they expect for thirty
cameras. Their written reply, in substance:

- There is **no fixed participant-facing limit** on concurrent RTSP sessions -
  per team, per IP, per camera or in aggregate - and no fixed rate limit.
  Availability varies with **overall sandbox usage and gateway load**.
- Keep open **only the streams actively required**; many unnecessary
  simultaneous or long-lived connections can affect feed availability.
- The thirty cameras are for development and testing; the architecture should
  be **scalable and independent of a fixed camera count**.
- Use connection management, **per-camera isolation, reconnection with
  backoff**, and open streams **according to actual processing
  requirements**; **stagger connections** and avoid unnecessary repeated ones.
  They described our backoff and per-camera isolation as appropriate.
- **No participant-specific `/api/ingest` catalogue** will be provided;
  continue with the access mechanism issued through the hackathon resources.
- The variation we measured when many upstream RTSP connections were open at
  once comes from sandbox usage and upstream availability, and **should not be
  read as a limitation of our local bridge**.

How each point is met here:

| Guidance | Implementation |
|---|---|
| Only the streams actively required | CONTROL ROOM (Dense 6×5) holds up to 30 direct WHEP sessions; OPTIMIZED VIEW holds at most 12 near the viewport, with 600 px prefetch and release after 15 s off screen (`ui/app.js`). Both stagger opens by 400 ms and label the policy at `#media-policy`. Signalling uses our authenticated proxy; browser clients hold no Sentinel credentials. Selected AI workers use RTSP/TCP separately. The hub is on demand (`live/hub.py`); snapshots reuse hub ownership (`live/snapshot.py`). The relay is opt-in (`SAAKSHYA_LOCAL_RELAY=1`): its local government-camera cap defaults to 15 (`live/relay.py::MAX_CAMERAS`), configurable through `SAAKSHYA_RELAY_MAX_CAMERAS`; positive values slice the government list, 0 disables the cap, and own feeds are added separately. Fifteen was measured during one ramp on this machine (`reports/CLAUDE_LIVE_WALL_RESULT.md`), not a sandbox or universal bridge limit. |
| Per-camera isolation | One worker per camera (`ingest/stream.py` `StreamManager`); a camera that fails is backed off on its own and does not take the others down. |
| Reconnection with backoff | Hub `StreamConfig` starts at 2 s, multiplies by 1.8 up to 30 s, with ±30% jitter (`ingest/stream.py`). The relay publisher uses `AUTH_BACKOFF_S=300`, jittered 0.7–1.45x, after an authentication refusal; consecutive refusals double the base up to `AUTH_BREAKER_MAX_SCALE=6` (`live/relay_publisher.py`). |
| Stagger connections | Hub opens are 0.18 s apart, at start-up and on demand; browser WHEP opens 400 ms apart (`TILE_WHEP_STAGGER_MS`); relay publishers 1.25 s apart. |
| No fixed camera count | Cameras come from the registry (the onboarding portal and CSV import), never a constant; the registry/GIS plane was load-tested with 80,000 synthetic camera rows (`reports/SCALE_80K_LOAD_TEST.md`). |
| No `/api/ingest` catalogue | The camera list is probed and onboarded into the registry, and every such record says `source="probe"`. |

What we observed and reported - the grid refusing new sessions for 45-60
minutes after repeated back-to-back recordings - is consistent with variable shared availability,
not proof of a quota or a particular session-reaping mechanism, and the platform's answer to it is the one above: fewer
sessions, opened when needed, backed off when refused.

---

**Measured during a test window ≠ sandbox limit.** The sanitised point-by-point
record is [SENTINEL_SUPPORT_CLARIFICATION.md](SENTINEL_SUPPORT_CLARIFICATION.md).

## Pre-submission checklist (ours)

- [x] Every client forces RTSP over TCP.
- [x] No timing logic depends on declared FPS or on frame arrival time.
- [x] Inter-frame gaps do not crash or stall the pipeline.
- [x] Reconnect with backoff is implemented.
- [x] Decoder warnings on join are not fatal.
- [x] Camera list and per-camera properties: `/api/ingest` is not provided to participants (organisers' reply), so they come from probe + registry, labelled as such.
- [x] Only the streams actively required are open: on-demand hub, visible-tile WHEP, relay opt-in (see "Concurrent access" above).
- [x] Pipeline handles mixed H.264 / H.265 and mixed resolutions.
- [x] Behaviour is sane across a scene discontinuity.

---

## How to run against this grid

Credentials in the **process environment only**. Then:

```
make live-serve     # workspace over sqlite:///var/live.db
make live-watch     # 30-camera ingest, continuous, from the onboarded registry
```

`make live-ingest` is the shorter staged sample (5 then 10 cameras, a few
minutes). `make live-profile` re-measures capability; it now injects the same
stream credential.

Report feed problems with the camera id, the exact **redacted** URL, client and
version, UTC timestamp, and the client-side error log. Confirm live status in
the catalogue (when reachable) or in `/system/health` before reporting a camera
as down.

Support path: the integrator guide. Do not send credentials, frames, or
unredacted URLs.
