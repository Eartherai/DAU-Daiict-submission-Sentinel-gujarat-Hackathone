# Final live production readiness

Generated 2026-09-17 04:08 IST. Operator-style pass against the live API on `127.0.0.1:8080` (`sqlite:///var/final_qa.db`).

This is **not** a claim that 30 government cameras are browser-LIVE, or that 50 tiles are government live feeds.

Labels used below: `MEASURED_REAL` · `MEASURED_OWN_FEED` · `MEASURED_SYNTHETIC` · `DESIGNED` · `NOT_MEASURED` · `EXTERNAL_DEPENDENCY`.

---

## Startup (this process)

| Check | Result |
|---|---|
| startup_time | uvicorn factory start log `2026-09-16T22:31:13Z`; `/healthz` 200 immediately after |
| backend_ready | `/readyz` 200 · `auth_required: true` · 51 cameras in store |
| frontend_ready | `/` login + workspace with cache `cr099` |
| database_ready | `final_qa.db` · LIVE CAPTURE (not demonstration store) |
| camera_service_ready | `/config` `live.whep=true` `live.proxy=true` |
| analytics_ready | store observations present; live detector FPS **NOT_MEASURED** on this API process |
| maps_ready | Google Maps loader `/maps/google-api` · key **not** published on `/config` |
| media_ready | Direct Sentinel WHEP (browser) + RTSP/TCP (AI). Proxy so the grid password never reaches the page |

---

## Exact current 30-camera result

Do not treat any single number as “the wall.” These are different experiments.

| Pass | Result | Label | Evidence |
|---|---|---|---|
| Historical 60s Direct-WHEP-all-30 | **15 visible / 11 LIVE / 0 NO_SIGNAL** | MEASURED_REAL | prior `var/reports/final/live/wall_30_60s.json` · `make final-evaluation` |
| Groups of 10 (fresh) | 1–10 **6 LIVE**; 11–20 **3 LIVE**; 21–30 **2 visible** (1 LIVE + 1 PREVIEW) | MEASURED_REAL | `reports/final_live_qa/live/coverage_groups10.json` |
| 15 historically WHEP-capable, simultaneous, conc=4, 20s | **14 LIVE / 1 WHEP_UNAVAILABLE (cam18)** | MEASURED_REAL | `reports/final_live_qa/live/coverage_direct15.json` |
| Same 15, stagger conc=1 | 9 LIVE (slower stagger missed the 20s window) | MEASURED_REAL | coverage_matrix |
| Sequential 30 (first run) | 0/30 WHEP_UNAVAILABLE | invalid | Playwright lacked `--disable-web-security` |
| Sequential 30 retry | harness hung in one `page.evaluate`; killed at ~500s | inconclusive | not used as camera fact |
| Product **12-grid**, GOVERNMENT MODE, 16s (after local fixes) | **12 of 12 showing a frame**; mix of STILL (ingest snapshot) and LIVE chips; real burned-in timestamps | MEASURED_REAL | `reports/final_live_qa/ui/12-camera_wall.png` |
| Product 16/25/30-grid in one QA cycle | tiles present; many stills; Sentinel HTTP 502/503 in console | MEASURED_REAL + test-induced fan-in | `16-camera_wall.png` `30-camera_wall.png` |

### Local vs upstream (15/30)

**Eliminated as “dashboard half empty” (local, now fixed):**

- `.product-modes` stole the 1fr workspace row (live/GIS looked empty).
- Default layout was **Focus**, so wall-size 12/16/25/30 screenshots were one hero player.
- Hidden filmstrip + tab thumbs queued **30–354** snapshot captures (`LIVE_MAX_INFLIGHT` was 30). That is a reconnect storm against Sentinel, not a wall.
- Tile WHEP attached to `display:none` grid tiles while Focus was on.
- Government cameras in the 50-eval store lacked `whep_url` on an earlier pass (already backfilled; `/config` whep true on this process).

**Not eliminated — EXTERNAL_DEPENDENCY / Sentinel:**

