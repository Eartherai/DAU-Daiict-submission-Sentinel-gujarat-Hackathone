# 30-CAMERA ROOT CAUSE — STANDALONE vs THE ACTUAL APPLICATION

Measured 2026-09-20 01:30–02:05 IST against the **live Sentinel government
grid** (`103.250.160.189:8554`) through the running local relay, and against
the real SAAKSHYA application at `http://127.0.0.1:8083` — not a test page.

## 1. The headline result

The premise under investigation was *"standalone Chromium sees 30, the
application does not."* **Measured side by side on the same relay, that gap does
not exist.**

| | Standalone WHEP harness | The actual application |
|---|---|---|
| Tiles attempted | 32 | 30 |
| `<video>` elements created | 32 | 29 |
| Truly live (frames advancing) | **22** | **17** |
| Frozen / stale | 3 | 9 |
| No video | 6 | 3 |
| Media profile | h264 Baseline 640×360 @8fps | identical |

Both clients sit at roughly two-thirds of the wall. The application is not
meaningfully worse than the standalone harness. **The ceiling is upstream, in
Sentinel admission — not in the browser lifecycle.**

## 2. What the application does correctly (verified, not assumed)

These were the suspected defects. All three are already fixed in the working tree:

**Video elements are persistent.** Every `<video>` node was tagged and tracked
across a 30-second window. Cumulative-created equalled live-count at every
sample — 6 → 15 → 21 → 24 → 29, monotonic. **Not one element was destroyed and
recreated.** Polling updates status only. Brief §7 satisfied.

**The wall was mid-warmup, not stuck.** A snapshot at t+14s reads "1 of 30
showing a frame" and only 6 video elements — which is what earlier sessions
appear to have recorded as total failure. Left alone, the same wall reaches
**17–19 of 30** within 60s. The stagger is ~450ms × 30 plus per-camera auth
backoff. *The wall needs ~60 seconds to fill; any measurement before that is
measuring the ramp.*

**LIVE is honest.** The application's own label read "17 of 30 showing a frame"
at the same instant an independent `currentTime`-delta measurement over a 12s
window returned exactly **17 advancing**. The app is not calling frozen tiles
LIVE. Brief §8/§17 satisfied.

## 3. The actual root cause — pool-synchronised auth backoff with no jitter

`relay.py::_publisher_env` splits the wall across two Sentinel accounts **by
camera-number parity**:

```python
if digits and int(digits) % 2 == 0:      # even → BACKUP account
    env["SENTINEL_GRID_EMAIL"] = backup_email
```

odd cameras → primary account, even cameras → backup account, 15 each.

`relay_publisher.py` applies `AUTH_BACKOFF_S = 300.0` on a 401. The backoff is
correct in magnitude and **is honoured** — but it carries **no jitter**, and the
pool shares one identity. So when the primary account's concurrent-session
admission is exceeded, all 15 odd publishers 401 within seconds of each other,
all enter a 300-second backoff together, and **all 15 go dark and recover in
lockstep.**

Caught in the act at 01:56:

```
ready 15/32
not ready: cam01 cam03 cam05 cam07 cam09 cam11 cam13 cam15 cam17
           cam18 cam19 cam21 cam23 cam25 cam26 cam27 cam29
```

Every odd camera, simultaneously. Log evidence, same moment:

```
cam01  6 x 401  ODD/primary   -> publisher authentication backoff
cam03  6 x 401  ODD/primary   -> publisher authentication backoff
cam05  6 x 401  ODD/primary   -> publisher authentication backoff
cam02  2 x 401  EVEN/backup   -> upstream InvalidDataError   (transport, not auth)
cam04  2 x 401  EVEN/backup   -> upstream ConnectionResetError
cam06  2 x 401  EVEN/backup   -> upstream ConnectionResetError
```

Cumulative: **primary pool 90 × 401, backup pool 43 × 401.**

