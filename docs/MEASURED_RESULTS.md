# Measured results

Every figure below is read from a report file or from the live store by `tools/verify/measured_results.py`. None is typed by hand, and each carries the artefact it came from so any claim on a slide can be traced to the run that produced it.

A row reading **not measured** is a gap, stated rather than dropped. Synthetic-corpus figures are never substituted for live ones.

Generated 2026-09-06T21:02:56+00:00.

## The estate, on the live government grid

| Claim | Measured | Source |
|---|---|---|
| Cameras onboarded | 30 | `live store` |
| Cameras with a position | 19 of 30 | `live store` |
| Codec mix | 23x h264, 6x hevc | `live store` |
| Resolution mix | 18x 1920x1080, 5x 1280x720, 4x 1280x960, 1x 960x576, 1x 2560x1440 | `live store` |
| Monochrome / infrared cameras | 13 of 29 profiled, detected from imagery not configuration | `var/reports/live_camera_profile.json` |

## Live ingest

| Claim | Measured | Source |
|---|---|---|
| 6 cameras, 16.98 min: streaming | 6 | `var/reports/live_ingest.json` |
| 6 cameras, 16.98 min: frames delivered | 11,145 | `var/reports/live_ingest.json` |
| 6 cameras, 16.98 min: observations | 181 | `var/reports/live_ingest.json` |
| 6 cameras, 16.98 min: reconnects / decoder warnings / scene cuts | 2 / 1002 / 0 | `var/reports/live_ingest.json` |
| 6 cameras, 16.98 min: peak RSS | 1628 MB | `var/reports/live_ingest.json` |
| 6 cameras, 81.4 min: streaming | 6 | `var/reports/live_cluster.json` |
| 6 cameras, 81.4 min: frames delivered | 35,980 | `var/reports/live_cluster.json` |
| 6 cameras, 81.4 min: observations | 7,752 | `var/reports/live_cluster.json` |
| 6 cameras, 81.4 min: reconnects / decoder warnings / scene cuts | 0 / 0 / 0 | `var/reports/live_cluster.json` |
| 6 cameras, 81.4 min: peak RSS | 1522 MB | `var/reports/live_cluster.json` |
| 8 cameras, 5.0 min: streaming | 8 | `var/reports/live_located.json` |
| 8 cameras, 5.0 min: frames delivered | 16,266 | `var/reports/live_located.json` |
| 8 cameras, 5.0 min: observations | 3,696 | `var/reports/live_located.json` |
| 8 cameras, 5.0 min: reconnects / decoder warnings / scene cuts | 0 / 0 / 0 | `var/reports/live_located.json` |
| 8 cameras, 5.0 min: peak RSS | 1659 MB | `var/reports/live_located.json` |
| Concurrent streams sustained on one host | 44 of 50 | `var/reports/camera_load.json` |
| Analytics throughput, one process | 11.4 frames/s (~11.4 cameras at 1 fps) | `var/reports/camera_load.json` |

## What the cameras can actually do

| Claim | Measured | Source |
|---|---|---|
| Cameras graded | 30 of 30 | `live store` |
| ANPR grades, per camera | 28 UNSUITABLE, 2 UNKNOWN | `live store, graded from each camera's own stream` |
| Appearance grades, per camera | 20 GOOD, 8 DEGRADED, 2 UNKNOWN | `live store, graded from each camera's own stream` |
| Presence grades, per camera | 27 GOOD, 3 DEGRADED | `live store, graded from each camera's own stream` |

## Timebase, measured from the cameras' own clocks

| Claim | Measured | Source |
|---|---|---|
| Burned-in clocks read | 26 of 30 cameras, by a vision model running locally | `var/reports/overlays.json` |
| Largest shared-timebase cluster | 13 cameras: cam01, cam02, cam03, cam04, cam05, cam07, cam08, cam09, cam10, cam11, cam12, cam13, cam14 | `var/reports/overlays.json` |
| Cameras in a declared cluster | 13 of 21 | `live store` |
| Cameras whose own timing is sound enough to correlate | 12 of 21 | `live store` |

## Camera positions and their support

| Claim | Measured | Source |
|---|---|---|
| Position precision | 10 LOCALITY, 7 LANDMARK, 2 CITY | `live store` |
| Signage corroboration of position | 13 NO SIGNAGE READ, 8 CORROBORATED, 5 NO OVERLAP, 4 UNREACHABLE | `var/reports/landmarks.json` |

