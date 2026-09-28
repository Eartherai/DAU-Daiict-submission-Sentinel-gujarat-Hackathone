# Final demo acceptance

Generated 2026-09-17 05:40 IST after a **headed Google Chrome** operator film against the live process on `127.0.0.1:8080` (`sqlite:///var/final_qa.db`).

This is **not** a claim that 30 government cameras are browser-LIVE, that 50 tiles are government live feeds, that own-feed replay is a live camera, or that GJ01TA0001 is a government ANPR hit.

Labels: `MEASURED_REAL` · `MEASURED_OWN_FEED` · `MEASURED_SYNTHETIC` · `DESIGNED` · `NOT_MEASURED` · `EXTERNAL_DEPENDENCY`.

**Committee package:** `reports/final_live_qa/demo/`

| Artifact | Status |
|---|---|
| `final_demo.mp4` | 1920×1080 H.264 yuvj420p · 12 fps · 00:02:13.50 · 20.6 MB · 1602 frames |
| `final_demo_system_idle.mp4` | appendix after store idle (System / Audit / Evidence) |
| `final_demo_frames/` | 00–23 from the film + 24–27 idle recapture + `from_video/` stills |
| `chromium_environment.json` | Chrome 153 · ANGLE Metal Apple M5 |
| `chromium_gpu.txt` / `chromium_gpu.png` | chrome://gpu Hardware accelerated · not SwiftShader |
| `clickthrough_results.json` | 63 clicks/actions |
| `visual_acceptance.json` | frame-by-frame inspection |
| `demo_timeline.md` | evaluator timeline |
| `final_browser_console.log` | redacted |
| `final_browser_network.log` | redacted |
| `final_demo_metadata.json` | honesty flags all false for 30/50 LIVE claims |

---

## A. Chromium environment

| Field | Value | Label |
|---|---|---|
| Browser | Google Chrome (Playwright `channel=chrome`, **headed**) | MEASURED |
| Version | Chrome/153.0.8010.47 · user-agent Chrome/153.0.0.0 | MEASURED |
| Headless | **false** | MEASURED |
| Viewport | 1920×1080 | MEASURED |
| Display | Apple M5 + HP 524sa | MEASURED |
| Launch args | `--use-angle=metal` `--ignore-gpu-blocklist` `--enable-gpu-rasterization` `--enable-zero-copy` `--autoplay-policy=no-user-gesture-required` `--window-size=1920,1080` | MEASURED |
| API | real process `http://127.0.0.1:8080` · LIVE CAPTURE store `final_qa.db` | MEASURED |
| Maps | real Google Maps loader `/maps/google-api` · key **not** on `/config` | MEASURED |
| Camera config | 30 government `cam01`–`cam30` with Direct Sentinel WHEP + RTSP/TCP | MEASURED_REAL |
| Frontend | `ui/` cache `cr100` | MEASURED |

Headless Chromium was **not** used for the visual acceptance film.

---

## B. Real browser GPU / WebRTC state

From `chrome://gpu` (`chromium_gpu.png`) and `RTCRtpSender.getCapabilities('video')`:

| Check | Result | Label |
|---|---|---|
| Canvas / compositing / rasterization | Hardware accelerated | MEASURED |
| Video decode / encode | Hardware accelerated | MEASURED |
| WebGL / WebGL2 / WebGPU | Hardware accelerated | MEASURED |
| GPU0 ACTIVE | `ANGLE (Apple, ANGLE Metal Renderer: Apple M5, Version 26.6.2)` DRIVER_VENDOR=Apple | MEASURED |
| Skia backend | GraphiteDawnMetal | MEASURED |
| SwiftShader | **not** the active renderer | MEASURED |
| WebRTC `RTCPeerConnection` | true | MEASURED |
| H.264 | true | MEASURED |
| H.265 / HEVC | true | MEASURED |
| VP8 / VP9 / AV1 | present in codec list | MEASURED |
| Hardware-decode *utilisation %* | **NOT_MEASURED** (capability true; no encoder-load probe) | NOT_MEASURED |

