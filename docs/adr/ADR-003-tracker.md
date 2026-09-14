# ADR-003: roboflow/trackers over BoxMOT
**Status:** accepted **Date:** 2026-09-01

## Context
Need stable per-camera track identity, PTS-aware motion, and recovery across
segment breaks. Track identity is **local camera continuity, not statewide
identity** — that distinction is load-bearing.

## Options
1. BoxMOT — most complete toolkit. **AGPL-3.0.**
2. **roboflow/trackers** — Apache-2.0, maintained (pushed on audit day).
3. Upstream ByteTrack (803 d stale) / BoT-SORT (753 d stale) — MIT but abandoned.
4. OC-SORT — MIT, maintained, strong under occlusion.

## Evaluation
BoxMOT is blocked on licence. Upstream repos are permissively licensed but >2
years without a push, which in a government deployment is a security-patch
liability. `roboflow/trackers` provides clean Apache-2.0 reimplementations under
active maintenance.

## Decision
`roboflow/trackers`. OC-SORT registered as a candidate for occlusion-heavy
cameras.

## Trade-offs accepted
Fewer algorithms than BoxMOT. We need one good tracker, not twelve.

## Revisit when
Measured ID-switch rate on government feeds is unacceptable.
