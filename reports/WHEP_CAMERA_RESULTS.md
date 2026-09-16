# WHEP camera results

## Local synthetic control

**PASS** — C-014 certified on MediaMTX → WHEP → Chromium after B-frame fix.
See `PHASE8C_BROWSER_CERTIFICATION.md`.

## Government cameras via managed local gateway

| Camera | Negotiation | First decoded frame | Continuous soak | Notes |
|---|---|---|---|---|
| cam01 | PASS (~140 ms) | PASS (~1.5 s) | PASS (12 s, ~169 frames, 0 loss) | Local gateway `stream/gov-cam01`; credentials never sent to browser |
| cam03 | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Not run this cycle |
| cam18 | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Not run this cycle |
| cam22 | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Not run this cycle |
| cam26 | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Not run this cycle |
| cam30 | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | Not run this cycle |

Direct unauthenticated probes of the government WHEP host are not treated as
results. Browser clients must use the same-origin signaling proxy or a local
managed gateway path.
