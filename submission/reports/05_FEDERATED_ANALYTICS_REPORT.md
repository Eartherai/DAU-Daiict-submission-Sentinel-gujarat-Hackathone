# Federated analytics report

Generated 2026-09-28 10:55:30Z from `sqlite:////Users/earther/Desktop/Gujarat CCTV/saakshya/var/live.db` (opened read-only). Every figure is
counted in SQL across the whole store; nothing is sampled or estimated.

A *source domain* is a camera's provenance, resolved with the platform's
own classifier — GOVERNMENT (the supplied grid), OWN_FEED (participant
submission feeds) and SYNTHETIC_CONTROL (labelled evaluation slots),
never mixed. This is a federation report: the section that matters is
**cross-source vehicles**, the plates seen under more than one domain.

## Estate

| | |
|---|---:|
| Cameras onboarded | 56 |
| Observations | 1,168,232 |
| Distinct registration marks | 378 |
| Watchlist entries | 29 |
| Alerts raised | 142 |
| First observation | 2026-09-02T01:24:47.770108+00:00 |
| Last observation | 2026-09-28T07:23:35.144148+00:00 |

## Cameras per source domain

| Source domain | Cameras |
|---|---:|
| GOVERNMENT | 30 |
| OWN_FEED | 6 |
| SYNTHETIC_CONTROL | 20 |

### By source domain and department

| Source domain | Department | Cameras |
|---|---|---:|
| GOVERNMENT | GSRTC | 1 |
| GOVERNMENT | Home (Police) | 27 |
| GOVERNMENT | Panchayat | 2 |
| OWN_FEED | Own estate | 2 |
| OWN_FEED | Own feed (licensed footage) | 4 |
| SYNTHETIC_CONTROL | Health | 1 |
| SYNTHETIC_CONTROL | Municipal Corporation | 1 |
| SYNTHETIC_CONTROL | SYNTHETIC | 18 |

## Observations per source and object type

| Source domain | bicycle | bus | car | motorcycle | person | truck | truck_bus | unknown | van | Total |
|---|---|---|---|---|---|---|---|---|---|---|
| GOVERNMENT | 13,534 | 49,493 | 530,788 | 59,647 | 309,107 | 184,858 | 5,837 | 1,465 | 5,061 | 1,159,790 |
| OWN_FEED | 12 | 360 | 4,061 | 847 | 1,451 | 1,140 | 429 | 59 | 83 | 8,442 |
| SYNTHETIC_CONTROL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Plates published per source

Distinct marks; *confirmed* had two or more agreeing reads, *leads* had
one. A mark seen under two domains is counted in each — the deduplicated
figure is the distinct-marks line above.

| Source domain | Distinct | Confirmed | Leads |
|---|---:|---:|---:|
| GOVERNMENT | 264 | 149 | 115 |
| OWN_FEED | 114 | 10 | 104 |
| SYNTHETIC_CONTROL | 0 | 0 | 0 |

## Watchlist incidents per source

| Source domain | Alerts |
|---|---:|
| GOVERNMENT | 142 |
| OWN_FEED | 0 |
| SYNTHETIC_CONTROL | 0 |

## Cross-camera and cross-source vehicles

- **0** marks were seen by more than one camera.
- **0** marks were seen under more than one source domain — the vehicles federation actually correlated.

No mark was seen under more than one source domain in this store.

---

*Federation correlates identities across systems; provenance is carried
with every figure so a government count is never inflated by own-feed or
control data.*
