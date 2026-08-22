"""Tests for Agent 5's structural-support check on inferred rule dependencies.

Note: the non-batched path in analyze_dependencies calls self.client directly
(self._json_request is used only by the batched/cross-batch paths), so the
integration tests below stub self.client.chat_completion, not _json_request.

Context: Agent 5.7's independent grounding verifier re-derives whether each
claimed rule-to-rule dependency actually follows from the two rules' own
condition/outcome logic, and on the fannie_mae readiness graph found 44% of
dependency/conflict claims did not hold up — the model's own reasoning showed
many were between rules that reference completely disjoint variables ("these
are independent requirement checks... different predicates, neither
references the other's outputs").

Before this fix, `analyze_dependencies` accepted every dependency the LLM
proposed with no deterministic check at all — acceptance was entirely "the
LLM said so." `dependency_has_structural_support` adds the weakest possible
deterministic signal (do the two rules share any variable name at all) and
`annotate_dependency_structural_support` discounts confidence when that
signal is absent, without ever silently dropping a dependency — a purely
procedural dependency ("check eligibility before pricing") can be real and
valid without sharing a variable, so this only flags, never deletes.
"""

from unittest.mock import MagicMock

from agents.agent_5_knowledge_graph_optimizer import (
    KnowledgeGraphOptimizer,
    _rule_variable_names,
    annotate_dependency_structural_support,
    dependency_has_structural_support,
)


# ─────────────────────────────────────────────────────────────────────────
# _rule_variable_names / dependency_has_structural_support — unit tests
# ─────────────────────────────────────────────────────────────────────────

def _rule(variables=(), condition_predicates=(), outcomes=()):
    return {
        "variables": [{"name": n} for n in variables],
        "condition_predicates": [{"variable": v} for v in condition_predicates],
        "outcomes": [{"variable": v} for v in outcomes],
    }


def test_rule_variable_names_collects_all_three_sources():
    rule = _rule(
        variables=["threshold_amount"],
        condition_predicates=["price_differential"],
        outcomes=["maximum_pools"],
    )
    assert _rule_variable_names(rule) == {"threshold_amount", "price_differential", "maximum_pools"}


def test_rule_variable_names_is_case_insensitive_and_trims_whitespace():
    rule = _rule(variables=["  Threshold_Amount  "])
    assert _rule_variable_names(rule) == {"threshold_amount"}


def test_shared_variable_is_structurally_supported():
    """The real, confirmed-valid pattern: rule B's condition references a
    variable rule A's outcome produces — a genuine data-flow dependency."""
    source = _rule(outcomes=["underwritten_as_high_ltv_refinance"])
    target = _rule(condition_predicates=["underwritten_as_high_ltv_refinance"])
    assert dependency_has_structural_support(source, target) is True


def test_disjoint_variables_are_not_structurally_supported():
    """The real, confirmed-false-positive pattern from the fannie_mae graph:
    two rules whose predicates never reference each other."""
    source = _rule(condition_predicates=["existing_loan_ltv_ratio"])
    target = _rule(condition_predicates=["mers_rider_state"], outcomes=["postclosing_assignment_prohibited"])
    assert dependency_has_structural_support(source, target) is False


def test_non_rule_inputs_are_not_structurally_supported():
    """A missing or malformed rule lookup must degrade to 'unsupported'
    rather than raising — annotate_dependency_structural_support relies on
    this when a dependency references an unknown rule_id."""
    assert dependency_has_structural_support(None, {"variables": []}) is False
    assert dependency_has_structural_support({"variables": []}, "not-a-dict") is False
    assert dependency_has_structural_support("nope", "nope") is False


def test_empty_variable_sets_are_not_structurally_supported():
    assert dependency_has_structural_support(_rule(), _rule()) is False


# ─────────────────────────────────────────────────────────────────────────
# annotate_dependency_structural_support
# ─────────────────────────────────────────────────────────────────────────

def test_supported_dependency_keeps_its_confidence():
    entry = {"confidence": 88}
    source = _rule(outcomes=["x"])
    target = _rule(condition_predicates=["x"])

    result = annotate_dependency_structural_support(entry, source, target)

    assert result is entry, "must mutate and return the same dict"
    assert entry["structurally_supported"] is True
    assert entry["confidence"] == 88, "a supported dependency's confidence must be untouched"


def test_unsupported_dependency_is_flagged_and_confidence_discounted():
    entry = {"confidence": 88}
    source = _rule(condition_predicates=["a"])
    target = _rule(condition_predicates=["b"])

    annotate_dependency_structural_support(entry, source, target)

    assert entry["structurally_supported"] is False
    assert entry["confidence"] == 50, "must be capped at the default unsupported ceiling"


