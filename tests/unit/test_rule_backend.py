"""The copilot answers without a language model, or says why it cannot.

The assistant's opening line promises "I can search, trace and explain — using
the same engine as the workspace". With no API key configured that promise was
empty: it declined every question, including ones the deterministic tools could
answer completely. The rule backend keeps the promise for question shapes that
map onto a tool call, and declines the rest as plainly as before.

It runs inside the same orchestrator as the LLM path, so the grounding check,
tool-call budget and prompt-injection scan all still apply.
"""
from __future__ import annotations

import json

import pytest

from saakshya.copilot.backends import (
    RuleBackend,
    UnavailableBackend,
    default_backend,
)

TOOLS = [{"name": n} for n in (
    "search_plate", "search_vehicle", "get_camera_context",
    "get_camera_neighbors", "get_camera_capability", "build_trajectory",
    "validate_trajectory", "query_watchlist", "get_evidence",
    "verify_evidence", "explain_match", "draft_report")]


def plan(question: str) -> list[str]:
    turn = RuleBackend().complete("", [{"role": "user", "content": question}], TOOLS)
    return [c.name for c in turn.tool_calls]


@pytest.mark.parametrize("question,expected", [
    ("Where was GJ38BH5815 seen?", "search_plate"),
    ("Trace the route of GJ 38 BH 5815", "build_trajectory"),
    ("Is GJ21T4831 on the watchlist?", "query_watchlist"),
    ("Why does GJ38BH5815 match?", "explain_match"),
    ("Draft a report for GJ38BH5815", "draft_report"),
    ("Can cam21 read plates?", "get_camera_capability"),
    ("What is cam01?", "get_camera_context"),
    ("Which cameras are next to cam04?", "get_camera_neighbors"),
])
def test_question_shapes_reach_the_right_tool(question, expected):
    assert expected in plan(question)


def test_spaced_and_hyphenated_marks_are_normalised():
    turn = RuleBackend().complete(
        "", [{"role": "user", "content": "find GJ 38 BH 5815 please"}], TOOLS)
    assert turn.tool_calls[0].arguments["plate"] == "GJ38BH5815"


def test_a_question_with_no_handle_is_declined_plainly():
    turn = RuleBackend().complete("", [{"role": "user", "content": "Tell me a joke"}], TOOLS)
    assert not turn.tool_calls
    assert "registration mark" in turn.text
    assert "SAAKSHYA_LLM_KEY" in turn.text


def test_it_never_plans_a_tool_the_deployment_does_not_offer():
    """A restricted registry must not be worked around."""
    turn = RuleBackend().complete(
        "", [{"role": "user", "content": "Where was GJ38BH5815 seen?"}],
        [{"name": "get_camera_context"}])
    assert [c.name for c in turn.tool_calls] == []


def _with_results(question, pairs):
    msgs = [{"role": "user", "content": question}]
    use, res = [], []
    for i, (name, payload) in enumerate(pairs):
        use.append({"type": "tool_use", "id": f"t{i}", "name": name, "input": {}})
        res.append({"type": "tool_result", "tool_use_id": f"t{i}",
                    "content": json.dumps(payload)})
    msgs.append({"role": "assistant", "content": use})
    msgs.append({"role": "user", "content": res})
    return RuleBackend().complete("", msgs, TOOLS).text


def test_the_answer_states_that_no_model_was_used():
    text = _with_results("Where was GJ38BH5815?", [
        ("search_plate", {"result_count": 1, "candidates": [
            {"camera_id": "cam21", "status": "CONFIRMED_BY_PLATE",
             "t_norm": "2026-09-02T01:26:22Z", "observation_quality": 0.96}]})])
    assert "no language model was involved" in text
    assert "no data left this deployment" in text


def test_an_empty_search_is_not_reported_as_absence_of_the_vehicle():
    text = _with_results("Where was GJ00XX0000?",
                         [("search_plate", {"result_count": 0, "candidates": []})])
    assert "absence of evidence" in text
    assert "not evidence the vehicle was absent" in text


def test_a_truncated_result_is_not_partially_trusted():
    msgs = [{"role": "user", "content": "Where was GJ38BH5815?"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t0", "name": "search_plate", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t0",
                 "content": '{"result_count": 4, "candidates": [{"camera_id"'}]}]
    text = RuleBackend().complete("", msgs, TOOLS).text
    assert "truncated" in text
    assert "4" not in text            # nothing read out of a broken fragment


def test_a_refusal_is_reported_as_a_refusal():
    text = _with_results("Where was GJ38BH5815?",
                         [("search_plate", {"refused": True, "reason": "out of jurisdiction"})])
    assert "refused" in text and "out of jurisdiction" in text


def test_trajectory_score_is_never_called_a_probability():
    text = _with_results("Trace GJ38BH5815", [
        ("build_trajectory", {"hypotheses": [
            {"status": "CONFIRMED", "score": 0.767, "legs": []}]})])
    assert "not a probability" in text


def test_copilot_can_be_switched_off_for_a_deployment(monkeypatch):
    monkeypatch.setenv("SAAKSHYA_COPILOT", "off")
    assert isinstance(default_backend(), UnavailableBackend)


def test_rules_are_the_default_when_no_key_is_set(monkeypatch):
    monkeypatch.delenv("SAAKSHYA_LLM_KEY", raising=False)
    monkeypatch.delenv("SAAKSHYA_COPILOT", raising=False)
    assert isinstance(default_backend(), RuleBackend)
