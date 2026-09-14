"""Signage read from a camera's own view is recorded, and never overstated.

Three cases, and conflating them misleads an operator:

  * signage that matches the recorded label **corroborates** the position;
  * signage that names somewhere else is a **disagreement** worth a human look;
  * signage on a camera with **no recorded name at all** — several on this grid
    are called nothing but `cam25` — is neither. It is the first evidence of
    where the camera points, and reporting it as "does not match the recorded
    label" asserts a conflict with a label that does not exist.

In no case does a place name on a hoarding become a coordinate.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "read_landmarks", ROOT / "tools" / "live" / "read_landmarks.py")
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)

MODEL = "Qwen/Qwen3-VL-4B-Instruct"


def note(names, corroborates, label):
    return rl.signage_note(
        {"names": names, "corroborates": corroborates, "label": label}, MODEL)


def test_matching_signage_corroborates():
    t = note(["PALDI JUNCTION", "V.S. Hospital"], ["PALDI JUNCTION"],
             "Paldi Circle")
    assert "corroborates" in t
    assert "does not match" not in t


def test_conflicting_signage_is_a_disagreement_not_a_correction():
    t = note(["Madhuram Bypass Road"], [], "Timbavadi Gate")
    assert "does not match the recorded label" in t
    assert "Not corrected automatically" in t
    assert "not a survey" in t


def test_an_unnamed_camera_gets_a_lead_not_a_contradiction():
    t = note(["GRAM PANCHAYAT"], [], "cam25")
    assert "no recorded name" in t
    assert "does not match" not in t, (
        "a camera with no label cannot disagree with one")
    assert "lead" in t


def test_an_empty_label_is_treated_as_unnamed():
    assert "no recorded name" in note(["GRAM PANCHAYAT"], [], "")


def test_every_note_names_the_reader_and_refuses_to_be_a_position():
    for names, hits, label in ((["A Road"], ["A Road"], "A Road"),
                               (["B Road"], [], "C Road"),
                               (["D Road"], [], "cam30")):
        t = note(names, hits, label)
        assert MODEL in t, "the reader must be attributable"
        assert "survey" in t or "corroborates" in t


# ---- the matcher itself ---------------------------------------------------- #
@pytest.mark.parametrize("names,label,site,expected", [
    # Whole-token overlap, which substring matching lost once acronyms were
    # normalised: "O.N.G.C." has no four-letter run to match on.
    (["O.N.G.C. Office BS-103 B1"], "O.N.G.C. Office", "ONGC Office", True),
    # Substring containment, which token overlap loses: the sign runs the
    # words together and shares no whole token with the label.
    (["Suvidhapark"], "Suvidha Park", "Suvidha Park, Paldi", True),
    (["PALDI JUNCTION"], "Paldi Circle", "Paldi Junction", True),
    (["Madhuram Bypass Road"], "Timbavadi Gate", "Timbawadi Gate", False),
    (["Vadla Fatak"], "New Bypass Circle 2", "New bypass", False),
])
def test_matcher_needs_both_tests(names, label, site, expected):
    assert bool(rl.agrees(names, label, site)) is expected


def test_generic_words_alone_never_corroborate():
    """"Hospital" on a board agrees with nothing."""
    assert rl.agrees(["Hospital", "Road", "Junction"], "City Hospital",
                     "Hospital Road") == []
