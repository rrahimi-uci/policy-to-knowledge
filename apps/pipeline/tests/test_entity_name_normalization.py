"""Tests for generalized entity-name normalization.

Context: `_normalise_graph_entity_names` only ever replaced six hardcoded
legacy names (LEGACY_ENTITY_NAMES). On a real fresh extraction run, Agent 2
produced 24 entity type keys, most in PascalCase (CreditScore,
DocumentCustodian, PostClosingQCReview, ...) — none of which matched the
hardcoded list, so all 24 passed through unnormalized and the
`naming_consistency` invariant failed with 380 violations, the single largest
non-schema blocker after the scope_basis fix.

`_build_entity_name_map` generalizes this: it computes canonical
SCREAMING_SNAKE_CASE forms for whatever entity_types keys a given graph
actually has, merged over the fixed legacy list, so the fix applies to any
run's actual output instead of requiring each new bad name to be added by
hand. Verified against all 24 real names before being wired in: every one
converts correctly, including an acronym run (QC) and a short word (Of), and
already-canonical names are untouched (idempotent).
"""

from agents.agent_5_5_executable_readiness import (
    LEGACY_ENTITY_NAMES,
    _build_entity_name_map,
    _normalise_graph_entity_names,
    _to_screaming_snake_case,
)
from utils.kg_readiness import CANONICAL_ENTITY_RE, naming_issues


# ─────────────────────────────────────────────────────────────────────────
# _to_screaming_snake_case — unit tests, including the real names it must
# handle correctly
# ─────────────────────────────────────────────────────────────────────────

def test_simple_pascal_case_name():
    assert _to_screaming_snake_case("CreditScore") == "CREDIT_SCORE"


def test_acronym_run_is_kept_as_its_own_segment():
    """PostClosingQCReview: the two-letter acronym QC must not be glued to
    the word before or after it."""
    assert _to_screaming_snake_case("PostClosingQCReview") == "POST_CLOSING_QC_REVIEW"


def test_short_connecting_word():
    assert _to_screaming_snake_case("PowerOfAttorney") == "POWER_OF_ATTORNEY"


def test_leading_acronym():
    assert _to_screaming_snake_case("PACELoan") == "PACE_LOAN"


def test_single_word_is_just_uppercased():
    assert _to_screaming_snake_case("Lender") == "LENDER"


def test_already_canonical_name_is_unchanged():
    """The conversion must be idempotent — re-running it on an
    already-correct name must not alter it."""
    for name in ("FANNIE_MAE", "SELLER_SERVICER", "MBS_POOL", "SECURITY_INSTRUMENT"):
        assert _to_screaming_snake_case(name) == name


def test_all_24_real_entity_names_from_one_extraction_run():
    """Locks in the exact conversions verified against a real graph before
    this fix was wired in — a regression here would silently break the fix
    for a case that already worked."""
    expected = {
        "MortgageLoan": "MORTGAGE_LOAN",
        "Lender": "LENDER",
        "DocumentCustodian": "DOCUMENT_CUSTODIAN",
        "MortgageDocument": "MORTGAGE_DOCUMENT",
        "LoanFile": "LOAN_FILE",
        "PostClosingQCReview": "POST_CLOSING_QC_REVIEW",
        "UnderwritingRiskAssessment": "UNDERWRITING_RISK_ASSESSMENT",
        "CreditScore": "CREDIT_SCORE",
        "InsurancePolicy": "INSURANCE_POLICY",
        "PACELoan": "PACE_LOAN",
        "FANNIE_MAE": "FANNIE_MAE",
        "SELLER_SERVICER": "SELLER_SERVICER",
        "POLICY_LOSS_EVENT": "POLICY_LOSS_EVENT",
        "MORTGAGE_NOTE": "MORTGAGE_NOTE",
        "DELIVERY_INSTRUCTION": "DELIVERY_INSTRUCTION",
        "REPRESENTATION_AND_WARRANTY": "REPRESENTATION_AND_WARRANTY",
        "MBS_POOL": "MBS_POOL",
        "BORROWER": "BORROWER",
        "MORTGAGE_DIFFERENTIAL_PAYMENTS_INCOME": "MORTGAGE_DIFFERENTIAL_PAYMENTS_INCOME",
        "RepresentationWarranty": "REPRESENTATION_WARRANTY",
        "MANUFACTURED_HOME": "MANUFACTURED_HOME",
        "LenderIncentive": "LENDER_INCENTIVE",
        "SECURITY_INSTRUMENT": "SECURITY_INSTRUMENT",
        "PowerOfAttorney": "POWER_OF_ATTORNEY",
    }
    for original, canonical in expected.items():
        assert _to_screaming_snake_case(original) == canonical, original


# ─────────────────────────────────────────────────────────────────────────
# _build_entity_name_map
# ─────────────────────────────────────────────────────────────────────────

def test_map_includes_the_fixed_legacy_names():
    mapping = _build_entity_name_map({"entity_types": {}})
    for original, canonical in LEGACY_ENTITY_NAMES.items():
        assert mapping[original] == canonical


def test_map_adds_non_canonical_keys_from_the_graph():
    mapping = _build_entity_name_map({"entity_types": {"CreditScore": {}, "FANNIE_MAE": {}}})
    assert mapping["CreditScore"] == "CREDIT_SCORE"
    assert "FANNIE_MAE" not in mapping, "an already-canonical key needs no mapping entry"


def test_map_does_not_override_an_explicit_legacy_mapping():
    """setdefault must not let a graph-derived guess replace a known-correct
    legacy mapping, even if they happened to disagree."""
    mapping = _build_entity_name_map({"entity_types": {"ManufacturedHome": {}}})
    assert mapping["ManufacturedHome"] == LEGACY_ENTITY_NAMES["ManufacturedHome"]


