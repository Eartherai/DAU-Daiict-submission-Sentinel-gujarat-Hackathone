# Submission evidence snapshot

MEASURED from the main reference `var/live.db`, opened read-only on 28 September
2026. This is a snapshot of stored observations and representative watchlist
entries, not a new live test or an accusation about a real vehicle.

## Canonical demonstration roles

| Role | Plate | Camera/read count | Label |
|---|---|---|---|
| Government designated vehicle | GJ11S7924 | cam06: 52 | SINGLE-CAMERA government evidence |
| Government watchlist example | GJ38BH5815 | cam21: 1 | evaluation_designated, HIGH, ACTIVE; alert HIGH OPEN |
| Historical government rehearsal | GJ1VV0119 | cam07: 2 | investigation_target; not the designated vehicle for submission |
| Own-feed trace | GJ18JX7786 | C-014: 2, then C-021: 5 | CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION; `var/demo.db` |

Counts are stored published observations, not individual OCR attempts.

## Active government-store watchlist

Source: `var/live.db`, `watchlist` joined to `observations` by plate.
Entries are representative test data; category names are not allegations.

| Plate | Category | Priority | Cameras and stored reads |
|---|---|---|---|
| GJ01RS9114 | evaluation_designated | HIGH | cam06: 14 |
| GJ03JL6883 | evaluation_designated | HIGH | cam06: 1 |
| GJ07XZ4409 | stolen_vehicle | HIGH | No stored reads |
| GJ11BR0928 | evaluation_designated | HIGH | cam06: 23 |
| GJ11BR1008 | evaluation_designated | HIGH | cam06: 3 |
| GJ11C0370 | evaluation_designated | HIGH | cam06: 1 |
| GJ11CH8698 | evaluation_designated | HIGH | cam06: 1 |
| GJ11DB2886 | evaluation_designated | HIGH | cam06: 19 |
| GJ11DB9063 | evaluation_designated | HIGH | cam06: 2 |
| GJ11S7924 | evaluation_designated | HIGH | cam06: 52 |
| GJ11S9258 | evaluation_designated | HIGH | cam06: 24 |
| GJ11YY6198 | evaluation_designated | HIGH | cam06: 3 |
| GJ18899 | evaluation_designated | HIGH | cam06: 1 |
| GJ18X6705 | evaluation_designated | HIGH | cam06: 66 |
| GJ18Z8826 | evaluation_designated | HIGH | cam06: 2 |
| GJ18ZT1782 | evaluation_designated | HIGH | cam06: 11 |
| GJ1VV0119 | investigation_target | HIGH | cam07: 2 |
| GJ21T4831 | evaluation_designated | HIGH | cam20: 1 |
| GJ25W7686 | evaluation_designated | HIGH | cam06: 4 |
| GJ38BH5815 | evaluation_designated | HIGH | cam21: 1 |

## Government analytics and evidence limits

Read-only SQL on 28 September, restricted to cam01–cam30 in `var/live.db`:
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

Government ANPR: **901 read rows, 178 distinct plates, 9 cameras** in both
the store and `var/demo/government_feed_anpr_report.csv`. Of these, **474 read
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
Since commit `672a2a0`, `analytics/worker.py` seals `pipe.evidence_frame(o)`, the
frame of the track's best plate read (`tests/unit/test_evidence_read_frame.py`).
It does not repair old stills. Historical trace
reports and films need visual/source verification before their images are
presented as evidence of the named plate.

## Reproduce without opening streams

Open each store with `sqlite3.connect("file:PATH?mode=ro", uri=True)`. Only
the following non-secret columns were selected; token/user tables were not read.

```sql
SELECT object_type, COUNT(*), COUNT(DISTINCT camera_id) FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]' GROUP BY object_type;
SELECT COUNT(*), MIN(t_norm_us), MAX(t_norm_us) FROM observations
WHERE camera_id GLOB 'cam[0-9][0-9]';
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

Apply the observation query to `var/demo.db` for the own-feed plate.
The government film is being re-recorded; its duration and CSV statistics must
be stamped from the final files at pack build. These stored-read counts should
be rechecked if the store changes.
