# ADR-006: Camera Link Model in Postgres, no graph database
**Status:** accepted **Date:** 2026-09-01

## Context
Need to prune physically impossible cross-camera associations and rank plausible
routes, on an estate with **no camera calibration** and no surveyed topology.

## Options
1. Static GIS-distance graph.
2. **Learned Camera Link Model** — transition-time distributions from observed
   co-occurrences, seeded by GIS distance.
3. Markov / HMM over camera states.
4. Temporal graph network or GNN.
5. Neo4j or Apache AGE as the store.

## Evaluation
The Camera Link Model is **established prior art** in AI City Challenge
literature (~2019–2021) and is honestly labelled N1. It bootstraps without a
survey, which is decisive here. A GNN will not train on hours of data and is not
explainable to a jury. The graph has ~10² nodes at PoC and ~10⁴ statewide with
sparse edges — a recursive CTE outperforms a graph database at that size and
removes a dependency. Neo4j Community is GPL-3.0.

## Decision
Camera Link Model, stored as Postgres tables, traversed with recursive CTEs.
k-shortest-path over time-dependent edges for trajectory hypotheses.

## Trade-offs accepted
No learned transition model initially. Deferred until officer-confirmation
labels exist.

## Revisit when
Edge count exceeds ~10⁶, or a learned ranker measurably beats the deterministic
solver on held-out data.
