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

## Reproduce without opening streams

Open each store with `sqlite3.connect("file:PATH?mode=ro", uri=True)`. Only
the following non-secret columns were selected; token/user tables were not read.

```sql
SELECT plate, category, priority FROM watchlist WHERE status='ACTIVE' ORDER BY plate;
SELECT camera_id, COUNT(*) FROM observations WHERE plate = ? GROUP BY camera_id;
SELECT plate, category, priority, status, COUNT(*) FROM alerts
WHERE plate IN (?, ?, ?) GROUP BY plate, category, priority, status;
```

Apply the observation query to `var/demo.db` for the own-feed plate.
The government film is being re-recorded; its duration and CSV statistics must
be stamped from the final files at pack build. These stored-read counts should
be rechecked if the store changes.
