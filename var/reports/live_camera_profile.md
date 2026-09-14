# Live camera profile — Sentinel Camera Grid

**Provenance:** `GOVERNMENT_LIVE` — the organiser's live grid. These figures are not comparable with the local synthetic corpus and are never merged with it.

**Generated:** 2026-09-02T06:39:56+05:30 (IST) · 2026-09-02T01:09:56+00:00 (UTC)
**Sample:** 30 s per camera, 4 concurrent, ANPR measured
**Reachable:** 29 of 29

> **Camera set discovered by probing, not from the catalogue.**
> The camera set was discovered by probing the documented id pattern because the catalogue host requires a signed-in session. It is not the authoritative set and may miss cameras whose ids do not follow the pattern.
>
> Catalogue said: catalogue at https://cctv.corp8.cloud/cameras.json redirected to '/auth/login' — the CDN host requires a signed-in session. Provide it through SENTINEL_GRID_COOKIE (a session cookie captured after signing in), SENTINEL_GRID_TOKEN, or SENTINEL_GRID_BASIC. It must not be written into any file in this repository.

## Delivery

| Camera | Codec | Resolution | Declared | **Measured (PTS)** | Mean gap | Max gap | PTS health | Warnings |
|---|---|---|---:|---:|---:|---:|---|---:|
| `cam01` | h264 | 1920x1080 | 30.0 | **15.03** | 0.0667 | 0.084 | OK | 0 |
| `cam02` | h264 | 1920x1080 | 30.0 | **29.95** | 0.0334 | 0.113 | OK | 0 |
| `cam03` | h264 | 1280x720 | 30.0 | **22.34** | 0.0448 | 1.36 | OK | 0 |
| `cam04` | h264 | 1920x1080 | 25.0 | **25.03** | 0.04 | 0.043 | OK | 0 |
| `cam05` | h264 | 1920x1080 | 30.0 | **30.01** | 0.0334 | 0.044 | OK | 0 |
| `cam06` | hevc | 1920x1080 | — | **24.06** | 0.0416 | 0.08 | OK | 0 |
| `cam07` | h264 | 1920x1080 | 25.0 | **21.45** | 0.0467 | 0.24 | OK | 0 |
| `cam08` | h264 | 1920x1080 | 25.0 | **11.7** | 0.119 | 2.6 | 6 regression(s), 0 forward jump(s) | 0 |
| `cam09` | h264 | 1920x1080 | 25.0 | **24.65** | 0.0406 | 0.16 | OK | 0 |
| `cam10` | h264 | 1920x1080 | 25.0 | **21.31** | 0.047 | 0.52 | OK | 0 |
| `cam11` | h264 | 1920x1080 | 25.0 | **20.86** | 0.0481 | 0.28 | OK | 0 |
| `cam12` | hevc | 1280x720 | 20.0 | **20.03** | 0.05 | 0.05 | OK | 0 |
| `cam13` | h264 | 1920x1080 | 10.0 | **10.03** | 0.1 | 0.121 | OK | 0 |
| `cam14` | h264 | 1920x1080 | 10.0 | **9.75** | 0.1029 | 0.601 | OK | 0 |
| `cam15` | h264 | 1920x1080 | 10.0 | **7.23** | 0.139 | 0.6 | OK | 0 |
| `cam16` | h264 | 1920x1080 | 10.0 | **2.18** | 0.4785 | 0.921 | OK | 0 |
| `cam17` | hevc | 1920x1080 | 25.0 | **25.03** | 0.04 | 0.041 | OK | 0 |
| `cam18` | hevc | 1920x1080 | 25.0 | **25.03** | 0.04 | 0.04 | OK | 0 |
| `cam19` | h264 | 1280x720 | 25.0 | **21.15** | 0.0474 | 1.2 | OK | 0 |
| `cam20` | h264 | 1280x720 | 25.0 | **24.15** | 0.0415 | 0.36 | OK | 0 |
| `cam22` | hevc | 1920x1080 | 25.0 | **25.0** | 0.045 | 0.08 | OK | 0 |
| `cam23` | h264 | 1280x720 | 25.0 | **24.65** | 0.0406 | 0.2 | OK | 0 |
| `cam24` | h264 | 960x576 | 12.0 | **12.09** | 0.0833 | 0.083 | OK | 0 |
| `cam25` | h264 | 1280x960 | 25.0 | **24.29** | 0.0412 | 0.2 | OK | 0 |
| `cam26` | hevc | 2560x1440 | 13.0 | **13.59** | 0.0738 | 1.076 | OK | 0 |
| `cam27` | h264 | 1280x960 | 25.0 | **24.87** | 0.0403 | 0.08 | OK | 0 |
| `cam28` | h264 | 1280x960 | 25.0 | **24.82** | 0.0403 | 0.08 | OK | 0 |
| `cam29` | h264 | 1280x960 | 25.0 | **24.84** | 0.0403 | 0.08 | OK | 0 |
| `cam30` | h264 | 1920x1080 | — | **17.54** | 0.058 | 1.085 | OK | 2 |

