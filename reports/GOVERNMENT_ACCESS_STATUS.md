# Government access status

## Current execution environment

Checked 2026-09-16 05:47 IST. Secret values were not printed or persisted.

| Layer | Status | Evidence |
|---|---|---|
| Catalogue access | **UNAVAILABLE** | `https://cctv.corp8.cloud/cameras.json` timed out in the bounded request |
| Camera metadata | **YES (local registry)** | 30 registered rows are present in the local store; authoritative catalogue session is not available |
| RTSP authorization | **FAIL** | `cam01` returned HTTP 401 before media opened |
| WHEP authorization | **UNVERIFIED** | endpoint exists; unauthenticated GET returned HTTP 405 because WHEP requires POST SDP negotiation |
| HLS authorization | **UNVERIFIED** | direct HLS URL returned HTTP 302; redirect target/session was not followed |
| Credentials present | **NO** | supported variables are absent: email/password, cookie, token, basic |
| Credentials configured | **NO** | no secret runtime configuration was present |
| Media access | **NO** | no authenticated frame was received in this run |

## Interpretation

This is an access/configuration block, not evidence that the 30 encoders are
corrupt or that the hackathon network is the root cause. The previous concurrent
probe also recorded 30/30 RTSP HTTP 401 responses. A real certification must
start with an approved session or runtime secret injection, prove one camera's
continuous frame progression, and only then launch 30 concurrent workers.

## Safe next step

Set the organizer-approved secrets in the process environment using the existing
mechanism documented in `src/saakshya/live/credentials.py` and `src/saakshya/live/grid.py`;
do not place them in files, reports, screenshots, frontend bundles, or git.
