"""The conformance fixture library.

Each fixture is a complete little Policy IR with a known, asserted outcome. Half
are meant to compile; half are meant to be refused, one refusal per fixture, so a
regression shows up as a specific blocker appearing or disappearing rather than as
a vague "something changed".

The negative fixtures map onto the plan's stress matrix: a fabricated attribute, a
compound clause with an exception, a modal flip, numeric and unit drift, an
unproven hit policy, a retention obligation that must not become a timer process,
a process with no actor, an unresolved cross-reference, and a wrong-span citation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from policy_ir import ids
from policy_ir.enums import (
    CompilationIntent,
    DataType,
    DependencyKind,
    DerivationMethod,
    Effect,
    EntityCategory,
    HitPolicy,
    Lifecycle,
    Modality,
    NullPolicy,
    Provenance,
    SemanticKind,
    SemanticRole,
)
from policy_ir.expressions import (
    All,
    Calendar,
    Comparison,
    ComparisonOperator,
    Literal,
    VariableRef,
)
from policy_ir.models import (
    AtomicPolicyClause,
    AuthoritySource,
    DataDefinition,
    DecisionModelCandidate,
    DecisionOutput,
    DependencyEdge,
    EffectivePeriod,
    EntityType,
    PolicyIR,
    ProcessActivity,
    ProcessFragmentCandidate,
    Scope,
    ScopeDimension,
    ScopeDimensionDefinition,
    TemporalConstraint,
    TriggerEvent,
)
from validation import blockers as codes

from .builder import DocumentHandle, FixtureBuilder

GE = ComparisonOperator.GE
LE = ComparisonOperator.LE
LT = ComparisonOperator.LT
GT = ComparisonOperator.GT
EQ = ComparisonOperator.EQ
N = DataType.NUMBER
S = DataType.STRING


@dataclass(frozen=True)
class Fixture:
    """One fixture plus what the gate and compilers are expected to conclude."""

    name: str
    description: str
    ir: PolicyIR
    texts: Mapping[str, str]
    expect_dmn: tuple[str, ...] = ()
    expect_bpmn: tuple[str, ...] = ()
    expect_codes: frozenset[str] = frozenset()
    forbid_codes: frozenset[str] = frozenset()

    def decision_id(self, name: str) -> str:
        for decision in self.ir.decisions:
            if decision.name == name:
                return decision.decision_id
        raise KeyError(f"fixture {self.name!r} has no decision named {name!r}")

    def process_id(self, name: str) -> str:
        for process in self.ir.processes:
            if process.name == name:
                return process.fragment_id
        raise KeyError(f"fixture {self.name!r} has no process named {name!r}")


# ---------------------------------------------------------------------------
# Shared source texts
# ---------------------------------------------------------------------------

ELIGIBILITY_TEXT = """Section 4.2 Purchase Eligibility

For purposes of this Section, a loan may be purchased when the borrower credit \
score is at least 620 and the loan-to-value ratio does not exceed 80 percent.

A loan with a borrower credit score below 620 may not be purchased.
"""

NOTICE_TEXT = """Section 7.1 Adverse Action Notice

After receiving a completed application, the Lender must evaluate purchase \
eligibility and must then send the adverse action notice to the borrower within \
30 calendar days. The file is closed once the notice has been sent.
"""

RETENTION_TEXT = """Section 9.4 Record Retention

The Lender must retain each loan file for 5 years after the loan is paid in full.
"""

FEE_TEXT = """Section 5.1 Upfront Fee

The Lender must pay an upfront fee of 0.25 percent of the guaranteed portion when \
the loan amount is greater than $500,000.
"""

SCOPED_TEXT = """Section 12.1 State Overlays

In California, a loan may be purchased when the borrower credit score is at least 660.

In New York, a loan may be purchased when the borrower credit score is at least 640.
"""

AUTHORITY_TEXT = """Section 3.1 Loans Below 640

The Guide provides that a loan must not be purchased if the borrower credit score \
is below 640.

Bulletin 2026-04 provides that a loan may be purchased when the borrower credit \
score is below 640.
"""

SUPERSESSION_TEXT = """Section 8.2 Documentation Standard

Effective 1 January 2025, a loan file must include 2 years of tax returns.

Effective 1 January 2026, a loan file must include 1 year of tax returns.
"""

RESTRICTED_TEXT = """Section 4.3 Restricted Counties