The declared rate is what the container reports. The measured rate is derived from presentation timestamps over the sample. Where they differ, the measured figure is the one every timing decision in this system uses.

## Image and scene

| Camera | Mean luma | Chroma | Colour mode | Sharpness | Scene motion | Band | Frames |
|---|---:|---:|---|---:|---:|---|---:|
| `cam01` | 0.547 | 0.0643 | COLOUR | 2985.3 | 0.025 | DAY | 478 |
| `cam02` | 0.577 | 0.0807 | COLOUR | 4167.0 | 0.0652 | DAY | 926 |
| `cam03` | 0.511 | 0.0704 | COLOUR | 7931.1 | 0.0234 | DAY | 687 |
| `cam04` | 0.455 | 0.0657 | COLOUR | 8322.9 | 0.0603 | DAY | 778 |
| `cam05` | 0.558 | 0.0773 | COLOUR | 5210.8 | 0.0497 | DAY | 928 |
| `cam06` | 0.081 | 0.0 | MONOCHROME_OR_IR | 1357.4 | 0.0098 | LOW_LIGHT | 740 |
| `cam07` | 0.484 | 0.0476 | COLOUR | 7598.1 | 0.0184 | DAY | 580 |
| `cam08` | 0.469 | 0.0653 | COLOUR | 6131.1 | 0.0468 | DAY | 249 |
| `cam09` | 0.544 | 0.0194 | MONOCHROME_OR_IR | 1495.7 | 0.0265 | DAY | 708 |
| `cam10` | 0.503 | 0.0522 | COLOUR | 2203.2 | 0.0326 | DAY | 519 |
| `cam11` | 0.519 | 0.047 | COLOUR | 1924.1 | 0.0179 | DAY | 257 |
| `cam12` | 0.411 | 0.0787 | COLOUR | 2922.5 | 0.0207 | DAY | 595 |
| `cam13` | 0.437 | 0.0322 | MONOCHROME_OR_IR | 595.8 | 0.0228 | DAY | 327 |
| `cam14` | 0.472 | 0.0378 | MONOCHROME_OR_IR | 605.7 | 0.0185 | DAY | 319 |
| `cam15` | 0.285 | 0.0 | MONOCHROME_OR_IR | 143.0 | 0.043 | DAY | 178 |
| `cam16` | 0.451 | 0.0354 | MONOCHROME_OR_IR | 1212.3 | 0.0031 | DAY | 25 |
| `cam17` | 0.418 | 0.0837 | COLOUR | 2391.9 | 0.0115 | DAY | 574 |
| `cam18` | 0.479 | 0.0271 | MONOCHROME_OR_IR | 4583.3 | 0.0298 | DAY | 761 |
| `cam19` | 0.421 | 0.052 | COLOUR | 1231.8 | 0.0068 | DAY | 609 |
| `cam20` | 0.522 | 0.0891 | COLOUR | 2415.8 | 0.01 | DAY | 711 |
| `cam22` | 0.54 | 0.0367 | MONOCHROME_OR_IR | 3477.4 | None | DAY | 9 |
| `cam23` | 0.329 | 0.0448 | COLOUR | 419.6 | 0.021 | DAY | 705 |
| `cam24` | 0.514 | 0.0 | MONOCHROME_OR_IR | 329.2 | 0.0101 | DAY | 133 |
| `cam25` | 0.378 | 0.0684 | COLOUR | 18522.5 | 0.0234 | DAY | 579 |
| `cam26` | 0.349 | 0.0776 | COLOUR | 1156.6 | 0.0378 | DAY | 388 |
| `cam27` | 0.371 | 0.0368 | MONOCHROME_OR_IR | 5305.9 | 0.0034 | DAY | 746 |
| `cam28` | 0.444 | 0.0 | MONOCHROME_OR_IR | 1349.4 | 0.0016 | DAY | 696 |
| `cam29` | 0.428 | 0.0 | MONOCHROME_OR_IR | 1323.6 | 0.0039 | DAY | 613 |
| `cam30` | 0.359 | 0.024 | MONOCHROME_OR_IR | 4356.3 | 0.0289 | DAY | 59 |

