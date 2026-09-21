# Final live production certification

Timestamp UTC: `2026-09-16T21:45:52Z` (government walls) / `2026-09-16T21:46:59Z` (UI/maps config).

Architecture unchanged: Direct Sentinel WHEP (browser) · RTSP/TCP AI · VideoToolbox bridge when used · adaptive scheduler · M1 registry/GIS · M2 unified viewing · M3 federation · M4 intelligence surfaces.

## A. Fresh live measurements (MEASURED_REAL)

Sentinel TCP 8554 and 8889 reachable. Catalogue session cookie absent → camera set is `DISCOVERED_NOT_CATALOGUE` (cam01–cam30 probe), not an authenticated `cameras.json`.

RTSP census (one attempt per camera, no gateway publish): **14 / 30 RTSP-live** with decoded frames. Concurrent probes produced `TCP_8554` / `DESCRIBE_AUTH` / `PYAV_NO_FRAME` on the remainder — those are not called NO_SIGNAL when a later WHEP plane is live.

Direct Sentinel WHEP headed Metal walls (Authorization header only; no credentials in URLs/JSON):

| Layout | Soak | Browser visible | LIVE | PREVIEW | RTSP_ONLY_AI | NO_SIGNAL | DEGRADED | First-frame P50 / P95 ms | Overall |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 12 | 30 s | 9 | 8 | 1 | 0 | 1 | 2 | 3501 / 24461 | AMBER |
| 16 | 30 s | 13 | 8 | 5 | 0 | 1 | 2 | 22264 / 27147 | AMBER |
| 25 | 30 s | 11 | 5 | 6 | 6 | 2 | 6 | 23711 / 29482 | AMBER |
| 30 | 30 s | 10 | 5 | 5 | 11 | 4 | 5 | 22159 / 27404 | AMBER |
| 30 | 60 s | **15** | **11** | 4 | 6 | **0** | 9 | 25954 / 52119 | AMBER |

Best fresh 30-camera result: **15 browser-visible, 11 LIVE, 4 PREVIEW, 6 RTSP_ONLY_AI, 0 NO_SIGNAL** at 60 s. GPU utilization **NOT_MEASURED** (Metal renderer string present). Promotion P50/P95 **NOT_MEASURED** (this wall does not run the adaptive scheduler clock). 120 s soak **not repeated this run**; prior Phase 16 120 s remains 19 visible / 8 LIVE / 11 PREVIEW.

JSON: `var/reports/final/live/census.json`, `wall_{12,16,25,30}_{30,60}s.json`.

## B. Model 1

80k synthetic SQLite registry (MEASURED_SYNTHETIC, `make final-evaluation`): insert **0.7086 s**; lookup P50/P95 **0.0454 / 0.0592 ms**; search **0.1485 / 0.1608 ms**; filter **3.4228 / 3.7872 ms**; page-50 **0.1563 / 0.169 ms**.

GIS 80k: cluster zoom6 **39.875 ms**, **18** groups, map layer **227.939 ms**, returned_features **6**, max_features **1500**. 80k markers are not sent to the browser.

50-logical store: **30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL**, onboarded **50**.

JSON: `var/reports/final/models/m1_80k_registry.json`, `m1_80k_gis.json`, `m1_50_logical.json`.

## C. Model 2

Overlay mode matrix (VIDEO / VEHICLES / PEOPLE / BOTH / ANPR / FULL / INCIDENT): `duplicate_whep: false` for every mode. Overlay is store metadata on the same video element.

JSON: `var/reports/final/models/m2_overlay_modes.json`.

## D. Model 3

50 DEMO/TEST adapters: kill-one **49/49 alive**, kill-10% **45/45 alive**. Event bus **1,868,373 ev/s** MEASURED_IN_PROCESS — not Kafka. Reconnect to a real departmental VMS is **EXTERNAL_DEPENDENCY**.

JSON: `var/reports/final/models/m3_adapters_50.json`, `m3_bus.json`.

## E. Model 4

OWN-PEOPLE / OWN-TRAFFIC are **local file replay** (not live streams): 1.mp4 29.1 s 1080p30; 2.mp4 762.5 s 1080p12.

