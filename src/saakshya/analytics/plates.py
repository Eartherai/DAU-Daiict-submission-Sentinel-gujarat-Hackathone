"""Indian registration mark normalisation and validation.

A plate read is not a string — it is a claim about a registration mark, and most
OCR errors on Indian plates are *structurally impossible* marks. Rejecting those
cheaply is worth more than a better OCR model, because it converts a confident
wrong answer into an honest no-answer.

Formats handled
---------------
Standard (BharatSeries excluded)::

    <2 letters state> <1-2 digits RTO> <1-3 letters series> <4 digits>
    GJ 05 AB 1234    GJ05AB1234    GJ-05-AB-1234    GJ05A1234    GJ051234

Bharat (BH) series, introduced for vehicles moving between states::

    <2 digits year> BH <4 digits> <1-2 letters>
    22BH1234A       22BH1234AA

Both are normalised to a compact canonical form with no separators, which is
what gets indexed and compared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Valid Indian state / UT registration prefixes. An OCR result whose first two
#: characters are not in this set is almost certainly a misread, and this is one
#: of the cheapest, highest-yield rejections available.
STATE_CODES: frozenset[str] = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
    "UP", "WB",
})

#: Characters that OCR confuses on plates, in both directions. Used only to
#: *suggest* repairs when a read is one substitution away from valid — never
#: applied silently.
CONFUSIONS: dict[str, tuple[str, ...]] = {
    "0": ("O", "D", "Q"), "O": ("0", "D", "Q"),
    "1": ("I", "L"), "I": ("1", "L"), "L": ("1", "I"),
    "2": ("Z",), "Z": ("2",),
    "5": ("S",), "S": ("5",),
    "8": ("B",), "B": ("8",),
    "6": ("G",), "G": ("6",),
}

_STANDARD = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{4})$")
_BH = re.compile(r"^(\d{2})(BH)(\d{4})([A-Z]{1,2})$")
_STRIP = re.compile(r"[^A-Z0-9]")


@dataclass(frozen=True, slots=True)
class PlateRead:
    """A normalised registration mark plus why we believe it."""

    canonical: str
    raw: str
    valid: bool
    scheme: str          # "standard" | "bh" | "invalid"
    state_code: str | None
    reason: str

    @property
    def display(self) -> str:
        """Human-facing spaced form, e.g. 'GJ 05 AB 1234'."""
        if not self.valid:
            return self.raw
        m = _STANDARD.match(self.canonical)
        if m:
            return " ".join(p for p in m.groups() if p)
        m = _BH.match(self.canonical)
        if m:
            return " ".join(m.groups())
        return self.canonical


def normalise(raw: str) -> str:
    """Strip separators, upper-case, drop OCR padding characters."""
    return _STRIP.sub("", (raw or "").upper().replace("_", ""))


def parse(raw: str) -> PlateRead:
    """Parse and validate. Never raises; an unparseable read is a result."""
    canon = normalise(raw)
    if not canon:
        return PlateRead("", raw, False, "invalid", None, "empty after normalisation")
    if not (6 <= len(canon) <= 11):
        return PlateRead(canon, raw, False, "invalid", None,
                         f"implausible length {len(canon)}")

    m = _BH.match(canon)
    if m:
        return PlateRead(canon, raw, True, "bh", "BH", "matches Bharat series format")

    m = _STANDARD.match(canon)
    if not m:
        return PlateRead(canon, raw, False, "invalid", None,
                         "does not match any Indian registration format")

    state = m.group(1)
    if state not in STATE_CODES:
        return PlateRead(canon, raw, False, "invalid", state,
                         f"'{state}' is not a valid state/UT code")
    return PlateRead(canon, raw, True, "standard", state, "valid standard format")


def repair_candidates(raw: str, max_edits: int = 1) -> list[PlateRead]:
    """Plates that are within ``max_edits`` OCR confusions of being valid.

    Returned as *candidates for an operator to consider*, never applied
    automatically. A silently repaired plate is a fabricated observation.
    """
    canon = normalise(raw)
    out: dict[str, PlateRead] = {}
    if max_edits < 1:
        return []
    for i, ch in enumerate(canon):
        for alt in CONFUSIONS.get(ch, ()):
            cand = canon[:i] + alt + canon[i + 1:]
            pr = parse(cand)
            if pr.valid and pr.canonical not in out:
                out[pr.canonical] = PlateRead(
                    pr.canonical, raw, True, pr.scheme, pr.state_code,
                    f"one-character repair {ch}->{alt} at position {i}",
                )
    return list(out.values())


def lookalikes(raw: str | None, *, exclude: str | None = None,
               limit: int = 6) -> list[dict[str, str]]:
    """Format-valid marks one OCR confusion from ``raw``, excluding ``exclude``.

    Returned for an operator to consider. Never applied to the stored read.
    If ``raw`` already parses to the published mark, nothing is offered —
    listing lookalikes next to a confirmed plate would undermine a vote.
    """
    if not raw:
        return []
    parsed = parse(raw)
    published = parse(exclude) if exclude else None
    if (parsed.valid and published is not None and published.valid
            and parsed.canonical == published.canonical):
        return []
    skip = {parsed.canonical, published.canonical if published else ""}
    skip.discard("")
    out: list[dict[str, str]] = []
    for pr in repair_candidates(raw):
        if pr.canonical in skip:
            continue
        skip.add(pr.canonical)
        out.append({"canonical": pr.canonical, "display": pr.display,
                    "reason": pr.reason})
        if len(out) >= limit:
            break
    return out


def agreement(a: str, b: str) -> float:
    """Character-level agreement between two normalised reads, 0..1.

    Used for fuzzy plate search and for deciding whether two reads of the same
    vehicle corroborate each other.
    """
    x, y = normalise(a), normalise(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    n = max(len(x), len(y))
    # Simple positional agreement with length penalty; adequate at plate lengths
    # and far cheaper than edit distance in the hot retrieval path.
    same = sum(1 for i in range(min(len(x), len(y))) if x[i] == y[i])
    return same / n
