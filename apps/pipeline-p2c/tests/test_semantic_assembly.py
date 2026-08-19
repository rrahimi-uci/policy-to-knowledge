"""Tests for the canonical semantic graph and domain-profile boundary."""

from __future__ import annotations

import json
from dataclasses import replace

from compilers.run import compile_all
from fixtures import all_fixtures
from policy_ir.enums import DerivationMethod, Provenance, Status
from policy_ir.models import PolicyIR, SemanticRelation
from semantic import DomainProfile, ProfileError, generic_profile, load_profile
from semantic import AssemblyError, assemble_proposal, proposal_schema
from semantic import synthesis_report
from validation import blockers as codes
from validation import run_gate


def _relation() -> SemanticRelation:
    item = all_fixtures()["notice_process"]
    return SemanticRelation(
        relation_id="rel_lender_governs_notice",
        source_id=item.ir.entity_types[0].entity_type_id,
        target_id=item.ir.clauses[0].clause_id,
        relation_type="governs",
        provenance=Provenance.OBSERVED,
        derivation_method=DerivationMethod.EXPLICIT_CROSS_REFERENCE,
        qualifiers={"scope": "consumer-notice"},
        evidence_ids=(item.ir.evidence_spans[0].evidence_id,),
    )


def test_evidenced_semantic_relation_round_trips_and_projects() -> None:
    item = all_fixtures()["notice_process"]
    ir = replace(item.ir, semantic_relations=(_relation(),))
    restored = PolicyIR.from_dict(ir.to_dict())
    assert restored.semantic_relations == ir.semantic_relations

    report = run_gate(restored, item.texts)
    assert report.relation_admitted("rel_lender_governs_notice")
    assert report.semantic_relations["rel_lender_governs_notice"].has(Status.GRAPH_ELIGIBLE)
    graph = compile_all(restored, item.texts, targets=("graph",)).graph
    assert graph is not None
    assert graph["relationships"] == [
        {
            "relationship_id": "rel_lender_governs_notice",
            "source_id": _relation().source_id,
            "target_id": _relation().target_id,
            "relationship_type": "governs",
            "provenance": "observed",
            "derivation_method": "explicit_cross_reference",
            "qualifiers": {"scope": "consumer-notice"},
            "evidence_ids": list(_relation().evidence_ids),
            "admitted": True,
            "blockers": [],
        }
    ]


def test_relation_with_unknown_endpoint_is_visible_to_the_gate_but_not_projected() -> None:
    item = all_fixtures()["notice_process"]
    relation = replace(_relation(), target_id="missing_concept")
    ir = replace(item.ir, semantic_relations=(relation,))
    report = run_gate(ir, item.texts)
    assert codes.UNKNOWN_RELATION_ENDPOINT in report.semantic_relations[relation.relation_id].codes()
    graph = compile_all(ir, item.texts, targets=("graph",)).graph
    assert graph is not None
    assert graph["relationships"] == []


def test_domain_profile_is_configuration_and_cannot_relax_relation_validation(tmp_path) -> None:
    item = all_fixtures()["notice_process"]
    relation = _relation()
    profile = DomainProfile(profile_id="health-like", version="1", relation_types=("treats",))
    assert profile.validate(replace(item.ir, semantic_relations=(relation,))) == (
        "semantic relation 'rel_lender_governs_notice' uses undeclared type 'governs'",
    )
    assert generic_profile().validate(replace(item.ir, semantic_relations=(relation,))) == ()

    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")
    assert load_profile(path) == profile
    path.write_text("[]", encoding="utf-8")
    try:
        load_profile(path)
    except ProfileError as exc:
        assert "root must be an object" in str(exc)
    else:  # pragma: no cover - explicit failure message for a broken parser
        raise AssertionError("non-object profile unexpectedly loaded")


def test_semantic_proposal_can_add_only_records_citing_application_owned_evidence() -> None:
    item = all_fixtures()["notice_process"]
    relation = _relation().to_dict()
    assembled = assemble_proposal(item.ir, {"semantic_relations": [relation]})
    assert assembled.semantic_relations == (_relation(),)
    assert "SemanticRelation" in proposal_schema()["$defs"]

    relation["evidence_ids"] = ["invented_evidence"]
    try:
        assemble_proposal(item.ir, {"semantic_relations": [relation]})
    except AssemblyError as exc:
        assert "not owned by this IR" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("fabricated evidence was admitted")


def test_synthesis_report_does_not_mutate_ir() -> None:
    item = all_fixtures()["notice_process"]
    before = (len(item.ir.decisions), len(item.ir.processes))

    report = synthesis_report(item.ir)
    assert report
    assert {op.target for op in report} <= {"dmn", "bpmn"}
    assert all(op.status in {"ready_for_explicit_model", "abstain"} for op in report)
    assert (len(item.ir.decisions), len(item.ir.processes)) == before
