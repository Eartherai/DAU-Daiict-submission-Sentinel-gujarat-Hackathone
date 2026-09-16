# Repeatability matrix

Generated from `phase8-repeatability-1` with 5 sequential and 5 concurrent 10-second authenticated RTSP/TCP runs per RED/AMBER camera.

## Results

| Camera | Sequential success | Concurrent success | Sequential frames | Concurrent frames | Classification |
|---|---:|---:|---|---|---|
| cam03 | 2/5 | 2/5 | 180, 0, 0, 0, 180 | 0, 0, 0, 180, 180 | INTERMITTENT / STARTUP-SENSITIVE |
| cam07 | 2/5 | 1/5 | 30, 0, 0, 0, 9 | 0, 0, 0, 14, 0 | INTERMITTENT / STARTUP-SENSITIVE |
| cam08 | 1/5 | 1/5 | 52, 0, 0, 0, 0 | 0, 0, 0, 21, 0 | INTERMITTENT / STARTUP-SENSITIVE |
| cam09 | 2/5 | 2/5 | 180, 0, 0, 0, 133 | 0, 0, 0, 87, 172 | INTERMITTENT / STARTUP-SENSITIVE |
| cam10 | 0/5 | 1/5 | 0, 0, 0, 0, 0 | 0, 0, 0, 132, 0 | INTERMITTENT / STARTUP-SENSITIVE |
| cam16 | 1/5 | 2/5 | 0, 0, 0, 0, 101 | 0, 0, 0, 134, 97 | INTERMITTENT / STARTUP-SENSITIVE |
| cam18 | 2/5 | 2/5 | 0, 127, 0, 0, 31 | 0, 0, 0, 103, 180 | INTERMITTENT / STARTUP-SENSITIVE |
| cam21 | 2/5 | 0/5 | 0, 15, 0, 0, 13 | 0, 0, 0, 0, 0 | INTERMITTENT / STARTUP-SENSITIVE |
| cam22 | 0/5 | 2/5 | 0, 0, 0, 0, 0 | 0, 0, 0, 120, 140 | INTERMITTENT / STARTUP-SENSITIVE |
| cam23 | 2/5 | 2/5 | 0, 102, 0, 0, 54 | 0, 0, 0, 67, 41 | INTERMITTENT / STARTUP-SENSITIVE |
| cam24 | 2/5 | 0/5 | 0, 79, 0, 0, 80 | 0, 0, 0, 0, 0 | INTERMITTENT / STARTUP-SENSITIVE |
| cam25 | 0/5 | 0/5 | 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0 | CONSISTENTLY BAD |
| cam26 | 1/5 | 2/5 | 0, 0, 0, 0, 46 | 0, 0, 0, 54, 43 | INTERMITTENT / STARTUP-SENSITIVE |
| cam27 | 2/5 | 2/5 | 0, 0, 0, 36, 180 | 0, 0, 0, 67, 112 | INTERMITTENT / STARTUP-SENSITIVE |
| cam28 | 2/5 | 1/5 | 0, 0, 0, 33, 166 | 0, 0, 0, 87, 0 | INTERMITTENT / STARTUP-SENSITIVE |
| cam30 | 2/5 | 2/5 | 0, 0, 0, 59, 77 | 0, 0, 0, 67, 71 | INTERMITTENT / STARTUP-SENSITIVE |

## Interpretation

- A successful run means more than one decoded frame; it does not imply browser playback or a stable production stream.
- `CONCURRENCY-SENSITIVE` means sequential and concurrent outcomes differ; this is evidence of a session/network/concurrency interaction candidate, not proof of a government-side defect.
- `INTERMITTENT` means the same authenticated endpoint alternated between frame delivery and no-frame/error outcomes during this test.
- `CONSISTENTLY BAD` means no run delivered more than one decoded frame in this bounded sample; it remains a raw-boundary observation, not a source attribution.
- PTS and decoder errors remain available in the machine-readable artifact `var/reports/phase8_repeatability.json`.

## Limits and next test

These were 10-second runs. They establish repeatability differences but do not replace 30/60-second soak tests. The environment still has no authenticated gateway/WHEP session or browser automation, so gateway, WebRTC, browser, overlay, AI-on, and video-wall claims remain `UNAVAILABLE`.