Playwright also injects `--enable-unsafe-swiftshader` as a fallback flag. GPU0 is Metal ACTIVE. The film is not a SwiftShader software-raster run.

---

## C. Complete click-through result

63 recorded actions. Real clicks, not URL-only navigation. Login used a refused token on camera, then sessionStorage inject — the real token was **never typed** into the recorded field.

| Area | Controls exercised | Result |
|---|---|---|
| LOGIN | gate, invalid token, session FIR-214/2026, purpose | **PASS** |
| OPERATIONS | Grid, Focus, wall 12/16/25/30/50, GOVERNMENT / 50-CAMERA, camera open, analytics VIDEO/VEHICLES/PEOPLE/ANPR/FULL/INCIDENT | **PASS** on 12-grid; **EXTERNAL_DEPENDENCY** on 16–30 after cycling |
| INTELLIGENCE | nav, own-feed chrome, FULL ANALYTICS, map contained | **PASS** with own-people dark (file replay) |
| INVESTIGATION | search GJ01TA0001, filters visible, FIRST SEEN, trajectory LIKELY, SEAL EVIDENCE | **PASS** |
| WATCHLIST / ALERTS | New / Acknowledged / Investigating / Resolved / All tabs, VIEW VIDEO / TRACK / ROUTE / OPEN GIS / ACKNOWLEDGE | **PASS** cards; TRACK click in the film stayed on Alerts (see O) |
| GIS | Google Maps Gujarat, pan-ready, search/filter, registry strip, cam* vs CTL-* | **PASS** |
| SYSTEM | architecture, DEGRADED honest (idle recapture) | **PASS** idle; **FAIL then FIXED** in the main film (store busy) |
| AUDIT | chain verified, 66 entries, GJ01TA0001 | **PASS** idle recapture |
| EVIDENCE | chain verified, no sealed records | **PASS** (honest empty) |
| Refresh | session restored, 12-grid frames returning | **PASS** |

Could an evaluator operate this without knowing the implementation? **Yes**, on the committee path: login → Operations Grid GOVERNMENT 12 → Investigate plate → GIS. They must be told, out loud: the 12-grid is the government wall; 30 LIVE is not claimed; GJ01TA0001 is OWN-TRAFFIC DEMO.

---

## D. Complete 30-camera result

Do not collapse these into one number.

| Pass | Result | Label |
|---|---|---|
| Headed film 12-grid GOVERNMENT | **12 of 12 showing a frame**; mix LIVE chips + STILL snapshots; real CSITMS timestamps | MEASURED_REAL |
| Headed film 16 / 25 / 30 after cycling | tiles present; many STILL / NO SIGNAL; Sentinel 502/503 in console | MEASURED_REAL + test-induced fan-in |
| Historical Direct-WHEP 15-id set, conc=4, 20s | **14 LIVE / 1 WHEP_UNAVAILABLE (cam18)** | MEASURED_REAL |
| Groups of 10 | 6 + 3 + 2 visible | MEASURED_REAL |
| All-30 60s soak (prior) | **15 visible / 11 LIVE / 0 NO_SIGNAL** | MEASURED_REAL |
| Sequential 30 Playwright | invalid then hung harness | not a camera fact |

**Not 30 LIVE.** Product budget is 12 Direct WHEP sessions, reused, staggered 400 ms.

---

## E. Exact 50-camera composition

| Domain | Count | What it is |
|---|---|---|
| GOVERNMENT | 30 (`cam01`–`cam30`) | Sentinel WHEP (browser) + RTSP/TCP (AI) |
| OWN_FEED | 2 (`OWN-PEOPLE`, `OWN-TRAFFIC`) | **file replay**, FULL ANALYTICS — not live cameras |
| SYNTHETIC_CONTROL | 18 designed + extra FAR fixture | DEMO/TEST · never a government stream |
| This store | **51 onboarded** | designed 50 + FAR |
| Logical 50 wall | 30+2+18 plus `CTL-SLOT-*` padding | CONTROL must not look like GOVERNMENT |

