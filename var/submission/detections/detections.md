# Detection output report

Produced from the live Gujarat government feed by `tools/verify/detection_report.py`. Every row is an observation this system recorded; none is illustrative.

- **444,073 detections** across **30 cameras**
- **77 carry a registration mark** (34 distinct)
- Window: 2026-09-02T01:24:47.770+00:00 to 2026-09-04T15:15:32.207+00:00

## What was detected

- **209,559** car
- **116,678** person
- **81,621** truck
- **20,976** bus
- **5,599** motorcycle
- **5,133** bicycle
- **1,965** truck_bus
- **1,681** van
- **861** unknown

People are counted separately from vehicles. They are never given a registration mark. Dwell is recorded; the word *intrusion* is not — that is a judgement about permission this system cannot make.

## Why so few registration marks

Most cameras on this estate are graded **UNSUITABLE** for plate reading, measured from their own streams rather than assumed: at these mountings a plate is around forty pixels wide. The system therefore reports thousands of *vehicles* and few *marks*, and grades each camera so an investigator knows before relying on it which question it can answer.

Cameras graded UNSUITABLE for ANPR: cam01, cam02, cam03, cam04, cam05, cam06, cam07, cam08, cam09, cam10, cam11, cam12, cam13, cam14, cam15, cam16, cam17, cam18, cam19, cam20, cam21, cam23, cam24, cam25, cam26, cam27, cam29, cam30.

## Registration marks read

One row per mark per camera. Repeated reads of the same plate on a looping camera are counted in **Hits**, not listed as a fleet.

| Last seen (UTC) | Camera | Location | Mark | Hits | Votes | Confidence |
|---|---|---|---|---|---|---|
| 2026-09-04T06:49:20.324+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **AR01R5151** | 3 | 3 | 0.905 |
| 2026-09-04T01:39:57.992+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **AR62387** | 1 | 2 | 0.787 |
| 2026-09-04T01:23:28.553+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **CG04L6989** | 1 | 2 | 0.749 |
| 2026-09-04T07:18:51.551+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ01DY5552** | 1 | 2 | 0.945 |
| 2026-09-04T13:49:47.070+00:00 | cam18 Rajkot CCTV | Rajkot | **GJ07TU6681** | 1 | 1 | 0.864 |
| 2026-09-04T09:52:04.089+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11BR2912** | 1 | 2 | 1.000 |
| 2026-09-04T02:41:39.741+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11C2226** | 1 | 2 | 0.748 |
| 2026-09-04T06:24:49.739+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11C9993** | 1 | 2 | 0.867 |
| 2026-09-04T06:25:06.718+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11CQ9932** | 1 | 2 | 0.916 |
| 2026-09-04T10:13:51.987+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ179966** | 1 | 2 | 0.810 |
| 2026-09-04T14:31:06.335+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ18BQ1681** | 1 | 1 | 0.943 |
| 2026-09-03T23:09:30.695+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ1F9922** | 1 | 2 | 0.762 |
| 2026-09-04T14:18:28.675+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ1VV0119** | 2 | 2 | 0.828 |
| 2026-09-04T10:13:34.625+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ1Z9966** | 2 | 2 | 0.811 |
| 2026-09-02T01:27:39.168+00:00 | cam20 Mohanpura | Gujarat (town not confirmed) | **GJ21T4831** | 1 | 2 | 0.922 |
| 2026-09-04T08:56:18.974+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ27B5130** | 1 | 3 | 0.809 |
| 2026-09-04T14:47:34.055+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ27BE6797** | 1 | 1 | 0.894 |
| 2026-09-04T05:15:28.837+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ31144** | 1 | 2 | 0.654 |
| 2026-09-04T01:41:27.273+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ31T8156** | 1 | 3 | 0.973 |
| 2026-09-04T06:46:33.444+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ32AG0028** | 38 | 4 | 0.968 |
| 2026-09-04T01:13:21.131+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32AG1811** | 1 | 2 | 1.000 |
| 2026-09-04T03:06:55.460+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32B3783** | 2 | 2 | 0.948 |
| 2026-09-03T20:13:10.252+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K0466** | 1 | 2 | 0.990 |
| 2026-09-04T02:47:34.512+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K8511** | 1 | 2 | 0.953 |
| 2026-09-04T14:27:07.313+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K8758** | 1 | 1 | 0.922 |
| 2026-09-04T10:36:02.673+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ33H2219** | 1 | 2 | 0.664 |
| 2026-09-02T01:26:22.336+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ38BH5815** | 1 | 2 | 0.995 |
| 2026-09-04T09:03:12.296+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ38TA7874** | 1 | 2 | 0.952 |
| 2026-09-04T14:50:19.533+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ3GAL6389** | 1 | 1 | 0.929 |
| 2026-09-04T13:17:22.729+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ3RRD4697** | 1 | 1 | 0.913 |
| 2026-09-04T01:12:02.412+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **GJ810962** | 1 | 2 | 0.816 |
| 2026-09-04T15:05:59.401+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ8R6860** | 1 | 1 | 0.823 |
| 2026-09-04T01:42:18.485+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **MH127339** | 1 | 2 | 0.795 |
| 2026-09-04T06:54:54.038+00:00 | cam06 Timbavadi Gate | Junagadh | **RJ27CR3745** | 2 | 5 | 0.998 |

