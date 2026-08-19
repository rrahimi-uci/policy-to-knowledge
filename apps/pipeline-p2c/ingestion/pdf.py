"""Stage 0/1: turn a PDF into hashed canonical text with real character offsets.

Three decisions shape this module, and each was forced by what the real corpus does.

**Canonical text is the whitespace-normalised extraction, not the raw output.**
PDF extractors wrap lines mid-sentence, so a sentence-level citation cannot be
anchored in the raw text at all — the phrase simply does not occur. Normalising at
ingestion and hashing *that* makes offsets stable and citations readable. Whatever
the parser produced is then immutable, and ``parser_version`` records how it was
produced, because a different extractor is a different canonical text.

**Section detection runs on the line-preserving form, then its offsets are mapped.**
Headings anchor at line starts, which normalisation destroys. So headings are found
first and their offsets translated into canonical coordinates, rather than keeping two
texts with two coordinate systems.

**Pages that yield no text are recorded, not skipped.** 21 pages across the committed
corpus are scanned images. A corpus that silently drops them looks fully processed
when it is not, so each becomes a zero-length chunk with ``extraction_failed`` in the
coverage ledger — countable, attributable to a page, and impossible to mistake for
content.

``pypdf`` is an optional dependency. The compiler proper stays pure standard library;
only this module needs it, and it says so clearly when it is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from policy_ir.models import Chunk, CoverageEntry, DocumentArtifact

from .registry import SourceRegistry
from .sections import Heading, find_headings, section_at

#: Bumped whenever normalisation changes, because the canonical text — and therefore
#: every offset and hash derived from it — changes with it.
NORMALIZER_VERSION = "normalize-1"

_SPACES = re.compile(r"[ \t\f\v ]+")
_LINE_BREAKS = re.compile(r"\s*\n\s*")


class PdfSupportUnavailable(RuntimeError):
    """Raised when PDF ingestion is attempted without ``pypdf`` installed."""


def _require_pypdf():
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PdfSupportUnavailable(
            "PDF ingestion needs the optional 'pypdf' dependency: pip install pypdf "
            "(or install requirements-dev.txt). The compiler itself needs no "
            "third-party packages."
        ) from exc
    return pypdf


def parser_version() -> str:
    """The extractor identity recorded on every ingested document."""
    pypdf = _require_pypdf()
    return f"pypdf-{pypdf.__version__}+{NORMALIZER_VERSION}"


@dataclass(frozen=True)
class PageText:
    """One page's raw extraction."""

    number: int
    text: str

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


def extract_pages(path: Path) -> tuple[PageText, ...]:
    """Extract each page's text in document order."""
    pypdf = _require_pypdf()
    reader = pypdf.PdfReader(str(path))
    return tuple(
        PageText(number=index + 1, text=page.extract_text() or "")
        for index, page in enumerate(reader.pages)
    )


def canonicalise(raw: str, offsets: Iterable[int] = ()) -> tuple[str, dict[int, int]]:
    """Normalise whitespace and translate ``offsets`` into canonical coordinates.

    Runs of spaces collapse to one space and line breaks become a single space, so a
    sentence the extractor wrapped across three lines becomes one citable string.
    Leading and trailing whitespace is trimmed.

    The returned map is built in the same pass, which is why the caller passes the
    offsets it cares about instead of getting a full index: a full map over the
    largest document in the corpus would be three million entries to answer eighty
    questions.
    """
    wanted = sorted(set(offsets))
    mapping: dict[int, int] = {}
    out: list[str] = []
    canonical_length = 0
    pending_space = False
    started = False
    next_wanted = 0

    for index, char in enumerate(raw):
        while next_wanted < len(wanted) and wanted[next_wanted] < index:
            # An offset that fell inside collapsed whitespace maps to whatever comes
            # next, which is the start of the following word.
            mapping.setdefault(wanted[next_wanted], canonical_length)
            next_wanted += 1

        if char.isspace():
            if started:
                pending_space = True
            if next_wanted < len(wanted) and wanted[next_wanted] == index:
                mapping[wanted[next_wanted]] = canonical_length + (1 if pending_space else 0)
                next_wanted += 1
            continue

        if pending_space:
            out.append(" ")
            canonical_length += 1
            pending_space = False
        if next_wanted < len(wanted) and wanted[next_wanted] == index:
            mapping[wanted[next_wanted]] = canonical_length
            next_wanted += 1
        out.append(char)
        canonical_length += 1
        started = True

    for remaining in wanted[next_wanted:]:
        mapping.setdefault(remaining, canonical_length)
    return "".join(out), mapping


