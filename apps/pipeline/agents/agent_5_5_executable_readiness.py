#!/usr/bin/env python3
"""Agent 5.5: evidence-backed completion for DMN/BPMN-ready graph rules."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import threading
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import get_config
from utils.kg_readiness import (
    CANONICAL_ENTITY_RE,
    cited_sections,
    corpus_manifest,
    dependency_edges,
    derive_dependency_chains,
    entity_rule_groups,
    final_rule_issues,
    mark_readiness,
    naming_issues,
    referential_integrity_issues,
    source_document_index,
)
from utils.llm_client import create_llm_client
from utils.prompt_manager import get_prompt_manager
from utils.rule_contract import EXCEPTION_BASES, SCOPE_BASES, validate_rule_v2

# Completion fields that every downstream reader (kg_readiness.final_rule_issues,
# this module's own searched_chunk_count/corpus_sha256 stamping) treats as a
# structured object and calls .get() on directly. A resolver returning anything
# else for one of these — a plain string, most often — must not overwrite the
# rule's existing value; see the two field-copy loops in this file.
_DICT_SHAPED_COMPLETION_FIELDS = {"exception_verification", "scope_derivation", "applicability_scope"}


class EvidenceResolver(Protocol):
    def complete_rule(self, rule: Mapping[str, Any], corpus: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def complete_rules(self, rules: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]: ...
    def analyse_entity(self, entity: str, rules: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]: ...


class OpenAIEvidenceResolver:
    """Source interpreter. It never performs graph/corpus integrity decisions."""

    def __init__(self, api_key: str, model: str, reasoning_effort: str) -> None:
        try:
            readiness_concurrency = max(1, int(os.getenv("KG_READINESS_LLM_CONCURRENCY", "4")))
        except (TypeError, ValueError):
            readiness_concurrency = 4
        self.readiness_concurrency = readiness_concurrency
        self.client = create_llm_client(
            api_key=api_key,
            model=model,
            concurrency=readiness_concurrency,
        )
        self.reasoning_effort = reasoning_effort
        self.prompts = get_prompt_manager()

    @staticmethod
    def _parse(content: str) -> Mapping[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        value = json.loads(content)
        if not isinstance(value, Mapping):
            raise ValueError("readiness response must be an object")
        return value

    def _json_completion(self, prompt: str, max_tokens: int) -> Mapping[str, Any]:
        """Request JSON with bounded retries for occasional malformed model output."""
        attempts = max(1, int(os.getenv("KG_READINESS_PARSE_ATTEMPTS", "3")))
        retry_prompt = prompt
        last_error: Exception | None = None
        for attempt in range(attempts):
            response = self.client.chat_completion(
                messages=[{"role": "user", "content": retry_prompt}], temperature=0,
                max_tokens=max_tokens, reasoning_effort=self.reasoning_effort,
            )
            content = response.choices[0].message.content or ""
            try:
                return self._parse(content)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = exc
                retry_prompt = (
                    prompt
                    + "\n\nYour previous response was not valid JSON. Retry now. "
                    "Return one complete JSON object only, with double-quoted keys and strings; "
                    "do not include markdown fences or explanatory text."
                )
                if attempt + 1 < attempts:
                    print(f"⚠️ Readiness JSON parse retry {attempt + 1}/{attempts - 1}", flush=True)
        assert last_error is not None
        raise last_error

    def complete_rule(self, rule: Mapping[str, Any], corpus: Mapping[str, Any]) -> Mapping[str, Any]:
        prompt = self.prompts.format_prompt(
            "executable_readiness_completion",
            rule_json=json.dumps(rule, ensure_ascii=False),
            corpus_json=json.dumps(corpus, ensure_ascii=False),
        )
        return self._json_completion(prompt, int(os.getenv("KG_READINESS_MAX_TOKENS", "6000")))

    def complete_rules(self, rules: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        prompt = self.prompts.format_prompt(
            "executable_readiness_batch_completion",
            rules_json=json.dumps(rules, ensure_ascii=False),
        )
        value = self._json_completion(prompt, int(os.getenv("KG_READINESS_BATCH_MAX_TOKENS", "16000")))
        completions = value.get("completions", [])
        return completions if isinstance(completions, list) else []

    def analyse_entity(self, entity: str, rules: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        prompt = self.prompts.format_prompt(
            "entity_conflict_analysis",
            entity_key=entity,
            rules_json=json.dumps(rules, ensure_ascii=False),
        )
        value = self._json_completion(prompt, int(os.getenv("KG_CONFLICT_MAX_TOKENS", "6000")))
        analyses = value.get("analyses", [])
        return analyses if isinstance(analyses, list) else []


def _project_execution(rule: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanical projection; final readiness still requires evidence checks."""
    variables = [item for item in rule.get("variables", []) if isinstance(item, Mapping)]
    inputs = [str(item.get("name")) for item in variables if item.get("role") in {"input", "derived"}]
    outputs = [str(item.get("name")) for item in variables if item.get("role") == "output"]
    targets = ["DMN"] if inputs and outputs else []
    execution: dict[str, Any] = {"targets": targets}
    if "DMN" in targets:
        execution["dmn"] = {"input_columns": inputs, "output_columns": outputs, "hit_policy": rule.get("recommended_hit_policy")}
    if str(rule.get("rule_type", "")).lower() in {"process", "validation", "compliance", "exception"} and outputs:
        targets.append("BPMN")
        execution["bpmn"] = {"gateway_type": "exclusive", "lane": rule.get("responsible_party"), "true_path_outcome_variables": outputs}
    return execution


LEGACY_ENTITY_NAMES = {
    "ManufacturedHome": "MANUFACTURED_HOME",
    "MortgageBackedSecurity": "MORTGAGE_BACKED_SECURITY",
    "MortgagePool": "MORTGAGE_POOL",
    "RepresentationAndWarranty": "REPRESENTATION_AND_WARRANTY",
    "SecurityInstrument": "SECURITY_INSTRUMENT",
    "SpecialFeatureCode": "SPECIAL_FEATURE_CODE",
}

LEGACY_VALUE_TYPES = {
    "array": "list",
    "enum_list": "list",
    "list_number": "list",
    "number_list": "list",
    "string_array": "list",
    "string_list": "list",
}

LEGACY_OPERATORS = {
    "=": "==",
    "BETWEEN": "in",
    "IN": "in",
    "NOT_IN": "not_in",
}


def _to_screaming_snake_case(name: str) -> str:
    """CreditScore -> CREDIT_SCORE; PostClosingQCReview -> POST_CLOSING_QC_REVIEW.

    Verified against all 24 entity names from one real extraction run,
    including acronym runs (QC) and short words (Of) — every already-canonical
    name passes through unchanged, so applying this to a name that doesn't
    need it is always a no-op.
    """
    step1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    step2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", step1)
    # Collapse any run of underscores/non-alphanumerics the substitutions above
    # can introduce next to a name's own separators (e.g. "Mixed_Case" already
    # has an underscore where step1 also inserts one) and strip the ends, so
    # the result always matches CANONICAL_ENTITY_RE rather than failing it
    # with a double underscore.
    step3 = re.sub(r"[^A-Za-z0-9]+", "_", step2).strip("_")
    return step3.upper()


