# LIVE30 final camera selection

## Best demo cameras

Use these first for the judge-facing selected-camera demo:

| Camera | Why |
| --- | --- |
| cam01 | H.264 1920x1080; 60 fresh decoded frames; clean pixel checks |
| cam02 | H.264 1920x1080; 60 fresh decoded frames; clean pixel checks |
| cam05 | H.264 1920x1080; 60 fresh decoded frames; clean pixel checks |
| cam06 | H.265 1920x1080; 60 fresh decoded frames; clean raw sample; browser compatibility remains unverified |
| cam12 | H.265 1280x720; 60 fresh decoded frames; clean raw sample; browser compatibility remains unverified |

These are the strongest **raw RTSP/PyAV** candidates, not a claim of browser
smoothness. cam01/cam02/cam05 are safer first choices because they are H.264.

## Safe secondary cameras

`cam11`, `cam13`, `cam14`, `cam15`, `cam17`, `cam19`, `cam20`, and `cam29`
produced fresh frames and no visual corruption classification in this bounded
capture. Their lower frame counts or H.265 codec should be treated as a
secondary qualification, not as a 30-camera guarantee.

## Degraded cameras

| Camera | Reason |
| --- | --- |
| cam03 | Raw H.264 frame showed macroblock/chroma artefact signal |
| cam04 | Only four fresh frames in capture; continuity weak |
| cam07 | No fresh frame in capture; prior RTSP run was marginal |
| cam10 | Only two fresh frames; continuity unproven |
| cam21 | No fresh frame in capture; prior RTSP run was marginal |
| cam23 | One fresh frame; prior diagnostic had input/output error |
| cam26 | H.265 2560x1440 raw frame visibly white/overexposed; only one fresh frame |

## Do not use cameras

`cam08`, `cam09`, `cam16`, `cam18`, `cam22`, `cam24`, `cam25`, `cam27`, `cam28`,
and `cam30` produced no fresh raw frame in the certification capture. They
should not be placed on the main judge wall until repeated authenticated runs
establish continuous progression.

## Important boundary

This selection is based on authenticated raw RTSP/PyAV evidence only. No
gateway, WebRTC, HLS, browser screenshot, or AI-on comparison artifacts exist
for this run. The UI should show the selected-camera fallback behavior and
avoid presenting the entire 30-camera estate as uniformly live.
