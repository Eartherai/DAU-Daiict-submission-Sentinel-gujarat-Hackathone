# Live camera profile — Sentinel Camera Grid

**Provenance:** `GOVERNMENT_LIVE` — the organiser's live grid. These figures are not comparable with the local synthetic corpus and are never merged with it.

**Generated:** 2026-09-02T00:30:42+05:30 (IST) · 2026-09-01T19:00:42+00:00 (UTC)
**Sample:** 30 s per camera, 3 concurrent, ANPR measured
**Reachable:** 6 of 6

> **Camera set discovered by probing, not from the catalogue.**
> The camera set was discovered by probing the documented id pattern because the catalogue host requires a signed-in session. It is not the authoritative set and may miss cameras whose ids do not follow the pattern.
>
> Catalogue said: catalogue at https://cctv.corp8.cloud/cameras.json redirected to '/auth/login' — the CDN host requires a signed-in session. Provide it through SENTINEL_GRID_COOKIE (a session cookie captured after signing in), SENTINEL_GRID_TOKEN, or SENTINEL_GRID_BASIC. It must not be written into any file in this repository.

## Delivery

| Camera | Codec | Resolution | Declared | **Measured (PTS)** | Mean gap | Max gap | PTS health | Warnings |
|---|---|---|---:|---:|---:|---:|---|---:|
| `cam02` | h264 | 1920x1080 | 30.0 | **29.99** | 0.0334 | 0.077 | OK | 0 |
| `cam05` | h264 | 1920x1080 | 30.0 | **30.01** | 0.0334 | 0.044 | OK | 0 |
| `cam09` | h264 | 1920x1080 | 25.0 | **25.03** | 0.04 | 0.04 | OK | 0 |
| `cam13` | h264 | 1920x1080 | 10.0 | **10.03** | 0.1 | 0.121 | OK | 0 |
| `cam24` | h264 | 960x576 | 12.0 | **12.04** | 0.0833 | 0.083 | OK | 0 |
| `cam26` | hevc | 2560x1440 | 15.0 | **15.98** | 0.0627 | 0.53 | OK | 0 |

The declared rate is what the container reports. The measured rate is derived from presentation timestamps over the sample. Where they differ, the measured figure is the one every timing decision in this system uses.

## Image and scene

| Camera | Mean luma | Sharpness | Scene motion | Band | Frames | Sampled |
|---|---:|---:|---:|---|---:|---:|
| `cam02` | 0.417 | 935.8 | 0.0239 | NIGHT | 926 | 62 |
| `cam05` | 0.405 | 1520.7 | 0.0272 | NIGHT | 927 | 62 |
| `cam09` | 0.027 | 1971.9 | 0.0107 | LOW_LIGHT | 721 | 56 |
| `cam13` | 0.361 | 221.7 | 0.0219 | NIGHT | 327 | 55 |
| `cam24` | 0.378 | 154.1 | 0.0045 | NIGHT | 278 | 47 |
| `cam26` | 0.337 | 1049.2 | 0.052 | NIGHT | 449 | 54 |

## Capability

Measured from this sample. **UNKNOWN means not enough evidence, never poor quality** — a short sample cannot establish what a camera does across a day, and converting silence into a bad grade would slander working equipment.

| Camera | Presence | Vehicle | Appearance | ANPR | Tracking | Forensic | Tier | Confidence |
|---|---|---|---|---|---|---|---|---|
| `cam02` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam05` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam09` | GOOD | GOOD | UNSUITABLE | UNSUITABLE | GOOD | GOOD | **T0** | MODERATE |
| `cam13` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |
| `cam24` | GOOD | DEGRADED | DEGRADED | UNSUITABLE | GOOD | DEGRADED | **T1** | MODERATE |
| `cam26` | GOOD | GOOD | GOOD | UNSUITABLE | GOOD | GOOD | **T1** | MODERATE |

## Why each grade

**`cam02`**

- *presence* — 926 frames at 30.0 fps by PTS, max gap 0.08s
- *tracking* — 30.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 936, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.417
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam05`**

- *presence* — 927 frames at 30.0 fps by PTS, max gap 0.04s
- *tracking* — 30.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 1521, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.405
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam09`**

- *presence* — 721 frames at 25.0 fps by PTS, max gap 0.04s
- *tracking* — 25.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 1972, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — mean luma 0.027 — effectively no illumination in frame. No colour or appearance signal can be recovered here, and producing one would be inventing it.
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam13`**

- *presence* — 327 frames at 10.0 fps by PTS, max gap 0.12s
- *tracking* — 10.0 fps with monotonic PTS
- *vehicle_detection* — 1920x1080 (sharpness 222, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 1920x1080 at mean luma 0.361
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — 1920x1080 supports re-processing a crop

**`cam24`**

- *presence* — 278 frames at 12.0 fps by PTS, max gap 0.08s
- *tracking* — 12.0 fps with monotonic PTS
- *vehicle_detection* — 960x576 — vehicles detectable, small or distant ones unreliable
- *vehicle_appearance* — mean luma 0.378 at 960x576 — appearance narrows a candidate list here; it does not identify a vehicle
- *anpr* — 0% read yield over 20 frames; route plate work elsewhere
- *forensic* — resolution limits what re-processing can recover

**`cam26`**

- *presence* — 449 frames at 16.0 fps by PTS, max gap 0.53s
- *tracking* — 16.0 fps with monotonic PTS
- *vehicle_detection* — 2560x1440 (sharpness 1049, recorded but not gated on — it varies with scene content, not just optics)
- *vehicle_appearance* — 2560x1440 at mean luma 0.337
- *anpr* — 0% read yield over 21 frames; route plate work elsewhere
- *forensic* — 2560x1440 supports re-processing a crop

## Method

Bounded real-time RTSP/TCP sample per camera. Every stream was closed after sampling. Timing is from PTS; the container's declared frame rate is recorded and not used.

Nothing here was tuned against this feed. Profiling comes before model selection, and a threshold moved to improve a number on the first day of real data is a threshold fitted to noise.
