"""IST everywhere a person reads a time.

The interface sliced ISO strings: 10:43:01 UTC was printed as '10:43:01' beside
a masthead clock reading 16:13 IST, and alert cards carried no date at all.
These tests pin the replacement — one Asia/Kolkata formatter that says IST and
keeps a date — in the browser code and in the server helpers the reports and
the copilot share.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from saakshya.common.ist import annotate_ist, fmt_ist, iso_ist, parse_instant
from tests.unit.s3_js import lift, run_node

FORMATTERS = ("IST_FMT", "IST_MONTHS", "istUtcByText", "rememberIst",
              "istInstant", "istParts", "fmtDay", "istAge",
              "fmtTime", "fmtClock", "fmtAlertClock")


def _js(expr: str, *, tz: str = "UTC") -> object:
    return run_node(lift(*FORMATTERS) + f"\nconsole.log(JSON.stringify({expr}));",
                    tz=tz)


# --------------------------------------------------------------------------- #
# Browser formatters
# --------------------------------------------------------------------------- #
def test_fmt_time_converts_utc_to_ist_and_says_so():
    # The exact observation from the finding: 10:43:01 UTC is 16:13:01 IST.
    assert _js('fmtTime("2026-09-21T10:43:01.764049+00:00")') == \
        "21 Sep 2026 16:13:01 IST"
    assert _js('fmtTime("2026-09-21T10:43:01Z")') == "21 Sep 2026 16:13:01 IST"


def test_fmt_time_is_pinned_to_kolkata_not_the_browser_zone():
    """A laptop set to New York must print the same evidence as one in Surat."""
    for tz in ("UTC", "America/New_York", "Asia/Tokyo"):
        assert _js('fmtTime("2026-09-21T10:43:01Z")', tz=tz) == \
            "21 Sep 2026 16:13:01 IST", tz


def test_crossing_midnight_moves_the_date():
    # 20:00 UTC on the 21st is 01:30 IST on the 22nd; slicing kept the 21st.
    assert _js('fmtTime("2026-09-21T20:00:00Z")') == "22 Sep 2026 01:30:00 IST"


def test_a_naive_value_is_read_as_utc():
    assert _js('fmtTime("2026-09-21 10:43:01")') == "21 Sep 2026 16:13:01 IST"


def test_clock_form_keeps_the_date():
    assert _js('fmtClock("2026-09-21T10:43:01Z")') == "21 Sep 16:13:01 IST"


def test_alert_clock_has_date_and_age_for_every_shape_the_api_sends():
    us = int(datetime(2026, 9, 21, 10, 43, 1, tzinfo=UTC).timestamp() * 1e6)
    out = _js("[fmtAlertClock({t_norm: '2026-09-21T10:43:01Z'}),"
              f" fmtAlertClock({{t_norm_us: {us}}}),"
              " fmtAlertClock({when: '2026-09-21T10:43:01Z'}),"
              " fmtAlertClock({}), fmtAlertClock(null)]")
    assert out[0].startswith("21 Sep 16:13:01 IST · ")
    assert out[0].endswith(" d ago")
    assert out[1].startswith("21 Sep 16:13:01 IST")
    assert out[2].startswith("21 Sep 16:13:01 IST")
    assert out[3:] == ["—", "—"]


def test_age_words():
    now = "Date.parse('2026-09-23T10:00:00Z')"
    out = _js(f"[istAge('2026-09-23T09:59:50Z', {now}),"
              f" istAge('2026-09-23T09:46:00Z', {now}),"
              f" istAge('2026-09-23T07:00:00Z', {now}),"
              f" istAge('2026-09-21T09:00:00Z', {now})]")
    assert out == ["just now", "14 min ago", "3 h ago", "2 d ago"]


def test_absent_and_unparseable_values_are_not_turned_into_times():
    assert _js('[fmtTime(null), fmtTime(""), fmtTime("pending"), fmtClock(undefined)]') \
        == ["—", "—", "pending", "—"]


def test_a_bare_date_is_a_day_not_midnight_utc():
    assert _js('[fmtTime("2026-09-21"), fmtDay("2026-09-21T20:00:00Z")]') == \
        ["21 Sep 2026", "22 Sep 2026"]


def test_formatted_value_remembers_its_utc_instant_for_the_title():
    out = _js('(() => { const s = fmtTime("2026-09-21T10:43:01.5Z");'
              ' return [s, istUtcByText.get(s)]; })()')
    assert out == ["21 Sep 2026 16:13:01 IST", "2026-09-21T10:43:01.500Z"]


def test_no_formatter_slices_the_iso_string_any_more():
    """The bug was string slicing; its signature must not come back."""
    src = lift("fmtTime", "fmtClock", "fmtAlertClock")
    assert "slice(11, 19)" not in src
    assert 'replace("T", " ")' not in src
    assert "toISOString().slice" not in src


# --------------------------------------------------------------------------- #
# Server helpers (reports, copilot)
# --------------------------------------------------------------------------- #
def test_server_formatter_matches_the_browser():
    assert fmt_ist("2026-09-21T10:43:01.764049+00:00") == "21 Sep 2026 16:13:01 IST"
    assert fmt_ist(datetime(2026, 9, 21, 20, 0, tzinfo=UTC)) == "22 Sep 2026 01:30:00 IST"
    assert fmt_ist("2026-09-21T10:43:01Z", date=False) == "16:13:01 IST"
    assert fmt_ist(None) == "—"
    assert iso_ist("2026-09-21T10:43:01Z") == "2026-09-21T16:13:01+05:30"


def test_microseconds_and_naive_values():
    us = int(datetime(2026, 9, 21, 10, 43, 1, tzinfo=UTC).timestamp() * 1e6)
    assert fmt_ist(us) == "21 Sep 2026 16:13:01 IST"
    assert parse_instant("2026-09-21 10:43:01") == datetime(2026, 9, 21, 10, 43, 1,
                                                            tzinfo=UTC)
    assert parse_instant("not a time") is None


def test_annotate_ist_adds_a_twin_beside_every_timestamp():
    src = {"t_norm": "2026-09-21T10:43:01Z", "plate": "GJ99ZZ0001",
           "candidates": [{"t_norm": "2026-09-21T20:00:00+00:00", "score": 1}],
           "count": 3, "note": "2026-09-21 is a date in prose, not a timestamp"}
    out = annotate_ist(src)
    assert out["t_norm_ist"] == "21 Sep 2026 16:13:01 IST"
    assert out["candidates"][0]["t_norm_ist"] == "22 Sep 2026 01:30:00 IST"
    assert "plate_ist" not in out and "note_ist" not in out
    # The original values are untouched: grounding still sees the UTC form.
    assert out["t_norm"] == src["t_norm"]
    json.dumps(out)
