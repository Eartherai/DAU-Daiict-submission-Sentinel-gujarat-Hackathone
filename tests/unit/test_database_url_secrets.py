"""A PostgreSQL URL carries a password; nothing this platform shows may.

The URL reached people four ways: /config served the text after the last
slash of it, which for a URL with no database path is `user:password@host`;
redacted() masked the user part and left `?password=` alone; the perf and
live tools printed or wrote it past redacted(); and the API handed it to the
AI worker on the command line, where `ps -axww` shows it to every account on
the host. The secret below is made up, and every test looks for it verbatim.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saakshya.analytics import worker
from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.security import Role
from saakshya.store.provenance import redacted, refuses_live_writes, store_name

ROOT = Path(__file__).resolve().parents[2]
SECRET = "S3cretPW-not-real"  # secret-test: a made-up password to look for

# Every form libpq and SQLAlchemy's psycopg dialect accept a password in.
PG_URLS = [
    f"postgresql+psycopg://saakshya:{SECRET}@127.0.0.1:5544/saakshya",
    f"postgresql+psycopg://saakshya:{SECRET}@127.0.0.1:5544",
    f"postgresql+psycopg://saakshya:{SECRET}@127.0.0.1:5544/",
    f"postgresql+psycopg://saakshya:{SECRET}@127.0.0.1:5544/?sslmode=disable",
    f"postgresql+psycopg://saakshya:{SECRET}@127.0.0.1:5544?dbname=saakshya",
    f"postgresql+psycopg://saakshya@127.0.0.1:5544/saakshya?password={SECRET}",
    f"postgresql+psycopg:///saakshya?host=127.0.0.1&password={SECRET}",
    f"postgresql+psycopg://saakshya@127.0.0.1/saakshya?sslpassword={SECRET}",
    # Not parseable (the port is not a number): nothing of it may come back.
    f"postgresql+psycopg://saakshya:{SECRET}@127.0.0.1:port/saakshya",
]


@pytest.mark.parametrize("url", PG_URLS)
def test_no_url_form_puts_the_password_in_a_store_name_or_a_redacted_url(url):
    assert SECRET not in store_name(url)
    assert SECRET not in redacted(url)


@pytest.mark.parametrize("url,expected", [
    (PG_URLS[0], "saakshya"),
    (PG_URLS[1], "postgresql"),      # no database named: libpq's default
    (PG_URLS[4], "saakshya"),
    (PG_URLS[6], "saakshya"),
    ("sqlite:///var/demo.db", "demo.db"),
    ("sqlite:////abs/var/live.db", "live.db"),
    ("sqlite:///file:/abs/var/demo.db?mode=ro&immutable=1&uri=true", "demo.db"),
])
def test_the_store_name_is_the_database_and_nothing_else(url, expected):
    assert store_name(url) == expected


def test_the_provenance_guard_still_reads_sqlite_file_names():
    assert refuses_live_writes("sqlite:///var/demo.db")
    assert not refuses_live_writes(PG_URLS[0])


def test_redacted_keeps_what_an_operator_needs_to_recognise_the_store():
    assert redacted(PG_URLS[0]) == "postgresql+psycopg://saakshya:***@127.0.0.1:5544/saakshya"
    assert redacted(PG_URLS[5]) == (
        "postgresql+psycopg://saakshya@127.0.0.1:5544/saakshya?password=***")
    assert redacted("sqlite:///var/live.db") == "sqlite:///var/live.db"


def test_config_never_serves_the_password_to_a_signed_in_role(tmp_path):
    state = AppState(f"sqlite:///{tmp_path / 'cfg.db'}",
                     evidence_root=tmp_path / "evidence")
    state.require_auth = True
    state.tokens.upsert_user("op.cfg", Role.OPERATOR, districts=("Ahmedabad",))
    token = state.tokens.mint("op.cfg")
    client = TestClient(create_app(state))
    for url in PG_URLS:
        # /config reads only the URL's text; the open store stays SQLite.
        state.db_url = url
        r = client.get("/config", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert SECRET not in r.text, url


def _spawn(monkeypatch, tmp_path, url):
    seen = {}

    class FakePopen:
        pid = 4242

        def __init__(self, cmd, **kw):
            seen["cmd"], seen["env"] = cmd, kw["env"]

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SAAKSHYA_AI_WORKER", "1")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(worker, "RUN", tmp_path / "var" / "run")
    monkeypatch.setattr("subprocess.Popen", FakePopen)
    worker.boot_ai_worker(url, cameras=["CAM-1"])
    return seen


def test_the_ai_worker_gets_the_store_url_in_its_environment_not_its_argv(
        monkeypatch, tmp_path):
    seen = _spawn(monkeypatch, tmp_path, PG_URLS[0])
    assert not any(SECRET in part for part in seen["cmd"])
    assert "--db" not in seen["cmd"]
    assert seen["env"]["SAAKSHYA_DB"] == PG_URLS[0]


def test_the_worker_reads_that_url_and_still_takes_an_explicit_db(monkeypatch):
    chosen = []

    class FakeWorker:
        def __init__(self, db_url, cameras):
            chosen.append(db_url)

        def run(self):
            return 0

    monkeypatch.setattr(worker, "Worker", FakeWorker)
    monkeypatch.setenv("SAAKSHYA_DB", PG_URLS[0])
    assert worker.main(["--cameras", "CAM-1"]) == 0
    assert worker.main(["--db", "sqlite:///var/other.db", "--cameras", "CAM-1"]) == 0
    assert chosen == [PG_URLS[0], "sqlite:///var/other.db"]


def test_the_collection_report_masks_the_store_url():
    from tests.unit.test_live_collection import a_report

    report = a_report(db_url=PG_URLS[5])
    assert SECRET not in str(report)
    assert report["store"].endswith("?password=***")


# --------------------------------------------------------------------------- #
# Every tool that prints or writes a database URL sends it through redacted().
# --------------------------------------------------------------------------- #
TOOLS = sorted([*(ROOT / "tools" / "perf").glob("*.py"),
                *(ROOT / "tools" / "live").glob("*.py")])


def _bare_db_url(node: ast.expr) -> bool:
    """`args.db` or `db_url` itself, not wrapped in redacted() or store_name()."""
    return ((isinstance(node, ast.Attribute) and node.attr == "db")
            or (isinstance(node, ast.Name) and node.id in {"db_url", "db"}))


def _shown(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue):
            yield node.value
        elif isinstance(node, ast.Dict):
            yield from (v for v in node.values if v is not None)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "print"):
            yield from node.args


@pytest.mark.parametrize("path", TOOLS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_tool_prints_or_reports_a_bare_database_url(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bare = [n.lineno for n in _shown(tree) if _bare_db_url(n)]
    assert not bare, f"{path.name} shows the database URL unmasked at lines {bare}"
