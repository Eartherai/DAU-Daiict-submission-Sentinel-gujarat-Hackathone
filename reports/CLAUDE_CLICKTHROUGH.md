# OPERATOR CLICK-THROUGH — FINDINGS

Every nav destination exercised against the live app, 1920x1080.

## All nine views load

| view | nodes | state |
|---|---|---|
| Overview | 178 | estate health, capability, open alerts |
| Investigate | 111 | mark search, near matches, watchlist filter |
| Alerts | 114 | 4 alerts, New / Acknowledged / Investigating |
| Evidence | 38 | "Chain verified — 2 record(s) need reading before use" |
| Live | 1619 | 30-camera wall |
| Intelligence | 188 | Model 4 central intelligence |
| Cameras | 825 | "ANPR: 21 UNKNOWN · 29 UNSUITABLE · 9 published a mark" |
| Analytics | 112 | capability across the estate (~10s to load) |
| System | 310 | rank → role RBAC mapping |

Wall sizes switch correctly: 30 → 3 columns, 12 and 16 → 4 columns.

## Three defects found and fixed

### 1. Entering Live showed a wall with no video

Leaving Live calls `closeTileWhepAll()`. Returning to it relied on a post-paint
callback inside the wall painter, which does not run on every path into the
view. Measured:

```
entered Live from nav      videos 0
dispatched scroll event    videos 0     (listener was never bound)
clicked a layout button    videos 16, decoding 10
```

So the wall sat empty until the operator happened to click a layout or
wall-size control, which re-ran the sync as a side effect. **This is the
"nothing is live" experience** reported throughout this project.

First fix attempt failed for an instructive reason: the wall painter is async,
so two animation frames after `show('live')` the grid is still empty, every
tile measures 0x0, the scheduler correctly skips them all — and nothing ever
retries. Establishing the plane now retries at 0 / 300 / 900 / 2000 / 4000ms.
`syncTileWhep` is idempotent, so repeating it costs nothing.

After: `wall-focus` applied, 30 tiles, 12 sessions, 8 decoding, status
"8 live sessions".

### 2. Asset cache versions were hardcoded and stale

`index.html` pinned `app.js?v=cr135` and `style.css?v=cr108`. A browser holding
those keys never re-fetches, so an edited file is served by the API and
silently ignored by the page. This is a deployment hazard that would have made
a demo recording show stale code — and it makes every "my change had no effect"
investigation start from a false premise.

The version is now a SHA-256 prefix of the bytes being served, computed on each
request, so the URL changes when and only when the file does.

### 3. Token expiry looked like six broken views

A first pass showed Overview, Alerts, Evidence, Cameras, Analytics and System
rendering almost nothing. The cause was an expired bearer token, and each view
was correctly reporting `NOT_AUTHENTICATED: token expired` rather than failing
silently. Not a defect — the app behaved correctly. Recorded because the
failure mode reads exactly like six broken screens.

## Second pass — the rest of the surface

**All 13 nav destinations load.** Beyond the nine above: Estate map, Cases,
Copilot, Audit log.

### Layouts preserve media (§45)

Grid -> Focus -> Two-up -> Tab -> Grid, with the session count sampled at each
step:

```
grid    12 videos, 8 decoding
focus   12 videos, 8 decoding
twoup   12 videos, 8 decoding
tab     12 videos, 8 decoding
grid    12 videos, 8 decoding
```

Not one renegotiation across five transitions. Telemetry panel reports
"8 active / 12 total" and "Visible tiles 4 of 30" — browser-observable values
only, which is what it claims to be.

### Alerts

Four alerts, filters New / Acknowledged / Investigating / Resolved / All, and
per-alert VIEW VIDEO · TRACK VEHICLE · ROUTE · OPEN GIS · ACKNOWLEDGE.
Acknowledging `GJ11BR0928` moved it out of New and into Acknowledged, and the
change propagated to the Intelligence watchlist panel
(`HIGH · ACKNOWLEDGED · 89.9%`) and into the audit log.

### Audit

`chain verified · 400 entries`, and the top row is the acknowledge itself:

```
2026-09-20 05:06:56  supervisor.live  SUPERVISOR  alert_acknowledge
FIR-000/2026  "ui redesign review"  AL01M2YGSDW2XT7RA52FWFQQYWTG
```

The case id and purpose typed at sign-in are carried onto the action. That is
the traceability requirement working end to end.

### Estate map

`41 on the map · 9 in the registry without coordinates · 50 registered`, with
Fit estate and colour-by Health / ANPR capability.

### Intelligence

Plate search for `GJ11BR0928` returns its real sightings (cam06, Junagadh,
car), each with OPEN VIDEO · TRACK VEHICLE · SHOW GIS · SHOW HISTORY. Category
filters: ALL / STOLEN VEHICLE / WANTED VEHICLE / WANTED PERSON / MISSING PERSON
/ BLACKLIST / CUSTOM.

## Three things I called broken that were not

Recorded because each one reads exactly like a defect:

1. **Six views "empty"** — an expired bearer token. Each view was correctly
   reporting `NOT_AUTHENTICATED` rather than failing silently.
2. **Audit log "empty"** — it had not finished loading. It renders 400 rows.
3. **Intelligence panels "empty"** — they populate on the app's own events; my
   synthetic `dispatchEvent` had not triggered the handler.

`/watchlist` returning nothing is also not a defect: it is purpose-bound and
answers *"watchlist:read is purpose-bound: supply a case id (X-Case-Id). Open a
case first if one does not exist."* That is a governance control working. The
panel could surface that sentence rather than rendering blank.

## Genuinely still open

- Analytics takes ~10s to render; it loads, but slowly enough to look stuck.
- Map interaction (zoom, pan, marker -> camera) not exercised — the pane was not
  displayed, so pointer input could not be driven.
- Watchlist add / remove / activate through the UI (the API path is proven).


## Wall-size change dropped live video into cached stills — fixed

Changing wall size repaints the grid, which destroys the tiles the media
scheduler was tracking. The layout buttons re-synced after their repaint; the
wall-size and priority buttons did not. The wall therefore fell back to the
still pump and reported `0 live sessions`, every tile a cached capture labelled
*"not live video"* — honest, and the wrong thing to be honest about.

Both handlers now re-sync after the repaint, retried at 0/300/900/2000ms
because the repaint is async. Measured across every size:

```
wall 12   12 tiles  12 videos  8 decoding  0 stills  "8 live sessions"
wall 16   16 tiles  12 videos  8 decoding  0 stills  "8 live sessions"
wall 25   25 tiles  12 videos  8 decoding  0 stills  "8 live sessions"
wall 30   30 tiles  12 videos  8 decoding  0 stills  "8 live sessions"
wall 12   12 tiles  12 videos  8 decoding  0 stills  "8 live sessions"
```

### A self-inflicted failure worth recording

The first recording after this fix still failed, with the Live step timing out
waiting for `#live .live-tile`. The cause was me: the browser pane I had been
testing in was holding twelve WHEP sessions on the same grid account the
recorder needed. Releasing them and waiting two minutes for the grid to reap
the sessions fixed it.

That is the same session-budget constraint that produced the 401 cascades
earlier in this project, arriving from a new direction — two clients of the
same account competing. Worth knowing before a live demonstration: close every
other window on the grid first.
