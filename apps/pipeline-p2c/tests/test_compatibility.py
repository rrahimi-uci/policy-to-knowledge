"""Backward compatibility with the legacy graph, tested against the real corpora.

These run over the four committed ``agent-5-optimized`` graphs, so they assert what
the adapter actually does to 1,481 real rules rather than to a toy. The headline
expectation is deliberately unflattering: every rule imports, every rule reaches
the graph, and *nothing* becomes DMN or BPMN. That is the plan's predicted outcome
for legacy artefacts, and a change that made it look better would be the bug.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters import import_legacy_graph
from compilers.graph import project_graph
from compilers.run import compile_all
from fixtures import all_fixtures
from policy_ir.enums import DependencyKind, EntityCategory, Provenance, SemanticKind, Status
from validation import blockers as codes
from validation import run_gate

from .conftest import legacy_graph_paths

LEGACY_PATHS = legacy_graph_paths()
requires_corpora = pytest.mark.skipif(
    not LEGACY_PATHS, reason="the committed legacy corpora are not present"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_every_legacy_rule_imports_and_reaches_the_graph(path: Path) -> None:
    graph = load(path)
    expected = len(graph["business_rules"])
    imported = import_legacy_graph(graph, graph_name=path.parts[-3])
    assert imported.imported_rules == expected
    report = run_gate(imported.ir, {})
    projected = project_graph(imported.ir, report, graph_name=path.parts[-3])
    assert projected["metadata"]["total_rules"] == expected


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_no_legacy_rule_becomes_executable(path: Path) -> None:
    imported = import_legacy_graph(load(path))
    report = run_gate(imported.ir, {})
    assert report.admitted_decisions() == ()
    assert report.admitted_processes() == ()
    assert not any(
        report.clause_has(clause.clause_id, Status.DMN_ELIGIBLE)
        for clause in imported.ir.clauses
    )
    assert not any(
        report.clause_has(clause.clause_id, Status.BPMN_ELIGIBLE)
        for clause in imported.ir.clauses
    )


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_legacy_rules_are_marked_unevidenced_rather_than_verified(path: Path) -> None:
    imported = import_legacy_graph(load(path))
    report = run_gate(imported.ir, {})
    seen = set(report.counts_by_code())
    assert seen == {codes.NO_EVIDENCE_CITED}
    projected = project_graph(imported.ir, report)
    assert all(not rule["reference_verified"] for rule in projected["business_rules"])
    assert all(
        not rule["compilation_status"]["dmn_eligible"] for rule in projected["business_rules"]
    )


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_legacy_rule_ids_survive_as_aliases(path: Path) -> None:
    """A historical ID must keep resolving after the migration."""
    graph = load(path)
    original_ids = [rule["rule_id"] for rule in graph["business_rules"]]
    imported = import_legacy_graph(graph)
    aliases = {alias for clause in imported.ir.clauses for alias in clause.legacy_rule_ids}
    assert set(original_ids) <= aliases


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_legacy_dependencies_are_downgraded_to_candidates(path: Path) -> None:
    imported = import_legacy_graph(load(path))
    for edge in imported.ir.dependencies:
        assert edge.derivation_method.value == "model_assisted_candidate"
        assert edge.kind in (
            DependencyKind.RELATED,
            DependencyKind.CONFLICT,
            DependencyKind.OVERRIDE,
        )


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_legacy_attributes_stay_unresolved_and_untyped(path: Path) -> None:
    """A bare attribute name cannot become a typed DMN input by being imported."""
    imported = import_legacy_graph(load(path))
    assert imported.ir.data_definitions
    for definition in imported.ir.data_definitions:
        assert definition.provenance is Provenance.UNRESOLVED
    for entity in imported.ir.entity_types:
        assert entity.category is EntityCategory.UNCLASSIFIED


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_the_adapter_fabricates_no_evidence_and_no_expressions(path: Path) -> None:
    imported = import_legacy_graph(load(path))
    assert imported.ir.evidence_spans == ()
    assert imported.ir.documents == ()
    for clause in imported.ir.clauses:
        assert clause.condition_ast is None
        assert clause.effect_ast is None
        assert clause.exception_ast is None


@requires_corpora
@pytest.mark.parametrize("path", LEGACY_PATHS, ids=lambda p: p.parts[-3])
def test_unrecognised_rule_types_stay_unclassified(path: Path) -> None:
    """Guessing a kind would create a clause guaranteed to fail its own contract."""
    imported = import_legacy_graph(load(path))
    kinds = {clause.semantic_kind for clause in imported.ir.clauses}
    assert SemanticKind.DECISION_RULE not in kinds
    assert kinds <= {
        SemanticKind.UNCLASSIFIED,
        SemanticKind.PROCESS_FRAGMENT,
        SemanticKind.CALCULATION,
        SemanticKind.VALIDATION,
        SemanticKind.DOCUMENTATION_REQUIREMENT,
        SemanticKind.AUTHORITY_STATEMENT,
    }


@requires_corpora
def test_both_legacy_source_reference_shapes_are_read() -> None:
    """Most corpora store an object; a minority store an array. Neither is lost."""
    from adapters.legacy_graph import _legacy_source_texts

    assert _legacy_source_texts({"source_reference": {"source_text": "a"}}) == ("a",)
    assert _legacy_source_texts(
        {"source_reference": [{"source_text": "a"}, {"source_text": "b"}]}
    ) == ("a", "b")
    assert _legacy_source_texts({"source_reference": None}) == ()
    seen_shapes = set()
    for path in LEGACY_PATHS:
        for rule in load(path)["business_rules"]:
            seen_shapes.add(type(rule.get("source_reference")).__name__)
    assert {"dict", "list"} <= seen_shapes


# -- forward compatibility of the v2 projection ----------------------------


def test_graph_projection_keeps_the_legacy_top_level_shape() -> None:
    item = all_fixtures()["notice_process"]
    result = compile_all(item.ir, item.texts, targets=("graph",))
    graph = result.graph
    assert graph is not None
    for key in (
        "metadata",
        "business_rules",
        "entity_types",
        "relationships",
        "dependency_details",
        "optimization_summary",
    ):
        assert key in graph
    rule = graph["business_rules"][0]
    for key in (
        "rule_id",
        "rule_name",
        "rule_type",
        "description",
        "conditions",
        "consequences",
        "exceptions",
        "source_reference",
        "mandatory",
        "data_points_required",
        "reference_verified",
    ):
        assert key in rule
    assert graph["metadata"]["artifact_role"] == "legacy_projection"


def test_no_supporting_span_disappears_in_projection() -> None:
    item = all_fixtures()["notice_process"]
    result = compile_all(item.ir, item.texts, targets=("graph",))
    projected = {
        reference["evidence_id"]
        for rule in result.graph["business_rules"]
        for reference in rule["source_reference"]
    }
    cited = {
        evidence_id for clause in item.ir.clauses for evidence_id in clause.all_evidence_ids()
    }
    assert cited <= projected


def test_every_artefact_shares_the_same_canonical_ids() -> None:
    item = all_fixtures()["notice_process"]
    result = compile_all(item.ir, item.texts)
    graph_ids = {rule["canonical_rule_id"] for rule in result.graph["business_rules"]}
    traced = set(result.traceability["clauses"])
    assert traced == set(item.ir.clause_index())
    assert graph_ids <= traced
    dmn_rules = {
        rule["clause_id"]
        for decision in result.traceability["artifacts"]["decisions.dmn"]["decisions"].values()
        for rule in decision["rules"]
    }
    assert dmn_rules <= graph_ids


def test_rollback_is_disabling_the_v2_targets() -> None:
    """The legacy projection stands alone, so v2 can be switched off wholesale."""
    item = all_fixtures()["notice_process"]
    result = compile_all(item.ir, item.texts, targets=("graph",))
    assert result.artifacts == ()
    assert "graph-v2.json" in result.files()
    assert "decisions.dmn" not in result.files()
    assert result.ok
