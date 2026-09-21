# DIRECT WHEP — THE ARCHITECTURE THAT ACTUALLY WORKS

2026-09-20, ~05:00 IST. Verified in the real application against the live
Sentinel grid.

## Result

```
plane            direct_whep    relay: false    hub: false
local decode processes                        0
live simultaneously                          17
resolution                 1920x1080 / 1280x720
currentTime ratio                          1.00
scroll -> new tiles opened                   12
```

## What was wrong for the whole session

The local relay was the wrong architecture, and every problem chased for hours
was a symptom of it:

| symptom | actual cause |
|---|---|
| 30-camera wall collapses | software-decoding 30x1080p30 falls behind; RTSP socket backs up; grid resets the slow reader |
| `ConnectionResetError` / `BrokenPipeError` | same - the grid disconnecting a reader that cannot keep up |
| repeated 401 lockouts | restarting 30 RTSP ingests; the grid still counts the old sessions |
| "cheap quality" | relay re-encoded 1920x1080 down to 360p, later 480p |
| passthrough undecodable | a packet copy cannot synthesise the IDR a WHEP joiner needs |

None of it was necessary. **The grid already serves the browser directly.**

## The integration contract, which settles it

From the Sentinel integration reference:

- `RTSP  rtsp://<host>:8554/stream/<id>` — *intended for AI inference*
- `WHEP  http://<host>:8889/stream/<id>/whep` — **intended for low-latency browser preview**
- `HLS   http://<host>/live/stream/<id>/index.m3u8` — *dashboards, mobile*

and, decisively:

> "When a client connects, the gateway replays its buffered group-of-pictures
> so the decoder can start at a keyframe."

The grid solves the exact keyframe-join problem that made local passthrough
undecodable. RTSP was only ever the AI plane. Ingesting RTSP to re-publish it
to the browser re-did, badly, work the grid already does.

## Architecture now

```
browser ──SDP offer──> SAAKSHYA (adds Basic auth) ──> Sentinel :8889 WHEP
browser <────────────── media, peer-to-peer ──────────── Sentinel
```

The credential stays in this process: signaling is proxied, media is not. The
browser never receives the grid password. Verified: `OPTIONS /stream/cam01/whep`
answers 401 without credentials and 204 with them.

The proxy already existed (`routes_investigation.camera_whep`) — it was gated
off whenever the relay was running. Turning the relay off was most of the work.

Launch:

```
SAAKSHYA_LOCAL_RELAY=0 SAAKSHYA_MEDIA_HUB=0
```

No MediaMTX, no publishers, no transcode, nothing to cool down, and a restart
can no longer lock the account, because the app holds no RTSP sessions at all.

## Viewport-following streams

All 30 cameras are on a scrolling 3-column wall of large tiles. Streams follow
the viewport rather than the wall:

- open for tiles within one screen above/below, ranked by distance from screen centre
- budget 12 concurrent, honouring "open only the cameras you are actively processing"
- 15s grace after a tile scrolls away, so scrolling back does not renegotiate
- re-evaluated on scroll and resize, debounced 180ms

**The bug that made this look broken:** the budget was applied with
`.slice(0, N)` over DOM order. The prefetch margin keeps far more tiles
eligible than the budget allows, so the earliest tiles in the document won
every time and the selection never changed no matter where the operator
looked. Ranking by distance from the viewport centre is what makes streams
actually follow the scroll. Measured after the fix: scrolling to 60% opened
12 new sessions for the tiles scrolled into.

## Fixes that stand independent of the plane

| file | change |
|---|---|
| `ui/style.css` | tile `min-height: 172px`, `#live-grid min-height: 540px` — the grid was collapsing to 24px with 2px tiles, so the scheduler (correctly refusing tiles under 8px) opened **zero** streams. This was the original "nothing is live". |
| `ui/style.css` | `object-fit: cover` for video; stills keep `contain` |
| `ui/style.css` | explicit grid columns; `auto-fill` against fixed rows was clipping tiles out of existence |
| `ui/style.css` | wall-30 Grid = scrolling large tiles; Dense = 6x5 control room |
| `ui/app.js` | streams ranked by viewport proximity; scroll/resize listeners; 15s grace |
| `ui/app.js` | `wallCams` prefers relay-published cameras (relevant when a relay is used) |
| `relay_publisher.py` | codec read from the open stream — the hardcoded HEVC list named cam17/cam22, both H.264; the real HEVC cameras are cam06/12/18/26 |
| `relay_publisher.py` | auth backoff jitter + circuit breaker (4-7 -> 7-14 -> 14-29 -> 21-44 min) |
| `relay_publisher.py` | VideoToolbox decode with software fallback |
| `relay.py` | `SAAKSHYA_RELAY_MAX_CAMERAS`; corrected HEVC set; passthrough flag with its measurement recorded |

The relay path is left intact and improved. It remains the right tool for the
AI plane, which genuinely needs RTSP frames locally.

## Not yet done

Sustained soak. Real AI on a current camera. ANPR. M1-M4. Full operator
click-through. Recording. HLS fallback for restricted networks (the catalogue
and HLS sit behind a form login, not Basic auth — `SENTINEL_GRID_COOKIE`).
