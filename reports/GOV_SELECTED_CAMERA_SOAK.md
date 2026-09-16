# Government selected-camera soak report

Managed path only (PyAV → MediaMTX → WHEP → Chromium). No architecture rewrite.

## 30-second certifications (cam01/02/05)

See `GOV_CAM01_02_05_BROWSER_CERTIFICATION.md`.

| Camera | Status | currentTime | freezes | packetsLost | Notes |
|---|---|---|---|---|---|
| cam01 | CERTIFIED (12 s prior + 60 s below) | — | — | — | Golden |
| cam02 | CERTIFIED 30 s | 30.28 | 0 | 0 | |
| cam05 | CERTIFIED 30 s | 30.27 | 1 | 0 | recovered |

## 60-second soaks

| Camera | Status | currentTime | framesDecoded Δ | freezes | ice end | Verdict |
|---|---|---|---|---|---|---|
| cam01 | MEASURED | **59.98** | 892 | **0** | connected | **GREEN** — gold soak |
| cam02 | MEASURED | 9.94 / 60 | 306 | 1 | disconnected | **AMBER** — upstream/session flap under long publish; 30 s path OK |
| cam05 | MEASURED | 45.55 / 60 | 1091 | 1 | disconnected | **AMBER** — advanced most of the minute then ICE dropped |

Artifacts: `var/reports/phase8c/gov/cam{01,02,05}_soak60.json`

## 5-minute soak

**Not completed in this cycle** (wall-clock). cam01 60 s green is the current long-soak proof.
Schedule cam01 300 s next; do not block demo config on it.

## HEVC

See `GOV_HEVC_PATH_SELECTION.md`: native WHEP UNAVAILABLE; transcode MEASURED.

## Publisher reliability fix

`tools/gov_whep_relay.py` now reconnects for the full publish window when
upstream demux ends early (bounded backoff). This was required after cam02
exited publish after ~0.6 s on a single demux pass.
