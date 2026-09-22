"""The HLD must cover what Step 6 asks participants to explain.

Step 6 lists seven topics. Six were covered; disaster recovery existed only as
a table row, a statewide rollout plan existed only as a capability roadmap, and
cost was explicitly NOT ESTIMATED. Those are now sections 15-17.

These tests check the document answers each topic, not that it contains a
keyword — a proposal can say "disaster recovery" once in a table and answer
nothing.
"""

import re
from pathlib import Path

import pytest

HLD = Path(__file__).resolve().parents[2] / "docs" / "HLD.md"


@pytest.fixture(scope="module")
def doc() -> str:
    return HLD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def headings(doc: str) -> list[str]:
    return [ln.strip() for ln in doc.splitlines() if ln.startswith("## ")]


def test_disaster_recovery_has_its_own_section(headings):
    assert any("disaster recovery" in h.lower() for h in headings), headings


def test_disaster_recovery_names_what_survives_what(doc):
    section = doc.split("## 15.", 1)[1].split("## 16.", 1)[0]
    for failure in ("Centre unreachable", "District node lost",
                    "Evidence tampering"):
        assert failure in section, failure
    # Objectives must be shaped, not invented.
    assert "RPO" in section and "RTO" in section


def test_rollout_plan_is_phased_with_exit_gates(doc):
    section = doc.split("## 16.", 1)[1].split("## 17.", 1)[0]
    assert "Exit gate" in section
    for phase in ("PoC", "First district", "Statewide"):
        assert phase in section, phase


def test_cost_model_exposes_its_assumptions(doc):
    section = doc.split("## 17.", 1)[1].split("## 18.", 1)[0]
    # The one measured input, and the unknown that dominates the model.
    assert "11.4" in section
    assert "gpu_speedup_factor" in section
    assert "must be benchmarked" in section


def test_cost_model_refuses_to_quote_a_price_it_cannot_support(doc):
    """No rupee figure, and the unknown is named with a way to resolve it.

    This asserted one sentence verbatim, which broke the moment the section
    was rewritten to solve the model across a range of GPU speedups instead of
    stopping at the free variable. The property it was protecting is the one
    worth pinning: the model may publish node counts derived from measurement,
    and may not publish a price it has no basis for.
    """
    section = doc.split("## 17.", 1)[1].split("## 18.", 1)[0]
    flat = " ".join(section.split())
    assert not re.search(r"(₹|Rs\.?\s?\d|INR\s?\d|crore|lakh)", flat, re.I), (
        "the cost model quotes a currency figure it cannot support")
    assert "UNKNOWN" in flat, "the honest status of the speedup factor was dropped"
    assert "benchmark" in flat.lower(), (
        "an unknown with no stated way to resolve it is just an unknown")


def test_section_12_no_longer_contradicts_the_new_sections(doc):
    """It used to read NOT ESTIMATED for cost and UNTESTED-only for DR."""
    table = doc.split("## 12.", 1)[1].split("## 13.", 1)[0]
    assert "§17" in table, "the cost row must point at the model"
    assert "§15" in table, "the DR row must point at the design"


def test_the_proposal_still_states_what_it_will_not_claim(headings, doc):
    """Adding sections must not quietly drop the discipline."""
    assert any("will not say" in h.lower() for h in headings)
    # Split on the heading's name rather than its number: adding a section
    # renumbers everything after it, and this passed by luck once already.
    tail = doc.split("What this proposal will not say", 1)[1]
    assert "Not tested at 80,000 cameras." in tail
