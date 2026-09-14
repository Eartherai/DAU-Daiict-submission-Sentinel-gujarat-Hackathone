#!/usr/bin/env python3
"""EXPLAIN the hot queries and report which index each one actually uses.

Written because "we added indexes" is not evidence. Every index in the schema
should be traceable to a query plan in this output; an index that appears here
as unused is either a query that needs rewriting or an index that should be
dropped, and both are worth knowing before an evaluator asks.

SQLite's `EXPLAIN QUERY PLAN` is used directly rather than through the ORM: the
plan is the artefact, and paraphrasing it would defeat the purpose. The same
queries on PostgreSQL would need `EXPLAIN (ANALYZE, BUFFERS)`; the deployment
note in docs/PERFORMANCE.md says so.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from saakshya.common.paths import display
from saakshya.store import Store
from saakshya.store import schema as S
from saakshya.store.repository import to_us

#: A plan line containing any of these means the query is reading more rows than
#: it should. "SCAN" without an index on a large table is the finding.
BAD = ("SCAN observations", "SCAN plate_reads", "SCAN audit_log", "USE TEMP B-TREE")


def plans(store: Store, label: str, stmt) -> dict:
    sql = str(stmt.compile(store.engine, compile_kwargs={"literal_binds": True}))
    with store.engine.connect() as c:
        rows = [r._mapping for r in c.exec_driver_sql(
            "EXPLAIN QUERY PLAN " + sql)]
    detail = [r["detail"] for r in rows]
    concerning = [d for d in detail if any(b in d for b in BAD)]
    return {"query": label, "plan": detail, "concerning": concerning,
            "sql": " ".join(sql.split())[:400]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("SAAKSHYA_DB",
                                                   "sqlite:///var/demo.db"))
    ap.add_argument("--json", type=Path, default=ROOT / "var" / "reports" / "query_plans.json")
    args = ap.parse_args()

    store = Store(args.db)

    store.create_all()      # a store older than the code is migrated, not queried
    now = datetime.now(UTC)
    plate = (store.distinct_plates() or ["GJ01AA0000"])[0]
    cams = [c["camera_id"] for c in store.list_cameras()][:4]

    checks = []

    # 1. The mandatory query: every observation of one registration mark.
    checks.append(plans(store, "plate search (exact, time-bounded)",
        select(S.observations)
        .where(S.observations.c.plate == plate,
               S.observations.c.t_norm_us >= to_us(now - timedelta(days=7)),
               S.observations.c.t_norm_us <= to_us(now))
        .order_by(S.observations.c.t_norm_us)))

    # 2. Camera timeline — what an investigator opens after clicking the map.
    checks.append(plans(store, "camera timeline",
        select(S.observations)
        .where(S.observations.c.camera_id == (cams[0] if cams else "X"),
               S.observations.c.t_norm_us >= to_us(now - timedelta(hours=6)))
        .order_by(S.observations.c.t_norm_us)))

    # 3. District-scoped scan — the access-control path, so it must be indexed.
    checks.append(plans(store, "district-scoped time window",
        select(S.observations)
        .where(S.observations.c.district == "Ahmedabad",
               S.observations.c.t_norm_us >= to_us(now - timedelta(days=1)))
        .order_by(S.observations.c.t_norm_us)))

    # 4. Trajectory input: several cameras at once.
    checks.append(plans(store, "trajectory candidate fetch (multi-camera)",
        select(S.observations)
        .where(S.observations.c.camera_id.in_(cams or ["X"]),
               S.observations.c.plate == plate)
        .order_by(S.observations.c.t_norm_us)))

    # 5. Graph edges out of one camera.
    checks.append(plans(store, "camera graph edges",
        select(S.camera_transitions)
        .where(S.camera_transitions.c.from_camera == (cams[0] if cams else "X"))))

    # 6. Watchlist lookup on every observation — the hottest query in ingest.
    checks.append(plans(store, "watchlist lookup by plate",
        select(S.watchlist).where(S.watchlist.c.plate == plate,
                                  S.watchlist.c.status == "ACTIVE")))

    # 7. Open alerts for the control room.
    checks.append(plans(store, "open alerts, newest first",
        select(S.alerts).where(S.alerts.c.status == "OPEN")
        .order_by(S.alerts.c.t_norm_us.desc())))

    # 8. Map viewport.
    checks.append(plans(store, "camera viewport (bbox)",
        select(S.cameras).where(S.cameras.c.lat.between(22.9, 23.3),
                                S.cameras.c.lon.between(72.4, 72.9))))

    # 9. Audit trail for one case.
    checks.append(plans(store, "audit trail for a case",
        select(S.audit_log).where(S.audit_log.c.case_id == "FIR-214/2026")
        .order_by(S.audit_log.c.id)))

    # 10. Edge queue drain.
    checks.append(plans(store, "edge queue drain (pending by sequence)",
        select(S.edge_queue).where(S.edge_queue.c.node_id == "node-01",
                                   S.edge_queue.c.state != "ACKED")
        .order_by(S.edge_queue.c.sequence).limit(500)))

    width = max(len(c["query"]) for c in checks)
    concerning = 0
    print(f"{'query':{width}}  plan")
    print("-" * (width + 60))
    for c in checks:
        first = c["plan"][0] if c["plan"] else "(no plan)"
        flag = "  <-- REVIEW" if c["concerning"] else ""
        concerning += bool(c["concerning"])
        print(f"{c['query']:{width}}  {first}{flag}")
        for extra in c["plan"][1:]:
            print(f"{'':{width}}  {extra}")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({
        "database": args.db,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "row_counts": store.stats(),
        "checks": checks,
    }, indent=2))
    print(f"\n{len(checks)} queries examined, {concerning} needing review")
    print(f"written: {display(args.json, ROOT)}")
    # A concerning plan is a finding, not a failure: on an empty table SQLite
    # will scan whatever it likes, and that is the correct choice.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
