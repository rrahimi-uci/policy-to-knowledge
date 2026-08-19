"""The extraction contract, and the strict parser that admits its output.

An extractor — model-driven or not — proposes :class:`CandidateClause` records. The
contract is built around three controls, because each closes a way an extractor could
put unsupported content into the IR:

1. **Citations are restricted to spans the application offered.** Every evidence ID
   must appear in the offered set. This is what stops a proposal citing text it was
   never shown, which the plan requires of the dependency prompt too.
2. **Identity is derived, never proposed.** A candidate has no ID field. The clause ID
   comes from the document hash, the cited spans and the clause kind, so the same
   evidence always yields the same clause and reordering a batch cannot change
   identity.
3. **A field cannot be both asserted and declared absent.** ``missing`` names the
   semantics an extractor did not produce in typed form; supplying one of those fields
   anyway is a contradiction and the candidate is refused. Without this, ``missing``
   would be decorative. Note that declaring ``condition`` absent while citing a
   *condition span* is consistent: it says "there is condition text here and I did not
   type it", which is exactly what an untyped extractor should say.

Unknown keys and unknown enum values are refused rather than ignored, exactly as in
:mod:`policy_ir.models` — silently dropping a field an extractor invented would hide
the drift the gate exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from policy_ir._parsing import (
    SchemaError,
    as_enum,
    as_str,
    as_tuple_of_str,
    check_keys,
    drop_none,
)
from policy_ir.enums import (
    CompilationIntent,
    Effect,
    Lifecycle,
    Modality,
    SemanticKind,
    SemanticRole,
)
from policy_ir.expressions import Expression, expression_from_dict
from policy_ir.ids import clause_id as derive_clause_id
from policy_ir.models import AtomicPolicyClause, EffectivePeriod, TemporalConstraint
from policy_ir.scope import Scope


class CandidateRejected(ValueError):
    """Raised when a proposed candidate violates the extraction contract."""


#: Semantic fields an extractor may declare it did not produce — either because the
#: text does not state them or because the extractor cannot type them. Both cases mean
#: the same thing downstream: nothing may assume them. Naming them explicitly means a
#: contradiction can be detected rather than merely hoped against.
DECLARABLE_MISSING = frozenset(
    {
        "condition",
        "effect",
        "exception",
        "subject",
        "action",
        "object",
        "temporal",
        "authority",
        "scope",
    }
)

#: Which candidate field each ``missing`` name forbids.
_MISSING_CONFLICTS: Mapping[str, tuple[str, ...]] = {
    "condition": ("condition_ast",),
    "effect": ("effect_ast",),
    "exception": ("exception_ast",),
    "subject": ("subject_ref",),
    "action": ("action",),
    "object": ("object_ref",),
    "temporal": ("temporal_constraint",),
    "authority": ("authority_ref",),
}


@dataclass(frozen=True)
class CandidateClause:
    """One proposed clause. Deliberately has no ID: identity is derived from content."""

    modality: Modality
    semantic_kind: SemanticKind
    effect: Effect
    display_text: str
    evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    subject_ref: str | None = None
    action: str | None = None
    object_ref: str | None = None
    condition_ast: Expression | None = None
    effect_ast: Expression | None = None
    exception_ast: Expression | None = None
    temporal_constraint: TemporalConstraint | None = None
    scope: Scope = field(default_factory=Scope)
    effective_period: EffectivePeriod = field(default_factory=EffectivePeriod)
    lifecycle: Lifecycle = Lifecycle.UNKNOWN
    compilation_intent: CompilationIntent = CompilationIntent.UNRESOLVED
    authority_ref: str | None = None
    cross_reference_targets: tuple[str, ...] = ()
    source_group_id: str | None = None
    missing: tuple[str, ...] = ()

    def cited_evidence_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for role in sorted(self.evidence):
            for value in self.evidence[role]:
                if value not in seen:
                    seen.append(value)
        return tuple(seen)

    def check_internal_consistency(self) -> None:
        """Refuse a candidate that both asserts and disclaims the same semantics."""
        unknown = sorted(set(self.missing) - DECLARABLE_MISSING)
        if unknown:
            raise CandidateRejected(
                f"missing names {unknown}, which are not declarable; choose from "
                f"{sorted(DECLARABLE_MISSING)}"
            )
        for name in self.missing:
            for attribute in _MISSING_CONFLICTS.get(name, ()):
                if getattr(self, attribute) is not None:
                    raise CandidateRejected(
                        f"{name!r} is declared unstated but {attribute} is supplied; a "
                        "field cannot be both asserted and disclaimed"
                    )
            if name == "scope" and self.scope.dimensions:
                raise CandidateRejected(
                    "'scope' is declared unstated but scope dimensions are supplied"
                )
        if not self.display_text.strip():
            raise CandidateRejected("display_text is empty")
        if not self.evidence:
            raise CandidateRejected(
                "a candidate must cite at least one span; an uncited proposal cannot be "
                "verified and would enter the graph unsupported"
            )


_REQUIRED = ("modality", "semantic_kind", "effect", "display_text", "evidence")
_OPTIONAL = (
    "subject_ref",
    "action",
    "object_ref",
    "condition_ast",
    "effect_ast",
    "exception_ast",
    "temporal_constraint",
    "scope",
    "effective_period",
    "lifecycle",
    "compilation_intent",
    "authority_ref",
    "cross_reference_targets",
    "source_group_id",
    "missing",
)


def candidate_from_dict(data: Mapping[str, Any]) -> CandidateClause:
    """Parse one proposed candidate, refusing anything outside the contract."""
    record = "CandidateClause"
    try:
        check_keys(data, record, list(_REQUIRED), list(_OPTIONAL))
    except SchemaError as exc:
        raise CandidateRejected(str(exc)) from exc
    if "clause_id" in data or "candidate_id" in data:  # pragma: no cover - guarded above
        raise CandidateRejected("a candidate may not choose its own identifier")

    raw_evidence = data["evidence"]
    if not isinstance(raw_evidence, Mapping):
        raise CandidateRejected(f"{record}.evidence must be an object keyed by role")
    evidence: dict[str, tuple[str, ...]] = {}
    try:
        for role, ids in raw_evidence.items():
            as_enum(SemanticRole, role, record, "evidence")
            evidence[role] = as_tuple_of_str(ids, record, f"evidence.{role}")

        def expression(key: str) -> Expression | None:
            value = data.get(key)
            return None if value is None else expression_from_dict(value)

        candidate = CandidateClause(
            modality=as_enum(Modality, data["modality"], record, "modality"),
            semantic_kind=as_enum(
                SemanticKind, data["semantic_kind"], record, "semantic_kind"
            ),
            effect=as_enum(Effect, data["effect"], record, "effect"),
            display_text=as_str(data["display_text"], record, "display_text"),
            evidence=evidence,
            subject_ref=data.get("subject_ref"),
            action=data.get("action"),
            object_ref=data.get("object_ref"),
            condition_ast=expression("condition_ast"),
            effect_ast=expression("effect_ast"),
            exception_ast=expression("exception_ast"),
            temporal_constraint=(
                TemporalConstraint.from_dict(data["temporal_constraint"])
                if data.get("temporal_constraint")
                else None
            ),
            scope=Scope.from_dict(data.get("scope", {})),
            effective_period=EffectivePeriod.from_dict(data.get("effective_period", {})),
            lifecycle=as_enum(
                Lifecycle, data.get("lifecycle", Lifecycle.UNKNOWN.value), record, "lifecycle"
            ),
            compilation_intent=as_enum(
                CompilationIntent,
                data.get("compilation_intent", CompilationIntent.UNRESOLVED.value),
                record,
                "compilation_intent",
            ),
            authority_ref=data.get("authority_ref"),
            cross_reference_targets=as_tuple_of_str(
                data.get("cross_reference_targets", ()), record, "cross_reference_targets"
            ),
            source_group_id=data.get("source_group_id"),
            missing=as_tuple_of_str(data.get("missing", ()), record, "missing"),
        )
    except (SchemaError, ValueError) as exc:
        if isinstance(exc, CandidateRejected):
            raise
        raise CandidateRejected(str(exc)) from exc
    candidate.check_internal_consistency()
    return candidate


def _clause_kind(candidate: CandidateClause) -> str:
    """The normalised kind mixed into the derived clause ID."""
    return f"{candidate.modality.value}:{candidate.semantic_kind.value}:{candidate.effect.value}"


def candidates_to_clauses(
    candidates: Iterable[CandidateClause],
    *,
    offered_span_ids: Iterable[str],
    document_sha256: str,
) -> tuple[AtomicPolicyClause, ...]:
    """Admit candidates as clauses, deriving identity and enforcing the span offer.

    Two candidates that cite the same spans with the same kind derive the same ID and
    are therefore the same clause; the first is kept. That is deduplication by
    construction rather than by a similarity threshold.
    """
    offered = frozenset(offered_span_ids)
    clauses: dict[str, AtomicPolicyClause] = {}
    for candidate in candidates:
        candidate.check_internal_consistency()
        cited = candidate.cited_evidence_ids()
        unknown = sorted(set(cited) - offered)
        if unknown:
            raise CandidateRejected(
                f"candidate cites span(s) {unknown} that were not offered to the "
                "extractor; a citation to unseen text cannot be verified"
            )
        clause_id = derive_clause_id(
            document_sha256, "|".join(sorted(cited)), _clause_kind(candidate)
        )
        if clause_id in clauses:
            continue
        clauses[clause_id] = AtomicPolicyClause(
            clause_id=clause_id,
            modality=candidate.modality,
            semantic_kind=candidate.semantic_kind,
            effect=candidate.effect,
            display_text=candidate.display_text,
            evidence={role: tuple(ids) for role, ids in candidate.evidence.items()},
            source_group_id=candidate.source_group_id,
            lifecycle=candidate.lifecycle,
            compilation_intent=candidate.compilation_intent,
            subject_ref=candidate.subject_ref,
            action=candidate.action,
            object_ref=candidate.object_ref,
            condition_ast=candidate.condition_ast,
            effect_ast=candidate.effect_ast,
            exception_ast=candidate.exception_ast,
            temporal_constraint=candidate.temporal_constraint,
            scope=candidate.scope,
            effective_period=candidate.effective_period,
            authority_ref=candidate.authority_ref,
            cross_reference_targets=candidate.cross_reference_targets,
        )
    return tuple(clauses[key] for key in sorted(clauses))


def candidate_to_dict(candidate: CandidateClause) -> dict[str, Any]:
    """Serialise a candidate, for round-trip tests and for logging a proposal."""
    return drop_none(
        {
            "modality": candidate.modality.value,
            "semantic_kind": candidate.semantic_kind.value,
            "effect": candidate.effect.value,
            "display_text": candidate.display_text,
            "evidence": {k: list(v) for k, v in sorted(candidate.evidence.items())},
            "subject_ref": candidate.subject_ref,
            "action": candidate.action,
            "object_ref": candidate.object_ref,
            "condition_ast": (
                candidate.condition_ast.to_dict() if candidate.condition_ast else None
            ),
            "effect_ast": candidate.effect_ast.to_dict() if candidate.effect_ast else None,
            "exception_ast": (
                candidate.exception_ast.to_dict() if candidate.exception_ast else None
            ),
            "temporal_constraint": (
                candidate.temporal_constraint.to_dict()
                if candidate.temporal_constraint
                else None
            ),
            "scope": candidate.scope.to_dict() if candidate.scope.dimensions else None,
            "effective_period": candidate.effective_period.to_dict() or None,
            "lifecycle": candidate.lifecycle.value,
            "compilation_intent": candidate.compilation_intent.value,
            "authority_ref": candidate.authority_ref,
            "cross_reference_targets": list(candidate.cross_reference_targets) or None,
            "source_group_id": candidate.source_group_id,
            "missing": list(candidate.missing) or None,
        }
    )