def _line_preserving(raw: str) -> str:
    """Collapse horizontal whitespace but keep line breaks, for heading detection."""
    return _SPACES.sub(" ", raw)


@dataclass
class IngestResult:
    """Everything one PDF contributed to the IR."""

    document: DocumentArtifact
    canonical_text: str
    chunks: tuple[Chunk, ...] = ()
    coverage: tuple[CoverageEntry, ...] = ()
    headings: tuple[Heading, ...] = ()
    page_count: int = 0
    pages_without_text: tuple[int, ...] = ()

    @property
    def extraction_gap(self) -> float:
        """Fraction of pages that produced no text at all."""
        return len(self.pages_without_text) / self.page_count if self.page_count else 0.0


def ingest_pdf(
    registry: SourceRegistry,
    path: Path,
    *,
    source_uri: str | None = None,
    retrieval_timestamp: str = "1970-01-01T00:00:00",
    license_record_id: str | None = None,
    max_chunk_chars: int = 20_000,
) -> IngestResult:
    """Register a PDF and chunk it by section, with a coverage entry per chunk."""
    raw_pages = extract_pages(path)
    raw = "\n".join(page.text for page in raw_pages)

    # Headings first, on the form that still has line starts, then translate.
    line_form = _line_preserving(raw)
    raw_headings = find_headings(line_form)
    canonical, mapped = canonicalise(line_form, (h.char_start for h in raw_headings))
    headings = tuple(
        Heading(heading.label, mapped[heading.char_start], heading.kind)
        for heading in raw_headings
    )

    document = registry.register_document(
        source_uri=source_uri or f"file://{path.name}",
        raw_bytes=path.read_bytes(),
        canonical_text=canonical,
        media_type="application/pdf",
        retrieval_timestamp=retrieval_timestamp,
        license_record_id=license_record_id,
        parser_version=parser_version(),
    )

    chunks: list[Chunk] = []
    coverage: list[CoverageEntry] = []
    for start, end, label in _section_bounds(canonical, headings, max_chunk_chars):
        chunk = registry.add_chunk(
            document.document_id, start, end, section_path=label
        )
        chunks.append(chunk)
        coverage.append(CoverageEntry(chunk_id=chunk.chunk_id, status="processed"))

    missing = tuple(page.number for page in raw_pages if not page.has_text)
    for page_number in missing:
        # A zero-length chunk is the honest record: this page contributed nothing to
        # the canonical text, and pretending it was processed would make the corpus
        # look complete.
        placeholder = registry.add_chunk(
            document.document_id,
            len(canonical),
            len(canonical),
            section_path=f"page {page_number}",
            page_start=page_number,
            page_end=page_number,
        )
        chunks.append(placeholder)
        coverage.append(
            CoverageEntry(
                chunk_id=placeholder.chunk_id,
                status="extraction_failed",
                note=f"page {page_number} produced no extractable text; it is most "
                "likely a scanned image and needs OCR under an explicit parser version",
            )
        )

    return IngestResult(
        document=document,
        canonical_text=canonical,
        chunks=tuple(chunks),
        coverage=tuple(coverage),
        headings=headings,
        page_count=len(raw_pages),
        pages_without_text=missing,
    )


def _section_bounds(
    canonical: str, headings: Sequence[Heading], max_chunk_chars: int
) -> tuple[tuple[int, int, str], ...]:
    """Section spans over canonical text, split to respect ``max_chunk_chars``."""
    bounds: list[tuple[int, int, str]] = []
    if not headings or headings[0].char_start > 0:
        first_end = headings[0].char_start if headings else len(canonical)
        if first_end > 0:
            bounds.append((0, first_end, ""))
    for index, heading in enumerate(headings):
        end = (
            headings[index + 1].char_start
            if index + 1 < len(headings)
            else len(canonical)
        )
        bounds.append((heading.char_start, end, heading.normalised()))

    out: list[tuple[int, int, str]] = []
    for start, end, label in bounds:
        if end <= start:
            continue
        cursor = start
        while cursor < end:
            stop = min(cursor + max_chunk_chars, end)
            out.append((cursor, stop, label))
            cursor = stop
    return tuple(out)


def section_for_offset(result: IngestResult, offset: int) -> str:
    """The section label covering a canonical offset."""
    return section_at(result.headings, offset)
