# ADR-005: NATS JetStream, with Kafka as the documented statewide path
**Status:** accepted **Date:** 2026-09-01

## Context
Computed statewide event rate: **926 events/sec** (80,000 cameras × 1,000
events/camera/day), ~12.9 MB/s payload. Requirements: durability, ordered
replay after an offline period, regional isolation, low operational burden.

## Options
NATS JetStream · Kafka · Redpanda · Pulsar · in-process queue.

## Evaluation
926 ev/s is a small number. Kafka is over-specified for the PoC and pilot and
carries real operational weight. Redpanda is **BSL** — unsuitable for government
procurement. Pulsar carries 1,730 open issues and heavy operational complexity.
NATS JetStream is a single Apache-2.0 binary with durable streams and replay.

## Decision
NATS JetStream for PoC and pilot. Kafka documented as the statewide swap-in,
justified by fan-out and multi-consumer needs rather than by throughput.

## Trade-offs accepted
A future migration. The event schema (`CCTV-EVENT v1`) is bus-agnostic, so the
change is transport-only.

## Revisit when
Multiple independent consumer groups need independent replay at state scale.
