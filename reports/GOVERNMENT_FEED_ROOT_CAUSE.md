# Government feed root-cause status

## Proven

| Finding | Evidence |
| --- | --- |
| Authenticated RTSP/TCP access works for the supplied authority credentials | cam01 and the concurrent 30-camera run opened authenticated RTSP sessions |
| Raw RTSP/PyAV frames can be visually degraded | fresh raw cam03 was flagged for macroblock artefacts; cam26 was visibly white/overexposed; these are raw-frame findings |
| Some cameras opened but produced no usable fresh frame in the bounded run | fresh capture: cam07, cam08, cam09, cam16, cam18, cam21, cam22, cam24, cam25, cam27, cam30 had no fresh JPEG |
| Gateway/browser/WebRTC stages were not exercised | no gateway endpoint/browser session/WebRTC stats artifacts exist under `var/reports/live30_live/` |
| No AI-induced playback conclusion is possible | AI-on/browser comparison was not run |

## Likely, but not proven

- For raw frames that are already macroblocked or overexposed, the defect is
  present at or before the PyAV raw-decode boundary. Candidate causes are
  source encoder, RTP loss/reordering, missing reference frames, or decoder
  concealment.
- For no-frame cameras, candidate causes include source availability,
  per-camera stream scheduling, keyframe wait, network variability, or decoder
  failure. A socket opening is not evidence of a live stream.
- H.265 may contribute to browser incompatibility for cam06/cam12/cam17/cam18/
  cam22/cam26, but this is unverified because browser WHEP was not tested.

## Unverified

| Layer | Status |
| --- | --- |
| Government source encoder | UNVERIFIED |
| Packet loss / RTP jitter | UNVERIFIED; no packet capture or gateway stats |
| Gateway | UNAVAILABLE |
| WebRTC/WHEP | UNAVAILABLE |
| HLS | UNAVAILABLE beyond an unauthenticated redirect |
| Browser rendering | UNAVAILABLE |
| Overlay | UNAVAILABLE |

The correct wording is: **“Raw RTSP/PyAV frame is already degraded.”** It is
not yet valid to say “government-side problem” until the same camera is compared
through a gateway and browser path.
