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

#: Numbers are allotted from 0001 to 9999; 0000 is never issued. A recogniser
#: that reads a plate whose digits are smeared - the licensed footage blurs
#: some - fills them with zeros: "MH01EK0000", with three agreeing frames at
#: 0.85, where the number was not visible at all.
_NO_ZERO_NUMBER = "number 0000 is never issued"
#: RTO codes start at 1 (DL3, GJ01). "KA0S2836" is an S read into the RTO.
_NO_ZERO_RTO = "RTO code 0 is never issued"
#: A read refused for one of these has the shape of a mark: it is never
#: published, but it is still a frame's reading of the plate. The vote counts
#: it as disagreement - a 0000 is the recogniser saying the number could not be
#: read - where dropping it would leave the frames that did guess a number
#: looking unanimous.
NEVER_ISSUED: frozenset[str] = frozenset({_NO_ZERO_NUMBER, _NO_ZERO_RTO})


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
        if m.group(3) == "0000":
            return PlateRead(canon, raw, False, "invalid", "BH", _NO_ZERO_NUMBER)
        return PlateRead(canon, raw, True, "bh", "BH", "matches Bharat series format")

    m = _STANDARD.match(canon)
    if not m:
        return PlateRead(canon, raw, False, "invalid", None,
                         "does not match any Indian registration format")

    state = m.group(1)
    if state not in STATE_CODES:
        return PlateRead(canon, raw, False, "invalid", state,
                         f"'{state}' is not a valid state/UT code")
    if m.group(4) == "0000":
        return PlateRead(canon, raw, False, "invalid", state, _NO_ZERO_NUMBER)
    if int(m.group(2)) == 0:
        return PlateRead(canon, raw, False, "invalid", state, _NO_ZERO_RTO)
    return PlateRead(canon, raw, True, "standard", state, "valid standard format")


#: What a glyph must be when its position in the mark forces a digit or a
#: letter. Only unambiguous pairs: "0" in a letter slot could be O, D or Q,
#: so it is not typed at all, and such a read stays invalid.
_AS_DIGIT = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "Z": "2",
             "S": "5", "G": "6", "B": "8"}
#: No 1->I or 0->O: series letters avoid I and O precisely because they are
#: read as 1 and 0, so typing a digit into one would invent an unlikely mark.
_AS_LETTER = {"2": "Z", "5": "S", "6": "G", "8": "B"}


def slot_typed(raw: str, max_forced: int = 2) -> PlateRead:
    """Read a mark against the positions of the Indian format.

    A plate font draws O and 0, I and 1, B and 8 almost alike, and a general
    text recogniser returns "MHO1EA4753" for MH01EA4753. Where the format
    fixes a position's class - the RTO and the last four are digits, the state
    and series are letters - a glyph of the other class is read as its twin.
    That is a reading of the characters, not a repair of the mark: nothing is
    changed that the position does not force, at most ``max_forced`` glyphs
    are typed, a split of the string that needs fewer is always preferred, and
    two different splits needing the same fewest leave the read invalid. What
    was typed is stated in ``reason``, and ``raw`` keeps what the OCR said.
    A valid read is returned untouched.

    A read that types only to a mark never issued ("MHO1EK0000") stays
    invalid, but is returned as that mark with the never-issued reason, as
    "MH01EK0000" itself is: the vote counts both the same way.
    """
    direct = parse(raw)
    canon = normalise(raw)
    if direct.valid or not (8 <= len(canon) <= 11):
        return direct
    best: list[tuple[int, str, list[str]]] = []
    unissued: list[tuple[int, str, list[str]]] = []
    # RTO codes are two digits everywhere but Delhi (DL 1C, DL 3S). Allowing a
    # one-digit RTO elsewhere let "MHOLCT3466" type as MH 0 LCT 3466 with one
    # edit, over the right reading MH 01 CT 3466 with two.
    rtos = (1, 2) if canon[:2] == "DL" else (2,)
    for rto in rtos:
        series = len(canon) - 2 - rto - 4
        if not 0 <= series <= 3:
            continue
        classes = "LL" + "D" * rto + "L" * series + "DDDD"
        out, notes = [], []
        for i, (ch, cls) in enumerate(zip(canon, classes, strict=True)):
            if cls == "D" and not ch.isdigit():
                alt = _AS_DIGIT.get(ch)
            elif cls == "L" and ch.isdigit():
                alt = _AS_LETTER.get(ch)
            else:
                out.append(ch)
                continue
            if alt is None:
                break
            out.append(alt)
            notes.append(f"{ch}->{alt} at {i}")
        else:
            cand = "".join(out)
            if len(notes) <= max_forced:
                typed = parse(cand)
                if typed.valid:
                    best.append((len(notes), cand, notes))
                elif typed.reason in NEVER_ISSUED:
                    unissued.append((len(notes), cand, notes))
    if not best:
        unissued.sort()
        if (unissued and direct.reason not in NEVER_ISSUED
                and len({u[1] for u in unissued if u[0] == unissued[0][0]}) == 1):
            pr = parse(unissued[0][1])
            return PlateRead(pr.canonical, raw, False, "invalid", pr.state_code, pr.reason)
        return direct
    best.sort()
    fewest = [b for b in best if b[0] == best[0][0]]
    if len({b[1] for b in fewest}) > 1:
        return PlateRead(canon, raw, False, "invalid", None,
                         "two readings of the positions fit equally; not typed")
    _, cand, notes = fewest[0]
    pr = parse(cand)
    return PlateRead(pr.canonical, raw, True, pr.scheme, pr.state_code,
                     "position-typed: " + ", ".join(notes))


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


def resemblance(a: str, b: str) -> float:
    """How alike two reads of one plate are, 0..1: one minus their edit
    distance over the longer length.

    The vote uses this, not `agreement`, to decide which readings are the same
    plate read differently. By position, an inserted or dropped character
    shifts everything after it: GJ01AA1234 against GJ01A1234 - a doubled
    letter the recogniser's CTC decode merged - agrees 0.5 and MH11AB1234
    against MH1AB1234 0.3, so neither counted against the other and a 2-2 tie
    was settled by which frame came first. Here each is one edit, 0.9. A
    substitution costs one edit as it costs one position, so every pair that
    agreed by position resembles at least as much. Plates are at most eleven
    characters and this runs once per distinct reading of a track.
    """
    x, y = normalise(a), normalise(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return 1.0 - prev[-1] / max(len(x), len(y))
