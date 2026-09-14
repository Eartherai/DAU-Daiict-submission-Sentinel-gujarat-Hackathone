# ADR-008: One tool-calling orchestrator; multi-agent rejected
**Status:** accepted **Date:** 2026-09-01

## Context
An investigation copilot is attractive to judges and dangerous at a live
government evaluation.

## Options
A. Deterministic pipeline only.
B. **Single LLM orchestrator over typed tools.**
C. Supervisor + sub-agents.
D. Multi-agent swarm.
E. Graph runtime (LangGraph).

## Evaluation
| | Latency | Reproducible | Auditable | Fails how |
|---|---|---|---|---|
| A | best | total | total | rigid query surface |
| B | good | high | high | occasional bad tool choice, recoverable |
| C | poor | low | medium | cascading hallucination |
| D | worst | none | poor | undebuggable live |

AutoGen entered maintenance in October 2025 (CC-BY-4.0 on a code repo, 138 days
stale at audit). LangGraph is healthy and well-adopted, but we need one loop,
not a graph runtime — adopting it would add a dependency to solve a problem we
do not have.

## Decision
**A with B on top, and A must pass with B switched off** — an exit criterion,
not an aspiration. No mutation tools: the LLM cannot modify a watchlist, clear
an alert, export evidence, or override confidence.

## Trade-offs accepted
A narrower copilot than a multi-agent demo would show. Reliability over
spectacle.

## Revisit when
The tool surface exceeds ~15 tools or genuine parallel planning is needed.
