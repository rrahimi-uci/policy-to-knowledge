"""A deterministic, model-free clause extractor.

It finds normative sentences, cites them by offset, and emits clauses that assert
almost nothing: a modality, the text, and where that text is. It types no condition,
no effect and no threshold, so its output is graph-only by construction and can never
reach DMN or BPMN.

That is the point. It gives the whole pipeline a real input path over the real corpus
today, and it is the baseline any model-driven extractor must beat — the plan requires
a direct-extraction baseline that is not allowed to quietly benefit from the gate.

**One caveat, stated because a passing gate could otherwise be mistaken for
validation.** This extractor reads modality from the same marker table
:mod:`validation.attestation` checks it against, and — since the fix described below —
from the same *regions* the gate reads. Its modality therefore cannot fail that check.
The check carries information only for a modality proposed independently, by a model or
by hand. Nothing else about the gate is weakened: provenance, offsets and hashes are
verified exactly as for any other clause.

Getting that alignment right was not automatic. Reading modality from the whole sentence
while the gate reads only the subject, condition and effect regions produced 216
mislabels across the committed corpus — every one a sentence whose only modal marker sat
inside its ``unless`` clause, so the gate correctly found the declared modality
unsupported by the parts of the clause that carry normative force. The response is not
to drop those sentences, because the requirement inside the exception is real; it is to
recognise the carve as wrong and cite the sentence whole.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ingestion.registry import SourceRegistry
from policy_ir.enums import (
    CompilationIntent,
    Effect,
    Modality,
    SemanticKind,
    SemanticRole,
)
from policy_ir.models import AtomicPolicyClause, Chunk, CoverageEntry, EvidenceSpan
from validation.attestation import attested_modalities

from .candidates import CandidateClause, candidates_to_clauses
from .sentences import Sentence, split_sentences

#: Most constraining first. A sentence attesting both a prohibition and a permission
#: ("may not") is a prohibition, and taking the weaker reading would understate it.
_MODALITY_PRECEDENCE = (
    Modality.PROHIBITION,
    Modality.OBLIGATION,
    Modality.PERMISSION,
    Modality.RECOMMENDATION,
    Modality.DEFINITION,
)

#: Structural drafting markers, not domain vocabulary.
_CONDITION_MARKERS = (
    "if ",
    "when ",
    "where ",
    "provided that",
    "in the event that",
    "to the extent that",
    "subject to",
)
_EXCEPTION_MARKERS = ("unless", "except that", "except as", "except when", "other than")

#: Roles the gate reads when checking that a declared modality is supported. The
#: extractor must read the same regions, or it will label a clause from text the gate
#: does not treat as modal-bearing.
_MODAL_BEARING_ROLES = (SemanticRole.SUBJECT, SemanticRole.CONDITION, SemanticRole.EFFECT)

#: Semantics this extractor never produces in typed form.
_ALWAYS_MISSING = ("condition", "effect", "exception", "subject", "action", "object")

_WORD_BOUNDARY = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class ExtractionStats:
    """What one extraction pass looked at and produced."""

    chunks_scanned: int = 0
    sentences_scanned: int = 0
    normative_sentences: int = 0
    clauses_emitted: int = 0

    @property
    def normative_rate(self) -> float:
        return (
            self.normative_sentences / self.sentences_scanned
            if self.sentences_scanned
            else 0.0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "chunks_scanned": self.chunks_scanned,
            "sentences_scanned": self.sentences_scanned,
            "normative_sentences": self.normative_sentences,
            "clauses_emitted": self.clauses_emitted,
            "normative_rate": round(self.normative_rate, 4),
        }


@dataclass
class ExtractionResult:
    """Clauses, the spans they cite, and per-chunk coverage."""

    clauses: tuple[AtomicPolicyClause, ...] = ()
    spans: tuple[EvidenceSpan, ...] = ()
    coverage: tuple[CoverageEntry, ...] = ()
    stats: ExtractionStats = field(default_factory=ExtractionStats)


def _choose_modality(text: str) -> Modality | None:
    attested = attested_modalities(text)
    for modality in _MODALITY_PRECEDENCE:
        if modality in attested:
            return modality
    return None


def _modal_text(
    sentence: Sentence, regions: Sequence[tuple[SemanticRole, int, int]]
) -> str:
    """The text the gate will read when checking this clause's modality."""
    base = sentence.char_start
    return " ".join(
        sentence.text[begin - base : finish - base]
        for role, begin, finish in regions
        if role in _MODAL_BEARING_ROLES
    )


def _first_marker(lowered: str, markers: Sequence[str]) -> int | None:
    positions = [lowered.find(marker) for marker in markers]
    hits = [position for position in positions if position >= 0]
    return min(hits) if hits else None


