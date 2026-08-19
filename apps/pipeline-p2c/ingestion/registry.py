"""The immutable source registry.

Everything downstream anchors to content, not to filenames. A document is
identified by the SHA-256 of its bytes *and* of its canonical extracted text;
chunks are slices of that canonical text with real character offsets, so
overlapping chunks cannot shift a span. Chunking is transport; provenance is the
document hash plus an offset pair.

Text normalisation is separated from the canonical text on purpose. The canonical
text is what offsets index into and what hashes cover, and it is never rewritten.
:func:`normalize_text` produces a *comparison* form used only to decide whether a
cited span matches the source under benign OCR and whitespace noise — a
``normalized_exact`` match, which is recorded as weaker than ``exact``.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass, field

from policy_ir import ids
from policy_ir.enums import MatchStatus, SemanticRole
from policy_ir.models import Chunk, DocumentArtifact, EvidenceSpan

#: Characters OCR and PDF extraction commonly substitute. Folding these for
#: comparison keeps a curly quote from failing an otherwise exact citation, while
#: the canonical text keeps whatever the parser produced.
_LOOKALIKES = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    " ": " ",
    "﻿": "",
    "​": "",
    "…": "...",
}

_WHITESPACE = re.compile(r"\s+")

PARSER_VERSION = "p2c-text-1.0.0"


def normalize_text(text: str) -> str:
    """Return the comparison form of ``text``.

    Case is preserved: "MUST" and "must" are the same word, but "Lender" and
    "lender" can be different defined terms in a policy document, and folding
    case here would let a citation match a different definition.
    """
    folded = unicodedata.normalize("NFKC", text)
    for source, target in _LOOKALIKES.items():
        folded = folded.replace(source, target)
    return _WHITESPACE.sub(" ", folded).strip()


@dataclass
class SourceRegistry:
    """Registered documents and their chunks, keyed by content."""

    documents: dict[str, DocumentArtifact] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    chunks: dict[str, Chunk] = field(default_factory=dict)

    def register_document(
        self,
        *,
        source_uri: str,
        raw_bytes: bytes,
        canonical_text: str,
        media_type: str = "text/plain",
        retrieval_timestamp: str | None = None,
        license_record_id: str | None = None,
        parser_version: str = PARSER_VERSION,
    ) -> DocumentArtifact:
        """Register a document and return its artefact record."""
        source_sha = ids.sha256_bytes(raw_bytes)
        document_id = ids.document_id(source_uri, source_sha)
        artifact = DocumentArtifact(
            document_id=document_id,
            source_uri=source_uri,
            source_sha256=source_sha,
            canonical_text_sha256=ids.sha256_text(canonical_text),
            media_type=media_type,
            retrieval_timestamp=retrieval_timestamp or _dt.datetime(1970, 1, 1).isoformat(),
            parser_version=parser_version,
            license_record_id=license_record_id,
        )
        self.documents[document_id] = artifact
        self.texts[document_id] = canonical_text
        return artifact

    def add_chunk(
        self,
        document_id: str,
        char_start: int,
        char_end: int,
        *,
        section_path: str = "",
        page_start: int | None = None,
        page_end: int | None = None,
    ) -> Chunk:
        """Register a chunk as a slice of a document's canonical text."""
        text = self.text(document_id)
        if not 0 <= char_start <= char_end <= len(text):
            raise ValueError(
                f"chunk offsets [{char_start}, {char_end}) fall outside document "
                f"{document_id!r} of length {len(text)}"
            )
        body = text[char_start:char_end]
        chunk_sha = ids.sha256_text(body)
        chunk = Chunk(
            chunk_id=ids.chunk_id(document_id, chunk_sha, char_start),
            document_id=document_id,
            chunk_sha256=chunk_sha,
            char_start=char_start,
            char_end=char_end,
            section_path=section_path,
            page_start=page_start,
            page_end=page_end,
        )
        self.chunks[chunk.chunk_id] = chunk
        return chunk

    def add_page_placeholder(self, document_id: str, page_number: int) -> Chunk:
        """Register a zero-length chunk standing in for a page with no text.

        The schema attaches coverage to a chunk, and a page that produced nothing has
        no span in the canonical text. Emitting no record would make a document with
        scanned pages look fully processed, so the placeholder carries the page number
        and its ID is derived from that page — never from its (empty) content.
        """
        text = self.text(document_id)
        chunk = Chunk(
            chunk_id=ids.missing_page_chunk_id(document_id, page_number),
            document_id=document_id,
            chunk_sha256=ids.sha256_text(""),
            char_start=len(text),
            char_end=len(text),
            section_path=f"page {page_number}",
            page_start=page_number,
            page_end=page_number,
        )
        self.chunks[chunk.chunk_id] = chunk
        return chunk

    def chunk_whole_document(self, document_id: str, *, section_path: str = "") -> Chunk:
        """Convenience for small documents: one chunk covering everything."""
        return self.add_chunk(
            document_id, 0, len(self.text(document_id)), section_path=section_path
        )

    def text(self, document_id: str) -> str:
        try:
            return self.texts[document_id]
        except KeyError as exc:
            raise KeyError(f"document {document_id!r} is not registered") from exc

    def chunk_text(self, chunk_id: str) -> str:
        chunk = self.chunks[chunk_id]
        return self.text(chunk.document_id)[chunk.char_start : chunk.char_end]

    def locate(self, chunk_id: str, needle: str) -> tuple[int, int]:
        """Find ``needle`` inside a chunk and return canonical document offsets.

        Only an exact, unambiguous occurrence is accepted. A phrase that appears
        twice raises rather than picking the first hit: the plan's stress matrix
        requires an ambiguous match to stay unresolved instead of being silently
        resolved to whichever copy came first.
        """
        chunk = self.chunks[chunk_id]
        body = self.chunk_text(chunk_id)
        first = body.find(needle)
        if first < 0:
            raise ValueError(f"{needle!r} does not occur in chunk {chunk_id!r}")
        if body.find(needle, first + 1) >= 0:
            raise ValueError(
                f"{needle!r} occurs more than once in chunk {chunk_id!r}; "
                "cite a longer, unambiguous span"
            )
        return chunk.char_start + first, chunk.char_start + first + len(needle)

    def span_at(
        self,
        chunk_id: str,
        char_start: int,
        char_end: int,
        role: SemanticRole,
        *,
        match_status: MatchStatus = MatchStatus.EXACT,
    ) -> EvidenceSpan:
        """Build an evidence span from offsets that are already known.

        :meth:`make_span` searches for a phrase and refuses an ambiguous one, which is
        right for a human citing a quote. An extractor walking sentences already knows
        where it is, and its sentence may legitimately recur verbatim elsewhere in the
        document — so it must anchor by position, not by search.
        """
        chunk = self.chunks[chunk_id]
        if not (chunk.char_start <= char_start <= char_end <= chunk.char_end):
            raise ValueError(
                f"[{char_start}, {char_end}) falls outside chunk {chunk_id!r} "
                f"[{chunk.char_start}, {chunk.char_end})"
            )
        text = self.text(chunk.document_id)
        return EvidenceSpan(
            evidence_id=ids.evidence_id(
                chunk.document_id, chunk.chunk_sha256, char_start, char_end, role.value
            ),
            document_id=chunk.document_id,
            chunk_id=chunk_id,
            chunk_sha256=chunk.chunk_sha256,
            char_start=char_start,
            char_end=char_end,
            exact_text=text[char_start:char_end],
            semantic_role=role,
            match_status=match_status,
            section_path=chunk.section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
        )

    def make_span(
        self,
        chunk_id: str,
        needle: str,
        role: SemanticRole,
        *,
        match_status: MatchStatus = MatchStatus.EXACT,
    ) -> EvidenceSpan:
        """Build an evidence span for an exact phrase inside a chunk."""
        chunk = self.chunks[chunk_id]
        char_start, char_end = self.locate(chunk_id, needle)
        return EvidenceSpan(
            evidence_id=ids.evidence_id(
                chunk.document_id, chunk.chunk_sha256, char_start, char_end, role.value
            ),
            document_id=chunk.document_id,
            chunk_id=chunk_id,
            chunk_sha256=chunk.chunk_sha256,
            char_start=char_start,
            char_end=char_end,
            exact_text=needle,
            semantic_role=role,
            match_status=match_status,
            section_path=chunk.section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
        )

    def document_tuple(self) -> tuple[DocumentArtifact, ...]:
        return tuple(self.documents[key] for key in sorted(self.documents))

    def chunk_tuple(self) -> tuple[Chunk, ...]:
        return tuple(self.chunks[key] for key in sorted(self.chunks))
