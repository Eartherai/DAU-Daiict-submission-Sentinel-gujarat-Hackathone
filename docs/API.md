# API

**Source of truth is the code.** OpenAPI is generated from the route
definitions, not maintained beside them, so this document cannot drift into
describing a system that does not exist. Live schema: `GET /openapi.json`,
interactive at `/docs`.

The generated OpenAPI is the complete operation inventory. Everything below is implemented and covered by tests; the live schema is the complete list.

---

## Authentication and purpose

```
Authorization: Bearer <token>          required on every endpoint except /healthz
X-Case-Id:     FIR-214/2026            required on purpose-bound endpoints
X-Purpose:     tracing a stolen vehicle  required, minimum 12 characters
```

Purpose-bound: `/search`, `/trajectory/*`, `/gis/trajectory/*`, `/watchlist`,
`/targets/*/observations`, `/evidence/*/export`, `/evidence/from-observation/*`.

A purpose-bound request without both headers is refused with **400
PURPOSE_REQUIRED** before any data is read. 400 rather than 403 because the
caller is entitled to ask — they have not yet said why.

### Error shape

Every error, from every layer:

```json
{"detail": {"code": "OUT_OF_JURISDICTION",
            "message": "officer.ahd is scoped to ['Ahmedabad']; 'Surat' is outside it"}}
```

| Code | Status | Meaning |
|---|---|---|
| `NOT_AUTHENTICATED` | 401 | No token, unknown token, revoked or expired |
| `PERMISSION_DENIED` | 403 | The role does not hold this permission |
| `OUT_OF_JURISDICTION` | 403 | The district is outside the caller's scope |
| `PURPOSE_REQUIRED` | 400 | Case id and/or purpose missing |
| `QUERY_TOO_BROAD` | 400 | An unfiltered estate scan was refused |
| `RANGE_TOO_LARGE` | 400 | Time window beyond 400 days |
| `BUSY` | 503 | Bounded admission refused rather than queued |
| `INTERNAL_ERROR` | 500 | Returns a request id and nothing else |

`X-Request-Id` is on every response and in every log line.

---

## Investigation

| Method | Path | Purpose-bound | Notes |
|---|---|:---:|---|
| GET | `/search` | ✓ | Plate, fuzzy plate, colour, type, time, district, camera, watchlist-only |
| GET | `/observations/{id}` | | Full evidence panel for one observation |
| GET | `/targets/{plate}/observations` | ✓ | Quality-filtered observation set (§24) |
| GET | `/trajectory/{plate}` | ✓ | Ranked route hypotheses with typed legs |
| GET | `/cameras/{id}` | | Registry, health, capability, graph neighbours |
| GET | `/cameras/{id}/next` | | Ranked next cameras with the decomposition (§25) |
| GET | `/overview` | | Operational home screen |
| GET | `/me` | | Principal and held permissions |

`/search` always returns a `search_strategy` block naming the cameras searched
and, per camera, why each excluded one was excluded. "Not found" never hides the
strategy that produced it.

Every scored result carries `why.terms` — the per-signal decomposition. There is
no endpoint that returns a bare confidence number.

---

## GIS

GIS endpoints share a filter vocabulary where applicable: `bbox` (`west,south,east,north`), `zoom`,
`district`, `department`, `tier`, `status`, `capability`, `grade`, `time_band`.

| Method | Path | Returns |
|---|---|---|
| GET | `/gis/cameras` | Locations with health and measured capability; clusters above 1500 features |
| GET | `/gis/health` | Stream health, including `never_observed` as its own count |
| GET | `/gis/capability` | Measured grades per camera, per time band |
| GET | `/gis/trajectory/{plate}` | One hypothesis as geometry, leg kinds preserved |
| GET | `/gis/alerts` | Alert locations |
| GET | `/gis/coverage` | Gaps: `DISTANCE`, `CAPABILITY`, `AVAILABILITY` |
| GET | `/gis/extent` | Bounding box of the located estate |
| GET | `/gis/near` | Cameras within a radius, nearest first, jurisdiction-scoped |
| GET | `/gis/gaps` | Registry completeness and governance gaps |
| GET | `/gis/timebase` | Camera timing health and time clusters |
| GET | `/gis/timebase/check` | Whether selected cameras may be correlated |

Two properties worth knowing:

- **`cameras_without_location` is always reported.** A map that silently omits
  the cameras it has no coordinates for looks like complete coverage of an
  estate it has not drawn.
- **Every coverage gap carries a caveat in words**: it states where the system
  cannot observe, never where a vehicle was.

---

## Cases

