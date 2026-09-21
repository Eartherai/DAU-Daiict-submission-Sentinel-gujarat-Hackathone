# Media architecture audit

Generated 2026-09-17 after instrumenting the product path (not a guess).

Labels: `MEASURED_REAL` · `MEASURED_OWN_FEED` · `DESIGNED` · `EXTERNAL_DEPENDENCY`.

## Connection graph (before this pass)

```
Sentinel WHEP :8889  ←—— N browser RTCPeerConnections (≤12 tiles)
Sentinel RTSP :8554  ←—— SnapshotService short grabs (≤4 inflight) when ingest JPEG missing
Sentinel RTSP :8554  ←—— StreamWorker / live ingest (separate process, often not running)
Sentinel RTSP :8554  ←—— SelectedView (one extra decode on click)
Local MP4            ←—— OWN-PEOPLE / OWN-TRAFFIC file view

SQLite WAL           ←—— ingest upsert_health, observations, audit, /system/health
```

Each browser tile that negotiated WHEP opened **its own upstream Sentinel session**. HTTP 201 did not imply a first frame (ICE / codec). Cycling 12→16→25→30 produced 502/503. Snapshots competed with WHEP. `/system/health` waited on the same SQLite as ingest writers (`busy_timeout` was 60s).

## Connection graph (after local hub)

```
GOVERNMENT CAMERA
    |
    | one RTSP/TCP (StreamWorker)
    v
LOCAL MEDIA HUB (in API process)
    +-- JPEG latest-frame-wins  →  N browser tiles (same JPEG, no extra Sentinel)
    +-- bounded AI queue        →  detector/tracker/ANPR (own-feeds + SAAKSHYA_AI_GOV)
    +-- in-memory telemetry     →  GET /media/hub, GET /cameras/{id}/media-state
    +-- batched health flush    →  SQLite every 5s (not per frame)

OWN-PEOPLE / OWN-TRAFFIC
    | local MP4, same hub
    v
FILE REPLAY (never labelled LIVE government)
```

Browser Direct WHEP to Sentinel is **off** while the hub is up (`/config live.plane=local_hub`). That is the fan-out: one upstream, many local subscribers.

## Session multiplicity (target)

| Consumer | Upstream sessions per camera |
|---|---|
| Browser wall | 0 extra (hub JPEG) |
| Snapshot API | 0 extra (hub memory) |
| AI | 0 extra (same decoded frames, drop-oldest queue depth 2) |
| Selected `/view` | optional one extra file/RTSP for hero PTS pump |
| Sentinel WHEP per tile | **none** while hub is on |

## State machine

SOURCE: CONNECTING | CONNECTED | RECONNECTING | UPSTREAM ERROR | NO SIGNAL  
VIDEO: CONNECTING | LIVE | PREVIEW | RECONNECTING | NO SIGNAL  
AI: OFF | ACTIVE | DEGRADED  

LIVE is **only** VIDEO when hub JPEG age ≤ 4.0 s **and** SOURCE is CONNECTED. A still is never LIVE. Own-feed file replay is **REPLAY**, never LIVE.

## Measured after this pass (2026-09-17)

Snapshot (`reports/final_live_qa/hub_wall.json`):

- upstream slots **32**
- government SOURCE CONNECTED **30/30**
- government VIDEO LIVE **20/30** (peak **26/30** earlier in the same session)
- JPEG fps median **4.6**
- own-feeds VIDEO **REPLAY**
- `/healthz` p50 1.1 ms, `/audit` p50 1.5 ms, `/search?plate=GJ01TA0001` p50 2.8 ms while ingesting

30/30 browser LIVE was not achieved. 32 upstream RTSP sessions were.

See `reports/FINAL_REALTIME_PRODUCTION_CERTIFICATION.md`.

## SQLite

- WAL, `synchronous=NORMAL`, `busy_timeout=4000` (was 60000).
- Media frames do not write SQLite.
- Health is flushed every 5s.
- `/system/health` feed component reads **hub memory** first.

## Remaining EXTERNAL_DEPENDENCY

If Sentinel will not accept 30 simultaneous RTSP/TCP ingests, the hub will show fewer SOURCE CONNECTED than 30. That is an upstream limit, not a browser WHEP storm. The wall must not fake LIVE for the rest.

## Key files

- `src/saakshya/live/hub.py` — MediaHub
- `src/saakshya/ingest/stream.py` — StreamWorker (one capture, internal fan-out)
- `src/saakshya/api/app.py` — lifespan boot
- `ui/app.js` — tile planes, no per-tile Sentinel WHEP when hub is on
