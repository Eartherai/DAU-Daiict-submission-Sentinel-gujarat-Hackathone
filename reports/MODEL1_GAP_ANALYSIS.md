# Registry gap analysis

Generated 2026-09-21 14:52:53Z from `sqlite:///var/live.db`. Counted across the whole registry in
SQL; nothing here is sampled or estimated.

A gap is a field no department has supplied yet, not a field the
platform cannot hold — every column named below exists in the schema and
is accepted by `POST /registry/cameras/import`.

## Estate

| | |
|---|---:|
| Cameras onboarded | 34 |
| Capacity slots (no stream, not graded) | 18 |
| Cameras with no capability sample | 2 |

## Departments

| Department | Cameras |
|---|---:|
| Home (Police) | 27 |
| Own estate | 2 |
| Panchayat | 2 |
| GSRTC | 1 |
| Health | 1 |
| Municipal Corporation | 1 |

Every expected department has at least one camera onboarded.

## Missing metadata

| Field | Missing | Of | Share | |
|---|---:|---:|---:|---|
| `vms` | 32 | 34 | 94.1% | `██████████████████████████··` |
| `storage_location` | 32 | 34 | 94.1% | `██████████████████████████··` |
| `retention_days` | 32 | 34 | 94.1% | `██████████████████████████··` |
| `vendor` | 32 | 34 | 94.1% | `██████████████████████████··` |
| `camera_type` | 32 | 34 | 94.1% | `██████████████████████████··` |
| `coordinates` | 9 | 34 | 26.5% | `███████·····················` |

### What each blocks

- **`vms`** — which departmental VMS a feed must be integrated through.
- **`storage_location`** — whether footage sits in cloud or local storage.
- **`retention_days`** — how long footage survives, which bounds any retrospective investigation.
- **`vendor`** — vendor-specific SDK or ONVIF profile selection.
- **`camera_type`** — fixed or PTZ, which changes what analytics apply.
- **`coordinates`** — placement on the GIS map and any spatial query.

## Cameras with no capability sample

2 cameras have never been graded: `HLT-DEMO-01`, `MC-DEMO-01`

An ungraded camera is an absence of evidence about that camera, not
a poor grade. Run a capability sample to replace the unknown with a
measurement.

---

*Counted across the whole registry in SQL. A field listed here is one no department has supplied yet, not one the platform cannot hold — the column exists in the schema.*
