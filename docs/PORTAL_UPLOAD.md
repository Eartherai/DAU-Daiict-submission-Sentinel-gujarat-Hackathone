# Portal upload — do this now

Registration and submission close **15 September 2026** (official countdown
on https://sentinel.gujarat.gov.in/, checked 6 Sep 2026). Shortlisting that
evening. On-site event **22–23 September 2026**.

Portal: https://sentinel.gujarat.gov.in/register
Sign in: https://sentinel.gujarat.gov.in/login
Helpdesk: sentinel.hackathon@gujarat.gov.in · +91 95370 89982

Nothing in this repository can press Submit. This page is the pack, in order.

Do **not** upload tokens, `.env`, stream passwords, or `/tmp/saakshya-*-token.raw`.

Minute plan if you start at T=0:

| Clock | Action |
|---|---|
| 0:00 | Create a Drive folder `SAAKSHYA — GPIC 2026` (Anyone with the link can view). |
| 0:05 | Drop in `var/demo/PORTAL_PACK/`. Start YouTube upload of `06_SAAKSHYA_launch.mp4`. |
| 0:10 | Open https://sentinel.gujarat.gov.in/register (or Sign In). |
| 0:15 | Paste from `PORTAL_PACK/PASTE.txt`. |
| 0:25 | Attach PPTX **and** PDF, HLD, own-feed 2:47 and/or 2:58 UI film, government-feed + reports. |
| 0:35 | Paste YouTube/Drive links. |
| 0:40 | Read once. Forbidden: production ready · legally admissible · tested at 80,000. |
| 0:45 | Submit. |

## 1 · Host the long film first (while you fill the form)

Upload `var/demo/SAAKSHYA_launch.mp4` as **unlisted** YouTube, or Drive/OneDrive
with **anyone with the link can view**.

- Duration: **15 min 03 s** · 1920×1080 · ~150 MB
  (real tour of the live government workspace — not freeze-padded)
- Title: `SAAKSHYA — Gujarat Police Innovation Challenge 2026 — live government grid`
- Paste the description from `var/demo/YOUTUBE_DESCRIPTION.txt`

If YouTube rejects the size, put the same file on Drive and paste that link.
The two required short films can go in the same Drive folder.

Optional second host (own-feed UI, **not** the live grid):
`var/demo/SAAKSHYA_designated.mp4` — **3 min 13 s**, 1920×1080.
Designated vehicle on the local corpus (`GJ05AB1234` / `GJ35BV6925` on C-014
and C-021, watchlist alerts). Title:
`SAAKSHYA — designated vehicle on own-feed corpus (not government grid)`.
Description: `var/demo/DESIGNATED_YOUTUBE.txt`.

A ready-to-upload copy of every file is in `var/demo/PORTAL_PACK/`. Drag that
folder to Drive.

## 2 · Files to attach on the portal

Paths are relative to `saakshya/`.

| Portal field | File | Notes |
|---|---|---|
| Presentation (PPT/PDF) | `var/demo/SAAKSHYA_deck.pptx` **and** `.pdf` | **54 slides**, 16:9 full-bleed. Upload PPTX if the form wants PowerPoint. |
| High-level design | `docs/HLD.md` **and** `var/demo/diagrams/HLD_diagrams.pdf` | Also the four PNGs in `var/demo/diagrams/`. |
| Own-feed video (2–3 min **hard cap**) | `var/demo/own_feed.mp4` **or** `var/demo/SAAKSHYA_designated_2m58.mp4` | Overlay 2:47 · 1080p25 with plates on frames; **or** real-UI screen recording 2:58 (FAQ 31). |
| Own-feed report | `var/demo/own_feed.csv` and `var/demo/own_feed.json` | Rows drawn on that video, not the live store. |
| Government-feed video | `var/demo/government_feed.mp4` | **1 min 37 s.** Provenance stamped. Zero plates — geometry, not a failed reader. |
| Government-feed report (that video) | `var/demo/government_feed.csv` and `var/demo/government_feed.json` | Do not mix with the live-store report. |
| Live-store detection report | `var/reports/detections/detections.md` + `summary.json` | SQL as of 6 Sep 2026 10:54 UTC. **Do not quote `detections.csv` as the same run.** |
| Launch walkthrough (host as the YouTube/Drive link) | `var/demo/SAAKSHYA_launch.mp4` | Live grid, every surface. |
| Optional extra: designated vehicle on **our** feed | `var/demo/SAAKSHYA_designated.mp4` | **3 min 13 s.** Demo store UI. Slate says LOCAL SYNTHETIC. |

### Drive folder layout (copy as-is)

```
SAAKSHYA — GPIC 2026/
  01_SAAKSHYA_deck.pdf
  02_HLD.md
  02_HLD_diagrams.pdf
  03_own_feed.mp4
  03_own_feed.csv
  03_own_feed.json
  04_government_feed.mp4
  04_government_feed.csv
  04_government_feed.json
  05_detections.md
  05_detections_summary.json
  06_SAAKSHYA_launch.mp4
  07_SAAKSHYA_designated.mp4          (optional; own-feed UI, not the live grid)
  README.txt                         (this page, or YOUTUBE_DESCRIPTION.txt)
```

Quote numbers only from `docs/MEASURED_RESULTS.md` (generated 2026-09-06T21:02:56Z):
**689,502** observations · **178,757** persons · **69** marks · **74** corroborated ·
**43** leads · **0** cross-camera repeats · **1** OCR-lookalike pair
(`GJ32K5587`/`GJ3ZK5587`) · **9** cameras published a mark.

## 3 · What to type if the form asks in words

**Solution name:** SAAKSHYA (साक्ष्य — evidence)

**Chosen model:** Hybrid of Models 1 + 2 + 3. Model 4 (central recording of every
camera) was rejected: modelled 80,000 × 2 Mbps ≈ 160 Gbps, 30-day retention ≈ 52 PB.

**One sentence on the designated vehicle:** On the live government grid we
rehearse `GJ1VV0119` (cam07, one camera, timebase RESTRICTED) and the open
watchlist alert `GJ38BH5815` (cam21). Cross-camera identity is demonstrated on
the own-feed corpus: `GJ05AB1234` and `GJ35BV6925` on C-014 and C-021.

**Problem, in two lines:** Federate heterogeneous CCTV without hauling 80,000
streams to one hall; search a designated vehicle by registration mark; keep
every answer auditable.

**Key features (paste):**
- Metadata-first onboarding (Model 1); ingest stills, not a second RTSP copy (Model 2); observation store as the metadata bus (Model 3).
- ANPR with voting, person detection from the same pass, no face recognition.
- Representative watchlist with automated alerts; purpose binding on every search.
- Hash-chained evidence; BSA s.63 generated as DRAFT_PENDING_SIGNATURE.
- Copilot with Gemini coordinator and deterministic fallback; stills are never enhanced.

**Phrases that must not appear:** production ready · legally admissible ·
tested at 80,000.

## 4 · Optional hosted URL / repository

Leave blank unless the team has already published a viewer-safe URL.
Do **not** paste the live bearer token or grid password into the form.

## 5 · After Submit

Keep ingest running if a jury session is still possible today. If the ingest
log says `streaming=0/30` and camera health last_error is HTTP 401, the
sandbox passkey has been refused — refresh it from the Sentinel portal and
restart ingest with the new values in the **process environment only**.
The films and `var/live.db` still stand; Submit does not wait on live RTSP.
