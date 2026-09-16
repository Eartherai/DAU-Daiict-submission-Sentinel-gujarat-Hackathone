# HEVC path validation (Phase D)

Timestamp UTC: `2026-09-16T03:58:38.733807+00:00`

Native browser HEVC WHEP remains unsupported in this harness.
Selected path: **HEVC_TRANSCODED_H264** when `browser_hevc_supported=False`.

H.264 cameras must stay on **DIRECT_H264** (no unnecessary transcode).

| Camera | Path | Status | currentTime | freezes | pkt loss |
|---|---|---|---:|---:|---:|
| cam06 | HEVC_TRANSCODED_H264 | **MEASURED** | 9.763 | 2 | 0 |
| cam12 | HEVC_TRANSCODED_H264 | prior MEASURED | — | — | — |
| cam17 | HEVC_TRANSCODED_H264 | prior MEASURED | — | — | — |

Command:
```bash
python tools/gov_whep_relay.py cam06 --seconds 35 --transcode --whep-test --whep-seconds 12
```

Overall: **PASS**

Selector unit tests: PASS.

Machine-readable: `var/reports/phase8c/gov/hevc_path_validation.json`