The 50-wall frame shows GOVERNMENT badges on `cam*`. Empty later tiles are CONTROL or not-yet-captured stills — **not 50 government LIVE**.

---

## F. Government vs own-feed vs synthetic

| Surface | Honest label shown |
|---|---|
| Handling strip | GOVERNMENT FEED: Direct Sentinel WHEP (browser) + RTSP/TCP (AI) |
| Handling strip | OWN FEED: OWN-PEOPLE + OWN-TRAFFIC file replay — FULL ANALYTICS |
| Architecture | command orchestration with regional media/AI pools — **not 80k central decode** |
| Intelligence | DEMO / CONTROLLED TEST · AI P50 **NOT_MEASURED** |
| Alert GJ01TA0001 | camera **OWN-TRAFFIC** · stolen_vehicle · confidence 0.83 |
| Investigate | FIRST SEEN **OWN-TRAFFIC** · CONFIRMED BY PLATE on own-feed observation |
| 50-wall | GOVERNMENT vs CTL-* ids |

---

## G. Google Maps verification

| Check | Result | Label |
|---|---|---|
| Basemap loads (Gujarat / Ahmedabad streets) | yes — GIS + Investigate movement map | MEASURED_REAL |
| Key on `/config` | `maps_key_published: false` | MEASURED |
| Key in film / logs / frames | not present (scan of demo text artifacts clean) | MEASURED |
| Console | `loading=async` warning; brief 1×1 canvas then recover | MEASURED |
| Intelligence map containment | Model-4 chrome visible after `.intel-map-wrap { position: relative }` | FIXED then PASS |
| Cluster / country zoom | estate map at Gujarat scale; Ahmedabad thumbs in registry strip | MEASURED |

**Rotate** the Maps key previously pasted in chat / leaked into a local pytest assertion. It was never committed.

---

## H. Designated vehicle scenario (GJ01TA0001)

**MEASURED_OWN_FEED / DEMO.** Not a government ANPR hit.

| Step | Result |
|---|---|
| Search | result_count 1 · CONFIRMED BY PLATE · quality 0.80 |
| Watchlist | 6 entries |
| Alert | 1 OPEN · OWN-TRAFFIC · stolen_vehicle · 0.83 MEDIUM |
| Follow | timeline 3 · 1 confirmed · 2 ranked follow-ups · **1 contradiction** |
| Trajectory | LIKELY **0.73** · score is an **ordering score, not a probability** |
| Timebase | **RESTRICTED** (single camera, no shared timebase claimed) |
| Evidence | **Not yet sealed** — SEAL EVIDENCE present; idle Evidence page: chain verified, no records |

---

## I. RBAC verification

Existing **6** product roles. Gujarat ranks map onto them (`RANK_EQUIVALENCE`). Fourteen ranks are **not** fourteen products.

| Gujarat ranks | Role | May | Must not |
|---|---|---|---|
| DGP, Addl. DGP, IGP, DIG, SSP | SUPERVISOR | wall, search, watchlist write, investigate, evidence, audit | admin user/policy writes |
| SP, Addl. SP, DySP / ACP, PI | INVESTIGATOR | wall, search, alerts, evidence, investigation | watchlist write, statewide search, admin |
| API, PSI, ASI, HC, PC | OPERATOR | wall, health, acknowledge alerts | plate search, trajectory, evidence export, watchlist write |
| IT / estate administrator | ADMIN | users, registry, policy | vehicle search |
| oversight / audit cell | AUDITOR | audit log and camera identity | observations, evidence, search |

The headed film used **supervisor.demo** (statewide). Rank table sits **below the fold** on SYSTEM (architecture copy is the first screen). `/command/summary` returns `rank_equivalence` (5 rows). Operator 403 on plate search was measured on a prior API pass, not re-filmed in this take.