| Feed | First decode frame | Seek to ~10 s PTS | Detections (12 frames) | Detector FPS |
|---|---|---|---|---|
| OWN-PEOPLE | 16.86 ms | 1255.2 ms (landed 9.93 s) | people 0 · vehicles 0 | NOT_MEASURED |
| OWN-TRAFFIC | 9.7 ms | 94.8 ms (landed 10.0 s) | people 0 · vehicles 0 | NOT_MEASURED |

Watchlist DEMO/CONTROLLED TEST plate `GJ01TA0001`: DETECTION→ALERT **1.888 ms** (`make final-evaluation` fixture; not pixels).

Contradiction example: **173.46 km in 2.0 s**, minimum plausible **3122.3 s**.

JSON: `var/reports/final/models/m4_own_feeds.json`, `m4_watchlist.json`, `m4_investigation.json`, `m4_isolation.json`.

## F. 30-camera live wall

AMBER, not a global failure. 60 s soak: 15 visible, 0 NO_SIGNAL. Failed/weak WHEP tiles were **not** replaced with synthetic in GOVERNMENT mode.

## G. 50-camera logical

PASS as composition. CONTROL slots are labelled SYNTHETIC_CONTROL / CONTROL — never GOVERNMENT.

## H. Google Maps

`GOOGLE_MAPS_API_KEY` loaded from gitignored `.env.local` (alias `SAAKSHYA_GOOGLE_MAPS_KEY` still accepted). `/config` publishes `google.enabled` + `loader: /maps/google-api` and **does not publish the key**. Loader HTTP **302**. Raster OSM tiles remain the fallback. Canvas overlays still draw markers, clusters, alerts, FIRST SEEN → NEXT → LAST SEEN.

## I. Full demo

Judge path in `reports/FINAL_DEMO_RUNBOOK.md`. Product JS syntax error on Alerts (extra `)`) was fixed so the signed-in shell loads. Handling-strip overflow CSS tightened.

## J. Visual QA

See `reports/FINAL_VISUAL_QA.md` and `reports/FINAL_VISUAL_ACCEPTANCE.md`. LOGIN PASS. Other product surfaces AMBER (overflow / sparse live tiles in the 1440×900 capture). Not declared perfect.

## K. Remaining blockers

1. Authenticated Sentinel catalogue (`SENTINEL_GRID_COOKIE`) still EXTERNAL_DEPENDENCY.
2. Fresh 30-camera browser-visible count is **15** at 60 s (not 30 LIVE). Do not claim 30 government live tiles.
3. 120 s wall not re-soaked this run.
4. Own-feed 12-frame AI emitted **0** boxes — DETECTIONS = 0, DETECTOR FPS = NOT_MEASURED.
5. GPU utilization NOT_MEASURED.
6. No real departmental VMS.
7. Product live wall on the demo store shows registry stills, not the headed Sentinel WHEP wall.
8. Integration/e2e tests that open `var/media/C-047.mp4` error (`Invalid data`); not a Sentinel media-path change. Do not claim those tests passed this run.
9. Rotate the Google Maps key: a pytest assertion previously dumped the configured value into a local terminal log. The key is not in git. Tests now isolate Maps env and do not print the value.

## L. Judge-safe claims

- Centralized analytics and command orchestration with regional media/AI pools.
- Real government Direct WHEP wall ran without a global failure; best fresh 30-cam 60 s: 15 visible, 11 LIVE, 0 NO_SIGNAL.
- M1 80k registry/GIS measured synthetic, clustered, max 1500 features.
- M2 overlay modes do not open a second WHEP.
- M3 50-adapter isolation DEMO/TEST.
- M4 own-feed is file replay; watchlist workflow is DEMO/CONTROLLED TEST.
- Alert → Video → Track → Route → GIS → Evidence is implemented; contradiction shows distance / elapsed / minimum travel.
- Google Maps loads when the env key is present; the key is not in git, `/config`, or reports.
- 50-camera mode is 30+2+18.
- SECRET SCAN and `make final-evaluation` are the gates.

Do not say: 50 government live feeds, 80k central decode, Kafka measured, GPU 0%, ANPR accuracy, invented detections.
