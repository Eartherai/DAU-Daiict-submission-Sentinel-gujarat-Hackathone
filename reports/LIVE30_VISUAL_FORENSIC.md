# LIVE30 visual forensic review

Each available JPEG was opened and measured individually from actual raw pixels. Missing JPEGs are classified from the absence of a fresh frame, not mistaken for a black image.

| Camera | Codec | Resolution | Frames | Raw status | Visual status | Corruption type | Confidence | Notes |
|---|---|---:|---:|---|---|---|---|---|
| cam01 | h264 | 1920x1080 | 60 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=96.9; dark=0.001; white=0.012; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam02 | h264 | 1920x1080 | 60 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=92.4; dark=0.005; white=0.029; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam03 | h264 | 1280x720 | 60 | LIVE | AMBER | MACROBLOCK / CHROMA ARTEFACT | MEDIUM | mean_luma=77.5; dark=0.076; white=0.000; green=0.003; blockiness=1.57; chroma_bands=0.000 |
| cam04 | h264 | 1920x1080 | 4 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=79.8; dark=0.025; white=0.012; green=0.000; blockiness=1.41; chroma_bands=0.000 |
| cam05 | h264 | 1920x1080 | 60 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=98.5; dark=0.000; white=0.010; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam06 | hevc | 1920x1080 | 60 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=91.8; dark=0.000; white=0.000; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam07 | h264 | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam08 | h264 | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam09 | h264 | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam10 | h264 | 1920x1080 | 2 | DEGRADED | AMBER | MARGINAL FRAME COUNT | HIGH | mean_luma=123.8; dark=0.000; white=0.002; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam11 | h264 | 1920x1080 | 6 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=101.6; dark=0.000; white=0.010; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam12 | hevc | 1280x720 | 60 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=111.2; dark=0.004; white=0.004; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam13 | h264 | 1920x1080 | 41 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=96.3; dark=0.000; white=0.014; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam14 | h264 | 1920x1080 | 47 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=97.9; dark=0.000; white=0.009; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam15 | h264 | 1920x1080 | 14 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=97.7; dark=0.000; white=0.007; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam16 | h264 | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam17 | hevc | 1920x1080 | 60 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=120.5; dark=0.000; white=0.004; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam18 | hevc | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam19 | h264 | 1280x720 | 8 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=66.9; dark=0.097; white=0.005; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam20 | h264 | 1280x720 | 31 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=103.4; dark=0.000; white=0.000; green=0.048; blockiness=1.00; chroma_bands=0.000 |
| cam21 | h264 | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam22 | hevc | 1920x1080 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam23 | h264 | 1280x720 | 1 | DEGRADED | AMBER | MARGINAL FRAME COUNT | HIGH | mean_luma=122.3; dark=0.000; white=0.000; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam24 | h264 | 960x576 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam25 | h264 | 1280x960 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam26 | hevc | 2560x1440 | 1 | DEGRADED | RED | WHITE / OVEREXPOSED | HIGH | mean_luma=151.3; dark=0.000; white=0.382; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam27 | h264 | 1280x960 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam28 | h264 | 1280x960 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |
| cam29 | h264 | 1280x960 | 30 | LIVE | GREEN | NONE DETECTED | MEDIUM | mean_luma=119.6; dark=0.000; white=0.001; green=0.000; blockiness=1.00; chroma_bands=0.000 |
| cam30 | h264 | 0x0 | 0 | NO_FRAME | RED | NO_FRAME | HIGH | No fresh raw frame file was produced. |

## Interpretation

- `SOURCE VISUAL CORRUPTION` here means the raw RTSP/PyAV JPEG itself is degraded; it does **not** prove the upstream government encoder is responsible. Gateway/browser stages are unavailable.
- `NO FRAME` means no fresh JPEG existed; it is not classified as a black frame.
- `LOW QUALITY BUT VALID` is not treated as corruption when scene pixels are coherent.
