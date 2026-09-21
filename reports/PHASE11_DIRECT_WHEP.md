# Phase 11 — Direct Sentinel WHEP

Timestamp UTC: `2026-09-19T05:48:08.885131+00:00`

## Decision

**Primary browser path recommendation:** `DIRECT_SENTINEL_WHEP_PRIMARY_LIMITED_CONCURRENCY`

cam01 direct WHEP PASS; multi-cam still limited — use direct for focus tiles; measure further before 16.

## cam01_30s

Path: `DIRECT_SENTINEL_WHEP`  Overall: **PASS**

- PASS/AMBER/FAIL: 1/0/0
- first-frame p50/p95: 4014.199999988079 / 4014.199999988079 ms
- negotiation p50: 465.29999999701977 ms

## Security

Credentials: Authorization Basic header only. Never in URL/stdout/JSON.

Catalogue: authenticated `/cameras.json` is used; `/api/ingest` is not the current portal contract (see SENTINEL_CONTRACT_PROBE).
