# Government cam01 / cam02 / cam05 browser certification

Measured on the **same managed path** proven for cam01:

```text
Government RTSP (auth in-process)
  → PyAV republish (no ffmpeg argv secrets)
  → local MediaMTX `stream/gov-<id>`
  → WHEP
  → Chromium
  → canvas pixel proof
```

Credentials: process environment only. Artifacts contain no secrets.
`SECRET SCAN` was PASS before this work; re-run after.

## Summary

| Camera | Browser status | Resolution | currentTime | framesDecoded Δ | packetsLost | freezes | reconnects | canvas luma | Notes |
|---|---|---|---|---|---|---|---|---|---|
| cam01 | **CERTIFIED** (prior 12 s soak) | 1920×1080 | ≈12.1 s | ≈168 | 0 | 0 | 0 | ≈97 | Night traffic; Chimanbhai Bridge overlay |
| cam02 | **CERTIFIED** (30 s soak) | 1920×1080 | 30.28 s | 747 | 0 | 0 | 0 | ≈84.2 | Peak FPS 59; some decoder drops recorded |
| cam05 | **CERTIFIED** (30 s soak) | 1920×1080 | 30.27 s | 788 | 0 | 1 | 0 | ≈99.9 | One short stall event; recovered |

Certification rule: MEASURED browser decode with advancing `currentTime`, non-black canvas, and artifact JSON/PNG present.

## cam02 (30 s)

Artifact: `var/reports/phase8c/gov/cam02_whep.json` + `.png`

- first_frame_ms ≈ 647
- negotiation_ms ≈ 161
- ice_state: connected
- packetsReceived_end ≈ 2043
- framesDropped_end ≈ 101 (decoder drops; no freeze count)
- freezes: 0

## cam05 (30 s)

Artifact: `var/reports/phase8c/gov/cam05_whep.json` + `.png`

- first_frame_ms ≈ 575
- negotiation_ms ≈ 136
- ice_state: connected
- packetsReceived_end ≈ 2099
- framesDropped_end ≈ 114
- freezes: 1 (recovered; currentTime still reached 30.27)

## cam01 (reference)

Artifact: `var/reports/phase8c/gov/cam01_whep.json` + `.png` (12 s soak from Phase 8C scale-up).
Re-soak at 30 s / 5 min tracked in `GOV_SELECTED_CAMERA_SOAK.md`.

## Path selection

All three are H.264 → `StreamPath.DIRECT_H264` via managed WHEP gateway
(`saakshya.live.path_selector`).