def test_map_fixes_a_rule_reference_that_never_appears_as_an_entity_types_key():
    """Real case from one extraction run: entity_types only ever defines
    "BORROWER" (already canonical), but one rule cites the counterparty as
    "Borrower" — that string is never a candidate at all if only entity_types
    keys are scanned, so the reference silently fails naming_issues forever."""
    graph = {
        "entity_types": {"BORROWER": {}, "FANNIE_MAE": {}},
        "business_rules": [{"rule_id": "R1", "responsible_party": "FANNIE_MAE", "counterparties": ["Borrower"]}],
    }
    mapping = _build_entity_name_map(graph)
    assert mapping["Borrower"] == "BORROWER"


def test_map_does_not_invent_a_mapping_for_an_unrelated_typo():
    """A reference that canonicalizes to a name nobody defined must be left
    alone — silently rewriting it to a different, still-undefined name would
    only make the underlying typo harder to spot in naming_issues output."""
    graph = {
        "entity_types": {"BORROWER": {}},
        "business_rules": [{"rule_id": "R1", "responsible_party": "Boroower", "counterparties": []}],
    }
    mapping = _build_entity_name_map(graph)
    assert "Boroower" not in mapping


# ─────────────────────────────────────────────────────────────────────────
# _normalise_graph_entity_names — integration, and the invariant it must
# satisfy: naming_issues drops to (near) zero afterward
# ─────────────────────────────────────────────────────────────────────────

def test_pascal_case_entity_keys_are_normalised_end_to_end():
    graph = {
        "entity_types": {"CreditScore": {"definition": "x"}, "DocumentCustodian": {}},
        "business_rules": [
            {"rule_id": "R1", "responsible_party": "DocumentCustodian", "counterparties": ["CreditScore"]},
        ],
    }

    fixed = _normalise_graph_entity_names(graph)

    assert set(fixed["entity_types"]) == {"CREDIT_SCORE", "DOCUMENT_CUSTODIAN"}
    assert fixed["business_rules"][0]["responsible_party"] == "DOCUMENT_CUSTODIAN"
    assert fixed["business_rules"][0]["counterparties"] == ["CREDIT_SCORE"]
    assert naming_issues(fixed) == []


def test_already_canonical_graph_is_unaffected():
    graph = {
        "entity_types": {"FANNIE_MAE": {}, "BORROWER": {}},
        "business_rules": [{"rule_id": "R1", "responsible_party": "FANNIE_MAE", "counterparties": ["BORROWER"]}],
    }

    fixed = _normalise_graph_entity_names(graph)

    assert fixed == graph
    assert naming_issues(fixed) == []


def test_mixed_canonical_and_pascal_case_graph():
    graph = {
        "entity_types": {"FANNIE_MAE": {}, "PostClosingQCReview": {}},
        "business_rules": [
            {"rule_id": "R1", "responsible_party": "PostClosingQCReview", "counterparties": ["FANNIE_MAE"]},
        ],
    }

    fixed = _normalise_graph_entity_names(graph)

    assert set(fixed["entity_types"]) == {"FANNIE_MAE", "POST_CLOSING_QC_REVIEW"}
    assert naming_issues(fixed) == []


def test_reference_only_casing_mismatch_is_fixed_end_to_end():
    graph = {
        "entity_types": {"BORROWER": {}, "FANNIE_MAE": {}},
        "business_rules": [{"rule_id": "R1", "responsible_party": "FANNIE_MAE", "counterparties": ["Borrower"]}],
    }

    fixed = _normalise_graph_entity_names(graph)

    assert fixed["business_rules"][0]["counterparties"] == ["BORROWER"]
    assert naming_issues(fixed) == []


def test_a_collision_between_two_distinct_names_raises_rather_than_silently_merging():
    """Two entity types that happen to canonicalize to the same name is a
    genuine data problem this function must surface, not paper over."""
    graph = {"entity_types": {"CreditScore": {"a": 1}, "credit_score": {"b": 2}}}

    try:
        _normalise_graph_entity_names(graph)
        assert False, "expected a collision ValueError"
    except ValueError as exc:
        assert "CREDIT_SCORE" in str(exc)


def test_real_graph_naming_violations_drop_from_380_to_at_most_a_handful(tmp_path):
    """Integration check against a graph shaped like the real one that
    surfaced this bug: many PascalCase entities, a few already-canonical
    (including the fixed legacy names), and rule references to both."""
    graph = {
        "entity_types": {
            name: {}
            for name in (
                "MortgageLoan", "Lender", "DocumentCustodian", "MortgageDocument", "LoanFile",
                "PostClosingQCReview", "UnderwritingRiskAssessment", "CreditScore", "InsurancePolicy",
                "PACELoan", "FANNIE_MAE", "SELLER_SERVICER", "RepresentationWarranty",
                "LenderIncentive", "PowerOfAttorney", "ManufacturedHome",
            )
        },
        "business_rules": [
            {"rule_id": "R1", "responsible_party": "CreditScore", "counterparties": ["FANNIE_MAE", "Lender"]},
            {"rule_id": "R2", "responsible_party": "ManufacturedHome", "counterparties": []},
        ],
    }
    before = len(naming_issues(graph))

    fixed = _normalise_graph_entity_names(graph)

    after = naming_issues(fixed)
    assert before >= 15, "fixture must reproduce a large violation count to be a meaningful check"
    assert after == [], f"expected zero remaining naming issues, got: {after}"
