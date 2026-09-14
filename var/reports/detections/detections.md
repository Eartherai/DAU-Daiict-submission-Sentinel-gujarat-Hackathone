# Detection output report

Produced from the live Gujarat government feed by `tools/verify/detection_report.py`. Every row is an observation this system recorded; none is illustrative.

- **749,189 detections** across **30 cameras**
- **128 carry a registration mark** (75 distinct)
- Window: 2026-09-02T01:24:47.770+00:00 to 2026-09-07T11:51:02.542+00:00

## What was detected

- **350,535** car
- **197,326** person
- **140,783** truck
- **35,469** bus
- **9,522** motorcycle
- **8,431** bicycle
- **3,084** truck_bus
- **2,741** van
- **1,298** unknown

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
| 2026-09-06T22:04:38.909+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ010555** | 1 | 1 | 0.824 |
| 2026-09-06T22:04:06.951+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ01DY5552** | 3 | 2 | 0.945 |
| 2026-09-06T11:52:25.185+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ02778** | 1 | 1 | 0.837 |
| 2026-09-04T13:49:47.070+00:00 | cam18 Rajkot CCTV | Rajkot | **GJ07TU6681** | 1 | 1 | 0.864 |
| 2026-09-04T20:09:32.460+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ11AS7722** | 1 | 1 | 0.958 |
| 2026-09-04T09:52:04.089+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11BR2912** | 1 | 2 | 1.000 |
| 2026-09-04T02:41:39.741+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11C2226** | 1 | 2 | 0.748 |
| 2026-09-04T06:24:49.739+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11C9993** | 1 | 2 | 0.867 |
| 2026-09-04T06:25:06.718+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ11CQ9932** | 1 | 2 | 0.916 |
| 2026-09-06T22:09:26.531+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ11Z9966** | 2 | 1 | 0.904 |
| 2026-09-04T10:13:51.987+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ179966** | 1 | 2 | 0.810 |
| 2026-09-04T18:45:55.500+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ182956** | 1 | 1 | 0.909 |
| 2026-09-04T14:31:06.335+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ18BQ1681** | 1 | 1 | 0.943 |
| 2026-09-06T13:31:26.850+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ18E2297** | 1 | 1 | 0.830 |
| 2026-09-06T21:12:36.774+00:00 | cam08 Majewadi Gate | Junagadh | **GJ18ZT1080** | 2 | 1 | 0.969 |
| 2026-09-06T22:11:41.003+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ18ZT1284** | 2 | 2 | 0.997 |
| 2026-09-04T20:16:05.765+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ18ZT2911** | 1 | 1 | 0.935 |
| 2026-09-06T20:58:45.643+00:00 | cam08 Majewadi Gate | Junagadh | **GJ198699** | 1 | 2 | 0.783 |
| 2026-09-06T22:34:01.511+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ1BZT2227** | 1 | 1 | 0.982 |
| 2026-09-03T23:09:30.695+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ1F9922** | 1 | 2 | 0.762 |
| 2026-09-04T14:18:28.675+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ1VV0119** | 2 | 2 | 0.828 |
| 2026-09-04T10:13:34.625+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ1Z9966** | 2 | 2 | 0.811 |
| 2026-09-02T01:27:39.168+00:00 | cam20 Mohanpura | Gujarat (town not confirmed) | **GJ21T4831** | 1 | 2 | 0.922 |
| 2026-09-06T21:01:51.887+00:00 | cam20 Mohanpura | Gujarat (town not confirmed) | **GJ21Y5061** | 1 | 1 | 0.989 |
| 2026-09-06T12:17:17.547+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ24A0715** | 1 | 1 | 0.844 |
| 2026-09-06T20:33:11.184+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ27AA1423** | 1 | 2 | 0.897 |
| 2026-09-04T08:56:18.974+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ27B5130** | 1 | 3 | 0.809 |
| 2026-09-04T14:47:34.055+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ27BE6797** | 1 | 1 | 0.894 |
| 2026-09-04T20:17:23.667+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ27DS1308** | 1 | 1 | 0.982 |
| 2026-09-06T20:33:07.346+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ2AAA1423** | 1 | 1 | 0.946 |
| 2026-09-04T05:15:28.837+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ31144** | 1 | 2 | 0.654 |
| 2026-09-04T17:07:57.512+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ31T1460** | 1 | 1 | 0.929 |
| 2026-09-04T01:41:27.273+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ31T8156** | 1 | 3 | 0.973 |
| 2026-09-06T20:58:24.719+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32AA9000** | 2 | 2 | 0.950 |
| 2026-09-04T06:46:33.444+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ32AG0028** | 38 | 4 | 0.968 |
| 2026-09-06T14:28:38.574+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32AG0344** | 1 | 1 | 0.929 |
| 2026-09-04T01:13:21.131+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32AG1811** | 1 | 2 | 1.000 |
| 2026-09-06T12:01:56.883+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32AG1849** | 1 | 1 | 0.993 |
| 2026-09-04T03:06:55.460+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32B3783** | 2 | 2 | 0.948 |
| 2026-09-06T12:23:55.827+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32B5149** | 1 | 1 | 0.962 |
| 2026-09-06T13:09:14.252+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32D0107** | 1 | 1 | 0.900 |
| 2026-09-03T20:13:10.252+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K0466** | 1 | 2 | 0.990 |
| 2026-09-06T14:14:11.268+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K5507** | 1 | 1 | 0.967 |
| 2026-09-06T14:14:17.530+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K5587** | 1 | 1 | 0.946 |
| 2026-09-06T20:01:41.336+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K6903** | 1 | 1 | 0.961 |
| 2026-09-04T02:47:34.512+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K8511** | 1 | 2 | 0.953 |
| 2026-09-06T14:22:54.633+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K8758** | 2 | 1 | 0.992 |
| 2026-09-06T13:15:58.200+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32K9785** | 1 | 1 | 0.981 |
| 2026-09-04T18:08:44.924+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32NG2747** | 1 | 1 | 0.952 |
| 2026-09-06T13:01:03.962+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32T0330** | 1 | 1 | 0.888 |
| 2026-09-06T11:18:49.256+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ32T6171** | 1 | 1 | 0.990 |
| 2026-09-04T10:36:02.673+00:00 | cam06 Timbavadi Gate | Junagadh | **GJ33H2219** | 1 | 2 | 0.664 |
| 2026-09-06T10:51:32.031+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ37J4666** | 1 | 1 | 0.951 |
| 2026-09-04T18:31:23.544+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ38B4457** | 1 | 2 | 0.992 |
| 2026-09-02T01:26:22.336+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ38BH5815** | 1 | 2 | 0.995 |
| 2026-09-06T14:26:55.257+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ38BK4597** | 1 | 1 | 0.955 |
| 2026-09-04T09:03:12.296+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ38TA7874** | 1 | 2 | 0.952 |
| 2026-09-06T22:31:36.307+00:00 | cam10 Char Chowk Road 2 | Junagadh | **GJ38TA8097** | 1 | 2 | 0.992 |
| 2026-09-06T10:20:18.902+00:00 | cam30 cam30 | — | **GJ39T3513** | 1 | 1 | 0.928 |
| 2026-09-04T14:50:19.533+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ3GAL6389** | 1 | 1 | 0.929 |
| 2026-09-04T13:17:22.729+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ3RRD4697** | 1 | 1 | 0.913 |
| 2026-09-06T14:14:20.496+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ3ZK5587** | 2 | 2 | 0.945 |
| 2026-09-06T20:46:05.057+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ3ZT7383** | 1 | 1 | 0.856 |
| 2026-09-06T13:03:45.574+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ5K0315** | 2 | 1 | 0.970 |
| 2026-09-04T01:12:02.412+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **GJ810962** | 1 | 2 | 0.816 |
| 2026-09-04T15:05:59.401+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **GJ8R6860** | 1 | 1 | 0.823 |
| 2026-09-06T12:56:57.057+00:00 | cam07 Hero Showroom, Gir Somnath | Gir Somnath | **GJ99988** | 1 | 1 | 0.870 |
| 2026-09-04T01:42:18.485+00:00 | cam12 Tri Mandir Adalaj Tollnaka | Gandhinagar | **MH127339** | 1 | 2 | 0.795 |
| 2026-09-06T09:32:40.305+00:00 | cam10 Char Chowk Road 2 | Junagadh | **MH1TQT1656** | 1 | 1 | 0.877 |
| 2026-09-06T14:10:26.360+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **RJ22GB1677** | 2 | 1 | 0.972 |
| 2026-09-06T12:53:34.283+00:00 | cam21 Dethali Char Rasta | Gujarat (town not confirmed) | **RJ24CB0410** | 1 | 1 | 0.907 |
| 2026-09-04T06:54:54.038+00:00 | cam06 Timbavadi Gate | Junagadh | **RJ27CR3745** | 2 | 5 | 0.998 |