## Vehicles detected, by camera

| Camera | Detections |
|---|---|
| cam01 | 67,239 |
| cam04 | 56,478 |
| cam05 | 50,037 |
| cam10 | 43,218 |
| cam02 | 32,944 |
| cam16 | 29,219 |
| cam14 | 29,043 |
| cam11 | 27,000 |
| cam08 | 22,491 |
| cam13 | 17,556 |
| cam21 | 16,083 |
| cam17 | 13,908 |
| cam25 | 8,116 |
| cam18 | 7,048 |
| cam07 | 6,282 |
| cam12 | 3,174 |
| cam27 | 2,711 |
| cam06 | 2,506 |
| cam30 | 1,613 |
| cam03 | 1,472 |

## By object type

| Type | Count |
|---|---|
| car | 209,559 |
| person | 116,678 |
| truck | 81,621 |
| bus | 20,976 |
| motorcycle | 5,599 |
| bicycle | 5,133 |
| truck_bus | 1,965 |
| van | 1,681 |
| unknown | 861 |

## Sample of 40 detections

The full set is in the accompanying CSV.

| Timestamp (UTC) | Camera | Type | Colour | Mark | Quality |
|---|---|---|---|---|---|
| 2026-09-04T15:15:32.207+00:00 | cam01 | person | — | — |  |
| 2026-09-04T15:15:31.979+00:00 | cam02 | person | — | — |  |
| 2026-09-04T15:15:30.910+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:30.910+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:30.910+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:30.910+00:00 | cam08 | bus | — | — |  |
| 2026-09-04T15:15:30.910+00:00 | cam08 | bus | blue | — | 0.929 |
| 2026-09-04T15:15:30.910+00:00 | cam08 | car | grey | — | 0.876 |
| 2026-09-04T15:15:30.910+00:00 | cam08 | car | green | — | 0.597 |
| 2026-09-04T15:15:30.910+00:00 | cam08 | car | — | — | 0.816 |
| 2026-09-04T15:15:30.174+00:00 | cam04 | person | — | — |  |
| 2026-09-04T15:15:30.174+00:00 | cam04 | person | — | — |  |
| 2026-09-04T15:15:29.528+00:00 | cam01 | car | — | — | 0.822 |
| 2026-09-04T15:15:29.528+00:00 | cam01 | car | orange | — | 0.749 |
| 2026-09-04T15:15:29.528+00:00 | cam01 | car | orange | — | 0.593 |
| 2026-09-04T15:15:26.993+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:26.993+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:26.993+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:26.993+00:00 | cam08 | bus | — | — |  |
| 2026-09-04T15:15:26.993+00:00 | cam08 | bus | blue | — | 0.930 |
| 2026-09-04T15:15:26.993+00:00 | cam08 | car | — | — | 0.795 |
| 2026-09-04T15:15:26.993+00:00 | cam08 | car | black | — | 0.881 |
| 2026-09-04T15:15:26.993+00:00 | cam08 | car | green | — | 0.755 |
| 2026-09-04T15:15:26.993+00:00 | cam08 | truck | blue | — | 0.930 |
| 2026-09-04T15:15:26.827+00:00 | cam01 | car | — | — | 0.381 |
| 2026-09-04T15:15:26.827+00:00 | cam01 | car | white | — | 0.716 |
| 2026-09-04T15:15:26.658+00:00 | cam02 | car | grey | — | 0.925 |
| 2026-09-04T15:15:26.658+00:00 | cam02 | car | — | — | 0.166 |
| 2026-09-04T15:15:26.428+00:00 | cam14 | car | grey | — | 0.591 |
| 2026-09-04T15:15:26.114+00:00 | cam04 | car | — | — | 0.995 |
| 2026-09-04T15:15:25.025+00:00 | cam05 | car | — | — | 0.296 |
| 2026-09-04T15:15:25.025+00:00 | cam05 | car | white | — | 0.968 |
| 2026-09-04T15:15:24.226+00:00 | cam13 | person | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | truck | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | bus | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | truck | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | car | — | — |  |
| 2026-09-04T15:15:24.096+00:00 | cam08 | car | green | — | 0.762 |
