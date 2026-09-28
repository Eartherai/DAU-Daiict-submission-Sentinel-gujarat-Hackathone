# Integrating the government live grid

This is a dated account of the integration work and its limits. MEASURED means
a retained report records the result; VERIFIED means the cited implementation
was inspected. Organiser guidance and team-reported history are attributed
separately. Live counts describe a test window, not a sandbox quota or a
universal bridge limit. The government sandbox serves recorded footage as
simulated live streams; the submitted screen recording is **RECORDED**.
Source: [sandbox integration record](SENTINEL_SANDBOX.md).

## Measurements reported to Sentinel on 19 September 2026

The retained census and bridge reports are dated 16 September in UTC. The team
reported these results to Sentinel on 19 September; the report date is not
the test date. The correspondence date is the team's record of when the
message was sent; the mail itself is retained by the team, not in this repository.

| Finding | Evidence and boundary |
|---|---|
| MEASURED: all 30 documented camera IDs produced RTSP frames during the census window. | [Phase 14 census](../reports/PHASE14_REAL_CAMERA_SOURCE_CENSUS.md), summary; `var/reports/phase10/performance/phase14_source_census.json`. This is source reachability, not a simultaneous live browser wall. The probe-derived catalogue is labelled NOT_AUTHORITATIVE. |
| MEASURED: 15 cameras produced direct WHEP browser frames; the other 15 were RTSP-only bridge candidates in that window. | Same census; [Phase 16 source matrix](../reports/PHASE16_30_CAMERA_BROWSER_COVERAGE.md). The H.264 compatibility path re-encoded B-frame sources to baseline H.264 for browser playback. This is a historical compatibility result, not a permanent classification of the grid. |
| MEASURED: the local VideoToolbox path reached 15 concurrent preview bridges under the scale test's source conditions. | [Phase 16 bridge concurrency table](../reports/PHASE16_30_CAMERA_BROWSER_COVERAGE.md); `var/reports/phase10/performance/phase16_bridge_scale.json`. It does not establish a maximum for every machine or source mix. |
| MEASURED: a 19-camera hybrid wall, comprising 15 direct WHEP and 4 bridged cameras, held through the 60-second measurement with 0 NO_SIGNAL. | [Phase 16 hybrid wall table](../reports/PHASE16_30_CAMERA_BROWSER_COVERAGE.md); `var/reports/phase10/performance/phase16_hybrid_wall_60s.json`. The historical classifications were 8 LIVE, 11 PREVIEW and 11 RTSP_ONLY_AI. Zero NO_SIGNAL does not mean every camera was visible in the browser. |

The mixed-source wall exposed upstream RTSP authentication failures, timeouts
and source-availability degradation as fan-in increased. The bridge scale
test and the mixed-camera wall were different experiments. Their results do
not establish a local VideoToolbox encode-capacity limit or an upstream
session quota. Source: [retained limitations report, corrected interpretation](../reports/FINAL_LIMITATIONS_AND_EXTERNAL_DEPENDENCIES.md)
and [organiser clarification](SENTINEL_SUPPORT_CLARIFICATION.md).

## What we asked, and the answer

