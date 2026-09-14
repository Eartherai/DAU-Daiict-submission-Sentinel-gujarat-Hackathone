"""Government integration: what is promised must be what a camera can do.

The challenge names five systems and six alert categories. Listing all eleven is
easy; the useful work is saying which a *camera* can trigger. Three of the six
need face recognition this system deliberately does not perform, and one needs a
fingerprint no camera captures. A platform claiming all six would be claiming
something physically impossible.
"""
from __future__ import annotations

import pytest

from saakshya.watchlist.government import (
    BY_NAME,
    CATEGORIES,
    CONTRACTS,
    GovernmentSource,
    Keyed,
    SourceUnavailable,
    readiness,
)


def test_all_five_named_systems_are_covered():
    assert {c.name for c in CONTRACTS} == {"VAHAN", "SARATHI", "eGujCop",
                                           "AFIS", "NAFIS"}


def test_all_six_named_categories_are_covered():
    assert len(CATEGORIES) == 6


def test_only_vehicle_keyed_records_can_raise_a_camera_alert():
    for c in CATEGORIES:
        assert c.cctv_actionable is (c.keyed is Keyed.VEHICLE), c.name


def test_fingerprint_sources_are_never_cctv_actionable():
    """No camera on any estate captures a fingerprint."""
    for name in ("AFIS", "NAFIS"):
        assert BY_NAME[name].keyed is Keyed.FINGERPRINT
        assert not BY_NAME[name].cctv_actionable


def test_face_keyed_categories_are_not_actionable():
    """This system does not perform face recognition — a recorded decision,
    not a missing feature."""
    face = [c for c in CATEGORIES if c.keyed is Keyed.FACE]
    assert face, "the face-keyed categories should be present and excluded"
    assert not any(c.cctv_actionable for c in face)


def test_vahan_and_egujcop_are_the_actionable_sources():
    actionable = {c.name for c in CONTRACTS if c.cctv_actionable}
    assert actionable == {"VAHAN", "eGujCop"}


# ---- the adapters refuse rather than pretend --------------------------------- #
def test_an_unconfigured_source_raises_rather_than_returning_nothing():
    """An empty list is indistinguishable from a working integration over an
    empty registry, and would let a demonstration show one that does not exist."""
    src = GovernmentSource(BY_NAME["VAHAN"])
    assert not src.configured
    with pytest.raises(SourceUnavailable, match="not connected"):
        src.fetch()


def test_the_refusal_names_what_is_missing():
    """An integration conversation should start from a list, not a demand."""
    src = GovernmentSource(BY_NAME["eGujCop"])
    with pytest.raises(SourceUnavailable) as e:
        src.fetch()
    for need in BY_NAME["eGujCop"].requires:
        assert need in str(e.value)


def test_an_endpoint_without_a_client_still_refuses(monkeypatch):
    """Configuration is not implementation."""
    monkeypatch.setenv("TEST_CRED", "x")
    src = GovernmentSource(BY_NAME["VAHAN"], endpoint="https://example.invalid",
                           credential_env="TEST_CRED")
    assert src.configured
    with pytest.raises(SourceUnavailable, match="no client implementation"):
        src.fetch()


def test_representative_records_are_labelled_as_such():
    src = GovernmentSource(BY_NAME["VAHAN"])
    out = src.load_representative([
        {"registration_mark": "GJ01AB1234", "status": "STOLEN"}])
    assert out[0]["provenance"] == "REPRESENTATIVE"
    assert out[0]["source"] == "VAHAN"


def test_representative_records_must_carry_the_key_field():
    src = GovernmentSource(BY_NAME["VAHAN"])
    with pytest.raises(ValueError, match="registration_mark"):
        src.load_representative([{"colour": "white"}])


# ---- the readiness statement -------------------------------------------------- #
def test_readiness_reports_nothing_connected():
    r = readiness()
    assert r["connected"] == []
    assert "No government system is connected" in r["note"]


def test_readiness_splits_the_categories_honestly():
    r = readiness()
    assert set(r["actionable_from_cctv"]) == {"stolen_vehicle",
                                              "vehicle_of_interest"}
    assert len(r["not_actionable_from_cctv"]) == 4


def test_every_source_states_what_it_needs():
    for c in CONTRACTS:
        assert c.requires, f"{c.name} claims to need nothing"
        assert c.refresh, f"{c.name} does not say how it would stay current"