- Direct WHEP works concurrently for the historical 15-id set at **14/15**, not 30/30.
- Groups of 10: cam07–11, 15, 17, 21, 24–25, 27–30 stayed `WHEP_UNAVAILABLE` even with HTTP 201 on some (ICE disconnect / no first frame). That is source-side session/codec behaviour, not a missing UI tile.
- Opening 12 then 16 then 25 then 30 in one browser session produces 502/503. That historical run used a 12-session budget. Current policies are CONTROL ROOM up to 30 / OPTIMIZED VIEW at most 12, staggered 400 ms (`ui/app.js`); see `docs/SENTINEL_SUPPORT_CLARIFICATION.md`. CONTROL tiles never open a government stream.

**Honest operator wall for the demo:** GOVERNMENT MODE + Grid + wall 12 (or the 15 Direct-WHEP ids). Do not brute-force 30 extra WHEP clients.

---

## 50-camera composition (this store)

| Domain | Count | Notes |
|---|---|---|
| GOVERNMENT | 30 (`cam01`–`cam30`) | live Sentinel |
| OWN_FEED | 2 (`OWN-PEOPLE`, `OWN-TRAFFIC`) | **file replay**, not live |
| SYNTHETIC_CONTROL | 18 designed + **extra FAR fixture** | onboarded **51**, not 50 |
| Logical 50 wall | 30+2+18 plus padding slots `CTL-SLOT-*` | CONTROL must never look like GOVERNMENT |

The 50-grid screenshot shows GOVERNMENT badges on `cam*`. Empty/dark tiles are CONTROL or not-yet-captured stills — not 50 government live feeds.

---

## Designated vehicle (GJ01TA0001)

API rehearsal, supervisor token, purpose-bound headers. Artifact: `reports/final_live_qa/live/designated_vehicle.json`.

| Step | HTTP | Result |
|---|---|---|
| `/search?plate=GJ01TA0001` | 200 | `result_count` 1 · 1 candidate |
| `/watchlist` | 200 | 6 entries |
| `/alerts?status=OPEN` | 200 | 1 OPEN · OWN-TRAFFIC · stolen_vehicle · 0.83 |
| `/follow/GJ01TA0001` | 200 | timeline 3 · 1 confirmed · 2 ranked follow-ups · **1 contradiction** · score is **not** identity |
| `/trajectory/GJ01TA0001` | 200 | 1 hypothesis |
| UI TRACK | — | Investigate: FIRST SEEN OWN-TRAFFIC · trajectory **LIKELY 0.73** · **REQUIRES VERIFICATION** |

Certainty is not fabricated. Own-feed sighting is MEASURED_OWN_FEED / DEMO store, not a government ANPR hit.

---

## RBAC (existing 6 roles — not 14 fake permission sets)

| Gujarat ranks | Product role | May | Must not |
|---|---|---|---|
| DGP, Addl. DGP, IGP, DIG, SSP | SUPERVISOR | wall, search, watchlist write, investigate, evidence, audit | admin user/policy writes |
| SP, Addl. SP, DySP / ACP, PI | INVESTIGATOR | wall, search, alerts, evidence, investigation | watchlist write, statewide search, admin |
| API, PSI, ASI, HC, PC | OPERATOR | wall, health, acknowledge alerts | plate search, trajectory, evidence export, watchlist write |
| IT / estate administrator | ADMIN | users, registry, policy | vehicle search |
| oversight / audit cell | AUDITOR | audit log and camera identity | observations, evidence, search |

Rank table is on SYSTEM (below the architecture panels). Fourteen ranks are **not** fourteen products.

---

## Final acceptance table

