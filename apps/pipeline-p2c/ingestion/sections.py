"""Recovering section structure from extracted policy text.

A section path is what makes a citation readable ("SOP 50 10 8, Ch. 1" beats
"characters 106321–107238") and it is what cross-reference resolution matches
against. It is *not* provenance — the document hash and the character offsets are —
so a missed heading degrades readability, never correctness.

The patterns are structural rather than domain-specific: legal and regulatory
drafting conventions (``§ 1016.5(a)``, ``Section 4.2``, ``Chapter 3``, ``Part II``,
``Appendix V``) recur across every regulated industry. Nothing here names an
industry, and the domain-agnostic test enforces that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Heading forms, tried in order. Each must anchor at the start of a line so that a
#: mid-sentence cross-reference ("see § 1016.8") is not mistaken for a heading.
_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("section_symbol", re.compile(r"^\s*(§+\s*[\d]+(?:\.[\d]+)*(?:\([a-z0-9]+\))*)", re.M)),
    ("section_word", re.compile(r"^\s*(Section\s+[\dA-Z]+(?:[.\-][\dA-Za-z]+)*)", re.M)),
    ("chapter", re.compile(r"^\s*(Chapter\s+[\dIVXLC]+(?:[.\-][\dA-Za-z]+)*)", re.M | re.I)),
    ("chapter_short", re.compile(r"^\s*(Ch\.\s*[\dIVXLC]+(?:[.\-][\dA-Za-z]+)*)", re.M)),
    ("part", re.compile(r"^\s*(Part\s+[\dIVXLC]+)", re.M)),
    ("appendix", re.compile(r"^\s*(Appendix\s+[\dA-Z]+)", re.M)),
    ("subpart", re.compile(r"^\s*(Subpart\s+[\dA-Z]+(?:[\dA-Za-z\-]*))", re.M)),
    ("numbered", re.compile(r"^\s*(\d+\.\d+(?:\.\d+)*)\s+[A-Z]", re.M)),
)


@dataclass(frozen=True)
class Heading:
    """A heading found in canonical text, with the offset it starts at."""

    label: str
    char_start: int
    kind: str

    def normalised(self) -> str:
        """Collapse internal whitespace so the label is stable and comparable."""
        return re.sub(r"\s+", " ", self.label).strip()


def find_headings(text: str) -> tuple[Heading, ...]:
    """Find headings in ``text``, ordered by position and de-duplicated by offset.

    When two patterns match at the same offset the earlier pattern wins, which is why
    the table above is ordered from most to least specific.
    """
    found: dict[int, Heading] = {}
    for kind, pattern in _HEADING_PATTERNS:
        for match in pattern.finditer(text):
            start = match.start(1)
            if start not in found:
                found[start] = Heading(match.group(1), start, kind)
    return tuple(found[key] for key in sorted(found))


def section_at(headings: tuple[Heading, ...], offset: int) -> str:
    """The label of the innermost heading at or before ``offset``.

    Returns an empty string when the offset precedes every heading — front matter is
    real and should not be mislabelled as belonging to the first section.
    """
    label = ""
    for heading in headings:
        if heading.char_start > offset:
            break
        label = heading.normalised()
    return label


@dataclass(frozen=True)
class Segment:
    """A span of canonical text belonging to one section."""

    char_start: int
    char_end: int
    section_path: str

    @property
    def length(self) -> int:
        return self.char_end - self.char_start



#: How much of the budget may be given up to reach whitespace. A long run of
#: non-whitespace (a table of figures, a URL) must not be able to shrink a chunk
#: arbitrarily, so past this the hard cut stands and the boundary stays where it was.
_SNAP_FRACTION = 0.1


def _snap_to_whitespace(text: str, stop: int, limit: int, budget: int) -> int:
    """Move ``stop`` back to just after the last whitespace before it.

    Returns ``stop`` unchanged at the end of the section, or when no whitespace lies
    within the allowance — a boundary is better placed badly than a chunk left short.
    The allowance is a fraction of the chunk *budget*, not of the absolute offset, so it
    behaves the same at the start of a document as at the end.
    """
    if stop >= limit:
        return limit
    if stop <= 0 or stop >= len(text):
        return stop
    if text[stop].isspace() or text[stop - 1].isspace():
        return stop
    floor = max(0, stop - max(1, int(_SNAP_FRACTION * budget)))
    index = stop
    while index > floor:
        if text[index - 1].isspace():
            return index
        index -= 1
    return stop


def segment_by_section(
    text: str, *, min_length: int = 1, max_length: int | None = None
) -> tuple[Segment, ...]:
    """Split text into one segment per heading, optionally capping segment length.

    ``max_length`` splits an over-long section into consecutive pieces that keep the
    same section path. Splitting on a character budget rather than on sentences is
    deliberate: the boundary has no semantic meaning, and pretending otherwise would
    make chunking look like structure. Offsets stay absolute either way, so a span is
    unaffected by where the boundaries fall.

    The budget is nevertheless snapped back to whitespace. A hard cut is byte-exact and
    therefore passes every provenance check, but on a real 1,200-page guide it split 58
    of 324 chunks mid-word: the first unit of such a chunk read "al who is not a loan
    applicant", and the sentence straddling the cut was never presented whole to an
    extractor in either chunk, so a requirement could go unextracted purely because of
    where the budget landed. Snapping does not make the boundary semantic — it only
    stops it falling inside a token.
    """
    headings = find_headings(text)
    boundaries: list[tuple[int, int, str]] = []
    if not headings or headings[0].char_start > 0:
        first_end = headings[0].char_start if headings else len(text)
        if first_end > 0:
            boundaries.append((0, first_end, ""))
    for index, heading in enumerate(headings):
        end = headings[index + 1].char_start if index + 1 < len(headings) else len(text)
        boundaries.append((heading.char_start, end, heading.normalised()))

    segments: list[Segment] = []
    for start, end, label in boundaries:
        if end - start < min_length:
            continue
        if max_length is None or end - start <= max_length:
            segments.append(Segment(start, end, label))
            continue
        cursor = start
        while cursor < end:
            stop = _snap_to_whitespace(
                text, min(cursor + max_length, end), end, max_length
            )
            segments.append(Segment(cursor, stop, label))
            cursor = stop
    return tuple(segments)
