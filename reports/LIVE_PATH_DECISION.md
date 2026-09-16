# Live path decision

## Current decision

Keep **RTSP/TCP -> internal PyAV** as the authenticated analytics path. Do not
change the media architecture or claim a browser winner yet.

WHEP/WebRTC remains the intended selected-camera browser path, with snapshot
fallback, but it was not measurable in this environment because no gateway
endpoint or browser negotiation session was configured. HLS returned a redirect
without the required CDN session. Transcoding tools are not installed here.

## Evidence

The authenticated RTSP run decoded 15 cameras adequately in the fresh capture,
four only marginally, and eleven with no usable frame in the bounded capture.
This variation is not enough to select WebRTC, HLS, or transcoding by theory.
Repeatability and a same-camera raw/gateway/browser comparison are required.

## Selection rule

For each camera, select the path with the lowest measured freeze/black/
corruption rate, then startup and latency, then browser compatibility and
recovery. Do not force browser-native H.265; use H.264 transcoding only after a
measured browser failure on an H.265 source.
