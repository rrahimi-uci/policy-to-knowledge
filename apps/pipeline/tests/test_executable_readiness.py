from copy import deepcopy
from importlib import import_module

from tests.test_rule_contract import valid_rule
from utils.kg_readiness import derive_dependency_chains, referential_integrity_issues
from utils.rule_contract import validate_rule_v2


readiness_module = import_module("agents.agent_5_5_executable_readiness")
ExecutableReadinessCompleter = readiness_module.ExecutableReadinessCompleter
normalise_graph_entity_names = readiness_module._normalise_graph_entity_names
normalise_rule_contract = readiness_module._normalise_rule_contract


class Resolver:
    def complete_rule(self, rule, corpus):
        return {
            "exceptions": [],
            "exception_basis": "explicitly_none_in_source",
            "exception_verification": {
                "status": "explicitly_none_in_source",
                "searched_document_ids": ["organized_corpus"],
                "searched_chunk_count": corpus["searched_chunk_count"],
                "evidence": [],
                "unresolved_reason": None,
            },
            "applicability_scope": {
                "loan_types": ["conventional"],
                "occupancy_types": [],
                "transaction_types": [],
            },
            "scope_basis": "explicit",
            "scope_derivation": {
                "status": "explicit",
                "evidence": [{"chunk_path": "B2-1-01/001.txt", "section_id": "B2-1-01", "source_text": "conventional loan"}],
                "unresolved_reason": None,
            },
        }

    def analyse_entity(self, entity, rules):
        return [{
            "entity": entity,
            "rule_ids": [rule["rule_id"] for rule in rules],
            "status": "non_conflict",
            "reasoning": "The output variables differ and each rule addresses a separate decision.",
            "resolution": "No conflict; both decisions may execute.",
        }]


def graph_with_two_rules():
    first = valid_rule()
    second = deepcopy(first)
    second["rule_id"] = "BR-2"
    second["rule_name"] = "A separate pool decision"
    second["outcomes"][0]["variable"] = "secondary_output"
    second["variables"][-1]["name"] = "secondary_output"
    second["test_vectors"][0]["expected_output"] = {"secondary_output": 3}
    return {
        "business_rules": [first, second],
        "entity_types": {"SELLER_SERVICER": {}, "FANNIE_MAE": {}},
        "relationships": [],
        "dependency_details": {"dependencies": [{"source_rule_id": "BR-1", "target_rule_id": "BR-2", "dependency_type": "prerequisite"}]},
    }


def test_completion_emits_ready_dmn_rules_and_required_report(tmp_path):
    organized = tmp_path / "organized" / "B2-1-01"
    organized.mkdir(parents=True)
    (organized / "001.txt").write_text("A seller servicer must limit pools to three.")
    baseline = graph_with_two_rules()

    final_graph, report = ExecutableReadinessCompleter(Resolver()).complete(baseline, baseline, str(tmp_path / "organized"))

    assert report["invariants"]["corpus_integrity"]["pass"] is True
    assert report["invariants"]["naming_consistency"]["pass"] is True
    assert report["invariants"]["referential_integrity"]["pass"] is True
    assert report["conflicts_and_dependencies"]["dependency_chains_derived"] == 1
    assert all(rule["execution"]["targets"] == ["DMN"] for rule in final_graph["business_rules"])
    assert all(rule["requires_review"] is False for rule in final_graph["business_rules"])


def test_dangling_reference_fails_the_invariant_without_silent_removal():
    graph = graph_with_two_rules()
    graph["dependency_details"]["dependencies"].append({"source_rule_id": "BR-2", "target_rule_id": "BR-MISSING"})

    issues = referential_integrity_issues(graph)

    assert issues == [{"rule_id": "<graph>", "path": "dependency_details.dependencies[1].target_rule_id", "missing_rule_id": "BR-MISSING"}]


def test_chain_traversal_is_graph_derived_and_cycle_safe():
    chains, cycles = derive_dependency_chains([
        {"source_rule_id": "A", "target_rule_id": "B", "dependency_type": "prerequisite"},
        {"source_rule_id": "B", "target_rule_id": "C", "dependency_type": "conditional"},
        {"source_rule_id": "C", "target_rule_id": "B", "dependency_type": "override"},
    ])

    assert chains == [{"rule_ids": ["A", "B", "C"], "dependency_types": ["prerequisite", "conditional"]}]
    assert cycles == [["B", "C", "B"]]


