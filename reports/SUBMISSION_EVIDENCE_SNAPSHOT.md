# Submission evidence snapshot

MEASURED from the main reference `var/live.db`, opened read-only on 28 September
2026. This is a snapshot of stored observations and representative watchlist
entries, not a new live test or an accusation about a real vehicle.

## Canonical demonstration roles

| Role | Plate | Camera/read count | Label |
|---|---|---|---|
| Team-chosen government stand-in | GJ11S7924 | cam06: 57 (52 snapshot + 5 session) | SINGLE-CAMERA government evidence; not organiser-issued |
| Government watchlist example | GJ38BH5815 | cam21: 1 | evaluation_designated, HIGH, ACTIVE; alert HIGH OPEN |
| Historical government rehearsal | GJ1VV0119 | cam07: 2 | investigation_target; not the designated vehicle for submission |
| Synthetic route | GJ18JX7786 | C-014: 2, then C-021: 5 | SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage; `var/demo.db` |

Counts are stored published observations, not individual OCR attempts.
`GJ11S7924` was chosen by the team from its cam06 reads on 20 Sep; the
watchlist entry was created at 05:46 IST after the first read at 05:43 IST.
Its “Gujarat Police (representative)” authority text does not make it an
organiser-issued number. The five additional reads on 28 Sep are before the
filmed take. The synthetic route uses rendered clips from
`tools/sandbox/make_media.py`, not the licensed Mumbai own-feed footage;
there is no real multi-camera evidence in this submission.

## Active government-store watchlist

Source: `var/live.db`, `watchlist` joined to `observations` by plate.
Entries are representative test data; category names are not allegations.

| Plate | Category | Priority | Cameras and stored reads |
|---|---|---|---|
| GJ01RS9114 | evaluation_designated | HIGH | cam06: 16 |
| GJ03JL6883 | evaluation_designated | HIGH | cam06: 1 |
| GJ07XZ4409 | stolen_vehicle | HIGH | No stored reads |
| GJ11BR0928 | evaluation_designated | HIGH | cam06: 27 |
| GJ11BR1008 | evaluation_designated | HIGH | cam06: 3 |
| GJ11C0370 | evaluation_designated | HIGH | cam06: 1 |
| GJ11CH8698 | evaluation_designated | HIGH | cam06: 1 |
| GJ11DB2886 | evaluation_designated | HIGH | cam06: 20 |
| GJ11DB9063 | evaluation_designated | HIGH | cam06: 2 |
| GJ11S7924 | evaluation_designated | HIGH | cam06: 57 |
| GJ11S9258 | evaluation_designated | HIGH | cam06: 27 |
| GJ11YY6198 | evaluation_designated | HIGH | cam06: 3 |
| GJ18899 | evaluation_designated | HIGH | cam06: 1 |
| GJ18X6705 | evaluation_designated | HIGH | cam06: 72 |
| GJ18Z8826 | evaluation_designated | HIGH | cam06: 3 |
| GJ18ZT1782 | evaluation_designated | HIGH | cam06: 11 |
| GJ1VV0119 | investigation_target | HIGH | cam07: 2 |
| GJ21T4831 | evaluation_designated | HIGH | cam20: 1 |
| GJ25W7686 | evaluation_designated | HIGH | cam06: 4 |
| GJ38BH5815 | evaluation_designated | HIGH | cam21: 1 |

Read-only `watchlist GROUP BY status, category`: 18 ACTIVE
`evaluation_designated`, 1 ACTIVE `investigation_target`, 1 ACTIVE
representative `stolen_vehicle` (`GJ07XZ4409`), and 9 REVOKED `stolen_vehicle`.

## Government analytics and evidence limits

Read-only SQL on 28 September, restricted to cam01–cam30 in `var/live.db`
and the 24 Sep snapshot cutoff `t_norm_us <= 1790246409848994`:
**1,155,325 observations**, spanning 2 September 06:54 to 24 September 16:10
2026 IST (`t_norm_us`). Stored object labels are detector output, not audited
accuracy or unique-person/vehicle counts. Historical coverage across a date
range is not simultaneous deep-inference coverage.

| Object label | Observations | Cameras with that label |
|---|---:|---:|
| car | 529,966 | 29 |
| person | 307,290 | 30 |
| truck | 184,600 | 29 |
| motorcycle | 58,423 | 25 |
| bus | 49,403 | 28 |
| bicycle | 13,312 | 25 |
| truck_bus | 5,819 | 27 |
| van | 5,049 | 27 |
| unknown | 1,463 | 22 |

