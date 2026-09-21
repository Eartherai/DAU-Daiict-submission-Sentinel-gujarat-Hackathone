# FULL CHAIN, LIVE — cam06 TIMBAVADI GATE

2026-09-20 08:46:27 IST. Every hop below ran against live Sentinel video during
this session. No historical rows, no simulation, no replay.

## The chain

```
LIVE GOVERNMENT CAMERA   cam06 · Timbavadi Gate · Junagadh
                         RTSP direct · hevc 1920x1080 · daylight (luma 96.3)
        |
REAL DETECTION           object_type truck · colour grey
        |                observation_quality 0.987
REAL TRACK               TR01M2YD19SSJNXQWC07AK1KKXN7
        |
REAL PLATE READ          GJ11DB9063
        |                OCR confidence 0.975 · votes 2 (corroborated across frames)
        |
WATCHLIST                WL01M2YD1D45ENJW3PRW1569B7Q2
        |                category stolen_vehicle · priority HIGH · status ACTIVE
        |                source REPRESENTATIVE (permitted by the test case)
        |
REAL-TIME ALERT          AL01M2YD1DDHGSB6AB94VVGTVHGZ
        |                confidence 0.979 · source_quality 0.987 · status OPEN
        |                recommended_action "VERIFY and notify the district control room"
        |                raised from observation OB01M2YD1DDGMJMW38GEZQ1XDZQ7
        |
OPERATOR SURFACE         GET /alerts returns it, HIGH, OPEN
        |
GIS                      21.5108, 70.4598 · Junagadh · located=true
        |                21 government cameras carry a map location
        |
AUDIT                    audit_log: actor supervisor.live · action watchlist_add
                         · target GJ11DB9063
```

## Plates read live in the same run

```
GJ18Z8826   conf 0.992   votes 10   <- strongly corroborated
GJ11DB9063  conf 0.979   votes  2   <- raised the alert
GJ25W7686   conf 0.950   votes  4
GJ03JL6883  conf 0.945   votes  1
GJ11CH8698  conf 0.930   votes  4
GJ11C0370   conf 0.924   votes  1
GJ18899     conf 0.639   votes  2
```

Session total: **20 distinct plates** read live, all valid Indian formats, the
majority `GJ11` — the Junagadh RTO code — from a camera in Junagadh.

## Why the alert had not fired before

`watch.match(observation)` runs at the instant an observation is processed. An
entry added 2.7-12.5s *after* a read has already missed that vehicle, and at a
through-road the vehicle is gone. Closing the loop to sub-second means a plate
is on the watchlist before the next observation of the same track arrives, and
the alert is then raised by the running pipeline, not by a script.

The ordering matters operationally too: this is the real workflow. A vehicle is
listed, and the system alerts on sightings *after* that moment.

## Evidence, sealed at the moment of the alert

```
EVIDENCE        EZ01M2YGSE0NZ3PP79HQHKE53DJW
                frame   var/evidence/EZ01M2YGSE0NZ3PP79HQHKE53DJW.png (885,121 bytes)
                sha256  e70ddaad5cfa85e942c37c237979eb5f4c38a32d...  VERIFIED against disk
                chain   prev 453030e5... -> entry dad11050...
                capture "automated capture from live RTSP; no manual editing"
                device  ai-worker:cam06
                BSA S63 DRAFT_PENDING_SIGNATURE
observation.evidence_ref -> EZ01M2YGSE0NZ3PP79HQHKE53DJW   (back-link resolves)
```

`GET /evidence/chain/verify` returns `verified: true`.

### The ordering bug this exposed

Sealing at match time wrote the manifest against an observation that did not
exist yet: the worker batches observations and flushes them up to 0.8s later,
so the back-link `UPDATE` matched no rows and the subsequent `INSERT` stored
`evidence_ref = NULL`. The frame was sealed and the sighting still reported
"no evidence available" — which is exactly the condition that makes an
investigator seal a second manifest for the same frame.

Alerting observations now hold their frame until the flush succeeds and are
sealed immediately afterwards, so the manifest and the back-link are written
against a row that exists.

## A claim I made and had to withdraw

I reported the registry's `anpr: UNSUITABLE` on cam06 as a defect, on the
grounds that cam06 is the one camera that reads plates. Re-grading it from this
session's live observations shows the grade is correct:

```
DAY        3317 samples   62 plate reads   yield 3.3%   UNSUITABLE
NIGHT      1281 samples   11 plate reads   yield 1.6%   UNSUITABLE
LOW_LIGHT   318 samples    1 plate read    yield 0.3%   UNSUITABLE
```

The grade measures **yield**, not capability, and the grader's own reason text
says so: *"A mark that did appear is still a mark — the grade is about yield,
not existence."* A 3.3% yield means 97% of vehicles pass unread. UNSUITABLE is
the honest grade for systematic ANPR even though the camera demonstrably reads
plates when a vehicle presents one well.

What was genuinely stale was the stored row: a single LOW_LIGHT assessment built
on one plate read. All four bands are now graded from live observations for
every camera (200 assessments persisted). cam06's vehicle re-ID grade also moved
DEGRADED -> GOOD in the DAY band, which is what the attribute-based cross-camera
correlation depends on.

Estate-wide in the DAY band: 29 cameras UNSUITABLE for ANPR, 21 UNKNOWN. Six
cameras produced any plate read at all; cam06 leads at 3.3% yield, the next is
cam07 at 0.5%.

## The three ANPR gates, measured

Suitability cannot be read off a spec sheet. Three independent gates:

| gate | test | result across the estate |
|---|---|---|
| geometry | does a plate crop appear at all | ~2 cameras in 5; cam14+cam16 saw 2,781 vehicles and produced none |
| lighting | daylight | cam02 at night: OCR mean 0.51, no valid format |
| legibility | OCR confidence >= 0.82 | cam15 at 177px in daylight still read nothing: OCR 0.43-0.55, same vehicle read as `CMC046` then `TNT046` then `KJC026` |

cam06 passes all three: a gate where vehicles slow and face the camera.
cam15 has larger crops and full daylight and fails the third.

**Plate pixel width is necessary but not sufficient.** At 80,000 cameras,
ANPR readiness has to be measured per camera from the video.
