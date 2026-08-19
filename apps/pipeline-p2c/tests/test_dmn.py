"""DMN compiler tests.

The central assertion is the equivalence one: the Policy IR evaluator and an
independent reader of the emitted XML must agree. Everything else here guards a
specific way the compiler could quietly overstate what the source supports.
"""

from __future__ import annotations

import itertools

import pytest

from compilers.dmn import DMN_MODEL_NS, compile_dmn
from compilers.dmn_reference import read_decisions
from compilers.run import compile_all
from compilers.verify import validate_dmn
from evaluation import UNKNOWN, EvaluationContext, evaluate_decision
from fixtures import all_fixtures
from policy_ir.enums import CompilerProfile, HitPolicy
from policy_ir.feel import feel_name
from policy_ir.models import DecisionModelCandidate
from validation import blockers as codes
from validation import run_gate

EXECUTABLE = CompilerProfile.EXECUTABLE_SUBSET
REVIEW = CompilerProfile.REVIEW


def compiled(name: str, profile: CompilerProfile = EXECUTABLE):
    item = all_fixtures()[name]
    report = run_gate(item.ir, item.texts)
    return item, report, compile_dmn(item.ir, report, profile=profile)


def test_the_emitted_document_targets_dmn_15() -> None:
    _, _, artifact = compiled("eligibility_decision")
    assert f'xmlns="{DMN_MODEL_NS}"' in artifact.xml
    assert "20230324" in artifact.xml


@pytest.mark.parametrize("name", ["eligibility_decision", "exception_clause", "fee_calculation"])
def test_emitted_dmn_is_structurally_clean(name: str) -> None:
    _, _, artifact = compiled(name)
    assert validate_dmn(artifact.xml) == ()
    assert artifact.emitted_ids


def test_input_expressions_reference_declared_input_data() -> None:
    item, _, artifact = compiled("eligibility_decision")
    decision = read_decisions(artifact.xml)["decision_purchase_eligibility"]
    expected = tuple(
        feel_name(item.ir.data_definition_index()[input_id].name)
        for input_id in item.ir.decisions[0].input_data_refs
    )
    assert decision.input_names == expected


def test_every_rule_has_one_entry_per_input_and_output() -> None:
    _, _, artifact = compiled("eligibility_decision")
    decision = read_decisions(artifact.xml)["decision_purchase_eligibility"]
    for rule in decision.rules:
        assert len(rule.input_entries) == len(decision.input_names)
        assert rule.output_entry


def test_rules_annotate_their_originating_clause() -> None:
    """Traceability starts in the artefact itself, not only in the manifest."""
    _, _, artifact = compiled("eligibility_decision")
    decision = read_decisions(artifact.xml)["decision_purchase_eligibility"]
    annotations = {rule.annotation for rule in decision.rules}
    assert "clause_eligible" in annotations
    assert "clause_not_eligible" in annotations


@pytest.mark.parametrize(
    "score,ltv",
    list(itertools.product([560, 619, 620, 700, 850], [0.5, 0.8, 0.81, 0.95])),
)
def test_reference_evaluator_agrees_with_the_policy_ir_evaluator(score: int, ltv: float) -> None:
    item, _, artifact = compiled("eligibility_decision")
    ir_result = evaluate_decision(
        item.ir,
        "decision_purchase_eligibility",
        EvaluationContext.for_ir(item.ir, {"credit_score": score, "ltv_ratio": ltv}),
    )
    reference = read_decisions(artifact.xml)["decision_purchase_eligibility"]
    from_xml = reference.evaluate_value(
        {"borrower_credit_score": score, "loan_to_value_ratio": ltv}
    )
    from_ir = None if ir_result.value is UNKNOWN else ir_result.value
    assert from_ir == from_xml


@pytest.mark.parametrize(
    "score,county",
    list(itertools.product([600, 620, 700], ["standard", "restricted"])),
)
def test_exception_survives_into_the_compiled_table(score: int, county: str) -> None:
    """The 'unless' must still exclude restricted counties after compilation."""
    item, _, artifact = compiled("exception_clause")
    ir_result = evaluate_decision(
        item.ir,
        "decision_restricted_eligibility",
        EvaluationContext.for_ir(
            item.ir, {"credit_score": score, "county_status": county}
        ),
    )
    reference = read_decisions(artifact.xml)["decision_restricted_eligibility"]
    from_xml = reference.evaluate_value(
        {"borrower_credit_score": score, "property_county_status": county}
    )
    from_ir = None if ir_result.value is UNKNOWN else ir_result.value
    assert from_ir == from_xml
    if county == "restricted":
        assert from_xml is None