`MONOCHROME_OR_IR` means the camera is delivering a three-channel frame with no colour in it — infrared night mode. Nothing upstream would notice, and a colour estimator asked to read a vehicle from such a frame returns a confident answer that is fabricated. Appearance is graded UNSUITABLE on those cameras; detection and presence are unaffected.

## Capability

Measured from this sample. **UNKNOWN means not enough evidence, never poor quality** — a short sample cannot establish what a camera does across a day, and converting silence into a bad grade would slander working equipment.

| Camera | Presence | Vehicle | Appearance | ANPR | Tracking | Forensic | Tier | Confidence |
|---|---|---|---|---|---|---|---|---|
| `cam01` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam02` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam03` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam04` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam05` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam06` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | GOOD | **T0** | MODERATE |
| `cam07` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam08` | DEGRADED | GOOD | GOOD | UNSUITABLE | DEGRADED | GOOD | **T1** | MODERATE |
| `cam09` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | GOOD | **T0** | MODERATE |
| `cam10` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam11` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam12` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam13` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | GOOD | **T0** | MODERATE |
| `cam14` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | GOOD | **T0** | MODERATE |
| `cam15` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | DEGRADED | GOOD | **T0** | MODERATE |
| `cam16` | UNKNOWN | GOOD | UNSUITABLE | UNSUITABLE | UNKNOWN | GOOD | **UNASSIGNED** | MODERATE |
| `cam17` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam18` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | GOOD | **T0** | MODERATE |
| `cam19` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam20` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam22` | UNKNOWN | UNKNOWN | UNKNOWN | UNSUITABLE | UNKNOWN | UNKNOWN | **UNASSIGNED** | MODERATE |
| `cam23` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam24` | GOOD | DEGRADED | UNSUITABLE | UNSUITABLE | GOOD | DEGRADED | **T0** | MODERATE |
| `cam25` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam26` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam27` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | DEGRADED | **T0** | MODERATE |
| `cam28` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | DEGRADED | **T0** | MODERATE |
| `cam29` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | DEGRADED | **T0** | MODERATE |
| `cam30` | DEGRADED | UNKNOWN | UNKNOWN | UNKNOWN | GOOD | UNKNOWN | **T0** | MODERATE |

## Why each grade

**`cam01`**

- *presence* — 478 frames at 15.0 fps by PTS, max gap 0.08s
- *tracking* — 15.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 2985, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.547
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam02`**

- *presence* — 926 frames at 29.9 fps by PTS, max gap 0.11s
- *tracking* — 29.9 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 4167, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.577
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam03`**

- *presence* — 687 frames at 22.3 fps by PTS, max gap 1.36s
- *tracking* — 22.3 fps with monotonic PTS
- *vehicle_detection* — 1280x720 (sharpness 7931, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1280x720 at mean luma 0.511
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam04`**

- *presence* — 778 frames at 25.0 fps by PTS, max gap 0.04s
- *tracking* — 25.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 8323, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.455
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam05`**

- *presence* — 928 frames at 30.0 fps by PTS, max gap 0.04s
- *tracking* — 30.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 5211, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.558
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam06`**

- *presence* — 740 frames at 24.1 fps by PTS, max gap 0.08s
- *tracking* — 24.1 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 1357, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0000) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam07`**

- *presence* — 580 frames at 21.4 fps by PTS, max gap 0.24s
- *tracking* — 21.4 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 7598, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.484
- *anpr* — 0% read yield over 19 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam08`**

