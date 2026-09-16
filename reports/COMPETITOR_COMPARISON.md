# Competitor comparison

Evidence labels: **V** verified in source/tree or tests, **P** partial
implementation, **C** claimed/documented only, **M** mock/simulated,
**U** unavailable/ambiguous. Scores are 0 absent, 1 conceptual, 2 partial,
3 functioning, 4 strong, 5 exceptional/strongly demonstrated. Competitor
inspection used public GitHub source trees and manifests; it did not treat
README claims as tests.

| Repository | License | Registry/GIS | Stream federation | Detection/ANPR | Tracking/route | Watchlist/alerts | Ops/security | UX/demo | Overall |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **SAAKSHYA** | permissive policy | V 5 | V 4 | V 4 | V 5 | V 4 | V 5 | V 4 | **31** |
| DrishtiNet | none | V 5 | P 2 | P 2 | V 5 | P 3 | P 2 | V 4 | 23 |
| Jayshil06/SENTINEL | none | V 4 | P 3 | P 3 | P 3 | V 4 | P 3 | P 3 | 23 |
| bhupendrasharmaX/sentinel | none | P 3 | V 3 | V 4 | P 3 | P 3 | P 2 | P 3 | 21 |
| NETRA | none | V 5 | V 4 | P 3 | P 3 | P 3 | P 3 | V 4 | 25 |
| netra-gp | none | V 4 | P 2 | P 3 | P 2 | P 3 | P 2 | P 3 | 19 |
| gicvmap | none | P 3 | P 2 | P 3 | P 2 | P 3 | P 2 | P 3 | 18 |
| sentinel-nexus | none | V 4 | V 4 | P 2 | P 3 | P 3 | P 3 | P 3 | 22 |
| cctv-hackathon | none | P 2 | P 2 | M 1 | M 1 | M 1 | P 2 | M 1 | 10 |
| intel-i-gujarat | none | P 3 | P 2 | V 3 | P 3 | V 4 | P 2 | P 3 | 20 |
| VaibhavJain2609/prahari | none | C 2 | C 2 | C 2 | C 3 | C 3 | C 3 | C 3 | 18 |
| Redeye | none | V 4 | M 3 | M 3 | M 3 | M 3 | P 3 | V 5 | 24 |
| Priyanshu-byte-coder/prahari | Apache-2.0 | V 4 | P 3 | V 3 | V 4 | V 4 | V 3 | V 4 | 25 |
| unified Sentinel platform | none | P 3 | P 3 | P 3 | P 3 | P 3 | P 2 | P 3 | 20 |
| gsp | none | C 3 | C 2 | C 2 | C 3 | C 2 | C 3 | C 3 | 18 |
| TRINETRA | none | V 4 | P 2 | P 3 | V 4 | P 3 | P 2 | V 5 | 23 |
| Gujarat Police AI CCTV | none | V 4 | P 3 | V 4 | P 4 | V 4 | P 3 | V 4 | 26 |
| Vatsa10/sentinel | none | P 3 | P 3 | P 2 | P 2 | P 2 | P 2 | P 3 | 17 |
| gujarat-cctv-integration-platform | noassertion | V 4 | V 4 | P 3 | P 4 | P 3 | P 3 | P 3 | 24 |
| SentinelAI_GujaratCCTV | none | P 2 | V 3 | V 3 | P 2 | P 2 | P 2 | P 2 | 16 |
| chiragkkamani/gujarat-police | none | P 3 | P 2 | P 3 | P 2 | P 2 | P 2 | P 3 | 17 |

## Requirement coverage matrix

| Capability family | SAAKSHYA evidence | Common competitor state |
|---|---|---|
| Catalogue/registry/GIS/onboarding | V: registry schema, import, health, map | Often V/P design; live catalogue proof uncommon. |
| RTSP/HLS/WebRTC, H.264/H.265, PTS, reconnect | V: PyAV, MediaMTX, PTS, TCP, backoff, mixed-codec artifacts | Usually P/C; MediaMTX is strongest in NETRA. |
| Detection/tracking/ANPR/OCR normalization | V/P: modular pipeline, voting, raw reads, capability grades | Several V prototypes use YOLO/EasyOCR; model/license and measured output often unclear. |
| Re-ID/cross-camera/route/speed rejection | V: graph, timebase qualification, contradiction and coverage-gap legs | Route design is the strongest competitor cluster; live proof is usually unclear. |
| Watchlist/alerts/evidence/audit | V: real store/API/tests/hash chain | Frequently P/C, with Priyanshu's route/export workflow strongest OSS example. |
| UI/live wall/search/GIS | V: working static UI and recorded flows | Redeye/TRINETRA lead visual polish; some are simulated. |
| RBAC/security/observability | V: adversarial scorecard, purpose/jurisdiction gates, metrics | Generally P/C or undocumented. |
| 50-camera/80k scaling | V measured decode + modeled architecture | Most claims are architectural; no competitor evidence was treated as a measured 50-camera full analytics run. |

This matrix is a comparative engineering aid, not a claim that the public
repositories are inferior in every dimension. Scores should be revisited if
private demos or newly published code become available.
