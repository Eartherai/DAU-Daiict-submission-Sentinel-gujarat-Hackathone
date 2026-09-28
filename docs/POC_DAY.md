# On-site PoC — 22–23 September 2026

Use `FINAL_SUBMISSION.md` for current commands and pack names. Government
`GJ11S7924` on cam06 is SINGLE-CAMERA evidence. Own-feed `GJ18JX7786` is the
CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION
(`reports/SUBMISSION_EVIDENCE_SNAPSHOT.md`).

Venue: i-Hub, Ahmedabad (portal). Bring this machine if it still holds
`var/live.db` and the 30 ingest sessions; otherwise a cold start of ingest
needs `SENTINEL_GRID_EMAIL` / `PASSWORD` in the environment only.

## Do not

- Kill ingest to “clean up” unless the team accepts 30 RTSP reconnects.
- Print tokens, grid passwords, or Gemini keys on a projector.
- Say production ready, legally admissible, or tested at 80,000.
- Invent coordinates for cam20–cam30.
- Run a 30-tile WebRTC wall (30 extra stream copies).

If ingest is `0/30` with last_error **401**, the sandbox passkey was refused.
Refresh it from the portal, then restart ingest. Do not restart without a
new password — the current process will only 401. The store and films remain
the submission evidence.

## 12-minute jury path

1. Sign in. Case + purpose on the gate. Token field is a password box.
2. Overview — open alert, cameras that published a mark, ANPR GOOD = 0 is yield.
3. Live wall — CONTROL ROOM up to 30 direct WHEP sessions / OPTIMIZED VIEW at most 12; current policy in `FINAL_SUBMISSION.md`.
4. Map — 19 placed, 11 listed.
5. Find `GJ11S7924` — one-camera honesty.
6. Alerts — `GJ38BH5815` evaluation_designated HIGH; representative evaluation entry, not stolen.
7. OCR lookalike on the live store: `GJ32K5587` / `GJ3ZK5587` (2 vs Z, both
   cam07). Two marks, not merged. Typed lookalike `6J1VV0119` still works.
8. If they hand a **new** mark: watchlist (authority + reason required) → wait
   for ingest match → search → trajectory. Timebase ALLOWED / RESTRICTED /
   REFUSED, never guessed.
9. If they want two cameras: say the live store has 0 repeats; switch to
   port **8081** (`sqlite:///var/demo.db`) and `GJ18JX7786`.
   8081 is the own-feed workspace — never the live grid. Label it LOCAL
   SYNTHETIC out loud. Live tiles come from the local corpus (MediaMTX on
   this machine, or last stills in `var/demo_evidence/preview/`). Do not
   point 8081 at the government RTSP host.
10. Analytics — object mix (car / truck / bus / person / two-wheeler) is
    detector labels from the same pass. Long-stay is duration, not intrusion.
11. Copilot last. If Gemini 429s, rules still answer. Refuse “enhance this still”.
12. Evidence — chain verified; BSA s.63 unsigned.

## Fresh token (never in the repo)

```bash
PYTHONPATH=src .venv/bin/python -c "
from datetime import timedelta
from pathlib import Path
from saakshya.store import Store
from saakshya.security import TokenService
t = TokenService(Store('sqlite:///var/live.db'))
tok = t.mint('supervisor.live', label='poc-day', ttl=timedelta(hours=8))
Path('/tmp/saakshya-poc-token.raw').write_text(tok)
print('bytes', len(tok))
"
```

## If the grid is down

Own-feed corpus on port **8081** (not 8080): `GJ18JX7786` (C-014 then C-021),
watchlist alerts. Label it LOCAL SYNTHETIC out loud.