def test_legacy_naming_and_rule_shapes_normalise_to_one_v2_contract():
    rule = valid_rule()
    rule["responsible_party"] = "MortgagePool"
    rule["counterparties"] = ["ManufacturedHome"]
    rule["variables"].append({"name": "review_note", "type": "string", "role": "input"})
    rule["condition_predicates"].append({
        "predicate_id": "p2",
        "variable": "price_differential_amount",
        "operator": "IN",
        "value": [1, 2],
        "value_type": "number_list",
    })
    rule["condition_logic"] = {
        "any": [
            {"all": [{"predicate_ref": "p1"}, {"predicate_ref": "p2"}]},
            {"predicate_ref": "p1"},
        ]
    }
    rule["outcomes"][0]["operator"] = "<="
    rule["test_vectors"][0]["vector_basis"] = "derived_from_source_threshold_text"
    rule["exceptions"] = [{
        "variable": "price_differential_amount",
        "operator": "=",
        "value": 10,
    }]
    graph = normalise_graph_entity_names({
        "entity_types": {"MortgagePool": {}, "ManufacturedHome": {}},
        "business_rules": [rule],
    })
    rule = graph["business_rules"][0]

    normalise_rule_contract(rule)
    issues = validate_rule_v2(rule, graph["entity_types"])

    assert set(graph["entity_types"]) == {"MORTGAGE_POOL", "MANUFACTURED_HOME"}
    assert rule["responsible_party"] == "MORTGAGE_POOL"
    assert rule["counterparties"] == ["MANUFACTURED_HOME"]
    assert issues == []
    assert rule["test_vectors"][0]["vector_basis"] == "derived_from_source"
    assert rule["variables"][-1]["free_text"] is True


# ─────────────────────────────────────────────────────────────────────────
# exception_basis / scope_basis: a free-text explanation instead of an enum
# member must be coerced to the unresolved final state, not left as a raw v2
# schema violation with no actionable path. Real values observed on one run:
# "unresolved_insufficient_evidence", "explicit_in_source_but_details_not_
# in_evidence_packet", "unresolved_in_source_reference", and a full sentence
# of the model's own reasoning used wholesale as the enum value.
# ─────────────────────────────────────────────────────────────────────────

def test_off_schema_exception_basis_is_coerced_to_unresolved_and_keeps_its_reason():
    rule = valid_rule()
    rule["exception_basis"] = "explicit_in_source_but_details_not_in_evidence_packet"
    rule["exception_verification"] = {"state": "explicit_in_source_but_details_not_in_evidence_packet", "source_quote": "see B2-3-05 for exceptions"}

    normalise_rule_contract(rule)

    assert rule["exception_basis"] == "unresolved_after_full_document_search"
    assert rule["exception_verification"]["unresolved_reason"] == "explicit_in_source_but_details_not_in_evidence_packet"


def test_off_schema_exception_basis_with_non_dict_verification_is_upgraded_to_a_dict():
    """A bare-string exception_verification (a separate observed shape defect)
    must not block the coercion — it must end up a proper dict afterward."""
    rule = valid_rule()
    rule["exception_basis"] = "unresolved_in_source_reference"
    rule["exception_verification"] = "Unresolved: verification criteria are not present in the provided evidence text."

    normalise_rule_contract(rule)

    assert rule["exception_basis"] == "unresolved_after_full_document_search"
    assert isinstance(rule["exception_verification"], dict)
    assert rule["exception_verification"]["unresolved_reason"] == "unresolved_in_source_reference"


def test_off_schema_scope_basis_is_coerced_to_unresolved_after_source_review():
    rule = valid_rule()
    rule["scope_basis"] = "unresolved_insufficient_evidence"
    rule["scope_derivation"] = "no clean scope statement found"

    normalise_rule_contract(rule)

    assert rule["scope_basis"] == "unresolved_after_source_review"
    assert rule["scope_derivation"]["unresolved_reason"] == "unresolved_insufficient_evidence"


def test_valid_exception_basis_values_are_left_untouched():
    """The coercion must only ever fire on a genuinely off-schema string —
    every documented value, including the candidate-only ones, passes through."""
    for basis in ("explicit_in_source", "explicitly_none_in_source", "unresolved_after_full_document_search", "not_found_in_chunk_recheck_needed"):
        rule = valid_rule()
        rule["exceptions"] = [{"predicate_id": "ex1", "variable": "x", "operator": "==", "value": 1, "value_type": "number"}]
        rule["exception_basis"] = basis
        rule["exception_verification"] = {"unresolved_reason": ""}

        normalise_rule_contract(rule)

        assert rule["exception_basis"] == basis
        assert rule["exception_verification"]["unresolved_reason"] == ""


