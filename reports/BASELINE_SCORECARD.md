# Baseline scorecard

Scale: 0 absent, 10 strong evidence in this repository. Scores are evidence
scores, not predictions of the panel's mark.

| Area | Score | Evidence and limitation |
|---|---:|---|
| Government-feed success | 8 | 30-camera live store and ingest reports; current credentials/run are environment-dependent. |
| 50-camera readiness | 7 | 50-camera decode/load measurement with zero decoder errors; full analytics is not measured at 50. |
| ANPR | 7 | PTS-aware plate reads, voting, normalization, raw-read retention; live grades show 28 unsuitable and 2 unknown. |
| Vehicle tracking | 7 | Per-camera tracking and attributes are implemented and tested; cross-camera government identity is not demonstrated. |
| Cross-camera correlation | 6 | Graph/appearance/plate interfaces and synthetic route evidence; zero exact live-government repeats. |
| Route reconstruction | 8 | Explainable hypotheses, timebase qualification, speed rejection, coverage-gap/contradiction labels, tests. |
| Watchlist | 8 | Searchable records, priority/authority fields, matching, cooldown/de-duplication, alerts and tests. |
| Alerts | 8 | Real event path, statuses, evidence linkage, API/UI and tests. |
| GIS | 8 | Camera/alert/route APIs and map workflow; location precision is explicitly qualified. |
| Camera registry | 9 | Registry schema, catalogue import, metadata, health and stable-source principles. |
| Heterogeneous streams | 8 | H.264/H.265 measured, PyAV, RTSP TCP, HLS/WHEP metadata, reconnect and bounded fan-out. |
| Interoperability | 6 | Adapter-ready metadata and protocol fields; ONVIF/vendor adapters are architecture-ready, not integrated. |
| Security | 9 | Adversarial security suite and scorecard; host/database compromise out of scope. |
| RBAC | 8 | Roles, permissions, jurisdiction and purpose gates are implemented and tested. |
| Auditability | 9 | Hash-chained audit and evidence manifests with verification. |
| Evidence | 8 | Manifest/hash/chain and source-quality caveats; government video retention is intentionally not claimed. |
| Scalability | 7 | 50-camera decode measurement plus district/central model; statewide central load is modeled only. |
| Performance | 8 | API/DB/ingest measurements with artifacts; analytics CPU ceiling is known. |
| Reliability | 8 | Reconnect, segment handling, chaos harness and offline queue tests. |
| UI/UX | 8 | Working investigation workspace and recordings; static UI and external live media config remain deployment concerns. |
| Demo readiness | 9 | Isolated demo seed, scripts, films, portal pack, deterministic fixtures. |
| Documentation | 9 | HLD, ADRs, security, scale, measurements, test alignment and submission docs. |
| Deployment readiness | 6 | Runnable local stack and migration direction; no containerized HA deployment exercised here. |
| Differentiation | 9 | Honest capability grading, timebase verdicts, impossible-route rejection, provenance and purpose binding. |

**Baseline weighted mean: 7.9/10.** The score is intentionally lowered for
unmeasured full analytics at 50 cameras and the absence of a demonstrated
cross-camera government repeat.
