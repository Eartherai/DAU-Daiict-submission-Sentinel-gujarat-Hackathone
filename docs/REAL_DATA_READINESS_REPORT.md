# Real Data Readiness Report

**Generated:** 2026-09-01T06:44:05+00:00  
**Catalogue:** `var/media/catalogue.json`  
**Dataset label:** GOVERNMENT (characterisation only — no accuracy claim is made in this document)

## Summary

- cameras in catalogue: **6**
- reachable and decoded: **6**
- unreachable: **0**
- distinct codecs: h264, hevc
- distinct resolutions: 1280x720, 1920x1080, 640x480, 960x540
- structural problems: **0**

## Per-camera profile

| Camera | Codec | Resolution | Declared fps | Measured fps | Lum | Sharp | Activity | Tier hint | Warnings |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| `C-014` | h264 | 1280x720 | 15.0 | 15.0 | 0.51 | 0.49 | 1.27 | A_OR_B_PENDING_MEASUREMENT | — |
| `C-021` | hevc | 1280x720 | 12.0 | 12.0 | 0.49 | 0.14 | 1.80 | C_PRESENCE_LIKELY | very soft image — ANPR unlikely to be viable |
| `C-033` | h264 | 640x480 | 10.0 | 10.0 | 0.38 | 0.08 | 1.28 | C_PRESENCE_LIKELY | very soft image — ANPR unlikely to be viable |
| `C-047` | hevc | 1920x1080 | 15.0 | 15.0 | 0.50 | 0.33 | 1.12 | A_OR_B_PENDING_MEASUREMENT | — |
| `C-052` | h264 | 960x540 | 8.0 | 8.0 | 0.54 | 0.24 | 0.91 | B_PENDING_MEASUREMENT | — |
| `C-061` | h264 | 1280x720 | 15.0 | 15.0 | 0.53 | 0.71 | 2.07 | A_OR_B_PENDING_MEASUREMENT | — |

## What this report does and does not say

**Does:** describes what was received — reachability, codecs, resolutions, measured frame rate against declared, timing behaviour, and coarse image statistics.

**Does not:** state accuracy, or assign capability grades. A tier *hint* from a dozen frames is a starting point for compute allocation, not a measurement. Real grades require sustained observation across a diurnal cycle, and until then a camera's capability is `INSUFFICIENT_DATA`.

## Next steps

1. Resolve every structural problem above.
2. Import the catalogue into the registry (`make government-import`).
3. Run the pipeline for a sustained period to accumulate capability evidence and bootstrap the camera transition graph.
4. Only then benchmark models, and report per-camera yield rather than a single headline number.

