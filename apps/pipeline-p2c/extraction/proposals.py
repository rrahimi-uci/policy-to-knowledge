"""What an extractor returns, and how it becomes an evidenced clause.

A proposal cites :class:`~extraction.offer.TextUnit` **indices**, never span IDs or
offsets. The application resolves those indices against the request it issued and builds
the evidence spans itself, so an admitted clause's provenance is always something the
application computed rather than something a proposal asserted.

The conversion is where the offer becomes binding: an index outside the request is
refused, and there is no other way for a proposal to reach the document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ingestion.registry import SourceRegistry
from policy_ir._parsing import SchemaError, as_enum, as_int, as_str, as_tuple, check_keys
from policy_ir.enums import (
    CompilationIntent,
    Effect,
    Lifecycle,
    Modality,
    SemanticKind,
    SemanticRole,
)
from policy_ir.expressions import Expression, expression_from_dict
from policy_ir.models import AtomicPolicyClause, EffectivePeriod, EvidenceSpan, TemporalConstraint
from policy_ir.scope import Scope

from .candidates import CandidateClause, CandidateRejected, candidates_to_clauses
from .offer import ExtractionRequest


@dataclass(frozen=True)
class RoleCitation:
    """Which units support one part of a clause."""

    role: SemanticRole
    units: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "units", tuple(self.units))
        if not self.units:
            raise CandidateRejected(
                f"citation for role {self.role.value!r} names no unit; omit the role "
                "instead of citing nothing"
            )
        if len(set(self.units)) != len(self.units):
            raise CandidateRejected(
                f"citation for role {self.role.value!r} repeats a unit: {self.units}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role.value, "units": list(self.units)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RoleCitation":
        record = "RoleCitation"
        try:
            check_keys(data, record, ["role", "units"])
            units = data["units"]
            if not isinstance(units, (list, tuple)):
                raise SchemaError(f"{record}.units must be a list of integers")
            return cls(
                role=as_enum(SemanticRole, data["role"], record, "role"),
                units=tuple(as_int(u, record, "units") for u in units),
            )
        except SchemaError as exc:
            raise CandidateRejected(str(exc)) from exc


@dataclass(frozen=True)
class CandidateProposal:
    """One proposed clause, expressed only in terms of the offered units."""

    modality: Modality
    semantic_kind: SemanticKind
    effect: Effect
    display_unit: int
    citations: tuple[RoleCitation, ...]
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
    missing: tuple[str, ...] = ()

    def cited_units(self) -> tuple[int, ...]:
        seen: list[int] = []
        for citation in self.citations:
            for index in citation.units:
                if index not in seen:
                    seen.append(index)
        return tuple(sorted(seen))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "modality": self.modality.value,
            "semantic_kind": self.semantic_kind.value,
            "effect": self.effect.value,
            "display_unit": self.display_unit,
            "citations": [citation.to_dict() for citation in self.citations],
            "lifecycle": self.lifecycle.value,
            "compilation_intent": self.compilation_intent.value,
        }
        optional = {
            "subject_ref": self.subject_ref,
            "action": self.action,
            "object_ref": self.object_ref,
            "condition_ast": self.condition_ast.to_dict() if self.condition_ast else None,
            "effect_ast": self.effect_ast.to_dict() if self.effect_ast else None,
            "exception_ast": self.exception_ast.to_dict() if self.exception_ast else None,
            "temporal_constraint": (
                self.temporal_constraint.to_dict() if self.temporal_constraint else None
            ),
            "scope": self.scope.to_dict() if self.scope.dimensions else None,
            "effective_period": self.effective_period.to_dict() or None,
            "authority_ref": self.authority_ref,
            "cross_reference_targets": list(self.cross_reference_targets) or None,
            "missing": list(self.missing) or None,
        }
        out.update({key: value for key, value in optional.items() if value is not None})
        return out


_REQUIRED = ("modality", "semantic_kind", "effect", "display_unit", "citations")
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
    "missing",
)


def normalise_citations(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept role-keyed citations as well as the record list form.

    The wire contract keys citations by role, because given a list of ``{role, units}``
    the model twice named the same role in one proposal — ambiguous evidence for a field,
    refused by the parser, and a paid call wasted each time. Keyed by role the duplicate
    is not a representable document.

    The IR keeps the list form, since a citation is a record with its own identity. This
    is the single place the two shapes meet, so no caller has to remember which it holds,
    and replies captured before the contract changed still parse.
    """
    citations = data.get("citations")
    if not isinstance(citations, Mapping):
        return data

    def unique(units: Any) -> Any:
        """Collapse a repeated unit index, keeping first-seen order.

        Strict mode drops ``uniqueItems``, so the schema cannot forbid a repeat and the
        model duly sent unit 1 thirty-two times for one role. Unlike a duplicate *role*,
        a repeated *unit* carries no information — a role's citation is the set of units
        that support it — so collapsing it is lossless, where merging two roles' unit
        lists would be a guess.
        """
        if not isinstance(units, list):
            return units
        seen: list[Any] = []
        for unit in units:
            if unit not in seen:
                seen.append(unit)
        return seen

    return {
        **data,
        "citations": [
            {"role": role, "units": unique(units)}
            for role, units in citations.items()
            if units
        ],
    }


