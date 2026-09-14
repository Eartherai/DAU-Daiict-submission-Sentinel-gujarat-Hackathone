# Final submission pack — 6 September 2026

Upload these. Do not upload tokens, `.env`, or stream passwords.

Registration and portal upload are **team-only**. Official last date on
https://sentinel.gujarat.gov.in/ is **15 September 2026** (checked 6 Sep 2026).

## Required by the portal

| Item | File |
|---|---|
| Presentation | `var/demo/SAAKSHYA_deck.pdf` — **54 pages**, 7.3 MB |
| High-level design | `docs/HLD.md` and `var/demo/diagrams/` |
| Own-feed video (2–3 min cap) | `var/demo/own_feed.mp4` (2 min 47 s · 1920×1080) |
| Government-feed video + report | `var/demo/government_feed.mp4` + `var/reports/detections/` |
| Launch walkthrough (live grid, 15 min 03 s, every surface) | `var/demo/SAAKSHYA_launch.mp4` (1920×1080, ~150 MB, Indian-English VO) |
| Designated vehicle on **own-feed** UI (not the live grid) | `var/demo/SAAKSHYA_designated.mp4` — 3 min 13 s; `GJ05AB1234` / `GJ35BV6925` on C-014 + C-021 |
| Drag-to-Drive folder | `var/demo/PORTAL_PACK/` |

## Supporting

| Item | File |
|---|---|
| Measured numbers (quote these) | `docs/MEASURED_RESULTS.md` — generated 2026-09-06T10:54:10Z |
| Evaluation mapping | `docs/HACKATHON_READINESS.md` |
| Demo script | `docs/DEMO_SCRIPT.md` |
| Judge Q&A | `docs/JUDGE_QA.md` |
| Architecture decision | `docs/FINAL_ARCHITECTURE_DECISION.md` |

## What the live store holds (MEASURED, 6 Sep 2026 10:54 UTC)

- 30 government cameras onboarded; 19 on the map; 11 listed, not invented
- 552,889 observations; 145,868 persons (never plated)
- 44 distinct marks; 70 corroborated; 17 leads; **0 cross-camera repeats**
- 8 cameras published a mark; 737 forensic OCR attempts
- 1 open watchlist alert: `GJ38BH5815` stolen_vehicle HIGH on cam21
- Designated rehearsal: `GJ1VV0119` on cam07 (single camera)
- Cross-camera identity is demonstrated on the **synthetic** store (`make serve`): `GJ05AB1234` / `GJ35BV6925`
- Detection report Markdown/JSON: `var/reports/detections/` (SQL summary 6 Sep 10:54 UTC; CSV beside it is an earlier snapshot — do not quote both as one run)

## Launch film chapters (15 min 03 s)

Recorded 7 Sep 2026 against the live government grid. Indian-English voice (Aman). 1920×1080. Boxed stills, map, Gemini on/off.

| t | Surface |
|---|---|
| 0:00 | Title — hybrid Models 1+2+3 |
| 0:35 | Sign-in — case and purpose |
| 1:13 | Overview — open alert, measured store |
| 2:10 | Live wall — 30 government stills, vehicles boxed |
| 3:53 | Estate map — 19 placed, 11 listed |
| 5:15 | Cameras — ANPR UNSUITABLE is yield |
| 6:04 | Find `GJ1VV0119` — one-camera honesty |
| 6:58 | Lookalike `6J1VV0119` + person on cam28 |
| 7:43 | Watchlist alert `GJ38BH5815` |
| 8:26 | Analytics — timebase clusters |
| 9:13 | System — Model 4 rejected on arithmetic |
| 10:06 | Copilot — Gemini on, 16 tools |
| 10:56 | Ask — grounded in tool results |
| 11:37 | Refuse — enhance this still |
| 12:22 | Timebase — cam01+cam21 REFUSED, cam01+cam04 |
| 13:14 | Evidence + audit — hash chain, BSA unsigned |
| 14:11 | Close — what we will not claim |

## Designated-vehicle film on own feed (3 min 13 s)

`var/demo/SAAKSHYA_designated.mp4` — LOCAL SYNTHETIC, not the government grid.
Slate footer: `LOCAL SYNTHETIC · NOT GOVERNMENT DATA`.

| t | Surface |
|---|---|
| 0:00 | Title — own feed, not the live grid |
| 0:29 | Sign-in — `supervisor.demo`, FIR-214/2026 |
| 0:49 | Find `GJ05AB1234` — C-014 and C-021 |
| 1:19 | Route — CONFIRMED, 2 cameras, timebase RESTRICTED |
| 1:45 | Watchlist alerts — `GJ05AB1234` MEDIUM + `GJ15NT6564` HIGH |
| 2:17 | Second mark `GJ35BV6925` — same two cameras |
| 2:40 | Close — live grid still has zero cross-camera repeats |

## Copilot

Gemini is configured as coordinator (16 tools, vision available). On 6 Sep every billed model returned HTTP 429 (prepayment credits depleted), including Flash fallbacks. The copilot **falls back to deterministic rules** from the same tools. Search, trajectory, watchlist, alerts and evidence never call a language model. The launch film shows both: Gemini configured on the Copilot page, then a grounded answer from rules, then a refused "enhance this still".

## Phrases that must not appear in the upload

production ready · legally admissible · tested at 80,000

## Still only the team can do

1. Register and submit on https://sentinel.gujarat.gov.in/ (last date **15 September 2026**).
2. Host the launch film (unlisted YouTube or Drive with viewer access). Paste `var/demo/YOUTUBE_DESCRIPTION.txt`. Follow `docs/PORTAL_UPLOAD.md` in order.
3. Do not put the bearer token or grid password in the upload.
