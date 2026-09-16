from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_checker():
    path = Path(__file__).parents[2] / "tools" / "pre_demo_check.py"
    spec = importlib.util.spec_from_file_location("pre_demo_check", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_live_configuration_is_warning_not_ready(monkeypatch, tmp_path):
    checker = load_checker()
    monkeypatch.delenv("SAAKSHYA_WHEP_BASE", raising=False)
    monkeypatch.delenv("SENTINEL_GRID_EMAIL", raising=False)
    monkeypatch.delenv("SENTINEL_GRID_PASSWORD", raising=False)
    finding = next(c for c in checker.check(tmp_path) if c.category == "stream gateway")
    assert finding.status == "WARNING"
    assert "unavailable" in finding.detail


def test_core_artifacts_and_readable_database_are_ready(tmp_path, monkeypatch):
    checker = load_checker()
    (tmp_path / "src/saakshya/api").mkdir(parents=True)
    (tmp_path / "src/saakshya/api/app.py").touch()
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui/index.html").touch()
    (tmp_path / "var").mkdir()
    (tmp_path / "var/saakshya.db").touch()
    monkeypatch.setenv("SAAKSHYA_DB", "sqlite:///var/saakshya.db")
    finding = next(c for c in checker.check(tmp_path) if c.category == "database")
    assert finding.status == "READY"


def test_missing_required_artifact_is_blocker(tmp_path):
    checker = load_checker()
    finding = next(c for c in checker.check(tmp_path) if c.category == "backend")
    assert finding.status == "BLOCKER"
