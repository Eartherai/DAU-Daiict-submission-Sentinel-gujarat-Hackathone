#!/usr/bin/env python3
"""Stop calling real people's cars stolen.

To show the alert path working on live data, plates read off the government
evaluation footage were put on the watchlist. They were filed under
"stolen_vehicle". Nothing is known about those vehicles except that a camera
read them; the category put a false statement about a real, identifiable
owner into every alert card, every export and every demonstration film.

This re-files every such entry as `evaluation_designated` — "designated
vehicle of interest (evaluation)" — which is what it is. The alert path, the
priority and the match are unchanged; only the accusation goes. Alerts carry
the category they were raised under, so they are re-filed too.

A plate counts as real when it was read by a government camera in this store.
Fictional plates (the synthetic corpus, the GJ99 test fixtures) are never read
off real footage and are not touched here, except that test-harness rows are
revoked with a reason: they exist to exercise expiry and revocation in tests,
and do not belong in a store used for demonstrations.

    python tools/admin/recategorise_evaluation_watchlist.py --db sqlite:///var/live.db
    python tools/admin/recategorise_evaluation_watchlist.py --db sqlite:///var/live.db --apply

Dry run by default. Every change is written to the hash-chained audit log.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

#: Reasons that mark a row as a test fixture rather than an evaluation entry.
HARNESS_REASONS = ("expired entry under test", "revoked entry under test",
                   "low-quality read under test")
TARGET = "evaluation_designated"


def plan(store) -> dict:
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        read_by_gov = {r[0] for r in c.execute(
            select(S.observations.c.plate).where(
                S.observations.c.plate.is_not(None),
                S.observations.c.camera_id.like("cam%")).distinct())}
        rows = [dict(r._mapping) for r in c.execute(select(S.watchlist))]
    refile = [r for r in rows if r["category"] == "stolen_vehicle"
              and r["plate"] in read_by_gov]
    harness = [r for r in rows if (r.get("reason") or "") in HARNESS_REASONS
               and r.get("status") != "REVOKED"]
    return {"refile": refile, "harness": harness}


def apply(store, p: dict, actor: str) -> dict:
    from sqlalchemy import update

    from saakshya.store import now_us
    from saakshya.store import schema as S
    plates = sorted({r["plate"] for r in p["refile"]})
    with store.engine.begin() as c:
        for r in p["refile"]:
            c.execute(update(S.watchlist)
                      .where(S.watchlist.c.watchlist_id == r["watchlist_id"])
                      .values(category=TARGET, version=(r.get("version") or 1) + 1))
        n_alerts = 0
        if plates:
            res = c.execute(update(S.alerts)
                            .where(S.alerts.c.plate.in_(plates),
                                   S.alerts.c.category == "stolen_vehicle")
                            .values(category=TARGET, updated_at_us=now_us()))
            n_alerts = res.rowcount or 0
        for r in p["harness"]:
            c.execute(update(S.watchlist)
                      .where(S.watchlist.c.watchlist_id == r["watchlist_id"])
                      .values(status="REVOKED",
                              reason=f"{r['reason']} — test fixture, removed from "
                                     "the demonstration store"))
    _audit(store, actor, plates, n_alerts, len(p["harness"]))
    return {"watchlist_refiled": len(p["refile"]), "plates": plates,
            "alerts_refiled": n_alerts, "harness_revoked": len(p["harness"])}


def _audit(store, actor, plates, n_alerts, n_harness) -> None:
    """Record the change where every other watchlist change is recorded."""
    try:
        from saakshya.security import AuthContext, Principal, Role
        ctx = AuthContext(principal=Principal(user_id=actor, role=Role.ADMIN),
                          purpose="re-file evaluation watchlist entries that "
                                  "named real vehicles as stolen")
        ctx.audit(store, "watchlist_recategorise",
                  target=",".join(plates)[:500], result_count=len(plates) + n_harness)
    except Exception as exc:                       # pragma: no cover - reported
        print(f"  audit entry not written: {exc}", file=sys.stderr)


def main() -> int:
    from saakshya.store.repository import Store

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--actor", default="admin.recategorise")
    a = ap.parse_args()
    store = Store(a.db)
    # A store created before the alert lifecycle columns existed gains them
    # here, in place, exactly as the API does at startup. Without this the
    # first run against the live store failed on `updated_at_us` - inside one
    # transaction, so nothing was half-written.
    store.create_all()
    p = plan(store)
    print(f"real plates filed as stolen: {len(p['refile'])} "
          f"({', '.join(sorted({r['plate'] for r in p['refile']}))[:300]})")
    print(f"test-harness rows still active: {len(p['harness'])}")
    if not a.apply:
        print("dry run — re-run with --apply to write")
        return 0
    out = apply(store, p, a.actor)
    print(f"re-filed {out['watchlist_refiled']} watchlist entries and "
          f"{out['alerts_refiled']} alerts as '{TARGET}'; "
          f"revoked {out['harness_revoked']} test-harness rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
