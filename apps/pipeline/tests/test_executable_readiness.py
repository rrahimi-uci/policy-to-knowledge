from copy import deepcopy
from importlib import import_module

from tests.test_rule_contract import valid_rule
from utils.kg_readiness import derive_dependency_chains, referential_integrity_issues


ExecutableReadinessCompleter = import_module(
    "agents.agent_5_5_executable_readiness"
).ExecutableReadinessCompleter


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