def proposal_from_dict(data: Mapping[str, Any]) -> CandidateProposal:
    """Parse one proposal, refusing anything outside the contract."""
    record = "CandidateProposal"
    data = normalise_citations(data)
    try:
        check_keys(data, record, list(_REQUIRED), list(_OPTIONAL))

        def expression(key: str) -> Expression | None:
            value = data.get(key)
            return None if value is None else expression_from_dict(value)

        citations = as_tuple(data["citations"], record, "citations", RoleCitation.from_dict)
        if not citations:
            raise SchemaError(
                f"{record}.citations is empty; an uncited proposal cannot be verified"
            )
        roles = [citation.role for citation in citations]
        if len(set(roles)) != len(roles):
            raise SchemaError(
                f"{record}.citations names a role more than once; combine the units into "
                "one citation so the evidence for a field is unambiguous"
            )
        return CandidateProposal(
            modality=as_enum(Modality, data["modality"], record, "modality"),
            semantic_kind=as_enum(
                SemanticKind, data["semantic_kind"], record, "semantic_kind"
            ),
            effect=as_enum(Effect, data["effect"], record, "effect"),
            display_unit=as_int(data["display_unit"], record, "display_unit"),
            citations=citations,
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
            cross_reference_targets=tuple(
                as_str(t, record, "cross_reference_targets")
                for t in data.get("cross_reference_targets", ())
            ),
            missing=tuple(as_str(m, record, "missing") for m in data.get("missing", ())),
        )
    except CandidateRejected:
        raise
    except (SchemaError, ValueError) as exc:
        raise CandidateRejected(str(exc)) from exc


def resolve_proposal(
    proposal: CandidateProposal,
    request: ExtractionRequest,
    registry: SourceRegistry,
) -> tuple[CandidateClause, tuple[EvidenceSpan, ...]]:
    """Turn a proposal into a candidate, building its spans from the offered units.

    This is where the offer binds. Every index must be one the request issued; there is
    no other route from a proposal to the document, so a citation to unseen text is not
    merely refused but unexpressible.
    """
    offered = {unit.index for unit in request.units}
    cited = set(proposal.cited_units()) | {proposal.display_unit}
    unknown = sorted(cited - offered)
    if unknown:
        raise CandidateRejected(
            f"proposal cites unit(s) {unknown}, which this request did not offer "
            f"(it offered {sorted(offered)})"
        )

    spans: dict[str, EvidenceSpan] = {}
    evidence: dict[str, tuple[str, ...]] = {}
    for citation in proposal.citations:
        ids: list[str] = []
        for index in citation.units:
            unit = request.unit(index)
            span = registry.span_at(
                request.chunk_id, unit.char_start, unit.char_end, citation.role
            )
            spans[span.evidence_id] = span
            ids.append(span.evidence_id)
        evidence[citation.role.value] = tuple(ids)

    candidate = CandidateClause(
        modality=proposal.modality,
        semantic_kind=proposal.semantic_kind,
        effect=proposal.effect,
        display_text=request.unit(proposal.display_unit).text,
        evidence=evidence,
        subject_ref=proposal.subject_ref,
        action=proposal.action,
        object_ref=proposal.object_ref,
        condition_ast=proposal.condition_ast,
        effect_ast=proposal.effect_ast,
        exception_ast=proposal.exception_ast,
        temporal_constraint=proposal.temporal_constraint,
        scope=proposal.scope,
        effective_period=proposal.effective_period,
        lifecycle=proposal.lifecycle,
        compilation_intent=proposal.compilation_intent,
        authority_ref=proposal.authority_ref,
        cross_reference_targets=proposal.cross_reference_targets,
        source_group_id=request.chunk_id,
        missing=proposal.missing,
    )
    candidate.check_internal_consistency()
    return candidate, tuple(spans.values())


def admit_proposals(
    proposals: Iterable[CandidateProposal],
    request: ExtractionRequest,
    registry: SourceRegistry,
    *,
    document_sha256: str,
) -> tuple[tuple[AtomicPolicyClause, ...], tuple[EvidenceSpan, ...]]:
    """Resolve and admit a batch of proposals for one request."""
    candidates: list[CandidateClause] = []
    spans: dict[str, EvidenceSpan] = {}
    for proposal in proposals:
        candidate, built = resolve_proposal(proposal, request, registry)
        candidates.append(candidate)
        spans.update({span.evidence_id: span for span in built})
    clauses = candidates_to_clauses(
        candidates,
        offered_span_ids=list(spans),
        document_sha256=document_sha256,
    )
    return clauses, tuple(spans[key] for key in sorted(spans))
