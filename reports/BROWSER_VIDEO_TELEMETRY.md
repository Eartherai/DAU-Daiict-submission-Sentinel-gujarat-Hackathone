# Browser video telemetry

## Scope

The live wall exposes a small operator telemetry panel for values the browser can
actually observe. It is diagnostic evidence, not a substitute for host-level
capacity measurement or a government-feed result.

The panel reports:

- active and total playing video elements;
- visible wall tiles;
- snapshot request startup duration and the latest request error;
- WHEP negotiation startup duration and the latest negotiation error;
- playback/reconnect state;
- WebRTC inbound-video stats when exposed: decoded/dropped frames, packets
  received/lost, FPS, jitter, jitter-buffer delay, RTT, codec, decoder, and
  resolution;
- a no-frame watchdog that marks the selected stream `NO_FRAME` or `DEGRADED`
  instead of leaving a connected black stage looking healthy;
- explicit `UNAVAILABLE` for CPU, GPU, and network utilisation because the
  browser surface does not reliably expose those values.

## Source and mode labels

The handling bar also displays separate labels for government feed, own feed /
full analytics, and central analytics mode. These values are populated only from
the deployment configuration returned by the service. Missing fields remain
`not reported`; the UI does not infer a government or central-analytics claim
from the presence of a camera tile.

## Wall behaviour

The operator can select 4, 9, 16, or 30 wall slots and filter by
`PRIMARY`, `SECONDARY`, `PREVIEW`, or `INACTIVE` priority. Snapshot requests are
shared and briefly cached across the grid, filmstrip, and table views, so a
single camera does not create duplicate upstream requests for each visual
representation. The selected camera may still use WHEP when the deployment
provides it; otherwise the UI remains on the snapshot path.

## Validation status

`node --check ui/app.js` passes. Browser telemetry has not been presented as a
measured CPU/GPU/network benchmark, and no full approximately-50-camera
government-feed browser result is claimed without the required authenticated
feed and venue environment.
