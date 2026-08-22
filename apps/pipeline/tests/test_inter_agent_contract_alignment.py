"""Structural contract-alignment checks between agents and their validators.

Every bug found and fixed in this session was the same shape: one agent (or
its prompt) produces a field's value or shape, a different stage (a
validator, or a later agent) reads that same field expecting something else,
and nothing tied the two together — so the mismatch was invisible until a
real extraction run hit it:

  - Agent 3's extraction reasonably produced scope_basis "explicit_in_source"
    (by direct analogy to exception_basis's own documented convention), but
    utils.rule_contract.SCOPE_BASES only accepted bare "explicit" — 261 of 275
    schema violations on one real run, from a single missing enum entry.
  - Agent 5.5's readiness-completion prompt documents scope_derivation /
    exception_verification with an "evidence" list; when the resolver judged
    an already-final-looking rule as not needing further derivation and
    omitted the field, Agent 3's own (differently-shaped) candidate value was
    left in place, and kg_readiness.final_rule_issues had no fallback for it.
  - Agent 2 produced PascalCase entity names; the naming_consistency invariant
    required SCREAMING_SNAKE_CASE, and the only normalization was a fixed list
    of six previously-discovered legacy names.
  - A resolver completion replaced applicability_scope wholesale, dropping a
    standard key it didn't happen to populate, silently regressing "ready" to
    "review required" for real, well-scoped rules.

test_data_contracts.py already checks that domain PROMPT FILES contain the
field names agents read — that catches a prompt regressing independently of
its domain siblings. It does not check that a validator's *value* enums agree
with what a prompt tells the model is valid, which is the specific gap every
bug above fell through. These tests close that gap: they parse the actual
prompt text and cross-check it against the actual validator constants and
functions, so a future value/shape drift between an agent's output contract
and its consumer fails a test immediately, in CI, rather than surfacing 260
violations deep into a real paid extraction run.
"""

import re
from pathlib import Path

