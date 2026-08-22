"""Regression tests for a real crash hit during a fresh fannie_mae pipeline run.

`final_rule_issues` must never raise regardless of what's in a rule's
`exception_verification` / `scope_derivation` fields — it is a validator, and
a validator's job on malformed input is to report a failure, not crash the
process running it. Before this fix, three of its checks used the idiom
`(verification or {}).get(...)`, which only substitutes `{}` when
`verification` is falsy. A non-empty string is truthy, so a corrupted
`exception_verification` (a string instead of the expected dict) passed
straight through to `.get()` and raised `AttributeError: 'str' object has no
attribute 'get'` — which is exactly what happened here: Agent 5.5's
`finish_rule`/`_complete_evidence` copied a resolver completion field into the
rule without checking its type, and `final_rule_issues` was the first
downstream reader unguarded against the resulting corruption.

Both layers are tested: kg_readiness.final_rule_issues (must never crash on
malformed input) and agent_5_5's field-copy loops (must not let the
corruption in in the first place).
"""

from copy import deepcopy
from unittest.mock import MagicMock

from tests.test_rule_contract import valid_rule
from utils.kg_readiness import final_rule_issues


def _final_ready_rule() -> dict:
    """A rule shaped to pass every final_rule_issues check cleanly, so each
    test can corrupt exactly one field and see exactly the issues that field
    change should — and should only — introduce."""
    rule = valid_rule()
    rule["applicability_scope"] = {"loan_types": ["conventional"], "occupancy_types": [], "transaction_types": []}
    rule["scope_basis"] = "explicit"
    rule["scope_derivation"] = {
        "reviewed_chunk_count": 12,
        "evidence": [{"chunk_path": "a.txt", "section_id": "S1", "source_text": "conventional loans only"}],
    }
    rule["exception_basis"] = "explicit_in_source"
    rule["exceptions"] = [{"predicate_id": "ex1", "variable": "x", "operator": "==", "value": 1}]
    rule["exception_verification"] = {
        "searched_chunk_count": 12,
        "evidence": [{"chunk_path": "a.txt", "section_id": "S1", "source_text": "except when x equals 1"}],
    }
    rule["execution"] = {"targets": ["DMN"], "dmn": {"hit_policy": "UNIQUE", "inputs": [], "outputs": []}}
    return rule


def test_baseline_fixture_is_actually_clean():
    """Sanity check the fixture itself before relying on it to isolate one
    field's effect at a time."""
    assert final_rule_issues(_final_ready_rule(), ["SELLER_SERVICER", "FANNIE_MAE"]) == []


def test_string_exception_verification_does_not_crash():
    """The exact real-world failure: exception_basis == 'explicit_in_source'
    with exception_verification corrupted to a plain string.

    _final_ready_rule() (via valid_rule()) carries real field_evidence.exceptions
    citations, which _best_evidence now recognizes as sufficient proof for the
    "found something" exception_basis — so a corrupted dedicated verification
    field no longer fails the rule outright here. That is the intended,
    improved behavior; test_string_exception_verification_with_no_field_evidence_fallback_fails
    below covers the case where no fallback exists.
    """
    rule = _final_ready_rule()
    rule["exception_verification"] = "malformed string instead of a dict"

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert issues == []


def test_string_exception_verification_with_no_field_evidence_fallback_fails():
    """With no field_evidence to fall back on, the same corruption must still
    be reported as a real, non-crashing issue — not silently accepted."""
    rule = _final_ready_rule()
    rule["exception_verification"] = "malformed string instead of a dict"
    rule["field_evidence"]["exceptions"] = []

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    reasons = {issue["reason"] for issue in issues}
    assert "full-document search provenance is missing" in reasons
    assert "explicit exception lacks structured predicates or direct source evidence" in reasons


def test_string_exception_verification_with_unresolved_basis_does_not_crash():
    """unresolved_after_full_document_search has no positive citation to fall
    back on regardless of field_evidence — it must still require its own
    evidence-limit explanation."""
    rule = _final_ready_rule()
    rule["exception_basis"] = "unresolved_after_full_document_search"
    rule["exception_verification"] = "malformed string instead of a dict"

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    reasons = {issue["reason"] for issue in issues}
    assert "unresolved exception lacks a specific evidence limit" in reasons


def test_string_scope_derivation_does_not_crash():
    """Same shape as the exception_verification case: field_evidence.scope_basis
    provides a sufficient fallback, so this no longer fails outright."""
    rule = _final_ready_rule()
    rule["scope_derivation"] = "malformed string instead of a dict"

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert issues == []


def test_unresolved_after_source_review_with_string_scope_derivation_does_not_crash():
    """The unresolved_reason read for scope_basis=='unresolved_after_source_review'
    used raw `rule.get("scope_derivation", {}).get(...)` — the same
    `(x or {})`-style trap already fixed for exception_verification, just not
    updated here. `.get(key, default)` never substitutes `default` for a
    truthy non-dict, so a string scope_derivation raised
    AttributeError: 'str' object has no attribute 'get'."""
    rule = _final_ready_rule()
    rule["scope_basis"] = "unresolved_after_source_review"
    rule["scope_derivation"] = "no clean scope statement found in the reviewed chunks"

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert any(issue["requirement"] == "scope" for issue in issues)


