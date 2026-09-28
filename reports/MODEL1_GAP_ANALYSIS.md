# Registry gap analysis

Generated 2026-09-28 10:54:37Z from `var/live.db (read-only immutable reference, 28 Sep 2026)`. Counted across the whole registry in
SQL; nothing here is sampled or estimated.

A gap is a field no department has supplied yet, not a field the
platform cannot hold — every column named below exists in the schema and
is accepted by `POST /registry/cameras/import`.

The registry has 56 rows (read-only SQL `GROUP BY source_domain`): 30 GOVERNMENT,
6 OWN_FEED, 18 SYNTHETIC_CONTROL and 2 without an explicit stored domain.
The baseline is 50; operator additions remain. This report's completeness
query excludes `CTL-%` capacity slots, so its denominator is 38 camera
records plus 18 slots (`gis/service.py::registry_gaps`). It is not a live-feed count.

## Estate

| | |
|---|---:|
| Cameras onboarded | 38 |
| Capacity slots (no stream, not graded) | 18 |
| Cameras with no capability sample | 6 |

## Departments

| Department | Cameras |
|---|---:|
| Home (Police) | 27 |
| Own feed (licensed footage) | 4 |
| Own estate | 2 |
| Panchayat | 2 |
| GSRTC | 1 |
| Health | 1 |
| Municipal Corporation | 1 |

Every expected department has at least one camera onboarded.

## Missing metadata

| Field | Missing | Of | Share | |
|---|---:|---:|---:|---|
| `vms` | 36 | 38 | 94.7% | `███████████████████████████·` |
| `storage_location` | 36 | 38 | 94.7% | `███████████████████████████·` |
| `retention_days` | 36 | 38 | 94.7% | `███████████████████████████·` |
| `vendor` | 36 | 38 | 94.7% | `███████████████████████████·` |
| `camera_type` | 32 | 38 | 84.2% | `████████████████████████····` |
| `coordinates` | 13 | 38 | 34.2% | `██████████··················` |

### What each blocks

- **`vms`** — which departmental VMS a feed must be integrated through.
- **`storage_location`** — whether footage sits in cloud or local storage.
- **`retention_days`** — how long footage survives, which bounds any retrospective investigation.
- **`vendor`** — vendor-specific SDK or ONVIF profile selection.
- **`camera_type`** — fixed or PTZ, which changes what analytics apply.
- **`coordinates`** — placement on the GIS map and any spatial query.

## Cameras with no capability sample

6 cameras have never been graded: `HLT-DEMO-01`, `MC-DEMO-01`, `OWN-MUM-ARTERIAL`, `OWN-MUM-AUTOSTAND`, `OWN-MUM-JUNCTION`, `OWN-MUM-QUEUE`

An ungraded camera is an absence of evidence about that camera, not
a poor grade. Run a capability sample to replace the unknown with a
measurement.

---

*Counted across the whole registry in SQL. A field listed here is one no department has supplied yet, not one the platform cannot hold — the column exists in the schema.*
