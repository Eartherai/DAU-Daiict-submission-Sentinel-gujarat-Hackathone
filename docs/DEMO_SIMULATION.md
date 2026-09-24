# Demo simulation — isolated 30-channel archival replay

An opt-in demo media plane for showing a moving 30-tile wall without a network
connection to the government grid. It is a separate, disposable relay — not a
replacement for [SENTINEL_SANDBOX.md](SENTINEL_SANDBOX.md) (the real grid) or
the local relay in `src/saakshya/live/relay.py` (`SAAKSHYA_LOCAL_RELAY`, which
re-broadcasts actual Sentinel video).

Source of truth: `src/saakshya/live/simulation.py`. Routes:
`src/saakshya/api/routes_ops.py` (`/demo-simulation/cameras`,
`/demo-simulation/status`, and the `simulation` block on `/config`) and
`src/saakshya/api/routes_investigation.py` (`/demo-simulation/cameras/{id}/whep`).
Boot/shutdown wiring: `src/saakshya/api/app.py` lifespan.

## What it is

- **Opt-in only.** Disabled unless `SAAKSHYA_DEMO_SIMULATION` is set to one of
  `1`, `true`, `yes`, `on` (`simulation.simulation_enabled()`). It also never
  starts under pytest (`PYTEST_CURRENT_TEST` short-circuits it), so running the
  test suite cannot spawn media processes.
- **30 channels, `CAM-001`..`CAM-030`.** `simulation.catalog()` returns exactly
  these 30 camera ids; `validate_catalog()` raises if the count, id set, or
  labelling drifts before any process is spawned.
