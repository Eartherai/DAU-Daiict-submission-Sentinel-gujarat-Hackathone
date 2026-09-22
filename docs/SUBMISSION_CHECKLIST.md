# Final submission checklist

Written 22 September 2026. Every figure on this page was read off the file it
describes, not carried over from an earlier draft.

Two older pages — `docs/PORTAL_UPLOAD.md` and `docs/SUBMISSION.md` — describe
the artifacts as they were on 14 September and are **superseded by this one**.
They say 54 slides, a 2:47 own-feed film at 1080p, and a government film of
1:37 with zero plates read. None of those three numbers is still true. Do not
quote them on the portal.

## 1 · The four required items

| # | What the challenge asks for | File | Verified |
|---|---|---|---|
| 1 | Solution presentation | `var/demo/SAAKSHYA_deck.pptx` (17.7 MB) and `var/demo/SAAKSHYA_deck.pdf` (9.0 MB) | **34 slides**, 16:9. Upload the PPTX if the field wants PowerPoint; attach the PDF as well so nothing depends on their renderer. |
| 2 | Technical proposal / high-level design | `docs/HLD.md` (§1–19) plus `var/demo/diagrams/` | Includes §15 disaster recovery, §16 statewide rollout with exit gates, §17 an indicative cost model with its workings shown, §18 the cybersecurity architecture with every control marked IMPLEMENTED or SPECIFIED, §19 the claims this proposal declines to make. |
| 3 | Demo video — own feed, **maximum 2–3 minutes** | `var/demo/own_feed.mp4` | **2 m 27 s** · 2560×1440 @ 30 fps · 8.9 MB. Inside the cap with 33 s to spare. Seven beats, all driven cleanly: onboarding through the registry API, AI detection on our own feeds, analytics, the traced mark, the watchlist alert, sealed evidence, the audit record. |
| 4 | Demo video — government feed, **with a report of detected vehicles / plates and timestamps** | `var/demo/government_feed.mp4` + `var/demo/government_feed_anpr_report.csv` | Video **4 m 42 s** · 2560×1440 @ 30 fps · 95.6 MB (1080p copy: `government_feed_1080.mp4`, 20.8 MB, upload this one if the portal caps size). Report: **178 plate reads across 9 government cameras**, each with UTC timestamp, camera id, camera name, district, department, object type and vote count. |

The recorder refuses to finish an own-feed film over three minutes rather than
producing something an assessor will have cut off. That check passed.

## 2 · Model 1 deliverables

| Named deliverable | File | What it actually contains |
|---|---|---|
| Registry gap analysis | `reports/MODEL1_GAP_ANALYSIS.md` | 34 cameras onboarded, 18 capacity slots, six departments. Counted in SQL across the whole registry — not sampled. Names five fields at 94.1% unpopulated and says what each one blocks. |
| Registry API documentation | `reports/REGISTRY_API.md` | Generated from the running service's own OpenAPI schema, so it cannot document an endpoint the platform does not serve. |
| Sample onboarded camera-metadata dataset | `reports/sample_camera_metadata.csv` | 34 rows, 27 columns — the registry's own export, which round-trips back into `POST /registry/cameras/import.csv`. |
| Scalability and load test, ~80,000 cameras | `reports/SCALE_80K_LOAD_TEST.md` | Measured, not modelled: 80,000 cameras onboarded in 1.305 s, gap analysis over all of them in 171 ms, single lookup 0.7 ms, 58.01 MB on disk. Followed by a section on what those numbers do **not** prove. |

## 2b · A folder you can drag to Drive

`var/demo/SUBMIT/` holds every file named above, numbered in submission order,
built fresh on 22 September. The videos and the deck are hardlinks, so the
folder costs no extra disk and can never drift from the originals.

```
00_CHECKLIST.md
01_SAAKSHYA_deck.pptx              01_SAAKSHYA_deck.pdf
02_HLD.md                          02_HLD_diagrams.pdf
03_own_feed_2m27_1440p.mp4
04_government_feed_4m42_1440p.mp4  04_government_feed_1080p.mp4
04_government_feed_anpr_report.csv
05_MODEL1_GAP_ANALYSIS.md          05_REGISTRY_API.md
05_SCALE_80K_LOAD_TEST.md          05_sample_camera_metadata.csv
```

