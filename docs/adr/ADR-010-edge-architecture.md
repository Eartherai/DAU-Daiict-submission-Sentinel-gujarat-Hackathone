# ADR-010: Metadata-first federation; raw video stays at the department
**Status:** accepted **Date:** 2026-08-31 (reaffirmed 2026-09-01)

## Context
80,000 cameras across 26 departments, sites up to ~1,000 km apart, heterogeneous
retention (7 / 15+ days), existing departmental VMS estates with their own
operational control.

## Options
A. Centralise all video (Model 4).
B. **Metadata-first: analyse at the edge, ship events, fetch clips on demand.**
C. Edge-only, no central intelligence.
D. Federated search over departmental indexes.

## Evaluation
Centralising 1080p H.265 statewide is **160 Gbps and ~25.9 PB at 15-day
retention**; H.264 4 Mbps is 320 Gbps and ~51.8 PB. Metadata-first at 1,000
events/camera/day is **13.9 KB/camera/day → ~103 Mbps aggregate, ~1.11 TB/day**
— a **~1,550×** WAN reduction. Option C cannot do cross-district correlation,
which is the product. Option D is privacy-maximal but has unpredictable latency
across 26 departments and is very hard to demo.

**This is not our innovation.** The UK National ANPR Service runs exactly this
shape at ~90M reads/day. We present it as proven, not novel.

## Decision
Option B. Full video remains in departmental storage under departmental
retention. Clips are fetched on demand and only for flagged events.

## Trade-offs accepted
Evidence retrieval depends on the department's system being reachable, and on
their retention window not having expired — which is a real operational risk and
is stated in the HLD rather than hidden.

## Revisit when
The state funds a backbone that makes centralisation cheap, at which point
ingest is an adapter change, not a redesign.
