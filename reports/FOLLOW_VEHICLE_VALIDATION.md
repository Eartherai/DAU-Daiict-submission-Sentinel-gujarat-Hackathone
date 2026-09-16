# Follow Vehicle validation

The Follow Vehicle workflow is implemented at `GET /follow/{plate}` (with the
legacy-compatible `/follow-vehicle/{plate}` alias).

## Verified behavior

- Starts from an exact normalized plate search.
- Ranks later observations on other cameras.
- Exposes plate, colour, class, quality, temporal, and geographic terms.
- Applies elapsed-time and implied-speed constraints.
- Returns route, timeline, candidate, and evidence references.
- Emits `ROUTE_CONTRADICTION` instead of connecting physically impossible
  sightings.
- Includes distance, elapsed time, and implied speed for rejected transitions.
- Preserves authentication, jurisdiction scope, purpose binding, and audit
  logging through the existing investigation service.

Focused synthetic validation passed:

- same-plate subsequent-camera ranking;
- timeline and evidence references;
- impossible far-camera transition rejection;
- explicit contradiction code and speed calculation.

Government-feed limitation remains explicit: current government evidence has no
exact cross-camera repeat, so this workflow is demonstrated on own/demo data
when a complete route is required.
