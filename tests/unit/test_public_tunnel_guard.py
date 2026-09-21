"""Public tunnel mode must never combine with the local auth bypass."""
from __future__ import annotations

import pytest

from saakshya.api.deps import AppState


def test_public_tunnel_with_auth_disabled_refuses_to_boot(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_PUBLIC_TUNNEL", "1")
    monkeypatch.setenv("SAAKSHYA_REQUIRE_AUTH", "0")
    with pytest.raises(RuntimeError, match="SAAKSHYA_PUBLIC_TUNNEL"):
        AppState(f"sqlite:///{tmp_path / 'guard.db'}", evidence_root=tmp_path / "evidence")


def test_public_tunnel_with_auth_required_boots_normally(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAKSHYA_PUBLIC_TUNNEL", "1")
    monkeypatch.setenv("SAAKSHYA_REQUIRE_AUTH", "1")
    state = AppState(f"sqlite:///{tmp_path / 'ok.db'}", evidence_root=tmp_path / "evidence")
    assert state.require_auth is True
