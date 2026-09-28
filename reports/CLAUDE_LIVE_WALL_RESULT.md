# LIVE WALL — VERIFIED RESULT

Historical measurement record. Concurrent live counts below are **MEASURED
DURING A TEST WINDOW**, not sandbox limits. Current support guidance and wall
policies: `docs/SENTINEL_SUPPORT_CLARIFICATION.md`.

Measured 2026-09-20 03:34–03:40 IST in the **actual SAAKSHYA application**
(`http://127.0.0.1:8083`), against the live Sentinel government grid. Not a
test page, not a harness.

## Result

```
tiles            12
videoElements    12
verdicts         { LIVE: 12 }
resolutions      [ "1280x720" ]
app's own label  "12 of 12 showing a frame"
```

Per-tile `currentTime` advance over a 15s window (ratio 1.0 = real time):

| cam | ratio | cam | ratio | cam | ratio |
|---|---|---|---|---|---|
| cam01 | 0.99 | cam05 | 0.97 | cam09 | 0.91 |
| cam02 | 0.99 | cam06 | 1.06 | cam10 | 1.05 |
| cam03 | 0.99 | cam07 | 1.15 | cam11 | 1.05 |
| cam04 | 0.75 | cam08 | 1.17 | cam12 | 0.37 |

Relay at the same moment: **17/17 ready, 0 × 401, 0 broken pipes, load 6.59.**

## The defect that made the wall look dead

The wall was not failing to play video. **It was never asked to.**

```
gridHeight 24px · tileHeight 2px · tilesPassingGate 0/12 · videoCount 0
```

`#live-grid { min-height: 0 }` is an `#id` rule and overrode
`.live-grid { min-height: 360px }`. As a flex child with no spare space left
by the panel above it, the grid collapsed to 24px and every tile to ~2px.
`syncTileWhep` then behaved exactly as designed — it refuses to open a session
for a tile under 8px — so it opened **zero**.

This is the whole standalone-vs-application gap. A standalone page lays its own
tiles out and never hits it.

After the floors: `gridHeight 540 · tileHeight 172 · gate 12/12 · video 12`.

## Capacity, measured not guessed

Staged ramp, one account, 1280x720/15fps:

| stage | relay ready | flowing | publisher CPU | 401s | load |
|---|---|---|---|---|---|
| 1 | 1 | 1 | 12.4% | 0 | 4.9 |
| 5 | 5 | 5 | 32.0% | 0 | 6.2 |
| 10 | 9 | 10 | 46.7% | 0 | 5.4 |
| **15** | **15** | **15** | **45.6%** | **0** | **5.5** |
| 20 | 19 | 20 | 34.9% | 0 | 5.6 |
| 25 | 23 | 24 | 62.3% | 0 | 5.1 |
| 30 | 27 | 24 | 53.2% | 0 | 6.0 |

Sustained operation at 30 x 720p then collapsed:

```
63  BrokenPipeError        <- trigger
30  HTTPUnauthorizedError  <- consequence
18  InvalidDataError
```

Broken pipes and upstream 401 responses coincided with the collapse.
The logs do not establish whether upstream session retention caused it.
The measured live count is specific to this test window.

15 x 720p held during this ramp on this host. This is not a sandbox quota
or a universal bridge maximum; longer soaks were not completed.

## Upstream availability during the test window

Fast publisher restarts coincided with failed opens; after 15 minutes of
idle time, a single probe succeeded twice in this window. The upstream
session lifetime and account-lock mechanism were not verified. Organisers
subsequently confirmed no fixed participant-facing session limit; see
`docs/SENTINEL_SUPPORT_CLARIFICATION.md`.

Sources are `h264 High/Main 1920x1080 @ 25-30fps` — the relay had been
publishing 360p/8fps, discarding ~94% of the pixels.

## Changes

| File | Change |
|---|---|
| `ui/style.css` | tile `min-height: 172px` and `#live-grid min-height: 540px` — collapse is now structurally impossible; 25/30 walls opt out below |
| `ui/style.css` | `object-fit: cover` for video (stills keep `contain`) |
| `ui/style.css` | explicit grid columns per wall size; `auto-fill` against fixed rows had been clipping tiles out of existence |
| `ui/app.js` | default wall 30 -> 12 |
| `ui/app.js` | `wallCams` orders relay-published cameras first, so tiles are not spent on cameras with no stream |
| `relay_publisher.py` | auth backoff jitter (0.7-1.45x) — observed 288s/412s instead of lockstep 300s |
| `relay_publisher.py` | circuit breaker: consecutive refusals escalate 4-7 -> 7-14 -> 14-29 -> capped 21-44 min |
| `relay.py` | `SAAKSHYA_RELAY_MAX_CAMERAS` cap |
| `relay.py` | defaults raised 150k/180p/5fps -> 2500k/720p/15fps |

`node --check` passes; CSS braces balanced; `relay_publisher.py` ruff clean.
Two pre-existing ruff errors remain in `relay.py` (lines 53, 480), untouched.

## Launch

```
SAAKSHYA_RELAY_MAX_CAMERAS=15 SAAKSHYA_RELAY_MAX_HEIGHT=720 \
SAAKSHYA_RELAY_FPS=15 SAAKSHYA_RELAY_BITRATE=2500k SAAKSHYA_RELAY_STAGGER=2.5
```

Both accounts configured; the relay splits them by camera parity, ~7-8 each.

## Not done

Sustained 5/15/30-minute soaks. Real AI on a current government camera. ANPR.
M1-M4. Full operator click-through. Final recording. None attempted — the wall
has held 12/12 for minutes, not hours.
