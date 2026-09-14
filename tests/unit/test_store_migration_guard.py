"""A tool that opens a store must migrate it before querying it.

Adding a nullable column to `cameras` broke `tools/perf/query_plans.py` with
`sqlalchemy.exc.OperationalError: no such column: cameras.location_note` — a
raw driver error that names neither the cause nor the cure, raised deep inside a
SELECT, minutes into a release gate.

`create_all()` is the migrator and is additive and idempotent, so the fix is
simply to call it. The failure mode is easy to reintroduce, though: a new tool
opens a store, queries it, and works perfectly against a store that happens to
be current. It breaks only for whoever has an older database — which is
everybody, later.

Note that `pending_migrations()` does not catch this. By contract it reports
only columns that *cannot* be added in place, so a nullable column is invisible
to it: "no pending migrations" does not mean "schema is current".
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = sorted(p for p in (ROOT / "tools").rglob("*.py")
               if not p.name.startswith("_"))


def _opens_a_store(tree: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "Store" for n in ast.walk(tree))


def _migrates(tree: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "create_all" for n in ast.walk(tree))


@pytest.mark.parametrize("path", TOOLS, ids=lambda p: str(p.relative_to(ROOT)))
def test_a_tool_that_opens_a_store_migrates_it(path: Path):
    tree = ast.parse(path.read_text())
    if not _opens_a_store(tree):
        pytest.skip("does not open a store")
    assert _migrates(tree), (
        f"{path.relative_to(ROOT)} constructs a Store but never calls "
        "create_all(). It will work against a current database and fail with "
        "'no such column' against any older one.")


def test_the_guard_can_actually_fail(tmp_path):
    """A guard that cannot fail is not a guard."""
    bad = tmp_path / "bad_tool.py"
    bad.write_text("from saakshya.store import Store\n"
                   "store = Store('sqlite:///x.db')\n"
                   "store.list_cameras()\n")
    tree = ast.parse(bad.read_text())
    assert _opens_a_store(tree)
    assert not _migrates(tree)



# ─── provenance guard ────────────────────────────────────────────────────────
# Live observations must never be written into the demonstration or evaluation
# store. The guard matched a *substring* of the database URL, so
# `var/route_demo.db` — a store that is not the demo store — was refused. A
# guard that fires on names it does not mean gets worked around, and then it
# protects nothing.
#
# The logic now lives in the package and is imported here, rather than being
# re-implemented in the test or asserted against by grepping the tool's source.
from saakshya.store.provenance import (
    PROTECTED_STORES,
    refuses_live_writes,
)


@pytest.mark.parametrize("url,expected", [
    ("sqlite:///var/demo.db", True),
    ("sqlite:////absolute/var/demo.db", True),
    ("sqlite:///var/saakshya.db", True),
    # The false positive that prompted this.
    ("sqlite:///var/route_demo.db", False),
    ("sqlite:///var/live.db", False),
    ("sqlite:///var/demo_of_mine.db", False),
    ("sqlite:///var/my_demo.db", False),
])
def test_the_provenance_guard_matches_the_file_not_a_substring(url, expected):
    assert refuses_live_writes(url) is expected


def test_the_protected_set_is_explicit():
    assert {"demo.db", "saakshya.db"} == PROTECTED_STORES


def test_the_tool_uses_the_package_guard():
    """No second copy of the rule to drift out of step with this one."""
    from pathlib import Path as P
    src = (P(__file__).resolve().parents[2] / "tools" / "live" / "ingest.py").read_text()
    assert "refuses_live_writes(args.db)" in src
