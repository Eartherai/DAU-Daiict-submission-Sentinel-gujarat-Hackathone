"""The proposal answers Step 3's cybersecurity-architecture dimension.

Step 3 lists "Cybersecurity Architecture" among the dimensions every solution
must cover, Step 6 asks for cybersecurity controls beside backup and disaster
recovery, and Model 4's named deliverables include a security architecture
document.

`docs/SECURITY.md` answered the application half well — four authorisation
gates, purpose binding, a hash-chained audit — and its section 8 honestly
listed encryption at rest, rate limiting and mTLS as absent, each marked a
"deployment concern". What it never said was what the deployment should do
instead, and the HLD scored zero mentions of segmentation, TLS, encryption at
rest or key management. An admission of missing controls is not an
architecture.

These tests pin coverage rather than prose, so the section cannot quietly lose
a dimension an assessor is scoring.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HLD = (ROOT / "docs/HLD.md").read_text(encoding="utf-8")
SECURITY = (ROOT / "docs/SECURITY.md").read_text(encoding="utf-8")

SECTION = HLD[HLD.index("## 18. Cybersecurity architecture"):
              HLD.index("## 19. What this proposal will not say")]


def test_the_section_exists_and_is_substantive() -> None:
    assert len(SECTION) > 3000, "the cybersecurity section is a stub"


def test_every_dimension_step_three_and_six_name_is_covered() -> None:
    for term in ("segmentation", "TLS", "at rest", "key", "rate limit"):
        assert re.search(term, SECTION, re.I), (
            f"the cybersecurity architecture never mentions {term!r}")


def test_controls_separate_what_is_built_from_what_is_required() -> None:
    """The distinction is the whole value of the section.

    A prototype claiming enterprise controls it does not run is worth less
    than one that says which is which, because only the second can be
    deployed against.
    """
    assert "**IMPLEMENTED**" in SECTION
    assert "**SPECIFIED**" in SECTION
    assert SECTION.count("SPECIFIED") >= 8, (
        "too few controls are marked as deployment requirements; the section "
        "reads as though this build performs them")


def test_it_does_not_claim_encryption_this_build_does_not_perform() -> None:
    """SECURITY.md section 8 says there is none; the two must agree."""
    assert "No encryption at rest" in SECURITY
    at_rest = SECTION[SECTION.index("### 18.3"):SECTION.index("### 18.4")]
    assert "**SPECIFIED**" in at_rest
    assert "IMPLEMENTED**\n" not in at_rest.replace("Hash **IMPLEMENTED**", ""), (
        "the at-rest table claims an implemented encryption control")


def test_the_cleartext_camera_leg_is_admitted_not_papered_over() -> None:
    """Much of the estate speaks RTSP without transport security.

    Claiming end-to-end encryption across cameras of this age would be false,
    and an assessor who has run a police network will know it.
    """
    assert "cleartext" in SECTION.lower()
    assert "VLAN" in SECTION


def test_the_unkeyed_audit_chain_limit_is_stated() -> None:
    """A chain stored in the database it protects is detection, not prevention."""
    low = SECTION.lower()
    assert "unkeyed" in low or "append-only" in low
    assert "notaris" in low or "outside the system" in low, (
        "the section does not say what would make the chain survivable")


def test_security_md_points_at_the_deployment_architecture() -> None:
    """Otherwise a reader stops at 'what is not done' and concludes nothing is."""
    assert "§18" in SECURITY and "HLD" in SECURITY