A loan may be purchased when the borrower credit score is at least 620, unless \
the property is located in a restricted county.
"""


def _lender() -> EntityType:
    return EntityType(
        entity_type_id="entity_lender",
        name="Lender",
        category=EntityCategory.ACTOR_OR_ROLE,
        provenance=Provenance.OBSERVED,
        definition="The approved seller/servicer that originates and delivers loans.",
    )


def _authority(section: str) -> EntityType:
    return EntityType(
        entity_type_id=ids.ncname(f"authority_{section}"),
        name=section,
        category=EntityCategory.AUTHORITY_OR_POLICY_SOURCE,
        provenance=Provenance.OBSERVED,
    )


# ---------------------------------------------------------------------------
# Eligibility: the canonical clean decision
# ---------------------------------------------------------------------------


def _eligibility_parts(handle: DocumentHandle) -> dict[str, object]:
    """Build the shared eligibility decision, its clauses and its inputs."""
    condition_a = handle.cite(
        "the borrower credit score is at least 620 and the loan-to-value ratio does "
        "not exceed 80 percent",
        SemanticRole.CONDITION,
    )
    effect_a = handle.cite("a loan may be purchased", SemanticRole.EFFECT)
    condition_b = handle.cite("a borrower credit score below 620", SemanticRole.CONDITION)
    effect_b = handle.cite("may not be purchased", SemanticRole.EFFECT)

    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        provenance=Provenance.OBSERVED,
        minimum=Literal(300, N),
        maximum=Literal(850, N),
        null_policy=NullPolicy.REJECT,
        owning_entity_id="entity_lender",
        evidence_ids=(condition_a,),
    )
    ltv = DataDefinition(
        data_definition_id="ltv_ratio",
        name="loan to value ratio",
        type=N,
        provenance=Provenance.OBSERVED,
        null_policy=NullPolicy.TREAT_AS_ABSENT,
        evidence_ids=(condition_a,),
    )

    eligible = AtomicPolicyClause(
        clause_id="clause_eligible",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="A loan may be purchased at a credit score of 620 or more and an LTV of at most 80 percent.",
        evidence={
            SemanticRole.CONDITION.value: (condition_a,),
            SemanticRole.EFFECT.value: (effect_a,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.DMN,
        condition_ast=All(
            (
                Comparison(VariableRef("credit_score"), GE, Literal(620, N)),
                Comparison(VariableRef("ltv_ratio"), LE, Literal(0.8, N)),
            )
        ),
        effect_ast=Literal("eligible", S),
        legacy_rule_ids=("BR_PURCHASE_ELIGIBILITY_1_001",),
    )
    not_eligible = AtomicPolicyClause(
        clause_id="clause_not_eligible",
        modality=Modality.PROHIBITION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.DENY,
        display_text="A loan may not be purchased at a credit score below 620.",
        evidence={
            SemanticRole.CONDITION.value: (condition_b,),
            SemanticRole.EFFECT.value: (effect_b,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), LT, Literal(620, N)),
        effect_ast=Literal("not_eligible", S),
        legacy_rule_ids=("BR_PURCHASE_ELIGIBILITY_1_002",),
    )
    decision = DecisionModelCandidate(
        decision_id="decision_purchase_eligibility",
        name="Purchase eligibility",
        question="May this loan be purchased?",
        output_definition=DecisionOutput(
            name="purchase eligibility",
            type=S,
            allowed_values=(Literal("eligible", S), Literal("not_eligible", S)),
        ),
        input_data_refs=("credit_score", "ltv_ratio"),
        decision_rule_refs=("clause_eligible", "clause_not_eligible"),
        authority_refs=(ids.ncname("authority_Section 4.2"),),
        proposed_hit_policy=HitPolicy.UNIQUE,
    )
    return {
        "data_definitions": (credit_score, ltv),
        "clauses": (eligible, not_eligible),
        "decisions": (decision,),
        "entity_types": (_lender(), _authority("Section 4.2")),
    }


def _eligibility_decision() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    parts = _eligibility_parts(handle)
    return Fixture(
        name="eligibility_decision",
        description=(
            "Two disjoint credit-score bands. UNIQUE is provable, both rows are "
            "evidenced, so the decision compiles to executable DMN."
        ),
        ir=builder.ir(**parts),
        texts=builder.texts(),
        expect_dmn=("Purchase eligibility",),
        forbid_codes=frozenset({codes.HIT_POLICY_NOT_PROVEN, codes.LITERAL_NOT_ATTESTED}),
    )


# ---------------------------------------------------------------------------
# Negative and boundary fixtures
# ---------------------------------------------------------------------------


def _overlapping_rows() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    parts = dict(_eligibility_parts(handle))
    clauses = list(parts["clauses"])  # type: ignore[arg-type]
    # Widen the deny row so both rows can match a 700 score: UNIQUE is now a lie.
    clauses[1] = AtomicPolicyClause(
        **{
            **{
                field_name: getattr(clauses[1], field_name)
                for field_name in (
                    "clause_id",
                    "modality",
                    "semantic_kind",
                    "effect",
                    "display_text",
                    "evidence",
                    "lifecycle",
                    "compilation_intent",
                    "effect_ast",
                    "legacy_rule_ids",
                )
            },
            "condition_ast": Comparison(VariableRef("credit_score"), GE, Literal(620, N)),
        }
    )
    parts["clauses"] = tuple(clauses)
    return Fixture(
        name="overlapping_rows",
        description=(
            "Both rows match a 700 score with different outputs. UNIQUE cannot be "
            "proven, and the compiler must refuse rather than relabel it FIRST."
        ),
        ir=builder.ir(**parts),
        texts=builder.texts(),
        expect_codes=frozenset({codes.HIT_POLICY_NOT_PROVEN}),
    )


def _exception_clause() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://restricted", RESTRICTED_TEXT, "Section 4.3")
    condition = handle.cite(
        "the borrower credit score is at least 620", SemanticRole.CONDITION
    )
    effect = handle.cite("A loan may be purchased", SemanticRole.EFFECT)
    exception = handle.cite(
        "the property is located in a restricted county", SemanticRole.EXCEPTION
    )
    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    county = DataDefinition(
        data_definition_id="county_status",
        name="property county status",
        type=S,
        null_policy=NullPolicy.TREAT_AS_ABSENT,
        allowed_values=(Literal("restricted", S), Literal("standard", S)),
        evidence_ids=(exception,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_eligible_unless_restricted",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="A loan may be purchased at 620 or above unless the county is restricted.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
            SemanticRole.EXCEPTION.value: (exception,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), GE, Literal(620, N)),
        effect_ast=Literal("eligible", S),
        exception_ast=Comparison(VariableRef("county_status"), EQ, Literal("restricted", S)),
    )
    decision = DecisionModelCandidate(
        decision_id="decision_restricted_eligibility",
        name="Restricted county eligibility",
        question="May this loan be purchased given the county restriction?",
        output_definition=DecisionOutput(name="purchase eligibility", type=S),
        input_data_refs=("credit_score", "county_status"),
        decision_rule_refs=("clause_eligible_unless_restricted",),
        proposed_hit_policy=HitPolicy.UNIQUE,
    )
    return Fixture(
        name="exception_clause",
        description=(
            "The 'unless' clause must survive into the row as a negated county test, "
            "not be dropped when the condition is flattened."
        ),
        ir=builder.ir(
            data_definitions=(credit_score, county),
            clauses=(clause,),
            decisions=(decision,),
            entity_types=(_lender(),),
        ),
        texts=builder.texts(),
        expect_dmn=("Restricted county eligibility",),
    )


def _fee_calculation() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://fee", FEE_TEXT, "Section 5.1")
    condition = handle.cite("the loan amount is greater than $500,000", SemanticRole.CONDITION)
    effect = handle.cite(
        "must pay an upfront fee of 0.25 percent of the guaranteed portion",
        SemanticRole.EFFECT,
    )
    amount = DataDefinition(
        data_definition_id="loan_amount",
        name="loan amount",
        type=N,
        unit="USD",
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_upfront_fee",
        modality=Modality.OBLIGATION,
        semantic_kind=SemanticKind.CALCULATION,
        effect=Effect.PRODUCE_VALUE,
        display_text="Loans above $500,000 carry a 0.25 percent upfront fee.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("loan_amount"), GT, Literal(500000, N, unit="USD")),
        effect_ast=Literal(0.25, N, unit="percent"),
    )
    decision = DecisionModelCandidate(
        decision_id="decision_upfront_fee",
        name="Upfront fee rate",
        question="What upfront fee rate applies?",
        output_definition=DecisionOutput(name="upfront fee rate", type=N, unit="percent"),
        input_data_refs=("loan_amount",),
        decision_rule_refs=("clause_upfront_fee",),
        proposed_hit_policy=HitPolicy.UNIQUE,
    )
    return Fixture(
        name="fee_calculation",
        description="A single-row calculation with a currency-tagged threshold.",
        ir=builder.ir(
            data_definitions=(amount,),
            clauses=(clause,),
            decisions=(decision,),
            entity_types=(_lender(),),
        ),
        texts=builder.texts(),
        expect_dmn=("Upfront fee rate",),
    )


def _unit_drift() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://fee", FEE_TEXT, "Section 5.1")
    condition = handle.cite("the loan amount is greater than $500,000", SemanticRole.CONDITION)
    effect = handle.cite(
        "must pay an upfront fee of 0.25 percent of the guaranteed portion",
        SemanticRole.EFFECT,
    )
    amount = DataDefinition(
        data_definition_id="loan_amount",
        name="loan amount",
        type=N,
        unit="USD",
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_fee_eur",
        modality=Modality.OBLIGATION,
        semantic_kind=SemanticKind.CALCULATION,
        effect=Effect.PRODUCE_VALUE,
        display_text="The threshold has drifted from dollars to euros.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
        },
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("loan_amount"), GT, Literal(500000, N, unit="EUR")),
        effect_ast=Literal(0.25, N, unit="percent"),
    )
    return Fixture(
        name="unit_drift",
        description=(
            "A USD amount compared against a EUR threshold with no declared "
            "conversion. The type checker must refuse it."
        ),
        ir=builder.ir(
            data_definitions=(amount,), clauses=(clause,), entity_types=(_lender(),)
        ),
        texts=builder.texts(),
        expect_codes=frozenset({codes.ILL_TYPED_EXPRESSION}),
    )


def _numeric_drift() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    condition = handle.cite(
        "the borrower credit score is at least 620 and the loan-to-value ratio does "
        "not exceed 80 percent",
        SemanticRole.CONDITION,
    )
    effect = handle.cite("a loan may be purchased", SemanticRole.EFFECT)
    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_drifted_threshold",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="The threshold has drifted from 620 to 640.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
        },
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), GE, Literal(640, N)),
        effect_ast=Literal("eligible", S),
    )
    decision = DecisionModelCandidate(
        decision_id="decision_drifted_eligibility",
        name="Drifted eligibility",
        question="May this loan be purchased?",
        output_definition=DecisionOutput(name="purchase eligibility", type=S),
        input_data_refs=("credit_score",),
        decision_rule_refs=("clause_drifted_threshold",),
        proposed_hit_policy=HitPolicy.UNIQUE,
    )
    return Fixture(
        name="numeric_drift",
        description=(
            "A 640 threshold cited to text that says 620. The value is unattested, "
            "which is reviewable but never executable."
        ),
        ir=builder.ir(
            data_definitions=(credit_score,),
            clauses=(clause,),
            decisions=(decision,),
            entity_types=(_lender(),),
        ),
        texts=builder.texts(),
        expect_codes=frozenset({codes.LITERAL_NOT_ATTESTED}),
    )


def _modal_flip() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://fee", FEE_TEXT, "Section 5.1")
    condition = handle.cite("the loan amount is greater than $500,000", SemanticRole.CONDITION)
    effect = handle.cite(
        "must pay an upfront fee of 0.25 percent of the guaranteed portion",
        SemanticRole.EFFECT,
    )
    amount = DataDefinition(
        data_definition_id="loan_amount",
        name="loan amount",
        type=N,
        unit="USD",
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_modal_flip",
        modality=Modality.PROHIBITION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.DENY,
        display_text="Declared as a prohibition over text that states an obligation.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
        },
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("loan_amount"), GT, Literal(500000, N, unit="USD")),
        effect_ast=Literal("denied", S),
    )
    return Fixture(
        name="modal_flip",
        description="'must pay' cannot support a prohibition.",
        ir=builder.ir(
            data_definitions=(amount,), clauses=(clause,), entity_types=(_lender(),)
        ),
        texts=builder.texts(),
        expect_codes=frozenset({codes.MODALITY_NOT_ATTESTED}),
    )


def _wrong_span() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    condition = handle.fabricate(
        "the borrower credit score is at least 700",
        "a borrower credit score below 620",
        SemanticRole.CONDITION,
    )
    effect = handle.cite("a loan may be purchased", SemanticRole.EFFECT)
    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
    )
    clause = AtomicPolicyClause(
        clause_id="clause_wrong_span",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="A plausible threshold citing a span that does not say it.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
        },
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), GE, Literal(700, N)),
        effect_ast=Literal("eligible", S),
    )
    return Fixture(
        name="wrong_span",
        description=(
            "The cited offsets hold different words than the citation claims, which "
            "the hash-and-offset check must catch."
        ),
        ir=builder.ir(
            data_definitions=(credit_score,), clauses=(clause,), entity_types=(_lender(),)
        ),
        texts=builder.texts(),
        expect_codes=frozenset({codes.EVIDENCE_TEXT_MISMATCH}),
    )


def _proposed_attribute() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    condition = handle.cite(
        "the borrower credit score is at least 620 and the loan-to-value ratio does "
        "not exceed 80 percent",
        SemanticRole.CONDITION,
    )
    effect = handle.cite("a loan may be purchased", SemanticRole.EFFECT)
    invented = DataDefinition(
        data_definition_id="account_type",
        name="account type",
        type=S,
        provenance=Provenance.PROPOSED,
        null_policy=NullPolicy.TREAT_AS_ABSENT,
    )
    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_uses_proposed_input",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="Uses an attribute the source never states.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
        },
        compilation_intent=CompilationIntent.DMN,
        condition_ast=All(
            (
                Comparison(VariableRef("credit_score"), GE, Literal(620, N)),
                Comparison(VariableRef("account_type"), EQ, Literal("retail", S)),
            )
        ),
        effect_ast=Literal("eligible", S),
    )
    return Fixture(
        name="proposed_attribute",
        description=(
            "A PROPOSED attribute may live in the graph but must never become a DMN "
            "input."
        ),
        ir=builder.ir(
            data_definitions=(credit_score, invented),
            clauses=(clause,),
            entity_types=(_lender(),),
        ),
        texts=builder.texts(),
        expect_codes=frozenset({codes.PROPOSED_ELEMENT_IN_EXECUTABLE}),
    )


def _broken_reference() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    condition = handle.cite(
        "the borrower credit score is at least 620 and the loan-to-value ratio does "
        "not exceed 80 percent",
        SemanticRole.CONDITION,
    )
    effect = handle.cite("a loan may be purchased", SemanticRole.EFFECT)
    reference = handle.cite("For purposes of this Section", SemanticRole.CROSS_REFERENCE)
    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
        evidence_ids=(condition,),
    )
    clause = AtomicPolicyClause(
        clause_id="clause_broken_reference",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="Cites a section that does not exist.",
        evidence={
            SemanticRole.CONDITION.value: (condition,),
            SemanticRole.EFFECT.value: (effect,),
            SemanticRole.CROSS_REFERENCE.value: (reference,),
        },
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), GE, Literal(620, N)),
        effect_ast=Literal("eligible", S),
        cross_reference_targets=("Section 99.9",),
    )
    return Fixture(
        name="broken_reference",
        description="An unresolvable cross reference must block the clause.",
        ir=builder.ir(
            data_definitions=(credit_score,), clauses=(clause,), entity_types=(_lender(),)
        ),
        texts=builder.texts(),
        expect_codes=frozenset({codes.UNRESOLVED_CROSS_REFERENCE}),
    )


def _retention_obligation() -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://retention", RETENTION_TEXT, "Section 9.4")
    effect = handle.cite(
        "must retain each loan file for 5 years after the loan is paid in full",
        SemanticRole.EFFECT,
    )
    temporal = handle.cite("for 5 years", SemanticRole.TEMPORAL)
    subject = handle.cite("The Lender", SemanticRole.SUBJECT)
    clause = AtomicPolicyClause(
        clause_id="clause_retention",
        modality=Modality.OBLIGATION,
        semantic_kind=SemanticKind.TEMPORAL_CONSTRAINT,
        effect=Effect.REQUIRE_ACTION,
        display_text="Loan files must be retained for five years after payoff.",
        evidence={
            SemanticRole.EFFECT.value: (effect,),
            SemanticRole.TEMPORAL.value: (temporal,),
            SemanticRole.SUBJECT.value: (subject,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.GRAPH_ONLY,
        subject_ref="entity_lender",
        action="retain loan file",
        temporal_constraint=TemporalConstraint(
            duration=Literal("P1825D", DataType.DURATION),
            calendar=Calendar.CALENDAR_DAYS,
            relative_to="loan paid in full",
            evidence_ids=(temporal,),
        ),
    )
    return Fixture(
        name="retention_obligation",
        description=(
            "A retention obligation with no workflow. It belongs in the graph, and "
            "must not become a start event, a task sequence or a five-year timer."
        ),
        ir=builder.ir(clauses=(clause,), entity_types=(_lender(),)),
        texts=builder.texts(),
        forbid_codes=frozenset({codes.LITERAL_NOT_ATTESTED, codes.MODALITY_NOT_ATTESTED}),
    )


def _notice_process(*, with_actor: bool = True) -> Fixture:
    builder = FixtureBuilder()
    eligibility = builder.document("fixture://eligibility", ELIGIBILITY_TEXT, "Section 4.2")
    parts = _eligibility_parts(eligibility)
    notice = builder.document("fixture://notice", NOTICE_TEXT, "Section 7.1")

    trigger_ev = notice.cite("After receiving a completed application", SemanticRole.CONDITION)
    evaluate_ev = notice.cite("must evaluate purchase eligibility", SemanticRole.EFFECT)
    send_ev = notice.cite(
        "must then send the adverse action notice to the borrower within 30 calendar days",
        SemanticRole.EFFECT,
    )
    order_ev = notice.cite(
        "evaluate purchase eligibility and must then send", SemanticRole.TEMPORAL
    )
    end_ev = notice.cite("The file is closed once the notice has been sent", SemanticRole.EFFECT)
    subject_ev = notice.cite("the Lender", SemanticRole.SUBJECT)

    clause = AtomicPolicyClause(
        clause_id="clause_notice_process",
        modality=Modality.OBLIGATION,
        semantic_kind=SemanticKind.PROCESS_FRAGMENT,
        effect=Effect.REQUIRE_ACTION,
        display_text=(
            "On a completed application the Lender evaluates eligibility and sends the "
            "adverse action notice within 30 days."
        ),
        evidence={
            SemanticRole.CONDITION.value: (trigger_ev,),
            SemanticRole.EFFECT.value: (evaluate_ev, send_ev),
            SemanticRole.SUBJECT.value: (subject_ev,),
            SemanticRole.TEMPORAL.value: (order_ev,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.BPMN,
        subject_ref="entity_lender",
        action="send adverse action notice",
        temporal_constraint=TemporalConstraint(
            duration=Literal("P30D", DataType.DURATION),
            calendar=Calendar.CALENDAR_DAYS,
            relative_to="completed application",
            evidence_ids=(send_ev,),
        ),
    )

    evaluate = ProcessActivity(
        activity_id="activity_evaluate_eligibility",
        name="Evaluate purchase eligibility",
        kind="business_rule_task",
        actor_ref="entity_lender",
        decision_ref="decision_purchase_eligibility",
        evidence_ids=(evaluate_ev,),
    )
    send = ProcessActivity(
        activity_id="activity_send_notice",
        name="Send adverse action notice",
        kind="task",
        actor_ref="entity_lender",
        evidence_ids=(send_ev,),
    )
    fragment = ProcessFragmentCandidate(
        fragment_id="fragment_adverse_action_notice",
        name="Adverse action notice",
        activities=(evaluate, send),
        trigger_event=TriggerEvent(
            event_id="event_application_received",
            name="Completed application received",
            kind="message",
            evidence_ids=(trigger_ev,),
        ),
        responsible_actor_ref="entity_lender" if with_actor else None,
        participant_refs=("entity_lender",) if with_actor else (),
        ordering=(("activity_evaluate_eligibility", "activity_send_notice"),),
        decision_ref="decision_purchase_eligibility",
        temporal_constraint=clause.temporal_constraint,
        end_state="Notice sent and file closed",
        clause_refs=("clause_notice_process",),
        evidence_ids=(end_ev,),
    )
    precedence = DependencyEdge(
        edge_id="dep_evaluate_before_send",
        source_id="activity_evaluate_eligibility",
        target_id="activity_send_notice",
        kind=DependencyKind.TEMPORAL_PRECEDENCE,
        derivation_method=DerivationMethod.EXPLICIT_TEMPORAL_LANGUAGE,
        direction_semantics="evaluate must complete before the notice is sent",
        evidence_ids=(order_ev,),
    )

    ir = builder.ir(
        data_definitions=parts["data_definitions"],
        clauses=(*parts["clauses"], clause),  # type: ignore[misc]
        decisions=parts["decisions"],
        processes=(fragment,),
        dependencies=(precedence,),
        entity_types=parts["entity_types"],
    )
    if with_actor:
        return Fixture(
            name="notice_process",
            description=(
                "Trigger, responsible actor, two ordered activities with a validated "
                "precedence edge, a business rule task bound to an admitted decision, "
                "and a known end state."
            ),
            ir=ir,
            texts=builder.texts(),
            expect_dmn=("Purchase eligibility",),
            expect_bpmn=("Adverse action notice",),
        )
    return Fixture(
        name="missing_actor_process",
        description=(
            "Everything the executable subset needs except a responsible actor, so "
            "BPMN must be blocked while the review profile can still show it."
        ),
        ir=ir,
        texts=builder.texts(),
        expect_dmn=("Purchase eligibility",),
        expect_codes=frozenset({codes.MISSING_RESPONSIBLE_ACTOR}),
    )


def _inferred_sequence() -> Fixture:
    """Two activities that share an entity but state no order."""
    fixture_with_actor = _notice_process(with_actor=True)
    ir = fixture_with_actor.ir
    weakened = DependencyEdge(
        edge_id="dep_evaluate_before_send",
        source_id="activity_evaluate_eligibility",
        target_id="activity_send_notice",
        kind=DependencyKind.TEMPORAL_PRECEDENCE,
        derivation_method=DerivationMethod.MODEL_ASSISTED_CANDIDATE,
        direction_semantics="the two rules mention the same borrower",
        evidence_ids=(),
    )
    return Fixture(
        name="inferred_sequence",
        description=(
            "The precedence edge is only a model guess with no evidence. A shared "
            "entity is not a sequence flow, so BPMN must be blocked."
        ),
        ir=PolicyIR(
            documents=ir.documents,
            chunks=ir.chunks,
            evidence_spans=ir.evidence_spans,
            entity_types=ir.entity_types,
            data_definitions=ir.data_definitions,
            clauses=ir.clauses,
            decisions=ir.decisions,
            processes=ir.processes,
            dependencies=(weakened,),
        ),
        texts=fixture_with_actor.texts,
        expect_dmn=("Purchase eligibility",),
        expect_codes=frozenset(
            {codes.ORDERING_NOT_VALIDATED, codes.UNVALIDATED_EXECUTABLE_DEPENDENCY}
        ),
    )


# ---------------------------------------------------------------------------
# Scope, authority precedence and supersession
# ---------------------------------------------------------------------------


JURISDICTION = ScopeDimensionDefinition(
    dimension_id="dim_jurisdiction",
    name="jurisdiction",
    description="US state or territory whose overlay applies.",
    allowed_values=("US-CA", "US-NY", "US-TX"),
)


def _state_overlay(*, with_conflict: bool = False) -> Fixture:
    """Two state overlays whose score bands overlap but whose scopes cannot."""
    builder = FixtureBuilder()
    handle = builder.document("fixture://overlays", SCOPED_TEXT, "Section 12.1")

    ca_effect = handle.cite("In California, a loan may be purchased", SemanticRole.EFFECT)
    ca_scope = handle.cite("In California", SemanticRole.SCOPE)
    ca_condition = handle.cite(
        "the borrower credit score is at least 660", SemanticRole.CONDITION
    )
    ny_effect = handle.cite("In New York, a loan may be purchased", SemanticRole.EFFECT)
    ny_scope = handle.cite("In New York", SemanticRole.SCOPE)
    ny_condition = handle.cite(
        "the borrower credit score is at least 640", SemanticRole.CONDITION
    )

    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
        evidence_ids=(ca_condition,),
    )

    def overlay(name: str, state: str, threshold: int, condition_ev: str, effect_ev: str,
                scope_ev: str) -> AtomicPolicyClause:
        return AtomicPolicyClause(
            clause_id=f"clause_overlay_{state.lower().replace('-', '_')}",
            modality=Modality.PERMISSION,
            semantic_kind=SemanticKind.DECISION_RULE,
            effect=Effect.ALLOW,
            display_text=f"In {name} a loan may be purchased at {threshold} or above.",
            evidence={
                SemanticRole.CONDITION.value: (condition_ev,),
                SemanticRole.EFFECT.value: (effect_ev,),
                SemanticRole.SCOPE.value: (scope_ev,),
            },
            lifecycle=Lifecycle.ACTIVE,
            compilation_intent=CompilationIntent.DMN,
            condition_ast=Comparison(VariableRef("credit_score"), GE, Literal(threshold, N)),
            effect_ast=Literal("eligible", S),
            scope=Scope((ScopeDimension("jurisdiction", (state,), evidence_ids=(scope_ev,)),)),
        )

    california = overlay("California", "US-CA", 660, ca_condition, ca_effect, ca_scope)
    new_york = overlay("New York", "US-NY", 640, ny_condition, ny_effect, ny_scope)
    decision = DecisionModelCandidate(
        decision_id="decision_state_overlay",
        name="State overlay eligibility",
        question="May this loan be purchased under the applicable state overlay?",
        output_definition=DecisionOutput(name="purchase eligibility", type=S),
        input_data_refs=("credit_score",),
        decision_rule_refs=(california.clause_id, new_york.clause_id),
        proposed_hit_policy=HitPolicy.UNIQUE,
    )
    dependencies = ()
    if with_conflict:
        dependencies = (
            DependencyEdge(
                edge_id="dep_overlay_conflict",
                source_id=california.clause_id,
                target_id=new_york.clause_id,
                kind=DependencyKind.CONFLICT,
                derivation_method=DerivationMethod.MODEL_ASSISTED_CANDIDATE,
                direction_semantics="the two overlays state different thresholds",
            ),
        )
    ir = builder.ir(
        scope_dimensions=(JURISDICTION,),
        data_definitions=(credit_score,),
        clauses=(california, new_york),
        decisions=(decision,),
        dependencies=dependencies,
        entity_types=(_lender(),),
    )
    if with_conflict:
        return Fixture(
            name="disjoint_scope_conflict",
            description=(
                "A conflict is declared between two overlays, but their scopes are "
                "provably disjoint, so there is no real contradiction and the decision "
                "still compiles."
            ),
            ir=ir,
            texts=builder.texts(),
            expect_dmn=("State overlay eligibility",),
            forbid_codes=frozenset({codes.UNRESOLVED_CONFLICT, codes.HIT_POLICY_NOT_PROVEN}),
        )
    return Fixture(
        name="state_overlay_scope",
        description=(
            "660 in California and 640 in New York. The bands overlap, so UNIQUE is only "
            "provable because the jurisdiction axis becomes an input column."
        ),
        ir=ir,
        texts=builder.texts(),
        expect_dmn=("State overlay eligibility",),
        forbid_codes=frozenset({codes.HIT_POLICY_NOT_PROVEN}),
    )


def _undeclared_scope_dimension() -> Fixture:
    base = _state_overlay()
    ir = base.ir
    stripped = type(ir)(
        **{**{f: getattr(ir, f) for f in ir.__dataclass_fields__}, "scope_dimensions": ()}
    )
    return Fixture(
        name="undeclared_scope_dimension",
        description=(
            "The clauses are scoped on 'jurisdiction' but the corpus declares no such "
            "axis, so the limit is unverifiable and the rows are refused."
        ),
        ir=stripped,
        texts=base.texts,
        expect_codes=frozenset({codes.UNKNOWN_SCOPE_DIMENSION}),
    )


def _authority_conflict(*, tie: bool = False) -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://authority", AUTHORITY_TEXT, "Section 3.1")

    guide_authority_ev = handle.cite("The Guide", SemanticRole.AUTHORITY)
    guide_condition = handle.cite(
        "if the borrower credit score is below 640", SemanticRole.CONDITION
    )
    guide_effect = handle.cite("a loan must not be purchased", SemanticRole.EFFECT)
    bulletin_authority_ev = handle.cite("Bulletin 2026-04", SemanticRole.AUTHORITY)
    bulletin_condition = handle.cite(
        "when the borrower credit score is below 640", SemanticRole.CONDITION
    )
    bulletin_effect = handle.cite("a loan may be purchased", SemanticRole.EFFECT)

    credit_score = DataDefinition(
        data_definition_id="credit_score",
        name="borrower credit score",
        type=N,
        null_policy=NullPolicy.REJECT,
        evidence_ids=(guide_condition,),
    )
    guide_clause = AtomicPolicyClause(
        clause_id="clause_guide_denies_below_640",
        modality=Modality.PROHIBITION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.DENY,
        display_text="The Guide denies purchase below 640.",
        evidence={
            SemanticRole.CONDITION.value: (guide_condition,),
            SemanticRole.EFFECT.value: (guide_effect,),
            SemanticRole.AUTHORITY.value: (guide_authority_ev,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), LT, Literal(640, N)),
        effect_ast=Literal("not_eligible", S),
        authority_ref="auth_guide",
    )
    bulletin_clause = AtomicPolicyClause(
        clause_id="clause_bulletin_allows_below_640",
        modality=Modality.PERMISSION,
        semantic_kind=SemanticKind.DECISION_RULE,
        effect=Effect.ALLOW,
        display_text="The bulletin allows purchase below 640.",
        evidence={
            SemanticRole.CONDITION.value: (bulletin_condition,),
            SemanticRole.EFFECT.value: (bulletin_effect,),
            SemanticRole.AUTHORITY.value: (bulletin_authority_ev,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.DMN,
        condition_ast=Comparison(VariableRef("credit_score"), LT, Literal(640, N)),
        effect_ast=Literal("eligible", S),
        authority_ref="auth_bulletin",
    )
    decision = DecisionModelCandidate(
        decision_id="decision_below_640",
        name="Below-640 eligibility",
        question="May a loan below 640 be purchased?",
        output_definition=DecisionOutput(name="purchase eligibility", type=S),
        input_data_refs=("credit_score",),
        decision_rule_refs=(guide_clause.clause_id, bulletin_clause.clause_id),
        proposed_hit_policy=HitPolicy.UNIQUE,
    )
    conflict = DependencyEdge(
        edge_id="dep_guide_bulletin_conflict",
        source_id=guide_clause.clause_id,
        target_id=bulletin_clause.clause_id,
        kind=DependencyKind.CONFLICT,
        derivation_method=DerivationMethod.EXPLICIT_CROSS_REFERENCE,
        direction_semantics="the two sources state opposite outcomes for the same band",
        evidence_ids=(guide_effect, bulletin_effect),
    )
    ir = builder.ir(
        authority_sources=(
            AuthoritySource("auth_guide", "Selling Guide", 50, kind="guide"),
            AuthoritySource(
                "auth_bulletin", "Bulletin 2026-04", 50 if tie else 10, kind="bulletin"
            ),
        ),
        data_definitions=(credit_score,),
        clauses=(guide_clause, bulletin_clause),
        decisions=(decision,),
        dependencies=(conflict,),
        entity_types=(_lender(),),
    )
    if tie:
        return Fixture(
            name="authority_tie_conflict",
            description=(
                "Both sources carry equal weight, so precedence cannot settle the "
                "contradiction and both rows are refused."
            ),
            ir=ir,
            texts=builder.texts(),
            expect_codes=frozenset({codes.AUTHORITY_TIE, codes.UNRESOLVED_CONFLICT}),
        )
    return Fixture(
        name="authority_resolved_conflict",
        description=(
            "The Guide outranks the bulletin, so the bulletin row is refused and the "
            "decision compiles from the winner. Resolving a conflict has to enable "
            "compilation, not merely describe the problem."
        ),
        ir=ir,
        texts=builder.texts(),
        expect_dmn=("Below-640 eligibility",),
        expect_codes=frozenset({codes.OUTRANKED_BY_AUTHORITY}),
        forbid_codes=frozenset({codes.UNRESOLVED_CONFLICT, codes.AUTHORITY_TIE}),
    )


def _supersession(*, recorded: bool = True) -> Fixture:
    builder = FixtureBuilder()
    handle = builder.document("fixture://supersession", SUPERSESSION_TEXT, "Section 8.2")

    old_effect = handle.cite(
        "a loan file must include 2 years of tax returns", SemanticRole.EFFECT
    )
    old_start = handle.cite("Effective 1 January 2025", SemanticRole.TEMPORAL)
    new_effect = handle.cite(
        "a loan file must include 1 year of tax returns", SemanticRole.EFFECT
    )
    new_start = handle.cite("Effective 1 January 2026", SemanticRole.TEMPORAL)

    old = AtomicPolicyClause(
        clause_id="clause_two_years_of_returns",
        modality=Modality.OBLIGATION,
        semantic_kind=SemanticKind.DOCUMENTATION_REQUIREMENT,
        effect=Effect.CREATE_RECORD,
        display_text="A loan file must include two years of tax returns.",
        evidence={
            SemanticRole.EFFECT.value: (old_effect,),
            SemanticRole.TEMPORAL.value: (old_start,),
        },
        lifecycle=Lifecycle.SUPERSEDED,
        compilation_intent=CompilationIntent.GRAPH_ONLY,
        effective_period=EffectivePeriod(start="2025-01-01"),
    )
    new = AtomicPolicyClause(
        clause_id="clause_one_year_of_returns",
        modality=Modality.OBLIGATION,
        semantic_kind=SemanticKind.DOCUMENTATION_REQUIREMENT,
        effect=Effect.CREATE_RECORD,
        display_text="A loan file must include one year of tax returns.",
        evidence={
            SemanticRole.EFFECT.value: (new_effect,),
            SemanticRole.TEMPORAL.value: (new_start,),
        },
        lifecycle=Lifecycle.ACTIVE,
        compilation_intent=CompilationIntent.GRAPH_ONLY,
        effective_period=EffectivePeriod(start="2026-01-01"),
    )
    edges = ()
    if recorded:
        edges = (
            DependencyEdge(
                edge_id="dep_one_year_supersedes_two",
                source_id=new.clause_id,
                target_id=old.clause_id,
                kind=DependencyKind.SUPERSEDES,
                derivation_method=DerivationMethod.EXPLICIT_CROSS_REFERENCE,
                direction_semantics="the 2026 standard replaces the 2025 standard",
                evidence_ids=(new_start,),
            ),
        )
    ir = builder.ir(clauses=(old, new), dependencies=edges, entity_types=(_lender(),))
    if recorded:
        return Fixture(
            name="superseded_documentation",
            description=(
                "The 2026 standard supersedes the 2025 one. Both stay in the graph, the "
                "superseded clause cannot compile, and 'what was in force' is answerable "
                "for any date."
            ),
            ir=ir,
            texts=builder.texts(),
            expect_codes=frozenset({codes.SUPERSEDED_CLAUSE}),
            forbid_codes=frozenset({codes.SUPERSESSION_NOT_RECORDED}),
        )
    return Fixture(
        name="supersession_not_recorded",
        description=(
            "A clause marked superseded with no edge to its replacement. The status is "
            "unusable for a historical query, so it is reported as a defect."
        ),
        ir=ir,
        texts=builder.texts(),
        expect_codes=frozenset({codes.SUPERSESSION_NOT_RECORDED, codes.SUPERSEDED_CLAUSE}),
    )


_FACTORIES: tuple[Callable[[], Fixture], ...] = (
    _state_overlay,
    lambda: _state_overlay(with_conflict=True),
    _undeclared_scope_dimension,
    _authority_conflict,
    lambda: _authority_conflict(tie=True),
    _supersession,
    lambda: _supersession(recorded=False),
    _eligibility_decision,
    _exception_clause,
    _fee_calculation,
    _retention_obligation,
    lambda: _notice_process(with_actor=True),
    lambda: _notice_process(with_actor=False),
    _overlapping_rows,
    _numeric_drift,
    _unit_drift,
    _modal_flip,
    _wrong_span,
    _proposed_attribute,
    _broken_reference,
    _inferred_sequence,
)


def all_fixtures() -> dict[str, Fixture]:
    """Build every fixture. Cheap enough to call per test."""
    built = [factory() for factory in _FACTORIES]
    return {item.name: item for item in built}


def fixture_names() -> tuple[str, ...]:
    return tuple(sorted(all_fixtures()))


def fixture(name: str) -> Fixture:
    try:
        return all_fixtures()[name]
    except KeyError as exc:
        raise KeyError(f"unknown fixture {name!r}; have {fixture_names()}") from exc
