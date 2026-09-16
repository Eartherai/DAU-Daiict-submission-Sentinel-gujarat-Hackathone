# Sentinel contract probe

Timestamp UTC: `2026-09-16T14:21:31.113716+00:00`  
Client: `SaakshyaContractProbe/1.0`

## Decision

**Case:** `CATALOGUE_UNAVAILABLE_PLUS_PROTOCOL_AUTH_OK`  
**Ours vs external:** `EXTERNAL_FOR_CATALOGUE_AND_HLS_SESSION; CREDENTIALS_VALID`  
**Architecture failure:** `False`

Catalogue GET /api/ingest does not return JSON (RTSP host 404; CDN HTML Sign-in). RTSP advertises Basic; DESCRIBE+Basic=200; cam01 PyAV got H.264 frames. Direct WHEP POST without auth=401; with Authorization Basic=201 SDP. HLS on IP=404; CDN returns Sign-in HTML without SENTINEL_GRID_COOKIE. Not a MediaMTX architecture failure. Not a dead credential. Contract gap: catalogue/HLS session cookie. Intermittent TCP refuse on cam02/05 is external flakiness.

### Letter mapping (401 / access questions)

| Letter | Result |
|---|---|
| A credential problem | **No** — Basic auth succeeds for RTSP DESCRIBE and WHEP POST |
| B incorrect endpoint | Unknown until catalogue; configured URLs match guide templates |
| C stale catalogue / URL | Cannot verify — catalogue JSON unreachable |
| D auth mechanism mismatch | **No** — server advertises Basic; Basic works |
| E client implementation | **Partial** — WHEP browser must send `Authorization: Basic`; bare fetch 401/fails |
| F Sentinel sandbox access | **Partial** — catalogue + HLS need CDN session cookie |

## 1. Catalogue host

Authoritative JSON: **False**

| Attempt | Status | Result |
|---|---:|---|
| `http://103.250.160.189/api/ingest` | 404 | Not Found |
| `http://cctv.corp8.cloud/api/ingest` | 200 | HTML Sign-in SPA |
| `https://cctv.corp8.cloud/api/ingest` | 200 | HTML Sign-in SPA |
| `https://cctv.corp8.cloud/cameras.json` | 200 | HTML Sign-in SPA |

Live camera IDs from catalogue: **NONE** (catalogue unavailable)  
`SENTINEL_GRID_COOKIE`: not configured

## 2. Exact URLs (configured / guide — not catalogue-authoritative)

| ID | RTSP | WHEP | HLS (guide IP) |
|---|---|---|---|
| cam01 | `rtsp://103.250.160.189:8554/stream/cam01` | `http://103.250.160.189:8889/stream/cam01/whep` | `http://103.250.160.189/live/stream/cam01/index.m3u8` |
| cam02 | `rtsp://103.250.160.189:8554/stream/cam02` | `http://103.250.160.189:8889/stream/cam02/whep` | `http://103.250.160.189/live/stream/cam02/index.m3u8` |
| cam05 | `rtsp://103.250.160.189:8554/stream/cam05` | `http://103.250.160.189:8889/stream/cam05/whep` | `http://103.250.160.189/live/stream/cam05/index.m3u8` |

Catalogue vs configured match: **N/A** (no catalogue JSON)

## 3. RTSP auth mechanism

**Basic** (WWW-Authenticate). DESCRIBE without auth → 401. DESCRIBE with Basic → **200** (cam01, cam02).

## 4. RTSP result

| ID | TCP | DESCRIBE auth | SETUP | PLAY (minimal client) | PyAV frames | Codec |
|---|---|---:|---:|---:|---|---|
| cam01 | OK | 200 | 200 | 454 | **FRAME (5)** | h264 |
| cam02 | OK then refuse | 200 | fail/null | — | FAIL (connection refused) | — |
| cam05 | Connection refused | — | — | — | — | — |

## 5. Direct WHEP result

| ID | POST no auth | POST Basic | SDP answer |
|---|---:|---:|---|
| cam01 | 401 | **201** | yes |
| cam06 | 401 | 400 | False |

Browser bare fetch without Authorization failed (CORS/auth). HTTP POST with Basic proves WHEP access works.

## 6. Direct HLS result

| URL class | HTTP | Live sequence |
|---|---:|---|
| Guide IP `/live/stream/cam01/index.m3u8` | **404** | no |
| CDN `cctv.corp8.cloud/cam01/index.m3u8` | 200 HTML Sign-in | no |

## 7. First failing layer (contract)

1. **Catalogue** `/api/ingest` JSON — unavailable  
2. **HLS** — CDN session / IP 404  
3. Protocol auth itself is **not** failing when Basic is applied

## 8. OUR BUG vs EXTERNAL

| Item | Owner |
|---|---|
| Catalogue JSON + HLS Sign-in wall | **EXTERNAL** (need `SENTINEL_GRID_COOKIE` / organiser session) |
| Stream password Basic for RTSP/WHEP | **Works** — not dead credentials |
| cam02/cam05 intermittent connection refused | **EXTERNAL** flakiness |
| Browser WHEP without Authorization header | **OUR** client must send Basic |
| Minimal RTSP PLAY 454 | **OUR** hand-rolled session/track handling (PyAV still gets frames) |
| MediaMTX / scheduler architecture | **Not implicated** |

## Support evidence (external / catalogue)

- Camera IDs: cam01, cam02, cam05  
- Exact safe URLs: see table above  
- Client/version: `SaakshyaContractProbe/1.0`  
- UTC: `2026-09-16T14:21:31.113716+00:00`  
- Catalogue live confirmation: **UNAVAILABLE** (no JSON)  
- WHEP: no-auth 401 / Basic 201  
- RTSP cam01: Basic DESCRIBE 200 + PyAV H.264 frames  

Credentials: environment only. Not in this report.

Artifacts:
- `var/reports/phase10/sentinel_catalogue.json`
- `var/reports/phase10/sentinel_contract_probe.json`
