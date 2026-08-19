"""Contract and provenance tests.

The gate's promise is that an accepted field traces to exact bytes. These tests
attack that promise from both directions: valid records must survive a round trip,
and every way of breaking a citation must fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixtures import all_fixtures
from ingestion import SourceRegistry
from policy_ir._parsing import SchemaError
from policy_ir.enums import MatchStatus, SemanticRole, Status
from policy_ir.ids import SCHEMA_VERSION, derived_id, ncname
from policy_ir.jsonschema import schema_json
from policy_ir.models import PolicyIR
from validation import blockers as codes
from validation import run_gate

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "policy_ir" / "schema" / "policy-ir-v2.schema.json"


@pytest.mark.parametrize("name", sorted(all_fixtures()))
def test_ir_round_trips_losslessly(name: str) -> None:
    original = all_fixtures()[name].ir
    assert PolicyIR.from_dict(json.loads(json.dumps(original.to_dict()))) == original


def test_committed_json_schema_matches_the_dataclasses() -> None:
    """The committed schema is generated; drift means the two contracts disagree."""
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_json(), (
        "policy-ir-v2.schema.json is stale; regenerate it with "
        "python -c 'from policy_ir.jsonschema import schema_json; ...'"
    )


@pytest.mark.parametrize("name", sorted(all_fixtures()))
def test_json_schema_accepts_every_fixture(name: str) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(all_fixtures()[name].ir.to_dict(), schema)


def test_json_schema_rejects_unknown_fields() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    document = all_fixtures()["eligibility_decision"].ir.to_dict()
    document["clauses"][0]["invented_field"] = "surprise"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)


def test_parser_rejects_unknown_fields() -> None:
    document = all_fixtures()["eligibility_decision"].ir.to_dict()
    document["clauses"][0]["invented_field"] = "surprise"
    with pytest.raises(SchemaError, match="unknown key"):
        PolicyIR.from_dict(document)


def test_parser_rejects_a_foreign_schema_version() -> None:
    document = all_fixtures()["eligibility_decision"].ir.to_dict()
    document["schema_version"] = "policy-ir-9.9.9"
    with pytest.raises(SchemaError, match="does not match"):
        PolicyIR.from_dict(document)


def test_parser_rejects_an_unknown_enum_value() -> None:
    document = all_fixtures()["eligibility_decision"].ir.to_dict()
    document["clauses"][0]["modality"] = "vibes"
    with pytest.raises(SchemaError, match="is not one of"):
        PolicyIR.from_dict(document)


def test_ids_are_content_derived_not_position_derived() -> None:
    """Reordering inputs must not change identity, which batch-numbered IDs did."""
    assert derived_id("clause", "a", "b") == derived_id("clause", "a", "b")
    assert derived_id("clause", "a", "b") != derived_id("clause", "b", "a")
    # The separator matters: without it ("ab","c") and ("a","bc") would collide.
    assert derived_id("clause", "ab", "c") != derived_id("clause", "a", "bc")


def test_ids_are_valid_xml_ncnames() -> None:
    assert ncname("9 starts with a digit").startswith("_")
    assert ":" not in ncname("has:a:colon")
    assert ncname("") == "id"


def test_offsets_survive_overlapping_chunks() -> None:
    """Chunking is transport: two overlapping chunks must not move a span."""
    text = "A must pay the fee. B must file the report. C must retain the file."
    registry = SourceRegistry()
    document = registry.register_document(
        source_uri="mem://overlap", raw_bytes=text.encode(), canonical_text=text
    )
    first = registry.add_chunk(document.document_id, 0, 45)
    second = registry.add_chunk(document.document_id, 20, len(text))
    needle = "must file the report"
    from_first = registry.make_span(first.chunk_id, needle, SemanticRole.EFFECT)
    from_second = registry.make_span(second.chunk_id, needle, SemanticRole.EFFECT)
    assert (from_first.char_start, from_first.char_end) == (
        from_second.char_start,
        from_second.char_end,
    )
    assert text[from_first.char_start : from_first.char_end] == needle


def test_ambiguous_citation_is_refused_at_build_time() -> None:
    text = "The fee is due. The fee is due."
    registry = SourceRegistry()
    document = registry.register_document(
        source_uri="mem://ambiguous", raw_bytes=text.encode(), canonical_text=text
    )
    chunk = registry.chunk_whole_document(document.document_id)
    with pytest.raises(ValueError, match="more than once"):
        registry.make_span(chunk.chunk_id, "The fee is due.", SemanticRole.EFFECT)


def test_chunk_offsets_outside_the_document_are_refused() -> None:
    registry = SourceRegistry()
    document = registry.register_document(
        source_uri="mem://short", raw_bytes=b"short", canonical_text="short"
    )
    with pytest.raises(ValueError, match="outside"):
        registry.add_chunk(document.document_id, 0, 99)


def test_wrong_span_fails_closed() -> None:
    item = all_fixtures()["wrong_span"]
    report = run_gate(item.ir, item.texts)
    clause = report.clauses["clause_wrong_span"]
    assert codes.EVIDENCE_TEXT_MISMATCH in clause.codes()
    assert not clause.has(Status.PROVENANCE_EXACT)
    assert not clause.has(Status.DMN_ELIGIBLE)


def test_missing_canonical_text_fails_closed_rather_than_passing() -> None:
    """An unverifiable citation is refused, not trusted."""
    item = all_fixtures()["eligibility_decision"]
    report = run_gate(item.ir, {})
    clause = report.clauses["clause_eligible"]
    assert codes.EVIDENCE_TEXT_UNAVAILABLE in clause.codes()
    assert not clause.has(Status.PROVENANCE_EXACT)


def test_drifted_chunk_hash_fails_closed() -> None:
    item = all_fixtures()["eligibility_decision"]
    texts = dict(item.texts)
    document_id = next(iter(texts))
    texts[document_id] = texts[document_id].replace("620", "640")
    report = run_gate(item.ir, texts)
    clause = report.clauses["clause_eligible"]
    assert codes.CHUNK_HASH_MISMATCH in clause.codes()


def test_overstated_match_status_is_refused() -> None:
    """Declaring EXACT when only normalisation matches is itself a failure."""
    item = all_fixtures()["eligibility_decision"]
    ir = item.ir
    spans = []
    for span in ir.evidence_spans:
        if span.semantic_role is SemanticRole.CONDITION and "620" in span.exact_text:
            spans.append(
                type(span)(
                    **{
                        **{f: getattr(span, f) for f in span.__dataclass_fields__},
                        "exact_text": span.exact_text.replace(" ", "  "),
                    }
                )
            )
        else:
            spans.append(span)
    mutated = PolicyIR(
        schema_version=SCHEMA_VERSION,
        documents=ir.documents,
        chunks=ir.chunks,
        evidence_spans=tuple(spans),
        entity_types=ir.entity_types,
        data_definitions=ir.data_definitions,
        clauses=ir.clauses,
        decisions=ir.decisions,
    )
    report = run_gate(mutated, item.texts)
    all_codes = set(report.counts_by_code())
    assert codes.MATCH_STATUS_OVERSTATED in all_codes


def test_recovered_evidence_cannot_support_an_executable_projection() -> None:
    item = all_fixtures()["eligibility_decision"]
    ir = item.ir
    spans = tuple(
        type(span)(
            **{
                **{f: getattr(span, f) for f in span.__dataclass_fields__},
                "match_status": MatchStatus.RECOVERED,
            }
        )
        if span.semantic_role is SemanticRole.CONDITION
        else span
        for span in ir.evidence_spans
    )
    mutated = PolicyIR(
        schema_version=SCHEMA_VERSION,
        documents=ir.documents,
        chunks=ir.chunks,
        evidence_spans=spans,
        entity_types=ir.entity_types,
        data_definitions=ir.data_definitions,
        clauses=ir.clauses,
        decisions=ir.decisions,
    )
    report = run_gate(mutated, item.texts)
    assert codes.EVIDENCE_NOT_EXACT in set(report.counts_by_code())
    assert not report.decision_has("decision_purchase_eligibility", Status.DMN_ELIGIBLE)


def test_multi_span_evidence_keeps_its_roles() -> None:
    """A list of spans is first class; roles are not flattened away."""
    clause = all_fixtures()["exception_clause"].ir.clause_index()[
        "clause_eligible_unless_restricted"
    ]
    assert clause.evidence_for(SemanticRole.CONDITION)
    assert clause.evidence_for(SemanticRole.EFFECT)
    assert clause.evidence_for(SemanticRole.EXCEPTION)
    assert len(set(clause.all_evidence_ids())) == 3


def test_duplicate_ids_are_a_fatal_ir_error() -> None:
    item = all_fixtures()["eligibility_decision"]
    ir = item.ir
    duplicated = PolicyIR(
        schema_version=SCHEMA_VERSION,
        documents=ir.documents,
        chunks=ir.chunks,
        evidence_spans=ir.evidence_spans,
        entity_types=ir.entity_types,
        data_definitions=ir.data_definitions,
        clauses=ir.clauses + (ir.clauses[0],),
        decisions=ir.decisions,
    )
    report = run_gate(duplicated, item.texts)
    assert report.fatal
    assert any(blocker.code == codes.DUPLICATE_ID for blocker in report.global_blockers)