## Analytics output

| Claim | Measured | Source |
|---|---|---|
| Observations stored | 689,502 | `live store` |
| Person observations | 178,757 | `live store` |
| Person long-stay (dwell ≥ 12 s on one camera; not intrusion) | 42,089 | `live store` |
| Object mix (detector labels from the same pass, not identity) | 328,364 car, 178,777 person, 127,351 truck, 32,283 bus, 8,633 motorcycle, 7,344 bicycle, 2,929 truck_bus, 2,612 van, 1,203 unknown | `live store` |
| Observations carrying a registration mark | 117 | `live store` |
| Confirmed plates (votes ≥ 2) | 74 | `live store` |
| Plate leads (votes = 1, uncorroborated) | 43 | `live store` |
| Raw OCR attempts stored (including rejected) | 3,380 | `live store` |
| Cameras that published a mark | 9 | `live store` |
| Distinct marks read from the government feed | 69: AR01R5151, AR62387, CG04L6989, GJ01DY5552, GJ02778, GJ07TU6681, GJ11AS7722, GJ11BR2912, GJ11C2226, GJ11C9993, GJ11CQ9932, GJ179966, GJ182956, GJ18BQ1681, GJ18E2297, GJ18ZT2911, GJ198699, GJ1F9922, GJ1VV0119, GJ1Z9966, GJ21T4831, GJ21Y5061, GJ24A0715, GJ27AA1423, GJ27B5130, GJ27BE6797, GJ27DS1308, GJ2AAA1423, GJ31144, GJ31T1460, GJ31T8156, GJ32AA9000, GJ32AG0028, GJ32AG0344, GJ32AG1811, GJ32AG1849, GJ32B3783, GJ32B5149, GJ32D0107, GJ32K0466, GJ32K5507, GJ32K5587, GJ32K6903, GJ32K8511, GJ32K8758, GJ32K9785, GJ32NG2747, GJ32T0330, GJ32T6171, GJ33H2219, GJ37J4666, GJ38B4457, GJ38BH5815, GJ38BK4597, GJ38TA7874, GJ39T3513, GJ3GAL6389, GJ3RRD4697, GJ3ZK5587, GJ3ZT7383, GJ5K0315, GJ810962, GJ8R6860, GJ99988, MH127339, MH1TQT1656, RJ22GB1677, RJ24CB0410, RJ27CR3745 | `live store` |
| Exact cross-camera repeats among those marks | 0 | `live store` |
| OCR-lookalike pairs among those marks (one-character O/0 B/8 G/6 and kin) | 1: GJ32K5587/GJ3ZK5587 | `live store` |
| Alerts raised | 1 | `live store` |
| Evidence records | 3 | `live store` |
| Audit entries | 424 | `live store` |

## Latency

| Claim | Measured | Source |
|---|---|---|
| Search on the live store | 3.4 ms | `var/reports/live_evaluation.json` |
| Trajectory on the live store | 1.5 ms | `var/reports/live_evaluation.json` |
| Whole evaluation, ten stages | 0.017 s | `var/reports/live_evaluation.json` |
| API routes measured | 18 | `var/reports/api_latency.json` |
| Slowest route, p50 | 23.09 ms (GET  /audit) | `var/reports/api_latency.json` |
| Fastest route, p50 | 2.04 ms (GET  /gis/alerts) | `var/reports/api_latency.json` |
| Worst p99 across routes | 44.69 ms | `var/reports/api_latency.json` |

## Transport

| Claim | Measured | Source |
|---|---|---|
| Video off the wire | 1.363 Mbps across 3 cameras | `var/reports/bandwidth.json` |
| Observations, at peak event rate | 0.070668 Mbps (1331.7 bytes each) | `var/reports/bandwidth.json` |
| Ratio | 19.3x | `var/reports/bandwidth.json` |

## Assurance

| Claim | Measured | Source |
|---|---|---|
| Release gates | 14 of 14 pass | `var/reports/release_check.json` |
| Release candidate | True | `var/reports/release_check.json` |
| API routes verified against the live store | 46 pass, 0 fail | `var/reports/api_surface.json` |
| Security controls, each attacked | 14 of 14 refused the forbidden action | `var/reports/security_scorecard.json` |
| Cases where the right answer is no | 11 of 11 refused correctly | `var/reports/wrong_cases.json` |
| Models ACTIVE / FAILED | 4 / 2 | `var/reports/model_activation.json` |
