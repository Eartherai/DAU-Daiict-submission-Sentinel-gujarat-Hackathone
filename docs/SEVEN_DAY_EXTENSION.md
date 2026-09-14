# Seven extra days — what is actually worth doing

Official last date on https://sentinel.gujarat.gov.in/ is **15 September 2026**.
On-site event **22–23 September**. Today is 6 September. Do not wait until the
15th to press Submit.

The pack in `var/demo/PORTAL_PACK/` is already a complete submission. Extra
days should buy **jury-visible evidence**, not a rewrite.

## Do not spend the week on

- Face recognition. Deliberate abstention. The portal lists FRS as an example,
  not a mandate.
- Claiming a live multi-camera plate trail. The live store still has **0**
  exact cross-camera repeats (checked 6 Sep evening: 49 marks, 8 cameras, 0
  repeats). Geometry, not a missing feature.
- Opening a second 30-camera RTSP copy while ingest is running.
- Hosting the live government wall on the public internet.
- Inventing rupee costs, GIS for the eleven unlocated cameras, or
  “tested at 80,000”.

## Ranked by jury impact

### 1 · Submit the pack (A7) — team, this week, not day 15

Register at https://sentinel.gujarat.gov.in/register, upload
`var/demo/PORTAL_PACK/` (or the zip beside it), host the 15-minute launch film
unlisted. Target **11–12 September** so a portal glitch still leaves three days.

If the form allows a later replacement, submit a complete set now and replace
the detection report / deck numbers after a daylight ingest run.

### 2 · Keep the 30-camera ingest running (A1, expected output 1–3)

This is the only path that could change the live story. If **any** mark appears
on a second camera, that is the designated-vehicle clip the evaluation asks
for. Recheck daily:

```bash
cd saakshya
make daily-live-score
```

That command is MEASURED from `var/live.db`. Prefer the ingest log `streaming=N/30` over Overview STREAMING until ingest is next started (session-state health persist). If `cross-camera plates` becomes 1, stop other work and film that plate on the live UI.

### 3 · Daylight ANPR pass (A5)

Plate yield on this grid is geometry and light. A morning or afternoon window
on cam21 / cam07 / cam06 may add marks. It will not make cam04 (46 px plates)
readable. After a daylight run: regenerate `docs/MEASURED_RESULTS.md` and
`var/reports/detections/` with `--summary-only`, then the deck.

### 4 · Catalogue session (A3 map honesty)

Eleven cameras are listed, not invented. A signed-in catalogue session would
place them with `CATALOGUE` basis. Needs the team’s grid login, never committed.

### 5 · Gemini credits (bonus copilot)

The launch film already shows Gemini configured and rules fallback on HTTP 429.
Prepaid credits would let the coordinator answer from Gemini instead of rules.
The mandatory chain must stay LLM-free.

### 6 · Optional hosted URL / GitHub (A7 optional)

Viewer-safe **demo** store (`make serve` on demo.db), not the live government
grid. Tokens minted to `/tmp`, rotated, never in the repo. GitHub: no `.env`,
no `var/live.db`, no stream passwords.

### 7 · On-site PoC (A6) — `docs/POC_DAY.md`

22–23 September at i-Hub. Same machine, same ingest, fresh token, designated
rehearsal `GJ1VV0119`, alert `GJ38BH5815`, own-feed plates if the live grid
still has no repeat.

## Already demonstrated — do not redo unless the store changes

| Evaluation | Evidence |
|---|---|
| A1 live onboard | 30/30 ingest stills, launch film 2:00 |
| A2 deck | 54-slide PPTX + PDF |
| A3 HLD | `docs/HLD.md` + diagrams, hybrid 1+2+3 |
| A4 own feed | `own_feed.mp4` 2:47 (1080p25) and UI 2:58 |
| A4 government feed | `government_feed.mp4` + launch 15:03 |
| A5 analytics | 69 live marks, persons, dwell as long-stay, no FRS |
| Expected 1–3 live | `GJ1VV0119` one camera; `GJ38BH5815` alert |
| Expected 1–3 own feed | `GJ05AB1234` / `GJ35BV6925` on two cameras |

## If only two things get done

1. **Submit.**
2. **Leave ingest up** and watch for a second-camera plate.