| Area | Test | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Government cameras | 30 live census + matrix | **PASS WITH EXTERNAL DEPENDENCY** | coverage_direct15 14/15 · groups 6+3+2 · prior 15/30 @60s | 30 concurrent Direct WHEP is not available from Sentinel |
| 12 wall | visual Grid GOVERNMENT | **PASS** | `12-camera_wall.png` 12/12 frames | some tiles STILL vs LIVE; store chips can lag browser |
| 16 wall | visual | **PASS WITH EXTERNAL DEPENDENCY** | `16-camera_wall.png` | cycling walls after 12 exhausts grid (502) |
| 25 wall | visual | **PASS WITH EXTERNAL DEPENDENCY** | `25-camera_wall.png` | same |
| 30 wall | visual Grid | **KNOWN LIMITATION** | `30-camera_wall.png` + prior 15 vis/11 LIVE | do not call 30 LIVE |
| M1 registry | capability table | **PASS** | `CAMERA_HEALTH.png` 51 rows · UNKNOWN grades honest | sorts CONTROL ids first |
| M1 GIS | Google Maps | **PASS WITH EXTERNAL DEPENDENCY** | `GIS.png` map loads · registry strip cam01–24 | country zoom hides Ahmedabad markers; 1×1 canvas warning then recover |
| M2 live viewing | Grid + WHEP budget 12 | **FIXED** then **PASS WITH EXTERNAL DEPENDENCY** | app.js TILE_WHEP_BUDGET=12 · 12-wall | 30-wide Direct WHEP not supported upstream |
| M2 analytics | overlay modes present | **PASS** | FULL selected · People/Vehicles 0 store | detector FPS NOT_MEASURED |
| M2 ANPR | store marks | **PASS** | 3 marks last hour · UNKNOWN capability | ANPR accuracy NOT_MEASURED |
| M3 VMS federation | `/command/systems` 200 | **PASS** | DEMO/TEST label in SYSTEM copy | **not** 50 real departmental VMS |
| M4 intelligence | own feeds + command | **KNOWN LIMITATION** | Google Maps Ahmedabad fills the intel pane | Model-4 chrome exists in DOM; map overlay covers it in current MapView |
| Vehicle search | GJ01TA0001 | **PASS** | API result_count 1 · UI investigate | — |
| Watchlist | 6 entries + alert | **PASS** | WATCHLIST.png · API n=6 | DEMO / controlled |
| Alerting | OPEN stolen_vehicle | **PASS** | ALERT_DETAIL.png | own-feed camera |
| Tracking | TRACK button | **PASS** | TRACKING.png FIRST SEEN | LIKELY ≠ confirmed identity |
| Route | follow + trajectory | **PASS** | API timeline 3 · 1 contradiction | ROUTE button also opens GIS |
| Google Maps | loader, no key in `/config` | **PASS** | visual_qa.json maps_key_published false | loading=async warning; rotate previously exposed key |
| Evidence | jump / attach | **PASS WITH EXTERNAL DEPENDENCY** | follow.evidence_refs present | not fully click-filmed this pass |
| RBAC | rank_equivalence 5 rows | **PASS** | `/command/summary` | operator/auditor matrix not re-filmed this hour |
| Audit | `/audit?limit=8` 200 | **PASS** | chain entries n=8 | — |
| Failure recovery | API restart + one bad tile | **PASS** | healthz 200 after restart; 12-wall other tiles remain | full WHEP/RTSP kill matrix not re-run |
| 50-camera logical view | 50-grid | **PASS** | `50-camera_logical_wall.png` GOVERNMENT vs empty CONTROL | onboarded **51** (extra FAR) |
| 80k registry | certify | **PASS** | lookup P50 **0.044 ms** / P95 **0.0551 ms** · insert **0.6686 s** | unclustered 80k markers still a browser risk (DESIGNED clustering) |
| Security | secret scan + unit | **PASS** | SECRET SCAN PASS · 45 targeted tests · final-evaluation unit 0 | rotate Maps key (local pytest leak earlier, not git) |
| Visual QA | 17+ screenshots inspected | **FIXED** then mixed | `reports/final_live_qa/ui/` | Intelligence overlay; SYSTEM ranks below fold; TRACK vs GIS |

Status vocabulary: **PASS** · **PASS WITH EXTERNAL DEPENDENCY** · **KNOWN LIMITATION** · **FIXED** · **BLOCKING**.

No **BLOCKING** local defect remains for the committee path: login → operations → 12 government grid → investigate GJ01TA0001 → FIRST SEEN / LIKELY / GIS. **30 government LIVE tiles is BLOCKING only if the evaluation requires it; the upstream grid does not currently permit it.**

---

## A. Genuinely production-ready (measured)

- Auth, purpose binding, hash-chained audit.
- Google Maps via env loader; key not on `/config`.
- Designated-vehicle search → watchlist → alert → follow → trajectory with **LIKELY / REQUIRES VERIFICATION**.
- 12-camera government Grid with real frames.
- Direct WHEP for the historical 15-id set at **14 concurrent LIVE** (conc=4).
- 80k synthetic registry lookup P50 0.044 ms.
- SECRET SCAN PASS. `make final-evaluation` unit exit 0.

