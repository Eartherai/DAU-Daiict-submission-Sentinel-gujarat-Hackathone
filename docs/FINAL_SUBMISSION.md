# SAAKSHYA — final submission index

Team Saakshya · Gujarat Police CCTV Innovation Challenge (Sentinel).
Every file named here is in the submission folder `var/demo/SUBMIT/`
(built by `python tools/demo/build_submission_pack.py`). Upload **that
folder**, not the older `var/demo/PORTAL_PACK/`.

## Requirement → where it is answered

### 1. Solution presentation (PPT/PDF) — `01_SAAKSHYA_deck.pptx`, `01_SAAKSHYA_deck.pdf` (37 slides)

| Asked for | Answered |
|---|---|
| Proposed model with justification | Hybrid of Models 1 + 2 + 3, with Model 4 analytics on selected cameras; central recording of ~80,000 cameras declined on 160 Gbps / 52 PB arithmetic |
| Overview, objectives, innovations | Find → Trace → Verify → Act; capability measured per camera; metadata moves, video stays |
| Architecture and end-to-end workflow | Two architecture diagrams and the seven-step pipeline from camera to search |
| AI video analytics | RT-DETRv2 detection + ByteTrack tracking on the GPU; ANPR with a plate detector on full-resolution tiles and an Indian-trained recogniser (Awiros-ANPR-OCR, ported to PyTorch); per-track voting that publishes only plates the frames agree on; person detection, long-stay, restricted zones |
| Watchlist correlation and real-time alerts | Match at ingest in the same transaction as the sighting; incidents, honest priority, read-against-list |
| Technologies | PyAV, PyTorch + ONNX Runtime, FastAPI, SQLite and PostgreSQL 18 + PostGIS 3.6, vanilla ES; licences pinned |
| Scale, interoperability, security, deployment | District edge + metadata centre; four authorisation gates; hash-chained evidence and audit |
| Operational benefit | An index answers a plate nobody had asked for yet; honest capability grades |

### 2. Technical proposal — HLD — `02_HLD.md`, `02_HLD_diagrams.pdf`, `02_SECURITY.md`

| Asked for | HLD section |
|---|---|
| Architecture, diagrams, component interactions | §3, §4, `02_HLD_diagrams.pdf` |
| Heterogeneous cameras, NVRs, VMS | §10 (adapters; no VMS replaced), §13 item 6 |
| Ingesting live streams from dispersed locations | §4.1, §6, §15, §16; sandbox access pattern in `docs/SENTINEL_SANDBOX.md` |
| Watchlist databases and continuous correlation | §11, §11.1 |
| AI analytics: ANPR, FRS, detection, tracking | §4.2 (ANPR, detection, tracking, persons); §11.2 (FRS: designed and gated, with why) |
| Alert generation, prioritisation, visualisation, interaction | §11.1 |
| Scalability, interoperability, security, performance to ~80,000 cameras | §7, §12, §16, §17, §18; `05_SCALE_80K_LOAD_TEST.md` |
| Prerequisites and information needed from departments | §13 |

### 3. Own-feed demonstration (max 2–3 min) — `03_own_feed.mp4` (2 min 53 s, 2560×1440, narrated)

Licensed Mumbai traffic footage, heads blurred. Onboarding a camera through the
registry portal; the pipeline's own boxes on every frame; a plate read off the
footage searched and traced; a watchlist match and the alert it raised (on
fictional plates — no real vehicle is listed); a printable trace report; sealed
evidence; the audit log. Working backend throughout; no mock-ups.
Recorded 24 September with the previous plate recogniser (Apple Vision); the
submitted code uses the Indian-trained recogniser (HLD §4.2).

### 4. Government-feed demonstration — `04_government_feed.mp4` (8 min 10 s), `04_government_feed_1080p.mp4`, `04_government_feed_anpr_report.csv`

The issued cameras onboarded; live viewing over direct WebRTC; thirty cameras on
one wall; analytics output; every plate read with camera and timestamp; the
output report as CSV (plate, UTC and IST timestamp, camera, confidence, votes,
format validity, observation and evidence ids).

### Supporting material

`00_CHECKLIST.md` (honest limits), `05_*` (registry API, gap analysis, 80k load
test, sample metadata), `06_*` (printable trace reports).

## How to submit

- **Videos** — upload `03_own_feed.mp4` and `04_government_feed.mp4` to YouTube
  with visibility **Unlisted**; paste both links.
- **Documents and pack** — upload the whole `var/demo/SUBMIT/` folder to Google
  Drive or OneDrive and share it as **Anyone with the link — Viewer**.
- **Source** — `https://github.com/Eartherai/DAU-Daiict-submission-Sentinel-gujarat-Hackathone`
  (the submission branch must be pushed and merged to `main` first).
- **Hosted platform (optional)** — if one is offered to the committee, create
  a dedicated read-only screening account and send its credentials separately,
  never in a document or the repository.

Never upload `.env`, `.env.local`, token files, `var/pg/url`, or stream
passwords.
