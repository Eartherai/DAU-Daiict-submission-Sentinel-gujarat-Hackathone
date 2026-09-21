# CLAUDE TAKEOVER — REPOSITORY AND RUNTIME STATE

Captured 2026-09-20 ~01:30–02:00 IST. Forensic pass only: **nothing in git was
modified, reset, cleaned, stashed, checked out or restored.**

## 1. Git

| | |
|---|---|
| Current branch | `hackathon-winning-upgrade` |
| Tracking | `origin/hackathon-winning-upgrade` (in sync) |
| HEAD | `201a0ec` config: add live media session definition |
| Working tree | **49 modified, 79 untracked** — all preserved |
| Diff size | 4381 insertions / 912 deletions across 49 tracked files |

### Worktrees

| Path | Commit | State |
|---|---|---|
| `.` (main) | `201a0ec` `hackathon-winning-upgrade` | **newest**; all live work here |
| `.claude/worktrees/auth-hardening` | `1a80add` | locked; 6 modified + `ui/auth-gate.js`, `tests/js/`, `test_public_tunnel_guard.py` uncommitted |
| `.claude/worktrees/live-collection-supervisor` | `201a0ec` | `tools/live/collect.py`, `tests/unit/test_live_collection.py` uncommitted |

Largest uncommitted deltas: `ui/app.js` (+2282), `ui/style.css` (+395),
`ui/index.html` (+188), `src/saakshya/api/routes_investigation.py` (+286),
`src/saakshya/api/routes_ops.py` (+242), `src/saakshya/command/summary.py` (+233).

New untracked source of record: `src/saakshya/live/relay.py`,
`relay_publisher.py`, `hub.py`, `analytics/worker.py`, `command/certify.py`,
`command/domain.py`.

## 2. Runtime as found

Two API instances were already running — neither started by this session:

| PID | Port | Age | Role |
|---|---|---|---|
| 44785 | **8083** | 45 min | **live instance**; parent of MediaMTX 44828 and of all 30 relay publishers |
| 91010 | 8088 | 3 h 13 m | stale instance, 0% CPU, owned a duplicate analytics worker |

`SAAKSHYA_DB=sqlite:///var/live.db`. The app reports
`plane: "local_relay"`, `whep: true`, 32 relay cameras.

## 3. Relay architecture (as built, verified correct)

```
Sentinel RTSP/TCP  →  relay_publisher (credential added in-process)
                   →  local MediaMTX 127.0.0.1:18554
                   →  local WHEP 127.0.0.1:18889  →  browser
```

- Browser tiles consume **local relay** media. No browser→Sentinel WHEP. Correct per brief §2/§6.
- Credentials are **not** in argv (`ps` shows clean `rtsp://host/stream/camNN`), not in any repo file, not in `.env.local`, not in any shell profile. They live only in the process environment of PID 44785 and its children.
- Log redaction holds: publisher logs show `rtsp://<redacted>@103.250.160.189:8554/...`.
- Both `SENTINEL_GRID_EMAIL/_PASSWORD` and `_BACKUP` are configured on 44785.

## 4. Media profile (measured with ffprobe against the local relay)

```
cam01 / cam07 / cam17 : h264 Baseline 640x360 yuv420p 8/1 fps
OWN-TRAFFIC           : h264 Constrained Baseline 768x432 12.5 fps
```

**The 240x144 / 3 fps defect is not present.** `relay.py` still *defaults* to
`MAX_HEIGHT=180`, `FPS=5`, `BITRATE=150k`, but the running instance overrides
them to `360 / 8 / 450k` via `SAAKSHYA_RELAY_MAX_HEIGHT|FPS|BITRATE`. The
defaults remain a latent regression for anyone who starts the app without
those overrides.

## 5. Defect found and fixed this session — CPU starvation

Found saturating a 10-core machine, **load average 89.21 (15 min)**:

| PID | Elapsed | CPU time | Process |
|---|---|---|---|
| 96707 | 15 h 19 m | 518 min | `pytest tests/unit/test_live_collection.py` (hung, parent shell dead) |
| 96880 | 15 h 16 m | 516 min | `pytest …test_live_collection.py -k "not full_run"` (hung, parent shell dead) |
| 91062 | 2 h 50 m | 151 min | duplicate `analytics.worker` owned by the stale 8088 app |

~430% CPU of sustained waste. Killed with the user's approval.
**Load fell 89 → 25.8, and relay readiness rose 15/32 → 25/32.** This was
starving the 30 concurrent VideoToolbox transcodes and is a direct cause of the
degraded decode rates and path dropouts described in the brief.

`tests/unit/test_live_collection.py` hanging indefinitely is an open defect in
the `live-collection-supervisor` worktree.

## 6. Known defects still open

1. **Pool-synchronised auth backoff without jitter** — see `CLAUDE_30_CAMERA_ROOT_CAUSE.md` §3. Primary pool: 90×401. Backup pool: 43×401.
2. `relay.py` default media profile (180p/5fps/150k) is below the §12 floor.
3. Liveness depends on `requestVideoFrameCallback`, which collapses to ~1 Hz wherever the compositor is throttled. `framesDecoded` should be the primary signal.
4. Two stale API instances can coexist; the 8088 one silently owned an orphan worker.
5. `_start_mediamtx` refuses to start when ports are occupied, so an orphaned relay blocks every new app start and the credentials are unrecoverable from the orphan.

## 7. What was NOT done

No git state altered. No relay restarted. No credential written to any file.
No demo recorded.

## Correction — the "0 live sessions" investigation (2026-09-20)

I reported twice that the live wall was broken: first that "my revert broke tile
painting", then that the wall "renders 30 tiles but opens 0 WHEP sessions". Both
were wrong, and the second was wrong for an instructive reason.

The measuring browser pane had collapsed to **zero width**. `window.innerWidth`
was `0`, so `body` was 0px, so the grid resolved to `grid-template-columns:
0px 0px` and every tile measured **2px wide**. `syncTileWhep` gates on
`r.width >= 8 && r.height >= 8`, so it opened no sessions — which is exactly what
it is supposed to do. Opening thirty HD WHEP sessions for tiles nobody can see is
the bug; refusing to is the feature. The direct WHEP probe returning 201 while the
wall sat at zero was not a contradiction, it was the gate working.

Given a real 1600x900 viewport the same build, unchanged, produced:

- 30 tiles at 512x260
- 12 WHEP sessions opened (the `TILE_WHEP_BUDGET`), 12 playing
- 8 decoding within 20s at native **1920x1080 and 1280x720**

Two lessons worth keeping:

1. **`video.currentTime` does not advance on a WebRTC MediaStream.** I briefly
   read `advancingOver6s: 0` as "video is frozen". It is not a liveness signal
   here; `framesDecoded` from `getStats()` is, which is why the tile FPS badge is
   built on it. Do not re-derive this a third time.
2. **Verify the instrument before diagnosing the subject.** Three of the last
   failures I chased — the stale-script tab, the expired token, and this
   zero-width pane — were faults in how I was looking, not in what I was looking
   at. Check viewport, script hash, and token age before touching application code.

No application change was required. The wall is healthy.
