# FINAL PRODUCT — 50-camera command center + Model 4 intelligence demonstrator

**Date:** 2026-09-17  
**Media path:** unchanged (no WHEP/RTSP/bridge/ffmpeg edits). Own-feed file seek only.

## What this phase is

A productisation pass. Government sandbox cameras remain the interoperability wall. The two own submission feeds (`OWN-PEOPLE`, `OWN-TRAFFIC`) are the **golden Model 4** demonstration sources.

Claim used in the UI:

> Centralized analytics and command orchestration with regional media/AI pools for statewide deployment.

Not claimed: 80,000 cameras processed or recorded centrally; 50 government live streams; fabricated detections.

## Three domains (never mixed)

| Domain | Badge | What it is |
|---|---|---|
| `GOVERNMENT` | GOVERNMENT | Supplied Sentinel probe / catalogue cameras (~30) |
| `OWN_FEED` | OWN FEED | Participant golden feeds A/B |
| `SYNTHETIC_CONTROL` | CONTROL | Logical 50-wall fill. Never labelled government |

## Product modes

| Mode | Surface |
|---|---|
| OPERATIONS | Camera wall 12 / 16 / 25 / 30 / **50** |
| INTELLIGENCE | Model 4 command on own feeds |
| INVESTIGATION | Track / route / evidence |
| SYSTEM | Health, adapters, architecture, audit |

Wall domain filters: GOVERNMENT MODE, INTELLIGENCE DEMO, 50-CAMERA, ALL.

## Model 4 hero

Own Feed A (`OWN-PEOPLE`) and Own Feed B (`OWN-TRAFFIC`): video + people + vehicles + tracking + ANPR + watchlist + alerts + evidence + GIS. Detections are store observations only. Fixture use is labelled **DEMO / CONTROLLED TEST**.

50-camera evaluation composition in this store: **30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL**.

## Jump honesty

- Live WHEP: **EVENT TIMESTAMP** is distinct from **CURRENT LIVE POSITION**. Not seekable.
- Own-feed file in `var/media`: replay can seek to event PTS (`SelectedView.seek_file`). Sentinel RTSP path is not used for that seek.

## Labels

- MEASURED_REAL: 30 government probe IDs (prior phases); hybrid browser wall ~19.
- DESIGNED: 50 logical wall, M4 orchestration diagram.
- SYNTHETIC_CONTROL: remaining slots.
- GPU / detector FPS: UNAVAILABLE unless measured.

## Security

SECRET SCAN: PASS (this run).
