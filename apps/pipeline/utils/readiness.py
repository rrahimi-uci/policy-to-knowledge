"""Readiness evaluation for structured pipeline rules.

Readiness is a graph-quality status, not a decision to discard a rule. A rule
always remains in the output and records the exact requirements still needing
manual correction.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from utils.rule_contract import ContractIssue, validate_rule_v2

CHECK_NAMES = {
    1: "typed_logic_and_variables",
    2: "dependencies_conflicts_hit_policy",
    3: "versioning",
    4: "scope",
    5: "parties",
    6: "exceptions",
    7: "source_fidelity",
    8: "test_vectors",
}


def _check(status: str, reasons: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": status, "reasons": reasons}


def _issue_reasons(issues: Iterable[ContractIssue], section: int) -> list[dict[str, Any]]:
    return [
        {
            "code": issue.code,
            "path": issue.path,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in issues
        if issue.section == section
    ]


def _source_fidelity_reasons(rule: Mapping[str, Any]) -> list[dict[str, Any]]:
    reference = rule.get("source_reference")
    references = reference if isinstance(reference, list) else [reference]
    reasons: list[dict[str, Any]] = []

    for index, item in enumerate(references):
        path = f"source_reference[{index}]" if isinstance(reference, list) else "source_reference"
        if not isinstance(item, Mapping):
            reasons.append(
                {
                    "code": "invalid_source_reference",
                    "path": path,
                    "message": "A structured source reference is required.",
                    "severity": "error",
                }
            )
            continue
        verified = item.get("reference_verified", rule.get("reference_verified"))
        if verified is not True:
            reasons.append(
                {
                    "code": "unverified_source_reference",
                    "path": path,
                    "message": "reference_verified is not true; re-extract directly from the cited chunk.",
                    "severity": "error",
                }
            )
        score = item.get("text_match_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            reasons.append(
                {
                    "code": "missing_text_match_score",
                    "path": f"{path}.text_match_score",
                    "message": "text_match_score is required before finalization.",
                    "severity": "error",
                }
            )
        elif score < 0.5:
            reasons.append(
                {
                    "code": "weak_text_match_score",
                    "path": f"{path}.text_match_score",
                    "message": "Scores below 0.5 require direct source re-extraction.",
                    "severity": "error",
                }
            )

    return reasons


def _test_vector_boundary_reasons(rule: Mapping[str, Any]) -> list[dict[str, Any]]:
    variables = {
        str(variable.get("name", "")).strip().lower(): variable
        for variable in rule.get("variables", [])
        if isinstance(variable, Mapping)
    }
    numeric_inputs = {
        name
        for name, variable in variables.items()
        if variable.get("type") == "number" and variable.get("role") in {"input", "derived"}
    }
    if not numeric_inputs:
        return []

    boundary_variables = set()
    for vector in rule.get("test_vectors", []):
        if not isinstance(vector, Mapping):
            continue
        if vector.get("boundary_condition") is True:
            inputs = vector.get("inputs", {})
            if isinstance(inputs, Mapping):
                boundary_variables.update(str(name).strip().lower() for name in inputs)

    if numeric_inputs.intersection(boundary_variables):
        return []
    return [
        {
            "code": "missing_numeric_boundary_vector",
            "path": "test_vectors",
            "message": "Numeric rules require a boundary_condition test vector.",
            "severity": "error",
        }
    ]


def assess_rule_readiness(
    rule: Mapping[str, Any],
    entity_catalog: Iterable[str] = (),
    dependency_complete: bool = False,
) -> dict[str, Any]:
    """Return the v2 readiness payload for one rule.

    Dependency analysis happens in Agent 5, so requirement 2 is explicitly
    pending until that stage has populated the decision. All other sections are
    deterministic at validation time.
    """

    issues = validate_rule_v2(rule, entity_catalog)
    checks: dict[str, dict[str, Any]] = {}

    for section, name in CHECK_NAMES.items():
        reasons = _issue_reasons(issues, section)
        checks[f"{section}_{name}"] = _check("fail" if reasons else "pass", reasons)

    source_reasons = _source_fidelity_reasons(rule)
    if source_reasons:
        checks["7_source_fidelity"] = _check("fail", source_reasons)

    vector_reasons = _test_vector_boundary_reasons(rule)
    if vector_reasons:
        checks["8_test_vectors"] = _check("fail", checks["8_test_vectors"]["reasons"] + vector_reasons)

    if not dependency_complete:
        checks["2_dependencies_conflicts_hit_policy"] = _check(
            "pending",
            [
                {
                    "code": "dependency_analysis_pending",
                    "path": "recommended_hit_policy",
                    "message": "Agent 5 has not completed dependency/conflict analysis.",
                    "severity": "info",
                }
            ],
        )

    failed_sections = sorted(
        int(key.split("_", 1)[0])
        for key, value in checks.items()
        if value["status"] == "fail"
    )
    pending_sections = sorted(
        int(key.split("_", 1)[0])
        for key, value in checks.items()
        if value["status"] == "pending"
    )
    return {
        "checks": checks,
        "failed_sections": failed_sections,
        "pending_sections": pending_sections,
        "requires_review": bool(failed_sections or pending_sections),
        "status": "ready" if not failed_sections and not pending_sections else "review_required",
    }


def annotate_rule_readiness(
    rule: Mapping[str, Any],
    entity_catalog: Iterable[str] = (),
    dependency_complete: bool = False,
) -> dict[str, Any]:
    """Attach readiness without mutating the caller's object."""

    annotated = deepcopy(dict(rule))
    readiness = assess_rule_readiness(annotated, entity_catalog, dependency_complete)
    annotated["readiness"] = readiness
    if readiness["requires_review"]:
        annotated["requires_review"] = True
    return annotated
