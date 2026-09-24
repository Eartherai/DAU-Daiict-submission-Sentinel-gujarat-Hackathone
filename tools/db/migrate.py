#!/usr/bin/env python3
"""Copy a Saakshya store from one database to another, table by table.

    python tools/db/migrate.py --from var/live.db --to "$(cat var/pg/url)"

The source is opened read-only (SQLite `immutable`), so a store can be copied
while nothing is writing to it and is never modified by the copy. The
destination is created with the application's own `Store.create_all` - on
PostgreSQL that includes PostGIS and its indexes - and must be empty unless
`--replace` is given.

Rows are copied verbatim, in foreign-key order, in batches. Nothing is
recomputed: the audit log and the evidence records are hash chains, and a copy
that changed one byte of a timestamp would break them. That is also the test
of the copy. Afterwards the tool counts every table on both sides and verifies
both chains on the destination; it exits non-zero if either differs.

Integer ids are copied as they are, so PostgreSQL's sequences are then moved
past the largest id, or the next insert would collide.

PostgreSQL text cannot hold NUL, which SQLite stores without complaint. The
API now refuses the character, but a store written before that may carry it
(the government store's audit log held a security probe's search for
NUL-quote-quote). On PostgreSQL each NUL is written as `NUL_STAND_IN`
(U+2400) and counted; the audit chain's verifier turns it back before hashing,
so those entries still verify against the hashes made when they were written.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _source_url(src: str) -> str:
    if "://" in src:
        return src
    path = Path(src).resolve()
    return f"sqlite:///file:{path}?mode=ro&immutable=1&uri=true"


def main() -> int:
    from sqlalchemy import create_engine, func, inspect, select, text

    from saakshya.store import Store
    from saakshya.store import schema as S
    from saakshya.store.repository import NUL_STAND_IN

    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="SQLite file or database URL")
    ap.add_argument("--to", dest="dst", required=True, help="destination database URL")
    ap.add_argument("--batch", type=int, default=5000)
    ap.add_argument("--replace", action="store_true",
                    help="empty the destination's tables first")
    ap.add_argument("--evidence-root", type=Path,
                    help="the store's evidence directory, to verify the evidence chain "
                         "on the destination (the files are shared, not copied)")
    a = ap.parse_args()

    src = create_engine(_source_url(a.src))
    dst_store = Store(a.dst)
    dst_store.create_all()
    dst = dst_store.engine
    have = set(inspect(src).get_table_names())
    tables = [t for t in S.metadata.sorted_tables if t.name in have]

    with dst.begin() as c:
        busy = [t.name for t in tables
                if c.execute(select(func.count()).select_from(t)).scalar()]
        if busy and not a.replace:
            print(f"destination is not empty ({', '.join(busy[:5])}...); "
                  "pass --replace to empty it first", file=sys.stderr)
            return 2
        for t in reversed(tables):
            if t.name in busy:
                c.execute(t.delete())

    stand_in = dst.dialect.name == "postgresql"
    nuls = 0

    def clean(row: dict) -> dict:
        nonlocal nuls
        for k, v in row.items():
            if stand_in and isinstance(v, str) and "\x00" in v:
                row[k] = v.replace("\x00", NUL_STAND_IN)
                nuls += 1
        return row

    t0 = time.perf_counter()
    counts: dict[str, tuple[int, int]] = {}
    for t in tables:
        src_cols = {col["name"] for col in inspect(src).get_columns(t.name)}
        cols = [col for col in t.columns if col.name in src_cols]
        n = 0
        with src.connect() as s, dst.begin() as d:
            rows = s.execution_options(yield_per=a.batch).execute(select(*cols))
            for part in rows.partitions(a.batch):
                d.execute(t.insert(), [clean(dict(r._mapping)) for r in part])
                n += len(part)
        with dst.connect() as d:
            got = d.execute(select(func.count()).select_from(t)).scalar() or 0
        counts[t.name] = (n, got)
        if n:
            print(f"  {t.name:<24} {n:>9,} rows", flush=True)

    if dst.dialect.name == "postgresql":
        with dst.begin() as d:
            for t in tables:
                pk = [c for c in t.primary_key.columns]
                if len(pk) == 1 and pk[0].autoincrement is True:
                    d.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                        f"COALESCE((SELECT MAX({pk[0].name}) FROM {t.name}), 0) + 1, false)"))

    bad = {k: v for k, v in counts.items() if v[0] != v[1]}
    total = sum(v[0] for v in counts.values())
    print(f"copied {total:,} rows in {time.perf_counter() - t0:.0f} s; "
          f"counts {'MATCH' if not bad else f'DIFFER: {bad}'}")

    if nuls:
        print(f"{nuls} text value(s) held a NUL, which PostgreSQL cannot store: "
              f"written with U+2400 in its place")
    ok = not bad
    chain_ok, err = dst_store.verify_audit_chain()
    print(f"audit chain on the destination: {'verified' if chain_ok else err}")
    ok &= chain_ok
    if a.evidence_root:
        from saakshya.evidence.manifest import EvidenceService
        ev = EvidenceService(dst_store, root=a.evidence_root).verify_chain()
        print(f"evidence chain on the destination: {'verified' if ev.ok else 'FAILED'}")
        ok &= ev.ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
