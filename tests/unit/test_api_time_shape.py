"""Times published by the API are ISO-8601, whatever the store holds.

`/alerts` returned `t_norm_us: 1788312382336128` — the raw storage integer —
while every other list endpoint returned ISO-8601. No client could read it, and
because the UI formats a missing time as an em dash rather than failing, an
alert with a perfectly good timestamp simply displayed as having none. A silent
wrong answer, from a field-name mismatch across the boundary.
"""
from __future__ import annotations

import re

from saakshya.api.routes_ops import _US_FIELDS, _with_iso_times

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def test_every_microsecond_field_gains_an_iso_twin():
    row = {f: 1788312382336128 for f in _US_FIELDS}
    out = _with_iso_times(row)
    for f in _US_FIELDS:
        plain = f[:-3]
        assert plain in out, f"{f} published no ISO form"
        assert ISO.match(out[plain]), f"{plain} is not ISO-8601: {out[plain]!r}"


def test_raw_microseconds_are_kept():
    """Clients that want exact integer microseconds must not lose them."""
    out = _with_iso_times({"t_norm_us": 1788312382336128})
    assert out["t_norm_us"] == 1788312382336128


def test_absent_and_null_timestamps_do_not_invent_a_time():
    out = _with_iso_times({"t_norm_us": None, "camera_id": "cam21"})
    assert "t_norm" not in out
    assert out["camera_id"] == "cam21"


def test_conversion_is_correct_not_merely_formatted():
    out = _with_iso_times({"t_norm_us": 1_000_000_000_000_000})
    assert out["t_norm"].startswith("2001-09-09T01:46:40")
