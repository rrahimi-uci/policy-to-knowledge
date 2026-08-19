"""Authority precedence, and what it does to a declared conflict.

Before this, any declared conflict between two rows killed the whole decision.
That is the right default when nothing is known, but a regulated corpus routinely
holds a guide and a bulletin that disagree, and the resolution is a stated fact.
These tests pin all three outcomes: no real conflict, resolved, and unresolvable.
"""

from __future__ import annotations

from compilers.dmn import compile_dmn
from compilers.dmn_reference import read_decisions
from compilers.verify import validate_dmn
from fixtures import all_fixtures
from policy_ir.enums import Status
from policy_ir.scope import AuthoritySource
from validation import blockers as codes
from validation import run_gate
from validation.evidence_gate import _resolve_conflicts


def test_weight_is_the_only_thing_the_engine_compares() -> None:
    """Precedence is declared configuration, never inferred from a name or kind."""
    statute = AuthoritySource("a", "Statute", 100, kind="statute")
    bulletin = AuthoritySource("b", "Bulletin", 10, kind="bulletin")
    assert statute.outranks(bulletin)
    assert not bulletin.outranks(statute)
    assert not statute.outranks(AuthoritySource("c", "Other", 100))


def test_authority_round_trips() -> None:
    source = AuthoritySource(
        "auth_guide", "Selling Guide", 50, kind="guide", citation="Guide §3.1",
        effective_from="2026-01-01",
    )
    assert AuthoritySource.from_dict(source.to_dict()) == source


# -- resolved ---------------------------------------------------------------


def test_a_heavier_authority_resolves_the_conflict() -> None:
    item = all_fixtures()["authority_resolved_conflict"]
    report = run_gate(item.ir, item.texts)
    seen = set(report.counts_by_code())
    assert codes.OUTRANKED_BY_AUTHORITY in seen
    assert codes.UNRESOLVED_CONFLICT not in seen
    assert codes.AUTHORITY_TIE not in seen


def test_the_loser_stays_in_the_graph_but_cannot_compile() -> None:
    item = all_fixtures()["authority_resolved_conflict"]
    report = run_gate(item.ir, item.texts)
    loser = report.clauses["clause_bulletin_allows_below_640"]
    assert loser.has(Status.GRAPH_ELIGIBLE)
    assert not loser.has(Status.DMN_ELIGIBLE)
    assert not loser.has(Status.BPMN_ELIGIBLE)
    winner = report.clauses["clause_guide_denies_below_640"]
    assert winner.has(Status.DMN_ELIGIBLE)


def test_resolution_enables_compilation_rather_than_only_describing_it() -> None:
    """The point of resolving: the decision compiles from the surviving row."""
    item = all_fixtures()["authority_resolved_conflict"]
    report = run_gate(item.ir, item.texts)
    assert report.decision_has("decision_below_640", Status.DMN_ELIGIBLE)
    artifact = compile_dmn(item.ir, report)
    assert artifact.emitted_ids == ("decision_below_640",)
    assert validate_dmn(artifact.xml) == ()
    decision = read_decisions(artifact.xml)["decision_below_640"]
    assert len(decision.rules) == 1
    assert decision.rules[0].annotation == "clause_guide_denies_below_640"
    assert decision.evaluate_value({"borrower_credit_score": 600}) == "not_eligible"


def test_a_dropped_row_does_not_block_its_decision() -> None:
    """An outranked row is excluded by design, not a defect in the table."""
    item = all_fixtures()["authority_resolved_conflict"]
    report = run_gate(item.ir, item.texts)
    assert codes.ROW_NOT_ADMITTED not in report.decisions["decision_below_640"].codes()


# -- unresolvable -----------------------------------------------------------


def test_equal_weight_leaves_the_conflict_unresolved() -> None:
    item = all_fixtures()["authority_tie_conflict"]
    report = run_gate(item.ir, item.texts)
    seen = set(report.counts_by_code())
    assert codes.AUTHORITY_TIE in seen
    assert codes.UNRESOLVED_CONFLICT in seen
    assert codes.OUTRANKED_BY_AUTHORITY not in seen
    assert report.admitted_decisions() == ()


def test_a_missing_authority_leaves_the_conflict_unresolved() -> None:
    item = all_fixtures()["authority_resolved_conflict"]
    ir = item.ir
    stripped = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "authority_sources": ()}
    )
    report = run_gate(stripped, item.texts)
    seen = set(report.counts_by_code())
    # The clauses now cite authorities nobody declared, which is itself a defect,
    # and the conflict cannot be settled.
    assert codes.UNKNOWN_AUTHORITY in seen
    assert report.admitted_decisions() == ()


def test_an_undeclared_authority_reference_is_refused() -> None:
    item = all_fixtures()["authority_resolved_conflict"]
    ir = item.ir
    stripped = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "authority_sources": ()}
    )
    report = run_gate(stripped, item.texts)
    assert codes.UNKNOWN_AUTHORITY in report.clauses["clause_guide_denies_below_640"].codes()


# -- no real conflict -------------------------------------------------------


def test_disjoint_scopes_mean_there_was_no_conflict() -> None:
    item = all_fixtures()["disjoint_scope_conflict"]
    report = run_gate(item.ir, item.texts)
    seen = set(report.counts_by_code())
    assert codes.UNRESOLVED_CONFLICT not in seen
    assert codes.OUTRANKED_BY_AUTHORITY not in seen
    assert report.decision_has("decision_state_overlay", Status.DMN_ELIGIBLE)


def test_scope_is_checked_before_authority() -> None:
    """Two rules that cannot both apply need no precedence to separate them."""
    item = all_fixtures()["disjoint_scope_conflict"]
    clause_reports = dict(run_gate(item.ir, item.texts).clauses)
    outcomes = _resolve_conflicts(item.ir, clause_reports)
    assert [o.kind for o in outcomes] == ["disjoint_scope"]
    assert all(o.loser_id is None for o in outcomes)


def test_every_outcome_records_why() -> None:
    for name in ("authority_resolved_conflict", "authority_tie_conflict", "disjoint_scope_conflict"):
        item = all_fixtures()[name]
        clause_reports = dict(run_gate(item.ir, item.texts).clauses)
        for outcome in _resolve_conflicts(item.ir, clause_reports):
            assert outcome.kind in ("disjoint_scope", "resolved", "unresolved")
            assert outcome.reason.strip(), (name, outcome)
