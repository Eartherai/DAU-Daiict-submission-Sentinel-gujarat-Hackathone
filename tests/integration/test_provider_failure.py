"""An AI provider that fails must not take the workspace with it.

§44 of the directive: Claude unavailable, Gemini unavailable — core
investigation continues. Before this, an HTTP 401 from the provider propagated
out of the request handler as a **500**. The assistant's dependency became the
application's failure, which is precisely what "no core feature depends on an
external LLM" is meant to rule out.

Found by a security scorecard run, and only because a decoy secret planted to
test for key leakage looked enough like an API key that the provider gateway
selected the external backend — which then failed against the real endpoint.
"""
from __future__ import annotations

import pytest

from saakshya.copilot.backends import RuleBackend, Turn
from saakshya.copilot.orchestrator import Copilot


class Exploding:
    """A provider that is configured, selected, and broken."""

    name = "anthropic"
    available = True

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def complete(self, system, messages, tools):
        self.calls += 1
        raise self.exc


@pytest.fixture
def workspace(tmp_path):
    from saakshya.investigation import CaseService, InvestigationService
    from saakshya.store import Store

    store = Store(f"sqlite:///{tmp_path}/copilot.db")
    store.create_all()
    store.upsert_camera({"camera_id": "cam21", "name": "Dethali Char Rasta",
                         "district": "Ahmedabad"})
    return InvestigationService(store), CaseService(store)


@pytest.fixture
def ctx():
    from saakshya.security import AuthContext, Principal, Role

    return AuthContext(
        principal=Principal(user_id="sup.test", role=Role.SUPERVISOR,
                            districts=()),
        case_id="FIR-TEST/2026", purpose="verifying provider failure degrades")


@pytest.mark.parametrize("exc", [
    RuntimeError("HTTP 401 Unauthorized"),
    TimeoutError("read timed out"),
    ConnectionError("name resolution failed"),
    ValueError("malformed response body"),
])
def test_a_broken_provider_does_not_raise(workspace, ctx, exc):
    service, cases = workspace
    bad = Exploding(exc)
    answer = Copilot(service, cases, backend=bad).ask(ctx, "Where was GJ38BH5815?")
    assert bad.calls >= 1, "the provider was never actually tried"
    assert answer.available is True
    assert answer.text, "an empty answer is not a graceful degradation"


def test_the_question_is_still_answered_from_tools(workspace, ctx):
    service, cases = workspace
    answer = Copilot(service, cases,
                     backend=Exploding(RuntimeError("HTTP 503"))
                     ).ask(ctx, "Where was GJ38BH5815 seen?")
    assert "search_plate" in answer.text or "absence of evidence" in answer.text
    assert answer.grounded


def test_the_failure_is_reported_not_hidden(workspace, ctx):
    """Silently swapping the engine underneath a user is its own dishonesty."""
    service, cases = workspace
    answer = Copilot(service, cases,
                     backend=Exploding(RuntimeError("HTTP 401"))
                     ).ask(ctx, "Where was GJ38BH5815 seen?")
    joined = " ".join(answer.warnings)
    assert "anthropic" in joined
    assert "deterministic rules" in joined
    assert "unaffected" in joined


def test_the_answering_backend_is_named_honestly(workspace, ctx):
    """Reporting the configured backend after falling back would tell a reader
    the answer came from a model when it came from rules."""
    service, cases = workspace
    answer = Copilot(service, cases,
                     backend=Exploding(RuntimeError("HTTP 401"))
                     ).ask(ctx, "Where was GJ38BH5815 seen?")
    assert "fallback" in answer.backend
    assert answer.backend != "anthropic"


def test_the_warning_is_not_repeated_once_per_step(workspace, ctx):
    service, cases = workspace
    answer = Copilot(service, cases,
                     backend=Exploding(RuntimeError("HTTP 401"))
                     ).ask(ctx, "Where was GJ38BH5815 seen?")
    assert len(set(answer.warnings)) == len(answer.warnings)


def test_a_failing_fallback_still_does_not_raise(workspace, ctx, monkeypatch):
    """Belt and braces: if even the rules backend broke, the request must not."""
    service, cases = workspace
    monkeypatch.setattr(RuleBackend, "complete",
                        lambda self, s, m, t: (_ for _ in ()).throw(
                            RuntimeError("fallback is broken too")))
    answer = Copilot(service, cases,
                     backend=Exploding(RuntimeError("HTTP 401"))
                     ).ask(ctx, "Where was GJ38BH5815 seen?")
    assert "unavailable" in answer.text.lower()


def test_a_healthy_provider_is_named_as_itself(workspace, ctx):
    class Fine:
        name = "anthropic"
        available = True

        def complete(self, system, messages, tools):
            return Turn(text="cam21 at 01:26", stop_reason="end")

    service, cases = workspace
    answer = Copilot(service, cases, backend=Fine()).ask(ctx, "anything")
    assert answer.backend == "anthropic"
    # There *is* a warning here, and it is the right one: the model asserted
    # "cam21 at 01:26" with no tool result behind it, and grounding withheld it.
    # What must be absent is any suggestion the provider failed.
    joined = " ".join(answer.warnings)
    assert "provider failed" not in joined
    assert "could not be traced to a tool result" in joined
