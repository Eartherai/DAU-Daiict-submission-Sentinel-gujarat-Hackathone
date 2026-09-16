# HEVC government camera path selection

Raw PyAV decode for cam06 / cam12 / cam17: **LIVE HEVC**, `has_b_frames=false`.

Browser path comparison on the managed gateway:

| Camera | Raw | Native HEVC→WHEP | Transcode HEVC→H.264→WHEP | Selected path |
|---|---|---|---|---|
| cam06 | LIVE 1920×1080 HEVC | UNAVAILABLE (no decoded frame) | MEASURED (~9.3 s / 15 s, 0 loss, 2 freezes) | `HEVC_TRANSCODED_H264` |
| cam12 | LIVE 1280×720 HEVC | UNAVAILABLE | MEASURED (~9.7 s / 15 s, 0 loss, 2 freezes) | `HEVC_TRANSCODED_H264` |
| cam17 | LIVE 1920×1080 HEVC | UNAVAILABLE | MEASURED (~11.1 s / 15 s, first_frame ~9.3 s, 0 loss, 2 freezes) | `HEVC_TRANSCODED_H264` |

Artifacts:

- `var/reports/phase8c/gov/hevc_raw_probe.json`
- `var/reports/phase8c/gov/cam{06,12,17}_whep_native.json`
- `var/reports/phase8c/gov/cam{06,12,17}_whep_transcode.json`

## Decision

Chromium in this harness does **not** produce a decoded frame for native HEVC WHEP
on these three cameras. Server-side transcode to Constrained-Baseline H.264
(`--transcode` on `tools/gov_whep_relay.py`) restores browser playback.

Do **not** transcode H.264 cameras (cam01/02/05) — they already pass on copy remux.

`StreamPathSelector` encodes this rule: HEVC + `browser_hevc_supported=False`
→ `HEVC_TRANSCODED_H264`.
