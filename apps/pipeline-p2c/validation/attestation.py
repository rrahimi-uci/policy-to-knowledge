"""Surface checks that a clause's numbers and modality are actually in the source.

These are deliberately *surface* checks, and the docs say so: matching the digits
"620" in a cited span does not prove the span means "credit score at least 620".
What they do catch is the failure mode that matters most in practice — a
plausible-looking threshold, deadline or modal verb that the cited text never
contains. The plan's risk register names this exactly: "span/string checks can
still accept semantic errors", mitigated by keeping the claim bounded.

Every check here is deterministic and offline.
"""

from __future__ import annotations

import re
from typing import Iterable

from policy_ir.enums import DataType, Modality
from policy_ir.expressions import Expression, Literal, iter_literals, parse_duration

#: Modal markers, longest first so that "must not" is tested before "must".
_MODALITY_MARKERS: tuple[tuple[Modality, tuple[str, ...]], ...] = (
    (
        Modality.PROHIBITION,
        (
            "must not",
            "shall not",
            "may not",
            "must never",
            "is prohibited",
            "are prohibited",
            "is not permitted",
            "are not permitted",
            "no lender may",
            "cannot",
            "may no longer",
        ),
    ),
    (
        Modality.OBLIGATION,
        (
            "must",
            "shall",
            "is required",
            "are required",
            "required to",
            "is obligated",
            "has a duty",
        ),
    ),
    (
        Modality.PERMISSION,
        ("may", "is permitted", "are permitted", "is allowed", "are allowed", "can"),
    ),
    (
        Modality.RECOMMENDATION,
        ("should", "is recommended", "are recommended", "is encouraged", "best practice"),
    ),
    (
        Modality.DEFINITION,
        ("means", "is defined as", "are defined as", "refers to", "for purposes of"),
    ),
)

#: Prohibition markers that also contain an obligation marker as a substring.
_NEGATED_OBLIGATIONS = ("must not", "shall not", "must never")


def attested_modalities(text: str) -> frozenset[Modality]:
    """Return the modalities the text plausibly expresses.

    "The lender must not charge a fee" contains the substring "must", so a naive
    scan would attest OBLIGATION for a prohibition. Negated obligations are
    therefore stripped before the obligation markers are tested.
    """
    lowered = text.lower()
    found: set[Modality] = set()
    for modality, markers in _MODALITY_MARKERS:
        haystack = lowered
        if modality is Modality.OBLIGATION:
            for negated in _NEGATED_OBLIGATIONS:
                haystack = haystack.replace(negated, " ")
        if modality is Modality.PERMISSION:
            haystack = haystack.replace("may not", " ").replace("cannot", " ")
        if any(marker in haystack for marker in markers):
            found.add(modality)
    return frozenset(found)


#: Cardinal number words that appear in policy prose. Without these, "retained
#: for five years" would fail to attest a ``P1825D`` duration and the gate would
#: refuse a perfectly well-evidenced clause.
_NUMBER_WORDS: dict[int, str] = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy",
    80: "eighty", 90: "ninety", 100: "one hundred",
}


def _number_patterns(value: float) -> tuple[re.Pattern[str], ...]:
    """Build the surface forms a number may legitimately take in policy prose.

    A threshold written ``0.8`` in the IR usually reads "80 percent" or "eighty
    percent" in the source, and ``5000`` reads "$5,000". Recognising those forms
    is what keeps the attestation check from producing false refusals on
    perfectly well-evidenced clauses.
    """
    patterns: list[str] = []

    def add_integer(number: int) -> None:
        plain = str(number)
        patterns.append(rf"\b{re.escape(plain)}\b")
        if len(plain) > 3:
            patterns.append(rf"\b{re.escape(f'{number:,}')}\b")
        word = _NUMBER_WORDS.get(number)
        if word:
            patterns.append(rf"\b{re.escape(word)}\b")

    if value == int(value):
        add_integer(int(value))
    else:
        decimal = repr(value).rstrip("0").rstrip(".")
        patterns.append(re.escape(decimal))

    # Ratios in the IR are frequently percentages in the prose.
    if 0 < value <= 1:
        scaled = value * 100
        if scaled == int(scaled):
            percent = int(scaled)
            forms = [str(percent)]
            word = _NUMBER_WORDS.get(percent)
            if word:
                forms.append(word)
            for form in forms:
                patterns.append(rf"\b{re.escape(form)}\s*(?:%|percent)")
    elif value != int(value):
        scaled = value * 100
        if scaled == int(scaled):
            patterns.append(rf"\b{re.escape(str(int(scaled)))}\s*(?:%|percent)")

    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def number_attested(value: float, text: str) -> bool:
    """True when the number appears in the text in a recognisable form."""
    return any(pattern.search(text) for pattern in _number_patterns(value))


def duration_attested(literal: Literal, text: str) -> bool:
    """True when a duration's magnitude appears in the text.

    Only the count is checked, not the unit word: "10 business days" and "10 days"
    both attest ``P10D``. The unit itself is guarded separately by the calendar
    field and the type checker, which refuse to unify business days with calendar
    days.
    """
    delta = parse_duration(literal.value)
    candidates: list[float] = []
    total_seconds = delta.total_seconds()
    if total_seconds % 86400 == 0:
        days = int(total_seconds // 86400)
        candidates.append(days)
        if days % 7 == 0:
            candidates.append(days // 7)
        if days % 365 == 0:
            candidates.append(days // 365)
        if days % 30 == 0:
            candidates.append(days // 30)
    else:
        if total_seconds % 3600 == 0:
            candidates.append(int(total_seconds // 3600))
        else:
            candidates.append(int(total_seconds // 60))
    return any(number_attested(float(candidate), text) for candidate in candidates)


def date_attested(literal: Literal, text: str) -> bool:
    """True when a date's ISO form or its year appears in the text.

    Deliberately loose: policy prose writes dates in many formats, and a strict
    matcher would produce false refusals. The year is the part that a fabricated
    date almost always gets wrong.
    """
    raw = str(literal.value)
    if raw in text:
        return True
    year = raw[:4]
    return bool(re.search(rf"\b{re.escape(year)}\b", text))


def unattested_literals(
    expressions: Iterable[Expression | None], text: str
) -> tuple[Literal, ...]:
    """Return literals whose value cannot be found in the supporting text.

    Only numbers, durations and dates are checked. String and boolean literals are
    skipped: a coded value like ``"primary_residence"`` is a normalised token that
    legitimately differs from the words in the source.
    """
    missing: list[Literal] = []
    for expression in expressions:
        if expression is None:
            continue
        for literal in iter_literals(expression):
            if literal.type is DataType.NUMBER:
                if not number_attested(float(literal.value), text):
                    missing.append(literal)
            elif literal.type is DataType.DURATION:
                if not duration_attested(literal, text):
                    missing.append(literal)
            elif literal.type in (DataType.DATE, DataType.DATE_TIME):
                if not date_attested(literal, text):
                    missing.append(literal)
    return tuple(missing)
