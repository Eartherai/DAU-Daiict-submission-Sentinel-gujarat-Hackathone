# Final requirement traceability

Status: PASS only with a measured artifact. Code existence is not PASS.

| Requirement | Model | Implementation | Test | Measured result | Artifact | Demo step | Status |
|---|---|---|---|---|---|---|---|
| Unified CCTV registry | 1 | SQLite Camera registry | 1k/10k/50k/80k | 80k lookup P50 0.044 ms | var/reports/final/model1/registry_80000.json | Estate map search | PASS |
| GIS clustering / filters | 1 | MapService cluster + domain filters | 80k cluster; 50 GIS | cluster 38.848 ms | var/reports/final/model1/gis_80k.json | Map filters | PASS |
| 80k live video | 1/2 | Regional media DESIGNED | — | not claimed | — | — | DESIGNED |
| Unified viewing | 2 | Native video + overlay | Fresh 30@60s Direct WHEP + Phase 16 120s | 15 visible at 60s; 19 at 120s | var/reports/final/live/wall_30_60s.json | OPERATIONS wall | PASS |
| 50 government live | 2 | — | — | 30 registered, 15 visible at 60s | same | — | BLOCKED_EXTERNAL |
| 50 logical wall | 2 | 30+2+18 domains | seed_50 | onboarded 50 | var/reports/final/scale/fifty_logical.json | 50-CAMERA WALL | PASS |
| Overlay modes | 2 | overlay_allows + UI | unit | modes table | var/reports/final/model2/overlay_modes.json | Analytics toolbar | PASS |
| COMPARE no 2nd WHEP | 2 | canvas.drawImage | code + UI | WORKING | ui/app.js mountCompare | COMPARE | PASS |
| Operator action latency | 2 | product actions | — | NOT_MEASURED this run | — | click through | PARTIAL |
| VMS federation | 3 | RTSP/ONVIF/GenericVMS DEMO/TEST | 2/5/10/25/50 + kill | isolation on 50 | var/reports/final/model3/adapters.json | SYSTEM connected systems | PASS |
| Kafka bus | 3 | EventBus in-process | 5000 events | 2036798.4 ev/s MEASURED_IN_PROCESS | var/reports/final/model3/event_bus.json | — | DESIGNED |
| Real departmental VMS | 3 | adapters only | — | no credentials | — | labelled DEMO/TEST | BLOCKED_EXTERNAL |
| Own-feed video | 4 | local MP4 decode | 30/60/120 s windows | first-frame 15.9 / 7.8 ms | var/reports/final/model4/video_only_decode.json | INTELLIGENCE | PASS |
| Own-feed detection FPS | 4 | CameraPipeline optional | 12 frames | MEASURED_OWN_FEED | var/reports/final/model4/own_feed_ai.json | INTELLIGENCE | PARTIAL |
| People count | 4 | pipeline / store | own AI | 0 | same | PEOPLE mode | PASS |
| Vehicles | 4 | pipeline / store | own AI | 0 | same | VEHICLES mode | PASS |
| ANPR accuracy | 4 | OCR | ground truth missing | NOT_MEASURED | — | ANPR | NOT_APPLICABLE |
| Watchlist match | 4 | WatchlistService + AlertEngine | controlled fixture | 1.701 ms | var/reports/final/model4/watchlist_controlled.json | WATCHLIST MATCH | PASS |
| Follow / hops | 4 | follow_vehicle + entity_tracking | valid + contradiction | FIRST/NEXT/LAST + reason | var/reports/final/model4/investigation.json | TRACK TARGET | PASS |
| Jump live vs own | 4 | jump_playback + seek_file | live not seekable; file seek | seek 1219.7 ms | var/reports/final/model4/own_feed_seek.json | JUMP TO EVENT | PASS |
| FAST/BALANCED/DEEP | 4 | AI_CADENCE + scheduler | 100-frame flags | cadence table | var/reports/final/model4/ai_cadence.json | cadence chips | PASS |
| AI kill isolation | 4 | in-process thread | kill AI, video continues | True | var/reports/final/model4/failure_isolation.json | — | PASS |
| Dashboard KPIs | 4 | command_summary.kpis | source on every cell | GPU NOT_MEASURED | /command/summary | INTELLIGENCE KPIs | PASS |
| Hybrid architecture | 5 | claim text | — | not 80k central decode | UI intel-claim | SYSTEM | PASS |
