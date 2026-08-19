"""Deterministic, offset-preserving sentence segmentation over canonical text.

Every sentence keeps the absolute character offsets it occupies, because those
offsets are the provenance an extracted clause will cite. A segmenter that returned
strings would force a search to recover the position, and a sentence that recurs
verbatim — boilerplate does — could not then be located unambiguously.

Splitting is conservative. Policy prose is full of terminators that end nothing:
``Ch. 12``, ``§ 1016.5``, ``U.S.C.``, ``No. 4``, ``$5,000.00``, ``e.g.``. Over-splitting
truncates a requirement mid-clause and produces a citation that omits its own
condition, so the rule here is to split only where the evidence for a boundary is
strong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words that end in a period without ending a sentence. Structural and citational
#: rather than domain-specific: these appear in regulatory drafting everywhere.
_ABBREVIATIONS = frozenset(
    {
        "no", "nos", "ch", "chs", "sec", "secs", "art", "arts", "para", "paras",
        "pt", "pts", "app", "apps", "fig", "figs", "cf", "eg", "ie", "etc", "vs",
        "viz", "al", "ibid", "supra", "infra", "seq", "ff",
        "inc", "llc", "llp", "ltd", "co", "corp", "assn", "dept", "div", "bur",
        "mr", "mrs", "ms", "dr", "prof", "jr", "sr", "st",
        "u", "s", "c", "f", "r", "d", "n", "e", "w",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
        "nov", "dec",
        "approx", "est", "max", "min", "avg", "vol", "ed", "eds", "pp", "p",
    }
)

#: A boundary needs a terminator, whitespace, then something that can begin a
#: sentence: a capital, a section symbol, a digit-led enumerator, or a bullet.
_BOUNDARY = re.compile(r"([.;!?])(\s+)(?=[A-Z§(•·]|\d+[.)]\s)")

_TRAILING_TOKEN = re.compile(r"([A-Za-z]+)\.$")
_DECIMAL_TAIL = re.compile(r"\d[.,]$")
_INITIAL_TAIL = re.compile(r"(?:^|[\s(])[A-Za-z]\.$")


@dataclass(frozen=True)
class Sentence:
    """One sentence, with the absolute offsets it occupies in canonical text."""

    char_start: int
    char_end: int
    text: str

    @property
    def length(self) -> int:
        return self.char_end - self.char_start


def _is_real_boundary(prefix: str) -> bool:
    """Decide whether the terminator ending ``prefix`` really ends a sentence."""
    stripped = prefix.rstrip()
    if not stripped:
        return False
    if _DECIMAL_TAIL.search(stripped):
        # "5.5" or "1,000." mid-number
        return False
    if _INITIAL_TAIL.search(stripped):
        # A single letter with a period: "U.", "S.", "A." — part of an initialism.
        return False
    match = _TRAILING_TOKEN.search(stripped)
    if match and match.group(1).lower() in _ABBREVIATIONS:
        return False
    return True


def split_sentences(
    text: str, *, offset: int = 0, min_length: int = 2
) -> tuple[Sentence, ...]:
    """Split ``text`` into sentences, reporting offsets shifted by ``offset``.

    ``offset`` lets a caller segment a chunk's body while still reporting absolute
    document coordinates, which is what every citation needs.
    """
    sentences: list[Sentence] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.end(1)
        if not _is_real_boundary(text[start:end]):
            continue
        body = text[start:end]
        if len(body.strip()) >= min_length:
            sentences.append(_trimmed(body, start, offset))
        start = match.end(2)
    tail = text[start:]
    if len(tail.strip()) >= min_length:
        sentences.append(_trimmed(tail, start, offset))
    return tuple(s for s in sentences if s.length > 0)


def _trimmed(body: str, start: int, offset: int) -> Sentence:
    """Trim surrounding whitespace while keeping offsets exact."""
    leading = len(body) - len(body.lstrip())
    trailing = len(body) - len(body.rstrip())
    begin = start + leading
    finish = start + len(body) - trailing
    return Sentence(offset + begin, offset + finish, body[leading : len(body) - trailing])