def _build_entity_name_map(graph: Any) -> dict[str, str]:
    """Map every non-canonical entity_types key in *graph* to its
    SCREAMING_SNAKE_CASE form, merged over the fixed legacy list.

    The extraction prompt asks for entity type keys in this form, but nothing
    enforces it at extraction time — Agent 2 has produced PascalCase names
    (CreditScore, DocumentCustodian, ...) for entire graphs, and the fixed
    LEGACY_ENTITY_NAMES list only ever covered six specific names discovered
    reactively in earlier datasets. Building the map from the graph's own
    entity_types generalizes the fix to whatever a given run actually
    produced, instead of requiring every new bad name to be added by hand.

    A rule's own `responsible_party`/`counterparties` references are scanned
    too: a reference can be non-canonical even when the entity it refers to
    is already canonical everywhere in entity_types (e.g. one rule citing
    "Borrower" as a counterparty while entity_types only ever defines
    "BORROWER") — that name never appears as an entity_types key, so it would
    otherwise never become a normalization candidate at all.
    """
    mapping = dict(LEGACY_ENTITY_NAMES)
    entity_types = graph.get("entity_types") if isinstance(graph, Mapping) else None
    known_canonical_keys: set[str] = set(mapping.values())
    if isinstance(entity_types, Mapping):
        for key in entity_types:
            key_str = str(key)
            if not key_str:
                continue
            if CANONICAL_ENTITY_RE.fullmatch(key_str):
                known_canonical_keys.add(key_str)
                continue
            canonical = _to_screaming_snake_case(key_str)
            if canonical and canonical != key_str:
                mapping.setdefault(key_str, canonical)
                known_canonical_keys.add(canonical)

    # A rule's own reference can be non-canonical even when the entity it
    # refers to is already canonical everywhere in entity_types (e.g. one
    # rule citing "Borrower" as a counterparty while entity_types only ever
    # defines "BORROWER") — that string never appears as an entity_types key,
    # so without this it would never become a normalization candidate at
    # all. Only remap a reference when its canonical form is already a known
    # entity: an unrelated typo ("Boroower") must stay exactly as written so
    # it keeps failing naming_issues visibly, rather than being silently
    # rewritten to a differently-wrong, canonical-looking name nobody defined.
    rules = graph.get("business_rules") if isinstance(graph, Mapping) else None
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            references = [rule.get("responsible_party"), *(rule.get("counterparties") or [])]
            for reference in references:
                key_str = str(reference) if reference else ""
                if not key_str or key_str in mapping or CANONICAL_ENTITY_RE.fullmatch(key_str):
                    continue
                canonical = _to_screaming_snake_case(key_str)
                if canonical and canonical != key_str and canonical in known_canonical_keys:
                    mapping[key_str] = canonical
    return mapping


def _normalise_graph_entity_names(value: Any, mapping: Mapping[str, str] | None = None) -> Any:
    """Replace exact entity identifiers — the fixed legacy list plus any
    non-canonical entity_types key found in *value* itself — including
    dictionary keys.

    `mapping` is computed once from the top-level graph on the outermost call
    and threaded through the recursion; callers normally pass only `value`.
    """
    if mapping is None:
        mapping = _build_entity_name_map(value)
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            normalised_key = mapping.get(str(key), key)
            normalised_item = _normalise_graph_entity_names(item, mapping)
            if normalised_key in result and result[normalised_key] != normalised_item:
                raise ValueError(f"entity-name normalization collision at {normalised_key!r}")
            result[normalised_key] = normalised_item
        return result
    if isinstance(value, list):
        return [_normalise_graph_entity_names(item, mapping) for item in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def _normalise_value_type(value: Any) -> Any:
    return LEGACY_VALUE_TYPES.get(str(value), value)


def _normalise_operator(value: Any) -> Any:
    return LEGACY_OPERATORS.get(str(value), value)


def _evidence_pointer(value: Any) -> dict[str, str] | None:
    # source_reference is documented (rule_contract_v2.txt, every domain
    # prompt) as a single object, but Agent 3 sometimes emits a list of
    # citations for a rule whose justification spans more than one excerpt —
    # Agent 5.7's own _iter_references already treats that as legitimate.
    # Take the first usable entry rather than discarding real evidence: on
    # one ContractNLI pilot run, a rule with source_reference shaped this way
    # and no exceptions left field_evidence.exceptions empty, which is a hard
    # v2 schema violation that fails the whole pipeline outright.
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, Mapping)), None)
    if not isinstance(value, Mapping):
        return None
    pointer = {
        "chunk_path": str(value.get("chunk_path", "")).strip(),
        "section_id": str(value.get("section_id", "")).strip(),
        "source_text": str(value.get("source_text", value.get("text", value.get("quote", "")))).strip(),
    }
    return pointer if all(pointer.values()) else None


def _invert_predicate(predicate: Mapping[str, Any], predicate_id: str) -> dict[str, Any]:
    inverse = {"==": "!=", "!=": "==", ">": "<=", ">=": "<", "<": ">=", "<=": ">", "in": "not_in", "not_in": "in"}
    result = deepcopy(dict(predicate))
    result["predicate_id"] = predicate_id
    operator = _normalise_operator(result.get("operator"))
    if operator in inverse:
        result["operator"] = inverse[operator]
    elif result.get("value_type") == "boolean" and isinstance(result.get("value"), bool):
        result["operator"] = "=="
        result["value"] = not result["value"]
    else:
        result["operator"] = "!="
    return result


def _restore_legacy_outcome_operators(graph: dict[str, Any], baseline: Mapping[str, Any]) -> None:
    """Restore comparison operators on a replay from the immutable pre-readiness graph."""
    baseline_operators = {
        (str(rule.get("rule_id")), str(outcome.get("variable"))): outcome.get("operator")
        for rule in baseline.get("business_rules", [])
        if isinstance(rule, Mapping)
        for outcome in rule.get("outcomes", []) or []
        if isinstance(outcome, Mapping) and outcome.get("operator") != "="
    }
    for rule in graph.get("business_rules", []) or []:
        if not isinstance(rule, dict):
            continue
        baseline_rule = next(
            (
                item for item in baseline.get("business_rules", [])
                if isinstance(item, Mapping) and str(item.get("rule_id")) == str(rule.get("rule_id"))
            ),
            None,
        )
        for outcome in rule.get("outcomes", []) or []:
            if not isinstance(outcome, dict):
                continue
            current_name = str(outcome.get("variable"))
            operator = baseline_operators.get((str(rule.get("rule_id")), current_name))
            if operator is not None:
                outcome["operator"] = operator
                continue
            if not isinstance(baseline_rule, Mapping):
                continue
            for baseline_outcome in baseline_rule.get("outcomes", []) or []:
                if not isinstance(baseline_outcome, Mapping) or baseline_outcome.get("operator") == "=":
                    continue
                original_name = str(baseline_outcome.get("variable"))
                if _threshold_output_name(original_name, baseline_outcome.get("operator")) != current_name:
                    continue
                baseline_variable = next(
                    (
                        item for item in baseline_rule.get("variables", []) or []
                        if isinstance(item, Mapping) and str(item.get("name")) == original_name
                    ),
                    None,
                )
                declared_names = {
                    str(item.get("name")) for item in rule.get("variables", []) or [] if isinstance(item, Mapping)
                }
                vector_uses_original = any(
                    isinstance(vector, Mapping) and original_name in (vector.get("inputs") or {})
                    for vector in rule.get("test_vectors", []) or []
                )
                if vector_uses_original and isinstance(baseline_variable, Mapping) and original_name not in declared_names:
                    restored_variable = deepcopy(dict(baseline_variable))
                    restored_variable["role"] = "input"
                    rule.setdefault("variables", []).append(restored_variable)
                break