def test_string_scope_derivation_with_no_field_evidence_fallback_fails():
    rule = _final_ready_rule()
    rule["scope_derivation"] = "malformed string instead of a dict"
    rule["field_evidence"]["scope_basis"] = []

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    reasons = {issue["reason"] for issue in issues}
    assert "scope review provenance is missing" in reasons
    assert "source-derived scope lacks evidence entries" in reasons


def test_none_exception_verification_does_not_crash():
    """None is falsy, so the old `(x or {})` idiom happened to handle it —
    covered here so the fix doesn't regress the one case that used to work.
    Falls back to field_evidence.exceptions the same as the string case."""
    rule = _final_ready_rule()
    rule["exception_verification"] = None

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert issues == []

    rule["field_evidence"]["exceptions"] = []
    issues_without_fallback = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])
    assert any("provenance is missing" in issue["reason"] for issue in issues_without_fallback)


def test_list_shaped_exception_verification_does_not_crash():
    """Any non-Mapping type must be handled the same way, not just str."""
    rule = _final_ready_rule()
    rule["exception_verification"] = ["not", "a", "dict"]

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert issues == []

    rule["field_evidence"]["exceptions"] = []
    issues_without_fallback = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])
    assert any("provenance is missing" in issue["reason"] for issue in issues_without_fallback)


def test_well_formed_verification_and_derivation_still_pass():
    """The fix must not turn well-formed data into false failures."""
    assert final_rule_issues(_final_ready_rule(), ["SELLER_SERVICER", "FANNIE_MAE"]) == []


# ─────────────────────────────────────────────────────────────────────────
# Root cause: Agent 5.5 must not copy a malformed completion field into the
# rule in the first place.
# ─────────────────────────────────────────────────────────────────────────

def _completer():
    from agents.agent_5_5_executable_readiness import ExecutableReadinessCompleter

    completer = object.__new__(ExecutableReadinessCompleter)
    completer.resolver = MagicMock()
    return completer


def test_complete_evidence_rejects_string_exception_verification():
    """A malformed completion value must not overwrite the rule's existing
    evidence content. The corpus-provenance fields (searched_chunk_count,
    corpus_sha256) DO get re-stamped onto whatever exception_verification
    ends up being — that's `_complete_evidence`'s own job, run unconditionally
    after the field-copy loop — so this checks the substantive `evidence`
    content survived, not byte-for-byte equality with the original dict.
    """
    rule = _final_ready_rule()
    original_evidence = deepcopy(rule["exception_verification"]["evidence"])
    completer = _completer()
    completer.resolver.complete_rule.return_value = {
        "exception_verification": "the model returned a string here instead of an object",
    }

    result = completer._complete_evidence(rule, {"searched_chunk_count": 1, "corpus_sha256": "abc"})

    assert isinstance(result["exception_verification"], dict)
    assert result["exception_verification"]["evidence"] == original_evidence, (
        "a malformed completion value must never overwrite a rule's existing evidence"
    )


def test_complete_evidence_accepts_well_formed_exception_verification():
    rule = _final_ready_rule()
    completer = _completer()
    new_verification = {"searched_chunk_count": 5, "evidence": []}
    completer.resolver.complete_rule.return_value = {"exception_verification": new_verification}

    result = completer._complete_evidence(rule, {"searched_chunk_count": 5, "corpus_sha256": "xyz"})

    assert result["exception_verification"]["searched_chunk_count"] == 5
    # The corpus-derived provenance stamping must still apply to a good value.
    assert result["exception_verification"]["corpus_sha256"] == "xyz"


def test_complete_evidence_rejects_string_scope_derivation():
    rule = _final_ready_rule()
    original_evidence = deepcopy(rule["scope_derivation"]["evidence"])
    completer = _completer()
    completer.resolver.complete_rule.return_value = {"scope_derivation": "also malformed"}

    result = completer._complete_evidence(rule, {"searched_chunk_count": 1, "corpus_sha256": "abc"})

    assert isinstance(result["scope_derivation"], dict)
    assert result["scope_derivation"]["evidence"] == original_evidence


def test_complete_evidence_still_updates_string_fields_normally():
    """The fix must be scoped to the dict-shaped fields only — plain string/
    list fields the resolver is allowed to update must still flow through."""
    rule = _final_ready_rule()
    completer = _completer()
    completer.resolver.complete_rule.return_value = {
        "exception_basis": "explicitly_none_in_source",
        "exceptions": [],
    }

    result = completer._complete_evidence(rule, {"searched_chunk_count": 1, "corpus_sha256": "abc"})

    assert result["exception_basis"] == "explicitly_none_in_source"
    assert result["exceptions"] == []


# ─────────────────────────────────────────────────────────────────────────
# scope_basis: "explicit_in_source" must be held to the same evidence
# requirement as "explicit" in final_rule_issues, not silently exempted.
# ─────────────────────────────────────────────────────────────────────────

