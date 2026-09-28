# Registry API

Generated 2026-09-28 10:54:37Z from this worktree's OpenAPI schema in process,
without starting a server or contacting a network. This verifies the declared
contract, not a live endpoint test.

The registry is Model 1: camera metadata, onboarding and gap reporting.
It holds what departments supply and reports what they have not — it
never invents a value to fill a column.

## Authentication

Every request carries a bearer token and is written to the hash-chained
audit log with its actor, role and purpose. Onboarding requires
`admin:write`; reading the registry requires `camera:read`. A role that
lacks the permission is refused before the request reaches the store,
and the refusal is audited like any other action.

```
Authorization: Bearer <token>
```

## Endpoints

### `GET /gis/cameras`

Camera locations, health and capability.

| Parameter | In | Type | Default |
|---|---|---|---|
| `bbox` | query | string | — |
| `zoom` | query | number | `11.0` |
| `district` | query | string | — |
| `department` | query | string | — |
| `tier` | query | string | — |
| `status` | query | string | — |
| `capability` | query | string | — |
| `grade` | query | string | — |
| `codec` | query | string | — |
| `region` | query | string | — |
| `camera_type` | query | string | — |
| `ai_status` | query | string | — |
| `q` | query | string | — |
| `source_domain` | query | string | — |
| `limit` | query | integer | `1500` |
| `authorization` | header | string | — |
| `X-Case-Id` | header | string | — |
| `X-Purpose` | header | string | — |
| `X-Purpose-Encoding` | header | string | — |


### `GET /gis/capability`

Measured capability per camera.

| Parameter | In | Type | Default |
|---|---|---|---|
| `bbox` | query | string | — |
| `district` | query | string | — |
| `time_band` | query | string | — |
| `authorization` | header | string | — |
| `X-Case-Id` | header | string | — |
| `X-Purpose` | header | string | — |
| `X-Purpose-Encoding` | header | string | — |


### `GET /gis/gaps`

Registry gap analysis (Model 1).

What the registry does not yet know about its own estate.

| Parameter | In | Type | Default |
|---|---|---|---|
| `authorization` | header | string | — |
| `X-Case-Id` | header | string | — |
| `X-Purpose` | header | string | — |
| `X-Purpose-Encoding` | header | string | — |


### `GET /registry/cameras/export.csv`

Export the registry.

The registry as a file a department can read, check and send back.

Round-trips with the importer: the columns written here are the columns it
accepts, so an export can be corrected in a spreadsheet and re-imported.

| Parameter | In | Type | Default |
|---|---|---|---|
| `department` | query | string | — |
| `include_slots` | query | boolean | `False` |
| `limit` | query | integer | `100000` |
| `authorization` | header | string | — |
| `X-Case-Id` | header | string | — |
| `X-Purpose` | header | string | — |
| `X-Purpose-Encoding` | header | string | — |


### `POST /registry/cameras/import`

Bulk camera onboarding (JSON).

| Parameter | In | Type | Default |
|---|---|---|---|
| `authorization` | header | string | — |
| `X-Case-Id` | header | string | — |
| `X-Purpose` | header | string | — |
| `X-Purpose-Encoding` | header | string | — |


### `POST /registry/cameras/import.csv`

Bulk camera onboarding (CSV).

The same import, from the spreadsheet a department actually holds.

The header names the columns; unknown columns are ignored rather than
refused, because a departmental export carries operational columns that are
none of this registry's business.

| Parameter | In | Type | Default |
|---|---|---|---|
| `update_existing` | query | boolean | `False` |
| `dry_run` | query | boolean | `False` |
| `authorization` | header | string | — |
| `X-Case-Id` | header | string | — |
| `X-Purpose` | header | string | — |
| `X-Purpose-Encoding` | header | string | — |


## Camera record

Every field a department may supply. Only `camera_id` is required:
a registry's purpose is to hold what is known and report what is
not, so a row carrying nothing but an identifier is a legitimate
entry that the gap report will then name.

| Field | Type | Required |
|---|---|---|
| `camera_id` | string | **yes** |
| `name` | string | no |
| `department` | string | no |
| `district` | string | no |
| `site` | string | no |
| `lat` | number | no |
| `lon` | number | no |
| `vendor` | string | no |
| `model_name` | string | no |
| `camera_type` | string | no |
| `vms` | string | no |
| `rtsp_url` | string | no |
| `hls_url` | string | no |
| `whep_url` | string | no |
| `codec` | string | no |
| `width` | integer | no |
| `height` | integer | no |
| `declared_fps` | integer | no |
| `storage_location` | string | no |
| `retention_days` | integer | no |
| `tier` | string | no |
| `owner` | string | no |
| `region` | string | no |
| `road` | string | no |
| `integration_model` | string | no |
| `maintenance_status` | string | no |
| `quality_note` | string | no |

## Worked examples

### Onboard two cameras

```
POST /registry/cameras/import
Content-Type: application/json

{
  "cameras": [
    {
      "camera_id": "MC-0001",
      "name": "Municipal gate",
      "department": "Municipal Corporation",
      "district": "Ahmedabad",
      "lat": 23.0301,
      "lon": 72.58,
      "vms": "Milestone",
      "storage_location": "cloud",
      "retention_days": 15
    },
    {
      "camera_id": "RTO-0007",
      "name": "Testing track",
      "department": "RTO",
      "district": "Rajkot"
    }
  ]
}
```

### Check a departmental spreadsheet without committing it

```
POST /registry/cameras/import.csv?dry_run=true
Content-Type: text/csv

camera_id,name,department,lat,lon,vms,retention_days
MC-0002,Riverfront east,Municipal Corporation,23.02,72.57,Milestone,15
```

### Ask the registry what it does not know

Example response fields, read-only 28 Sep snapshot (`reports/MODEL1_GAP_ANALYSIS.md`).

```
GET /gis/gaps

{
  "cameras": 38,
  "capacity_slots": 18,
  "departments_absent": [],
  "field_gaps": [
    {
      "field": "vms",
      "missing": 36,
      "of": 38,
      "pct": 94.7
    }
  ]
}
```

## Behaviour an integrator should rely on

- **An import applies wholly or not at all.** Rows are validated first;
  one bad row refuses the batch, naming the row number and the reason.
  A partial import would leave nobody able to say which half landed.
- **`dry_run` runs the same validation and writes nothing**, which is
  how a department checks a file before committing it.
- **Re-uploading cannot silently overwrite curation.** Amending an
  existing camera must be asked for with `update_existing`, so a stale
  spreadsheet cannot rewrite a position corrected by hand.
- **Export round-trips into import.** The columns written by
  `export.csv` are the columns `import.csv` accepts, so a file can be
  corrected in a spreadsheet and sent back.
- **Unknown CSV columns are ignored, not refused**, because a
  departmental export carries operational columns that are none of this
  registry's business.

For investigation, alerts, cases, operations and edge APIs, see `docs/API.md`
in the repository. That full API document is not currently in the pack.