def _threshold_output_name(variable_name: str, operator: Any) -> str:
    lowered = variable_name.lower()
    if operator == "<=" and not any(token in lowered for token in ("max", "maximum")):
        return f"maximum_allowed_{variable_name}"
    if operator == ">=" and not any(token in lowered for token in ("min", "minimum")):
        return f"minimum_required_{variable_name}"
    if str(operator).upper() == "IN" and "allowed" not in lowered:
        return f"allowed_{variable_name}_values"
    return variable_name


def _coerce_unresolved_basis(rule: dict[str, Any], basis_field: str, valid_values: set[str], verification_field: str, unresolved_value: str) -> None:
    """Coerce an off-schema *_basis string into the correct unresolved final
    state, preserving the model's own explanation rather than discarding it.

    Both scope_basis and exception_basis have been observed holding a
    free-text explanation instead of an enum member — sometimes the model's
    own reasoning wholesale ("unresolved_in_source_exception_not_structurable
    _with_available_rule_variables (source states...)"), sometimes a compact
    ad hoc label ("explicit_in_source_but_details_not_in_evidence_packet").
    Every real case observed is semantically an unresolved state the model
    couldn't cleanly structure — not a new final state and not one of the
    documented ones — so it is normalized to the one unresolved bucket that
    already exists for this field, with the original string kept as the
    reviewable reason rather than silently dropped or left as a raw v2
    schema violation with no actionable path.
    """
    value = rule.get(basis_field)
    if not isinstance(value, str) or value in valid_values:
        return
    verification = rule.get(verification_field)
    verification_map = dict(verification) if isinstance(verification, Mapping) else {}
    if not str(verification_map.get("unresolved_reason", "")).strip():
        verification_map["unresolved_reason"] = value
    rule[verification_field] = verification_map
    rule[basis_field] = unresolved_value


