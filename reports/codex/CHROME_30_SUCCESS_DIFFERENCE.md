# Standalone Chromium success vs application wall

Measured on 2026-09-20 against the actual local application and relay.

| Area | Standalone Chromium test | Application before repair | Repair / result |
|---|---|---|---|
| Browser transport | Persistent local WHEP peer per camera | HLS was selected for every grid tile | Local WHEP is now the default; HLS requires explicit `?transport=hls` |
| Media element lifecycle | One video element and peer held for the test | HLS element attached after an early one-shot `play()` | WHEP video is persistent; playback is retried on metadata/canplay |
| Playback proof | `currentTime`, decoded frames and WebRTC stats | One decoded frame could briefly set LIVE | LIVE requires recent `requestVideoFrameCallback`; browser test also measures time advancement |
| Wall quality | Relay/source rendition used by WHEP | 240–256×144 at 3 fps | 640×360 at 8 fps and 450 kbps |
| Keyframes/timing | Browser-decodable WHEP | Relay lacked reliable regular IDR and used incorrect cadence timestamps | Two-second-or-less GOP, no B-frames, explicit timebase, source-PTS sampling |
| Startup | Controlled WHEP waves | Thirty HLS muxers and retries | WHEP peers staggered 450 ms and held |
| Upstream retry | Test run did not supervise long-lived admission failure | Outer supervisor killed the child after 18 s, defeating its 300 s 401 backoff | Live child is retained through cooldown; no forced respawn before retry |
| Status | Test measured actual browser state | Relay-ready and poster frames could influence LIVE | Relay state and browser playback state remain separate |
| Current external state | Previously had admitted Sentinel paths | Sentinel currently returns 401 for both pools after the old restart storm | Exact blocker is upstream admission cooldown; application correctly reports no live government path |

## Current acceptance facts

- The repaired HLS diagnostic path proved 640×360 moving playback before the switch to WHEP.
- The primary application path is now persistent local WHEP.
- Current local MediaMTX government readiness is 0/30 because Sentinel is returning 401, not because WHEP SDP, autoplay, or the DOM is being rebuilt.
- The backup account's portal form login currently returns HTTP 403. No credential is written here.
- No 30/30 claim is valid until all 30 browser videos advance over a measurement window.

## Required next gate

Allow the enforced Sentinel cooldown to elapse without restarting publishers. Then measure, in the real application, for every camera:

1. local relay path ready;
2. WHEP video has decoded dimensions;
3. video is not paused;
4. `currentTime` advances;
5. frame callbacks remain recent.

Only after 30/30 passes should AI scaling or recording begin.
