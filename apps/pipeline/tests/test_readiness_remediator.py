from copy import deepcopy

from agents.agent_5_6_readiness_remediator import ReadinessRemediator
from tests.test_executable_readiness import graph_with_two_rules


class Resolver:
    model = "test-model"
    reasoning_effort = "medium"

    def complete(self, prompt_name, field, payload, max_tokens):
        if field == "remediations":
            import json
            packets = json.loads(payload["remediation_json"])
            return [{
                "rule_id": packet["rule"]["rule_id"],
                "variables_to_add": [{"name": "exception_applies", "type": "boolean", "role": "input"}],
                "exceptions": [{
                    "predicate_id": "ex1", "variable": "exception_applies",
                    "operator": "==", "value": True, "value_type": "boolean",
                }],
                "exception_basis": "explicit_in_source",
                "exception_verification": {
                    "status": "explicit_in_source",
                    "evidence": [{
                        "chunk_path": "B2-1-01/001.txt", "section_id": "B2-1-01",
                        "source_text": "Except when exception_applies.",
                    }],
                    "unresolved_reason": None,
                },
                "applicability_scope": {"loan_types": ["conventional"], "occupancy_types": [], "transaction_types": []},
                "scope_basis": "explicit",
                "scope_derivation": {
                    "status": "explicit",
                    "evidence": [{
                        "chunk_path": "B2-1-01/001.txt", "section_id": "B2-1-01",
                        "source_text": "A conventional loan.",
                    }],
                    "unresolved_reason": None,
                },
            } for packet in packets]
        import json
        pairs = json.loads(payload["conflicts_json"])
        return [{
            "entity": pair["entity"],
            "rule_ids": pair["rule_ids"],
            "status": "non_conflict",
            "reasoning": "Both conditions may fire, but the output variables are disjoint.",
            "resolution": "Preserve both independent output assignments.",
            "hit_policy_updates": [],
        } for pair in pairs]


def test_agent_5_6_targets_review_rules_and_revalidates(tmp_path, monkeypatch):
    organized = tmp_path / "organized" / "B2-1-01"
    organized.mkdir(parents=True)
    (organized / "001.txt").write_text("A conventional loan. Except when exception_applies.")
    baseline = graph_with_two_rules()
    graph = deepcopy(baseline)
    graph["dependency_details"]["conflicts"] = [{
        "entity": "SELLER_SERVICER",
        "rule_ids": ["BR-1", "BR-2"],
        "status": "unresolved",
        "reasoning": "Pair was not returned.",
        "resolution": "",
    }]
    for rule in graph["business_rules"]:
        rule["requires_review"] = True
        rule["readiness"] = {
            "status": "review_required",
            "failed_requirements": [
                {"requirement": "exceptions", "reason": "Exception needs a typed variable."},
                {"requirement": "conflicts", "reason": "Pair was not returned."},
            ],
            "review_reason": "Exception and conflict unresolved.",
        }
        rule["exception_basis"] = "unresolved_after_full_document_search"
        rule["exception_verification"] = {
            "searched_chunk_count": 1,
            "unresolved_reason": "Exception needs a typed variable.",
        }
        rule["scope_basis"] = "explicit"
        rule["scope_derivation"] = {
            "reviewed_chunk_count": 1,
            "evidence": [{
                "chunk_path": "B2-1-01/001.txt", "section_id": "B2-1-01",
                "source_text": "A conventional loan.",
            }],
        }

    monkeypatch.setenv("KG_REMEDIATION_MAX_PASSES", "2")
    final_graph, report = ReadinessRemediator(Resolver()).remediate(
        baseline, graph, tmp_path / "organized", tmp_path / "output"
    )

    assert report["rules_requiring_review"] == 0
    assert report["remediation"]["rules_made_ready"] == 2
    assert all(rule["requires_review"] is False for rule in final_graph["business_rules"])
    assert all(any(variable["name"] == "exception_applies" for variable in rule["variables"]) for rule in final_graph["business_rules"])
    assert final_graph["dependency_details"]["conflicts"][0]["status"] == "non_conflict"


def test_multi_rule_unresolved_conflict_expands_to_every_pair():
    graph = graph_with_two_rules()
    third = deepcopy(graph["business_rules"][0])
    third["rule_id"] = "BR-3"
    graph["business_rules"].append(third)
    graph["dependency_details"]["conflicts"] = [{
        "entity": "SELLER_SERVICER",
        "rule_ids": ["BR-1", "BR-2", "BR-3"],
        "status": "unresolved",
        "reasoning": "Legacy group analysis.",
        "resolution": "",
    }]

    candidates = ReadinessRemediator._conflict_candidates(graph)

    assert {tuple(candidate["rule_ids"]) for candidate in candidates} == {
        ("BR-1", "BR-2"), ("BR-1", "BR-3"), ("BR-2", "BR-3")
    }


def test_multi_value_output_contract_is_graph_wide_and_resolves_collect_collision():
    graph = graph_with_two_rules()
    left, right = graph["business_rules"]
    for rule, value in ((left, "036"), (right, 343)):
        rule["variables"].append({"name": "required_special_feature_code", "type": "string", "role": "output"})
        rule["outcomes"] = [{
            "variable": "required_special_feature_code", "operator": "=",
            "value": value, "value_type": "string" if isinstance(value, str) else "number",
        }]
        rule["recommended_hit_policy"] = "COLLECT"
    right["outcomes"][0]["value"] = ["343"]
    right["outcomes"][0]["value_type"] = "list"
    conflict = {
        "entity": "RELATIONSHIP", "rule_ids": [left["rule_id"], right["rule_id"]],
        "status": "unresolved", "reasoning": "Scalar/list drift.", "resolution": "",
    }

    names = ReadinessRemediator._normalise_multi_value_outputs(graph["business_rules"])
    by_id = {rule["rule_id"]: rule for rule in graph["business_rules"]}
    ReadinessRemediator._resolve_collected_output_conflicts([conflict], by_id, names)

    assert names == {"required_special_feature_code"}
    assert left["outcomes"][0]["value"] == ["036"]
    assert all(rule["variables"][-1]["type"] == "list" for rule in graph["business_rules"])
    assert conflict["status"] == "non_conflict"
    assert conflict["resolution"]
