"""Conservative classification report for potential DMN and BPMN assembly.

The report is deliberately not an auto-compiler.  It tells a reviewer or a provider
which already-evidenced clauses could participate in a decision or process and which
required semantics are still absent.  Constructing a DecisionModelCandidate or
ProcessFragmentCandidate remains an explicit proposal, then passes the evidence gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from policy_ir.enums import CompilationIntent, SemanticKind
from policy_ir.models import AtomicPolicyClause, PolicyIR


@dataclass(frozen=True)
class SynthesisOpportunity:
    clause_id: str
    target: str
    status: str
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "clause_id": self.clause_id,
            "target": self.target,
            "status": self.status,
            "missing": list(self.missing),
        }


def _decision_missing(clause: AtomicPolicyClause) -> tuple[str, ...]:
    missing = []
    if clause.condition_ast is None:
        missing.append("condition_ast")
    if clause.effect_ast is None:
        missing.append("effect_ast")
    if not clause.evidence_for("condition"):
        missing.append("condition_evidence")
    if not clause.evidence_for("effect"):
        missing.append("effect_evidence")
    return tuple(missing)


def _process_missing(clause: AtomicPolicyClause) -> tuple[str, ...]:
    missing = []
    if not clause.subject_ref:
        missing.append("responsible_actor")
    if not clause.action:
        missing.append("activity_action")
    if not clause.evidence_for("effect"):
        missing.append("activity_evidence")
    return tuple(missing)


def synthesis_report(ir: PolicyIR) -> tuple[SynthesisOpportunity, ...]:
    """Classify declared intent without turning a clause into a workflow by default."""
    out: list[SynthesisOpportunity] = []
    for clause in sorted(ir.clauses, key=lambda item: item.clause_id):
        if clause.compilation_intent in (CompilationIntent.DMN, CompilationIntent.BOTH):
            allowed_kind = clause.semantic_kind in {
                SemanticKind.DECISION_RULE, SemanticKind.CALCULATION, SemanticKind.VALIDATION,
            }
            missing = ("decision_semantic_kind",) if not allowed_kind else _decision_missing(clause)
            out.append(
                SynthesisOpportunity(
                    clause.clause_id, "dmn", "ready_for_explicit_model" if not missing else "abstain", missing
                )
            )
        if clause.compilation_intent in (CompilationIntent.BPMN, CompilationIntent.BOTH):
            allowed_kind = clause.semantic_kind is SemanticKind.PROCESS_FRAGMENT
            missing = ("process_semantic_kind",) if not allowed_kind else _process_missing(clause)
            out.append(
                SynthesisOpportunity(
                    clause.clause_id, "bpmn", "ready_for_explicit_model" if not missing else "abstain", missing
                )
            )
    return tuple(out)
