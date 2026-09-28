# LIVE ANPR ON THE GOVERNMENT FEED

Historical measurement record. Concurrent live counts below are **MEASURED
DURING A TEST WINDOW**, not sandbox limits. Current support guidance and wall
policies: `docs/SENTINEL_SUPPORT_CLARIFICATION.md`.

2026-09-20, ~05:20–06:07 IST. Every number below comes from **live Sentinel
video read during this run**. No historical rows, no simulation, no replay of
stored observations.

## Proven

| stage | result |
|---|---|
| current government camera | cam06 Timbavadi Gate, Junagadh — RTSP direct, 1920x1080 |
| real vehicle detection | **7,333 observations** in ~45 min |
| real tracking | stable track ids, motion driven by **PTS** not arrival time |
| real plate read | **11 plates**, 3 corroborated across frames |
| watchlist | 20 entries, populated from live-read plates |
| real-time alert | **NOT closed on live data** — see below |

### The plates

```
cam06  GJ11S7924   0.953  votes=2   <- corroborated
cam06  GJ11S9258   0.968  votes=1   102px
cam06  GJ37AB9445  0.956  votes=1    84px
cam06  GJ03PD2863  0.923  votes=1   156px
cam06  GJ27AA0401  0.941  votes=1   163px
cam06  GJ11C1163   0.813  votes=2   <- corroborated  119px
cam06  GJ11BR0928  0.966  votes=1   119px
cam06  GJ11YY6198  0.965  votes=1    81px
cam06  GJ01RS9114  0.951  votes=1   157px
cam06  GJ11BR1008  0.948  votes=1   135px
cam06  GJ18ZT1782  0.947  votes=2   <- corroborated  142px
```

Detections by type: car 3153, person 2323, motorcycle 1068, truck 451,
bicycle 124, bus 88, van 75.

**Why these are believable.** Every plate is a valid Indian format with a real
RTO code, and the majority read `GJ11` — the Junagadh code — from a camera that
*is* in Junagadh. The engine never invents: it publishes a corroborated read
(>=2 agreeing frames, mean OCR >=0.55) or a single read only at >=0.82, and
rejects anything failing the format check.

## Two findings that decided the outcome

**1. Daylight, not resolution, is the ANPR variable.** cam02 at night produced
plate crops of the right size (147px avg, 167px max) and the OCR still returned
garbage: `'____1'` 0.52, `'CC4044'` 0.48, `'CB2111'` 0.53, `'L17'` 0.63 — mean
0.51, none above the 0.82 single-read gate, none a valid format. Headlight
glare and motion blur, not pixel count. Measuring mean luma across cameras and
switching to daylight ones turned 0 reads into 11.

**2. Geometry decides which cameras can do ANPR at all.** Measured plate crop
width per camera:

```
cam02  167px max  SUITABLE      cam06  136px max  SUITABLE
cam15  147px max  SUITABLE      cam12   43px max  ANPR_UNSUITABLE (toll plaza!)
cam04   49px max  ANPR_UNSUITABLE
```

The toll plaza was the obvious candidate and is the *worst* of them — its
camera sits too far back. This is exactly the case where a plate must be
reported `ANPR_UNSUITABLE` rather than guessed.

## The alert chain is not closed, and why

`watch.match(obs)` runs at the instant an observation is processed. A plate
watchlisted 2.7s *after* its read has already missed that vehicle, and at a
through-road the vehicle is gone. Five plates were watchlisted within
2.7–12.5s of their read; none produced an alert.

The alert present in the store (`GJ38BH5815`, cam21) is **historical, from an
earlier session**, and is explicitly not counted here.

Two honest ways to close it:

1. **Cross-camera.** The watchlist is now populated, so a vehicle passing a
   *second* camera matches against an entry already in force. This is also
   what the evaluation asks for — movement across the network.
2. **Wait one loop.** The feed is a 25-hour loop, so every watchlisted plate
   recurs at its original offset.

The cross-camera attempt failed for an unrelated reason: I restarted the AI
worker onto four cameras five seconds after killing the previous one, and
Sentinel answered 55x 401 in that window; session retention was not verified.
The same fast-restart mistake documented earlier in this session.

## Plane separation, which made this possible at all

RTSP is the grid's AI plane and WHEP is the browser plane, and they were
concurrent in the same test window: 30 WHEP tiles + 3 RTSP coincided with
401s for the AI and ~11 black tiles on the wall. Giving the **AI plane its own
account** fixed both: 0x401, and detection ran at 2.1–4.8 detector fps per
camera while the wall kept playing.

`worker.py` now attaches to the camera's registered Sentinel RTSP URL with the
credential added at connect time, and **redacts it before logging** — it was
logging the raw URL, which would have written the grid password into a log file
the moment the AI plane stopped using the local relay.

## Next

Cross-camera match after a proper cooldown; GIS route from the observation
lat/lon already stored; evidence + audit from the alert. The detection,
tracking, OCR and watchlist stages are proven live; only the match-ordering and
the hops after it remain.
