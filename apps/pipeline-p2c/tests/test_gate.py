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


def test_the_engine_names_no_domain_actors() -> None:
    """Domain knowledge belongs in configuration, not in the engine's own tables.

    A marker like "no lender may" would work, and would quietly make the compiler
    lending-specific. The generic pattern covers every industry's actor noun, and
    this test stops the specific form from creeping back in.

    Prose is exempt: naming mortgages in a docstring as an illustration is useful.
    What is checked is *code* — identifiers and the string literals the engine acts
    on — which is where a domain assumption would actually change behaviour.
    """
    import ast
    import io
    import re
    import tokenize
    from pathlib import Path

    engine = Path(__file__).resolve().parent.parent
    packages = (
        "policy_ir",
        "validation",
        "compilers",
        "evaluation",
        "ingestion",
        "extraction",
        "adapters",
    )
    domain_nouns = re.compile(
        r"\b(lender|borrower|seller|servicer|patient|provider|policyholder|insurer|"
        r"mortgage|hipaa|medicare|medicaid)\b",
        re.IGNORECASE,
    )

    def docstring_lines(source: str) -> set[int]:
        tree = ast.parse(source)
        lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                first = body[0].value
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
        return lines

    offenders: list[str] = []
    for package in packages:
        for path in sorted((engine / package).rglob("*.py")):
            source = path.read_text()
            exempt = docstring_lines(source)
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.COMMENT:
                    continue
                if token.start[0] in exempt:
                    continue
                if token.type in (tokenize.NAME, tokenize.STRING) and domain_nouns.search(
                    token.string
                ):
                    offenders.append(
                        f"{path.relative_to(engine)}:{token.start[0]}: {token.string.strip()}"
                    )
    assert not offenders, "domain vocabulary found in engine code:\n" + "\n".join(offenders)
