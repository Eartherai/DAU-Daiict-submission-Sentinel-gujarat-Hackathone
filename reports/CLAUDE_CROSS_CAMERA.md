# CROSS-CAMERA CORRELATION ON LIVE OBSERVATIONS

2026-09-20. Live Sentinel video only. Ranked candidates for review — not
identity claims.

## Why plates cannot carry this

Measured across three clusters:

| camera | observations | plate crops | verdict |
|---|---|---|---|
| cam06 Timbavadi Gate | — | 9 @136px | **SUITABLE** (13 plates read) |
| cam02 Janpath | — | @167px | SUITABLE (night: no confident read) |
| cam13 CN Vidhyalaya | 2512 | 6 @158px | SUITABLE |
| cam15 Suvidha Park | 1087 | 9 @183px | SUITABLE |
| cam04 Paldi Circle | — | @49px | ANPR_UNSUITABLE |
| cam12 Tri Mandir Tollnaka | — | @43px | ANPR_UNSUITABLE |
| cam14 Delight RLVD | 1353 | **0** | ANPR_UNSUITABLE |
| cam16 Visat P2 | 1428 | **0** | ANPR_UNSUITABLE |
| cam08/09/10/11 Junagadh | 188 | **0** | ANPR_UNSUITABLE |

**cam14 and cam16 saw 2,781 vehicles between them and produced not one plate
crop.** Roughly two cameras in five can do ANPR at all. A statewide design that
makes movement reconstruction depend on plates therefore forfeits most of the
estate. This is the path for the other three in five.

Lighting is the second gate. cam02 at night gave correctly-sized crops and OCR
still returned `'CC4044'` 0.48, `'L17'` 0.63, `'____1'` 0.52 — mean 0.51, no
valid format. Measuring mean luma and moving to daylight cameras turned 0 reads
into 13.

### The third gate, and why plate pixel width is the wrong metric

cam15 in full daylight (luma 98.7) with **larger** crops than cam06 — 177px vs
136px — read **zero** plates across two windows and 4,266 observations. So it is
neither size nor light. Raw OCR, before any gate:

```
cam15  det 0.67-0.76 (detector is confident it found a plate)
       OCR 0.43-0.55, mean 0.48, none >= 0.82
       '_C_12'  'CMC046'  'TNT046'  'KJC026'  'KMT132'  'AJ188A'  'WJT111'

cam06  OCR 0.81-0.97, valid Gujarat formats, 13 plates read
```

The same vehicle reads differently in consecutive frames — `CMC046` then
`TNT046` then `KJC026`. That is not a threshold problem; the glyphs are not
resolvable. A plate seen obliquely, or crossing frame fast, has a wide bounding
box whose characters are compressed or smeared.

**Plate pixel width is necessary but not sufficient.** ANPR suitability must be
graded on *OCR confidence*, not crop geometry. cam06 is a gate where vehicles
slow and approach head-on; cam15 is a junction with fast crossing traffic. Same
resolution, same daylight, opposite outcomes.

This matters at 80,000 cameras: suitability cannot be surveyed from a spec
sheet or a resolution field. It has to be measured per camera, from the video.

## What this does instead

`tools/verify/cross_camera_attributes.py`. Scores every pair of attributed
observations across two cameras on:

```
colour agreement    colour_agreement()   1.0 exact, 0.5 an expected confusion
size agreement      size_agreement()     1.0 exact, 0.5 adjacent class
travel plausibility 1.0 when the gap fits a 15-90 km/h crossing of the real
                    distance between the two cameras, tapering outside
quality             the lower of the two observation qualities
distinctiveness     how rare that description is in this window
```

A candidate is offered only when colour **and** size agree at all; a pair
matched on timing alone is not evidence.

### Distinctiveness is what makes it usable

The first run scored 691,580 candidates and the top fifteen were almost all
grey car / grey car at 0.996. That number is a lie: 1,677 grey cars were seen
in the same window, so the match carries almost no information. Showing it to
an officer at 0.996 would actively mislead.

The score is now damped by inverse frequency of the description, and every row
states how many vehicles share it. Result on the same data:

```
 score colour       type                   gap   km/h  shared  route
 0.592 blue/blue    motorcycle/motorcycle  161s  32.3       3  cam13->cam15
 0.550 orange/orange truck_bus/truck_bus   131s  39.7       4  cam15->cam13
 0.517 black/black  truck_bus/truck_bus    253s  20.5       5  cam15->cam13
 0.501 grey/grey    bus/bus                 59s  88.3       6  cam13->cam15
```

Grey cars are gone from the top. Scores are honest — nothing claims certainty
it does not have.

### GIS route, top candidate

```
CN Vidhyalaya (cam13)  23.02340, 72.55410  at 07:29:52
     | 1.44 km, 161s, implied 32.3 km/h
Suvidha Park  (cam15)  23.01060, 72.55630  at 07:32:33
matched on: colour blue (agreement 1.0), size motorcycle (agreement 1.0)
3 vehicles in this window share that description (distinctiveness 0.477)
CANDIDATE for investigator review — appearance correlation, not identity.
```

Real coordinates from the registry, real timestamps from live observations, a
plausible road speed over the true distance between two cameras.

## Why not an embedding

The repository had already measured a DINOv2 appearance embedding on this
government feed:

```
same vehicle        mean 0.830, p05 0.640
different vehicles  mean 0.576, p95 0.791
best balanced accuracy 0.831 at threshold 0.74
```

The distributions overlap, so an embedding can rank candidates but cannot
assert that two sightings are one vehicle. That measured conclusion governs
here; `embedding` is populated on 0 of 11,742 observations by design, not by
omission. Everything above is explainable to an officer who may disagree with a
specific claim — "blue, motorcycle-sized, 3 others like it" is arguable in a
way a cosine distance is not.

## Output

`var/reports/cross_camera_attributes.json` — cameras, coordinates, every
candidate with its component scores and both observation ids.

## Honest limits

- Appearance correlation ranks; it does not identify. Nothing here says two sightings are the same vehicle.
- Colour is recovered on 44% of observations; the rest carry no appearance weight.
- Only two cameras were correlated, because only two ANPR-suitable Ahmedabad cameras were attributed in the window. The method takes any number.
- A cross-camera **plate** match remains undemonstrated: it needs two cameras simultaneously plate-capable, daylit, and in one city. At this loop position the lit-and-capable pair (cam06 Junagadh, cam02 Gandhinagar) are ~300 km apart.
