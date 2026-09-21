# UI OVERHAUL — MEASURED AGAINST §66

§66: *"A prettier dashboard with worse media is a FAILURE."* So every change was
measured against the media baseline, not against a mockup.

## Before / after, 1920x1080, live Sentinel

| | before | after (CONTROL ROOM) |
|---|---|---|
| video share of viewport | 34.6% | **90.3%** |
| live sessions | 8 | **19** |
| open sessions | 12 | 30 |
| mean currentTime ratio | 1.04 | **1.01** |
| long tasks >50 ms (20s) | 0 | **0** |
| DOM nodes | 2332 | 2404 |
| JS heap | 9.7 MB | 10.3 MB |

Media improved. §66 satisfied.

## §46 — two policies, named on screen, never switched silently

| | CONTROL ROOM | OPTIMIZED VIEW |
|---|---|---|
| layout | Dense, 6x5 | Grid, 3-wide scrolling |
| budget | 30 (one per tile) | 12, viewport-ranked |
| prefetch | whole wall | one screen either side |

The badge in the live header states which is in force. The budget and the
prefetch window both key off it, so the contract and the behaviour cannot drift
apart.

## §38/§47 — command mode

Navigation collapses to a 52px icon rail, the two chrome bands collapse, and
the analytics / preset / filter toolbars fold behind a **COMMAND BAR** toggle.
Default is collapsed: the wall is fully usable without the command bar, which
is what took video from a third of the screen to 90%.

**A bug worth recording.** The first attempt used `display: none` on the two
chrome bands. That removes them as *grid items*, so auto-placement pulled the
nav and the entire main content up into the zero-height rows meant for those
bands, and the whole workspace rendered at zero height - a blank page. They are
now collapsed (`height: 0; visibility: hidden`) while staying grid items.

## §40/§45 — what does not destroy media

Verified in the running app:

- polling on the direct plane runs at 20s and only queues stills for tiles **without** a session; it never rebuilds the wall
- the layout buttons change `data-layout` and re-rank; they do not repaint
- the Command Bar toggle re-ranks; it does not repaint
- `syncTileWhep` reattaches an existing session's stream rather than renegotiating

A wall-size change still repaints and recreates `<video>` nodes. The
`RTCPeerConnection` survives and the stream is re-attached, so the session is
not renegotiated - but the node churn is real and is the remaining §40 gap.

## §42/§43 — loops

`requestVideoFrameCallback` drives per-tile liveness only; it never triggers an
application render. Scroll and resize listeners are passive and debounced to
180ms. Timers are separated: telemetry 500ms, per-session stats 1s, still queue
250ms, direct-plane health 20s.

## Not done from §36-§67

Tile-controller refactor (§41) - the wall still queries the DOM rather than
holding `cameraId -> TileController`. Wall-size repaint (§40). Memory soak
(§61). Alert rail (§51), target inspector (§52), map panel (§53), AI overlay
budget (§54), keyboard navigation (§63), and the full regression matrix (§65).

## The 11 tiles that are not live

30 sessions open, 19 delivering. The integration contract is explicit that
every client receives its own copy of the stream and asks callers to open only
what they are actively using. CONTROL ROOM asks the grid for thirty copies at
once; some are not served. This is a property of the grid, not of the browser -
OPTIMIZED VIEW exists precisely because it asks for fewer.
