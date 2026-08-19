"""The offer: numbered text units an extractor may cite, and nothing else.

The safest contract is one where a proposal cannot name a span at all. An extractor is
handed a chunk split into numbered :class:`TextUnit` records and answers with unit
*indices*; the application then builds the evidence spans itself from those indices.

That inverts the usual risk. If a proposal supplied span IDs, every one would have to be
checked against an offer set, and a fabricated ID would be caught only after the fact.
Here a fabricated citation is not expressible: an index outside the request's range is
rejected by the schema before parsing, and every admitted span is constructed from
offsets the application already holds. The extractor cannot cite text it was not shown
because it has no vocabulary for doing so.

Units are sentences. They are the smallest span that carries a complete requirement, and
a smaller unit would force an extractor to reassemble one before it could cite it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ingestion.registry import SourceRegistry
from policy_ir._parsing import SchemaError, as_int, as_str, as_tuple, check_keys
from policy_ir.models import Chunk

from .sentences import split_sentences


@dataclass(frozen=True)
class TextUnit:
    """One citable unit of a chunk, addressed by index rather than by ID."""

    index: int
    char_start: int
    char_end: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TextUnit":
        record = "TextUnit"
        check_keys(data, record, ["index", "char_start", "char_end", "text"])
        return cls(
            index=as_int(data["index"], record, "index"),
            char_start=as_int(data["char_start"], record, "char_start"),
            char_end=as_int(data["char_end"], record, "char_end"),
            text=as_str(data["text"], record, "text"),
        )


@dataclass(frozen=True)
class ExtractionRequest:
    """Everything an extractor is given for one chunk, and nothing more.

    Deliberately excludes the document's full text. An extractor that could read beyond
    its units could reason about text it cannot cite, and the resulting clause would be
    supported by evidence that does not cover it.
    """

    chunk_id: str
    document_id: str
    section_path: str
    units: tuple[TextUnit, ...]

    @property
    def unit_count(self) -> int:
        return len(self.units)

    def unit(self, index: int) -> TextUnit:
        for unit in self.units:
            if unit.index == index:
                return unit
        raise KeyError(f"unit {index} is not in this request")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "section_path": self.section_path,
            "units": [unit.to_dict() for unit in self.units],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtractionRequest":
        record = "ExtractionRequest"
        check_keys(data, record, ["chunk_id", "document_id", "units"], ["section_path"])
        units = as_tuple(data["units"], record, "units", TextUnit.from_dict)
        indices = [unit.index for unit in units]
        if indices != sorted(set(indices)):
            raise SchemaError(
                f"{record}.units must have unique indices in ascending order, got {indices}"
            )
        return cls(
            chunk_id=as_str(data["chunk_id"], record, "chunk_id"),
            document_id=as_str(data["document_id"], record, "document_id"),
            section_path=data.get("section_path", ""),
            units=units,
        )


def build_request(registry: SourceRegistry, chunk: Chunk) -> ExtractionRequest:
    """Split one chunk into numbered units, with absolute offsets preserved."""
    body = registry.chunk_text(chunk.chunk_id)
    sentences = split_sentences(body, offset=chunk.char_start)
    return ExtractionRequest(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        section_path=chunk.section_path,
        units=tuple(
            TextUnit(index, sentence.char_start, sentence.char_end, sentence.text)
            for index, sentence in enumerate(sentences)
        ),
    )


def build_requests(
    registry: SourceRegistry, chunks: Iterable[Chunk]
) -> tuple[ExtractionRequest, ...]:
    """One request per chunk that has any text to read.

    Placeholder chunks for pages with no extractable text are skipped: there is nothing
    to offer, and a request with no units would invite a proposal citing nothing.
    """
    requests = []
    for chunk in chunks:
        if chunk.char_end == chunk.char_start:
            continue
        request = build_request(registry, chunk)
        if request.units:
            requests.append(request)
    return tuple(requests)
