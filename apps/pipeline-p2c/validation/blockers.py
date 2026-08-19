"""Blocker codes, kept in one place so reports and tests share a vocabulary.

Every refusal the gate can issue is named here. A machine-readable code plus a
human message is the plan's requirement for an abstention record: "a failure must
be a machine-readable abstain/reject record with a reason".
"""

from __future__ import annotations

from dataclasses import dataclass

# -- schema and structure ---------------------------------------------------
DUPLICATE_ID = "duplicate_id"
MISSING_REQUIRED_FIELD = "missing_required_field"
MISSING_FIELD_EVIDENCE = "missing_field_evidence"
UNKNOWN_EVIDENCE_ID = "unknown_evidence_id"
#: The record cites nothing at all. Not a schema error — a legacy import legitimately
#: has no spans — but it can never be provenance-exact, so nothing executable follows.
NO_EVIDENCE_CITED = "no_evidence_cited"

# -- provenance -------------------------------------------------------------
UNKNOWN_DOCUMENT = "unknown_document"
UNKNOWN_CHUNK = "unknown_chunk"
CHUNK_DOCUMENT_MISMATCH = "chunk_document_mismatch"
CHUNK_HASH_MISMATCH = "chunk_hash_mismatch"
OFFSET_OUTSIDE_CHUNK = "offset_outside_chunk"
OFFSET_OUTSIDE_DOCUMENT = "offset_outside_document"
EVIDENCE_TEXT_MISMATCH = "evidence_text_mismatch"
EVIDENCE_TEXT_UNAVAILABLE = "evidence_text_unavailable"
MATCH_STATUS_OVERSTATED = "match_status_overstated"
EVIDENCE_NOT_EXACT = "evidence_not_exact"

# -- semantics --------------------------------------------------------------
ILL_TYPED_EXPRESSION = "ill_typed_expression"
LITERAL_NOT_ATTESTED = "literal_not_attested"
MODALITY_NOT_ATTESTED = "modality_not_attested"
UNRESOLVED_CROSS_REFERENCE = "unresolved_cross_reference"
INVALID_EFFECTIVE_PERIOD = "invalid_effective_period"
UNRESOLVED_CONFLICT = "unresolved_conflict"

# -- DMN --------------------------------------------------------------------
CONDITION_NOT_TABULAR = "condition_not_tabular"
ROW_USES_UNDECLARED_INPUT = "row_uses_undeclared_input"
UNTYPED_INPUT = "untyped_input"
NULL_POLICY_UNDEFINED = "null_policy_undefined"
PROPOSED_ELEMENT_IN_EXECUTABLE = "proposed_element_in_executable"
HIT_POLICY_NOT_PROVEN = "hit_policy_not_proven"
ORDERING_NOT_EVIDENCED = "ordering_not_evidenced"
AGGREGATION_NOT_DECLARED = "aggregation_not_declared"
OUTPUT_TYPE_MISMATCH = "output_type_mismatch"
UNKNOWN_REQUIRED_DECISION = "unknown_required_decision"
DECISION_CYCLE = "decision_cycle"
NOT_FEEL_EXPRESSIBLE = "not_feel_expressible"
NO_DECISION_ROWS = "no_decision_rows"
ROW_NOT_ADMITTED = "row_not_admitted"

# -- BPMN -------------------------------------------------------------------
MISSING_TRIGGER = "missing_trigger"
MISSING_RESPONSIBLE_ACTOR = "missing_responsible_actor"
NO_ACTIVITY = "no_activity"
MISSING_ACTIVITY_EVIDENCE = "missing_activity_evidence"
BUSINESS_RULE_TASK_WITHOUT_DECISION = "business_rule_task_without_decision"
ORDERING_NOT_VALIDATED = "ordering_not_validated"
DANGLING_ORDERING = "dangling_ordering"
ORDERING_CYCLE = "ordering_cycle"
UNREACHABLE_ACTIVITY = "unreachable_activity"
MISSING_END_STATE = "missing_end_state"
BRANCHING_NOT_SUPPORTED = "branching_not_supported"

# -- dependencies -----------------------------------------------------------
UNVALIDATED_EXECUTABLE_DEPENDENCY = "unvalidated_executable_dependency"
UNKNOWN_DEPENDENCY_ENDPOINT = "unknown_dependency_endpoint"


@dataclass(frozen=True)
class Blocker:
    """One machine-readable reason an element was refused."""

    code: str
    element_id: str
    message: str
    role: str | None = None

    def to_dict(self) -> dict[str, str]:
        out = {"code": self.code, "element_id": self.element_id, "message": self.message}
        if self.role:
            out["role"] = self.role
        return out
