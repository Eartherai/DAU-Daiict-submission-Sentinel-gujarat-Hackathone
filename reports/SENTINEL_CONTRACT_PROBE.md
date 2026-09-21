# Sentinel contract probe

Timestamp UTC: `2026-09-19T18:58:21.761751+00:00`  
Client: `SaakshyaContractProbe/1.0`

## Decision

**Case:** `F_OR_G_SOURCE_OK`  
**Ours vs external:** `OUR_BUG_IF_APP_FAILS`  
**Architecture failure:** `False`

RTSP frames arrive — source proven; app/relay issues are ours.

## 1. Catalogue host

| Attempt URL | Status | Result |
|---|---:|---|
| `https://cctv.corp8.cloud/cameras.json` | 200 | html_login_or_spa |
| `http://103.250.160.189/api/ingest` | 404 | HTTPError: HTTP Error 404: Not Found |
| `http://cctv.corp8.cloud/api/ingest` | 200 | html_login_or_spa |
| `https://cctv.corp8.cloud/api/ingest` | 200 | html_login_or_spa |
| `http://cctv.corp8.cloud/cameras.json` | 200 | html_login_or_spa |

Authoritative JSON reachable: **False**  
Live camera IDs from catalogue: `NONE — catalogue unavailable`

## 2. Endpoint comparison (cam01 / cam02 / cam05)

| ID | In catalogue | Catalogue RTSP | Configured RTSP | Match |
|---|---|---|---|---|
| cam01 | False | `None` | `rtsp://103.250.160.189:8554/stream/cam01` | None |

## 3. RTSP (TCP)

| ID | Auth advertised | Header trials | DESCRIBE auth | SETUP | PLAY | PyAV | First fail |
|---|---|---|---:|---:|---:|---|---|
| cam01 | basic | `{"Basic": {"status": 200, "error": null}}` | 200 | 200 | 454 | FRAME | PLAY |

## 4. Direct WHEP (no local MediaMTX)

| ID | Status | Negotiate HTTP | First frame ms | ICE | Error |
|---|---|---:|---:|---|---|
| cam01 | FAIL | None | None | None | signal timed out |
| cam06 | FAIL | None | None | None | signal timed out |

## 5. Direct HLS

| Key | Status | Playlist HTTP | Sequence advanced |
|---|---|---:|---|
| cam01:guide_ip | FAIL | 404 | False |
| cam01:cdn | FAIL | 200 | False |
| cam01:configured_template | FAIL | 200 | False |

## Support evidence (if external)

- Camera IDs: ['cam01']
- Exact URLs (safe): see JSON `support_evidence.exact_urls_safe`
- Client/version: `SaakshyaContractProbe/1.0`
- UTC timestamp: `2026-09-19T18:58:21.761751+00:00`
- Catalogue live confirmation: **unavailable** (no JSON from `/api/ingest`)
- Client-side errors: redacted in JSON `support_evidence.client_side_error_summary`

Credentials: environment only. Not in this report.

Artifacts:
- `var/reports/phase10/sentinel_catalogue.json`
- `var/reports/phase10/sentinel_contract_probe.json`
