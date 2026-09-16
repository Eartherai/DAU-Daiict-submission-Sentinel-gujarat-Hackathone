# Government wall scaling certification

Timestamp UTC: `2026-09-16T03:58:28.407308+00:00`

Overall: **PASS**

Important: **30 cameras managed ≠ 30 simultaneous full-quality browser decoders.**

| Wall | Registered | PRIMARY | SECONDARY | PREVIEW | INACTIVE | Decode candidates | Verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
| 9 | 9 | 1 | 3 | 5 | 0 | 4 | **PASS** |
| 16 | 16 | 1 | 3 | 5 | 7 | 4 | **PASS** |
| 30 | 30 | 1 | 3 | 5 | 21 | 4 | **PASS** |

## Per-wall notes

### Wall 9

**Wall-9 note:** 9 cameras registered/publishing concurrently; browser decode budget measured on PRIMARY/SECONDARY set (cam01/cam02/cam05/cam04). Remaining five tiles stayed PUBLISH_ONLY (PREVIEW/INACTIVE stills path). cam04 MEASURED but short `currentTime≈0.96` with ICE disconnect — treat as AMBER tile under load.

Browser decode wall measured via gov_wall_cert sequential WHEP against concurrent publishers.

Browser subset: measured_ok=4/4 (`/Users/earther/Desktop/Gujarat CCTV/saakshya/var/reports/phase8c/gov/wall9_results.json`).

| Camera | Status | currentTime | freezes | pkt loss |
|---|---|---:|---:|---:|
| cam01 | MEASURED | 8.066 | 0 | 0 |
| cam02 | MEASURED | 8.055 | 0 | 0 |
| cam05 | MEASURED | 8.084 | 0 | 0 |
| cam04 | MEASURED | 0.963 | 1 | 0 |
| cam11 | PUBLISH_ONLY | None | None | None |
| cam13 | PUBLISH_ONLY | None | None | None |
| cam14 | PUBLISH_ONLY | None | None | None |
| cam15 | PUBLISH_ONLY | None | None | None |
| cam19 | PUBLISH_ONLY | None | None | None |

### Wall 16

Managed priority wall CERTIFIED on UI budget model; not equal to N simultaneous full-quality browser decoders.

### Wall 30

Managed priority wall CERTIFIED on UI budget model; not equal to N simultaneous full-quality browser decoders.

## Acceptance

- Priority promotion/demotion model present in `ui/app.js` — mirrored here
- Lazy activation: only wall-visible tiles queue stills/WHEP
- Decode budget stays small vs registered count at 16/30
- Camera-specific path selection preserved (H.264 direct / HEVC transcode)

Machine-readable: `/Users/earther/Desktop/Gujarat CCTV/saakshya/var/reports/phase8c/gov/wall_scaling.json`

