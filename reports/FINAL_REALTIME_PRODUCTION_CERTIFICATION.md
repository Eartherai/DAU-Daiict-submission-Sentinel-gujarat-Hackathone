# FINAL REAL-TIME PRODUCTION CERTIFICATION

Generated 2026-09-17 after the local video-relay upgrade. Labels below are the only ones used.

This certifies **what was measured**. JPEG polling is no longer the product video plane. **30/30 browser LIVE was not achieved.** Peak measured browser video was **25/30** playing WebRTC tiles. Do not read 27/30 relay-ready or 25/30 playing as 30/30.

---

## A. Media architecture

**DESIGNED and MEASURED_REAL as the product plane:**

```
Sentinel RTSP/TCP
        |  ONE ffmpeg publisher / camera
        v
Local MediaMTX  (RTSP :18554, WHEP :18889)
        |-- WHEP  → browser tiles (same-origin `/cameras/{id}/whep`)
        |-- RTSP  → isolated AI worker
        `-- JPEG  → PREVIEW fallback only
```

Browser consumes **local WHEP**, not Sentinel WHEP. `/config` `live.plane=local_relay`, `whep=true`, `proxy=true`, `hub=false`.

Copy remux is not the government default. PHASE15 **MEASURED_REAL:** MediaMTX WebRTC rejects H264 B-frames. Government cameras transcode VideoToolbox H264 baseline `-bf 0`. Own-feeds try copy first.

Key files: `src/saakshya/live/relay.py`, `src/saakshya/analytics/worker.py`, `src/saakshya/api/routes_investigation.py` (local WHEP proxy), `ui/app.js` (`localRelay()`).

**EXTERNAL_DEPENDENCY:** Sentinel RTSP `:8554`. When it refuses, SOURCE leaves CONNECTED. VIDEO LIVE is not stamped from registry presence.

JPEG hub (`MediaHub`) remains in-tree as a non-default fallback (`SAAKSHYA_LOCAL_RELAY=0`). It is **not** the live transport of this certification.

---

## B. Upstream session count

**MEASURED_REAL** (after ~10 min soak, `GET /media/hub`):

| Snapshot | Upstream publishers | SOURCE CONNECTED | Government CONNECTED |
|---|---:|---:|---:|
| Early boot +147 s | 32 | 31 | 29 |
| During 30-wall measure | 32 | 30 | 28 |
| After layout remeasure +582 s | 32 | 29 | 27 |
| After AI kill | 32 | 29 | 27 |

Target for 30 government cameras is **30** upstream sessions. Peak government connected this run: **29/30**. Missing cameras were `cam19` / `cam23` (RECONNECTING / path not ready) — Sentinel-side, not extra browser sessions.

Process count: **31 ffmpeg** publishers + **1 MediaMTX**. Not 30 upstream + N Sentinel WHEP.

---

## C. Local relay count

**MEASURED_REAL:** MediaMTX `/v3/paths/list` peaked at **32/32 ready** shortly after boot. Later soak: **28/32 ready**. Own-feeds stayed up (`OWN-PEOPLE`, `OWN-TRAFFIC`).

Relay ports: RTSP `127.0.0.1:18554`, WHEP `127.0.0.1:18889`, API `127.0.0.1:19997`. No credentials on those URLs.

---

## D. Browser stream count

**MEASURED_REAL** Playwright Chromium, wall=30, government domain, `video.tile-whep` with `readyState>=2` and `videoWidth>0`:

| Run | video elements | playing | LIVE chips |
|---|---:|---:|---:|
| 1 (plates still on page) | 24 | **23** | 21 |
| 2 (30-wall fills video; plates hidden) | 27 | **25** | 25 |

Not 30/30. Tiles that were not playing showed CONNECTING, RECONNECTING, PREVIEW, or “grid busy” JPEG fallback.

Screenshot: `reports/final_live_qa/relay_wall_30.png`.

---

## E. 30-camera live result

**NOT 30/30.**

Honest result: **25/30 continuous local WebRTC video** at the measured snapshot, with **27/30 government SOURCE CONNECTED** on the relay. Several tiles were real 1920×1080 night road video, not JPEG animation.

Remaining bottleneck (precise):

1. **2–3 government upstreams** not CONNECTED (Sentinel RTSP drop / reconnect).
2. **VideoToolbox 1080p × ~30** on this Mac: ~74% ffmpeg CPU, ~5.1 GiB ffmpeg RSS. Browser WHEP negotiation clustered late (~30–38 s after page open in run 2).
3. Tiles without WHEP fall back to JPEG PREVIEW / “grid busy” — correctly **not** labelled LIVE from a stale still.

---

## F. FPS per camera

**NOT_MEASURED** as a per-tile WebRTC `framesPerSecond` table in the 30-wall run (the wall script counted playing elements, not inbound-rtp FPS).

Relay ffprobe of local output is **NOT_MEASURED** for every camera this pass; capability file records READY/NOT_READY only.

AI detector FPS on `OWN-TRAFFIC`: **2.48** **MEASURED_REAL** (`var/run/ai_worker.json`). Dropped frames 1229 vs analysed 1204 — latest-frame-wins is working (stale frames skipped).

Do not invent wall FPS. Do not call the old 4.6 JPEG cadence live video.

---

## G. Latency

**Relay path ready (ingest → MediaMTX ready), MEASURED_REAL** first-ready ms sample: 3182, 3635, 4417, 4472, 4588, 6546, 9138, 9599. That is publisher warmup, not browser first frame.

**Browser first observed decoded frame** (page-open clock, run 2): p50 **36.5 s**, p95 **37.5 s**. This is **not** WHEP negotiation time alone — samples stayed at 0–1 video elements until ~t=32 s, then 25 appeared together. Likely decoder/ICE bunching under 30 concurrent 1080p encodes.

Warm WHEP first-frame from PHASE16 on a pre-warmed single path was **35.75 ms**. That number is **not** this 30-wall.

End-to-end LIVE LATENCY from source PTS: **TIMEBASE LIMITED / NOT_MEASURED**. `video.currentTime` on MediaMTX WHEP tracks media time, not one-way delay.

---

## H. Drops

**MEASURED_REAL (AI worker):** 1229 dropped vs 1204 processed on `OWN-TRAFFIC` (queue depth 2, drop-oldest).

**Browser dropped frames:** NOT_MEASURED (no inbound-rtp table in the 30-wall script).

**Upstream reconnects:** `cam19` reconnects≥1 **MEASURED_REAL**.

---

## I. Reconnects

Government cameras that left CONNECTED: `cam19`, `cam23` (and later one UPSTREAM_ERROR). Relay supervisor restarts ffmpeg with backoff. **MEASURED_REAL** at the SOURCE plane. Browser PC reconnect count: NOT_MEASURED.

---

## J. AI result

**MEASURED_OWN_FEED:** isolated worker on `OWN-TRAFFIC` only (`SAAKSHYA_AI_CAMERAS` default). Heartbeat `ai=ACTIVE`, `frames=1204`, `last_ms≈362`.

SQLite observations written this session include `object_type=car` and `bus` on `OWN-TRAFFIC` with null plates.

**ANPR:** `anpr=UNAVAILABLE` on that source this run. Not faked.

**Watchlist → alert this worker:** no plate, so no new match. Store has 1 OPEN alert `GJ38BH5815` on `cam21` from **earlier** capture — **NOT** claimed as this worker’s live alert.

**Bounding boxes:** `var/run/ai_boxes/OWN-TRAFFIC.json` was empty at the inspect snapshot (no active tracks at that instant). Observations still prove detection ran.

---

## K. Detector FPS

**MEASURED_OWN_FEED:** 2.48 FPS on one selected stream. Not 30-camera AI. Scale 1/4/8/12/16/30: **NOT_MEASURED**. Production strategy this run: **SELECTIVE AI**. UI shows `AI ACTIVE` only on worker cameras; others `AI OFF`.

---

## L. GPU

ffmpeg **h264_videotoolbox** is in use (**MEASURED_REAL** encoder logs: `h264_videotoolbox` / MPEG range). Host GPU utilisation %: **NOT_MEASURED**. Headed Chrome Metal probe: **NOT_MEASURED** this pass (Playwright Chromium launched with `--use-angle=metal` but headless).

ffmpeg RSS ~5.1 GiB for 31 publishers **MEASURED_REAL**.

---

## M. ANPR

**UNAVAILABLE** on `OWN-TRAFFIC` this run (heartbeat). No plate published from the isolated worker. Do not treat gallery plates on the first screenshot as live ANPR — those are existing store marks.

---

## N. Alert latency

**NOT_MEASURED** for this worker (no plate match). Existing alert in store is prior data.

---

## O. Control-plane latency

Under relay ingest, **MEASURED_REAL** (`tools/hub_api_under_load.py`, ADMIN token):

| Path | HTTP | p50 | p95 |
|---|---:|---:|---:|
| `/healthz` | 200 | 2.0 ms | 3.8 ms |
| `/readyz` | 200 | 3.3 ms | 3.4 ms |
| `/system/health` | 200 | 22.5 ms | 23.9 ms |
| `/audit?limit=20` | 200 | 9.3 ms | 10.1 ms |
| `/search?plate=GJ01TA0001` | 403 | 3.2 ms | 3.3 ms |
| `/alerts?limit=20` | 403 | 2.9 ms | 3.2 ms |
| `/command/summary` | 200 | 5073 ms | 5450 ms |

ADMIN 403 on search/alerts is **RBAC**, not a media outage. Investigator token: `/search?plate=GJ01TA0001` **200** (~2.8 KB), `/alerts` **200**. **MEASURED_REAL**.

`/command/summary` is the slow control-plane path under ingest (seconds). Health/audit stay milliseconds. MEDIA LOAD MUST NOT BLOCK THE CONTROL PLANE — **partially met** (healthz yes, summary no).

Later `/command/summary` 812 ms **MEASURED_REAL**.

---

## P. Failure recovery

**MEASURED_REAL:** SIGTERM on the AI worker PID. `/healthz` stayed **200**. Relay stayed `local_relay` with 29 SOURCE CONNECTED / 27 government LIVE. MediaMTX paths still ready. Video plane did not restart.

AI worker restart-while-wall-stays-live as a supervised loop: **DESIGNED**, restarter not proven beyond the deferred 12 s boot.

One-camera AI crash isolation: worker is one process for selected cameras; a per-camera subprocess is **DESIGNED / NOT_MEASURED**.

---

## Q. Chromium validation

**MEASURED_REAL:** Playwright Chromium, 1920×1080, `--use-angle=metal`, autoplay allowed, real `video.tile-whep` pixels (see screenshot).

**NOT_MEASURED:** headed Google Chrome click-through of Operations / 12 / 16 / 25 / 30 / Intelligence / GIS / Evidence / System / Audit / Track Vehicle / OWN-PEOPLE replay.

---

## R. Screen recording

**NOT_MEASURED.** The previous 12 FPS demo is obsolete. A new 1920×1080 30 FPS H264 headed film was **not** produced in this pass. Do not reuse the old file as this architecture’s evidence.

---

## S. Google Maps

**EXTERNAL_DEPENDENCY / NOT_MEASURED** this pass. Key remains env-only.

---

## T. GJ01TA0001

Investigator search **200** **MEASURED_REAL**. Not a live-wall detection.

---

## U. RBAC

**MEASURED_REAL:** ADMIN search/alerts 403; INVESTIGATOR 200. Auth required. Tokens are live-db hashes, not demo-store leftovers.

---

## V. Audit

`/audit?limit=20` **200**, p50 9.3 ms under ingest **MEASURED_REAL**. Full Audit UI while 30-wall is headed: **NOT_MEASURED**.

---

## W. Evidence

UI Evidence while wall running: **NOT_MEASURED** this pass. Snapshot path does not open a second Sentinel RTSP while the relay owns the camera **DESIGNED** (`SnapshotService.get`).

---

## X. Security

- Sentinel credentials stay in ffmpeg argv / process env, never in `/config`, WHEP URLs, or reports.
- Local WHEP proxy posts SDP to loopback MediaMTX **without** Basic auth.
- Maps key env-only.
- No auth disable.

**MEASURED_REAL** that `/config` contains plane/whep flags and no password.

---

## Capability table (passthrough vs transcode)

From `var/run/relay_capability.json` after soak:

| Class | Count | Label |
|---|---:|---|
| Government transcode READY | 27 | MEASURED_REAL |
| Government transcode NOT_READY | 3 | MEASURED_REAL |
| Own-feed copy READY | 2 | MEASURED_OWN_FEED |
| HEVC (`cam17`, `cam22`) transcode | 2 | MEASURED_REAL |

Not all 30 were transcoded because of one camera: HEVC and B-frame H264 are transcoded; own-feeds used copy. Government copy is refused by design (B-frames).

---

## Tile UX

**MEASURED_REAL** after hiding `#live-plates` and plane-chip rows on the 30-wall: video fills the tile, compact LIVE + id + GOVERNMENT header, location/codec footer. First screenshot still showed chips and the plate gallery stealing the fold — that layout is fixed in `ui/style.css` (`cr104`).

Connection states: CONNECTING ring, LIVE chip, RECONNECTING amber, PREVIEW, `prefers-reduced-motion` respected in CSS **DESIGNED / partially MEASURED** (visible in screenshot).

SOURCE / VIDEO / AI remain separate chips (hidden on 30-wall density; still applied in DOM). LIVE is not stamped because a camera exists. Own-feed VIDEO is **REPLAY**.

---

## What is not certified

- 30/30 browser LIVE
- JPEG wall as smooth live video
- In-process AI beside 30 decodes (removed from the product path)
- Per-tile Sentinel WHEP
- Headed 30 FPS recording
- Full AI on 30 streams
- Live ANPR → watchlist → alert → GIS chain in this session

Next bottleneck to remove, in order: keep 30 local publishers connected; reduce wall encode (720p / lower bitrate) so WHEP first-frame is seconds not tens of seconds; then headed Chrome film; then one government camera with a readable plate through the isolated worker.