def test_overlapping_rows_are_refused_not_relabelled() -> None:
    item, report, artifact = compiled("overlapping_rows")
    assert codes.HIT_POLICY_NOT_PROVEN in set(report.counts_by_code())
    assert artifact.emitted_ids == ()
    # And the refusal is not silently converted into an ordered policy.
    assert "FIRST" not in artifact.xml and "PRIORITY" not in artifact.xml


def test_first_hit_policy_requires_evidenced_ordering() -> None:
    item = all_fixtures()["eligibility_decision"]
    decision = item.ir.decisions[0]
    ordered = DecisionModelCandidate(
        **{
            **{f: getattr(decision, f) for f in decision.__dataclass_fields__},
            "proposed_hit_policy": HitPolicy.FIRST,
            "ordering_evidence_ids": (),
        }
    )
    ir = type(item.ir)(
        **{**{f: getattr(item.ir, f) for f in item.ir.__dataclass_fields__}, "decisions": (ordered,)}
    )
    report = run_gate(ir, item.texts)
    assert codes.ORDERING_NOT_EVIDENCED in report.decisions[decision.decision_id].codes()


def test_collect_requires_a_declared_aggregation() -> None:
    item = all_fixtures()["fee_calculation"]
    decision = item.ir.decisions[0]
    collected = DecisionModelCandidate(
        **{
            **{f: getattr(decision, f) for f in decision.__dataclass_fields__},
            "proposed_hit_policy": HitPolicy.COLLECT,
            "aggregation": None,
        }
    )
    ir = type(item.ir)(
        **{**{f: getattr(item.ir, f) for f in item.ir.__dataclass_fields__}, "decisions": (collected,)}
    )
    report = run_gate(ir, item.texts)
    assert codes.AGGREGATION_NOT_DECLARED in report.decisions[decision.decision_id].codes()


def test_a_proposed_input_never_becomes_a_dmn_input() -> None:
    _, report, artifact = compiled("proposed_attribute")
    assert codes.PROPOSED_ELEMENT_IN_EXECUTABLE in set(report.counts_by_code())
    assert artifact.emitted_ids == ()


def test_review_profile_emits_what_the_executable_profile_refuses() -> None:
    """Review is for humans: it draws the model and says why it is not executable."""
    _, _, executable = compiled("numeric_drift", EXECUTABLE)
    _, _, review = compiled("numeric_drift", REVIEW)
    assert executable.emitted_ids == ()
    assert review.emitted_ids == ("decision_drifted_eligibility",)
    assert "REVIEW ONLY" in review.xml
    assert codes.LITERAL_NOT_ATTESTED in review.xml
    assert validate_dmn(review.xml) == ()


def test_review_profile_still_refuses_a_structural_failure() -> None:
    """Reviewable means "unverified", not "anything goes"."""
    item = all_fixtures()["eligibility_decision"]
    # Withholding the canonical text makes every span unverifiable, which is a
    # provenance-integrity failure rather than a soft one.
    review = compile_dmn(item.ir, run_gate(item.ir, {}), profile=REVIEW)
    assert review.emitted_ids == ()


def test_identical_input_compiles_to_identical_bytes() -> None:
    item = all_fixtures()["eligibility_decision"]
    first = compile_dmn(item.ir, run_gate(item.ir, item.texts))
    second = compile_dmn(item.ir, run_gate(item.ir, item.texts))
    assert first.xml == second.xml


def test_a_decision_whose_row_is_not_admitted_is_not_emitted() -> None:
    _, report, artifact = compiled("unit_drift")
    assert artifact.emitted_ids == ()


def test_compilation_report_records_every_refusal() -> None:
    item = all_fixtures()["overlapping_rows"]
    result = compile_all(item.ir, item.texts, targets=("dmn",))
    assert result.compilation_report["admitted"]["decisions"] == []
    assert result.compilation_report["skipped_by_code"]
    assert result.ok  # refusing to compile is not a run failure
