"""Validation and normalization for the pipeline's structured v2 rule contract.

The module is deliberately dependency-free so the extraction CLI and its tests can
enforce the same contract without a running service or a model call.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

RULE_SCHEMA_VERSION = "2.0"
VALUE_TYPES = {
    "number",
    "boolean",
    "enum",
    "date",
    "date_time",
    "duration",
    "string",
    "range",
    "list",
    "variable_reference",
}
VARIABLE_TYPES = {
    "number",
    "boolean",
    "enum",
    "date",
    "date_time",
    "duration",
    "string",
    "list",
}
OPERATORS = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in"}
VARIABLE_ROLES = {"input", "derived", "output"}
SCOPE_BASES = {
    "explicit",
    # The extraction prompt documents exception_basis's "explicit_in_source" /
    # "explicitly_none_in_source" convention explicitly (rule_contract_v2.txt
    # item 5) but never states scope_basis's equivalent this precisely, so the
    # model reasonably extends that same convention here by analogy — 254 of
    # 352 rules in one real run used it. Accepted as a synonym for "explicit"
    # everywhere "explicit" is treated specially: see the matching entries in
    # FINAL_SCOPE_BASES and the evidence-requirement checks in kg_readiness.py.
    "explicit_in_source",
    # Same cross-pollination from exception_basis's convention, this time for
    # its "explicitly_none_in_source" value — the model uses it to mean "the
    # source explicitly confirms no loan/occupancy/transaction restriction
    # applies," an affirmative claim backed by a real citation in every case
    # observed, so it is treated the same as "explicit_in_source" for
    # evidence-requirement purposes rather than as the evidence-free
    # "genuinely_unscoped".
    "explicitly_none_in_source",
    "explicitly_universal_in_source",
    "genuinely_unscoped",
    "inferred",  # candidate-stage only; final readiness rejects inferred-empty scope
    "unresolved_after_source_review",
}
EXCEPTION_BASES = {
    "explicit_in_source",
    "explicitly_none_in_source",
    "not_found_in_chunk_recheck_needed",  # candidate-stage only
    "unresolved_after_full_document_search",
}
HIT_POLICIES = {"UNIQUE", "FIRST", "PRIORITY", "COLLECT", "ANY"}


@dataclass(frozen=True)
class ContractIssue:
    """A non-destructive v2 contract validation finding."""

    section: int
    code: str
    path: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class ValidationResult:
    """Normalized rule plus findings collected without losing the raw candidate."""

    rule: dict[str, Any]
    issues: list[ContractIssue]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def _issue(
    issues: list[ContractIssue],
    section: int,
    code: str,
    path: str,
    message: str,
    severity: str = "error",
) -> None:
    issues.append(ContractIssue(section, code, path, message, severity))


def _normalise_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_evidence(value: Any, path: str, issues: list[ContractIssue]) -> None:
    if not isinstance(value, list) or not value:
        _issue(issues, 7, "missing_field_evidence", path, "At least one source pointer is required.")
        return

    for index, reference in enumerate(value):
        reference_path = f"{path}[{index}]"
        if not isinstance(reference, Mapping):
            _issue(issues, 7, "invalid_field_evidence", reference_path, "Evidence must be an object.")
            continue
        for required in ("chunk_path", "section_id", "source_text"):
            if not str(reference.get(required, "")).strip():
                _issue(
                    issues,
                    7,
                    "missing_evidence_reference_field",
                    f"{reference_path}.{required}",
                    "Evidence references require chunk_path, section_id, and source_text.",
                )


def _walk_logic(
    node: Any,
    predicate_ids: set[str],
    referenced_ids: list[str],
    path: str,
    issues: list[ContractIssue],
) -> None:
    if not isinstance(node, Mapping):
        _issue(issues, 1, "invalid_condition_logic", path, "Condition logic must be an object.")
        return

    if set(node) == {"predicate_ref"}:
        predicate_id = node.get("predicate_ref")
        if not isinstance(predicate_id, str) or predicate_id not in predicate_ids:
            _issue(
                issues,
                1,
                "unknown_predicate_reference",
                f"{path}.predicate_ref",
                "Condition logic references an unknown predicate.",
            )
        else:
            referenced_ids.append(predicate_id)
        return

    branch_names = [name for name in ("all", "any") if name in node]
    if len(branch_names) != 1 or len(node) != 1:
        _issue(
            issues,
            1,
            "invalid_condition_logic_node",
            path,
            "A logic node must contain exactly one of predicate_ref, all, or any.",
        )
        return

    children = node[branch_names[0]]
    if not isinstance(children, list) or not children:
        _issue(
            issues,
            1,
            "empty_condition_logic_branch",
            f"{path}.{branch_names[0]}",
            "A logic branch requires one or more child nodes.",
        )
        return

    for index, child in enumerate(children):
        _walk_logic(child, predicate_ids, referenced_ids, f"{path}.{branch_names[0]}[{index}]", issues)


def _validate_predicates(
    predicates: Any,
    variables: Mapping[str, Mapping[str, Any]],
    path: str,
    issues: list[ContractIssue],
) -> set[str]:
    if not isinstance(predicates, list) or not predicates:
        _issue(issues, 1, "missing_condition_predicates", path, "At least one atomic predicate is required.")
        return set()

    predicate_ids: set[str] = set()
    for index, predicate in enumerate(predicates):
        predicate_path = f"{path}[{index}]"
        if not isinstance(predicate, Mapping):
            _issue(issues, 1, "invalid_predicate", predicate_path, "Predicate must be an object.")
            continue

        predicate_id = predicate.get("predicate_id")
        if not isinstance(predicate_id, str) or not predicate_id.strip():
            _issue(issues, 1, "missing_predicate_id", f"{predicate_path}.predicate_id", "Predicate ID is required.")
        elif predicate_id in predicate_ids:
            _issue(issues, 1, "duplicate_predicate_id", f"{predicate_path}.predicate_id", "Predicate IDs must be unique.")
        else:
            predicate_ids.add(predicate_id)

        variable_name = _normalise_name(predicate.get("variable"))
        if not variable_name:
            _issue(issues, 1, "missing_predicate_variable", f"{predicate_path}.variable", "Predicate variable is required.")
        elif variable_name not in variables:
            _issue(
                issues,
                1,
                "undefined_predicate_variable",
                f"{predicate_path}.variable",
                "Every predicate variable must be declared in variables.",
            )

        if predicate.get("operator") not in OPERATORS:
            _issue(
                issues,
                1,
                "invalid_predicate_operator",
                f"{predicate_path}.operator",
                f"Operator must be one of {sorted(OPERATORS)}.",
            )

        value_type = predicate.get("value_type")
        if value_type not in VALUE_TYPES:
            _issue(
                issues,
                1,
                "invalid_predicate_value_type",
                f"{predicate_path}.value_type",
                f"value_type must be one of {sorted(VALUE_TYPES)}.",
            )
        elif value_type == "variable_reference":
            value_name = _normalise_name(predicate.get("value"))
            if value_name not in variables:
                _issue(
                    issues,
                    1,
                    "undefined_variable_reference",
                    f"{predicate_path}.value",
                    "A variable_reference must resolve to a declared variable.",
                )
        elif value_type == "number" and not _is_number(predicate.get("value")):
            _issue(issues, 1, "invalid_numeric_value", f"{predicate_path}.value", "Number predicates require a numeric value.")
        elif value_type == "boolean" and not isinstance(predicate.get("value"), bool):
            _issue(issues, 1, "invalid_boolean_value", f"{predicate_path}.value", "Boolean predicates require true or false.")

    return predicate_ids


def _validate_variables(rule: Mapping[str, Any], issues: list[ContractIssue]) -> dict[str, Mapping[str, Any]]:
    variables = rule.get("variables")
    if not isinstance(variables, list) or not variables:
        _issue(issues, 1, "missing_variables", "variables", "Every v2 rule requires typed variables.")
        return {}

    result: dict[str, Mapping[str, Any]] = {}
    for index, variable in enumerate(variables):
        variable_path = f"variables[{index}]"
        if not isinstance(variable, Mapping):
            _issue(issues, 1, "invalid_variable", variable_path, "Variable must be an object.")
            continue
        name = _normalise_name(variable.get("name"))
        if not name:
            _issue(issues, 1, "missing_variable_name", f"{variable_path}.name", "Variable name is required.")
            continue
        if name in result:
            _issue(issues, 1, "duplicate_variable_name", f"{variable_path}.name", "Variable names must be unique.")
            continue
        result[name] = variable

        variable_type = variable.get("type")
        if variable_type not in VARIABLE_TYPES:
            _issue(
                issues,
                1,
                "invalid_variable_type",
                f"{variable_path}.type",
                f"type must be one of {sorted(VARIABLE_TYPES)}.",
            )
        if variable_type == "string" and variable.get("free_text") is not True:
            _issue(
                issues,
                1,
                "unjustified_string_variable",
                f"{variable_path}.free_text",
                "String variables must explicitly declare free_text: true.",
            )
        if variable.get("role") not in VARIABLE_ROLES:
            _issue(
                issues,
                1,
                "invalid_variable_role",
                f"{variable_path}.role",
                f"role must be one of {sorted(VARIABLE_ROLES)}.",
            )
        if variable_type == "enum":
            allowed_values = variable.get("allowed_values")
            if not isinstance(allowed_values, list) or not allowed_values:
                _issue(
                    issues,
                    1,
                    "missing_enum_allowed_values",
                    f"{variable_path}.allowed_values",
                    "Enum variables require a non-empty allowed_values list.",
                )
        if variable_type == "number" and "allowed_range" in variable:
            allowed_range = variable["allowed_range"]
            if (
                not isinstance(allowed_range, list)
                or len(allowed_range) != 2
                or any(value is not None and not _is_number(value) for value in allowed_range)
            ):
                _issue(
                    issues,
                    1,
                    "invalid_allowed_range",
                    f"{variable_path}.allowed_range",
                    "allowed_range must be [number|null, number|null].",
                )
    return result


def _validate_outcomes(
    outcomes: Any,
    variables: Mapping[str, Mapping[str, Any]],
    issues: list[ContractIssue],
) -> None:
    if not isinstance(outcomes, list) or not outcomes:
        _issue(issues, 1, "missing_outcomes", "outcomes", "Every v2 rule requires at least one structured outcome.")
        return

    for index, outcome in enumerate(outcomes):
        outcome_path = f"outcomes[{index}]"
        if not isinstance(outcome, Mapping):
            _issue(issues, 1, "invalid_outcome", outcome_path, "Outcome must be an object.")
            continue
        variable_name = _normalise_name(outcome.get("variable"))
        variable = variables.get(variable_name)
        if variable is None:
            _issue(
                issues,
                1,
                "undefined_outcome_variable",
                f"{outcome_path}.variable",
                "Every outcome variable must be declared in variables.",
            )
        elif variable.get("role") != "output":
            _issue(
                issues,
                1,
                "outcome_variable_not_output",
                f"{outcome_path}.variable",
                "Outcome variables must have role output.",
            )

        if outcome.get("operator") != "=":
            _issue(issues, 1, "invalid_outcome_operator", f"{outcome_path}.operator", "Outcome operator must be =.")
        value_type = outcome.get("value_type")
        if value_type not in VALUE_TYPES:
            _issue(issues, 1, "invalid_outcome_value_type", f"{outcome_path}.value_type", "Outcome value_type is invalid.")
        elif value_type == "number" and not _is_number(outcome.get("value")):
            _issue(issues, 1, "invalid_outcome_number", f"{outcome_path}.value", "Numeric outcomes require a numeric value.")


def _validate_exceptions(
    exceptions: Any,
    variables: Mapping[str, Mapping[str, Any]],
    issues: list[ContractIssue],
) -> None:
    """Validate exception predicates without treating them as conditions."""
    if not isinstance(exceptions, list):
        _issue(issues, 6, "invalid_exceptions", "exceptions", "exceptions must be an array.")
        return

    predicate_ids: set[str] = set()
    for index, predicate in enumerate(exceptions):
        predicate_path = f"exceptions[{index}]"
        if not isinstance(predicate, Mapping):
            _issue(issues, 6, "invalid_exception_predicate", predicate_path, "Exception predicate must be an object.")
            continue
        predicate_id = predicate.get("predicate_id")
        if not isinstance(predicate_id, str) or not predicate_id.strip():
            _issue(issues, 6, "missing_exception_predicate_id", f"{predicate_path}.predicate_id", "Exception predicate ID is required.")
        elif predicate_id in predicate_ids:
            _issue(issues, 6, "duplicate_exception_predicate_id", f"{predicate_path}.predicate_id", "Exception predicate IDs must be unique.")
        else:
            predicate_ids.add(predicate_id)

        if _normalise_name(predicate.get("variable")) not in variables:
            _issue(issues, 6, "undefined_exception_variable", f"{predicate_path}.variable", "Exception variables must be declared in variables.")
        if predicate.get("operator") not in OPERATORS:
            _issue(issues, 6, "invalid_exception_operator", f"{predicate_path}.operator", "Exception operator is invalid.")
        value_type = predicate.get("value_type")
        if value_type not in VALUE_TYPES:
            _issue(issues, 6, "invalid_exception_value_type", f"{predicate_path}.value_type", "Exception value_type is invalid.")
        elif value_type == "variable_reference" and _normalise_name(predicate.get("value")) not in variables:
            _issue(issues, 6, "undefined_exception_variable_reference", f"{predicate_path}.value", "Exception variable reference must resolve to a declared variable.")


def _validate_rule_metadata(rule: Mapping[str, Any], entity_catalog: Iterable[str], issues: list[ContractIssue]) -> None:
    if rule.get("schema_version") != RULE_SCHEMA_VERSION:
        _issue(
            issues,
            1,
            "unsupported_schema_version",
            "schema_version",
            f"schema_version must be {RULE_SCHEMA_VERSION!r}.",
        )

    if rule.get("recommended_hit_policy") not in HIT_POLICIES:
        _issue(issues, 2, "invalid_hit_policy", "recommended_hit_policy", "A valid recommended_hit_policy is required.")

    if not str(rule.get("versioning_status", "")).strip() and not (
        rule.get("expiration_date") or rule.get("superseded_by")
    ):
        _issue(issues, 3, "missing_versioning_status", "versioning_status", "Versioning status or explicit expiration/supersession is required.")

    scope = rule.get("applicability_scope")
    if not isinstance(scope, Mapping):
        _issue(issues, 4, "missing_applicability_scope", "applicability_scope", "A structured scope object is required.")
    if rule.get("scope_basis") not in SCOPE_BASES:
        _issue(issues, 4, "invalid_scope_basis", "scope_basis", "scope_basis is not a recognized candidate or final evidence state.")
    if rule.get("scope_basis") == "inferred" and not str(rule.get("inference_reasoning", "")).strip():
        _issue(issues, 4, "missing_inference_reasoning", "inference_reasoning", "Inferred scope requires an explanation.")

    catalog = {_normalise_name(item) for item in entity_catalog}
    responsible_party = rule.get("responsible_party")
    if not isinstance(responsible_party, str) or not responsible_party.strip():
        _issue(issues, 5, "missing_responsible_party", "responsible_party", "A responsible_party is required.")
    elif catalog and _normalise_name(responsible_party) not in catalog:
        _issue(issues, 5, "unknown_responsible_party", "responsible_party", "responsible_party must use an existing entity type.")

    counterparties = rule.get("counterparties")
    if not isinstance(counterparties, list):
        _issue(issues, 5, "invalid_counterparties", "counterparties", "counterparties must be an array.")
    elif catalog:
        for index, party in enumerate(counterparties):
            if _normalise_name(party) not in catalog:
                _issue(issues, 5, "unknown_counterparty", f"counterparties[{index}]", "counterparty must use an existing entity type.")

    if rule.get("exception_basis") not in EXCEPTION_BASES:
        _issue(issues, 6, "invalid_exception_basis", "exception_basis", "exception_basis is required.")

    vectors = rule.get("test_vectors")
    if not isinstance(vectors, list) or not vectors:
        _issue(issues, 8, "missing_test_vectors", "test_vectors", "At least one structured test vector is required.")
    else:
        for index, vector in enumerate(vectors):
            vector_path = f"test_vectors[{index}]"
            if not isinstance(vector, Mapping) or not isinstance(vector.get("inputs"), Mapping) or not isinstance(vector.get("expected_output"), Mapping):
                _issue(issues, 8, "invalid_test_vector", vector_path, "Test vectors require inputs and expected_output objects.")
            elif vector.get("vector_basis") not in {"source_attested", "derived_from_source"}:
                _issue(issues, 8, "invalid_vector_basis", f"{vector_path}.vector_basis", "Test vectors require a source basis.")


def validate_rule_v2(
    rule: Mapping[str, Any],
    entity_catalog: Iterable[str] = (),
) -> list[ContractIssue]:
    """Return every v2 contract issue without mutating *rule*."""

    issues: list[ContractIssue] = []
    variables = _validate_variables(rule, issues)
    predicate_ids = _validate_predicates(rule.get("condition_predicates"), variables, "condition_predicates", issues)

    condition_logic = rule.get("condition_logic")
    if isinstance(condition_logic, str) and condition_logic in {"AND", "OR"}:
        if len(predicate_ids) < 2:
            _issue(
                issues,
                1,
                "flat_logic_requires_multiple_predicates",
                "condition_logic",
                "AND/OR condition_logic requires two or more predicates.",
            )
    else:
        referenced_ids: list[str] = []
        _walk_logic(condition_logic, predicate_ids, referenced_ids, "condition_logic", issues)
        for predicate_id in predicate_ids:
            if referenced_ids.count(predicate_id) != 1:
                _issue(
                    issues,
                    1,
                    "predicate_logic_coverage",
                    "condition_logic",
                    f"Predicate {predicate_id!r} must appear exactly once in condition_logic.",
                )

    _validate_outcomes(rule.get("outcomes"), variables, issues)
    _validate_exceptions(rule.get("exceptions"), variables, issues)
    _validate_rule_metadata(rule, entity_catalog, issues)

    evidence = rule.get("field_evidence")
    if not isinstance(evidence, Mapping):
        _issue(issues, 7, "missing_field_evidence", "field_evidence", "v2 rules require field_evidence.")
    else:
        for field_path in (
            "condition_predicates",
            "outcomes",
            "responsible_party",
            "scope_basis",
            "versioning_status",
            "exceptions",
            "test_vectors",
        ):
            _validate_evidence(evidence.get(field_path), f"field_evidence.{field_path}", issues)

    return issues


def normalize_rule_v2(rule: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with stable whitespace and normalized variable names."""

    normalized = deepcopy(dict(rule))
    for variable in normalized.get("variables", []):
        if isinstance(variable, dict) and isinstance(variable.get("name"), str):
            variable["name"] = variable["name"].strip()
    for collection_name in ("condition_predicates", "outcomes"):
        for item in normalized.get(collection_name, []):
            if isinstance(item, dict) and isinstance(item.get("variable"), str):
                item["variable"] = item["variable"].strip()
    return normalized


def parse_rule_v2(
    raw_rule: Mapping[str, Any],
    entity_catalog: Iterable[str] = (),
) -> ValidationResult:
    """Normalize a candidate and return contract issues without discarding it."""

    normalized = normalize_rule_v2(raw_rule)
    return ValidationResult(rule=normalized, issues=validate_rule_v2(normalized, entity_catalog))


def annotate_rule_contract(
    raw_rule: Mapping[str, Any],
    entity_catalog: Iterable[str] = (),
) -> dict[str, Any]:
    """Attach non-destructive contract findings and review state to a candidate."""

    result = parse_rule_v2(raw_rule, entity_catalog)
    rule = result.rule
    issues = [issue.as_dict() for issue in result.issues]
    rule["contract_issues"] = issues
    if any(issue["severity"] == "error" for issue in issues):
        rule["requires_review"] = True
    return rule
