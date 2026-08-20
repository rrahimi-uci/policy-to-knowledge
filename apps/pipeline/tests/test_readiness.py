from tests.test_rule_contract import valid_rule
from utils.readiness import annotate_rule_readiness, assess_rule_readiness


CATALOG = {"SELLER_SERVICER", "FANNIE_MAE"}


def test_fully_valid_rule_is_ready_after_dependency_analysis():
    readiness = assess_rule_readiness(valid_rule(), CATALOG, dependency_complete=True)

    assert readiness["status"] == "ready"
    assert readiness["failed_sections"] == []
    assert readiness["pending_sections"] == []


def test_dependency_check_is_pending_until_agent_five_finishes():
    readiness = assess_rule_readiness(valid_rule(), CATALOG)

    assert readiness["status"] == "review_required"
    assert readiness["pending_sections"] == [2]
    assert readiness["checks"]["2_dependencies_conflicts_hit_policy"]["status"] == "pending"


def test_source_score_below_half_fails_section_seven():
    candidate = valid_rule()
    candidate["source_reference"]["text_match_score"] = 0.499

    readiness = assess_rule_readiness(candidate, CATALOG, dependency_complete=True)

    assert 7 in readiness["failed_sections"]
    assert readiness["checks"]["7_source_fidelity"]["reasons"][0]["code"] == "weak_text_match_score"


def test_source_score_at_half_and_verified_passes_section_seven():
    readiness = assess_rule_readiness(valid_rule(), CATALOG, dependency_complete=True)

    assert readiness["checks"]["7_source_fidelity"]["status"] == "pass"


def test_unverified_source_sets_review_without_dropping_rule():
    candidate = valid_rule()
    candidate["source_reference"]["reference_verified"] = False

    annotated = annotate_rule_readiness(candidate, CATALOG, dependency_complete=True)

    assert annotated["rule_id"] == "BR-1"
    assert annotated["requires_review"] is True
    assert 7 in annotated["readiness"]["failed_sections"]


def test_numeric_rule_requires_boundary_vector():
    candidate = valid_rule()
    candidate["test_vectors"][0]["boundary_condition"] = False

    readiness = assess_rule_readiness(candidate, CATALOG, dependency_complete=True)

    assert 8 in readiness["failed_sections"]
    assert readiness["checks"]["8_test_vectors"]["reasons"][-1]["code"] == "missing_numeric_boundary_vector"