- **Isolated from the government relay and the primary store.** The relay runs
  its own MediaMTX instance on dedicated ports (default RTSP `28554`, WHEP
  `28889`, API `29997`, WebRTC ICE `28890`/`28891` — all distinct from the
  government local relay's `18554`/`18889`/`19997`), configured via
  `SAAKSHYA_SIMULATION_RTSP_PORT` / `_WHEP_PORT` / `_API_PORT` /
  `_WEBRTC_UDP_PORT` / `_WEBRTC_TCP_PORT`. `boot_simulation()` never touches
  `state.store` — the catalog is a static in-memory list, not a database
  table — and `stop()` only ever terminates subprocesses this instance itself
  spawned. `tests/unit/test_simulation.py::test_catalog_import_does_not_affect_seed_50_evaluation`
  pins that importing/using the catalog leaves the 50-row evaluation store
  (`enforce_evaluation_50` / `seed_50_evaluation` in
  `src/saakshya/command/domain.py` and `src/saakshya/command/scale.py`, 30
  GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL) unaffected.

## What the video actually is

- Each channel loops one of four fixed 4-minute (240s) local H.264 assets —
  `C-014.mp4`, `C-033.mp4`, `C-052.mp4`, `C-061.mp4` under `var/media/` — via
  `ffmpeg -re -stream_loop -1 -i <asset> -c:v copy` into the dedicated
  MediaMTX. Assets are round-robined across the 30 cameras
  (`_ASSETS[(i - 1) % 4]`); there is **no unique per-camera footage**.
  `validate_catalog()` rejects any media path that is not one of these four
  approved assets, or that resolves outside the workspace, or that does not
  exist on disk.
  - **Model precision note:** `-c:v copy` remuxes the source stream without
    re-encoding — it does not "copy" the file bit-for-bit across the network.
- **The 12-hour figure is a virtual replay window, not 12 hours of unique
  recording.** `replay_start = 0`, `replay_end = 43200` (`12 * 60 * 60`),
  `asset_duration_s = 240`, `loop_period_s = 240`. The catalog carries
  `media_status = "LOOPED_4M_ASSET_NOT_12H_UNIQUE"` on every row specifically
  so no caller can read the 12h window as 12h of distinct footage.
- `current_fps` is always `None` in the catalog and in every snapshot row
  before a camera is confirmed ready — there is no frame-rate probe, and the
  code never fabricates a rate from the declared `source_fps`.

## AI / ANPR status

Every catalog row carries `analytics_capability` and `anpr_capability` set to
the literal string `NOT_MEASURED` (`simulation.NOT_MEASURED`), and
`ai_enabled: false`. This is a deliberate refusal to claim capability that
hasn't been measured — no analytics or ANPR worker is attached to this plane.
Do not report AI/ANPR results as measured for these 30 channels.

## Start / stop / test

```bash
# Start the API with the simulation plane enabled (also needs var/bin/ffmpeg
# and var/bin/mediamtx, or both on PATH — checked by simulation_binaries_ok()):
SAAKSHYA_DEMO_SIMULATION=1 make serve

# Or against the live-government serve target:
SAAKSHYA_DEMO_SIMULATION=1 make live-serve
```

The plane starts inside the FastAPI `lifespan` (`src/saakshya/api/app.py`) and
is stopped there too — killing the server process stops it; there is no
separate `make sandbox-stop`-style target for this feature (that target
belongs to the unrelated `tools/sandbox/` ANPR-evaluation replica).

Endpoints to verify state (all require an authenticated bearer token — see
`make demo` for token seeding; `/demo-simulation/cameras` and
`/demo-simulation/status` additionally require `Permission.CAMERA_READ`,
while `/config` does not gate on any specific permission beyond
authentication):

```bash
# Non-sensitive summary: enabled/available flags, catalog + ready counts.
# No port, credential, or password ever appears in this response
# (pinned by test_config_does_not_claim_simulation_or_government_browser_live).
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/config | jq .simulation

# Full 30-row catalog merged with local readiness. 503 SIMULATION_DISABLED
# when the plane isn't running on this process.
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/demo-simulation/cameras

# Snapshot: started, ready_count, publisher_count, per-camera ready state.
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/demo-simulation/status
```

Run the feature's own tests directly:

```bash
.venv/bin/python -m pytest tests/unit/test_simulation.py tests/unit/test_simulation_integration.py -q
```

## Browser replay (WHEP)

The UI's Live tab has a **LIVE SIMULATION** domain button
(`ui/index.html`, `data-live-domain="simulation"`) alongside GOVERNMENT MODE /
50-CAMERA / ALL. It is shown only when `/config` reports
`simulation.available` (the plane is running on this process). Selecting it calls
`GET /demo-simulation/cameras` (never merged with GIS/store rows — see the
comment above `loadSimulationWall` in `ui/app.js`), then opens one WHEP
session per visible tile against `POST
/demo-simulation/cameras/{camera_id}/whep`. That route
(`routes_investigation.py`) forwards the browser's SDP offer only to the
SimulationRelay's own local MediaMTX WHEP endpoint — it never reaches
Sentinel or the government relay — and returns `404` for an unknown camera id
or `503 SIMULATION_NOT_READY` if the ffmpeg publisher hasn't produced inbound
bytes yet (`SimulationRelay._has_inbound_bytes`).

## UI acceptance criteria (observable tests)

Run with `SAAKSHYA_DEMO_SIMULATION=1 make serve`, then open the workspace and
select the **LIVE SIMULATION** domain button:

1. **Provenance label is always visible.** The live-count line reads
   `... · LIVE SIMULATION / ARCHIVAL REPLAY · 12h virtual window · repeated
   4-minute assets` (`renderLiveCount` in `ui/app.js`) and survives a wall-size
   click (12/16/25/30/50/9/4) — it must not silently revert to the plain
   `N cameras · wall M` string used for non-simulation domains.
2. **Focused tile carries an `ARCHIVAL REPLAY` HUD chip and a disclosure
   line.** Opening any `CAM-0xx` tile shows a `hud-chip` reading `ARCHIVAL
   REPLAY` and the stage note: *"LIVE SIMULATION / ARCHIVAL REPLAY — a looped
   archival asset over an isolated relay, not this camera's current view."*
   (`fillLiveStage` in `ui/app.js`). It must never show the government note
   ("Timestamp is the camera's own burned-in clock.").
3. **Disabled-plane state is explicit, not a blank wall.** With
   `SAAKSHYA_DEMO_SIMULATION` unset (or the binaries missing), selecting LIVE
   SIMULATION shows the warning notice *"LIVE SIMULATION / ARCHIVAL REPLAY is
   not available here."* rather than an empty or misleadingly-live wall.
4. **30 tiles, no more, no fewer.** `GET /demo-simulation/cameras` returns
   `catalog_count: 30`; the wall's camera count matches.
5. **No fabricated FPS.** The API's `current_fps` is always `null`/absent for
   this plane, and the UI must never synthesize one from the declared
   `source_fps`; a tile's own browser-observed playback FPS (if shown after
   WHEP decode) is a separate, legitimately-measured value and is not covered
   by this restriction.
6. **`/config` never claims simulation video is browser-confirmed live** and
   never leaks `local_port` / `rtsp_port` / `whep_port` / `api_port` /
   `credential` / `password` under the `simulation` key (this is asserted
   directly by `test_config_does_not_claim_simulation_or_government_browser_live`).

## Non-claims and limitations

- **This is not a government-current feed.** It is a locally generated
  archival replay played through an isolated, self-hosted relay. No packet of
  it originates from Sentinel or any government endpoint.
- **No 12-hour soak has been certified against this plane.** The 12h figure
  is the declared virtual replay window of a 240-second looped asset, not a
  duration this feature has been run or verified for continuously.
- **No production-capacity claim.** This is a demo aid for showing a moving
  wall in a disconnected environment. It says nothing about the platform's
  throughput, concurrency, or reliability at government-grid scale — see
  [SCALE_MODEL.md](SCALE_MODEL.md) and [MEASURED_RESULTS.md](MEASURED_RESULTS.md)
  for the load and capacity evidence that actually exists, all of which is
  measured against the real grid or the 50-row evaluation store, never this
  plane.
- **No analytics or ANPR result should be attributed to these 30 channels.**
  Every row is `NOT_MEASURED` / `ai_enabled: false` by construction.