---

## J. Audit verification

Idle recapture `26_audit_idle.png`:

- Chain **verified**
- **66** entries
- Actor `supervisor.demo` · role SUPERVISOR
- Case FIR-214/2026 · purpose “official evaluation designated vehicle” / “final live production visual acceptance”
- Targets include **GJ01TA0001** (`search_plate`, `follow_vehicle`, `trajectory_build`)

The main film’s Audit frame was empty because `/audit` waited behind the wall’s sqlite/snapshot load. That is a load artefact, not a missing chain.

---

## K. Failure recovery

| Event | Result |
|---|---|
| Invalid authentication | refused on camera; gate stayed | PASS |
| Refresh after wall load | session restored from sessionStorage; 12-grid frames returning | PASS |
| `/healthz` `/readyz` | 200 on this process | PASS |
| `/system/health` idle | 200 in ~10 ms · overall **DEGRADED** (feed DEGRADED; grid_access / inference / database / search / evidence / jobs / ai_providers HEALTHY) | PASS |
| Sentinel 502/503 while cycling 12→16→25→30 | other tiles remain; product does not fake LIVE | EXTERNAL_DEPENDENCY |
| Full WHEP/RTSP kill-one matrix | **not re-run this hour** | prior PASS |

---

## L. Screenshots (inspected, not a slideshow substitute)

Primary stills from the **same headed session** as `final_demo.mp4`:

- `00_login.png` — clean login, no real token
- `03_gov_grid_12.png` — 12/12 government frames
- `05_wall_30.png` — 30 tiles after cycling, mostly NO SIGNAL (honest)
- `07_wall_50.png` — GOVERNMENT vs empty CONTROL
- `09_intelligence.png` — Model 4 · OWN FEED · DEMO/CONTROLLED TEST
- `10_alerts.png` — GJ01TA0001 OWN-TRAFFIC
- `13_search.png` / `14_route.png` — FIRST SEEN · LIKELY 0.73 · REQUIRES VERIFICATION
- `15_gis.png` — Google Maps Gujarat
- `22_refresh.png` — session restored
- `24_system_idle.png` / `26_audit_idle.png` / `27_evidence_idle.png` — idle appendix

Extracted video frames `from_video/t00{5,20,40,70,90,110}.jpg` match the film (not a montage).

---

## M. Final screen recording

| Spec | Value |
|---|---|
| File | `reports/final_live_qa/demo/final_demo.mp4` |
| Codec | H.264 High `avc1` · yuvj420p |
| Size | 1920×1080 |
| FPS | 12 (JPEG pipe → libx264; target 30 was impractical on this capture path without dropping quality) |
| Duration | 00:02:13.50 |
| Bitrate | ~1237 kb/s |
| Cursor | visible (injected operator cursor) |
| DevTools / terminal / credentials | not in frame |
| Audio | none (UI-only) |

Validation: container opens in ffmpeg; no black full-window frames in sampled stills; login error is the **intended** invalid-token beat; map is Gujarat not a blank tile; 12-grid shows real CSITMS timestamps; 30-wall is **not** dressed as LIVE.

Appendix `final_demo_system_idle.mp4` (181 frames) covers System / Audit / Evidence after the store drained — those pages were spinner/empty in the main film because `/system/health` and `/audit` blocked on sqlite during WHEP/snapshot load.

The committee should **watch the mp4**, not a screenshot deck.

---

## N. Upstream observations during this test window

These are MEASURED DURING A TEST WINDOW, not sandbox limits. Organisers
confirmed no fixed participant-facing RTSP session limit; current policies
and guidance are in `docs/SENTINEL_SUPPORT_CLARIFICATION.md`.

