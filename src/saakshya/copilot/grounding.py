"""Mechanical grounding verification for copilot answers.

A language model asked about an investigation will, under pressure, produce a
camera that does not exist, a time that was never recorded, or a confidence it
computed itself. Instructing it not to is necessary and not sufficient. So the
answer is checked rather than trusted.

The check is deliberately mechanical and model-independent: extract every
factual token from the answer — camera identifiers, registration marks, evidence
and observation identifiers, timestamps, percentages — and require each one to
appear somewhere in the tool output that was actually returned during this turn.
Anything that does not is reported as ungrounded, and the orchestrator refuses
the answer rather than showing it.

This catches the failure that matters: not a badly worded sentence, but a
specific fabricated fact that an officer might act on. It cannot catch a wrong
*interpretation* of grounded facts, and does not claim to — that is what the
decomposed evidence in the UI is for.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: Identifier shapes, derived from the system's own id conventions rather than
#: from any particular camera name. `C-014` is an example, never a constant.
CAMERA_ID = re.compile(r"\b[A-Z]{1,4}-\d{2,6}\b")
#: Live Gujarat ids are `cam01`…`cam30`, not the synthetic `C-014` shape.
CAMERA_LIVE = re.compile(r"\bCAM\d{1,3}\b")
EVIDENCE_ID = re.compile(r"\b(?:EV|OB|TR|AL|WL)-[A-Za-z0-9]{4,}\b")
#: Indian registration marks: two-letter state, district digits, optional
#: series letters, four digits. Also the BH series.
PLATE = re.compile(r"\b(?:[A-Z]{2}\s?\d{1,2}\s?[A-Z]{0,3}\s?\d{4}"
                   r"|\d{2}\s?BH\s?\d{4}\s?[A-Z]{1,2})\b")
TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?"      # ISO
    r"|\b(?:[01]?\d|2[0-3]):[0-5]\d\b")                    # bare clock time
PERCENT = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
NUMERIC = re.compile(r"\b\d+(?:\.\d+)?\b")
#: A number standing on its own in prose, not a digit run inside an identifier.
#: The lookarounds are the whole point: `\b` treats the "87" in OB01M1EX87ZQ as
#: a word boundary, which is how the substring problem survived a first fix.
_STANDALONE_NUMBER = re.compile(r"(?<![A-Za-z0-9])-?\d+(?:\.\d+)?(?![A-Za-z0-9])")


@dataclass
class GroundingReport:
    grounded: bool = True
    ungrounded: list[dict[str, str]] = field(default_factory=list)
    checked: int = 0
    #: What the answer *did* correctly cite. Useful in the UI as provenance.
    citations: list[str] = field(default_factory=list)

    def add(self, kind: str, value: str) -> None:
        self.grounded = False
        self.ungrounded.append({"kind": kind, "value": value})

    def to_dict(self) -> dict[str, Any]:
        return {"grounded": self.grounded, "tokens_checked": self.checked,
                "ungrounded": self.ungrounded, "citations": self.citations[:40]}


def _corpus(tool_results: list[Any]) -> str:
    """Everything the tools actually returned, as one searchable blob.

    Adequate for *structured* tokens — a camera id, a registration mark, an
    evidence id — because those have a distinctive shape that does not occur by
    accident. It is **not** adequate for bare numbers; see `_numbers`.
    """
    return json.dumps(tool_results, default=str, ensure_ascii=False).upper()


def _numbers(node: Any, out: set[float] | None = None) -> set[float]:
    """Every numeric value the tools actually returned, walked structurally.

    Substring-matching a number against the serialised results is far weaker
    than it looks: "87" occurs inside an identifier, inside an epoch
    microsecond, inside 0.874, inside a timestamp. A fabricated "87%
    probability" was accepted as grounded whenever those two digits happened to
    appear anywhere in the payload — which, with generated identifiers, is
    intermittent. That made the check both unsound and flaky, and the flakiness
    is what exposed it.

    Walking the structure and comparing values means a number is grounded only
    if the tools genuinely produced it.
    """
    if out is None:
        out = set()
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.add(float(node))
    elif isinstance(node, str):
        # Numbers rendered into prose still count — "score 0.79" inside an
        # explanation is real tool output. Digit runs *embedded in an
        # identifier* do not: "87" inside OB01M1EX87ZQ is not a number the tools
        # reported, and treating it as one reintroduces exactly the substring
        # unsoundness this function exists to remove.
        for tok in _STANDALONE_NUMBER.findall(node):
            try:
                out.add(float(tok))
            except ValueError:
                continue
    elif isinstance(node, dict):
        for v in node.values():
            _numbers(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _numbers(v, out)
    return out


def _number_is_grounded(value: float, numbers: set[float],
                        tolerance: float = 1e-6) -> bool:
    """A percentage may legitimately render a 0-1 score, so both forms count."""
    for candidate in (value, value / 100.0):
        for n in numbers:
            if abs(n - candidate) <= tolerance:
                return True
            # Tool output is rounded for display; 0.79 must match a 0.7863
            # score without accepting 0.87.
            if abs(round(n, 2) - round(candidate, 2)) <= tolerance:
                return True
    return False


def _normalise_time(t: str) -> list[str]:
    """A model may write 08:41 for an ISO 2026-09-01T08:41:07+00:00.

    Both forms are accepted as long as the hour and minute appear in the tool
    output; requiring character-identical timestamps would reject correct
    answers, and accepting any digits would defeat the check.
    """
    t = t.strip().replace(" ", "T")
    forms = [t.upper()]
    m = re.search(r"(\d{2}):(\d{2})", t)
    if m:
        forms.append(f"{m.group(1)}:{m.group(2)}")
    return forms


def verify(answer: str, tool_results: list[Any], *,
           known_cameras: set[str] | None = None) -> GroundingReport:
    """Check every factual token in `answer` against `tool_results`."""
    rep = GroundingReport()
    if not answer.strip():
        return rep
    corpus = _corpus(tool_results)
    numbers = _numbers(tool_results)
    upper = answer.upper()

    for pattern in (CAMERA_ID, CAMERA_LIVE):
        for m in pattern.finditer(upper):
            tok = m.group(0)
            # CAMERA_ID already consumed C-014; skip a double-count if both hit.
            if pattern is CAMERA_LIVE and CAMERA_ID.fullmatch(tok):
                continue
            rep.checked += 1
            if tok in corpus:
                rep.citations.append(tok)
                continue
            # A camera that exists but was not returned is still ungrounded: the
            # model has asserted something about it without having looked.
            known = {k.upper() for k in (known_cameras or ())}
            kind = ("camera_not_in_results" if tok in known
                    else "camera_does_not_exist")
            rep.add(kind, tok)

    for pattern, kind in ((EVIDENCE_ID, "identifier"), (PLATE, "registration_mark")):
        for m in pattern.finditer(upper):
            tok = m.group(0)
            rep.checked += 1
            if tok.replace(" ", "") in corpus.replace(" ", ""):
                rep.citations.append(tok)
            else:
                rep.add(kind, tok)

    for m in TIMESTAMP.finditer(upper):
        tok = m.group(0)
        rep.checked += 1
        if any(f in corpus for f in _normalise_time(tok)):
            rep.citations.append(tok)
        else:
            rep.add("timestamp", tok)

    for m in PERCENT.finditer(upper):
        tok = m.group(0)
        rep.checked += 1
        digits = re.sub(r"[^\d.]", "", tok)
        try:
            value = float(digits)
        except ValueError:
            rep.add("statistic", tok)
            continue
        if _number_is_grounded(value, numbers):
            rep.citations.append(tok)
        else:
            rep.add("statistic", tok)

    return rep


#: Phrases the copilot must never produce, whatever the tool output said. These
#: are claims about legal status and certainty that this system is not entitled
#: to make, and no amount of correct grounding would make them acceptable.
FORBIDDEN = (
    "legally admissible",
    "proven to be",
    "confirms that the vehicle was",
    "definitely the same vehicle",
    "guaranteed",
    "100% certain",
    "100% confidence",
)


def check_language(answer: str) -> list[str]:
    lowered = answer.lower()
    return [p for p in FORBIDDEN if p in lowered]


#: Content that arrived from a camera — OCR text, a filename, a scene caption —
#: is data. If it contains something shaped like an instruction, that is an
#: attempted injection and is reported, never followed.
INJECTION_MARKERS = re.compile(
    r"(?i)\b(system\s*:|assistant\s*:|ignore (?:all |the )?previous|"
    r"disregard (?:all |the )?(?:previous|above)|new instructions?|"
    r"you are now|mark this vehicle|authoris(?:e|ed)|authoriz(?:e|ed)|"
    r"grant access|override|reveal the (?:prompt|token|key))\b")


def scan_untrusted(text: str | None) -> list[str]:
    """Return instruction-like fragments found in camera-derived content."""
    if not text:
        return []
    return sorted({m.group(0) for m in INJECTION_MARKERS.finditer(text)})
