# Final government camera matrix (Phase 9 partial)

Evidence-based status after scaling the cam01-proven managed path.
Statuses: GREEN / AMBER / RED. UNAVAILABLE means not measured this cycle.

| Camera | Codec | Resolution | Raw | Relay | WHEP | Browser | AI | Stability | Selected Path | Status | Root Cause |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cam01 | h264 | 1920×1080 | VERIFIED | VERIFIED | VERIFIED | VERIFIED 60 s | overlay wired | GREEN | DIRECT_H264 | **GREEN** | — |
| cam02 | h264 | 1920×1080 | VERIFIED | VERIFIED | VERIFIED | VERIFIED 30 s; 60 s AMBER | pending | AMBER long-soak | DIRECT_H264 | **GREEN** (30 s) / AMBER (60 s) | intermittent upstream under long publish |
| cam05 | h264 | 1920×1080 | VERIFIED | VERIFIED | VERIFIED | VERIFIED 30 s; 60 s AMBER | pending | AMBER | DIRECT_H264 | **GREEN** (30 s) / AMBER (60 s) | ICE drop late in soak |
| cam06 | hevc | 1920×1080 | VERIFIED | VERIFIED (transcode) | native FAIL / tx PASS | MEASURED tx | pending | AMBER freezes | HEVC_TRANSCODED_H264 | **AMBER** | no browser HEVC |
| cam12 | hevc | 1280×720 | VERIFIED | VERIFIED (transcode) | native FAIL / tx PASS | MEASURED tx | pending | AMBER | HEVC_TRANSCODED_H264 | **AMBER** | no browser HEVC |
| cam17 | hevc | 1920×1080 | VERIFIED | VERIFIED (transcode) | native FAIL / tx PASS | MEASURED tx | pending | AMBER slow start | HEVC_TRANSCODED_H264 | **AMBER** | no browser HEVC |

## Judge set

- **GOLDEN:** cam01
- **SECONDARY:** cam02, cam05 (30 s proven; prefer short focus demos)
- **DEGRADED/HEVC:** cam06/12/17 via transcode only
- **EXTERNAL:** none justified yet for these IDs (pipeline works when session is up)

## Support email

Not sent. Failures observed so far are intermittent session/ICE under load or
missing browser HEVC — both handled on our side (reconnect + transcode).
