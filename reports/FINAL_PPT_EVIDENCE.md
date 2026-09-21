# PPT-ready evidence (do not invent)

| Slide claim | Number | Label | Artifact |
|---|---|---|---|
| Statewide architecture | Central analytics + regional media/AI pools | DESIGNED | UI claim |
| 80k cameras centrally decoded | **do not say this** | — | — |
| Registry 80k lookup P50 | 0.044 ms | MEASURED_SYNTHETIC | var/reports/final/model1/registry_80000.json |
| Registry 80k lookup P95 | 0.0551 ms | MEASURED_SYNTHETIC | same |
| Registry 80k insert | 0.6686 s | MEASURED_SYNTHETIC | same |
| GIS 80k cluster | 38.848 ms | MEASURED_SYNTHETIC | var/reports/final/model1/gis_80k.json |
| Government 30-cam 60s visible | 15 | MEASURED_REAL | var/reports/final/live/wall_30_60s.json |
| LIVE / PREVIEW / RTSP_ONLY_AI / NO_SIGNAL (60s) | 11 / 4 / 6 / 0 | MEASURED_REAL | same |
| First-frame P50/P95 (60s) | 25954.04999999702 / 52119.14500000551 ms | MEASURED_REAL | same |
| Prior 120s visible | 19 | MEASURED_REAL | phase16_hybrid_wall_120s.json |
| 50-camera demo | 30 GOV + 2 OWN + 18 CONTROL | MEASURED_SYNTHETIC composition | var/reports/final/scale/fifty_logical.json |
| Adapters isolated | 50; kill-one True | MEASURED_SYNTHETIC DEMO/TEST | var/reports/final/model3/adapters.json |
| Event bus | 2036798.4 ev/s | MEASURED_IN_PROCESS | var/reports/final/model3/event_bus.json |
| Own-feed decode first frame | PEOPLE 15.9 ms · TRAFFIC 7.8 ms | MEASURED_OWN_FEED | var/reports/final/model4/video_only_decode.json |
| Own-feed seek | 1219.7 ms | MEASURED_OWN_FEED | var/reports/final/model4/own_feed_seek.json |
| Watchlist DETECTION→ALERT | 1.701 ms | DEMO / CONTROLLED TEST | var/reports/final/model4/watchlist_controlled.json |
| People (own AI) | 0 | MEASURED_OWN_FEED | var/reports/final/model4/own_feed_ai.json |
| Vehicles (own AI) | 0 | MEASURED_OWN_FEED | same |
| ANPR accuracy | NOT_MEASURED | NOT_MEASURED | — |
| GPU | NOT_MEASURED | NOT_MEASURED | never 0% |
| Kafka | NOT_MEASURED | DESIGNED | — |
