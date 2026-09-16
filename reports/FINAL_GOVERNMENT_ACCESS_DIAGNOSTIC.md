# Final government access diagnostic

Timestamp UTC: `2026-09-16T14:12:07.053349+00:00`

## Verdict

**Failure domain:** `EXTERNAL_ACCESS/AUTHENTICATION`  
**Architecture failure:** `False`

Credentials: environment-only (`SENTINEL_GRID_*`). Not printed. Not in argv. Not in this report.

Synthetic browser path previously MEASURED at 16/16 PASS. This diagnostic isolates government RTSP authentication.

## Per-camera

| Camera | Classification | DESCRIBE no-auth | DESCRIBE auth | SETUP | PLAY | PyAV | Relay 30s | WHEP | First fail |
|---|---|---:|---:|---:|---:|---|---|---|---|
| cam01 | AUTH_REJECTED | 401 | 401 | None | None | AUTH_401 | SKIPPED_NO_FRAME | SKIPPED_NO_FRAME | DESCRIBE_AUTH |
| cam02 | AUTH_REJECTED | 401 | 401 | None | None | AUTH_401 | SKIPPED_NO_FRAME | SKIPPED_NO_FRAME | DESCRIBE_AUTH |
| cam05 | AUTH_REJECTED | 401 | 401 | None | None | AUTH_401 | SKIPPED_NO_FRAME | SKIPPED_NO_FRAME | DESCRIBE_AUTH |

## Layer notes

1. **TCP** to `103.250.160.189:8554` — reachability only.
2. **DESCRIBE/SETUP/PLAY** — RTSP with `Authorization` header (not URL authority).
3. **PyAV** — ephemeral in-memory authority injection required by libavformat; errors redacted.
4. **Relay / WHEP** — only attempted after authenticated frames.

## Interpretation

Government endpoint is reachable over TCP but rejects authentication (HTTP/RTSP 401) with the configured fresh credentials. This is **EXTERNAL_ACCESS/AUTHENTICATION**, not a MediaMTX/WHEP architecture failure. Do not rewrite the media path until authenticated PLAY succeeds.

## Artifacts

- `var/reports/phase10/government_access_diagnostic.json`
- Secret scan required after this run.