def _normalise_rule_contract(rule: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy extraction shapes without changing rule/source identity."""
    _coerce_unresolved_basis(rule, "exception_basis", EXCEPTION_BASES, "exception_verification", "unresolved_after_full_document_search")
    _coerce_unresolved_basis(rule, "scope_basis", SCOPE_BASES, "scope_derivation", "unresolved_after_source_review")
    variables = rule.get("variables")
    if not isinstance(variables, list):
        variables = []
        rule["variables"] = variables
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        if variable.get("type") == "datetime":
            variable["type"] = "date_time"
        if variable.get("type") == "string":
            variable["free_text"] = True

    for field in ("condition_predicates", "outcomes", "exceptions"):
        values = rule.get(field)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            if field != "outcomes":
                item["operator"] = _normalise_operator(item.get("operator"))
            item["value_type"] = _normalise_value_type(item.get("value_type"))
            if item.get("value_type") == "boolean" and isinstance(item.get("value"), str):
                lowered = item["value"].strip().lower()
                if lowered in {"true", "false"}:
                    item["value"] = lowered == "true"
    variable_by_name = {
        str(variable.get("name", "")).strip().lower(): variable
        for variable in variables
        if isinstance(variable, dict) and str(variable.get("name", "")).strip()
    }
    for outcome in rule.get("outcomes", []) or []:
        if not isinstance(outcome, dict):
            continue
        original_name = str(outcome.get("variable", "")).strip()
        original_operator = outcome.get("operator")
        output_name = _threshold_output_name(original_name, original_operator)
        variable = variable_by_name.get(original_name.lower())
        if output_name != original_name and variable is not None:
            predicate_variables = {
                str(predicate.get("variable", "")).strip().lower()
                for predicate in rule.get("condition_predicates", []) or []
                if isinstance(predicate, Mapping)
            }
            vector_uses_original = any(
                isinstance(vector, Mapping) and original_name in (vector.get("inputs") or {})
                for vector in rule.get("test_vectors", []) or []
            )
            if original_name.lower() in predicate_variables or vector_uses_original:
                output_variable = deepcopy(variable)
                output_variable["name"] = output_name
                output_variable["role"] = "output"
                variables.append(output_variable)
                variable["role"] = "input"
                variable = output_variable
            else:
                variable["name"] = output_name
            variable_by_name.pop(original_name.lower(), None)
            variable_by_name[output_name.lower()] = variable
            outcome["variable"] = output_name
            for vector in rule.get("test_vectors", []) or []:
                expected = vector.get("expected_output") if isinstance(vector, Mapping) else None
                if isinstance(expected, dict) and original_name in expected:
                    expected[output_name] = expected.pop(original_name)
        if variable is not None:
            variable["role"] = "output"
        outcome["operator"] = "="

    predicates = rule.get("condition_predicates")
    if not isinstance(predicates, list):
        predicates = []
        rule["condition_predicates"] = predicates
    predicate_by_id = {
        str(predicate.get("predicate_id")): predicate
        for predicate in predicates
        if isinstance(predicate, dict) and predicate.get("predicate_id")
    }
    referenced_predicates: dict[str, int] = {}

    def normalise_logic(node: Any) -> dict[str, Any] | None:
        if not isinstance(node, Mapping):
            return None
        if node.get("variable") and node.get("operator") is not None:
            predicate = deepcopy(dict(node))
            predicate_id = str(predicate.get("predicate_id") or f"p{len(predicates) + 1}")
            while predicate_id in predicate_by_id:
                predicate_id = f"p{len(predicates) + 1}"
            predicate["predicate_id"] = predicate_id
            predicate["operator"] = _normalise_operator(predicate.get("operator"))
            predicate["value_type"] = _normalise_value_type(predicate.get("value_type"))
            predicates.append(predicate)
            predicate_by_id[predicate_id] = predicate
            return {"predicate_ref": predicate_id}
        if "predicate_ref" in node:
            predicate_id = str(node.get("predicate_ref"))
            if node.get("negate") is True and predicate_id in predicate_by_id:
                negated_id = f"{predicate_id}_negated"
                suffix = 2
                while negated_id in predicate_by_id:
                    negated_id = f"{predicate_id}_negated_{suffix}"
                    suffix += 1
                negated = _invert_predicate(predicate_by_id[predicate_id], negated_id)
                predicates.append(negated)
                predicate_by_id[negated_id] = negated
                return {"predicate_ref": negated_id}
            referenced_predicates[predicate_id] = referenced_predicates.get(predicate_id, 0) + 1
            if referenced_predicates[predicate_id] > 1 and predicate_id in predicate_by_id:
                duplicate_id = f"{predicate_id}_copy_{referenced_predicates[predicate_id]}"
                while duplicate_id in predicate_by_id:
                    referenced_predicates[predicate_id] += 1
                    duplicate_id = f"{predicate_id}_copy_{referenced_predicates[predicate_id]}"
                duplicate = deepcopy(predicate_by_id[predicate_id])
                duplicate["predicate_id"] = duplicate_id
                predicates.append(duplicate)
                predicate_by_id[duplicate_id] = duplicate
                return {"predicate_ref": duplicate_id}
            return {"predicate_ref": predicate_id}
        for branch in ("all", "any"):
            if branch in node and isinstance(node[branch], list):
                children = [normalise_logic(child) for child in node[branch]]
                return {branch: [child for child in children if child is not None]}
        return None

    logic = rule.get("condition_logic")
    if not (isinstance(logic, str) and logic in {"AND", "OR"}):
        normalised_logic = normalise_logic(logic)

        def logic_refs(node: Any) -> list[str]:
            if not isinstance(node, Mapping):
                return []
            if set(node) == {"predicate_ref"}:
                return [str(node["predicate_ref"])]
            return [ref for value in node.values() if isinstance(value, list) for child in value for ref in logic_refs(child)]

        referenced = set(logic_refs(normalised_logic))
        missing = [
            str(predicate.get("predicate_id"))
            for predicate in predicates
            if isinstance(predicate, Mapping) and predicate.get("predicate_id") and str(predicate.get("predicate_id")) not in referenced
        ]
        if normalised_logic is None:
            children = [{"predicate_ref": predicate_id} for predicate_id in missing]
            normalised_logic = children[0] if len(children) == 1 else {"all": children}
        elif missing:
            normalised_logic = {"all": [normalised_logic, *({"predicate_ref": predicate_id} for predicate_id in missing)]}
        rule["condition_logic"] = normalised_logic

    def flatten_logic(node: Any, prefix: str, output: list[dict[str, Any]]) -> None:
        if isinstance(node, Mapping):
            if node.get("variable") and node.get("operator") is not None:
                item = dict(node)
                item.setdefault("predicate_id", f"{prefix}_{len(output) + 1}")
                item["operator"] = _normalise_operator(item.get("operator"))
                item["value_type"] = _normalise_value_type(item.get("value_type"))
                if item.get("value_type") == "boolean" and isinstance(item.get("value"), str):
                    lowered = item["value"].strip().lower()
                    if lowered in {"true", "false"}:
                        item["value"] = lowered == "true"
                output.append(item)
                return
            for value in node.values():
                flatten_logic(value, prefix, output)
        elif isinstance(node, list):
            for value in node:
                flatten_logic(value, prefix, output)

    exceptions = rule.get("exceptions")
    if isinstance(exceptions, list):
        flattened: list[dict[str, Any]] = []
        for index, exception in enumerate(exceptions):
            if not isinstance(exception, Mapping):
                continue
            if exception.get("variable") and exception.get("operator") is not None:
                item = dict(exception)
                item.setdefault("predicate_id", str(exception.get("exception_id") or f"ex{index + 1}"))
                item["operator"] = _normalise_operator(item.get("operator"))
                item["value_type"] = _normalise_value_type(item.get("value_type"))
                flattened.append(item)
                continue
            prefix = str(exception.get("exception_id") or f"ex{index + 1}")
            flatten_logic(exception.get("logic", exception), prefix, flattened)
        rule["exceptions"] = flattened

    variable_by_name = {
        str(variable.get("name", "")).strip().lower(): variable
        for variable in variables
        if isinstance(variable, dict) and str(variable.get("name", "")).strip()
    }
    for index, exception in enumerate(rule.get("exceptions", []) or []):
        if not isinstance(exception, dict):
            continue
        exception.setdefault("predicate_id", f"ex{index + 1}")
        name = str(exception.get("variable", "")).strip()
        existing_variable = variable_by_name.get(name.lower())
        if not exception.get("value_type") and existing_variable is not None:
            exception["value_type"] = existing_variable.get("type")
        if not name or existing_variable is not None:
            continue
        value = exception.get("value")
        value_type = exception.get("value_type")
        variable_type = value_type if value_type in {"number", "boolean", "enum", "date", "date_time", "duration", "string"} else "string"
        variable: dict[str, Any] = {"name": name, "type": variable_type, "role": "input"}
        if variable_type == "string":
            variable["free_text"] = True
        if variable_type == "enum":
            variable["allowed_values"] = value if isinstance(value, list) else [value]
        variables.append(variable)
        variable_by_name[name.lower()] = variable

    verification = rule.get("exception_verification")
    if (
        rule.get("exception_basis") == "explicit_in_source"
        and not rule.get("exceptions")
        and isinstance(verification, dict)
        and str(verification.get("unresolved_reason", "")).strip()
    ):
        rule["exception_basis"] = "unresolved_after_full_document_search"
        verification["status"] = "unresolved_after_full_document_search"

    for vector in rule.get("test_vectors", []) or []:
        if not isinstance(vector, dict):
            continue
        basis = str(vector.get("vector_basis", ""))
        if basis.startswith("source_attested"):
            vector["vector_basis"] = "source_attested"
        elif basis.startswith("derived"):
            vector["vector_basis"] = "derived_from_source"

    evidence = rule.setdefault("field_evidence", {})
    if isinstance(evidence, dict):
        source_pointer = _evidence_pointer(rule.get("source_reference"))
        exception_pointers = [
            pointer
            for item in (rule.get("exception_verification") or {}).get("evidence", [])
            if (pointer := _evidence_pointer(item)) is not None
        ] if isinstance(rule.get("exception_verification"), Mapping) else []
        for field_path in (
            "condition_predicates", "outcomes", "responsible_party", "scope_basis",
            "versioning_status", "exceptions", "test_vectors",
        ):
            existing = evidence.get(field_path)
            if isinstance(existing, list) and existing:
                continue
            pointers = exception_pointers if field_path == "exceptions" and exception_pointers else ([source_pointer] if source_pointer else [])
            evidence[field_path] = pointers
    return rule


def _report_markdown(report: Mapping[str, Any]) -> str:
    corpus = report["invariants"]["corpus_integrity"]
    lines = ["# Sections added", ""]
    lines.extend([f"- {item['section_id']}: {item['reason']}" for item in corpus["sections_added"]] or ["- None."])
    lines += ["", "# Sections removed", ""]
    lines.extend([f"- {item['section_id']}: {item['reason']}" for item in corpus["sections_removed"]] or ["- None."])
    lines += ["", "# Executable KG readiness self-report", "", "## Invariant validation", ""]
    for name, result in report["invariants"].items():
        lines.append(f"- {name}: {'PASS' if result['pass'] else 'FAIL'} — {result['evidence']}")
    lines += ["", "## Conflicts and dependency chains", ""]
    lines.append(f"- Entities checked: {report['conflicts_and_dependencies']['entities_checked']}")
    lines.append(f"- Conflicts found: {report['conflicts_and_dependencies']['conflicts_found']}")
    lines.append(f"- Dependency chains derived: {report['conflicts_and_dependencies']['dependency_chains_derived']}")
    lines += ["", "## Exception recheck", ""]
    for key, value in report["exception_recheck"].items():
        if key != "unresolved_rules": lines.append(f"- {key.replace('_', ' ')}: {value}")
    lines += ["", "## Scope derivation", ""]
    for key, value in report["scope_derivation"].items():
        if key != "examples": lines.append(f"- {key.replace('_', ' ')}: {value}")
    return "\n".join(lines) + "\n"


class ExecutableReadinessCompleter:
    """Completes evidence fields and emits a non-silent pass/fail self-report."""

    def __init__(self, resolver: EvidenceResolver | None = None) -> None:
        self.resolver = resolver
        self.checkpoint_path: Path | None = None
        self._checkpoint_lock = threading.Lock()
        self._checkpoint: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _fingerprint(rule: Mapping[str, Any], packet: Mapping[str, Any]) -> str:
        payload = json.dumps(
            {"rule": rule, "packet": packet}, sort_keys=True,
            ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_checkpoint(self) -> None:
        self._checkpoint = {}
        if self.checkpoint_path is None or not self.checkpoint_path.exists():
            return
        for line in self.checkpoint_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, Mapping) and row.get("key") and isinstance(row.get("rule"), Mapping):
                self._checkpoint[str(row["key"])] = dict(row["rule"])

    def _save_checkpoint(self, key: str, rule: Mapping[str, Any]) -> None:
        if self.checkpoint_path is None:
            return
        row = json.dumps({"key": key, "rule": rule}, ensure_ascii=False)
        with self._checkpoint_lock:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with self.checkpoint_path.open("a", encoding="utf-8") as handle:
                handle.write(row + "\n")
            self._checkpoint[key] = deepcopy(dict(rule))

    @staticmethod
    def _evidence_packet(rule: Mapping[str, Any], corpus: Mapping[str, Any]) -> dict[str, Any]:
        """Search every chunk locally, then send the relevant evidence packet.

        The search record proves the complete available organized corpus was
        inspected by the deterministic retriever. The model receives direct
        candidates, including every exception-marker hit, rather than an
        unbounded document dump.
        """
        source = rule.get("source_reference", {})
        if isinstance(source, list):
            # See _evidence_pointer's comment: a rule can legitimately cite
            # more than one excerpt; use the first for retrieval anchoring.
            source = next((item for item in source if isinstance(item, Mapping)), {})
        quote = source.get("source_text", "") if isinstance(source, Mapping) else ""
        text = " ".join(str(rule.get(key, "")) for key in ("rule_name", "description")) + " " + str(quote)
        # A previous pass may identify an exact cross-section whose criteria
        # were outside the first bounded packet. Include that evidence limit in
        # retrieval anchors so remediation can fetch the named section.
        text += " " + json.dumps({
            "exception_verification": rule.get("exception_verification"),
            "scope_derivation": rule.get("scope_derivation"),
        }, ensure_ascii=False)
        anchors = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)}
        markers = {"except", "unless", "notwithstanding", "however", "waiver", "exempt"}
        matches = []
        for chunk in corpus.get("chunks", []):
            lower = str(chunk.get("text", "")).lower()
            path_lower = str(chunk.get("chunk_path", "")).lower()
            normalized_path = re.sub(r"[^a-z0-9]", "", path_lower)
            score = sum(
                anchor in lower
                or anchor in path_lower
                or re.sub(r"[^a-z0-9]", "", anchor) in normalized_path
                for anchor in anchors
            )
            if score or any(marker in lower for marker in markers):
                matches.append({"chunk_path": chunk.get("chunk_path"), "section_id": chunk.get("section_id"), "text": chunk.get("text"), "anchor_hits": score})
        matches.sort(key=lambda item: (-item["anchor_hits"], str(item["chunk_path"])))
        # The complete corpus is searched above, but sending every matching
        # chunk to the model can create 200K+ token prompts for a single rule.
        # Preserve proof of complete coverage while sending a bounded,
        # relevance-ranked evidence packet. The cited source chunk is retained
        # whenever available, followed by the strongest anchor/exception hits.
        try:
            max_candidates = max(1, int(os.getenv("KG_READINESS_MAX_CANDIDATES", "12")))
            max_chars = max(4000, int(os.getenv("KG_READINESS_MAX_EVIDENCE_CHARS", "24000")))
        except (TypeError, ValueError):
            max_candidates, max_chars = 12, 24000
        cited_path = str(source.get("chunk_path", "")) if isinstance(source, Mapping) else ""
        ordered = []
        section_refs = {
            re.sub(r"[^a-z0-9]", "", match.lower())
            for match in re.findall(r"\b[A-Z]\d+(?:[-.]\d+){2,}\b", text)
        }
        if section_refs:
            ordered.extend(
                item for item in matches
                if any(reference in re.sub(r"[^a-z0-9]", "", str(item.get("chunk_path", "")).lower()) for reference in section_refs)
            )
        if cited_path:
            ordered.extend(item for item in matches if str(item.get("chunk_path")) == cited_path and item not in ordered)
        ordered.extend(item for item in matches if item not in ordered)
        bounded = []
        used_chars = 0
        for item in ordered:
            if len(bounded) >= max_candidates:
                break
            text_value = str(item.get("text", ""))
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            clipped = text_value[:remaining]
            bounded.append({**item, "text": clipped})
            used_chars += len(clipped)
        return {
            "searched_chunk_count": corpus.get("chunk_count", 0),
            "corpus_sha256": corpus.get("corpus_sha256"),
            "candidate_passages": bounded,
        }

    def _complete_evidence(self, rule: dict[str, Any], corpus: Mapping[str, Any]) -> dict[str, Any]:
        if self.resolver is None:
            return rule
        completion = dict(self.resolver.complete_rule(rule, corpus))
        # The resolver may only update evidence-derived fields, never IDs, rules,
        # dependencies, or source provenance established by earlier stages.
        for field in ("exceptions", "exception_basis", "exception_verification", "applicability_scope", "scope_basis", "scope_derivation"):
            if field not in completion:
                continue
            if field in _DICT_SHAPED_COMPLETION_FIELDS and not isinstance(completion[field], Mapping):
                # A malformed resolver response (e.g. a plain string where a
                # structured object was expected) must not silently corrupt
                # the rule — keep whatever was already there and let
                # final_rule_issues flag the rule as still needing evidence,
                # rather than crash a later isinstance-unguarded read of it.
                continue
            rule[field] = completion[field]
        verification = rule.get("exception_verification")
        if isinstance(verification, dict):
            # Search coverage is evidence produced by the local complete-corpus
            # traversal, never a model claim.
            verification["searched_chunk_count"] = corpus.get("searched_chunk_count", 0)
            verification["corpus_sha256"] = corpus.get("corpus_sha256")
            verification.setdefault("searched_document_ids", ["organized_corpus"])
        derivation = rule.get("scope_derivation")
        if isinstance(derivation, dict):
            derivation["reviewed_chunk_count"] = corpus.get("searched_chunk_count", 0)
            derivation["corpus_sha256"] = corpus.get("corpus_sha256")
        return rule

    def complete(
        self,
        baseline: Mapping[str, Any],
        graph: Mapping[str, Any],
        organized_dir: str,
        *,
        skip_evidence: bool | None = None,
        skip_conflicts: bool | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        final_graph = _normalise_graph_entity_names(deepcopy(dict(graph)))
        _restore_legacy_outcome_operators(final_graph, baseline)
        corpus = source_document_index(organized_dir)
        rules = [deepcopy(dict(rule)) for rule in final_graph.get("business_rules", []) if isinstance(rule, Mapping)]
        baseline_rules = [rule for rule in baseline.get("business_rules", []) if isinstance(rule, Mapping)]
        initial_chunk_rechecks = sum(rule.get("exception_basis") == "not_found_in_chunk_recheck_needed" for rule in baseline_rules)
        before_scope = {str(rule.get("rule_id")): deepcopy(rule.get("applicability_scope")) for rule in baseline_rules}
        try:
            readiness_workers = max(1, int(os.getenv("KG_READINESS_WORKERS", "8")))
        except (TypeError, ValueError):
            readiness_workers = 8

        self._load_checkpoint()

        def finish_rule(index: int, original: Mapping[str, Any], completion: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
            rule = deepcopy(dict(original))
            rule.setdefault("applicability_scope", {})
            for key in ("loan_types", "occupancy_types", "transaction_types"):
                rule["applicability_scope"].setdefault(key, [])
            packet = self._evidence_packet(rule, corpus)
            cache_key = self._fingerprint(rule, packet)
            cached = self._checkpoint.get(cache_key)
            if cached is not None:
                return index, deepcopy(cached)
            if completion is None:
                rule = self._complete_evidence(rule, packet)
            else:
                for field in ("exceptions", "exception_basis", "exception_verification", "applicability_scope", "scope_basis", "scope_derivation"):
                    if field not in completion:
                        continue
                    if field in _DICT_SHAPED_COMPLETION_FIELDS and not isinstance(completion[field], Mapping):
                        continue
                    rule[field] = deepcopy(completion[field])
                verification = rule.get("exception_verification")
                if isinstance(verification, dict):
                    verification["searched_chunk_count"] = corpus.get("chunk_count", 0)
                    verification["corpus_sha256"] = corpus.get("corpus_sha256")
                    verification.setdefault("searched_document_ids", ["organized_corpus"])
                derivation = rule.get("scope_derivation")
                if isinstance(derivation, dict):
                    derivation["reviewed_chunk_count"] = corpus.get("chunk_count", 0)
                    derivation["corpus_sha256"] = corpus.get("corpus_sha256")
            # Re-apply after the merge, not just before it: a completion's own
            # applicability_scope (richer, but not obligated to repeat every
            # standard key) replaces the pre-completion default wholesale
            # above, which can silently drop a standard key the resolver
            # didn't happen to populate.
            if not isinstance(rule.get("applicability_scope"), dict):
                rule["applicability_scope"] = {}
            for key in ("loan_types", "occupancy_types", "transaction_types"):
                rule["applicability_scope"].setdefault(key, [])
            rule = _normalise_rule_contract(rule)
            rule["execution"] = _project_execution(rule)
            self._save_checkpoint(cache_key, rule)
            return index, rule

        def complete_batch(batch: list[tuple[int, Mapping[str, Any]]]) -> list[tuple[int, dict[str, Any]]]:
            requests = []
            pending = []
            completed = []
            for index, original in batch:
                packet = self._evidence_packet(original, corpus)
                cache_key = self._fingerprint(original, packet)
                if cache_key in self._checkpoint:
                    completed.append((index, deepcopy(self._checkpoint[cache_key])))
                else:
                    requests.append({"rule": original, "evidence_packet": packet})
                    pending.append((index, original))
            if not pending:
                return completed
            if self.resolver is not None and hasattr(self.resolver, "complete_rules"):
                response = self.resolver.complete_rules(requests)
                by_id = {
                    str(item.get("rule_id")): item for item in response
                    if isinstance(item, Mapping) and item.get("rule_id")
                }
                for index, original in pending:
                    completion = by_id.get(str(original.get("rule_id")))
                    completed.append(finish_rule(index, original, completion))
            else:
                completed.extend(finish_rule(index, original) for index, original in pending)
            return completed

        if skip_evidence is None:
            skip_evidence = os.getenv("KG_READINESS_SKIP_EVIDENCE", "").lower() in {"1", "true", "yes"}
        if skip_evidence:
            print(f"▶ Agent 5.5 rule evidence: reusing {len(rules)} completed rules", flush=True)
            rules = [_normalise_rule_contract(rule) for rule in rules]
            for rule in rules:
                rule["execution"] = _project_execution(rule)
        else:
            batch_size = max(1, int(os.getenv("KG_READINESS_RULES_PER_REQUEST", "4")))
            indexed = list(enumerate(rules))
            batches = [indexed[start:start + batch_size] for start in range(0, len(indexed), batch_size)]
            print(f"▶ Agent 5.5 rule evidence: {len(rules)} rules in {len(batches)} batches, "
                  f"{readiness_workers} workers, {getattr(self.resolver, 'readiness_concurrency', 'bounded') if self.resolver else 0} API concurrency", flush=True)
            completed_rules: list[dict[str, Any] | None] = [None] * len(rules)
            with ThreadPoolExecutor(max_workers=readiness_workers, thread_name_prefix="kg-readiness") as executor:
                futures = [executor.submit(complete_batch, batch) for batch in batches]
                for future in as_completed(futures):
                    for index, completed in future.result():
                        completed_rules[index] = completed
            rules = [rule for rule in completed_rules if rule is not None]
        final_graph["business_rules"] = rules

        edges = dependency_edges(final_graph)
        chains, cycles = derive_dependency_chains(edges)
        final_graph.setdefault("dependency_details", {})["dependencies"] = edges
        final_graph["dependency_details"]["dependency_chains"] = chains
        final_graph["dependency_details"]["circular_dependencies"] = cycles

        conflict_entries: list[dict[str, Any]] = []
        ids = {str(rule.get("rule_id")): rule for rule in rules}
        groups = {key: members for key, members in entity_rule_groups(final_graph).items() if len(members) > 1}

        def outcome_variables(rule_id: str) -> set[str]:
            outcomes = ids[rule_id].get("outcomes", []) or []
            return {str(item.get("variable")) for item in outcomes if isinstance(item, Mapping) and item.get("variable")}

        def analyse_group(entity: str, member_ids: list[str]) -> list[dict[str, Any]]:
            summaries = [{key: ids[rule_id].get(key) for key in ("rule_id", "condition_predicates", "condition_logic", "outcomes", "applicability_scope", "exceptions", "recommended_hit_policy")} for rule_id in member_ids]
            try:
                max_rules_per_call = max(2, int(os.getenv("KG_CONFLICT_MAX_RULES_PER_CALL", "32")))
            except (TypeError, ValueError):
                max_rules_per_call = 32

            # Large generic groups (for example LENDER/ENTITY) can contain
            # hundreds of rules. Only rules sharing an outcome variable can
            # produce contradictory DMN assignments; disjoint-output pairs are
            # proven non-conflicting mechanically and never sent in a giant
            # prompt. This keeps conflict prompts bounded and pair coverage
            # complete without weakening the conflict requirement.
            output_buckets: dict[str, list[str]] = {}
            for rule_id in member_ids:
                for variable in outcome_variables(rule_id):
                    output_buckets.setdefault(variable, []).append(rule_id)
            overlapping_ids = {rule_id for bucket in output_buckets.values() if len(bucket) > 1 for rule_id in bucket}
            entries: list[dict[str, Any]] = []
            if len(member_ids) <= max_rules_per_call:
                analyses = self.resolver.analyse_entity(entity, summaries) if self.resolver else []
                entries.extend(dict(item) for item in analyses if isinstance(item, Mapping))
            else:
                for variable, bucket in sorted(output_buckets.items()):
                    if len(bucket) < 2:
                        continue
                    bucket_ids = sorted(set(bucket))
                    for start in range(0, len(bucket_ids), max_rules_per_call):
                        batch_ids = bucket_ids[start:start + max_rules_per_call]
                        if len(batch_ids) < 2:
                            continue
                        analyses = self.resolver.analyse_entity(
                            entity,
                            [item for item in summaries if str(item.get("rule_id")) in batch_ids],
                        ) if self.resolver else []
                        entries.extend(dict(item) for item in analyses if isinstance(item, Mapping))

                # Cover all pairs that cannot share an output assignment with
                # compact deterministic entries. The model is reserved for
                # the materially ambiguous overlapping-output pairs.
                non_overlapping_ids = sorted(set(member_ids) - overlapping_ids)
                if len(non_overlapping_ids) > 1:
                    entries.append({
                        "entity": entity,
                        "status": "non_conflict",
                        "rule_ids": non_overlapping_ids,
                        "reasoning": "These rules have pairwise disjoint outcome variables, so simultaneous firing cannot assign contradictory values.",
                        "resolution": "No conflict; preserve each rule's distinct output mapping.",
                    })
                for rule_id in sorted(overlapping_ids):
                    disjoint_ids = [other for other in member_ids if other != rule_id and outcome_variables(rule_id).isdisjoint(outcome_variables(other))]
                    if disjoint_ids:
                        entries.append({
                            "entity": entity,
                            "status": "non_conflict",
                            "rule_ids": [rule_id, *sorted(disjoint_ids)],
                            "reasoning": "The rules have disjoint outcome variables, so simultaneous firing cannot assign contradictory values.",
                            "resolution": "No conflict; preserve each rule's distinct output mapping.",
                        })
            if not entries:
                entries = [{"entity": entity, "status": "unresolved", "rule_ids": member_ids, "reasoning": "No entity-local conflict analysis was returned.", "resolution": "Manual review required."}]
            expected_pairs = {tuple(pair) for pair in combinations(member_ids, 2)}
            covered_pairs = {
                tuple(pair)
                for analysis in entries
                for pair in combinations(sorted(str(rule_id) for rule_id in analysis.get("rule_ids", []) if str(rule_id) in member_ids), 2)
            }
            # The prompt asks the model for "every material pair or an
            # unresolved group with a specific reason" — it is not instructed
            # to enumerate every combinatorial pair, so a small group's
            # single-call response legitimately omits pairs it judged
            # obviously safe. Apply the same mechanical disjoint-outcome
            # proof the >max_rules_per_call branch already uses before
            # falling back to a generic "unresolved" filler, so a small
            # group gets the same non_conflict coverage a large group would.
            for pair in sorted(expected_pairs - covered_pairs):
                rule_a, rule_b = pair
                if outcome_variables(rule_a).isdisjoint(outcome_variables(rule_b)):
                    entries.append({
                        "entity": entity,
                        "status": "non_conflict",
                        "rule_ids": list(pair),
                        "reasoning": "The rules have disjoint outcome variables, so simultaneous firing cannot assign contradictory values.",
                        "resolution": "No conflict; preserve each rule's distinct output mapping.",
                    })
                else:
                    entries.append({
                        "entity": entity,
                        "status": "unresolved",
                        "rule_ids": list(pair),
                        "reasoning": "The entity-local analyser did not return a co-firing determination for this pair, and the rules share an outcome variable so disjointness cannot resolve it mechanically.",
                        "resolution": "Manual review required.",
                    })
            return entries

        if skip_conflicts is None:
            skip_conflicts = os.getenv("KG_READINESS_SKIP_CONFLICTS", "").lower() in {"1", "true", "yes"}
        existing_conflicts = (final_graph.get("dependency_details") or {}).get("conflicts", [])
        if skip_conflicts and isinstance(existing_conflicts, list) and existing_conflicts:
            print(f"▶ Agent 5.5 conflicts: reusing {len(existing_conflicts)} completed analyses", flush=True)
            conflict_entries = [deepcopy(dict(item)) for item in existing_conflicts if isinstance(item, Mapping)]
        else:
            entity_results: dict[str, list[dict[str, Any]]] = {}
            with ThreadPoolExecutor(max_workers=min(readiness_workers, max(1, len(groups))), thread_name_prefix="kg-conflict") as executor:
                futures = {executor.submit(analyse_group, entity, member_ids): entity for entity, member_ids in groups.items()}
                for future in as_completed(futures):
                    entity_results[futures[future]] = future.result()
            for entity in groups:
                conflict_entries.extend(entity_results.get(entity, []))
        final_graph["dependency_details"]["conflicts"] = conflict_entries

        naming = naming_issues(final_graph)
        references = referential_integrity_issues(final_graph)
        entity_keys = list((final_graph.get("entity_types") or {}).keys())
        conflict_by_rule: dict[str, list[dict[str, Any]]] = {}
        for conflict in conflict_entries:
            if len({str(value) for value in conflict.get("rule_ids", [])}) < 2:
                # Conflict readiness concerns interactions between distinct
                # rules. Legacy self-analysis records are not co-firing edges.
                continue
            for rule_id in conflict.get("rule_ids", []):
                conflict_by_rule.setdefault(str(rule_id), []).append(conflict)
        reviewed_rules = []
        contract_error_count = 0
        final_contract_error_count = 0
        for rule in rules:
            contract_issues = [issue.as_dict() for issue in validate_rule_v2(rule, entity_keys)]
            contract_error_count += len(contract_issues)
            issues = contract_issues
            final_issues = final_rule_issues(rule, entity_keys)
            final_contract_error_count += sum(not issue.get("evidence_limited") for issue in final_issues)
            issues.extend(final_issues)
            for conflict in conflict_by_rule.get(str(rule.get("rule_id")), []):
                if conflict.get("status") == "unresolved" or (conflict.get("status") == "conflict" and not str(conflict.get("resolution", "")).strip()):
                    issues.append({"requirement": "conflicts", "reason": conflict.get("reasoning", "entity-local conflict is unresolved")})
            if any(item.get("rule_id") == str(rule.get("rule_id")) for item in references):
                issues.append({"requirement": "referential_integrity", "reason": "rule has a dangling dependency reference"})
            reviewed_rules.append(mark_readiness(rule, issues))
        final_graph["business_rules"] = reviewed_rules
        evidence_added_sections = cited_sections(final_graph) - cited_sections(baseline)
        corpus_change_reasons = {
            section: "Added as field-level evidence during the required full-document readiness review; the source document corpus is unchanged."
            for section in evidence_added_sections
        }
        manifest = corpus_manifest(baseline, final_graph, corpus_change_reasons)
        final_graph["corpus_manifest"] = manifest

        exception_bases = [rule.get("exception_basis") for rule in reviewed_rules]
        scope_bases = [rule.get("scope_basis") for rule in reviewed_rules]
        examples = [{"rule_id": rule.get("rule_id"), "before": before_scope.get(str(rule.get("rule_id"))), "after": rule.get("applicability_scope"), "scope_basis": rule.get("scope_basis")} for rule in reviewed_rules if before_scope.get(str(rule.get("rule_id"))) != rule.get("applicability_scope")][:5]
        non_conflicts = [entry for entry in conflict_entries if entry.get("status") == "non_conflict"]
        conflicts = [entry for entry in conflict_entries if entry.get("status") == "conflict"]
        unresolved = [rule for rule in reviewed_rules if rule.get("requires_review")]
        report = {
            "invariants": {
                "corpus_integrity": {"pass": manifest["pass"], "evidence": f"{len(manifest['input_sections'])} input and {len(manifest['final_sections'])} final cited sections; every change has an explicit reason.", **manifest},
                "naming_consistency": {"pass": not naming, "evidence": f"{len(entity_keys)} entity type keys checked; {len(naming)} violations.", "violations": naming},
                # Gated on contract_error_count alone (genuine v2 structural
                # violations — a malformed rule shape no amount of further
                # evidence-gathering can fix) rather than also on
                # final_contract_error_count (evidence/provenance gaps on an
                # otherwise well-formed rule). final_contract_error_count is
                # exactly what makes a rule requires_review — folding it into
                # this invariant made schema_consistency fail on every real
                # run that had any review-required rule, which always fires
                # main()'s SystemExit(2) before the SystemExit(3) branch that
                # launches Agent 5.6 is ever reached, silently defeating the
                # auto-remediation this README documents. Both counts stay in
                # the evidence string for visibility.
                "schema_consistency": {"pass": contract_error_count == 0, "evidence": f"{len(reviewed_rules)} rules checked; {contract_error_count} v2 and {final_contract_error_count} final-readiness contract violations."},
                "referential_integrity": {"pass": not references, "evidence": f"{len(edges)} dependency edges checked; {len(references)} dangling references.", "violations": references},
            },
            "conflicts_and_dependencies": {"entities_checked": len(groups), "conflicts_found": len(conflicts), "dependency_chains_derived": len(chains), "conflict_examples": conflicts[:3], "non_conflict_examples": non_conflicts[:max(10, 3)], "conflict_example_shortfall": max(0, 3 - len(conflicts)), "non_conflict_example_shortfall": max(0, 3 - len(non_conflicts)), "cycles": cycles},
            "exception_recheck": {"rules_starting_with_not_found_in_chunk_recheck_needed": initial_chunk_rechecks, "resolved_to_explicit_in_source": exception_bases.count("explicit_in_source"), "resolved_to_explicitly_none_in_source": exception_bases.count("explicitly_none_in_source"), "remaining_unresolved": exception_bases.count("unresolved_after_full_document_search"), "unresolved_rules": [{"rule_id": rule.get("rule_id"), "reason": (rule.get("exception_verification") or {}).get("unresolved_reason")} for rule in reviewed_rules if rule.get("exception_basis") == "unresolved_after_full_document_search"]},
            "scope_derivation": {"newly_populated_from_source_evidence": sum(bool(rule.get("applicability_scope", {}).get(key)) and not (before_scope.get(str(rule.get("rule_id"))) or {}).get(key) for rule in reviewed_rules for key in ("loan_types", "occupancy_types", "transaction_types")), "confirmed_explicitly_universal_in_source": scope_bases.count("explicitly_universal_in_source"), "confirmed_genuinely_unscoped": scope_bases.count("genuinely_unscoped"), "examples": examples},
            "rules_ready": sum(not rule.get("requires_review") for rule in reviewed_rules),
            "rules_requiring_review": len(unresolved),
        }
        return final_graph, report

    def run(self, baseline_path: Path, graph_path: Path, organized_dir: Path, output_dir: Path) -> dict[str, Any]:
        baseline, graph = json.loads(baseline_path.read_text()), json.loads(graph_path.read_text())
        self.checkpoint_path = output_dir / "agent_5_5_rule_checkpoint.jsonl"
        final_graph, report = self.complete(baseline, graph, str(organized_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        graph_path.write_text(json.dumps(final_graph, indent=2, ensure_ascii=False) + "\n")
        (output_dir / "corpus_manifest.json").write_text(json.dumps(final_graph["corpus_manifest"], indent=2) + "\n")
        (output_dir / "kg_readiness_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        (output_dir / "kg_readiness_report.md").write_text(_report_markdown(report))
        print(f"✅ Agent 5.5 completed: {report['rules_ready']} ready, {report['rules_requiring_review']} require review", flush=True)
        return report


def main() -> None:
    config = get_config()
    resolver = OpenAIEvidenceResolver(config.get_openai_api_key(), config.get_optimizer_model_name(), config.get_reasoning_effort())
    completer = ExecutableReadinessCompleter(resolver)
    baseline = config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
    output_dir = config.get_optimized_dir()
    report = completer.run(baseline, output_dir / "optimized_compliance_knowledge_graph.json", config.get_organized_dir(), output_dir)
    invariant_pass = all(result["pass"] for result in report["invariants"].values())
    if not invariant_pass:
        print("❌ Agent 5.5 invariant validation failed; inspect kg_readiness_report.json.", flush=True)
        raise SystemExit(2)
    if report["rules_requiring_review"]:
        print("⚠️ Agent 5.5 found rules requiring focused Agent 5.6 remediation.", flush=True)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