| Method | Path | Notes |
|---|---|---|
| POST | `/cases` | `case_id` is pattern-constrained; purpose ≥ 12 characters |
| GET | `/cases` | Scoped to the caller's jurisdiction |
| GET | `/cases/{id}` | Case, attachments, notes |
| POST | `/cases/{id}/items` | Attach target, observation, trajectory, alert, evidence or camera |
| POST | `/cases/{id}/notes` | |
| GET | `/cases/{id}/export` | Case file **with its full audit trail** and chain verification |

**Case identifiers contain slashes.** An Indian FIR number is `NNN/YYYY`, so
`FIR-214/2026` is the ordinary case, not an exotic input. Every case route uses
a path converter that accepts them, and `/cases/FIR-214/2026/export` resolves
correctly. Percent-encoding the slash works too.

Attachments are **snapshots**, not live references: a trajectory attached on
Tuesday still reads as it did on Tuesday, so an investigator's note about
"hypothesis A" stays meaningful after more observations arrive.

---

## Operations

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/watchlist` | Read is purpose-bound — asking discloses an investigation |
| GET | `/alerts` | |
| POST | `/alerts/{id}/acknowledge` · `/investigate` · `/clear` | Clearing requires a reason |
| POST | `/evidence/from-observation/{id}` | Seals frame and clip, appends to the chain |
| GET | `/evidence/{id}` · `/{id}/frame` | Frame served only from inside the evidence root |
| POST | `/evidence/{id}/verify` | Real cryptographic verification; no stub path |
| GET | `/evidence/{id}/export` | Package with the **draft** s.63 certificate |
| GET | `/evidence/chain/verify` | Whole-chain verification |
| GET | `/audit` | Entries plus chain verification; never synthesised |
| GET | `/capability/summary` · POST `/capability/grade` | Re-grade from stored observations |

---

## Registry, zone rules and output reports

Routes verified in `api/routes_registry.py`, `routes_zones.py`, `routes_ops.py`.

| Method | Path | Notes |
|---|---|---|
| POST | `/registry/cameras/import` · `/registry/cameras/import.csv` | JSON / CSV onboarding, admin write gate; validation before mutation |
| GET | `/registry/cameras/export.csv` | Export registry metadata, camera read gate |
| GET/POST | `/zones` | List authorised zone rules / create a rule with admin write permission |
| GET | `/zones/{rule_id}/entries` | Sightings inside a rule during its hours, alert read permission |
| GET | `/reports/vehicle/{plate}.html` | Printable, scoped, purpose-bound vehicle trace with evidence and digest |
| GET | `/reports/anpr.csv` | Purpose-bound ANPR export with plate, camera and timestamps |

Alert lifecycle: OPEN → ACKNOWLEDGED → UNDER INVESTIGATION → CLEARED.
Clearing requires a reason; transitions are audited (`api/routes_ops.py`).

## Edge

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/edge/{node}/events` | SERVICE | Idempotent replay; reports duplicates rather than hiding them |
| GET | `/edge/nodes` | | Sync state per node |
| GET | `/edge/watchlist/bundle` | | Bundle with its verification method **and its limitation** stated |

A SERVICE token holds `edge:sync` and nothing else.

---

## Copilot

| Method | Path | Notes |
|---|---|---|
| GET | `/copilot/describe` | Tool list, specialists, whether a model is configured |
| POST | `/copilot/ask` | Grounded answer, tool calls, camera ids from tools, warnings |
| POST | `/copilot/scene` | Optional still caption. Off unless `SAAKSHYA_GEMINI_VISION=1`. Frame leaves the host. Not evidence. |

Read-only tools, **none of which writes**. Runs under the caller's own principal
and purpose, so it cannot reach anything the caller could not. Every factual
token in an answer is checked against that turn's tool output; an answer that
fails grounding is withheld and the raw results are shown instead. Gemini does
not enhance or generate government stills.

---

## Operations endpoints

`/healthz` liveness · `/readyz` readiness · `/metrics` Prometheus text ·
`/metrics.json`.

Readiness deliberately does **not** check camera reachability: an estate with
cameras down is degraded, not unready, and failing readiness there would remove
the system from rotation exactly when operators need it.

---

## Limits

| Limit | Value | Behaviour at the limit |
|---|---|---|
| Concurrent searches | 8 | `503 BUSY` after a 5 s wait — refused, not queued |
| Concurrent exports | 2 | `503 BUSY` |
| Results per query | 2000 | Clamped |
| Time span | 400 days | `400 RANGE_TOO_LARGE` |
| Edge batch | 1000 events | Rejected at the model |
| Map features | 1500 | Clusters instead of enumerating |
