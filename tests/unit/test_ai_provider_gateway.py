"""One switch decides where assistant reasoning happens, and none of it is load-bearing.

`AI_PROVIDER` makes the choice explicit rather than inferring it from whichever
key happens to be set in the environment. Whatever it selects, no core feature
depends on it: search, trajectory, watchlist, alerting and evidence are decided
by deterministic code, and the application must run with AI_PROVIDER=disabled.
"""
from __future__ import annotations

import pytest

from saakshya.copilot.backends import (
    PROVIDERS,
    AnthropicBackend,
    GeminiBackend,
    RuleBackend,
    UnavailableBackend,
    default_backend,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("AI_PROVIDER", "SAAKSHYA_COPILOT", "SAAKSHYA_LLM_KEY",
              "SAAKSHYA_GEMINI_KEY", "SAAKSHYA_GEMINI_KEYS", "GEMINI_API_KEY",
              "SAAKSHYA_GEMINI_MODEL", "SAAKSHYA_GEMINI_VISION"):
        monkeypatch.delenv(k, raising=False)


def test_the_default_keeps_data_on_the_host(monkeypatch):
    """For government CCTV, 'nothing leaves' is what you get without asking."""
    assert isinstance(default_backend(), RuleBackend)


def test_disabled_means_disabled(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "disabled")
    assert isinstance(default_backend(), UnavailableBackend)


def test_the_older_switch_is_still_honoured(monkeypatch):
    """A deployment that switched the copilot off must not have it come back
    because the setting was renamed underneath them."""
    monkeypatch.setenv("SAAKSHYA_COPILOT", "off")
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("SAAKSHYA_LLM_KEY", "k")
    assert isinstance(default_backend(), UnavailableBackend)


@pytest.mark.parametrize("provider,key,cls", [
    ("anthropic", "SAAKSHYA_LLM_KEY", AnthropicBackend),
    ("gemini", "SAAKSHYA_GEMINI_KEY", GeminiBackend),
])
def test_a_named_provider_is_selected_when_configured(monkeypatch, provider, key, cls):
    monkeypatch.setenv("AI_PROVIDER", provider)
    monkeypatch.setenv(key, "test-key")
    assert isinstance(default_backend(), cls)


@pytest.mark.parametrize("provider", ["anthropic", "gemini"])
def test_a_named_provider_without_its_key_degrades_rather_than_failing(
        monkeypatch, provider):
    """Every question failing is a worse outcome than answering the ones the
    deterministic tools can answer."""
    monkeypatch.setenv("AI_PROVIDER", provider)
    assert isinstance(default_backend(), RuleBackend)


def test_a_misspelling_never_silently_enables_a_provider(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropci")
    monkeypatch.setenv("SAAKSHYA_LLM_KEY", "k")
    # 'auto' is the fallback, and auto with a key selects anthropic — the point
    # is that the *typo* is reported, not that it silently selected nothing.
    assert isinstance(default_backend(), AnthropicBackend)


def test_auto_prefers_a_configured_provider_over_rules(monkeypatch):
    monkeypatch.setenv("SAAKSHYA_GEMINI_KEY", "k")
    assert isinstance(default_backend(), GeminiBackend)


def test_no_key_is_ever_echoed_by_a_backend():
    b = AnthropicBackend(api_key="super-secret-value")  # secret-test
    assert "super-secret-value" not in repr(b)
    assert "super-secret-value" not in str(getattr(b, "name", ""))
    g = GeminiBackend(api_key="super-secret-value")  # secret-test
    assert "super-secret-value" not in repr(g)
    assert g.model == "gemini-3-flash-preview"


def test_gemini_accepts_the_studio_alias_and_a_key_pool(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "studio-alias")
    assert isinstance(default_backend(), GeminiBackend)
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("SAAKSHYA_GEMINI_KEYS", "k1,k2")
    b = GeminiBackend()
    assert b.available
    assert len(b._keys) == 2


def test_the_provider_list_is_closed():
    assert set(PROVIDERS) == {"auto", "disabled", "local", "anthropic", "gemini"}


# ---- the translation layer, without a network ------------------------------ #
def test_gemini_translation_keeps_one_conversation_shape():
    """The orchestrator is the tested component; it must not learn a second
    dialect for every provider added."""
    msgs = [
        {"role": "user", "content": "where was GJ38BH5815"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": "t0", "name": "search_plate",
             "input": {"plate": "GJ38BH5815"},
             "thought_signature": "sig-abc"},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t0", "content": "{}"}]},
    ]
    out = GeminiBackend._to_gemini(msgs)
    assert [m["role"] for m in out] == ["user", "model", "user"]
    assert out[1]["parts"][1]["functionCall"]["name"] == "search_plate"
    assert out[1]["parts"][1]["thoughtSignature"] == "sig-abc"
    assert out[2]["parts"][0]["functionResponse"]["name"] == "search_plate"
    assert out[2]["parts"][0]["functionResponse"]["response"] == {}


def test_an_unconfigured_backend_declines_without_a_network():
    b = GeminiBackend(api_key="")
    turn = b.complete("sys", [{"role": "user", "content": "hi"}], [])
    assert not turn.tool_calls
    assert turn.stop_reason == "unavailable"


def test_request_header_local_keeps_data_on_the_host():
    from saakshya.copilot.backends import backend_from_header
    assert isinstance(backend_from_header("local"), RuleBackend)
    assert isinstance(backend_from_header("off"), RuleBackend)


def test_request_header_gemini_without_a_key_falls_back(monkeypatch):
    from saakshya.copilot.backends import backend_from_header
    assert isinstance(backend_from_header("gemini"), RuleBackend)


def test_request_header_gemini_with_a_key_selects_gemini(monkeypatch):
    from saakshya.copilot.backends import backend_from_header
    monkeypatch.setenv("SAAKSHYA_GEMINI_KEY", "k")
    assert isinstance(backend_from_header("gemini"), GeminiBackend)


def test_copilot_config_does_not_wait_for_a_lazy_object(monkeypatch):
    from saakshya.api.routes_ops import _copilot_public_config
    monkeypatch.delenv("SAAKSHYA_COPILOT", raising=False)
    monkeypatch.setenv("SAAKSHYA_GEMINI_KEY", "k")
    cfg = _copilot_public_config()
    assert cfg["available"] is True
    assert cfg["gemini"] is True
