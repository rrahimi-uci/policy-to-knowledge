"""The extraction seam: what an extractor is offered, and what it may return.

The property under test is that a citation to unseen text is **unexpressible**, not
merely rejected. A proposal names unit indices; the emitted JSON Schema enumerates
exactly the indices a request offered; and the application builds every evidence span
itself from offsets it already holds. There is no route from a proposal to the document
other than an index the request issued.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extraction.candidates import CandidateRejected
from extraction.contract import PROHIBITIONS, proposal_schema, render_instructions
from extraction.offer import ExtractionRequest, TextUnit, build_request, build_requests
from extraction.proposals import (
    admit_proposals,
    proposal_from_dict,
    resolve_proposal,
)
from ingestion import SourceRegistry
from policy_ir._parsing import SchemaError
from policy_ir.enums import SemanticRole, Status
from policy_ir.models import PolicyIR
from validation import run_gate

SAMPLE = (
    "Section 2. The Lender must pay the fee within 10 business days. "
    "A Seller may request an exception."
)


def fixture(text: str = SAMPLE):
    registry = SourceRegistry()
    document = registry.register_document(
        source_uri="mem://offer", raw_bytes=text.encode(), canonical_text=text
    )
    chunk = registry.chunk_whole_document(document.document_id, section_path="Section 2")
    return registry, chunk, document


def minimal(**overrides) -> dict:
    base = {
        "modality": "obligation",
        "semantic_kind": "documentation_requirement",
        "effect": "create_record",
        "display_unit": 0,
        "citations": {"effect": [0]},
    }
    base.update(overrides)
    return base


# -- the offer --------------------------------------------------------------


def test_a_request_offers_numbered_units_with_absolute_offsets() -> None:
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    assert [unit.index for unit in request.units] == [0, 1]
    for unit in request.units:
        assert SAMPLE[unit.char_start : unit.char_end] == unit.text


def test_a_request_does_not_carry_the_document_text() -> None:
    """An extractor that could read past its units could reason beyond its evidence."""
    registry, chunk, _ = fixture()
    payload = build_request(registry, chunk).to_dict()
    assert set(payload) == {"chunk_id", "document_id", "section_path", "units"}
    assert SAMPLE not in json.dumps(payload)


def test_requests_round_trip() -> None:
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    assert ExtractionRequest.from_dict(request.to_dict()) == request


def test_out_of_order_units_are_refused() -> None:
    with pytest.raises(SchemaError, match="ascending order"):
        ExtractionRequest.from_dict(
            {
                "chunk_id": "c",
                "document_id": "d",
                "units": [
                    TextUnit(1, 0, 1, "b").to_dict(),
                    TextUnit(0, 1, 2, "a").to_dict(),
                ],
            }
        )


def test_placeholder_chunks_are_not_offered() -> None:
    registry, chunk, document = fixture()
    placeholder = registry.add_page_placeholder(document.document_id, 4)
    requests = build_requests(registry, [chunk, placeholder])
    assert [r.chunk_id for r in requests] == [chunk.chunk_id]


def test_building_requests_is_deterministic() -> None:
    """Re-ingestion must rebuild the same requests, or unit indices would not resolve."""
    first = build_request(*fixture()[:2])
    second = build_request(*fixture()[:2])
    assert first == second


# -- the generated schema ---------------------------------------------------


def test_the_schema_is_itself_valid() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    registry, chunk, _ = fixture()
    jsonschema.Draft202012Validator.check_schema(
        proposal_schema(build_request(registry, chunk))
    )


def test_the_schema_makes_a_fabricated_citation_unexpressible() -> None:
    """The central control: not "rejected later" but "cannot be produced"."""
    jsonschema = pytest.importorskip("jsonschema")
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    schema = proposal_schema(request)

    jsonschema.validate({"candidates": [minimal()]}, schema)
    with pytest.raises(jsonschema.ValidationError, match="is not one of"):
        jsonschema.validate(
            {"candidates": [minimal(citations={"effect": [99]})]}, schema
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidates": [minimal(display_unit=99)]}, schema)


def test_the_schema_enumerates_only_the_offered_indices() -> None:
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    schema = proposal_schema(request)
    expected = [unit.index for unit in request.units]
    assert schema["$defs"]["CandidateProposal"]["properties"]["display_unit"]["enum"] == expected
    for role_slot in schema["$defs"]["RoleCitations"]["properties"].values():
        assert role_slot["items"]["enum"] == expected


def test_the_schema_closes_every_vocabulary_and_forbids_extra_keys() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    registry, chunk, _ = fixture()
    schema = proposal_schema(build_request(registry, chunk))
    proposal = schema["$defs"]["CandidateProposal"]
    assert proposal["additionalProperties"] is False
    for field in ("modality", "semantic_kind", "effect", "lifecycle", "compilation_intent"):
        assert "enum" in proposal["properties"][field], field
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidates": [minimal(invented="surprise")]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidates": [minimal(modality="vibes")]}, schema)


def test_the_schema_embeds_the_expression_grammar_from_one_generator() -> None:
    registry, chunk, _ = fixture()
    schema = proposal_schema(build_request(registry, chunk))
    assert "Expression" in schema["$defs"]
    assert "Comparison" in schema["$defs"]
    assert schema["$defs"]["CandidateProposal"]["properties"]["condition_ast"] == {
        "$ref": "#/$defs/Expression"
    }


def test_the_instructions_state_the_prohibitions_and_list_the_units() -> None:
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    text = render_instructions(request)
    for rule in PROHIBITIONS:
        assert rule in text
    for unit in request.units:
        assert f"[{unit.index}] {unit.text}" in text
    assert "empty `candidates` list" in text, "zero output must be permitted explicitly"


def test_the_instructions_name_no_domain() -> None:
    registry, chunk, _ = fixture()
    text = render_instructions(build_request(registry, chunk)).lower()
    for noun in ("mortgage", "healthcare", "hipaa", "insurer", "policyholder"):
        assert noun not in text


# -- proposals --------------------------------------------------------------


def test_a_proposal_cannot_cite_a_unit_that_was_not_offered() -> None:
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    proposal = proposal_from_dict(minimal(citations=[{"role": "effect", "units": [99]}]))
    with pytest.raises(CandidateRejected, match="did not offer"):
        resolve_proposal(proposal, request, registry)


def test_a_proposal_cannot_choose_its_display_text_freely() -> None:
    """display_text comes from the cited unit, so it cannot drift from the source."""
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    candidate, _ = resolve_proposal(proposal_from_dict(minimal(display_unit=1)), request, registry)
    assert candidate.display_text == request.unit(1).text


def test_the_application_builds_the_spans() -> None:
    registry, chunk, document = fixture()
    request = build_request(registry, chunk)
    _, spans = resolve_proposal(proposal_from_dict(minimal()), request, registry)
    assert len(spans) == 1
    span = spans[0]
    assert span.semantic_role is SemanticRole.EFFECT
    assert registry.text(document.document_id)[span.char_start : span.char_end] == span.exact_text
    assert span.chunk_id == chunk.chunk_id


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"citations": []}, "empty"),
        ({"citations": [{"role": "effect", "units": []}]}, "no unit"),
        (
            {"citations": [{"role": "effect", "units": [0]}, {"role": "effect", "units": [1]}]},
            "more than once",
        ),
        ({"citations": [{"role": "effect", "units": [0, 0]}]}, "repeats a unit"),
        ({"modality": "vibes"}, "is not one of"),
        ({"invented": "surprise"}, "unknown key"),
    ],
)
def test_malformed_proposals_are_refused(payload: dict, match: str) -> None:
    with pytest.raises(CandidateRejected, match=match):
        proposal_from_dict(minimal(**payload))


def test_a_contradiction_between_missing_and_a_supplied_field_is_refused() -> None:
    registry, chunk, _ = fixture()
    request = build_request(registry, chunk)
    proposal = proposal_from_dict(
        minimal(
            missing=["effect"],
            effect_ast={"kind": "literal", "value": 1, "type": "number"},
        )
    )
    with pytest.raises(CandidateRejected, match="declared unstated"):
        resolve_proposal(proposal, request, registry)


def test_proposals_round_trip() -> None:
    proposal = proposal_from_dict(
        minimal(
            citations=[{"role": "condition", "units": [0]}, {"role": "effect", "units": [1]}],
            missing=["exception"],
            compilation_intent="graph_only",
        )
    )
    assert proposal_from_dict(proposal.to_dict()) == proposal


def test_admitting_the_same_proposal_twice_yields_one_clause() -> None:
    registry, chunk, document = fixture()
    request = build_request(registry, chunk)
    proposal = proposal_from_dict(minimal())
    clauses, spans = admit_proposals(
        [proposal, proposal], request, registry,
        document_sha256=document.canonical_text_sha256,
    )
    assert len(clauses) == 1
    assert len(spans) == 1


def test_an_admitted_proposal_passes_the_gate_with_verified_provenance() -> None:
    registry, chunk, document = fixture()
    request = build_request(registry, chunk)
    clauses, spans = admit_proposals(
        [proposal_from_dict(minimal(missing=["condition", "exception"]))],
        request,
        registry,
        document_sha256=document.canonical_text_sha256,
    )
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=spans,
        clauses=clauses,
    )
    report = run_gate(ir, {document.document_id: registry.text(document.document_id)})
    assert report.counts_by_code() == {}
    assert report.clause_has(clauses[0].clause_id, Status.PROVENANCE_EXACT)
    assert report.clause_has(clauses[0].clause_id, Status.GRAPH_ELIGIBLE)
    assert not report.clause_has(clauses[0].clause_id, Status.DMN_ELIGIBLE)


# -- CLI --------------------------------------------------------------------

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


requires_corpus = pytest.mark.skipif(
    not CORPUS_PDF.exists() or not _pypdf_available(),
    reason="the committed corpus or the pypdf extra is not present",
)


@requires_corpus
def test_emit_requests_writes_a_request_schema_and_contract_per_chunk(tmp_path: Path) -> None:
    from cli.compile_policy import EXIT_OK, main

    assert (
        main(["--ingest", str(CORPUS_PDF), "--emit-requests", str(tmp_path), "--dry-run", "--quiet"])
        == EXIT_OK
    )
    requests = sorted(tmp_path.glob("*.request.json"))
    assert requests
    assert len(list(tmp_path.glob("*.schema.json"))) == len(requests)
    assert len(list(tmp_path.glob("*.instructions.md"))) == len(requests)
    payload = json.loads(requests[0].read_text(encoding="utf-8"))
    assert ExtractionRequest.from_dict(payload).units


@requires_corpus
def test_a_proposal_round_trips_from_a_real_document(tmp_path: Path) -> None:
    """Emit a request, answer it, and see the clause reach the graph."""
    from cli.compile_policy import EXIT_OK, main

    requests_dir = tmp_path / "requests"
    main(["--ingest", str(CORPUS_PDF), "--emit-requests", str(requests_dir), "--dry-run", "--quiet"])

    chosen = None
    for path in sorted(requests_dir.glob("*.request.json")):
        request = ExtractionRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for unit in request.units:
            if " must " in unit.text and len(unit.text) < 400:
                chosen = (request, unit)
                break
        if chosen:
            break
    assert chosen, "expected an obligation in this bulletin"
    request, unit = chosen

    proposal_file = tmp_path / "proposals.json"
    proposal_file.write_text(
        json.dumps(
            {
                "chunk_id": request.chunk_id,
                "candidates": [
                    {
                        "modality": "obligation",
                        "semantic_kind": "documentation_requirement",
                        "effect": "create_record",
                        "display_unit": unit.index,
                        "citations": [{"role": "effect", "units": [unit.index]}],
                        "compilation_intent": "graph_only",
                        "missing": ["condition", "exception"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out = tmp_path / "out"
    assert (
        main(["--ingest", str(CORPUS_PDF), "--proposals", str(proposal_file), "--out", str(out), "--quiet"])
        == EXIT_OK
    )
    ir = PolicyIR.from_dict(json.loads((out / "policy-ir-v2.json").read_text(encoding="utf-8")))
    assert ir.metadata["artifact_role"] == "model_extraction"
    assert len(ir.clauses) == 1
    graph = json.loads((out / "graph-v2.json").read_text(encoding="utf-8"))
    rule = graph["business_rules"][0]
    assert rule["reference_verified"] is True
    assert rule["compilation_status"]["dmn_eligible"] is False
    assert rule["source_reference"][0]["source_text"] == unit.text


@requires_corpus
def test_proposals_for_an_unknown_chunk_are_an_error(tmp_path: Path) -> None:
    from cli.compile_policy import main

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"chunk_id": "chunk_nope", "candidates": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--ingest", str(CORPUS_PDF), "--proposals", str(bad), "--dry-run", "--quiet"])
