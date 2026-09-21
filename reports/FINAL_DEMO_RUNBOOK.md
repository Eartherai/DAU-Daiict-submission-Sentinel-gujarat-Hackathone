# Final demo runbook

## Judge commands

1. `cd saakshya && make live-serve` (or `make serve` if the grid is down). Maps: `GOOGLE_MAPS_API_KEY` in gitignored `.env.local` only.
2. Sign in. Set Case + Purpose before search.
3. **OPERATIONS** — 30-camera government wall. Domain badge GOVERNMENT. LIVE vs PREVIEW. Do not claim 50 government live feeds.
4. Preset **50-CAMERA WALL** — 30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL. CONTROL tiles must never say GOVERNMENT.
5. **INTELLIGENCE** — OWN-PEOPLE and OWN-TRAFFIC (**file replay**, not live). Modes VIDEO / VEHICLES / PEOPLE / BOTH / ANPR / FULL / INCIDENT. Cadence FAST / BALANCED / DEEP.
6. COMPARE uses the same video element (no second WHEP).
7. Watchlist DEMO/CONTROLLED TEST: VIEW VIDEO → TRACK → ROUTE → GIS → ACKNOWLEDGE / INVESTIGATE.
8. **WHERE DID THE TARGET GO?** FIRST SEEN / NEXT / LAST SEEN with elapsed, distance, MATCH/LIKELY/CONTRADICTION reason.
9. JUMP TO EVENT: government EVENT TIMESTAMP vs CURRENT LIVE POSITION (do not fake seek). Own-feed file can seek; label Replay / Recorded.
10. **SYSTEM → Connected systems** — DEMO / TEST only.
11. GIS: Google Maps when the env key is loaded; OSM raster fallback otherwise.
12. KPI / resource panel: NOT_MEASURED stays NOT_MEASURED. GPU is never 0%.

## Demo-ready configuration

{
  "wall": "30 GOVERNMENT + 2 OWN_FEED (OWN-PEOPLE, OWN-TRAFFIC) + 18 SYNTHETIC_CONTROL",
  "intelligence": "INTELLIGENCE mode on the two own feeds",
  "system": "SYSTEM \u2192 Connected systems (DEMO / TEST)",
  "maps": "GOOGLE_MAPS_API_KEY from gitignored .env.local; loader /maps/google-api; key not in /config",
  "commands": [
    "make live-serve",
    "OPERATIONS \u2192 30-camera government wall (Direct Sentinel WHEP)",
    "OPERATIONS \u2192 50-CAMERA WALL (logical badges)",
    "INTELLIGENCE \u2192 OWN-PEOPLE / OWN-TRAFFIC (file replay)",
    "TRACK TARGET / ROUTE / GIS / EVIDENCE on a watchlist plate",
    "SYSTEM \u2192 Connected systems (DEMO / TEST)"
  ]
}