def test_evidence_limited_final_state_stays_under_review(tmp_path):
    organized = tmp_path / "organized" / "B2-1-01"
    organized.mkdir(parents=True)
    (organized / "001.txt").write_text("The exception cannot be expressed from the available variables.")
    graph = graph_with_two_rules()
    for rule in graph["business_rules"]:
        rule["exception_basis"] = "unresolved_after_full_document_search"
        rule["exception_verification"] = {
            "searched_chunk_count": 1,
            "unresolved_reason": "The cited source does not define the necessary decision variable.",
        }
        rule["scope_basis"] = "genuinely_unscoped"
        rule["scope_derivation"] = {"reviewed_chunk_count": 1}

    final_graph, report = ExecutableReadinessCompleter().complete(
        graph, graph, str(tmp_path / "organized")
    )

    assert report["invariants"]["schema_consistency"]["pass"] is True
    assert all(rule["requires_review"] is True for rule in final_graph["business_rules"])
    assert all("necessary decision variable" in rule["readiness"]["review_reason"] for rule in final_graph["business_rules"])


def test_uncovered_pairs_use_mechanical_disjoint_proof_before_falling_back_to_unresolved(tmp_path):
    """entity_conflict_analysis.txt only asks the model for "every material
    pair or an unresolved group" — a small entity group's single-call
    response can legitimately omit a pair it judged too obviously safe to
    name. Before this fix, every such gap became a generic "unresolved,
    manual review required" entry even when the two rules provably cannot
    conflict (disjoint outcome variables) — the same proof the large-group
    (> KG_CONFLICT_MAX_RULES_PER_CALL) code path already applied. On the real
    fannie_mae_readiness_20260822 run this filler accounted for 792 of the
    review-required determinations, the single largest driver in the graph."""
    organized = tmp_path / "organized" / "B2-1-01"
    organized.mkdir(parents=True)
    (organized / "001.txt").write_text("A seller servicer must limit pools to three.")

    first = valid_rule()
    second = deepcopy(first)
    second["rule_id"] = "BR-2"
    second["rule_name"] = "A separate pool decision"
    second["outcomes"][0]["variable"] = "secondary_output"
    second["variables"][-1]["name"] = "secondary_output"
    second["test_vectors"][0]["expected_output"] = {"secondary_output": 3}
    third = deepcopy(first)
    third["rule_id"] = "BR-3"
    third["rule_name"] = "A rule sharing BR-1's outcome variable"
    # third keeps `first`'s outcome variable, so (BR-1, BR-3) genuinely overlaps.

    graph = {
        "business_rules": [first, second, third],
        "entity_types": {"SELLER_SERVICER": {}, "FANNIE_MAE": {}},
        "relationships": [],
        "dependency_details": {"dependencies": []},
    }

    class PartialResolver(Resolver):
        def analyse_entity(self, entity, rules):
            # Only ever reports the BR-1/BR-2 pair, exactly as a model would
            # when it judges the remaining pairs immaterial to name — every
            # pair touching BR-3 is left uncovered.
            covered = [rule["rule_id"] for rule in rules if rule["rule_id"] in {"BR-1", "BR-2"}]
            if len(covered) < 2:
                return []
            return [{
                "entity": entity,
                "rule_ids": covered,
                "status": "non_conflict",
                "reasoning": "The output variables differ and each rule addresses a separate decision.",
                "resolution": "No conflict; both decisions may execute.",
            }]

    final_graph, _report = ExecutableReadinessCompleter(PartialResolver()).complete(
        graph, graph, str(tmp_path / "organized")
    )

    conflicts = final_graph["dependency_details"]["conflicts"]
    by_pair = {
        tuple(sorted(entry["rule_ids"])): entry
        for entry in conflicts
        if len(entry.get("rule_ids", [])) == 2
    }

    disjoint_pair = by_pair[("BR-2", "BR-3")]
    assert disjoint_pair["status"] == "non_conflict"
    assert "disjoint outcome variables" in disjoint_pair["reasoning"]

    overlapping_pair = by_pair[("BR-1", "BR-3")]
    assert overlapping_pair["status"] == "unresolved"
    assert "share an outcome variable" in overlapping_pair["reasoning"]