- *presence* — 6 PTS regression(s) — ordering is unreliable, so absence of a detection here is not evidence of absence
- *tracking* — 11.7 fps — association across frames will be harder and tracks will fragment
- *vehicle_detection* — 1920x1080 (sharpness 6131, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.469
- *anpr* — 0% read yield over 17 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam09`**

- *presence* — 708 frames at 24.6 fps by PTS, max gap 0.16s
- *tracking* — 24.6 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 1496, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0194) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam10`**

- *presence* — 519 frames at 21.3 fps by PTS, max gap 0.52s
- *tracking* — 21.3 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 2203, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.503
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam11`**

- *presence* — 257 frames at 20.9 fps by PTS, max gap 0.28s
- *tracking* — 20.9 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 1924, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.519
- *anpr* — 0% read yield over 19 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam12`**

- *presence* — 595 frames at 20.0 fps by PTS, max gap 0.05s
- *tracking* — 20.0 fps with monotonic PTS
- *vehicle_detection* — 1280x720 (sharpness 2922, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1280x720 at mean luma 0.411
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam13`**

- *presence* — 327 frames at 10.0 fps by PTS, max gap 0.12s
- *tracking* — 10.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 596, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0322) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam14`**

- *presence* — 319 frames at 9.8 fps by PTS, max gap 0.60s
- *tracking* — 9.8 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 606, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0378) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam15`**

- *presence* — 178 frames at 7.2 fps by PTS, max gap 0.60s
- *tracking* — 7.2 fps — association across frames will be harder and tracks will fragment
- *vehicle_detection* — 1920x1080 (sharpness 143, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0000) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 16 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam16`**

- *presence* — 25 frames in the sample; 40 needed to grade delivery
- *tracking* — not enough delivery evidence
- *vehicle_detection* — 1920x1080 (sharpness 1212, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0354) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 16 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam17`**

- *presence* — 574 frames at 25.0 fps by PTS, max gap 0.04s
- *tracking* — 25.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 2392, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.418
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam18`**

- *presence* — 761 frames at 25.0 fps by PTS, max gap 0.04s
- *tracking* — 25.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 4583, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0271) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam19`**

- *presence* — 609 frames at 21.1 fps by PTS, max gap 1.20s
- *tracking* — 21.1 fps with monotonic PTS
- *vehicle_detection* — 1280x720 (sharpness 1232, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1280x720 at mean luma 0.421
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam20`**

- *presence* — 711 frames at 24.1 fps by PTS, max gap 0.36s
- *tracking* — 24.1 fps with monotonic PTS
- *vehicle_detection* — 1280x720 (sharpness 2416, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1280x720 at mean luma 0.522
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam22`**

- *presence* — 9 frames in the sample; 40 needed to grade delivery
- *tracking* — not enough delivery evidence
- *vehicle_detection* — not enough sampled frames to judge the image
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere

**`cam23`**

- *presence* — 705 frames at 24.6 fps by PTS, max gap 0.20s
- *tracking* — 24.6 fps with monotonic PTS
- *vehicle_detection* — 1280x720 (sharpness 420, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1280x720 at mean luma 0.329
- *anpr* — 0% read yield over 19 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam24`**

- *presence* — 133 frames at 12.1 fps by PTS, max gap 0.08s
- *tracking* — 12.1 fps with monotonic PTS
- *vehicle_detection* — 960x576 — vehicles detectable, small or distant ones unreliable
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0000) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam25`**

- *presence* — 579 frames at 24.3 fps by PTS, max gap 0.20s
- *tracking* — 24.3 fps with monotonic PTS
- *vehicle_detection* — 1280x960 (sharpness 18522, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1280x960 at mean luma 0.378
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam26`**

- *presence* — 388 frames at 13.6 fps by PTS, max gap 1.08s
- *tracking* — 13.6 fps with monotonic PTS
- *vehicle_detection* — 2560x1440 (sharpness 1157, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 2560x1440 at mean luma 0.349
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 2560x1440 supports re-processing a crop

**`cam27`**

- *presence* — 746 frames at 24.9 fps by PTS, max gap 0.08s
- *tracking* — 24.9 fps with monotonic PTS
- *vehicle_detection* — 1280x960 (sharpness 5306, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0368) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam28`**

- *presence* — 696 frames at 24.8 fps by PTS, max gap 0.08s
- *tracking* — 24.8 fps with monotonic PTS
- *vehicle_detection* — 1280x960 (sharpness 1349, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0000) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam29`**

- *presence* — 613 frames at 24.8 fps by PTS, max gap 0.08s
- *tracking* — 24.8 fps with monotonic PTS
- *vehicle_detection* — 1280x960 (sharpness 1324, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — monochrome / infrared frame (mean chroma 0.0000) — there is no colour in this image to match on. Vehicle detection and presence are unaffected.
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam30`**

- *presence* — PTS advanced at 0.42x wall time over the sample at 17.5 fps — this stream is not keeping up with real time, so periods of it are simply not delivered
- *tracking* — 17.5 fps with monotonic PTS
- *vehicle_detection* — not enough sampled frames to judge the image
- *anpr* — not measured in this pass — run with --anpr once the stream characteristics are understood

## Method

Bounded real-time RTSP/TCP sample per camera. Every stream was closed after sampling. Timing is from PTS; the container's declared frame rate is recorded and not used.

Nothing here was tuned against this feed. Profiling comes before model selection, and a threshold moved to improve a number on the first day of real data is a threshold fitted to noise.
