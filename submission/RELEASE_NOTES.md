# SAAKSHYA v1.0 — final submission

**Gujarat Police Innovation Challenge 2026 · Sentinel Camera Grid · DAU (DA-IICT) · 28 September 2026**

A federated CCTV intelligence and evidence platform: a hybrid of **all four
models, 1 + 2 + 3 + 4, all built**. Model 4's central analytics ran live on the
government grid on 28 Sep (4 slots, 4,465 observations, 200 plate reads).

## Films

| Film | Length | What it shows |
|---|---|---|
| `03_own_feed.mp4` | 2:43 | Sign-in, form onboarding validated before write, administrator → officer handoff, per-frame detection and voted plates on licensed footage, ANPR search, watchlist alert with map, route and trace report, evidence chain |
| `04_government_feed.mp4` | 5:40 | Recorded **live** on the Sentinel grid, 28 Sep 2026 12:41–12:47 IST, with the live count measured on screen |
| `04b_government_tour.mp4` | 15:04 | Every feature, from sign-in: 49 beats, 0 failures, on government footage recorded on 15 Sep. The footage is labelled RECORDED on every tile and never called live |

## Results

- **Government store:** 1,155,325 observations; persons on all 30 cameras, vehicles on 29.
- **Plate report:** 1,101 government plate reads with UTC/IST timestamps (`04_government_feed_anpr_report.csv`).
- **Indian plate recogniser:** 17 of 21 hand-read plates exact, against 5 of 21 for the previous recogniser.
- **Quality:** 1,582 tests pass, 0 fail; the secret scan passes on every file and the full history.

**Not claimed:**
- no government plate was read on two government cameras, so there is no real multi-camera government route (route logic is shown on a labelled synthetic corpus);
- no live test at 80,000 cameras; statewide sizing is MODELLED.

## Assets

- **Deck:** `01_SAAKSHYA_deck.pdf` / `.pptx`
- **Design:** HLD diagrams
- **Films:** all three at 2560×1440; 1080p copies are in `submission/films/`
- **Reports:** government plate CSV, replay-reads CSV, designated-vehicle trace report

Start with `submission/` and `docs/FINAL_SUBMISSION.md`. The live-grid integration story is in `docs/LIVE_INTEGRATION_STORY.md`.
