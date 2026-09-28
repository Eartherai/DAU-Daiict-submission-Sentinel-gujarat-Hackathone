# Presentation content guide

The rendered presentation is owned by `tools/demo/render_submission_deck.py`.
Use [FINAL_SUBMISSION.md](FINAL_SUBMISSION.md) for the pack inventory and
[HLD.md](HLD.md) for technical claims. This guide supersedes the earlier
slide-by-slide script and its obsolete film names.

| Topic | Evidence to present |
|---|---|
| Model choice | Model 1 registry/GIS/governance; Model 2 unified viewing and metadata search; Model 3 VMS federation; Model 4 selected central analytics. Statewide central recording declined on MODELLED arithmetic (`SCALE_MODEL.md`). |
| Government designated vehicle | `GJ11S7924`, cam06 only, SINGLE-CAMERA evidence (`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`). |
| Own-feed route | `GJ18JX7786`, C-014 then C-021: CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION (same snapshot report). |
| Watchlist | `GJ38BH5815` is evaluation_designated, HIGH, not stolen (same snapshot report); correlate at ingest, acknowledge → investigate → clear with reason. |
| Analytics | Detection, tracking, voted ANPR, person presence and restricted-zone rules; selected cameras, adaptive cadence, hardware-bounded deep inference (`HLD.md` §4). |
| Payload and scale | ~400 B MODELLED optimised payload; 1,331.7 B MEASURED serialised row (`var/reports/bandwidth.json`). Sizing uses the measured row. MODELLED gated daily volumes: 92.16–184.32 GB vs 306.82–613.65 GB (`SCALE_MODEL.md`). |
| Load | Local streams: 50 initially, 44 streaming / 6 down at end, no recovery, 0 decoder errors (`var/reports/camera_load.json`). Synthetic registry/GIS load is separate (`reports/SCALE_80K_LOAD_TEST.md`). |
| GPU | Equal observation counts, no plates on either device in the historical pipeline sample (`var/reports/pipeline_device.json`); target GPU pools MODELLED/SIZED. |
| Films | Own feed 2:53 (`var/demo/own_feed.mp4`, ffprobe); government re-recorded — duration stamped at pack build. Recogniser provenance in `FINAL_SUBMISSION.md`. |

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

The measured concurrency is a few selected cameras at a time, not the whole
registry (see `reports/SCALE_80K_LOAD_TEST.md` for the historical four-camera
run). `command/summary.py` reports “N of M camera(s) with a stream under
analysis”. Integrated cameras remain available to the viewer and health
surfaces, subject to source availability. `AdaptiveInferenceScheduler` changes
inference **cadence** by NORMAL / HIGH_PRIORITY / ALERT / FORENSIC priority;
it does not rotate which cameras receive deep inference. GPU pool capacities
in this proposal are **MODELLED/SIZED**, not measured cluster throughput.