Ignore the older `var/demo/PORTAL_PACK/` and `PORTAL_PACK.zip` — they are the
14 September artifacts.

## 3 · Before you upload

- [ ] **Revoke the live supervisor token — after your last live demo, not
      before it.** A working token was pasted into
      `tools/recorder/record_full_demo.py` during development. It is gone from
      the working tree and from history — `tools/verify/secret_scan.py` passes
      across 976 tracked files and the full history — but the credential is
      valid until the account that issued it is disabled. Disabling kills
      *every* token for that user, including the one the recorders use, so
      sequence it last:

      ```
      .venv/bin/python tools/admin/users.py --db sqlite:///var/live.db disable --user supervisor.live
      .venv/bin/python tools/admin/users.py --db sqlite:///var/live.db add     --user supervisor.live --role SUPERVISOR --name "Supervisor (live grid)"
      .venv/bin/python tools/admin/users.py --db sqlite:///var/live.db token   --user supervisor.live --days 7
      ```

      `add` re-enables the account; `token` prints the replacement once and
      stores only its SHA-256. Put it in a file outside the repository.
- [ ] **Rotate the Sentinel grid credentials.** They were typed into a chat
      transcript. They live only in `.env.local` (mode 600, gitignored), but a
      credential that has been pasted anywhere should be treated as exposed.
- [ ] **Run the secret scan once more** on whatever you are about to attach:
      `python tools/verify/secret_scan.py`
- [ ] **Host the two films.** Unlisted YouTube, or Drive/OneDrive with "anyone
      with the link can view". Nothing in this repository can do this for you,
      and nothing in it has been given portal credentials.
- [ ] **Confirm the portal dates yourself.** This repository records
      submission closing 15 September 2026 and the on-site event 22–23
      September 2026, read off the official site on 6 September. That is old
      enough to re-check before you rely on it.
- [ ] **Do not attach** `.env.local`, any `*-token.raw`, or anything under
      `var/run/`.

## 4 · What to say plainly if asked

These are the honest limits. Stating them first is cheaper than being caught
by them in questions.

- **The AI plane runs four cameras, CPU-only** — roughly 1.4 fps each, ~5.6 fps
  aggregate, P50 around 170 ms and P95 up to 1.5 s. Statewide inference needs
  GPU capacity; the registry numbers say nothing about it and the load-test
  report says so in its own words.
- **94% of registry metadata is unpopulated** on five fields. That is the point
  of the gap report rather than a defect in it: the platform holds what
  departments have supplied and names what they have not, and it does not
  invent a value to fill a column.
- **The 178 plates are 178 distinct marks on 9 cameras, with zero exact
  cross-camera repeats.** A vehicle traced from one government camera to
  another is not something this estate has yet shown; the cross-camera trace
  in the own-feed film is on our own corpus, and the film says so. `docs/HLD.md`
  §19 states the same thing.
- **The store is SQLite**, not the PostgreSQL + PostGIS deployment the
  challenge suggests. The store abstracts its backend; that migration has not
  been exercised and is not claimed.
- **Two government cameras show corrupted colour** in the film — Dethali Char
  Rasta green, O.N.G.C. Office orange. Both artifacts are present in the
  upstream feed; they are not produced by anything here.
- **The upstream grid meters WHEP sessions.** After repeated recording it
  refuses new sessions for roughly 45–60 minutes. If you intend to show the
  live wall on stage, do not re-record beforehand.
- **Nothing here is production ready, legally admissible, or tested at 80,000
  cameras end to end.** The registry plane was tested at 80,000. The video and
  inference planes were not, and saying otherwise would be false.

## 5 · How to regenerate any of it

```
python tools/demo/record_own_feed.py        --base http://127.0.0.1:8083 --token-file tok.raw
python tools/demo/record_government_feed.py --base http://127.0.0.1:8083 --token-file tok.raw
python tools/reports/gap_analysis.py        --out reports/MODEL1_GAP_ANALYSIS.md
python tools/reports/registry_api_doc.py    --base http://127.0.0.1:8083 --token-file tok.raw
python tools/reports/scale_load_test.py     --n 80000
```

Every artifact in section 1 and 2 is produced by one of these commands. None
was assembled by hand, so none can quietly drift from what the code does.
