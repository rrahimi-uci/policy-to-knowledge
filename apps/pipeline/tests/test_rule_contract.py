from copy import deepcopy

from utils.rule_contract import annotate_rule_contract, parse_rule_v2


def valid_rule():
    evidence = {
        "chunk_path": "B2-1-01/001.txt",
        "section_id": "B2-1-01",
        "source_text": "A seller servicer must limit the number of pools to three.",
    }
    return {
        "schema_version": "2.0",
        "rule_id": "BR-1",
        "condition_predicates": [
            {
                "predicate_id": "p1",
                "variable": "price_differential_amount",
                "operator": ">=",
                "value": "designated_threshold_amount",
                "value_type": "variable_reference",
            }
        ],
        "condition_logic": {"predicate_ref": "p1"},
        "outcomes": [
            {
                "variable": "maximum_number_of_pools",
                "operator": "=",
                "value": 3,
                "value_type": "number",
            }
        ],
        "variables": [
            {
                "name": "price_differential_amount",
                "type": "number",
                "unit": "USD",
                "allowed_range": [0, None],
                "role": "input",
            },
            {
                "name": "designated_threshold_amount",
                "type": "number",
                "unit": "USD",
                "role": "derived",
            },
            {
                "name": "maximum_number_of_pools",
                "type": "number",
                "role": "output",
            },
        ],
        "recommended_hit_policy": "UNIQUE",
        "versioning_status": "current_no_known_supersession",
        "applicability_scope": {"loan_types": ["conventional"]},
        "scope_basis": "inferred",
        "inference_reasoning": "The cited section is within the conventional-loan chapter.",
        "responsible_party": "SELLER_SERVICER",
        "counterparties": ["FANNIE_MAE"],
        "exceptions": [],
        "exception_basis": "explicitly_none_in_source",
        "test_vectors": [
            {
                "inputs": {"price_differential_amount": 100000},
                "expected_output": {"maximum_number_of_pools": 3},
                "vector_basis": "source_attested",
                "boundary_condition": True,
            }
        ],
        "source_reference": {
            **evidence,
            "text_match_score": 0.5,
            "reference_verified": True,
        },
        "field_evidence": {
            "condition_predicates": [evidence],
            "outcomes": [evidence],
            "responsible_party": [evidence],
            "scope_basis": [evidence],
            "versioning_status": [evidence],
            "exceptions": [evidence],
            "test_vectors": [evidence],
        },
    }


def test_valid_v2_rule_passes_contract_validation():
    result = parse_rule_v2(valid_rule(), {"SELLER_SERVICER", "FANNIE_MAE"})

    assert result.valid
    assert result.issues == []


def test_variable_reference_must_resolve_to_typed_variable():
    candidate = valid_rule()
    candidate["condition_predicates"][0]["value"] = "missing_threshold"

    result = parse_rule_v2(candidate, {"SELLER_SERVICER", "FANNIE_MAE"})

    assert any(issue.code == "undefined_variable_reference" for issue in result.issues)


def test_mixed_logic_must_reference_every_predicate_once():
    candidate = valid_rule()
    candidate["condition_predicates"].append(
        {
            "predicate_id": "p2",
            "variable": "price_differential_amount",
            "operator": "<",
            "value": 500000,
            "value_type": "number",
        }
    )
    candidate["condition_logic"] = {"all": [{"predicate_ref": "p1"}]}

    result = parse_rule_v2(candidate, {"SELLER_SERVICER", "FANNIE_MAE"})

    assert any(issue.code == "predicate_logic_coverage" for issue in result.issues)


def test_contract_annotation_retains_invalid_candidate_and_marks_review():
    candidate = deepcopy(valid_rule())
    candidate.pop("variables")

    annotated = annotate_rule_contract(candidate, {"SELLER_SERVICER", "FANNIE_MAE"})

    assert annotated["rule_id"] == "BR-1"
    assert annotated["requires_review"] is True
    assert any(issue["code"] == "missing_variables" for issue in annotated["contract_issues"])


def test_exception_predicates_must_reference_declared_variables():
    candidate = valid_rule()
    candidate["exceptions"] = [
        {
            "predicate_id": "e1",
            "variable": "unknown_exception_flag",
            "operator": "==",
            "value": True,
            "value_type": "boolean",
        }
    ]

    result = parse_rule_v2(candidate, {"SELLER_SERVICER", "FANNIE_MAE"})

    assert any(issue.code == "undefined_exception_variable" for issue in result.issues)


def test_string_variables_must_be_explicitly_free_text():
    candidate = valid_rule()
    candidate["variables"].append(
        {"name": "document_identifier", "type": "string", "role": "input"}
    )

    result = parse_rule_v2(candidate, {"SELLER_SERVICER", "FANNIE_MAE"})

    assert any(issue.code == "unjustified_string_variable" for issue in result.issues)
