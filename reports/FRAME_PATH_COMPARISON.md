# Frame path comparison

## Current authenticated evidence

The raw/source side is now captured for the authenticated RTSP run under
`var/reports/live30_live/frames/`. The gateway and browser stages are
**UNAVAILABLE** because no WHEP gateway/browser session is configured in this
environment.

| Camera | Raw RTSP/PyAV | Gateway | Browser | Current conclusion |
| --- | --- | --- | --- | --- |
| cam01 | decoded usable frame | UNAVAILABLE | UNAVAILABLE | raw source path works |
| cam03 | decoded frame flagged by corruption heuristic | UNAVAILABLE | UNAVAILABLE | source/transport/decode requires repeat test |
| cam10 | decoded usable sample in fresh capture | UNAVAILABLE | UNAVAILABLE | raw path works in this run |
| cam18 | no frame in bounded capture | UNAVAILABLE | UNAVAILABLE | source/network/decode undetermined |
| cam30 | decoder failure / no stable frame | UNAVAILABLE | UNAVAILABLE | source/network/decode undetermined |

No browser corruption is attributed without a browser frame. The fresh contact
sheet is not evidence of gateway or frontend rendering because it is assembled
from raw RTSP/PyAV frames.

## Required next comparison

For each RED/AMBER camera, capture source frame, gateway snapshot, browser
screenshot, and WebRTC stats from the same UTC window. Only then classify the
first layer where a green, black, or macroblock artifact appears.
