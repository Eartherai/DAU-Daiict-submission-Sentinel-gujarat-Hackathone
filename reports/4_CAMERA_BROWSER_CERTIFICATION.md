# 4-camera browser wall certification

Concurrent publishers on one MediaMTX; sequential Chromium WHEP soaks (20 s each)
against the live fan-out. Tool: `tools/gov_wall_cert.py`.

Cameras: **cam01, cam02, cam05** (H.264 copy) + **cam06** (HEVC→H.264 transcode).

| Camera | Path | Status | currentTime | freezes | packetsLost | ice |
|---|---|---|---|---|---|---|
| cam01 | DIRECT_H264 | MEASURED | 20.22 | 1 | 0 | connected |
| cam02 | DIRECT_H264 | MEASURED | 14.25 | 1 | 0 | connected |
| cam05 | DIRECT_H264 | MEASURED | 2.08 | 1 | 0 | disconnected |
| cam06 | HEVC_TRANSCODED_H264 | MEASURED | 19.45 | 2 | 0 | connected |

Artifact: `var/reports/phase8c/gov/wall4_results.json`

## Interpretation

- All four produced a decoded browser frame under concurrent relay load.
- cam05 degraded under multi-publish contention (short currentTime) — treat as
  SECONDARY on the judge wall, not GOLDEN.
- cam01 remains the PRIMARY / golden focus camera.
- Per-tile failure did not prevent other cameras from measuring (isolation OK
  at the measurement harness level).

## Not yet measured

9 / 16 / 30 simultaneous *browser-visible* tiles in one page session.
Next: drive the UI wall with PRIMARY/SECONDARY/PREVIEW priorities using this
same gateway fan-out.
