# ADR-004: pgvector (PoC) → Qdrant (pilot) → Milvus (statewide)
**Status:** accepted **Date:** 2026-09-01

## Context
Appearance retrieval. Query shape is **heavily filtered**: time window, district,
camera set, vehicle class — then nearest-neighbour within the survivors.
Scale: ~25k vectors (PoC) → ~10M (2k cameras) → **~2.4 B at 30-day retention**
statewide.

## Options
pgvector · Qdrant · Milvus · FAISS · Weaviate.

## Evaluation
pgvector matches dedicated stores at ~1M vectors and is comfortable to ~5–10M —
covering PoC and a 2,000-camera pilot with one database and no extra operational
surface. Qdrant integrates payload indexes into HNSW traversal and is reported
**2–4× faster on filtered queries**; because our workload is filter-dominated,
that matters far more than raw unfiltered QPS. Milvus is the only option with
mature horizontal sharding at billion scale.

## Decision
Three-stage path, chosen by scale. All behind one repository interface.

## Trade-offs accepted
Two future migrations. Accepted because each is justified by a measured
threshold, and pretending one store spans 25k → 2.4B vectors would be dishonest.

## Revisit when
Pilot exceeds ~10M vectors, or filtered-query p95 exceeds 200 ms.
