"""One test per row of the plan's stress-test matrix.

Each row states a threat, a transformation and a required result. A row only counts
if its expected result is an executable assertion, so anything that would need
human judgement is absent here by design rather than asserted loosely.
"""

from __future__ import annotations

import pytest

from compilers.bpmn import compile_bpmn
from compilers.dmn import compile_dmn
from compilers.run import compile_all
from fixtures import all_fixtures
from policy_ir.enums import Status
from validation import blockers as codes
from validation import run_gate

FIXTURES = all_fixtures()

#: threat -> (fixture, blocker code that must appear)
REFUSALS = {
    "prompt invents an attribute": ("proposed_attribute", codes.PROPOSED_ELEMENT_IN_EXECUTABLE),
    "modal flip": ("modal_flip", codes.MODALITY_NOT_ATTESTED),
    "numeric drift": ("numeric_drift", codes.LITERAL_NOT_ATTESTED),
    "unit drift": ("unit_drift", codes.ILL_TYPED_EXPRESSION),
    "unproven hit policy": ("overlapping_rows", codes.HIT_POLICY_NOT_PROVEN),
    "missing process actor": ("missing_actor_process", codes.MISSING_RESPONSIBLE_ACTOR),
    "inferred sequence from related rules": ("inferred_sequence", codes.ORDERING_NOT_VALIDATED),
    "broken cross reference": ("broken_reference", codes.UNRESOLVED_CROSS_REFERENCE),
    "evidence mismatch": ("wrong_span", codes.EVIDENCE_TEXT_MISMATCH),
}


@pytest.mark.parametrize("threat", sorted(REFUSALS))
def test_threat_produces_its_specific_refusal(threat: str) -> None:
    fixture_name, expected = REFUSALS[threat]
    item = FIXTURES[fixture_name]
    report = run_gate(item.ir, item.texts)
    assert expected in set(report.counts_by_code()), threat


#: Which artefact each threat must be kept out of.
BLOCKED_ARTIFACT = {
    "prompt invents an attribute": "decisions.dmn",
    "modal flip": "decisions.dmn",
    "numeric drift": "decisions.dmn",
    "unit drift": "decisions.dmn",
    "unproven hit policy": "decisions.dmn",
    "broken cross reference": "decisions.dmn",
    "evidence mismatch": "decisions.dmn",
    "missing process actor": "processes-executable.bpmn",
    "inferred sequence from related rules": "processes-executable.bpmn",
}


@pytest.mark.parametrize("threat", sorted(REFUSALS))
def test_a_refused_threat_never_reaches_an_executable_artefact(threat: str) -> None:
    fixture_name, _ = REFUSALS[threat]
    item = FIXTURES[fixture_name]
    result = compile_all(item.ir, item.texts)
    filename = BLOCKED_ARTIFACT[threat]
    assert result.artifact(filename).emitted_ids == (), threat


def test_compound_clause_keeps_its_exception() -> None:
    """"A unless B" must not flatten into "A"."""
    item = FIXTURES["exception_clause"]
    report = run_gate(item.ir, item.texts)
    artifact = compile_dmn(item.ir, report)
    assert artifact.emitted_ids
    assert "not(" in artifact.xml
    assert "exception folded into the row" in artifact.xml


def test_false_process_inference_is_impossible_from_a_bare_obligation() -> None:
    item = FIXTURES["retention_obligation"]
    report = run_gate(item.ir, item.texts)
    bpmn = compile_bpmn(item.ir, report)
    assert bpmn.emitted_ids == ()
    assert "task" not in bpmn.xml
    assert "timer" not in bpmn.xml


def test_xml_injection_in_source_text_stays_data() -> None:
    """Source text that looks like markup or FEEL is escaped, never executed."""
    from policy_ir.enums import DataType, Provenance
    from policy_ir.models import DataDefinition

    item = FIXTURES["eligibility_decision"]
    definitions = list(item.ir.data_definitions)
    hostile = DataDefinition(
        data_definition_id=definitions[0].data_definition_id,
        name='</text><script>alert("x")</script> & score',
        type=DataType.NUMBER,
        provenance=Provenance.OBSERVED,
        null_policy=definitions[0].null_policy,
    )
    ir = type(item.ir)(
        **{
            **{f: getattr(item.ir, f) for f in item.ir.__dataclass_fields__},
            "data_definitions": (hostile, *definitions[1:]),
        }
    )
    report = run_gate(ir, item.texts)
    artifact = compile_dmn(ir, report)
    assert "<script>" not in artifact.xml
    assert "&lt;" in artifact.xml or artifact.emitted_ids == ()


def test_non_deterministic_generation_is_ruled_out() -> None:
    item = FIXTURES["notice_process"]
    first = compile_all(item.ir, item.texts)
    second = compile_all(item.ir, item.texts)
    assert first.files() == second.files()
    assert first.manifest["outputs"] == second.manifest["outputs"]


def test_abstention_is_reported_not_hidden() -> None:
    """Coverage and blocker distribution are results, not omissions."""
    item = FIXTURES["overlapping_rows"]
    result = compile_all(item.ir, item.texts)
    report = result.compilation_report
    assert report["gate"]["blocker_counts"]
    assert report["skipped_by_code"]
    assert report["assurance"]["governance_approved"] == "not claimed by this run"


def test_a_clean_fixture_survives_every_stage() -> None:
    item = FIXTURES["notice_process"]
    result = compile_all(item.ir, item.texts)
    assert result.ok
    assert result.report.admitted_decisions() == ("decision_purchase_eligibility",)
    assert result.report.admitted_processes() == ("fragment_adverse_action_notice",)
    assert result.artifact("decisions.dmn").emitted_ids
    assert result.artifact("processes-executable.bpmn").emitted_ids