from agents.agent_5_5_executable_readiness import (
    LEGACY_ENTITY_NAMES,
    _normalise_graph_entity_names,
    _project_execution,
    _to_screaming_snake_case,
)
from tests.test_rule_contract import valid_rule
from utils.kg_readiness import CANONICAL_ENTITY_RE, final_rule_issues, naming_issues
from utils.rule_contract import (
    EXCEPTION_BASES,
    HIT_POLICIES,
    SCOPE_BASES,
    VALUE_TYPES,
    validate_rule_v2,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FINAL_SCOPE_BASES = {
    "explicit", "explicit_in_source", "explicitly_universal_in_source",
    "genuinely_unscoped", "unresolved_after_source_review",
}
FINAL_EXCEPTION_BASES = {
    "explicit_in_source", "explicitly_none_in_source",
    "unresolved_after_full_document_search",
}


def _pipe_enum(prompt_text: str, field: str) -> set[str]:
    """Extract a `"field": "a | b | c"` documented enum from a prompt."""
    match = re.search(rf'"{field}"\s*:\s*"([^"]+)"', prompt_text)
    assert match, f"prompt does not document a value list for {field!r}"
    return {value.strip() for value in match.group(1).split("|")}


# ─────────────────────────────────────────────────────────────────────────
# 1. FINAL_* enums must be a subset of the broader schema enums.
#
# A value valid at Agent 5.5's final-readiness gate but absent from
# utils.rule_contract's schema enum means a rule can pass readiness and still
# fail schema_consistency (or vice versa) — exactly the scope_basis bug. This
# is the single highest-value structural check: it would have failed the
# moment "explicit_in_source" was added to FINAL_SCOPE_BASES without also
# updating SCOPE_BASES, long before any real extraction ran.
# ─────────────────────────────────────────────────────────────────────────

def test_final_scope_bases_is_a_subset_of_schema_scope_bases():
    missing = FINAL_SCOPE_BASES - SCOPE_BASES
    assert not missing, (
        f"FINAL_SCOPE_BASES has value(s) {missing} that utils.rule_contract.SCOPE_BASES "
        f"does not accept — a rule could pass Agent 5.5's readiness gate and still fail "
        f"schema_consistency for its own scope_basis value."
    )


def test_final_exception_bases_is_a_subset_of_schema_exception_bases():
    missing = FINAL_EXCEPTION_BASES - EXCEPTION_BASES
    assert not missing, (
        f"FINAL_EXCEPTION_BASES has value(s) {missing} that utils.rule_contract."
        f"EXCEPTION_BASES does not accept."
    )


# ─────────────────────────────────────────────────────────────────────────
# 2. The readiness-completion prompt's documented enums must match the
# validator constants that check what it produces.
#
# This is a direct, mechanical guard against the exact scope_basis bug: parse
# what the prompt tells the model is valid, and assert every one of those
# values is actually accepted downstream.
# ─────────────────────────────────────────────────────────────────────────

def _readiness_completion_prompt() -> str:
    path = PROJECT_ROOT / "prompts" / "executable_readiness_completion.txt"
    return path.read_text(encoding="utf-8")


def test_prompt_documented_exception_basis_values_are_all_schema_valid():
    documented = _pipe_enum(_readiness_completion_prompt(), "exception_basis")
    undeclared = documented - EXCEPTION_BASES
    assert not undeclared, (
        f"executable_readiness_completion.txt documents exception_basis value(s) "
        f"{undeclared} that utils.rule_contract.EXCEPTION_BASES does not accept — "
        f"the model can be told to produce a value the schema will then reject."
    )


def test_prompt_documented_scope_basis_values_are_all_schema_valid():
    documented = _pipe_enum(_readiness_completion_prompt(), "scope_basis")
    undeclared = documented - SCOPE_BASES
    assert not undeclared, (
        f"executable_readiness_completion.txt documents scope_basis value(s) "
        f"{undeclared} that utils.rule_contract.SCOPE_BASES does not accept."
    )


def test_prompt_documented_exception_basis_values_are_final_states():
    """Every value this prompt may emit must be a FINAL state — it must never
    document the candidate-only not_found_in_chunk_recheck_needed value."""
    documented = _pipe_enum(_readiness_completion_prompt(), "exception_basis")
    assert documented <= FINAL_EXCEPTION_BASES, (
        f"executable_readiness_completion.txt documents non-final exception_basis "
        f"value(s) {documented - FINAL_EXCEPTION_BASES}"
    )


def test_prompt_documented_scope_basis_values_are_final_states():
    documented = _pipe_enum(_readiness_completion_prompt(), "scope_basis")
    assert documented <= FINAL_SCOPE_BASES, (
        f"executable_readiness_completion.txt documents non-final scope_basis "
        f"value(s) {documented - FINAL_SCOPE_BASES}"
    )


# ─────────────────────────────────────────────────────────────────────────
# 3. Every field the readiness-completion prompt promises to return is
# actually consumed somewhere (Agent 5.5's field-copy loop or
# final_rule_issues) — the inverse mismatch: a field nobody reads is a
# silent no-op at best and a sign the two were never reconciled at worst.
# ─────────────────────────────────────────────────────────────────────────

def test_every_promised_completion_field_is_consumed_by_agent_5_5():
    prompt = _readiness_completion_prompt()
    promised_top_level = {"exceptions", "exception_basis", "exception_verification",
                           "applicability_scope", "scope_basis", "scope_derivation"}
    for field in promised_top_level:
        assert f'"{field}"' in prompt, f"expected {field!r} in the prompt's own documented shape"

    agent_5_5_source = (PROJECT_ROOT / "agents" / "agent_5_5_executable_readiness.py").read_text()
    for field in promised_top_level:
        assert f'"{field}"' in agent_5_5_source, (
            f"executable_readiness_completion.txt promises {field!r} but "
            f"agent_5_5_executable_readiness.py never reads it back out of a completion"
        )


# ─────────────────────────────────────────────────────────────────────────
# 4. scope_derivation / exception_verification "evidence": the readiness
# prompt's documented shape must be exactly what final_rule_issues reads.
# ─────────────────────────────────────────────────────────────────────────

def test_readiness_completion_evidence_shape_matches_what_final_rule_issues_reads():
    prompt = _readiness_completion_prompt()
    # The prompt documents both objects with an "evidence": [...] list of
    # {chunk_path, section_id, source_text} records — assert that shape is
    # named exactly once for each field, matching final_rule_issues's own
    # `.get("evidence")` reads (see utils/kg_readiness.py::_best_evidence).
    for field in ("exception_verification", "scope_derivation"):
        segment = prompt[prompt.index(f'"{field}"'):]
        segment = segment[:segment.index("}}") + 2]
        assert '"evidence"' in segment, (
            f'{field} in executable_readiness_completion.txt must document an '
            f'"evidence" list — final_rule_issues reads exactly that key.'
        )


def test_field_evidence_fallback_actually_satisfies_final_rule_issues():
    """End-to-end: a rule whose dedicated verification/derivation is missing
    entirely, but whose field_evidence (Agent 3's own, schema-required output)
    has real citations, must be accepted — this is the fallback that makes
    the shape mismatch harmless instead of a silent rule loss."""
    rule = valid_rule()
    rule["scope_basis"] = "explicit_in_source"
    rule["exception_basis"] = "explicit_in_source"
    rule["applicability_scope"] = {"loan_types": ["conventional"], "occupancy_types": [], "transaction_types": []}
    rule["exceptions"] = [{"predicate_id": "ex1", "variable": "price_differential_amount", "operator": "==", "value": 1, "value_type": "number"}]
    rule.pop("scope_derivation", None)
    rule.pop("exception_verification", None)
    rule["execution"] = _project_execution(rule)

    assert final_rule_issues(rule, {"SELLER_SERVICER", "FANNIE_MAE"}) == []


# ─────────────────────────────────────────────────────────────────────────
# 5. _project_execution's output shape must match what final_rule_issues
# checks for a DMN/BPMN projection.
# ─────────────────────────────────────────────────────────────────────────

def test_project_execution_shape_satisfies_final_rule_issues_execution_check():
    rule = valid_rule()
    rule["rule_type"] = "compliance"  # eligible for a BPMN projection too

    execution = _project_execution(rule)

    assert execution["targets"], "a rule with input+output variables must get at least a DMN target"
    assert isinstance(execution.get("dmn"), dict)
    assert set(execution["dmn"]) >= {"input_columns", "output_columns", "hit_policy"}
    if "BPMN" in execution["targets"]:
        assert isinstance(execution.get("bpmn"), dict)
        assert set(execution["bpmn"]) >= {"gateway_type", "lane", "true_path_outcome_variables"}

    rule["execution"] = execution
    rule["scope_basis"], rule["exception_basis"] = "genuinely_unscoped", "explicitly_none_in_source"
    rule["scope_derivation"] = {"reviewed_chunk_count": 1}
    rule["exception_verification"] = {"searched_chunk_count": 1}
    issues = final_rule_issues(rule, {"SELLER_SERVICER", "FANNIE_MAE"})
    assert not any(issue["requirement"] == "execution" for issue in issues)


def test_final_rule_issues_execution_check_reads_exactly_the_keys_project_execution_writes():
    """A structural cross-check: every key final_rule_issues's execution
    branch reads must be one _project_execution actually writes, so adding a
    new required key to one side without the other fails immediately."""
    kg_readiness_source = (PROJECT_ROOT / "utils" / "kg_readiness.py").read_text()
    start = kg_readiness_source.index('execution = rule.get("execution")')
    end = kg_readiness_source.index("return issues", start)
    execution_check = kg_readiness_source[start:end]

    written_keys = set(_project_execution(valid_rule())) | {"dmn", "bpmn"}
    for key in ("targets", "dmn", "bpmn"):
        assert f'"{key}"' in execution_check, f"final_rule_issues no longer checks execution.{key}"
        assert key in written_keys, f"_project_execution no longer writes execution.{key}"


# ─────────────────────────────────────────────────────────────────────────
# 6. Entity naming: whatever casing convention an upstream agent uses, the
# normalized graph must always satisfy naming_issues == []. Enumerated
# structurally rather than against one fixed example list, so a new casing
# pattern (not just the ones already seen) is covered.
# ─────────────────────────────────────────────────────────────────────────

def test_normalise_graph_entity_names_output_always_satisfies_naming_issues():
    candidates = [
        "CreditScore", "DocumentCustodian", "PostClosingQCReview", "PACELoan",
        "PowerOfAttorney", "already_lower_snake", "Mixed_Case_Name", "SCREAMING_SNAKE_OK",
        *LEGACY_ENTITY_NAMES.keys(),
    ]
    graph = {
        "entity_types": {name: {} for name in candidates},
        "business_rules": [
            {"rule_id": f"R{i}", "responsible_party": name, "counterparties": []}
            for i, name in enumerate(candidates)
        ],
    }

    fixed = _normalise_graph_entity_names(graph)

    assert naming_issues(fixed) == []
    for key in fixed["entity_types"]:
        assert CANONICAL_ENTITY_RE.fullmatch(key), f"{key!r} is not canonical after normalization"


def test_to_screaming_snake_case_is_idempotent_for_every_canonical_form():
    """A conversion that isn't idempotent could re-mangle an
    already-canonical name on a second pass (e.g. a re-run over cached data)."""
    for name in ("FANNIE_MAE", "MBS_POOL", "SECURITY_INSTRUMENT", "A", "AB_CD"):
        once = _to_screaming_snake_case(name)
        twice = _to_screaming_snake_case(once)
        assert once == name, f"{name!r} should already be canonical"
        assert once == twice