def _carve_roles(sentence: Sentence) -> tuple[tuple[SemanticRole, int, int], ...]:
    """Split a sentence into role-tagged regions, conservatively.

    Two drafting shapes are recognised — a trailing qualifier ("… must pay X if Y") and
    a leading one ("If Y, … must pay X") — because those two cover most of the corpus
    and each has an unambiguous boundary. Anything else is cited whole as the effect
    rather than guessed at, since a mis-carved region would attach a condition to the
    wrong clause.
    """
    text = sentence.text
    lowered = text.lower()
    start, end = sentence.char_start, sentence.char_end

    exception_at = _first_marker(lowered, _EXCEPTION_MARKERS)
    condition_at = _first_marker(lowered, _CONDITION_MARKERS)

    # Leading condition: "If Y, the lender must pay X."
    if condition_at is not None and condition_at <= 1:
        comma = text.find(",")
        if 0 < comma < len(text) - 1:
            regions = [
                (SemanticRole.CONDITION, start, start + comma),
                (SemanticRole.EFFECT, start + comma + 1, end),
            ]
            return tuple(_trim(text, start, region) for region in regions)
        return ((SemanticRole.EFFECT, start, end),)

    boundaries = sorted(
        (position, role)
        for position, role in (
            (condition_at, SemanticRole.CONDITION),
            (exception_at, SemanticRole.EXCEPTION),
        )
        if position is not None and position > 0
    )
    if not boundaries:
        return ((SemanticRole.EFFECT, start, end),)

    regions: list[tuple[SemanticRole, int, int]] = [
        (SemanticRole.EFFECT, start, start + boundaries[0][0])
    ]
    for index, (position, role) in enumerate(boundaries):
        stop = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(text)
        regions.append((role, start + position, start + stop))
    return tuple(_trim(text, start, region) for region in regions)


def _trim(
    text: str, base: int, region: tuple[SemanticRole, int, int]
) -> tuple[SemanticRole, int, int]:
    """Trim punctuation and whitespace from a region without losing its offsets."""
    role, begin, finish = region
    body = text[begin - base : finish - base]
    leading = len(body) - len(body.lstrip(" ,;:"))
    trailing = len(body) - len(body.rstrip(" ,;:"))
    return role, begin + leading, finish - trailing


def extract_from_chunk(
    registry: SourceRegistry, chunk: Chunk
) -> tuple[tuple[CandidateClause, ...], tuple[EvidenceSpan, ...], int, int]:
    """Extract candidates from one chunk. Returns candidates, spans and two counts."""
    body = registry.chunk_text(chunk.chunk_id)
    sentences = split_sentences(body, offset=chunk.char_start)
    candidates: list[CandidateClause] = []
    spans: dict[str, EvidenceSpan] = {}
    normative = 0

    for sentence in sentences:
        if not _WORD_BOUNDARY.search(sentence.text):
            continue
        if _choose_modality(sentence.text) is None:
            continue
        normative += 1

        regions = _carve_roles(sentence)
        modality = _choose_modality(_modal_text(sentence, regions))
        if modality is None:
            # The sentence is normative but its modal verb landed outside the regions
            # the gate reads — almost always inside an "unless" clause carrying its own
            # requirement. Dropping it would lose that requirement, so cite the sentence
            # whole and let the modality come from all of it.
            regions = ((SemanticRole.EFFECT, sentence.char_start, sentence.char_end),)
            modality = _choose_modality(sentence.text)
            if modality is None:  # pragma: no cover - guarded above
                continue

        evidence: dict[str, tuple[str, ...]] = {}
        for role, begin, finish in regions:
            if finish <= begin:
                continue
            span = registry.span_at(chunk.chunk_id, begin, finish, role)
            spans[span.evidence_id] = span
            evidence.setdefault(role.value, ())
            evidence[role.value] = (*evidence[role.value], span.evidence_id)
        if not evidence:
            continue

        candidates.append(
            CandidateClause(
                modality=modality,
                # Untyped by construction: this extractor reads modality and position,
                # and claiming a semantic kind it has not established would be a guess.
                semantic_kind=SemanticKind.UNCLASSIFIED,
                effect=Effect.NO_DIRECT_EFFECT,
                display_text=sentence.text,
                evidence=evidence,
                compilation_intent=CompilationIntent.GRAPH_ONLY,
                source_group_id=chunk.chunk_id,
                missing=_ALWAYS_MISSING,
            )
        )
    return tuple(candidates), tuple(spans.values()), len(sentences), normative


def extract_deterministic(
    registry: SourceRegistry, chunks: Iterable[Chunk]
) -> ExtractionResult:
    """Extract clauses from every chunk, recording coverage for each one."""
    documents = registry.documents
    all_clauses: dict[str, AtomicPolicyClause] = {}
    all_spans: dict[str, EvidenceSpan] = {}
    coverage: list[CoverageEntry] = []
    chunks_scanned = sentences_scanned = normative_total = 0

    for chunk in chunks:
        if chunk.char_end == chunk.char_start:
            # A placeholder for a page with no extractable text. Its coverage was
            # already recorded at ingestion; there is nothing here to read.
            continue
        chunks_scanned += 1
        candidates, spans, sentence_count, normative = extract_from_chunk(registry, chunk)
        sentences_scanned += sentence_count
        normative_total += normative
        all_spans.update({span.evidence_id: span for span in spans})

        document = documents[chunk.document_id]
        clauses = candidates_to_clauses(
            candidates,
            offered_span_ids=[span.evidence_id for span in spans],
            document_sha256=document.canonical_text_sha256,
        )
        for clause in clauses:
            all_clauses.setdefault(clause.clause_id, clause)
        coverage.append(
            CoverageEntry(
                chunk_id=chunk.chunk_id,
                status="candidates_emitted" if clauses else "no_policy_semantics_found",
                note=(
                    f"{len(clauses)} clause(s) from {normative} normative of "
                    f"{sentence_count} sentence(s)"
                ),
            )
        )

    return ExtractionResult(
        clauses=tuple(all_clauses[key] for key in sorted(all_clauses)),
        spans=tuple(all_spans[key] for key in sorted(all_spans)),
        coverage=tuple(coverage),
        stats=ExtractionStats(
            chunks_scanned=chunks_scanned,
            sentences_scanned=sentences_scanned,
            normative_sentences=normative_total,
            clauses_emitted=len(all_clauses),
        ),
    )
