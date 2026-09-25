#!/usr/bin/env python3
"""Copy a Saakshya store from one database to another, table by table.

    python tools/db/migrate.py --from var/live.db --to "$(cat var/pg/url)"

The source is opened read-only (SQLite `mode=ro`), so the copy never modifies
it. It is not opened `immutable`: that tells SQLite the file cannot change, so
it never reads the write-ahead log, and every store the application writes is
in WAL mode. Rows committed since the last checkpoint live only in the WAL
while any connection is open (a running API, an idle job) or after a writer
was killed, and an immutable copy left them out and still reported MATCH,
because it compared the rows it had read with the rows it had written. A
read-only open of a WAL store may leave empty `-wal` and `-shm` files beside
it; the database file itself is untouched. Copy while nothing is writing: a
row committed during the copy is caught by the count check below, and the
tool exits non-zero.

The destination is created with the application's own `Store.create_all` - on
PostgreSQL that includes PostGIS and its indexes - and must be empty unless
`--replace` is given.

Rows are copied verbatim, in foreign-key order, in batches. Nothing is
recomputed: the audit log and the evidence records are hash chains, and a copy
that changed one byte of a timestamp would break them. That is also the test
of the copy. Afterwards the tool counts every table three ways - the rows it
read, the rows on the destination, and the source counted afresh on its own
connection - and verifies the audit chain on the destination, and the evidence
chain too when `--evidence-root` is given; it exits non-zero if anything
differs.

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
    return f"sqlite:///file:{path}?mode=ro&uri=true"


def _ignores_the_wal(url: str) -> bool:
    """A SQLite URL opened `immutable`, which never reads the write-ahead log."""
    from urllib.parse import parse_qs
    if not url.startswith("sqlite"):
        return False
    flag = parse_qs(url.partition("?")[2]).get("immutable", ["0"])[-1]
    return flag.lower() in {"1", "yes", "true", "on"}


def main(argv: list[str] | None = None) -> int:
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
    a = ap.parse_args(argv)

    src_url = _source_url(a.src)
    if _ignores_the_wal(src_url):
        print("refusing an immutable source: SQLite then never reads the write-ahead "
              "log, and rows committed since the last checkpoint would be left out "
              "of the copy", file=sys.stderr)
        return 2
    src = create_engine(src_url)
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
    counts: dict[str, tuple[int, ...]] = {}
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

    # The source counted again on a connection of its own. Comparing only the
    # rows read with the rows written cannot see a row the read never reached,
    # and that is how an immutable open's missing WAL rows reported MATCH. It
    # also catches a row committed to the source during the copy.
    src.dispose()
    fresh = create_engine(src_url)
    with fresh.connect() as s:
        now_have = set(inspect(s).get_table_names())
        for t in tables:
            counts[t.name] += (s.execute(select(func.count()).select_from(t)).scalar() or 0,)
    fresh.dispose()
    unread = sorted(t.name for t in S.metadata.sorted_tables
                    if t.name in now_have and t.name not in have)

    bad = {k: v for k, v in counts.items() if len(set(v)) > 1}
    total = sum(v[0] for v in counts.values())
    print(f"copied {total:,} rows in {time.perf_counter() - t0:.0f} s; counts "
          f"{'MATCH' if not bad else f'DIFFER (read, written, source now): {bad}'}")
    if unread:
        print(f"tables on the source that the copy did not see: {', '.join(unread)}")

    if nuls:
        print(f"{nuls} text value(s) held a NUL, which PostgreSQL cannot store: "
              f"written with U+2400 in its place")
    ok = not bad and not unread
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
