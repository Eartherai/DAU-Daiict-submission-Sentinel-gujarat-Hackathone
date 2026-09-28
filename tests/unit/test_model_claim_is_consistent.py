"""All three submitted surfaces state the same integration model.

Evaluation area 7 scores "completeness, accessibility, and consistency of all
required documents, videos, reports, links, credentials and supporting
technical information". An assessor reads the deck, then the HLD, then opens
the workspace. Before this test they got three different answers:

    deck  "Hybrid of Models 1 + 2 + 3. Model 4 is rejected."
    HLD   "Hybrid of Models 1 + 2 + 3 with a selected-camera Model 4
           central analytics proof-of-concept."
    UI    "hybrid Models 1+2+3+4 (selective central analytics) + 5
           (adaptive media)"

The UI's was the worst of the three: the challenge defines four reference
models plus a hybrid option, so a Model 5 is not a stronger claim, it is
evidence of not having read the problem statement.

The deck's was the second worst, because it was needlessly modest. Its own
Model 4 page already argued that "every functional outcome Model 4 lists is
present ... the transport is what differs" — so its headline conceded a
capability the platform demonstrates.

The settled claim is the HLD's, which is both true and the strongest of the
three: Models 1 + 2 + 3 as the architecture, Model 4's analytics on selected
cameras, and Model 4's statewide central *recording* declined on arithmetic.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DECK = (ROOT / "tools/demo/render_submission_deck.py").read_text(encoding="utf-8")
HLD = (ROOT / "docs/HLD.md").read_text(encoding="utf-8")
INDEX = (ROOT / "ui/index.html").read_text(encoding="utf-8")
# The System view's architecture panel is built in script, not in the page, so
# checking index.html alone let "hybrid Models 1+2+3+4+5" ship in app.js.
APP = (ROOT / "ui/app.js").read_text(encoding="utf-8")

SURFACES = {"deck": DECK, "HLD": HLD, "workspace": INDEX, "workspace script": APP}


def test_no_surface_invents_a_model_beyond_the_four_defined() -> None:
    """The portal's Step 2 lists Models 1-4 plus a hybrid option.

    Verified against sentinel.gujarat.gov.in/problems on 22 Sep 2026: "Evaluate
    the four reference models or design a hybrid/innovative architecture",
    with Model 1 tagged MANDATORY MODEL. Step 3's "five reference solution
    models" counts Hybrid/Innovative as the fifth; there is no Model 5.
    """
    for name, text in SURFACES.items():
        for bad in ("Model 5", "1+2+3+4+5", "+ 5 (adaptive media)"):
            assert bad not in text, (
                f"{name} names {bad!r}; the challenge defines four reference "
                "models plus a hybrid option")


def test_every_surface_claims_the_same_hybrid() -> None:
    for name, text in SURFACES.items():
        assert "Models 1 + 2 + 3" in text, (
            f"{name} does not state the hybrid in the settled wording")


def test_no_surface_says_model_4_is_rejected_outright() -> None:
    """Model 4's analytics are demonstrated; only its transport is declined.

    Saying "Model 4 is rejected" gives away a capability we built, and
    contradicts both the HLD and the Intelligence view's own banner.
    """
    for name, text in SURFACES.items():
        for bad in ("Model 4 is rejected",
                    "Model 4 (central VMS) rejected",
                    "Model 4 (central VMS recording) is rejected"):
            assert bad not in text, f"{name} still says {bad!r}"


def test_every_surface_keeps_selected_camera_model_4() -> None:
    for name, text in SURFACES.items():
        lowered = text.lower()
        assert ("selected-camera model 4" in lowered
                or "selected cameras" in lowered
                or "selected-camera" in lowered), (
            f"{name} does not say that Model 4 analytics run on selected "
            "cameras, so the hybrid claim above it is unsupported")


def test_the_arithmetic_behind_declining_central_recording_survives() -> None:
    """Declining a model is only credible with the number that forces it."""
    for name in ("deck", "HLD"):
        text = SURFACES[name]
        assert "160 Gbps" in text, f"{name} lost the ingest arithmetic"
        assert "52 PB" in text, f"{name} lost the retention arithmetic"


def test_the_deck_table_shows_both_halves_of_the_model_4_position() -> None:
    """A table listing only the declined half contradicts its own headline."""
    assert "M4 — Central analytics  (kept, selected cameras)" in DECK
    assert "M4 — Statewide central recording  (declined)" in DECK
