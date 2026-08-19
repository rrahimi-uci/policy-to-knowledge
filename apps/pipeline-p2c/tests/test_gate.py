"""Gate behaviour, driven by the fixture library's declared expectations.

Each fixture states what the gate should conclude, so this file is the table-driven
regression net: a change that widens or narrows admission shows up as a specific
fixture flipping rather than as a diff nobody reads.
"""

from __future__ import annotations

import pytest

from fixtures import all_fixtures, fixture_names
from policy_ir.enums import Status
from validation import blockers as codes
from validation import run_gate

FIXTURES = all_fixtures()


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_expected_dmn_admission(name: str) -> None:
    item = FIXTURES[name]
    report = run_gate(item.ir, item.texts)
    admitted = {
        decision.name
        for decision in item.ir.decisions
        if report.decision_has(decision.decision_id, Status.DMN_ELIGIBLE)
    }
    assert admitted == set(item.expect_dmn), item.description


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_expected_bpmn_admission(name: str) -> None:
    item = FIXTURES[name]
    report = run_gate(item.ir, item.texts)
    admitted = {
        process.name
        for process in item.ir.processes
        if report.process_has(process.fragment_id, Status.BPMN_ELIGIBLE)
    }
    assert admitted == set(item.expect_bpmn), item.description


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_expected_blocker_codes_are_present(name: str) -> None:
    item = FIXTURES[name]
    report = run_gate(item.ir, item.texts)
    seen = set(report.counts_by_code())
    assert set(item.expect_codes) <= seen, item.description


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_forbidden_blocker_codes_are_absent(name: str) -> None:
    item = FIXTURES[name]
    report = run_gate(item.ir, item.texts)
    seen = set(report.counts_by_code())
    assert not (set(item.forbid_codes) & seen), item.description


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_blocker_names_a_real_element_and_a_known_code(name: str) -> None:
    item = FIXTURES[name]
    report = run_gate(item.ir, item.texts)
    known_codes = {
        value
        for key, value in vars(codes).items()
        if key.isupper() and isinstance(value, str)
    }
    known_ids = (
        set(item.ir.clause_index())
        | set(item.ir.decision_index())
        | set(item.ir.process_index())
        | {edge.edge_id for edge in item.ir.dependencies}
    )
    for blocker in report.all_blockers():
        assert blocker.code in known_codes, blocker
        assert blocker.element_id in known_ids, blocker
        assert blocker.message.strip(), blocker


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_report_serialises_to_json_safe_structures(name: str) -> None:
    import json

    item = FIXTURES[name]
    report = run_gate(item.ir, item.texts)
    json.dumps(report.to_dict())


def test_a_clause_never_marks_itself_eligible() -> None:
    """Eligibility lives in the report, not in the record, so nothing self-certifies."""
    clause = FIXTURES["eligibility_decision"].ir.clauses[0]
    serialised = clause.to_dict()
    for forbidden in ("validation_status", "dmn_eligible", "eligible", "statuses"):
        assert forbidden not in serialised


def test_compilation_intent_is_a_request_not_a_permission() -> None:
    """A clause asking for DMN does not get it if the evidence does not support it."""
    item = FIXTURES["numeric_drift"]
    clause = item.ir.clauses[0]
    assert clause.compilation_intent.value == "dmn"
    report = run_gate(item.ir, item.texts)
    assert not report.clause_has(clause.clause_id, Status.DMN_ELIGIBLE)


def test_graph_eligibility_is_more_permissive_than_execution() -> None:
    """The product keeps working even when nothing is executable."""
    item = FIXTURES["numeric_drift"]
    report = run_gate(item.ir, item.texts)
    clause_id = item.ir.clauses[0].clause_id
    assert report.clause_has(clause_id, Status.GRAPH_ELIGIBLE)
    assert not report.clause_has(clause_id, Status.SEMANTIC_SUPPORTED)


def test_statuses_are_independent_not_a_single_ladder() -> None:
    item = FIXTURES["numeric_drift"]
    report = run_gate(item.ir, item.texts)
    statuses = report.clauses[item.ir.clauses[0].clause_id].statuses
    assert Status.PROVENANCE_EXACT in statuses
    assert Status.SEMANTIC_SUPPORTED not in statuses


def test_fixture_names_are_stable() -> None:
    assert "eligibility_decision" in fixture_names()
    assert len(fixture_names()) == len(set(fixture_names()))
