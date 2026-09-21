# The empty Live wall: connection starvation, not a paint bug

## Symptom

Entering Live directly painted thirty tiles in about five seconds, every time.
Reaching Live by clicking the nav after Overview, Cameras, Analytics and the
map left the grid completely empty — not black tiles, no tiles at all — and it
stayed empty however long you waited. The demo recorder failed on exactly this
step, and had carried a comment describing the behaviour as an app defect
"worth fixing properly" with a reload-and-retry workaround that also stopped
working.

## What it was not

- Not a paint bug. `paintLiveWorkspace` was never reached.
- Not an exception. A trap on `error` and `unhandledrejection` caught nothing.
- Not the generation guard, and not the `active` check. Both passed.
- Not a filter. `liveDistrict` and `livePriority` were both `all`.
- Not the server. `/gis/cameras?zoom=16` answers in **0.28s** to curl while the
  browser tab timed out on the same URL at 15s.

## What it was

The browser allows **six connections per origin, shared across the whole
profile** — not per tab. Snapshot captures on this estate take one to ten
seconds each. Two code paths issued them without bound or cancellation:

1. `sharedSnapshot` — queued and bounded, but its `fetch` carried no
   `AbortSignal`, so leaving Live cleared the pending queue while the captures
   already in flight kept their sockets.
2. `fillRegistryStill` — the map's camera rail, called in a **`for` loop, one
   fetch per camera**, with no queue, no concurrency limit and no cancellation.

Visiting the map therefore issued ~30 uncancellable multi-second captures. On
entering Live, the loader's `await api("/gis/cameras?zoom=16")` queued behind
them and effectively never returned. The loader sat on that await forever, so
`clear(box)` had run but nothing was ever appended.

This is why the failure depended on the *route* rather than on Live itself:
entered cold, the camera-list request goes out before the snapshot storm;
entered from the map, it goes out behind it.

Proof: with the app tab open, a **newly created second tab** also timed out on
the same request. Closing the first tab dropped that same request to **3ms**.

## The fix

- A `snapshotAborts` registry of `AbortController`s; every snapshot fetch, from
  both paths, registers one and clears it on settle.
- `abortSnapshots()` aborts all in-flight captures and empties both queues. It
  runs when leaving Live and again at the top of `loaders.live`, before the
  camera-list request, so that request is never issued into a saturated pool.
- The registry rail is bounded to **three** concurrent captures. It is a row of
  thumbnails and should not hold the entire connection budget.
- An `AbortError` is treated as bookkeeping, not a capture failure: it no
  longer writes `state.telemetry.snapshot.error` and no longer marks the tile
  `failed`. Leaving Live used to look like an estate fault.

## Result

On the exact path that failed — Overview → Cameras → Analytics → Map → Live —
the wall goes from **0 tiles** to **60** (thirty cameras across the grid and
the accessible table). Verified in a real 1600x900 viewport.

## Two measurement traps worth keeping

1. **A collapsed browser pane reports `innerWidth: 0`.** Tiles then measure 2px,
   and `syncTileWhep` correctly refuses to open sessions for tiles nobody can
   see. That refusal is the feature, not the bug. Check the viewport before
   concluding the wall is broken.
2. **`video.currentTime` does not advance on a WebRTC MediaStream.** It is not a
   liveness signal. `framesDecoded` from `getStats()` is.
