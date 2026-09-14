# ADR-009: Versioned model registry with licence gating in code
**Status:** accepted **Date:** 2026-09-01

## Context
A government platform must be able to answer "what produced this result?" and
must never silently swap a model. Licence compliance by intention fails under
deadline pressure — which is exactly when AGPL weights get pulled in.

## Options
1. Model names as configuration strings.
2. **A registry of records with licence class, pinned revision, approval flags.**
3. An external MLOps registry (MLflow, W&B).

## Evaluation
Option 1 is what most teams do and provides no provenance and no licence
control. Option 3 is right at pilot scale and disproportionate now. Option 2 is
~200 lines and makes the licence policy *executable*.

## Decision
`src/saakshya/models/registry.py`. Every record carries licence class, exact HF
revision, hardware requirements, and separate `approved_for_demo` /
`approved_for_production` flags. `ModelRouter` refuses non-permissive licences;
`test_router_never_returns_a_copyleft_model` asserts it across every task ×
profile. **Rejected models stay in the registry with their reason**, so the
decision survives staff turnover.

## Trade-offs accepted
Adding a model requires a registry entry. That friction is the feature.

## Revisit when
Model count exceeds ~30, or signed-artifact verification is required — at which
point this becomes the Model Trust Registry (hash, signature, provenance).
