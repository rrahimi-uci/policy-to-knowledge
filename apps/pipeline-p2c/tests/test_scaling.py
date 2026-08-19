"""Guards against the per-item rebuilds that made the gate and projection quadratic.

These assert *operation counts*, not wall-clock time, so they are deterministic and
cannot flake on a busy machine. Each one pins a specific mistake that was made and
would be easy to make again: rebuilding an index inside a loop over the items it
indexes, and re-hashing a chunk once per citation instead of once per run.
"""

from __future__ import annotations

import pytest

from compilers.graph import project_graph
from ingestion import SourceRegistry
from policy_ir.enums import Effect, Modality, SemanticKind, SemanticRole
from policy_ir import ids
from policy_ir.models import AtomicPolicyClause, EvidenceSpan, PolicyIR
from validation import evidence_gate, run_gate

SENTENCE = "The Lender must pay fee number {n} within 10 business days. "


def build(count: int) -> tuple[PolicyIR, dict[str, str]]:
    """One document, one chunk, ``count`` evidenced clauses citing it."""
    text = "".join(SENTENCE.format(n=index) for index in range(count))
    registry = SourceRegistry()
    document = registry.register_document(
        source_uri=f"mem://{count}", raw_bytes=text.encode(), canonical_text=text
    )
    chunk = registry.chunk_whole_document(document.document_id)

    spans = []
    clauses = []
    cursor = 0
    for index in range(count):
        body = SENTENCE.format(n=index)
        start, end = cursor, cursor + len(body.rstrip())
        cursor += len(body)
        # Built directly rather than via a registry helper, so this guard stays
        # independent of whichever span constructors exist.
        span = EvidenceSpan(
            evidence_id=ids.evidence_id(
                document.document_id, chunk.chunk_sha256, start, end, "effect"
            ),
            document_id=document.document_id,
            chunk_id=chunk.chunk_id,
            chunk_sha256=chunk.chunk_sha256,
            char_start=start,
            char_end=end,
            exact_text=text[start:end],
            semantic_role=SemanticRole.EFFECT,
        )
        spans.append(span)
        clauses.append(
            AtomicPolicyClause(
                clause_id=f"clause_{index}",
                modality=Modality.OBLIGATION,
                semantic_kind=SemanticKind.UNCLASSIFIED,
                effect=Effect.NO_DIRECT_EFFECT,
                display_text=body.strip(),
                evidence={"effect": (span.evidence_id,)},
            )
        )
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=tuple(spans),
        clauses=tuple(clauses),
    )
    return ir, {document.document_id: text}


def test_an_index_is_built_once_not_per_item() -> None:
    ir, _ = build(4)
    for accessor in (
        ir.clause_index,
        ir.evidence_index,
        ir.chunk_index,
        ir.document_index,
        ir.data_definition_index,
        ir.clause_id_set,
        ir.section_paths,
    ):
        assert accessor() is accessor(), accessor.__name__


def test_the_index_cache_does_not_affect_equality_or_serialisation() -> None:
    """The cache is a plain attribute, not a field, so the record stays a value."""
    ir, _ = build(3)
    ir.clause_index()
    assert "_index_cache" not in ir.to_dict()
    assert PolicyIR.from_dict(ir.to_dict()) == ir


def test_a_chunk_is_hashed_once_per_run_not_once_per_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-hashing a chunk body per span was 68% of gate runtime on a real document."""
    calls: list[int] = []
    original = evidence_gate.sha256_text

    def counted(text: str) -> str:
        calls.append(len(text))
        return original(text)

    monkeypatch.setattr(evidence_gate, "sha256_text", counted)

    for count in (8, 64):
        calls.clear()
        ir, texts = build(count)
        run_gate(ir, texts)
        # One chunk in this document, so one hash of a chunk body — regardless of how
        # many clauses cite it.
        assert len(calls) == 1, f"{count} clauses hashed {len(calls)} times"


def test_gate_work_grows_linearly_with_clause_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Total bytes hashed must not grow with the square of the clause count."""
    original = evidence_gate.sha256_text
    totals: dict[int, int] = {}

    for count in (100, 400):
        hashed = 0

        def counted(text: str, _original=original) -> str:
            nonlocal hashed
            hashed += len(text)
            return _original(text)

        monkeypatch.setattr(evidence_gate, "sha256_text", counted)
        ir, texts = build(count)
        run_gate(ir, texts)
        totals[count] = hashed

    # Quadrupling the clauses quadruples the document length, so hashing the single
    # chunk once grows about 4x. The quadratic version grew 16x.
    growth = totals[400] / max(totals[100], 1)
    assert growth < 8, f"hashed bytes grew {growth:.1f}x for a 4x input"


def test_projection_reads_each_index_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The graph projection rebuilt the evidence index once per rule."""
    ir, texts = build(32)
    report = run_gate(ir, texts)

    builds = {"count": 0}
    original = PolicyIR.evidence_index

    def counted(self: PolicyIR) -> dict:
        if "evidence" not in getattr(self, "_index_cache", {}):
            builds["count"] += 1
        return original(self)

    monkeypatch.setattr(PolicyIR, "evidence_index", counted)
    project_graph(ir, report)
    assert builds["count"] <= 1, "the evidence index must not be rebuilt per rule"
