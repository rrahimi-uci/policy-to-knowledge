"""Helpers for writing conformance fixtures without boilerplate.

Fixtures are built through the real :class:`~ingestion.registry.SourceRegistry`,
so their hashes, chunk boundaries and character offsets are genuine. A fixture
cannot accidentally pass the provenance checks by construction; if a cited phrase
is not in the source text, building the fixture fails loudly here rather than
producing a case that only appears to be evidenced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ingestion.registry import SourceRegistry
from policy_ir.enums import MatchStatus, SemanticRole
from policy_ir.models import Chunk, DocumentArtifact, EvidenceSpan, PolicyIR


@dataclass
class DocumentHandle:
    """One registered document, with a helper for citing phrases inside it."""

    registry: SourceRegistry
    artifact: DocumentArtifact
    chunk: Chunk
    spans: dict[str, EvidenceSpan] = field(default_factory=dict)

    def cite(
        self,
        needle: str,
        role: SemanticRole,
        *,
        match_status: MatchStatus = MatchStatus.EXACT,
    ) -> str:
        """Record an evidence span for ``needle`` and return its evidence ID."""
        span = self.registry.make_span(
            self.chunk.chunk_id, needle, role, match_status=match_status
        )
        self.spans[span.evidence_id] = span
        return span.evidence_id

    def fabricate(
        self,
        claimed_text: str,
        anchor: str,
        role: SemanticRole,
    ) -> str:
        """Record a span whose offsets point at ``anchor`` but which claims
        ``claimed_text``.

        Used only by the negative fixtures: this is what a wrong-span citation
        looks like, and the gate must reject it.
        """
        start, end = self.registry.locate(self.chunk.chunk_id, anchor)
        span = EvidenceSpan(
            evidence_id=f"ev_fabricated_{len(self.spans)}_{role.value}",
            document_id=self.artifact.document_id,
            chunk_id=self.chunk.chunk_id,
            chunk_sha256=self.chunk.chunk_sha256,
            char_start=start,
            char_end=end,
            exact_text=claimed_text,
            semantic_role=role,
            match_status=MatchStatus.EXACT,
            section_path=self.chunk.section_path,
        )
        self.spans[span.evidence_id] = span
        return span.evidence_id


@dataclass
class FixtureBuilder:
    """Accumulates documents and IR parts for one fixture."""

    registry: SourceRegistry = field(default_factory=SourceRegistry)
    handles: list[DocumentHandle] = field(default_factory=list)

    def document(self, uri: str, text: str, section_path: str) -> DocumentHandle:
        artifact = self.registry.register_document(
            source_uri=uri,
            raw_bytes=text.encode("utf-8"),
            canonical_text=text,
            media_type="text/plain",
            retrieval_timestamp="2026-01-01T00:00:00",
            license_record_id="fixture-local",
        )
        chunk = self.registry.chunk_whole_document(
            artifact.document_id, section_path=section_path
        )
        handle = DocumentHandle(self.registry, artifact, chunk)
        self.handles.append(handle)
        return handle

    def spans(self) -> tuple[EvidenceSpan, ...]:
        collected: dict[str, EvidenceSpan] = {}
        for handle in self.handles:
            collected.update(handle.spans)
        return tuple(collected[key] for key in sorted(collected))

    def texts(self) -> Mapping[str, str]:
        return dict(self.registry.texts)

    def ir(self, **parts: object) -> PolicyIR:
        return PolicyIR(
            documents=self.registry.document_tuple(),
            chunks=self.registry.chunk_tuple(),
            evidence_spans=self.spans(),
            coverage=(),
            **parts,  # type: ignore[arg-type]
        )
