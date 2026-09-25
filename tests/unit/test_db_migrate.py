"""tools/db/migrate.py copies what the source holds, including its WAL.

Every store the application writes is in WAL mode. Rows committed since the
last checkpoint live only in `<db>-wal` while any connection is open - the API,
an idle job - or after a writer was killed. The tool opened the source
`immutable`, which never reads the WAL: those rows were left out, the count
compared the rows it had read with the rows it had written, and it printed
MATCH and exited 0. The destination here is another SQLite file, so this runs
without a PostgreSQL; tests/postgres covers the same copy into PostgreSQL.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from saakshya.store import Store
from tests.conftest import make_observation

ROOT = Path(__file__).resolve().parents[2]


def _migrate():
    spec = importlib.util.spec_from_file_location("db_migrate", ROOT / "tools/db/migrate.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _count(url: str, table: str) -> int:
    e = create_engine(url)
    try:
        with e.connect() as c:
            return int(c.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
    finally:
        e.dispose()


@pytest.fixture
def live(tmp_path):
    """A store with five observations and an audit entry checkpointed into the
    file, and five more and a second entry still in the WAL: `src` stays open,
    as a running API would."""
    path = tmp_path / "live.db"
    src = Store(f"sqlite:///{path}")
    src.create_all()
    src.upsert_camera({"camera_id": "CAM-1", "district": "Ahmedabad",
                       "lat": 23.0, "lon": 72.5})
    src.add_observations([make_observation("CAM-1", plate="GJ01AB0001", offset_s=i)
                          for i in range(5)])
    src.audit("sup", "search_plate", target="GJ01AB0001", result_count=5)
    with src.engine.connect() as c:
        c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    src.add_observations([make_observation("CAM-1", plate="GJ01AB0002", offset_s=10 + i)
                          for i in range(5)])
    src.audit("sup", "search_plate", target="GJ01AB0002", result_count=5)
    assert (tmp_path / "live.db-wal").stat().st_size > 0
    # The scenario is live: an immutable open sees only the checkpointed half.
    assert _count(f"sqlite:///file:{path}?mode=ro&immutable=1&uri=true",
                  "observations") == 5
    yield path, src
    src.engine.dispose()


def test_rows_still_in_the_wal_are_copied(live, tmp_path, capsys):
    path, _src = live
    dst = tmp_path / "copy.db"
    assert _migrate().main(["--from", str(path), "--to", f"sqlite:///{dst}"]) == 0
    assert "counts MATCH" in capsys.readouterr().out
    copy = Store(f"sqlite:///{dst}")
    assert copy.count_observations() == 10
    assert _count(f"sqlite:///{dst}", "audit_log") == 2
    assert copy.verify_audit_chain() == (True, None)


def test_an_immutable_source_is_refused(live, tmp_path, capsys):
    path, _src = live
    url = f"sqlite:///file:{path}?mode=ro&immutable=1&uri=true"
    assert _migrate().main(["--from", url, "--to", f"sqlite:///{tmp_path / 'c.db'}"]) == 2
    assert "write-ahead log" in capsys.readouterr().err


def test_a_row_committed_during_the_copy_fails_the_count(live, tmp_path, capsys,
                                                         monkeypatch):
    """The source is counted again on its own connection after the copy, so a
    row the copy did not read is reported, whatever the reason."""
    import sqlalchemy

    path, src = live
    real, calls = sqlalchemy.create_engine, []

    def engine_after_a_write(url, *a, **kw):
        calls.append(url)
        if len(calls) == 2:           # the recount: a writer got in first
            src.add_observations([make_observation("CAM-1", plate="GJ01AB0003",
                                                   offset_s=99)])
        return real(url, *a, **kw)

    monkeypatch.setattr(sqlalchemy, "create_engine", engine_after_a_write)
    rc = _migrate().main(["--from", str(path), "--to", f"sqlite:///{tmp_path / 'c.db'}"])
    out = capsys.readouterr().out
    assert rc == 1 and len(calls) == 2
    assert "DIFFER" in out and "'observations': (10, 10, 11)" in out
