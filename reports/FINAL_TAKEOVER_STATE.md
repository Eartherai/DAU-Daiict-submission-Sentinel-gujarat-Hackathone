# Final takeover state — 28 Sep 2026

Recorded before any modification, by the session that took over after the
previous one hit its usage limit. Everything below was checked in the worktree,
not copied from the previous session's summary. Where that summary disagrees
with the files, the files win and the disagreement is noted.

## Repository

| Item | State |
|---|---|
| Branch | `hackathon-winning-upgrade` |
| HEAD | `b5a21c8` Submission: sizing and costs, Model 3 deliverables, deck slides for the brief |
| Upstream | `origin/hackathon-winning-upgrade`, **99 commits ahead, nothing pushed** |
| Dirty tracked files | 2 — `var/reports/phase10/sentinel_catalogue.json`, `sentinel_contract_probe.json` (a re-run probe: new timestamp, catalogue unreachable). User-owned measurement output; left untouched. |
| Untracked entries | 27 (evidence, reports, mediamtx configs, worktrees). Left untouched. |

## Worktrees and unmerged work

| Source | Verdict |
|---|---|
| `~/saakshya-orch/wt-{deck,hld,hub,ocr}` | Uncommitted diffs are **already applied to HEAD** (reverse-apply check passes). |
| `~/saakshya-orch/wt-fed` | Its new files (`docs/ADAPTERS.md`, `tools/reports/federated_report.py`, test) are committed. |
| `~/saakshya-orch/wt-gate` | Not merged, deliberately — cosmetic line-wrapping of the deck generator that conflicted with the deck lane. |
| `~/saakshya-orch/wt-audit` | Report only. **Its 15 ranked fixes were never applied** — the previous session hit its limit while dispatching them. |
| `fix/api`, `fix/ocr`, `fix/store`, `fix/store-v2` | Every patch is already in HEAD (`git cherry` all `-`). |
| `fix/ocr2` (6 commits) | Superseded: the same intent (Metal lock for every spelling, fail loudly, no single-read lead) landed in `fe2af64` from the OCR lane. Not merged. |
| `worktree-wf_70c9cc93-762-1` `fe90655` "Tell the officer the truth about alerts, near matches, leads and refusals" | **Possibly lost work.** Not in HEAD, 16 files / +443 lines across copilot, incidents, trace report and `ui/app.js`, and it no longer applies (conflicts in four copilot files). Not merged during submission mastering: it rewrites the mandatory alert path. Flagged for a decision after submission. |

## Previously claimed fixes

| Claim | Verified |
|---|---|
| Corroboration read the oldest 20,000 observations | Fixed — `intelligence/search.py:183-189` windowed follow scan, with the old behaviour described in place. |
| `enforce_evaluation_50` deleted operator-onboarded cameras | Fixed — `command/domain.py:371` keeps unrecognised cameras. |
| Post-boot onboarding lost the district | Fixed — `tests/unit/test_live_evaluation_blind_spots.py:114-138` onboards a camera after the first batch and asserts its observations carry the district; passes. |
| Demo onboarding filmed under SUPERVISOR | Recorder now uses the estate administrator, then hands over. RBAC unchanged. |

## Test baseline at `b5a21c8`

`.venv/bin/python -m pytest -q -p no:cacheprovider` (whole `tests/`, no live
Sentinel test — the two files naming the sandbox host use it only as a string
in redaction assertions): **1,375 passed, 20 skipped, 0 failed**, exit 0,
20 min 45 s (run while five agents shared the CPU).

## Submission pack `var/demo/SUBMIT/` (224 MB, 19 files)

The pack was **not rebuilt after the last merge**:

- `01_SAAKSHYA_deck.pptx/.pdf` date from 01:35; the deck generator changed in
  `b5a21c8` at 05:24. The pack ships the deck *without* the sizing, cost and
  50-camera composition slides.
- `02_HLD_diagrams.pdf` dates from 3 Sep and labels **Model 2 as "central
  processing"** (`tools/demo/render_diagrams.py:213,229`), contradicting the HLD.
- The federated analytics report and `docs/ADAPTERS.md` are not in the pack.

### Films (ffprobe)

| File | Duration | Format | Previous session said |
|---|---|---|---|
| `03_own_feed.mp4` | **2:53.5** (173.5 s, 5,205 frames) | h264 2560×1440 30 fps | 2m46s |
| `04_government_feed.mp4` | **8:10.3** (490.3 s, 12,258 frames) | h264 2560×1440 25 fps | 4m41s |

The government film, recorded 24 Sep, **fails the brief's own quality gate**:

- t=1 s: blank "Loading the shift picture…"; t=10 s: blank "Loading measured
  capability…"; t=45 s: a registry table, still no moving video.
- t=120 s: a 3×3 wall with **all nine tiles black**.
- t=160–250 s: good — moving government footage on the wall and a selected
  camera — but several tiles show H.264 smearing.
- t=300 s and t=470 s: near-blank pages.
- It shows 38 onboarded cameras, against the 50-camera composition in the deck.

Cause: the recorder waits fixed timeouts (`wait_for_timeout`) instead of waiting
for content to render.

## Documentation findings

- **Sentinel clarification is already in `docs/SENTINEL_SANDBOX.md:127-148`**
  ("no fixed participant-facing limit"). One line contradicts it in spirit:
  `:154`, relay "capped at the 15 cameras it was measured to sustain".
- **AI coverage wording** (`command/summary.py:291-296`): "reporting 4 of 30
  camera(s) with a stream under analysis". Deliberately honest — the comment
  says why. `runtime/inference_scheduler.py` adapts *inference cadence* by
  priority mode; nothing found rotates *which* cameras get deep inference. The
  tiered wording may say "all integrated cameras health-monitored, N under deep
  inference, adaptive cadence" — it must not claim camera rotation.
- Bytes per observation: docs model ~400 B; `var/reports/bandwidth.json`
  measures 1,331.7 B.

## CLI agents

`codex1..4` and `claude4` are shell aliases for `codex` / `claude` with separate
`CODEX_HOME` / `CLAUDE_CONFIG_DIR` accounts. Aliases do not expand in scripts,
so lanes invoke the underlying command with the environment variable set.
Codex lanes run `-s workspace-write`, which confines writes to the lane's
worktree and has no network — they cannot reach Sentinel.