def test_unsupported_dependency_never_raises_a_low_confidence_higher():
    """A dependency that already had low confidence for some other reason
    must not be pushed UP to the discount ceiling."""
    entry = {"confidence": 20}
    source = _rule(condition_predicates=["a"])
    target = _rule(condition_predicates=["b"])

    annotate_dependency_structural_support(entry, source, target)

    assert entry["confidence"] == 20


def test_custom_confidence_cap_is_respected():
    entry = {"confidence": 90}
    annotate_dependency_structural_support(entry, _rule(), _rule(), unsupported_confidence_cap=30)
    assert entry["confidence"] == 30


def test_non_numeric_confidence_is_left_alone():
    """Some callers store confidence as a qualitative label; discounting must
    not crash or corrupt a value it doesn't know how to compare."""
    entry = {"confidence": "medium"}
    annotate_dependency_structural_support(entry, _rule(), _rule())
    assert entry["confidence"] == "medium"
    assert entry["structurally_supported"] is False


# ─────────────────────────────────────────────────────────────────────────
# analyze_dependencies — integration through the real (non-batched) path
# ─────────────────────────────────────────────────────────────────────────

def _optimizer_with_dependencies(dependencies):
    import json as _json

    optimizer = object.__new__(KnowledgeGraphOptimizer)
    optimizer.model = "test-model"
    optimizer.reasoning_effort = "medium"
    optimizer.config = MagicMock()
    optimizer.config.get_optimizer_batch_size.return_value = 100
    optimizer.config.get_optimizer_description_truncation_length.return_value = 500
    optimizer.config.get_optimizer_dependency_temperature.return_value = 0.2
    optimizer.config.get_optimizer_dependency_max_tokens.return_value = 4000
    optimizer.prompt_manager = MagicMock()
    optimizer.prompt_manager.format_prompt.return_value = "irrelevant prompt text"

    payload = _json.dumps({"dependencies": dependencies})
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=payload))]
    optimizer.client = MagicMock()
    optimizer.client.chat_completion.return_value = response
    optimizer._calculate_dependency_confidence = KnowledgeGraphOptimizer._calculate_dependency_confidence.__get__(optimizer)
    return optimizer


def test_analyze_dependencies_flags_a_structurally_unsupported_claim():
    rules = [
        {"rule_id": "A", "condition_predicates": [{"variable": "existing_loan_ltv_ratio"}]},
        {"rule_id": "B", "condition_predicates": [{"variable": "mers_rider_state"}]},
    ]
    dependencies = [{
        "source_rule_id": "A", "target_rule_id": "B", "dependency_type": "prerequisite",
        "rationale": "Plausible but not entailed by either rule's own logic.",
        "strength": 4, "confidence": 90,
    }]
    optimizer = _optimizer_with_dependencies(dependencies)

    rules_with_deps, metadata = optimizer.analyze_dependencies(rules)

    rule_b = next(r for r in rules_with_deps if r["rule_id"] == "B")
    dep_entry = rule_b["dependencies"][0]
    assert dep_entry["structurally_supported"] is False
    assert dep_entry["confidence"] <= 50
    # The raw metadata (what optimize_parallel re-reads post-dedup) must carry
    # the same annotation, not just the per-rule entry.
    raw_dep = metadata["dependency_analysis"]["dependencies"][0]
    assert raw_dep["structurally_supported"] is False


def test_analyze_dependencies_leaves_a_supported_claim_at_full_confidence():
    rules = [
        {"rule_id": "A", "outcomes": [{"variable": "underwritten_as_high_ltv_refinance"}]},
        {"rule_id": "B", "condition_predicates": [{"variable": "underwritten_as_high_ltv_refinance"}]},
    ]
    dependencies = [{
        "source_rule_id": "A", "target_rule_id": "B", "dependency_type": "prerequisite",
        "rationale": "B's condition directly reads A's outcome variable.",
        "strength": 5, "confidence": 92,
    }]
    optimizer = _optimizer_with_dependencies(dependencies)

    rules_with_deps, metadata = optimizer.analyze_dependencies(rules)

    rule_b = next(r for r in rules_with_deps if r["rule_id"] == "B")
    dep_entry = rule_b["dependencies"][0]
    assert dep_entry["structurally_supported"] is True
    assert dep_entry["confidence"] == 92, "a genuinely supported dependency must not be discounted"
