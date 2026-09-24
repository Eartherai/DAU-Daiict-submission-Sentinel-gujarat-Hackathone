"""Reading a plate against the positions of the Indian format.

A general text recogniser returns "MHO1EA2753": an O where the RTO must be a
digit. Where a position forces a class, the glyph is read as its twin - and
nothing else is changed. Each case below was read off the Mumbai footage.
"""
from __future__ import annotations

import pytest

from saakshya.analytics.anpr import AnprConfig, AnprEngine, PlateVoter, RawRead
from saakshya.analytics.plates import slot_typed


@pytest.mark.parametrize("raw, want, typed", [
    ("MHO1EA4753", "MH01EA4753", "O->0 at 2"),
    ("MH478L0485", "MH47BL0485", "8->B at 4"),
    ("MHOLCT3466", "MH01CT3466", "L->1 at 3"),      # two-digit RTO, not MH 0 LCT
    ("MHO2F65664", "MH02FG5664", "6->G at 5"),
])
def test_forced_positions_are_typed_and_said(raw, want, typed) -> None:
    pr = slot_typed(raw)
    assert pr.valid and pr.canonical == want
    assert typed in pr.reason and pr.raw == raw


@pytest.mark.parametrize("raw", [
    "MH02F13523",      # 1 in a series slot: series letters avoid I, so not typed
    "MH02005005",      # 0 in a series slot could be O, D or Q
    "NHODEC8350",      # no state NH; M/N is not a position-forced confusion
])
def test_what_the_positions_do_not_force_stays_invalid(raw) -> None:
    assert not slot_typed(raw).valid


def test_a_valid_read_is_returned_untouched() -> None:
    pr = slot_typed("GJ05AB1234")
    assert pr.canonical == "GJ05AB1234" and pr.reason == "valid standard format"


def test_delhi_keeps_its_one_digit_rto() -> None:
    assert slot_typed("DL3CAB1234").canonical == "DL3CAB1234"


def test_the_vote_reads_through_the_positions() -> None:
    v = PlateVoter(AnprConfig())
    v.add("T1", [RawRead("MHO2EZ1785", 0.9, (0, 0, 10, 5), 0.9, 0.0),
                 RawRead("MH02EZ1785", 0.9, (0, 0, 10, 5), 0.9, 0.1)])
    best = v.resolve("T1")
    assert best is not None and best.plate.canonical == "MH02EZ1785" and best.votes == 2


def test_the_portable_ocr_can_be_forced(monkeypatch) -> None:
    class Fake:
        name = "fake-onnx"
    monkeypatch.setenv("SAAKSHYA_OCR", "onnx")
    eng = AnprEngine(AnprConfig(), backend=Fake())
    assert eng.ocr_backend is eng.backend


def test_number_0000_is_never_a_mark() -> None:
    # A plate whose digits are blurred came back as MH01EK0000, three frames
    # agreeing at 0.85. No registration is numbered 0000.
    from saakshya.analytics.plates import parse
    for mark in ("MH01EK0000", "GJ050000", "22BH0000A"):
        r = parse(mark)
        assert not r.valid and "0000" in r.reason, mark
        assert not slot_typed(mark).valid, mark
    assert parse("MH01EK0001").valid and parse("22BH0001A").valid


def test_rto_zero_is_never_a_mark() -> None:
    from saakshya.analytics.plates import parse
    for mark in ("KA0S2836", "GJ00AB1234"):
        assert not parse(mark).valid, mark
    assert parse("DL3CAB1234").valid and parse("GJ01AB1234").valid