## B. Fixed during this run

- Shell CSS: product-modes spans the full row; live/GIS get the 1fr workspace.
- Default live layout **Grid** (Focus remains available).
- Snapshot inflight **4**, queue cap **12**, skip `CTL-SLOT-*`, do not queue hidden filmstrip/tab.
- Tile WHEP only for on-screen government tiles (getBoundingClientRect), budget 12, stagger 400 ms.
- `openLive` no longer auto-starts a hero WHEP on Grid.
- Handling strip: government / own-feed / central-analytics labels from `/config` (architecture facts, not fake LIVE counts).
- Header health chip says **(store)** so Online 0 is not mistaken for “no WHEP.”
- SYSTEM loading note; rank → role table from existing RBAC.
- Maps resize after view show; capability page actually fills.

## C. What still fails / is imperfect

- Intelligence page: Google Maps overlay covers Model-4 own-feed chrome in the current MapView (investigation GIS is usable).
- SYSTEM rank / connected-systems tables sit below the fold.
- Store `NO SIGNAL` chips can disagree with a visible STILL/LIVE frame until `markTileLive` runs.
- Onboarded **51** (FAR fixture) vs designed 50.
- Sequential 30 individual census did not complete (harness).
- Own-feed tiles on Intelligence were black in a short wait; they are file replay, not live.
- Console: many 502/503 during wall cycling (upstream busy — expected if we fan in).
- GPU, detector FPS, ANPR accuracy: **NOT_MEASURED**.

## D. Blocked by Sentinel / government upstream

- 30 concurrent Direct WHEP sessions.
- A stable subset of cam ids never produce a first frame (B-frame / session / grid busy). HTTP 201 ≠ LIVE.
- Snapshot stills 502 when the product used to open 30 parallel captures (now capped).

## E. Synthetic / control only

- 18 CONTROL (+ FAR) · 80k registry · 50 DEMO/TEST adapters · in-process event bus · own-feed file replay · watchlist GJ01TA0001 on OWN-TRAFFIC.

## F. Exact current 30-camera result

Best **measured** concurrent Direct WHEP: **14/15** of the historically capable set. Best **all-30** browser soak on file: **15 visible / 11 LIVE / 0 NO_SIGNAL** at 60s. Product 12-grid: **12/12 frames** (stills + live chips). **Not 30 LIVE.**

## G. Exact current 50-camera composition

**30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL** designed. This store: **51 onboarded**.

## H. Exact current measured performance

- 80k lookup P50 0.044 ms / P95 0.0551 ms · insert 0.6686 s (MEASURED_SYNTHETIC)
- Event bus ~2.036e6 ev/s MEASURED_IN_PROCESS
- Direct15 first frames ~2–11 s (MEASURED_REAL)
- Watchlist DETECTION→ALERT ~1.7 ms DEMO/CONTROLLED TEST (`make final-evaluation`)
- CPU / GPU / detector FPS: **NOT_MEASURED**

## I. Remaining actions before real production deployment

1. Agree the demo wall is **Grid / GOVERNMENT / 12** (or the 15 Direct-WHEP ids), and say so out loud.
2. Drop or hide the extra FAR camera so onboarded = 50.
3. Contain Google Maps on the Intelligence page so own-feed stages stay visible.
4. Persist browser LIVE/STILL onto store health without inventing STREAMING for cameras with no session.
5. Complete a sequential per-camera census with a per-camera Playwright timeout (not one 30-step evaluate).
6. **Rotate** the Google Maps key that was previously pasted into chat / leaked into a local pytest assertion. It was never committed.
7. Do not enable 30-wide WHEP against Sentinel.

---

## Security

- `SECRET SCAN: PASS (813 tracked files + full history)`
- `/config` does not publish the Maps key
- No government credentials in UI artifacts (scan refuses `AIzaSy` / `skv_` / Bearer)
- Auth remains required on this process

## Evaluation suite

`tools/verify/final_certification.py` unit exit 0 (2026-09-16T22:38Z). That report still quotes the **15/30 @ 60s** soak as Model 2’s strongest all-thirty number. This document is the operator addendum: local wall bugs were real; **30 LIVE is still not true.**
