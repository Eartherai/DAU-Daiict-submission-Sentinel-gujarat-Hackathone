"""India Standard Time, for everything a person reads.

The store keeps UTC and should: it is unambiguous and every clock comparison in
the pipeline depends on it. But officers read times in IST, and the interface
printed the UTC value with its offset stripped — '2026-09-20 04:11:27' beside a
masthead clock reading '08:30 IST'. A sighting at 09:41 in the morning read as
04:11, five and a half hours out, in a document meant to be a movement history.

So there is one rule: anything rendered for a person is IST and says so, and
the UTC value travels beside it (a column, a title attribute) rather than being
thrown away. IST has had no daylight saving since 1945, so a fixed +05:30 offset
is exact and needs no timezone database on the deployment host.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30), "IST")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: An ISO-8601 timestamp with a time part, as the API and the store emit them.
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
                  r"(Z|[+-]\d{2}:?\d{2})?$")


def parse_instant(value: Any) -> datetime | None:
    """A datetime, an ISO string or epoch microseconds, as an aware datetime.

    A naive value is read as UTC, because that is what this store writes; the
    alternative — reading it as local time — silently shifts it by the host's
    offset, which is the very error this module exists to remove.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        # Microseconds since the epoch is the store's integer form.
        dt = datetime.fromtimestamp(float(value) / 1e6, UTC)
    else:
        s = str(value).strip()
        if not _ISO.match(s):
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def to_ist(value: Any) -> datetime | None:
    dt = parse_instant(value)
    return dt.astimezone(IST) if dt else None


def fmt_ist(value: Any, *, date: bool = True, seconds: bool = True) -> str:
    """'21 Sep 2026 16:13:01 IST'. An absent time is an em dash, never 'now'."""
    t = to_ist(value)
    if t is None:
        return "—"
    clock = t.strftime("%H:%M:%S" if seconds else "%H:%M")
    if not date:
        return f"{clock} IST"
    return f"{t.day:02d} {_MONTHS[t.month - 1]} {t.year} {clock} IST"


def iso_ist(value: Any) -> str:
    """ISO-8601 with the +05:30 offset — for machine readers of a CSV."""
    t = to_ist(value)
    return t.isoformat(timespec="seconds") if t else ""


def iso_utc(value: Any) -> str:
    dt = parse_instant(value)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z") if dt else ""


def annotate_ist(node: Any) -> Any:
    """Add a `<key>_ist` beside every ISO timestamp in a nested result.

    Used on copilot tool results. The language model was handed UTC strings
    and, told nothing else, repeated them as '04:11:27 UTC' while the screen
    beside it showed IST. Converting time zones is arithmetic a model gets
    wrong often enough to matter; giving it the IST string to quote does not
    depend on it. The grounding check reads the same annotated result, so a
    quoted IST time is checked against a value the system produced.
    """
    if isinstance(node, dict):
        out: dict[Any, Any] = {}
        for k, v in node.items():
            out[k] = annotate_ist(v)
            if (isinstance(k, str) and isinstance(v, str) and not k.endswith("_ist")
                    and f"{k}_ist" not in node and _ISO.match(v.strip())):
                out[f"{k}_ist"] = fmt_ist(v)
        return out
    if isinstance(node, list):
        return [annotate_ist(v) for v in node]
    return node