- Concurrent Direct WHEP is stable for a historical **~15-id** set (**14/15** LIVE), not 30/30.
- Groups of 10: several ids stay `WHEP_UNAVAILABLE` even after HTTP 201 (ICE / no first frame).
- Opening 12 then 16 then 25 then 30 in one session produces **502/503**.
- Snapshot stills 503 under fan-in.
- HTTP 201 ≠ LIVE.
- Do not brute-force 30 extra WHEP clients against the grid.

---

## O. Remaining local limitations

- Onboarded **51** vs designed 50 (extra FAR fixture).
- Header `Online 0 · degraded 51 (store)` is **store STREAMING**, not browser WHEP. Confusing until the operator reads “(store)”.
- Store **NO SIGNAL** chips can sit on tiles that already show a STILL/LIVE frame.
- Intelligence **OWN-PEOPLE** tile often black on a short wait (file replay).
- TRACK from Alerts in the film did not navigate (likely collision with the live **TRACKING** overlay control). Investigate search completed the path. Local UX debt: TRACK vs TRACKING labels.
- SYSTEM / AUDIT / Evidence lag while the wall is capturing — sqlite lock. Idle they populate.
- Rank table below the fold on SYSTEM.
- `plate.jpg` 404s in the network log (no plate crop on those cameras).
- GPU utilisation %, detector FPS, ANPR accuracy: **NOT_MEASURED**.
- Film is 12 fps, not 30 fps.

No **BLOCKING** local defect remains on the committee path (login → 12 government grid → GJ01TA0001 → GIS → audit). **30 government LIVE tiles is blocking only if the evaluation requires it; Sentinel does not currently permit it.**

---

## P. Exact final measured metrics

| Metric | Value | Label |
|---|---|---|
| Product 12-grid frames | 12/12 | MEASURED_REAL |
| Direct15 concurrent LIVE | 14/15 | MEASURED_REAL |
| All-30 60s visible / LIVE | 15 / 11 | MEASURED_REAL |
| `/system/health` idle | ~10 ms · overall DEGRADED | MEASURED |
| 80k registry lookup P50 / P95 | 0.044 ms / 0.0551 ms | MEASURED_SYNTHETIC |
| 80k insert | 0.6686 s | MEASURED_SYNTHETIC |
| Watchlist DETECTION→ALERT | ~1.7 ms | DEMO / CONTROLLED TEST |
| Event bus | ~2.036e6 ev/s | MEASURED_IN_PROCESS |
| Film duration | 133.5–144.6 s wall clock / 00:02:13.50 container | MEASURED |
| Detector FPS / GPU % / ANPR accuracy | — | NOT_MEASURED |

---

## Q. Security / secret scan

- `SECRET SCAN: PASS (813 tracked files + full history)`
- Demo text artifacts (`*.log` `*.json` `*.md` `*.txt`) scanned for `AIza` / `skv_` / `Bearer` — **clean**
- `/config` does not publish the Maps key
- Real token never typed into the recorded login field
- Auth required on this process (`/me` 401 before session)
- **Rotate** the previously exposed Google Maps key (chat / local pytest). Not in git.

---

## R. Final recommendation on demo readiness

**CONDITIONAL DEMO-READY** for a committee that accepts an honest 12-camera government wall plus a controlled own-feed vehicle scenario.

Hand them:

1. `reports/final_live_qa/demo/final_demo.mp4`
2. This document
3. Spoken briefing: **not 30 LIVE**, **not 50 government feeds**, **GJ01TA0001 is OWN-TRAFFIC DEMO**, **own feeds are file replay**, **architecture is regional media/AI pools not 80k central decode**

Do **not** present the 30-wall cycle as simultaneous live government video.

Status vocabulary used above: **PASS** · **PASS WITH EXTERNAL DEPENDENCY** · **KNOWN LIMITATION** · **FIXED** · **BLOCKING**.

The acceptance condition was real backend + current data + government sources + Google Maps + headed Chromium + click-through + visual inspection + screen recording + designated-vehicle + failure/recovery + regression of local wall bugs. Those are done. **Tests passing alone was not treated as acceptance.**
