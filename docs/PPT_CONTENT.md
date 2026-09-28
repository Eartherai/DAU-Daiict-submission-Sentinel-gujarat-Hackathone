# Presentation content guide

The rendered presentation is owned by `tools/demo/render_submission_deck.py`.
Use [FINAL_SUBMISSION.md](FINAL_SUBMISSION.md) for the pack inventory and
[HLD.md](HLD.md) for technical claims. This guide supersedes the earlier
slide-by-slide script and its obsolete film names. It is no longer input for
`tools/demo/render_deck.py`; use the submitted renderer above.

| Topic | Evidence to present |
|---|---|
| Model choice | Model 1 registry/GIS/governance; Model 2 unified viewing and metadata search; Model 3 VMS federation; Model 4 selected central analytics. Statewide central recording declined on MODELLED arithmetic (`SCALE_MODEL.md`). |
| Team-chosen government stand-in | `GJ11S7924` (not organiser-issued), cam06 only, SINGLE-CAMERA evidence (`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). |
| Synthetic route | `GJ18JX7786`, C-014 then C-021: SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage (same snapshot report). |
| Watchlist | `GJ38BH5815` is evaluation_designated, HIGH, not stolen (same snapshot report); correlate at ingest, acknowledge → investigate → clear with reason. |
| Analytics | Detection, tracking, voted ANPR, person presence and restricted-zone rules; selected cameras, fixed-interval sampling in the live worker (the adaptive scheduler is built and tested, not yet wired into it), hardware-bounded deep inference (`HLD.md` §4). |
| Payload and scale | ~400 B MODELLED optimised payload; 1,331.7 B MEASURED serialised row (`var/reports/bandwidth.json`). Sizing uses the measured row. MODELLED gated daily volumes: 92.16–184.32 GB vs 306.82–613.65 GB (`SCALE_MODEL.md`). |
| Load | Local streams: 50 initially, 44 streaming / 6 down at end, no recovery, 0 decoder errors (`var/reports/camera_load.json`). Synthetic registry/GIS load is separate (`reports/SCALE_80K_LOAD_TEST.md`). |
| GPU | Equal observation counts, no plates on either device in the historical pipeline sample (`var/reports/pipeline_device.json`); target GPU pools MODELLED/SIZED. |
| Films | Own feed 2:43 (`var/demo/own_feed.mp4`, ffprobe, recorded 28 Sep); government 5:40 (`var/demo/government_feed.mp4`, recorded live 28 Sep 2026). Recogniser provenance in `FINAL_SUBMISSION.md`. |

**Model 2 media policies (VERIFIED, `ui/app.js`, `tileWhepBudget`).**
CONTROL ROOM (Dense 6×5) opens one direct WHEP session per tile, up to 30,
400 ms apart. OPTIMIZED VIEW (default scrolling wall) holds at most 12
sessions near the viewport, prefetches 600 px, and releases sessions 15 s
after leaving it. `#media-policy` names the active policy. Browser signalling
uses SAAKSHYA’s authenticated proxy; Sentinel credentials stay server-side.
Selected AI workers read RTSP/TCP separately. These are local viewing policies,
not sandbox limits or a claim that every tile is currently live.

Current demonstration hardware limits simultaneous deep-inference
concurrency. Analytics workers scale horizontally, so additional GPU nodes
raise concurrent inference throughput without redesigning ingest, event,
watchlist, GIS or investigation services.

The default is **4 deep-inference slots, prioritised by measured capability**
(VERIFIED in `src/saakshya/analytics/worker.py`, `SAAKSHYA_AI_CAMERA_LIMIT`).
At worker boot, stream-capable enabled cameras are ranked GOOD > DEGRADED >
UNKNOWN > UNSUITABLE by ANPR grade; ties use camera id. Assignments do not
rotate at runtime. This configured default is separate from the historical
four-camera measurement in `reports/SCALE_80K_LOAD_TEST.md`.
`command/summary.py` reports “N of M camera(s) with a stream under
analysis”. Integrated cameras remain available to the viewer and health
surfaces, subject to source availability. `AdaptiveInferenceScheduler` implements
priority cadence and is VERIFIED in the certification harness; `AnalyticsBudget` tier selection is unit-tested. Neither
is wired into the live worker (DESIGNED integration). The worker samples at a
fixed interval (`SAAKSHYA_AI_SAMPLE_S`, default 0.20 s); it does not rotate cameras.
GPU pool capacities in this proposal are **MODELLED/SIZED**, not measured cluster throughput.
