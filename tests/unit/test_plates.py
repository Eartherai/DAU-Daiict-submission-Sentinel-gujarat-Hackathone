"""Registration-mark normalisation and validation."""
from saakshya.analytics.plates import agreement, parse, repair_candidates


def test_separator_forms_normalise_to_one_canonical():
    for raw in ["GJ05AB1234", "GJ-05-AB-1234", "GJ 05 AB 1234", "gj05ab1234", "GJ05AB1234_"]:
        assert parse(raw).canonical == "GJ05AB1234", raw
        assert parse(raw).valid


def test_display_form_is_spaced():
    assert parse("GJ05AB1234").display == "GJ 05 AB 1234"


def test_short_series_variants_are_valid():
    assert parse("GJ05A1234").valid
    assert parse("GJ051234").valid
    assert parse("MH12DE1433").valid


def test_bharat_series():
    p = parse("22BH1234A")
    assert p.valid and p.scheme == "bh"


def test_invalid_state_code_rejected():
    p = parse("ZZ05AB1234")
    assert not p.valid and "not a valid state" in p.reason


def test_structurally_impossible_rejected():
    for bad in ["1A13256", "AM21347", "52", "", "GJ", "GJ05AB12345678"]:
        assert not parse(bad).valid, bad


def test_truncated_read_is_rejected():
    # This is exactly what a 9-slot OCR model produces on a 10-char Indian mark.
    assert not parse("GJ05AB1").valid
    assert not parse("GJ27PQ7").valid


def test_repair_is_offered_not_applied():
    # O/0 confusion in the RTO digits.
    cands = repair_candidates("GJO5AB1234")
    assert any(c.canonical == "GJ05AB1234" for c in cands)
    # The original parse still reports invalid — repairs are never silent.
    assert not parse("GJO5AB1234").valid


def test_lookalikes_are_empty_when_raw_already_matches_the_published_mark():
    from saakshya.analytics.plates import lookalikes
    assert lookalikes("GJ05AB1234", exclude="GJ05AB1234") == []


def test_lookalikes_from_an_invalid_raw_include_the_valid_repair():
    from saakshya.analytics.plates import lookalikes
    got = lookalikes("GJO5AB1234", exclude=None)
    assert any(x["canonical"] == "GJ05AB1234" for x in got)


def test_agreement():
    assert agreement("GJ05AB1234", "GJ05AB1234") == 1.0
    assert agreement("GJ05AB1234", "GJ05AB9999") == 0.6
    assert agreement("GJ05AB1234", "") == 0.0
