# Government feed support email

**Subject:** Request for Investigation of Live CCTV Feed Stability for Evaluation

Dear Evaluation Infrastructure Team,

We are the SAAKSHYA team preparing the CCTV evaluation demonstration. We have
now validated the approved RTSP authority credentials in an ephemeral process.
On **2026-09-16 00:20 UTC**, we made one bounded concurrent RTSP/TCP decode
attempt to each registered camera. Fifteen cameras produced usable fresh
frames, three were marginal, and twelve produced no stable frame in that
bounded run. This is a request for feed-side investigation, not a claim that
all cameras are defective.

| Camera | UTC timestamp | Protocol | Codec / resolution | Symptom |
| --- | --- | --- | --- | --- |
| cam07, cam08, cam09, cam16, cam18, cam21, cam22, cam24, cam25, cam27, cam28, cam30 | 2026-09-16 00:20 UTC | RTSP/TCP | mixed H.264/H.265; catalogue resolutions | no stable decoded frame in bounded concurrent run |
| cam10, cam23, cam26 | 2026-09-16 00:20 UTC | RTSP/TCP | mixed H.264/H.265; catalogue resolutions | only 1–2 decoded frames; continuous playback not established |

Please verify the source encoder, keyframe cadence, RTP/network path, and
recommended RTSP/WHEP client configuration for the listed cameras. We will
repeat single-camera runs and compare the same raw decoder against gateway
WebRTC/HLS and the browser once the gateway/session endpoint is available. We
will attach only concise redacted logs and screenshots, not large video files.

This request concerns only the measured camera IDs above; it does not claim
that all government feeds are affected. Thank you for confirming the preferred
transport and any feed-side remediation or diagnostic window.

Regards,  
SAAKSHYA team