The team's sanitised account of the 19 September question asked for intended
concurrency limits, any per-team, IP or camera limits, guidance for long-lived
sessions, the recommended pattern for a 30-camera demonstration, an
`/api/ingest` catalogue, and connection-staggering or rate-limit guidance.
The aim was “a genuine 30-camera live demonstration, rather than substituting
synthetic streams”. Source: the message as sent, retained by the team; in the
repository, the retained [concurrent-access record](SENTINEL_SANDBOX.md#concurrent-access--what-the-organisers-said-and-what-this-platform-does)
also records the request for limits and the expected integration pattern.
No mail identities or access details are reproduced here.

Sentinel's answer, paraphrased from that record and the
[sanitised support clarification](SENTINEL_SUPPORT_CLARIFICATION.md), was:

- There is no fixed participant-facing concurrent RTSP limit per team, IP,
  camera or aggregate, and no fixed participant-facing rate limit.
- Availability varies with shared sandbox usage and gateway load. Keep only
  needed streams open and avoid unnecessary long-lived or repeated sessions.
- Design independently of the supplied camera count. Per-camera isolation
  and reconnection with backoff are appropriate; stagger connections.
- No separate participant-specific `/api/ingest` catalogue is provided.
- Large-fan-in variation should not be read as a local-bridge limitation.

This is support guidance, not a measured performance guarantee. We did not
establish why a particular authentication refusal occurred.

## The implementation we rebuilt and hardened

The response shaped the following operating choices. These are VERIFIED in
the cited code; they are not a claim that every mechanism was first written
after the reply.

| Choice | Implementation and operator meaning |
|---|---|
| Direct browser WHEP through authenticated signalling | `src/saakshya/api/routes_investigation.py:506` checks camera-read permission and district scope, then adds upstream authentication server-side. The browser receives the signalling answer, not the grid credentials. Media flows directly from the media server. |
| Two explicit wall policies | `ui/app.js:2760` and `ui/app.js:2812`; `#media-policy` names CONTROL ROOM or OPTIMIZED VIEW. On the direct WHEP path, CONTROL ROOM allows up to 30 sessions, opened 400 ms apart. OPTIMIZED VIEW budgets at most 12 near the viewport, prefetches 600 px and releases sessions after 15 s off screen. These are local policies, not promised live counts. |
| On-demand capture hub | `src/saakshya/live/hub.py:292` registers sources, opens AI-assigned cameras and own files as required, and opens other government cameras on demand. `live/snapshot.py` reuses hub ownership instead of opening a redundant capture. |
| Selected deep inference | `src/saakshya/analytics/worker.py:353`: **4 deep-inference slots, prioritised by measured capability**. Assignment occurs at worker boot; this does not rotate coverage over every camera. Wall playback and AI coverage are separate measurements. |
| Truthful playback state | `ui/app.js:4670` checks decoded-frame progress and recent rendered frames. `ui/app.js:4502` gives archival cameras REPLAY status. A connection or cached still alone is not advancing live video. Recorded government clips must remain labelled RECORDED; synthetic route material remains SYNTHETIC RENDERED TEST CORPUS. |
| Recording preflight and stall hand-over | `tools/demo/record_government_feed.py:385` measures readiness before recording; `:874` checks the opening again; `:940` handles stalls, including selection of another advancing focus camera. These gates constrain a take; they do not guarantee the upstream will stay available. |
| Government-only output report | `tools/demo/record_government_feed.py:732` requests `/reports/anpr.csv?reads=all&domain=GOVERNMENT` and validates the returned rows. The delivered report keeps government findings separate from own-feed and synthetic data. |

## 28 September: the recording session

The team made **eight recording attempts** on 28 September. Six left records
in `var/demo/gov_take{1,4,5,6,7,8}/` (`beats.json`, `preflight.json`):

- takes 1 and 5 stopped when the focused government video stopped advancing;
  the recorder gained a bounded hand-over to the next advancing camera;
- take 4 timed out on the person-detections beat behind a search spinner;
  the UI was fixed;
- take 6 stopped before filming because opening availability fell after
  preflight; a bounded re-sample was added;
- take 7 is the submitted 5:40 film. It ended when the bulk-validation beat
  failed, so the refusal and handoff beats were not filmed;
- take 8's preflight found no advancing video: from 12:57 IST the grid
  returned 401 to this project's credentials.

The other two attempts left no retained directory. Every stop was the
recorder refusing a take rather than filming a stall or a loading screen.

**MEASURED:** the recording session showed **6–13 of 30** government cameras
advancing at once. The submitted take is **5:40**, recorded at approximately
**12:41–12:47 IST**, with the live count visible in the wall beats. It is a
recording of that test window, not a current live view. Sources:
`var/demo/gov_take7/beats.json`, `var/demo/gov_take7/capture.json`,
[submission certification, Films](../reports/FINAL_SUBMISSION_CERTIFICATION.md#films-measured-ffprobe-and-extracted-frames)
and [session evidence snapshot](../reports/SUBMISSION_EVIDENCE_SNAPSHOT.md#28-sep-2026-live-recording-session-measured).

**MEASURED:** the current recogniser produced **200 live cam06 plate reads
during the 28 September recording session, 11:15–12:53 IST**. Only **21** fall
within the filmed take's **12:40:59–12:47:22 IST** window. Sources:
`var/demo/government_feed_anpr_report.csv` and the session evidence snapshot
above. Those are single-camera findings; they do not establish a real
multi-camera route.

From **12:57 IST**, the project's grid credentials were rejected with
**401 Unauthorized** on RTSP and WHEP, preventing further live recording.
Source: [submission certification, Known external limitations](../reports/FINAL_SUBMISSION_CERTIFICATION.md#known-external-limitations).
The rejection is recorded; its cause is not established. Neither the live
count nor the rejection proves a fixed sandbox concurrency limit.

This account describes the submitted take identified above. A later replay
or replacement film needs its own capture date, source-domain label and
measured results; it must not inherit these live-session claims.
