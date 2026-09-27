# Federated analytics report

Generated 2026-09-27 23:54:23Z from the demonstration store (`var/demo.db`) (opened read-only). Every figure is
counted in SQL across the whole store; nothing is sampled or estimated.

A *source domain* is a camera's provenance, resolved with the platform's
own classifier — GOVERNMENT (the supplied grid), OWN_FEED (participant
submission feeds) and SYNTHETIC_CONTROL (labelled evaluation slots),
never mixed. This is a federation report: the section that matters is
**cross-source vehicles**, the plates seen under more than one domain.

## Estate

| | |
|---|---:|
| Cameras onboarded | 50 |
| Observations | 1,934 |
| Distinct registration marks | 83 |
| Watchlist entries | 2 |
| Alerts raised | 2 |
| First observation | 2026-09-01T08:00:07+00:00 |
| Last observation | 2026-09-18T21:20:53.449906+00:00 |

## Cameras per source domain

| Source domain | Cameras |
|---|---:|
| GOVERNMENT | 30 |
| OWN_FEED | 2 |
| SYNTHETIC_CONTROL | 18 |

### By source domain and department

| Source domain | Department | Cameras |
|---|---|---:|
| GOVERNMENT | Home (Police) | 30 |
| OWN_FEED | Own estate | 2 |
| SYNTHETIC_CONTROL | GSRTC | 1 |
| SYNTHETIC_CONTROL | Health | 1 |
| SYNTHETIC_CONTROL | Home (Police) | 1 |
| SYNTHETIC_CONTROL | Home (Traffic) | 1 |
| SYNTHETIC_CONTROL | Municipal | 1 |
| SYNTHETIC_CONTROL | Panchayat | 1 |
| SYNTHETIC_CONTROL | SYNTHETIC | 12 |

## Observations per source and object type

| Source domain | bus | car | motorcycle | truck | truck_bus | unknown | van | Total |
|---|---|---|---|---|---|---|---|---|
| GOVERNMENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| OWN_FEED | 26 | 1,321 | 0 | 13 | 288 | 4 | 27 | 1,679 |
| SYNTHETIC_CONTROL | 0 | 50 | 1 | 0 | 56 | 141 | 7 | 255 |

## Plates published per source

Distinct marks; *confirmed* had two or more agreeing reads, *leads* had
one. A mark seen under two domains is counted in each — the deduplicated
figure is the distinct-marks line above.

| Source domain | Distinct | Confirmed | Leads |
|---|---:|---:|---:|
| GOVERNMENT | 0 | 0 | 0 |
| OWN_FEED | 0 | 0 | 0 |
| SYNTHETIC_CONTROL | 83 | 44 | 39 |

## Watchlist incidents per source

| Source domain | Alerts |
|---|---:|
| GOVERNMENT | 0 |
| OWN_FEED | 0 |
| SYNTHETIC_CONTROL | 2 |

## Cross-camera and cross-source vehicles

- **14** marks were seen by more than one camera.
- **0** marks were seen under more than one source domain — the vehicles federation actually correlated.

No mark was seen under more than one source domain in this store.

---

*Federation correlates identities across systems; provenance is carried
with every figure so a government count is never inflated by own-feed or
control data.*