Nine minutes later, backoffs expired and the wall self-healed to **25/32**, with
the deficit now spread evenly (4 odd, 3 even). So this is **not** a permanent
lockout — it is a 5-minute synchronised pool outage that recurs. That is
precisely the failure mode brief §11 names, and the missing ingredient is the
one §11 lists that the code does not implement: **jitter**.

### Recommended fix

1. Add per-publisher jitter to `AUTH_BACKOFF_S`, e.g. `300 * uniform(0.7, 1.4)`, so a pool de-synchronises instead of failing as one block.
2. Honour a `Retry-After` when Sentinel supplies one.
3. Add a per-account circuit breaker that caps concurrent RTSP sessions below the observed admission ceiling rather than discovering it by 401.
4. Surface `RATE_LIMITED` as a distinct source state (§9) — right now these tiles read `RECONNECTING`, which misdescribes a camera that is deliberately waiting.

## 4. Second finding — CPU starvation was degrading the whole media plane

Before any of the above could be measured cleanly, the machine was at **load
average 89.21 on 10 cores**: two `pytest test_live_collection.py` runs hung for
**15 hours** (518 min CPU each) plus a duplicate `analytics.worker` (151 min) —
~430% of sustained waste.

Effect on video, measured through the browser: decode rates on the government
wall scattered between **0.75 and 7.67 fps against an 8 fps source**, inbound
jitter reached **0.4–0.8 s**, and MediaMTX paths lost readiness mid-session
(32/32 → 26/32 → 15/32).

After killing the three processes: load **89 → 25.8**, readiness **15/32 →
25/32**. Several live tiles then showed `currentTime` advancing at ratio
1.3–1.84× wall clock — the player draining buffer after a stall, i.e. recovery.

**30 concurrent VideoToolbox transcodes have no CPU headroom to spare.** A
background test run is enough to degrade the command wall. This belongs under
the existing `run_job.py` CLASS A/C/D lease discipline, which the hung pytest
processes bypassed.

## 5. Third finding — `requestVideoFrameCallback` is not a safe sole liveness signal

Measured across 26 connected tiles over a 12-second window:

```
mean framesDecoded/s (getStats) : 3.76   (range 0.75 – 12.50)
mean rVFC callbacks/s           : 0.87   (pinned ~1.0 on EVERY tile)
mean getStats framesPerSecond   : 4.04
```

rVFC reported ~1 fps for every tile regardless of whether it was decoding at
0.75 or 12.5 fps. A control measurement showed `requestAnimationFrame` itself
running at **2 fps** in this pane, so in this environment the clamp is the
compositor, **not the product** — I am not claiming a defect in headed Chrome on
a normal display.

But the product consequence is real: liveness is currently derived from rVFC,
so anywhere the compositor throttles — background tab, unfocused window,
low-power mode, remote capture, a recording rig — healthy tiles will be marked
STALE. **Make `framesDecoded` from `RTCRtpReceiver.getStats()` the primary
liveness signal and keep rVFC as a corroborator.**

## 6. What 30/30 actually requires

Not a browser rewrite. In priority order:

1. **De-synchronise auth backoff (jitter) and cap per-account concurrency.** This is the binding constraint — it alone costs up to 15 cameras at a time.
2. **Protect the media plane from background CPU load.** Route every heavy job through the existing lease.
3. **Raise `relay.py` defaults** from 180p/5fps/150k to the 360p/8fps/450k the running instance already uses, so a default start is not below the §12 floor.
4. **Switch liveness to `framesDecoded`.**
5. Allow ~60s of warmup before judging the wall, and label the ramp as `CONNECTING` rather than letting an observer read it as failure.

## 7. Not yet done

Staged 1→5→10→15→20→25→30 timing runs; sustained 5/15/30-minute soaks; real AI
on a current government camera; ANPR; M1–M4; full operator click-through; final
recording. None should be attempted before item 1 above is fixed — the wall
cannot hold 30 while a 15-camera pool drops out every five minutes.
