# 30-camera live-feed check

## Execution

Run: **2026-09-16 05:25 IST / 2026-09-15 23:55 UTC**  
Configured cameras: **30** (`cam01` through `cam30`)  
Concurrent RTSP probes: **30 workers, one attempt per camera, 3-second bound**  
Credentials: **not configured in this environment**  
WHEP endpoint: **not configured in this environment**

## Result

All 30 RTSP probes returned **401 Unauthorized** before a video stream could be
opened. This is an access/authentication boundary, not evidence that all 30
camera encoders are broken. No honest live FPS, latency, freeze, green-frame,
or moving-car claim can be made from this run.

| Camera IDs | Result | Root-cause classification |
| --- | --- | --- |
| cam01–cam30 | 30/30 `UNAVAILABLE`, HTTP 401 | **ACCESS / CREDENTIAL CONFIGURATION** |

The diagnostic outputs are stored under `var/reports/live30/rtsp/` with URLs
redacted. The failure was concurrent and uniform across all registered sources.

## Screenshot inspection

`var/reports/live30/contact_sheet.jpg` contains one frame for each of the 30
registered cameras. These are **stored preview JPEGs, not a live screenshot**:

- all 30 files were approximately 29.96 hours old at inspection;
- several frames visibly contain green/corrupt regions or heavy blocking;
- cam09 and cam22 are nearly black;
- cam08, cam10, cam28, and cam29 contain strong green regions;
- cam07, cam12, cam16, cam20, cam21, and cam26 contain visible block artefacts;
- the burned-in dates are from June 2026, not the current run.

The contact sheet therefore proves that the available preview store is not a
judge-ready live wall. It does not prove the current government source is
currently producing those exact frames.

## Local controls

The available 21 local clips decode through PyAV without black or decoder-error
counts in the bounded sample, but their decoded PTS is constant and their
container-declared FPS is implausible. They are decode controls only, not live
transport evidence. The diagnostic correctly withholds observed FPS.

## Required next action

Configure the organizer-approved credentials and/or authenticated Resources
session, then repeat this exact 30-worker run. Only after a successful open can
we compare direct RTSP, gateway WHEP, HLS, and H.264-transcoded paths and
measure movement, latency, freezes, and recovery.
