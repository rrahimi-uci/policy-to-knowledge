"""Contextual scope: the reasoning, and its effect on compilation.

Scope only earns its place if it changes what compiles. The central test here is
that two state overlays with overlapping credit-score bands become provably
non-overlapping once the jurisdiction axis is an input column — without it, UNIQUE
is refused and neither rule compiles.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from compilers.dmn import DMN_MODEL_NS, compile_dmn
from compilers.dmn_reference import read_decisions
from compilers.verify import validate_dmn
from fixtures import all_fixtures
from policy_ir.enums import DataType, Status
from policy_ir.expressions import Comparison, ComparisonOperator as Op, Literal, VariableRef
from policy_ir.scope import Scope, ScopeDimension, ScopeDimensionDefinition
from policy_ir.tabular import Row, decompose, prove_disjoint, scope_atoms, scope_input_key
from validation import blockers as codes
from validation import run_gate

NS = {"dmn": DMN_MODEL_NS}
CA = ScopeDimension("jurisdiction", ("US-CA",))
NY = ScopeDimension("jurisdiction", ("US-NY",))
NOT_CA = ScopeDimension("jurisdiction", ("US-CA",), negated=True)
PURCHASE = ScopeDimension("product", ("purchase",))


# -- reasoning --------------------------------------------------------------


def test_a_universal_scope_applies_everywhere() -> None:
    assert Scope().is_universal
    assert Scope().applies_to({}) is True


def test_applicability_is_three_valued() -> None:
    scope = Scope((CA,))
    assert scope.applies_to({"jurisdiction": "US-CA"}) is True
    assert scope.applies_to({"jurisdiction": "US-NY"}) is False
    # Not told which state: "we do not know" must not read as "does not apply".
    assert scope.applies_to({}) is None


def test_a_definite_miss_settles_a_multi_axis_scope() -> None:
    scope = Scope((CA, PURCHASE))
    assert scope.applies_to({"jurisdiction": "US-CA", "product": "refinance"}) is False
    assert scope.applies_to({"jurisdiction": "US-CA"}) is None
    assert scope.applies_to({"jurisdiction": "US-CA", "product": "purchase"}) is True


def test_negated_dimensions_invert() -> None:
    assert Scope((NOT_CA,)).applies_to({"jurisdiction": "US-CA"}) is False
    assert Scope((NOT_CA,)).applies_to({"jurisdiction": "US-NY"}) is True


def test_a_context_may_supply_several_values_for_one_axis() -> None:
    assert Scope((CA,)).applies_to({"jurisdiction": ["US-NY", "US-CA"]}) is True
    assert Scope((CA,)).applies_to({"jurisdiction": ["US-NY", "US-TX"]}) is False


def test_disjointness_is_only_claimed_when_provable() -> None:
    assert Scope((CA,)).overlaps(Scope((NY,))) is False
    assert Scope((CA,)).overlaps(Scope((NOT_CA,))) is False
    # A shared axis that intersects, or an axis only one side constrains, cannot
    # separate them.
    assert Scope((CA,)).overlaps(Scope((CA, PURCHASE))) is True
    assert Scope((CA,)).overlaps(Scope((PURCHASE,))) is True
    assert Scope((CA,)).overlaps(Scope()) is True


def test_two_negations_are_never_provably_disjoint() -> None:
    """The axis vocabulary is open, so some third value may satisfy both."""
    other = ScopeDimension("jurisdiction", ("US-NY",), negated=True)
    assert Scope((NOT_CA,)).overlaps(Scope((other,))) is True


def test_an_axis_cannot_be_constrained_twice() -> None:
    from policy_ir._parsing import SchemaError

    with pytest.raises(SchemaError, match="more than once"):
        Scope((CA, NY))


def test_a_dimension_must_constrain_something() -> None:
    from policy_ir._parsing import SchemaError

    with pytest.raises(SchemaError, match="at least one value"):
        ScopeDimension("jurisdiction", ())


def test_scope_round_trips() -> None:
    scope = Scope((CA, PURCHASE))
    assert Scope.from_dict(scope.to_dict()) == scope


# -- effect on the non-overlap proof ---------------------------------------


def _band_row(clause_id: str, threshold: int, scope: Scope) -> Row:
    atoms = decompose(
        Comparison(VariableRef("score"), Op.GE, Literal(threshold, DataType.NUMBER))
    )
    atoms.update(scope_atoms(scope))
    return Row(clause_id, atoms)


def test_scope_makes_overlapping_bands_provably_disjoint() -> None:
    rows = [_band_row("ca", 660, Scope((CA,))), _band_row("ny", 640, Scope((NY,)))]
    types = {"score": DataType.NUMBER, scope_input_key("jurisdiction"): DataType.STRING}

    with_scope = prove_disjoint(rows, types, ["score", scope_input_key("jurisdiction")])
    without_scope = prove_disjoint(rows, types, ["score"])

    assert with_scope.disjoint is True
    assert without_scope.disjoint is False, "the bands really do overlap on score alone"


def test_scope_keys_cannot_collide_with_data_definitions() -> None:
    """Data-definition IDs are XML NCNames, which cannot contain a colon."""
    assert ":" in scope_input_key("jurisdiction")


# -- effect on compilation --------------------------------------------------


def test_state_overlays_compile_because_jurisdiction_is_an_input() -> None:
    item = all_fixtures()["state_overlay_scope"]
    report = run_gate(item.ir, item.texts)
    assert report.decision_has("decision_state_overlay", Status.DMN_ELIGIBLE)
    assert codes.HIT_POLICY_NOT_PROVEN not in set(report.counts_by_code())


def test_the_emitted_table_carries_a_jurisdiction_column() -> None:
    item = all_fixtures()["state_overlay_scope"]
    artifact = compile_dmn(item.ir, run_gate(item.ir, item.texts))
    assert validate_dmn(artifact.xml) == ()
    decision = read_decisions(artifact.xml)["decision_state_overlay"]
    assert "scope_jurisdiction" in decision.input_names
    entries = {rule.rule_id: rule.input_entries for rule in decision.rules}
    assert '"US-CA"' in entries["rule_clause_overlay_us_ca"]
    assert '"US-NY"' in entries["rule_clause_overlay_us_ny"]


def test_the_declared_vocabulary_becomes_an_item_definition() -> None:
    item = all_fixtures()["state_overlay_scope"]
    artifact = compile_dmn(item.ir, run_gate(item.ir, item.texts))
    root = ET.fromstring(artifact.xml)
    names = [d.get("name") for d in root.findall("dmn:itemDefinition", NS)]
    assert "tscope_jurisdiction" in names
    allowed = root.find(".//dmn:itemDefinition[@name='tscope_jurisdiction']/dmn:allowedValues/dmn:text", NS)
    assert allowed is not None and "US-CA" in (allowed.text or "")


def test_the_reference_evaluator_honours_the_scope_column() -> None:
    item = all_fixtures()["state_overlay_scope"]
    artifact = compile_dmn(item.ir, run_gate(item.ir, item.texts))
    decision = read_decisions(artifact.xml)["decision_state_overlay"]
    # 650 clears New York's bar but not California's.
    assert decision.evaluate_value(
        {"borrower_credit_score": 650, "scope_jurisdiction": "US-NY"}
    ) == "eligible"
    assert decision.evaluate_value(
        {"borrower_credit_score": 650, "scope_jurisdiction": "US-CA"}
    ) is None
    assert decision.evaluate_value(
        {"borrower_credit_score": 700, "scope_jurisdiction": "US-CA"}
    ) == "eligible"


def test_an_undeclared_axis_is_refused() -> None:
    item = all_fixtures()["undeclared_scope_dimension"]
    report = run_gate(item.ir, item.texts)
    assert codes.UNKNOWN_SCOPE_DIMENSION in set(report.counts_by_code())
    assert report.admitted_decisions() == ()


def test_a_value_outside_the_declared_vocabulary_is_refused() -> None:
    item = all_fixtures()["state_overlay_scope"]
    ir = item.ir
    clauses = list(ir.clauses)
    clauses[0] = type(clauses[0])(
        **{
            **{f: getattr(clauses[0], f) for f in clauses[0].__dataclass_fields__},
            "scope": Scope(
                (
                    ScopeDimension(
                        "jurisdiction",
                        ("US-ZZ",),
                        evidence_ids=clauses[0].scope.dimensions[0].evidence_ids,
                    ),
                )
            ),
        }
    )
    mutated = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "clauses": tuple(clauses)}
    )
    report = run_gate(mutated, item.texts)
    assert codes.SCOPE_VALUE_NOT_ALLOWED in set(report.counts_by_code())


def test_an_unevidenced_scope_limit_is_refused() -> None:
    """A scope narrows what a rule reaches, so it needs support like any other field."""
    item = all_fixtures()["state_overlay_scope"]
    ir = item.ir
    clauses = list(ir.clauses)
    stripped = Scope((ScopeDimension("jurisdiction", ("US-CA",)),))
    clauses[0] = type(clauses[0])(
        **{
            **{f: getattr(clauses[0], f) for f in clauses[0].__dataclass_fields__},
            "scope": stripped,
        }
    )
    mutated = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "clauses": tuple(clauses)}
    )
    report = run_gate(mutated, item.texts)
    assert codes.MISSING_FIELD_EVIDENCE in set(report.counts_by_code())


def test_a_scope_dimension_definition_is_the_configuration_seam() -> None:
    """Adding a domain means adding declarations, not engine code."""
    definition = ScopeDimensionDefinition(
        dimension_id="dim_payer",
        name="payer",
        allowed_values=("medicare", "medicaid", "commercial"),
    )
    assert ScopeDimensionDefinition.from_dict(definition.to_dict()) == definition


def test_a_negated_jurisdiction_is_omitted_from_the_flat_legacy_field() -> None:
    """Legacy consumers read `jurisdiction` as an allow-list.

    Flattening "everywhere except California" to ``["US-CA"]`` would invert the
    meaning for anyone reading that field, so a negated constraint is omitted there
    and carried exactly in ``applicability_scope`` and ``scope`` instead.
    """
    from compilers.graph import project_graph

    item = all_fixtures()["state_overlay_scope"]
    ir = item.ir
    clauses = list(ir.clauses)
    original = clauses[0]
    clauses[0] = type(original)(
        **{
            **{f: getattr(original, f) for f in original.__dataclass_fields__},
            "scope": Scope(
                (
                    ScopeDimension(
                        "jurisdiction",
                        ("US-CA",),
                        negated=True,
                        evidence_ids=original.scope.dimensions[0].evidence_ids,
                    ),
                )
            ),
        }
    )
    mutated = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "clauses": tuple(clauses)}
    )
    graph = project_graph(mutated, run_gate(mutated, item.texts))
    rule = next(r for r in graph["business_rules"] if r["rule_id"] == original.clause_id)

    assert rule["jurisdiction"] == [], "a negation must not read as an allow-list"
    assert rule["applicability_scope"] == ["jurisdiction!=US-CA"]
    assert rule["scope"]["dimensions"][0]["negated"] is True


def test_a_positive_jurisdiction_still_reaches_the_flat_field() -> None:
    from compilers.graph import project_graph

    item = all_fixtures()["state_overlay_scope"]
    graph = project_graph(item.ir, run_gate(item.ir, item.texts))
    flat = {
        rule["rule_id"]: rule["jurisdiction"] for rule in graph["business_rules"]
    }
    assert flat["clause_overlay_us_ca"] == ["US-CA"]
    assert flat["clause_overlay_us_ny"] == ["US-NY"]