## Vehicles detected, by camera

| Camera | Detections |
|---|---|
| cam01 | 131,828 |
| cam05 | 89,570 |
| cam04 | 83,403 |
| cam10 | 75,799 |
| cam02 | 62,516 |
| cam14 | 47,551 |
| cam11 | 46,263 |
| cam16 | 41,542 |
| cam08 | 36,700 |
| cam13 | 27,769 |
| cam21 | 23,828 |
| cam17 | 17,637 |
| cam25 | 14,183 |
| cam07 | 12,125 |
| cam18 | 10,780 |
| cam12 | 4,693 |
| cam15 | 3,978 |
| cam27 | 3,437 |
| cam03 | 3,117 |
| cam30 | 2,903 |

## By object type

| Type | Count |
|---|---|
| car | 350,535 |
| person | 197,326 |
| truck | 140,783 |
| bus | 35,469 |
| motorcycle | 9,522 |
| bicycle | 8,431 |
| truck_bus | 3,084 |
| van | 2,741 |
| unknown | 1,298 |

## Sample of 40 detections

The full set is in the accompanying CSV.

| Timestamp (UTC) | Camera | Type | Colour | Mark | Quality |
|---|---|---|---|---|---|
| 2026-09-07T11:51:02.542+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:02.542+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:02.216+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:02.216+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:02.216+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:01.706+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:01.706+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:51:01.139+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:51:01.139+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:59.546+00:00 | cam11 | bus | — | — |  |
| 2026-09-07T11:50:59.546+00:00 | cam11 | bus | grey | — | 0.899 |
| 2026-09-07T11:50:59.546+00:00 | cam11 | car | — | — | 0.876 |
| 2026-09-07T11:50:58.871+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:58.871+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:58.735+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:50:58.735+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:50:58.389+00:00 | cam04 | person | — | — |  |
| 2026-09-07T11:50:58.135+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:57.736+00:00 | cam04 | car | white | — | 0.807 |
| 2026-09-07T11:50:57.736+00:00 | cam04 | person | — | — |  |
| 2026-09-07T11:50:57.534+00:00 | cam03 | car | — | — | 0.804 |
| 2026-09-07T11:50:56.208+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:50:56.208+00:00 | cam25 | person | — | — |  |
| 2026-09-07T11:50:55.718+00:00 | cam01 | car | red | — | 0.958 |
| 2026-09-07T11:50:55.493+00:00 | cam03 | person | — | — |  |
| 2026-09-07T11:50:55.315+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:55.315+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:55.315+00:00 | cam10 | person | — | — |  |
| 2026-09-07T11:50:55.271+00:00 | cam05 | person | — | — |  |
| 2026-09-07T11:50:54.955+00:00 | cam11 | car | — | — |  |
| 2026-09-07T11:50:54.955+00:00 | cam11 | car | — | — |  |
| 2026-09-07T11:50:54.955+00:00 | cam11 | truck | — | — |  |
| 2026-09-07T11:50:54.955+00:00 | cam11 | truck | — | — | 0.919 |
| 2026-09-07T11:50:54.955+00:00 | cam11 | car | — | — | 0.871 |
| 2026-09-07T11:50:54.955+00:00 | cam11 | car | — | — | 0.919 |
| 2026-09-07T11:50:54.774+00:00 | cam14 | person | — | — |  |
| 2026-09-07T11:50:54.743+00:00 | cam02 | person | — | — |  |
| 2026-09-07T11:50:54.645+00:00 | cam01 | car | red | — | 0.989 |
| 2026-09-07T11:50:54.645+00:00 | cam01 | car | grey | — | 0.418 |
| 2026-09-07T11:50:54.615+00:00 | cam13 | person | — | — |  |