Government ANPR in the **24 Sep snapshot**: **901 read rows, 178 distinct
plates, 9 cameras**. The delivered CSV and complete store instead contain
**1,101 reads, 264 plates, 9 cameras**, including the 28 Sep session below.
Of the snapshot rows, **474 read
rows represent 97 distinct plates** with at least two agreeing frames
(`src/saakshya/reports/anpr.py::CONFIRM_VOTES = 2`). Confirmation by repeated
OCR agreement is not ground-truth identity verification. No plate occurs on
two government cameras; government observations have **zero non-null
appearance embeddings**, so no appearance re-identification ran on those rows.

Restricted-zone reporting uses the administrator's demonstration rule on
cam12, “No pedestrians on the toll-lane carriageway”, for the person class
(`zone_rules`, `api/routes_zones.py`). It is a demonstration policy, not a
claim that each entry represents an unlawful intrusion.

**Older evidence defect:** the worker previously sealed the frame in hand
when a track closed rather than the frame that produced the best plate read.
A sealed still can therefore show a different vehicle even if its hash verifies.
Since the worker session beginning **28 Sep 2026 11:15 IST** (commit `672a2a0`), `analytics/worker.py` seals `pipe.evidence_frame(o)`, the
frame of the track's best plate read (`tests/unit/test_evidence_read_frame.py`).
It does not repair old stills. Historical trace
reports and films need visual/source verification before their images are
presented as evidence of the named plate.

## Reproduce without opening streams

Open each store with `sqlite3.connect("file:PATH?mode=ro&immutable=1", uri=True)`. Only
the following non-secret columns were selected; token/user tables were not read.

```sql
SELECT object_type, COUNT(*), COUNT(DISTINCT camera_id) FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]' AND t_norm_us <= 1790246409848994
GROUP BY object_type;
SELECT COUNT(*), MIN(t_norm_us), MAX(t_norm_us) FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]' AND t_norm_us <= 1790246409848994;
SELECT COUNT(*), COUNT(DISTINCT plate), SUM(plate_votes >= 2),
       COUNT(DISTINCT CASE WHEN plate_votes >= 2 THEN plate END),
       COUNT(DISTINCT camera_id) FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]' AND plate IS NOT NULL AND plate <> '';
SELECT plate FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]' AND plate IS NOT NULL AND plate <> ''
GROUP BY plate HAVING COUNT(DISTINCT camera_id) > 1;
SELECT COUNT(*) FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]' AND embedding IS NOT NULL;
SELECT plate, category, priority FROM watchlist WHERE status='ACTIVE' ORDER BY plate;
SELECT camera_id, COUNT(*) FROM observations WHERE plate = ? GROUP BY camera_id;
SELECT plate, category, priority, status, COUNT(*) FROM alerts
WHERE plate IN (?, ?, ?) GROUP BY plate, category, priority, status;
```

For snapshot ANPR totals, add `t_norm_us <= 1790246409848994` to the
plate-count query. Apply the per-plate query to `var/demo.db` for the synthetic
plate. Camera source domains can be verified with:

```sql
SELECT camera_id, source_domain FROM cameras WHERE camera_id IN ('C-014', 'C-021');
SELECT source_domain, COUNT(*) FROM cameras GROUP BY source_domain;
SELECT status, category, COUNT(*) FROM watchlist GROUP BY status, category;
```

The live registry has 56 rows: 30 GOVERNMENT, 6 OWN_FEED, 18
SYNTHETIC_CONTROL and 2 with no explicit stored domain. The evaluation
baseline remains 50; operator-added records are retained.

## 28 Sep 2026 live recording session (MEASURED)

Between 11:15 and 12:53 IST the four deep-inference slots (cam06, cam12, cam10,
cam08) wrote 4,465 government observations after the snapshot: cam06 2,480,
cam10 1,050, cam08 708, cam12 227. Among them are 200 plate reads, 124 distinct
plates, all on cam06, by the current recogniser (`ocr: awiros-anpr-ocr` in the
row's `model_versions`; the 901 snapshot reads carry no `ocr` key: earlier
recogniser). The appended CSV `ocr_model` column is `model_versions.ocr`
when present and `earlier` otherwise. The film `04_government_feed.mp4` (5 m 40 s) was recorded in this
session at 12:41–12:47 IST; only 21 reads fall within the take
(12:40:59–12:47:22 IST, counted in the CSV). Its CSV holds every government read: 901 + 200 = 1,101 (264 distinct
plates, 9 cameras). Query: the snapshot queries above with
`t_norm_us > 1790246409848994` (24 Sep 16:10:09 IST).

During the session the shared sandbox delivered 6–13 of 30 government cameras
as advancing video at once (MEASURED DURING THIS TEST WINDOW, recorder samples in
`var/demo/gov_take7/beats.json`); 18 cameras advanced at some point in one
five-minute preflight. The organisers state there is no fixed participant-facing
session limit and that availability varies with shared load; these counts are
measurements, not a limit.