def test_explicit_in_source_scope_basis_still_requires_evidence():
    """With no evidence anywhere — dedicated or field_evidence fallback — an
    explicit_in_source scope claim must still be rejected."""
    rule = _final_ready_rule()
    rule["scope_basis"] = "explicit_in_source"
    rule["scope_derivation"]["evidence"] = []
    rule["field_evidence"]["scope_basis"] = []

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert any(issue["reason"] == "source-derived scope lacks evidence entries" for issue in issues)


def test_explicit_in_source_scope_basis_falls_back_to_field_evidence():
    """The dedicated scope_derivation.evidence is empty, but field_evidence.
    scope_basis (real, validated citations) is not — that must be enough."""
    rule = _final_ready_rule()
    rule["scope_basis"] = "explicit_in_source"
    rule["scope_derivation"]["evidence"] = []

    assert final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"]) == []


def test_explicit_in_source_scope_basis_with_evidence_passes():
    rule = _final_ready_rule()
    rule["scope_basis"] = "explicit_in_source"

    assert final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"]) == []


# ─────────────────────────────────────────────────────────────────────────
# scope_basis: "explicitly_none_in_source" must be held to the exact same
# evidence requirement as "explicit_in_source" — the real-world rules that
# use it (BATCH24-RULE-004, BATCH24-RULE-005, FM-B57-R3, BR-62-005) are
# genuinely well-evidenced, not information-free the way "genuinely_unscoped"
# is allowed to be.
# ─────────────────────────────────────────────────────────────────────────

def test_explicitly_none_in_source_scope_basis_still_requires_evidence():
    rule = _final_ready_rule()
    rule["scope_basis"] = "explicitly_none_in_source"
    rule["scope_derivation"]["evidence"] = []
    rule["field_evidence"]["scope_basis"] = []

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert any(issue["reason"] == "source-derived scope lacks evidence entries" for issue in issues)


def test_explicitly_none_in_source_scope_basis_with_evidence_passes():
    rule = _final_ready_rule()
    rule["scope_basis"] = "explicitly_none_in_source"

    assert final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"]) == []


# ─────────────────────────────────────────────────────────────────────────
# scope_derivation / exception_verification: a "source_evidence" list of
# {chunk_path, section_id, quote} entries is the same citation as a
# documented "evidence" list of {chunk_path, section_id, source_text}
# entries under a different field/key name (observed on FM-B57-R3 and
# BR-62-005) — it must not be treated as absent evidence.
# ─────────────────────────────────────────────────────────────────────────

def test_scope_derivation_source_evidence_alias_satisfies_the_evidence_check():
    rule = _final_ready_rule()
    rule["scope_basis"] = "explicit_in_source"
    rule["scope_derivation"] = {
        "derivation_type": "textual_scope_from_condition",
        "reviewed_chunk_count": 3,
        "source_evidence": [{"chunk_path": "a.txt", "section_id": "S1", "quote": "In all cases"}],
    }
    rule["field_evidence"]["scope_basis"] = []

    assert final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"]) == []


def test_exception_verification_source_evidence_alias_satisfies_the_evidence_check():
    rule = _final_ready_rule()
    rule["exception_basis"] = "explicit_in_source"
    rule["exception_verification"] = {
        "derivation_type": "textual_exception_from_condition",
        "searched_chunk_count": 3,
        "source_evidence": [{"chunk_path": "a.txt", "section_id": "S1", "quote": "unless waived in writing"}],
    }
    rule["field_evidence"]["exceptions"] = []

    assert final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"]) == []


# ─────────────────────────────────────────────────────────────────────────
# applicability_scope: a missing standard key must be treated the same as an
# explicit empty list, not as a type violation.
#
# Root cause: a resolver completion replaces applicability_scope wholesale
# with whatever it returns, which can add richer domain-specific keys
# (jurisdiction, trigger_event, ...) without repeating every one of the three
# standard keys. Agent 5.5's own `.setdefault(key, [])` backfill only ran
# before that replacement, so 12 of 352 rules in one real run had a real,
# populated applicability_scope that still failed this check for lacking one
# standard key outright.
# ─────────────────────────────────────────────────────────────────────────

def test_missing_standard_scope_key_is_treated_as_empty_list():
    rule = _final_ready_rule()
    rule["applicability_scope"] = {
        "loan_types": ["conventional"],
        "jurisdiction": ["TX"],
        # occupancy_types and transaction_types omitted entirely, not empty.
    }

    assert final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"]) == []


def test_wrong_typed_scope_key_is_still_rejected():
    """The fix must not accept a genuinely wrong type for a present key."""
    rule = _final_ready_rule()
    rule["applicability_scope"] = {
        "loan_types": "conventional",  # a string, not a list — a real defect
        "occupancy_types": [],
        "transaction_types": [],
    }

    issues = final_rule_issues(rule, ["SELLER_SERVICER", "FANNIE_MAE"])

    assert any("list-valued" in issue["reason"] for issue in issues)
