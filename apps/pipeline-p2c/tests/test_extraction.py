"""The extraction contract and the deterministic baseline extractor.

Two things are being pinned. First, the contract's three controls — a proposal cannot
cite a span it was not offered, cannot name its own identity, and cannot both assert
and disclaim a field. Second, that the baseline extractor produces genuinely evidenced
clauses while typing nothing, so its output reaches the graph and stops there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from compilers.run import compile_all
from extraction.candidates import (
    CandidateRejected,
    candidate_from_dict,
    candidate_to_dict,
    candidates_to_clauses,
)
from extraction.deterministic import extract_deterministic, extract_from_chunk
from extraction.sentences import split_sentences
from ingestion import SourceRegistry
from policy_ir.enums import (
    CompilationIntent,
    Effect,
    Modality,
    SemanticKind,
    SemanticRole,
    Status,
)
from policy_ir.models import PolicyIR
from validation import blockers as codes
from validation import run_gate

SAMPLE = (
    "Section 1.1 Fees. The Lender must pay the fee within 10 business days. "
    "If the loan is a short-term loan, the Lender must notify the borrower. "
    "A Seller may request an exception unless the property is in a restricted county. "
    "This paragraph is descriptive and states no requirement."
)


def registry_for(text: str = SAMPLE):
    registry = SourceRegistry()
    document = registry.register_document(
        source_uri="mem://sample", raw_bytes=text.encode(), canonical_text=text
    )
    chunk = registry.chunk_whole_document(document.document_id, section_path="Section 1.1")
    return registry, chunk, document


# -- sentence segmentation --------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("See Ch. 12 for details. Next sentence.", 2),
        ("Refer to § 1016.5(a) and No. 4 herein. Then this.", 2),
        ("The fee is $5,000.00 per loan. Another one.", 2),
        ("Cf. 15 U.S.C. 1691 for authority. Done.", 2),
        ("One sentence only", 1),
    ],
)
def test_terminators_that_end_nothing_do_not_split(text: str, expected: int) -> None:
    """Over-splitting truncates a requirement and drops half its own citation."""
    assert len(split_sentences(text)) == expected


def test_sentence_offsets_round_trip_and_are_absolute() -> None:
    sentences = split_sentences(SAMPLE, offset=100)
    for sentence in sentences:
        assert SAMPLE[sentence.char_start - 100 : sentence.char_end - 100] == sentence.text


# -- the contract's three controls -----------------------------------------


def minimal(**overrides) -> dict:
    base = {
        "modality": "obligation",
        "semantic_kind": "documentation_requirement",
        "effect": "create_record",
        "display_text": "Retain the file.",
        "evidence": {"effect": ["ev_1"]},
    }
    base.update(overrides)
    return base


def test_a_candidate_may_not_name_its_own_identity() -> None:
    """Identity is derived from content, so a batch cannot be reordered into new IDs."""
    with pytest.raises(CandidateRejected, match="unknown key"):
        candidate_from_dict(minimal(clause_id="chosen_by_the_extractor"))
    assert "clause_id" not in candidate_to_dict(candidate_from_dict(minimal()))


def test_a_candidate_may_not_cite_a_span_it_was_not_offered() -> None:
    candidate = candidate_from_dict(minimal())
    with pytest.raises(CandidateRejected, match="not offered"):
        candidates_to_clauses(
            [candidate], offered_span_ids=["ev_other"], document_sha256="abc"
        )
    admitted = candidates_to_clauses(
        [candidate], offered_span_ids=["ev_1"], document_sha256="abc"
    )
    assert len(admitted) == 1


def test_a_field_cannot_be_asserted_and_disclaimed_at_once() -> None:
    with pytest.raises(CandidateRejected, match="declared unstated"):
        candidate_from_dict(
            minimal(
                missing=["effect"],
                effect_ast={"kind": "literal", "value": 1, "type": "number"},
            )
        )
    with pytest.raises(CandidateRejected, match="declared unstated"):
        candidate_from_dict(minimal(missing=["authority"], authority_ref="auth_guide"))


def test_declaring_a_field_untyped_while_citing_its_text_is_consistent() -> None:
    """"There is condition text here and I did not type it" must be sayable."""
    candidate = candidate_from_dict(
        minimal(evidence={"condition": ["ev_1"], "effect": ["ev_2"]}, missing=["condition"])
    )
    assert candidate.condition_ast is None
    assert candidate.evidence["condition"] == ("ev_1",)


def test_unknown_fields_enums_and_missing_names_are_refused() -> None:
    with pytest.raises(CandidateRejected, match="unknown key"):
        candidate_from_dict(minimal(invented="surprise"))
    with pytest.raises(CandidateRejected, match="is not one of"):
        candidate_from_dict(minimal(modality="vibes"))
    with pytest.raises(CandidateRejected, match="not declarable"):
        candidate_from_dict(minimal(missing=["everything"]))


def test_an_uncited_candidate_is_refused() -> None:
    with pytest.raises(CandidateRejected, match="at least one span"):
        candidate_from_dict(minimal(evidence={}))


def test_candidates_round_trip() -> None:
    candidate = candidate_from_dict(
        minimal(
            evidence={"condition": ["ev_1"], "effect": ["ev_2"]},
            condition_ast={
                "kind": "comparison",
                "left": {"kind": "variable_ref", "data_definition_id": "score"},
                "operator": ">=",
                "right": {"kind": "literal", "value": 620, "type": "number"},
            },
            missing=["exception"],
            compilation_intent="dmn",
        )
    )
    assert candidate_from_dict(candidate_to_dict(candidate)) == candidate


def test_identical_evidence_and_kind_deduplicates_by_construction() -> None:
    candidate = candidate_from_dict(minimal())
    once = candidates_to_clauses([candidate], offered_span_ids=["ev_1"], document_sha256="abc")
    twice = candidates_to_clauses(
        [candidate, candidate], offered_span_ids=["ev_1"], document_sha256="abc"
    )
    assert len(twice) == 1
    assert twice[0].clause_id == once[0].clause_id


def test_a_different_document_yields_a_different_clause_id() -> None:
    candidate = candidate_from_dict(minimal())
    first = candidates_to_clauses([candidate], offered_span_ids=["ev_1"], document_sha256="a")
    second = candidates_to_clauses([candidate], offered_span_ids=["ev_1"], document_sha256="b")
    assert first[0].clause_id != second[0].clause_id


# -- the deterministic extractor -------------------------------------------


def test_only_normative_sentences_become_clauses() -> None:
    registry, chunk, _ = registry_for()
    result = extract_deterministic(registry, [chunk])
    assert result.stats.sentences_scanned == 5
    assert result.stats.normative_sentences == 3
    assert result.stats.clauses_emitted == 3
    texts = [clause.display_text for clause in result.clauses]
    assert not any("descriptive and states no requirement" in t for t in texts)


def test_modalities_are_read_from_the_text() -> None:
    registry, chunk, _ = registry_for()
    result = extract_deterministic(registry, [chunk])
    by_modality = {clause.modality for clause in result.clauses}
    assert by_modality == {Modality.OBLIGATION, Modality.PERMISSION}


def test_must_notify_is_an_obligation_not_a_prohibition() -> None:
    """Regression: "must not" occurs inside "must notify" as a substring.

    Substring matching read a routine obligation as a prohibition, and stripping the
    negation first then removed its obligation reading too, so the clause came out
    prohibitive. Markers now match whole words only.
    """
    registry, chunk, _ = registry_for()
    result = extract_deterministic(registry, [chunk])
    notify = next(c for c in result.clauses if "must notify" in c.display_text)
    assert notify.modality is Modality.OBLIGATION


def test_a_leading_condition_is_carved_from_the_effect() -> None:
    registry, chunk, _ = registry_for()
    result = extract_deterministic(registry, [chunk])
    clause = next(c for c in result.clauses if "must notify" in c.display_text)
    spans = {s.evidence_id: s for s in result.spans}
    condition = [spans[e].exact_text for e in clause.evidence_for(SemanticRole.CONDITION)]
    effect = [spans[e].exact_text for e in clause.evidence_for(SemanticRole.EFFECT)]
    assert condition == ["If the loan is a short-term loan"]
    assert effect == ["the Lender must notify the borrower."]


def test_a_trailing_exception_is_carved_from_the_effect() -> None:
    registry, chunk, _ = registry_for()
    result = extract_deterministic(registry, [chunk])
    clause = next(c for c in result.clauses if "may request an exception" in c.display_text)
    spans = {s.evidence_id: s for s in result.spans}
    exception = [spans[e].exact_text for e in clause.evidence_for(SemanticRole.EXCEPTION)]
    assert exception == ["unless the property is in a restricted county."]


def test_every_emitted_span_round_trips_against_the_document() -> None:
    registry, chunk, document = registry_for()
    result = extract_deterministic(registry, [chunk])
    text = registry.text(document.document_id)
    assert result.spans
    for span in result.spans:
        assert text[span.char_start : span.char_end] == span.exact_text


def test_the_extractor_types_nothing() -> None:
    """Untyped by construction is what keeps this baseline out of DMN and BPMN."""
    registry, chunk, _ = registry_for()
    result = extract_deterministic(registry, [chunk])
    for clause in result.clauses:
        assert clause.condition_ast is None
        assert clause.effect_ast is None
        assert clause.exception_ast is None
        assert clause.semantic_kind is SemanticKind.UNCLASSIFIED
        assert clause.effect is Effect.NO_DIRECT_EFFECT
        assert clause.compilation_intent is CompilationIntent.GRAPH_ONLY


def test_extracted_clauses_reach_the_graph_and_stop_there() -> None:
    registry, chunk, document = registry_for()
    result = extract_deterministic(registry, [chunk])
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=result.spans,
        clauses=result.clauses,
        coverage=result.coverage,
    )
    outcome = compile_all(ir, {document.document_id: registry.text(document.document_id)})
    assert outcome.ok
    assert outcome.graph is not None
    assert outcome.graph["metadata"]["total_rules"] == len(result.clauses)
    assert outcome.report.admitted_decisions() == ()
    assert outcome.report.admitted_processes() == ()
    assert outcome.artifact("decisions.dmn").emitted_ids == ()


def test_the_gate_finds_nothing_to_refuse() -> None:
    registry, chunk, document = registry_for()
    result = extract_deterministic(registry, [chunk])
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=result.spans,
        clauses=result.clauses,
    )
    report = run_gate(ir, {document.document_id: registry.text(document.document_id)})
    assert report.counts_by_code() == {}
    for clause in result.clauses:
        assert report.clause_has(clause.clause_id, Status.GRAPH_ELIGIBLE)
        assert not report.clause_has(clause.clause_id, Status.DMN_ELIGIBLE)


def test_a_modal_verb_only_inside_an_exception_does_not_mislabel_the_clause() -> None:
    """Regression: 216 mislabels across the committed corpus came from this shape.

    Reading modality from the whole sentence while the gate reads only the subject,
    condition and effect regions labelled a clause from text the gate does not treat as
    modal-bearing. Every failing case was a sentence whose only marker sat inside its
    "unless" clause. The requirement in that clause is real, so the fix is to recognise
    the carve as wrong and cite the sentence whole rather than to drop it.
    """
    text = (
        "This clause generally excludes loss caused by a director unless the director "
        'is also a salaried employee. "Dishonest acts" are defined as acts of that kind.'
    )
    registry, chunk, document = registry_for(text)
    result = extract_deterministic(registry, [chunk])
    assert result.clauses, "the requirement must not be dropped"

    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=result.spans,
        clauses=result.clauses,
    )
    report = run_gate(ir, {document.document_id: text})
    assert codes.MODALITY_NOT_ATTESTED not in set(report.counts_by_code())
    # Cited whole rather than carved, so the modal verb is inside a region the gate reads.
    first = result.clauses[0]
    assert set(first.evidence) == {"effect"}


def test_the_extractor_reads_the_same_regions_the_gate_checks() -> None:
    """Whatever the carve, a declared modality is supported by modal-bearing roles."""
    from extraction.deterministic import _MODAL_BEARING_ROLES
    from validation.attestation import attested_modalities

    text = (
        "If the loan is short-term, the Lender must notify the borrower. "
        "A Seller may request an exception unless the county is restricted. "
        "The clause applies unless the lender must first escalate the file."
    )
    registry, chunk, _ = registry_for(text)
    result = extract_deterministic(registry, [chunk])
    spans = {span.evidence_id: span for span in result.spans}
    modal_roles = {role.value for role in _MODAL_BEARING_ROLES}
    for clause in result.clauses:
        supporting = " ".join(
            spans[evidence_id].exact_text
            for role, ids in clause.evidence.items()
            if role in modal_roles
            for evidence_id in ids
        )
        assert clause.modality in attested_modalities(supporting), clause.display_text


def test_the_modality_check_cannot_fail_for_this_extractor() -> None:
    """Stated as a test so a green gate is not mistaken for validation.

    The extractor reads modality from the same marker table *and the same regions* the
    gate checks, so the attestation cannot fail here. It carries information only when
    the modality was proposed independently — which is why the modal-flip fixture exists.
    """
    registry, chunk, document = registry_for()
    result = extract_deterministic(registry, [chunk])
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=result.spans,
        clauses=result.clauses,
    )
    report = run_gate(ir, {document.document_id: registry.text(document.document_id)})
    assert codes.MODALITY_NOT_ATTESTED not in set(report.counts_by_code())

    # Flip one modality by hand and the check bites immediately.
    flipped = list(result.clauses)
    original = flipped[0]
    flipped[0] = type(original)(
        **{
            **{f: getattr(original, f) for f in original.__dataclass_fields__},
            "modality": Modality.DEFINITION,
        }
    )
    mutated = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "clauses": tuple(flipped)}
    )
    report = run_gate(mutated, {document.document_id: registry.text(document.document_id)})
    assert codes.MODALITY_NOT_ATTESTED in set(report.counts_by_code())


def test_coverage_is_recorded_for_every_chunk_read() -> None:
    registry, chunk, _ = registry_for()
    empty = registry.register_document(
        source_uri="mem://empty", raw_bytes=b"Nothing normative here.",
        canonical_text="Nothing normative here.",
    )
    quiet = registry.chunk_whole_document(empty.document_id)
    result = extract_deterministic(registry, [chunk, quiet])
    statuses = {entry.chunk_id: entry.status for entry in result.coverage}
    assert statuses[chunk.chunk_id] == "candidates_emitted"
    assert statuses[quiet.chunk_id] == "no_policy_semantics_found"


def test_placeholder_chunks_are_not_read() -> None:
    registry, chunk, document = registry_for()
    placeholder = registry.add_page_placeholder(document.document_id, 3)
    result = extract_deterministic(registry, [chunk, placeholder])
    assert placeholder.chunk_id not in {entry.chunk_id for entry in result.coverage}
    assert result.stats.chunks_scanned == 1


def test_extraction_is_deterministic() -> None:
    registry_a, chunk_a, _ = registry_for()
    registry_b, chunk_b, _ = registry_for()
    first = extract_deterministic(registry_a, [chunk_a])
    second = extract_deterministic(registry_b, [chunk_b])
    assert [c.clause_id for c in first.clauses] == [c.clause_id for c in second.clauses]
    assert [s.evidence_id for s in first.spans] == [s.evidence_id for s in second.spans]
    assert first.stats == second.stats


def test_extract_from_chunk_offers_only_the_spans_it_created() -> None:
    """The offer set is what stops a citation to unseen text; it must be exact."""
    registry, chunk, _ = registry_for()
    candidates, spans, _, _ = extract_from_chunk(registry, chunk)
    offered = {span.evidence_id for span in spans}
    for candidate in candidates:
        assert set(candidate.cited_evidence_ids()) <= offered


# -- real corpus ------------------------------------------------------------

CORPUS_PDF = (
    Path(__file__).resolve().parents[2]
    / "pipeline"
    / "compliance-files"
    / "comercial_lending"
    / "bulletin_2013_9a.pdf"
)


def _pypdf_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pypdf") is not None


@pytest.mark.skipif(
    not CORPUS_PDF.exists() or not _pypdf_available(),
    reason="the committed corpus or the pypdf extra is not present",
)
def test_a_real_document_yields_evidenced_graph_only_clauses() -> None:
    from ingestion.pdf import ingest_pdf

    registry = SourceRegistry()
    ingested = ingest_pdf(registry, CORPUS_PDF)
    result = extract_deterministic(registry, ingested.chunks)

    assert result.stats.clauses_emitted > 50, "this bulletin is full of requirements"
    text = registry.text(ingested.document.document_id)
    for span in result.spans:
        assert text[span.char_start : span.char_end] == span.exact_text

    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=result.spans,
        clauses=result.clauses,
        coverage=result.coverage,
    )
    outcome = compile_all(ir, {ingested.document.document_id: text})
    assert outcome.ok
    assert outcome.graph["metadata"]["total_rules"] == result.stats.clauses_emitted
    assert outcome.report.admitted_decisions() == ()
    assert set(outcome.report.counts_by_code()) == set()
