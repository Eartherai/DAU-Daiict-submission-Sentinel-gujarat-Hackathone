# Government 30-camera live certification

## Verdict

**DEGRADED / PARTIAL — not a 30-camera stable-live pass.**

The approved RTSP authority credentials were injected securely for this run.
Thirty RTSP/TCP workers were launched concurrently for an 8-second bounded
decode window on **2026-09-16 00:20 UTC**. Representative and full-run results
are stored under `var/reports/live30_live/`.

| Result | Count | Meaning |
| --- | ---: | --- |
| GREEN | 15 | At least 3 decoded frames in the fresh capture; no sampled black/freeze/decode-corruption count |
| AMBER | 3 | Only 1–2 decoded frames in the bounded capture; continuous playback not established |
| RED | 12 | No decoded frame or immediate stream/decoder failure in the bounded capture |

The 30-camera run is a real authenticated RTSP result, but it does **not**
demonstrate smooth 30-camera browser playback. The browser, WHEP, HLS, and
AI-on comparison were not run because the gateway/browser path is not
configured in this environment.

## Fresh contact sheet

`var/reports/live30_live/contact_sheet.jpg` was captured from the authenticated
RTSP session, not from the stale preview directory. Every tile is labelled with
camera ID, capture-time UTC clock, and state. It shows the real variation:
usable traffic scenes, macroblock/washed frames, and no-frame cameras.

## Representative observations

| Camera | Codec | Resolution | Frames | Observed FPS | State |
| --- | --- | ---: | ---: | ---: | --- |
| cam01 | H.264 | 1920x1080 | 148 | 14.99 | GREEN |
| cam08 | H.264 | 1920x1080 | 146 | 25.00 | GREEN |
| cam09 | H.264 | 1920x1080 | 136 | 25.00 | GREEN |
| cam10 | H.264 | 1920x1080 | 106 | 25.00 | GREEN |
| cam12 | H.265 | 1280x720 | 146 | 20.00 | GREEN |
| cam17 | H.265 | 1920x1080 | 128 | 25.00 | GREEN |
| cam18 | H.265 | 1920x1080 | 0 | unavailable | RED in representative run |
| cam20 | H.264 | 1280x720 | 180 | 25.00 | GREEN |
| cam22 | H.265 | 1920x1080 | 0 | unavailable | RED in representative run |
| cam28 | H.264 | 1280x960 | 112 | 24.78 | GREEN |
| cam29 | H.264 | 1280x960 | 105 | 24.76 | GREEN |
| cam30 | H.264 | 1920x1080 | 60 | unavailable | AMBER / decoder error |

The full-run JSON is authoritative for the exact per-camera result because
stream behaviour varied between concurrent attempts. A camera with zero frames
is never called live merely because the RTSP socket opened.

## Motion

Fresh frame capture proves temporal decode availability, not that every scene
contains a moving vehicle. The contact sheet includes traffic movement on
several cameras; a source-side timestamp/vehicle trajectory comparison is not
available for every camera. Absolute source-to-screen latency is therefore
unverified.

## Root-cause status

- **RTSP authentication:** fixed/configured for this run.
- **Internal PyAV/TCP decode:** works for a subset; intermittent no-frame and
  decoder failures remain.
- **Source/network/encoder:** not yet separable from one bounded client run.
- **Browser/WHEP/HLS:** not tested in this environment.
- **AI-induced playback impact:** not tested because browser gateway is absent.

The next fix must be evidence-led: capture repeated single-camera runs for
RED/AMBER feeds, compare raw decode against gateway and browser, then test
H.265-to-H.264 only for cameras that fail browser decode.
