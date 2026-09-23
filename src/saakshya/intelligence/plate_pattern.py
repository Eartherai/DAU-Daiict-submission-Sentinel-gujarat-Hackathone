"""Partial and wildcard registration-mark queries.

A witness rarely gives a whole plate. "GJ-18, X, six-seven-something", "it
ended four-four", "GJ01, then two letters I didn't catch, then 1234" are the
normal shape of a police enquiry. The search box used to accept only a whole
mark: a fragment such as ``GJ18X67`` was compared against the newest 20,000 of
a million observations with a character-agreement score, found nothing, and
said "No observation matched" — while GJ18X6705 had been read 66 times.

This module turns such a fragment into a query the store can answer exactly:

    GJ18X67         a fragment with no wildcard is a prefix  (GJ18X67*)
    GJ18X67*        ``*`` is any run of characters, including none
    GJ01??1234      ``?`` is exactly one unknown character
    GJ0[18]AB1234   ``[..]`` is one character from a set
    GJ*44, MH12*    several terms separated by commas

and, when the officer allows near matches, lets each written character also
stand for the characters OCR confuses it with (0/O/D/Q, 8/B, 1/I/L …), using
the same confusion table the plate reader's repair suggestions use. Nothing is
edited: a stored mark that matched only through a confusion is labelled so,
character by character, and ranked after exact matches.

The SQL side is a ``LIKE`` pattern plus, where the query starts with written
characters, an index range on the leading literal prefix, so a prefix query
reads a handful of index entries instead of scanning the table. The regular
expression here is then the arbiter: ``LIKE`` over-selects for classes and
confusions, and the regex decides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from saakshya.analytics.plates import CONFUSIONS, parse

#: Characters that make a query a pattern rather than a whole mark.
WILDCARDS = frozenset("*?[")

#: A fragment must pin down at least this many characters. "G*" would return
#: every Gujarat plate in the store; that is a listing, not a search, and it is
#: refused with a message rather than answered with a flood.
MIN_SPECIFIC_CHARS = 3

#: A comma list longer than this is almost certainly a paste of something else.
MAX_TERMS = 12

_SEPARATORS = re.compile(r"[\s\-.·/]+")


class PatternError(ValueError):
    """A query that cannot be turned into a bounded search."""


@dataclass(frozen=True)
class Token:
    #: "lit" one written character, "one" = ?, "run" = *, "class" = [..]
    kind: str
    chars: str = ""


@dataclass
class CharMatch:
    """How one character of a stored mark relates to the query."""

    ch: str
    #: exact | class | confusion | wild
    kind: str
    #: What the query had in this position, when it had something.
    query: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"ch": self.ch, "kind": self.kind, "query": self.query}


@dataclass
class PlateTerm:
    raw: str
    tokens: list[Token] = field(default_factory=list)
    #: True when the officer typed a fragment with no wildcard, and it was read
    #: as "starts with". Said back to them, so the reading is never silent.
    implicit_prefix: bool = False

    # -- description --------------------------------------------------------- #
    @property
    def text(self) -> str:
        out = []
        for t in self.tokens:
            out.append({"lit": t.chars, "one": "?", "run": "*",
                        "class": f"[{t.chars}]"}[t.kind])
        return "".join(out)

    @property
    def unknown_positions(self) -> int:
        return sum(1 for t in self.tokens if t.kind == "one")

    @property
    def specific_chars(self) -> int:
        return sum(1 for t in self.tokens if t.kind in ("lit", "class"))

    def describe(self, near: bool = False) -> str:
        """The query read back in words, e.g. 'GJ01 · ?? · 1234 — 2 unknown'."""
        parts: list[str] = []
        cur = ""
        for t in self.tokens:
            if t.kind == "lit":
                cur += t.chars
                continue
            if cur:
                parts.append(cur)
                cur = ""
            if t.kind == "one":
                if parts and set(parts[-1]) == {"?"}:
                    parts[-1] += "?"
                else:
                    parts.append("?")
            elif t.kind == "run":
                parts.append("*")
            else:
                parts.append(f"[{t.chars}]")
        if cur:
            parts.append(cur)
        bits = [" · ".join(parts)]
        if self.implicit_prefix:
            bits.append("starts with — any ending")
        if self.unknown_positions:
            n = self.unknown_positions
            bits.append(f"{n} unknown position{'s' if n != 1 else ''}")
        if any(t.kind == "run" for t in self.tokens) and not self.implicit_prefix:
            bits.append("* = any run of characters")
        if near:
            bits.append("OCR lookalikes allowed (0/O, 8/B, 1/I …)")
        return " — ".join(bits)

    # -- SQL ----------------------------------------------------------------- #
    def sql_like(self, near: bool = False) -> str:
        """A LIKE pattern that selects a superset of the true matches."""
        out = []
        for t in self.tokens:
            if t.kind == "lit":
                out.append("_" if near and t.chars in CONFUSIONS else t.chars)
            elif t.kind in ("one", "class"):
                out.append("_")
            else:
                out.append("%")
        like = "".join(out)
        # Collapse %% so the pattern stays readable in the audit record.
        while "%%" in like:
            like = like.replace("%%", "%")
        return like

    def literal_prefix(self, near: bool = False) -> str:
        """Leading written characters no wildcard or lookalike can change.

        Used as an index range, which turns a prefix query into a seek.
        """
        out = []
        for t in self.tokens:
            if t.kind != "lit" or (near and t.chars in CONFUSIONS):
                break
            out.append(t.chars)
        return "".join(out)

    # -- matching ------------------------------------------------------------ #
    def _regex(self, near: bool) -> re.Pattern[str]:
        parts = []
        for t in self.tokens:
            if t.kind == "lit":
                alts = {t.chars}
                if near:
                    alts |= set(CONFUSIONS.get(t.chars, ()))
                parts.append("([" + re.escape("".join(sorted(alts))) + "])")
            elif t.kind == "class":
                alts = set(t.chars)
                if near:
                    for c in t.chars:
                        alts |= set(CONFUSIONS.get(c, ()))
                parts.append("([" + re.escape("".join(sorted(alts))) + "])")
            elif t.kind == "one":
                parts.append("([A-Z0-9])")
            else:
                parts.append("([A-Z0-9]*?)")
        return re.compile("^" + "".join(parts) + "$")

    def match(self, plate: str, near: bool = False) -> list[CharMatch] | None:
        """Per-character account of how ``plate`` meets this term, or None."""
        m = self._regex(near).match(plate or "")
        if not m:
            return None
        out: list[CharMatch] = []
        for tok, got in zip(self.tokens, m.groups(), strict=True):
            if tok.kind == "lit":
                out.append(CharMatch(got, "exact" if got == tok.chars
                                     else "confusion", tok.chars))
            elif tok.kind == "class":
                out.append(CharMatch(got, "class" if got in tok.chars
                                     else "confusion", f"[{tok.chars}]"))
            elif tok.kind == "one":
                out.append(CharMatch(got, "wild", "?"))
            else:
                out.extend(CharMatch(c, "wild", "*") for c in got)
        return out


def normalise_query(raw: str) -> str:
    """Upper-case and drop separators, keeping the wildcard syntax."""
    return _SEPARATORS.sub("", (raw or "").upper())


def split_terms(raw: str) -> list[str]:
    return [t for t in (normalise_query(p) for p in (raw or "").split(",")) if t]


def is_pattern(raw: str | None) -> bool:
    """Whether a plate query needs the pattern path rather than exact lookup.

    A whole, format-valid mark is exact. A comma list, anything with a wildcard,
    or a fragment that is not a valid mark is a pattern — a fragment is read as
    "starts with", and the reading is reported back to the officer.
    """
    if not raw:
        return False
    if "," in raw:
        return True
    q = normalise_query(raw)
    if any(c in WILDCARDS for c in q):
        return True
    return not parse(q).valid and len(q) >= 2


def parse_term(raw: str) -> PlateTerm:
    q = normalise_query(raw)
    if not q:
        raise PatternError("empty plate term")
    tokens: list[Token] = []
    i = 0
    while i < len(q):
        c = q[i]
        if c == "*":
            if not tokens or tokens[-1].kind != "run":
                tokens.append(Token("run"))
            i += 1
        elif c == "?":
            tokens.append(Token("one"))
            i += 1
        elif c == "[":
            j = q.find("]", i + 1)
            if j < 0:
                raise PatternError(f"unclosed '[' in {raw!r}")
            chars = "".join(sorted(set(q[i + 1:j])))
            if not chars or not chars.isalnum():
                raise PatternError(
                    f"a [..] set must list letters or digits, e.g. [B8], in {raw!r}")
            tokens.append(Token("class", chars))
            i = j + 1
        elif c.isalnum():
            tokens.append(Token("lit", c))
            i += 1
        else:
            raise PatternError(f"character {c!r} is not allowed in a plate query")

    term = PlateTerm(raw=raw.strip(), tokens=tokens)
    if not any(t.kind in ("one", "run", "class") for t in tokens):
        # A bare fragment: the witness gave the start of the plate.
        term.tokens.append(Token("run"))
        term.implicit_prefix = True
    if term.specific_chars < MIN_SPECIFIC_CHARS:
        raise PatternError(
            f"{raw.strip()!r} pins down fewer than {MIN_SPECIFIC_CHARS} "
            "characters. That would list every plate in the store, not search "
            "for one — add the characters you are sure of.")
    return term


def parse_query(raw: str) -> list[PlateTerm]:
    terms = split_terms(raw)
    if not terms:
        raise PatternError("no plate terms in the query")
    if len(terms) > MAX_TERMS:
        raise PatternError(f"at most {MAX_TERMS} plates may be searched at once")
    return [parse_term(t) for t in terms]


def char_diff(query: str, plate: str) -> list[CharMatch]:
    """Position-by-position comparison of a whole-mark query with a stored mark.

    Used for near matches on a full plate, so the officer sees *which*
    characters differ rather than a percentage.
    """
    out: list[CharMatch] = []
    for i, ch in enumerate(plate or ""):
        q = query[i] if i < len(query) else None
        if q == ch:
            out.append(CharMatch(ch, "exact", q))
        elif q is not None and ch in CONFUSIONS.get(q, ()):
            out.append(CharMatch(ch, "confusion", q))
        else:
            out.append(CharMatch(ch, "wild", q))
    return out
