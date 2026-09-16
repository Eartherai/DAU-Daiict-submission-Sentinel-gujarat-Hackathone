# Government authentication validation

## Run

The approved email/password were injected into one ephemeral process through
`SENTINEL_GRID_EMAIL` and `SENTINEL_GRID_PASSWORD`. Values were not printed,
stored, logged, placed in reports, or sent to the frontend.

| Layer | Result | Evidence |
| --- | --- | --- |
| Catalogue | FAIL / unavailable | Existing catalogue session mechanism requires a CDN cookie/token/basic credential; the supplied RTSP authority credentials do not authenticate the catalogue request |
| Camera metadata | PASS | Local registry contains 30 configured camera rows |
| RTSP auth | PASS | cam01 and the concurrent run authenticated with RTSP/TCP using the approved authority credentials |
| WHEP auth | UNTESTED | WHEP requires SDP POST negotiation; no aiortc/browser session was available in the CLI run |
| HLS auth | UNVERIFIED | direct HLS returned HTTP 302; the authenticated CDN/session mechanism was not available |
| Media session | PARTIAL | RTSP media opened and decoded for representative cameras; several cameras opened but produced no frames or decode errors in the bounded run |

## Security

The credentials are not present in source, reports, screenshots, generated
JSON, or the frontend bundle. Future runs must use the same ephemeral runtime
injection and must not add catalogue cookies or tokens to this repository.
