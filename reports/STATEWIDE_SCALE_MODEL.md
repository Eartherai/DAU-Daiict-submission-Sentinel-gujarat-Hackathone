# Statewide scale model

This is a capacity model, not a measurement of statewide deployment. The
implementation keeps camera onboarding catalogue-driven, bounds inference, and
moves high-volume video processing toward edge/regional nodes. The central
store is intended for metadata, alerts, evidence references, and investigation
queries rather than 80,000 full-rate streams.

## Evidence classes

| Class | Count | What the repository can support |
|---|---:|---|
| Accessible government | **30** | Authenticated cameras actually accessible and measured in the available environment |
| Official target | **~50** | Challenge target; the current environment did not expose the complete target catalogue |
| Logical 50 | **50** | Capacity-path benchmark with the same catalogue-driven execution path; not 50 government feeds |
| Modeled statewide | **80,000** | Architecture arithmetic and deployment model only; not deployed, reachable, or benchmarked |

The 30 accessible feeds must never be relabelled as 50 government feeds.
Likewise, the logical-50 benchmark is not evidence of 50 simultaneous
government analytics.

## Model boundary

At statewide scale, edge nodes decode and sample streams, regional nodes run
bounded analytics and retain hot evidence, and the core receives compact events,
indexes, watchlist alerts, route features, and sealed evidence references.
Warm/cold retention and disaster recovery remain deployment decisions. Central
PostgreSQL/PostGIS/pgvector, failover, and 80,000-camera throughput require a
target environment and are not locally measured.

The next honest validation step is an authenticated approximately-50-camera
run with an explicit sampling policy, resource ceiling, decoder error rate,
alert latency, and retention accounting.
