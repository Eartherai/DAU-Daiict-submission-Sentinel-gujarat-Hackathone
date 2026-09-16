# What to learn conceptually

No competitor source code was copied. The items below are independently
reimplemented ideas, with their verification status kept separate.

| Repository | Strongest idea | What to learn | What not to copy / gap |
|---|---|---|---|
| DrishtiNet | Offline, geometry-aware route reconstruction | Keep route hypotheses explainable and topology constrained | No explicit license; do not copy source. |
| SENTINEL | Edge/central geospatial alert spine | Separate local detection from central correlation | Public ops/UI proof is limited. |
| sentinel | Per-camera AI workers and WebSocket alerts | Isolate stream failures from the rest of the grid | OCR/route integrity is not demonstrated. |
| NETRA | MediaMTX plus registry/GIS | One controlled media layer and source-of-truth registry | Do not assume design docs equal field validation. |
| netra-gp | Product-shaped registry/ANPR workflow | Keep onboarding and analytics in one operator flow | Public evidence is partial. |
| gicvmap | Detection-to-dispatch alert path | Make alerts operational, not a chart | Small repo and claims exceed proof. |
| sentinel-nexus | Metadata-first federation | Move intelligence, not every video byte | Deployment proof is unclear. |
| cctv-hackathon | Shared contracts | Freeze event/schema boundaries early | Scaffold is not an end-to-end system. |
| intel-i-gujarat | Suspicious behavior escalation | Add behavior analytics only when evidence-backed | Avoid uncalibrated suspicion labels. |
| Redeye | Tactical command-center presentation | Make state and incident context visible quickly | Many adapters are mocks. |
| Priyanshu/prahari | Audit-friendly route/export | Preserve route evidence and export provenance | Verify dependency licenses before reuse. |
| TRINETRA | Visual re-ID narrative and operator flow | Present re-ID as candidate evidence, never identity | UI richness must connect to backend data. |
| Gujarat Police AI CCTV | Integrated evidence/watchlist story | Join alert, evidence, route, and watchlist in one case flow | No license/live proof found. |
| Arka integration platform | Edge-first hybrid federation | Treat edge buffering and adapters as first-class | License status is ambiguous. |
| SentinelAI | Modular ANPR service | Keep model boundaries swappable | Microservice shape alone does not prove accuracy. |

SAAKSHYA already implements the highest-value versions of these ideas:
timebase-qualified route hypotheses, bounded stream fan-out, capability
grading, metadata-first edge design, evidence/audit provenance, and explicit
mock-vs-live labeling.
