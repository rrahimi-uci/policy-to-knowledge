"""Supersession and in-force queries.

``Lifecycle.SUPERSEDED`` on its own records a status without recording the
replacement, which makes "what applied on this date" unanswerable. These tests pin
the edge-based model and the ``--as-of`` filter, including the property that makes
the filter safe: the date is always an explicit input, never a read of the clock.
"""

from __future__ import annotations

import datetime as dt

from compilers.run import compile_all
from fixtures import all_fixtures
from policy_ir.enums import Status
from policy_ir.timeline import (
    clause_in_force_on,
    in_force_clause_ids,
    in_force_on,
    supersedes,
    superseded_by,
    supersession_chain,
    supersession_cycles,
    unknown_in_force_clause_ids,
)
from validation import blockers as codes
from validation import run_gate

OLD = "clause_two_years_of_returns"
NEW = "clause_one_year_of_returns"


def fixture_ir(name: str = "superseded_documentation"):
    item = all_fixtures()[name]
    return item.ir, item.texts


# -- the edge model ---------------------------------------------------------


def test_supersession_is_recorded_as_an_edge_in_both_directions() -> None:
    ir, _ = fixture_ir()
    assert superseded_by(ir, OLD) == (NEW,)
    assert supersedes(ir, NEW) == (OLD,)
    assert supersession_chain(ir, OLD) == (OLD, NEW)
    assert supersession_chain(ir, NEW) == (NEW,)


def test_a_missing_edge_is_reported_as_a_defect() -> None:
    ir, texts = fixture_ir("supersession_not_recorded")
    report = run_gate(ir, texts)
    assert codes.SUPERSESSION_NOT_RECORDED in report.clauses[OLD].codes()


def test_a_superseded_clause_stays_in_the_graph_but_cannot_compile() -> None:
    ir, texts = fixture_ir()
    report = run_gate(ir, texts)
    old = report.clauses[OLD]
    assert old.has(Status.GRAPH_ELIGIBLE)
    assert codes.SUPERSEDED_CLAUSE in old.codes()
    assert not old.has(Status.DMN_ELIGIBLE)
    assert not old.has(Status.BPMN_ELIGIBLE)


def test_a_supersession_cycle_is_detected() -> None:
    ir, _ = fixture_ir()
    edge = ir.dependencies[0]
    reverse = type(edge)(
        **{
            **{f: getattr(edge, f) for f in edge.__dataclass_fields__},
            "edge_id": "dep_reverse",
            "source_id": edge.target_id,
            "target_id": edge.source_id,
        }
    )
    cyclic = type(ir)(
        **{
            **{f: getattr(ir, f) for f in ir.__dataclass_fields__},
            "dependencies": (edge, reverse),
        }
    )
    assert supersession_cycles(cyclic)
    report = run_gate(cyclic, {})
    assert any(b.code == codes.SUPERSESSION_CYCLE for b in report.global_blockers)
    assert report.fatal


# -- historical queries ----------------------------------------------------


def test_the_older_standard_was_in_force_before_its_replacement_took_effect() -> None:
    ir, _ = fixture_ir()
    mid_2025 = dt.date(2025, 6, 1)
    assert in_force_on(ir, OLD, mid_2025) is True
    assert in_force_on(ir, NEW, mid_2025) is False
    assert in_force_clause_ids(ir, mid_2025) == frozenset({OLD})


def test_the_replacement_displaces_it_once_effective() -> None:
    ir, _ = fixture_ir()
    mid_2026 = dt.date(2026, 6, 1)
    assert in_force_on(ir, OLD, mid_2026) is False
    assert in_force_on(ir, NEW, mid_2026) is True
    assert in_force_clause_ids(ir, mid_2026) == frozenset({NEW})


def test_neither_was_in_force_before_the_earlier_start() -> None:
    ir, _ = fixture_ir()
    assert in_force_clause_ids(ir, dt.date(2024, 1, 1)) == frozenset()


def test_a_lifecycle_flag_does_not_veto_a_historical_query() -> None:
    """SUPERSEDED describes now; the edge and the dates describe history."""
    ir, _ = fixture_ir()
    old = ir.clause_index()[OLD]
    assert old.lifecycle.value == "superseded"
    assert clause_in_force_on(old, dt.date(2025, 6, 1)) is True


def test_an_active_unbounded_clause_is_in_force_not_unknown() -> None:
    """An author asserting ACTIVE with no bounds means "in force now"."""
    fee = all_fixtures()["fee_calculation"].ir
    on_date = dt.date(2026, 1, 1)
    assert unknown_in_force_clause_ids(fee, on_date) == frozenset()
    assert in_force_clause_ids(fee, on_date) == frozenset(
        clause.clause_id for clause in fee.clauses
    )


def test_an_unknown_lifecycle_with_no_dates_reports_unknown() -> None:
    fee = all_fixtures()["fee_calculation"].ir
    clauses = list(fee.clauses)
    clauses[0] = type(clauses[0])(
        **{
            **{f: getattr(clauses[0], f) for f in clauses[0].__dataclass_fields__},
            "lifecycle": type(clauses[0].lifecycle).UNKNOWN,
        }
    )
    mutated = type(fee)(
        **{**{f: getattr(fee, f) for f in fee.__dataclass_fields__}, "clauses": tuple(clauses)}
    )
    assert unknown_in_force_clause_ids(mutated, dt.date(2026, 1, 1)) == frozenset(
        {clauses[0].clause_id}
    )


def test_an_expired_clause_needs_an_end_date() -> None:
    ir, texts = fixture_ir()
    clauses = list(ir.clauses)
    clauses[0] = type(clauses[0])(
        **{
            **{f: getattr(clauses[0], f) for f in clauses[0].__dataclass_fields__},
            "lifecycle": type(clauses[0].lifecycle).EXPIRED,
        }
    )
    mutated = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "clauses": tuple(clauses)}
    )
    report = run_gate(mutated, texts)
    assert codes.INVALID_EFFECTIVE_PERIOD in report.clauses[OLD].codes()


# -- the as-of filter ------------------------------------------------------


def test_as_of_excludes_clauses_not_in_force() -> None:
    item = all_fixtures()["eligibility_decision"]
    # The eligibility clauses are ACTIVE and unbounded, so any date admits them.
    admitted = run_gate(item.ir, item.texts, as_of=dt.date(2026, 1, 1))
    assert admitted.decision_has("decision_purchase_eligibility", Status.DMN_ELIGIBLE)


def test_as_of_before_a_start_date_refuses_the_clause() -> None:
    ir, texts = fixture_ir()
    report = run_gate(ir, texts, as_of=dt.date(2024, 1, 1))
    assert codes.NOT_IN_FORCE in report.clauses[NEW].codes()


def test_as_of_is_recorded_in_the_manifest() -> None:
    item = all_fixtures()["eligibility_decision"]
    with_date = compile_all(item.ir, item.texts, as_of=dt.date(2026, 3, 3))
    without = compile_all(item.ir, item.texts)
    assert with_date.manifest["as_of"] == "2026-03-03"
    assert without.manifest["as_of"] is None


def test_as_of_keeps_output_byte_stable() -> None:
    """An explicit date is reproducible; reading the clock would not be."""
    item = all_fixtures()["eligibility_decision"]
    first = compile_all(item.ir, item.texts, as_of=dt.date(2026, 3, 3))
    second = compile_all(item.ir, item.texts, as_of=dt.date(2026, 3, 3))
    assert first.files() == second.files()
