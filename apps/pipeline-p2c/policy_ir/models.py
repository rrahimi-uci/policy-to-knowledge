"""Policy IR v2 records.

Policy IR is the canonical artefact: the legacy knowledge graph, DMN and BPMN
are all deterministic projections of it. The records here therefore carry no
admission verdicts of their own — an author (or an extraction agent) states what
it believes and where the evidence is, and :mod:`validation.evidence_gate`
decides separately what may be compiled. Keeping the verdict out of the record
is what makes "fail closed" enforceable: nothing can mark itself eligible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ._parsing import (
    SchemaError,
    as_enum,
    as_int,
    as_str,
    as_tuple,
    as_tuple_of_str,
    check_keys,
    drop_none,
)
from .enums import (
    CompilationIntent,
    DataType,
    DependencyKind,
    DerivationMethod,
    Effect,
    EntityCategory,
    HitPolicy,
    Lifecycle,
    MatchStatus,
    Modality,
    NullPolicy,
    Provenance,
    SemanticKind,
    SemanticRole,
    Aggregation,
)
from .expressions import Calendar, Expression, Literal, expression_from_dict
from .ids import SCHEMA_VERSION
from .scope import (  # noqa: F401  (re-exported: these are Policy IR records)
    AuthoritySource,
    Scope,
    ScopeDimension,
    ScopeDimensionDefinition,
)


def _expr(value: Any, record: str, key: str) -> Expression:
    try:
        return expression_from_dict(value)
    except ValueError as exc:
        raise SchemaError(f"{record}.{key}: {exc}") from exc


def _opt_expr(value: Any, record: str, key: str) -> Expression | None:
    return None if value is None else _expr(value, record, key)


# ---------------------------------------------------------------------------
# Sources and evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentArtifact:
    """An immutable source document, identified by content rather than filename."""

    document_id: str
    source_uri: str
    source_sha256: str
    canonical_text_sha256: str
    media_type: str
    retrieval_timestamp: str
    parser_version: str
    license_record_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "document_id": self.document_id,
                "source_uri": self.source_uri,
                "source_sha256": self.source_sha256,
                "canonical_text_sha256": self.canonical_text_sha256,
                "media_type": self.media_type,
                "retrieval_timestamp": self.retrieval_timestamp,
                "parser_version": self.parser_version,
                "license_record_id": self.license_record_id,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DocumentArtifact":
        r = "DocumentArtifact"
        check_keys(
            data,
            r,
            [
                "document_id",
                "source_uri",
                "source_sha256",
                "canonical_text_sha256",
                "media_type",
                "retrieval_timestamp",
                "parser_version",
            ],
            ["license_record_id"],
        )
        return cls(
            document_id=as_str(data["document_id"], r, "document_id"),
            source_uri=as_str(data["source_uri"], r, "source_uri"),
            source_sha256=as_str(data["source_sha256"], r, "source_sha256"),
            canonical_text_sha256=as_str(
                data["canonical_text_sha256"], r, "canonical_text_sha256"
            ),
            media_type=as_str(data["media_type"], r, "media_type"),
            retrieval_timestamp=as_str(data["retrieval_timestamp"], r, "retrieval_timestamp"),
            parser_version=as_str(data["parser_version"], r, "parser_version"),
            license_record_id=data.get("license_record_id"),
        )


@dataclass(frozen=True)
class Chunk:
    """A transport-sized slice of a document, mapped back to canonical offsets.

    Chunking is transport, never provenance: the character offsets are into the
    document's canonical text, so overlapping chunks cannot shift a span.
    """

    chunk_id: str
    document_id: str
    chunk_sha256: str
    char_start: int
    char_end: int
    section_path: str = ""
    page_start: int | None = None
    page_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "chunk_id": self.chunk_id,
                "document_id": self.document_id,
                "chunk_sha256": self.chunk_sha256,
                "char_start": self.char_start,
                "char_end": self.char_end,
                "section_path": self.section_path,
                "page_start": self.page_start,
                "page_end": self.page_end,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Chunk":
        r = "Chunk"
        check_keys(
            data,
            r,
            ["chunk_id", "document_id", "chunk_sha256", "char_start", "char_end"],
            ["section_path", "page_start", "page_end"],
        )
        return cls(
            chunk_id=as_str(data["chunk_id"], r, "chunk_id"),
            document_id=as_str(data["document_id"], r, "document_id"),
            chunk_sha256=as_str(data["chunk_sha256"], r, "chunk_sha256"),
            char_start=as_int(data["char_start"], r, "char_start"),
            char_end=as_int(data["char_end"], r, "char_end"),
            section_path=data.get("section_path", ""),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
        )


@dataclass(frozen=True)
class EvidenceSpan:
    """An exact character range in a hashed document, plus the role it plays."""

    evidence_id: str
    document_id: str
    chunk_id: str
    chunk_sha256: str
    char_start: int
    char_end: int
    exact_text: str
    semantic_role: SemanticRole
    match_status: MatchStatus = MatchStatus.EXACT
    section_path: str = ""
    page_start: int | None = None
    page_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "evidence_id": self.evidence_id,
                "document_id": self.document_id,
                "chunk_id": self.chunk_id,
                "chunk_sha256": self.chunk_sha256,
                "char_start": self.char_start,
                "char_end": self.char_end,
                "exact_text": self.exact_text,
                "semantic_role": self.semantic_role.value,
                "match_status": self.match_status.value,
                "section_path": self.section_path,
                "page_start": self.page_start,
                "page_end": self.page_end,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceSpan":
        r = "EvidenceSpan"
        check_keys(
            data,
            r,
            [
                "evidence_id",
                "document_id",
                "chunk_id",
                "chunk_sha256",
                "char_start",
                "char_end",
                "exact_text",
                "semantic_role",
            ],
            ["match_status", "section_path", "page_start", "page_end"],
        )
        return cls(
            evidence_id=as_str(data["evidence_id"], r, "evidence_id"),
            document_id=as_str(data["document_id"], r, "document_id"),
            chunk_id=as_str(data["chunk_id"], r, "chunk_id"),
            chunk_sha256=as_str(data["chunk_sha256"], r, "chunk_sha256"),
            char_start=as_int(data["char_start"], r, "char_start"),
            char_end=as_int(data["char_end"], r, "char_end"),
            exact_text=as_str(data["exact_text"], r, "exact_text"),
            semantic_role=as_enum(SemanticRole, data["semantic_role"], r, "semantic_role"),
            match_status=as_enum(
                MatchStatus, data.get("match_status", MatchStatus.EXACT.value), r, "match_status"
            ),
            section_path=data.get("section_path", ""),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
        )


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataDefinition:
    """A typed attribute: the unit of everything the compilers can reason about.

    The legacy graph stores ``data_points_required`` as bare names. A name is not
    enough to emit a DMN ``itemDefinition``, so every executable variable needs a
    FEEL type, and an explicit null policy before it can be compiled.
    """

    data_definition_id: str
    name: str
    type: DataType
    provenance: Provenance = Provenance.OBSERVED
    unit: str | None = None
    allowed_values: tuple[Literal, ...] = ()
    minimum: Literal | None = None
    maximum: Literal | None = None
    null_policy: NullPolicy = NullPolicy.UNDEFINED
    default_value: Literal | None = None
    derivation_function_id: str | None = None
    owning_entity_id: str | None = None
    aliases: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "data_definition_id": self.data_definition_id,
                "name": self.name,
                "type": self.type.value,
                "provenance": self.provenance.value,
                "unit": self.unit,
                "allowed_values": [v.to_dict() for v in self.allowed_values] or None,
                "minimum": self.minimum.to_dict() if self.minimum else None,
                "maximum": self.maximum.to_dict() if self.maximum else None,
                "null_policy": self.null_policy.value,
                "default_value": self.default_value.to_dict() if self.default_value else None,
                "derivation_function_id": self.derivation_function_id,
                "owning_entity_id": self.owning_entity_id,
                "aliases": list(self.aliases) or None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataDefinition":
        r = "DataDefinition"
        check_keys(
            data,
            r,
            ["data_definition_id", "name", "type"],
            [
                "provenance",
                "unit",
                "allowed_values",
                "minimum",
                "maximum",
                "null_policy",
                "default_value",
                "derivation_function_id",
                "owning_entity_id",
                "aliases",
                "evidence_ids",
            ],
        )
        allowed = tuple(
            _expr(v, r, "allowed_values") for v in data.get("allowed_values", ())
        )
        for value in allowed:
            if not isinstance(value, Literal):
                raise SchemaError(f"{r}.allowed_values entries must be literals")
        minimum = _opt_expr(data.get("minimum"), r, "minimum")
        maximum = _opt_expr(data.get("maximum"), r, "maximum")
        default = _opt_expr(data.get("default_value"), r, "default_value")
        for name, value in (("minimum", minimum), ("maximum", maximum), ("default_value", default)):
            if value is not None and not isinstance(value, Literal):
                raise SchemaError(f"{r}.{name} must be a literal")
        return cls(
            data_definition_id=as_str(data["data_definition_id"], r, "data_definition_id"),
            name=as_str(data["name"], r, "name"),
            type=as_enum(DataType, data["type"], r, "type"),
            provenance=as_enum(
                Provenance, data.get("provenance", Provenance.OBSERVED.value), r, "provenance"
            ),
            unit=data.get("unit"),
            allowed_values=allowed,  # type: ignore[arg-type]
            minimum=minimum,  # type: ignore[arg-type]
            maximum=maximum,  # type: ignore[arg-type]
            null_policy=as_enum(
                NullPolicy, data.get("null_policy", NullPolicy.UNDEFINED.value), r, "null_policy"
            ),
            default_value=default,  # type: ignore[arg-type]
            derivation_function_id=data.get("derivation_function_id"),
            owning_entity_id=data.get("owning_entity_id"),
            aliases=as_tuple_of_str(data.get("aliases", ()), r, "aliases"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class FunctionSignature:
    """A declared deterministic function the AST may call."""

    function_id: str
    name: str
    parameter_types: tuple[DataType, ...]
    return_type: DataType
    return_unit: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "function_id": self.function_id,
                "name": self.name,
                "parameter_types": [t.value for t in self.parameter_types],
                "return_type": self.return_type.value,
                "return_unit": self.return_unit,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FunctionSignature":
        r = "FunctionSignature"
        check_keys(
            data,
            r,
            ["function_id", "name", "parameter_types", "return_type"],
            ["return_unit", "evidence_ids"],
        )
        return cls(
            function_id=as_str(data["function_id"], r, "function_id"),
            name=as_str(data["name"], r, "name"),
            parameter_types=tuple(
                as_enum(DataType, t, r, "parameter_types") for t in data["parameter_types"]
            ),
            return_type=as_enum(DataType, data["return_type"], r, "return_type"),
            return_unit=data.get("return_unit"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class UnitConversion:
    """A declared, deterministic conversion between two units.

    Without an entry here the type checker refuses to compare quantities in
    different units, so "$5,000" can never quietly satisfy a "€5,000" threshold.
    """

    from_unit: str
    to_unit: str
    factor: float
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "from_unit": self.from_unit,
                "to_unit": self.to_unit,
                "factor": self.factor,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnitConversion":
        r = "UnitConversion"
        check_keys(data, r, ["from_unit", "to_unit", "factor"], ["evidence_ids"])
        factor = data["factor"]
        if isinstance(factor, bool) or not isinstance(factor, (int, float)):
            raise SchemaError(f"{r}.factor must be numeric, got {factor!r}")
        return cls(
            from_unit=as_str(data["from_unit"], r, "from_unit"),
            to_unit=as_str(data["to_unit"], r, "to_unit"),
            factor=float(factor),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class EntityType:
    """A canonical entity with an explicit category."""

    entity_type_id: str
    name: str
    category: EntityCategory
    provenance: Provenance = Provenance.OBSERVED
    definition: str = ""
    data_definition_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "entity_type_id": self.entity_type_id,
                "name": self.name,
                "category": self.category.value,
                "provenance": self.provenance.value,
                "definition": self.definition or None,
                "data_definition_ids": list(self.data_definition_ids) or None,
                "aliases": list(self.aliases) or None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityType":
        r = "EntityType"
        check_keys(
            data,
            r,
            ["entity_type_id", "name", "category"],
            ["provenance", "definition", "data_definition_ids", "aliases", "evidence_ids"],
        )
        return cls(
            entity_type_id=as_str(data["entity_type_id"], r, "entity_type_id"),
            name=as_str(data["name"], r, "name"),
            category=as_enum(EntityCategory, data["category"], r, "category"),
            provenance=as_enum(
                Provenance, data.get("provenance", Provenance.OBSERVED.value), r, "provenance"
            ),
            definition=data.get("definition", ""),
            data_definition_ids=as_tuple_of_str(
                data.get("data_definition_ids", ()), r, "data_definition_ids"
            ),
            aliases=as_tuple_of_str(data.get("aliases", ()), r, "aliases"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class EntityMention:
    """A surface mention resolved to a canonical entity, with the mapping kept.

    Resolution never rewrites the mention in place: the confidence, the method
    and any unresolved alternatives stay recorded so an audit can see what was
    collapsed.
    """

    mention_id: str
    surface_text: str
    evidence_id: str
    entity_type_id: str | None = None
    resolution_confidence: float | None = None
    resolution_method: str | None = None
    unresolved_alternatives: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "mention_id": self.mention_id,
                "surface_text": self.surface_text,
                "evidence_id": self.evidence_id,
                "entity_type_id": self.entity_type_id,
                "resolution_confidence": self.resolution_confidence,
                "resolution_method": self.resolution_method,
                "unresolved_alternatives": list(self.unresolved_alternatives) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityMention":
        r = "EntityMention"
        check_keys(
            data,
            r,
            ["mention_id", "surface_text", "evidence_id"],
            [
                "entity_type_id",
                "resolution_confidence",
                "resolution_method",
                "unresolved_alternatives",
            ],
        )
        return cls(
            mention_id=as_str(data["mention_id"], r, "mention_id"),
            surface_text=as_str(data["surface_text"], r, "surface_text"),
            evidence_id=as_str(data["evidence_id"], r, "evidence_id"),
            entity_type_id=data.get("entity_type_id"),
            resolution_confidence=data.get("resolution_confidence"),
            resolution_method=data.get("resolution_method"),
            unresolved_alternatives=as_tuple_of_str(
                data.get("unresolved_alternatives", ()), r, "unresolved_alternatives"
            ),
        )


# ---------------------------------------------------------------------------
# Clauses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectivePeriod:
    """When a clause is in force. Absent bounds mean "not stated in the source"."""

    start: str | None = None
    end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return drop_none({"start": self.start, "end": self.end})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EffectivePeriod":
        check_keys(data, "EffectivePeriod", [], ["start", "end"])
        return cls(start=data.get("start"), end=data.get("end"))


@dataclass(frozen=True)
class TemporalConstraint:
    """An explicit deadline or waiting period attached to a clause.

    Kept distinct from a BPMN timer on purpose: "records must be retained for
    five years" is a temporal constraint and not a five-year timer process.
    """

    duration: Literal
    calendar: Calendar = Calendar.CALENDAR_DAYS
    relative_to: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "duration": self.duration.to_dict(),
                "calendar": self.calendar.value,
                "relative_to": self.relative_to,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TemporalConstraint":
        r = "TemporalConstraint"
        check_keys(data, r, ["duration"], ["calendar", "relative_to", "evidence_ids"])
        duration = _expr(data["duration"], r, "duration")
        if not isinstance(duration, Literal) or duration.type is not DataType.DURATION:
            raise SchemaError(f"{r}.duration must be a duration literal")
        return cls(
            duration=duration,
            calendar=as_enum(
                Calendar, data.get("calendar", Calendar.CALENDAR_DAYS.value), r, "calendar"
            ),
            relative_to=data.get("relative_to"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class AtomicPolicyClause:
    """One atomic normative statement, bound to evidence field by field.

    ``evidence`` maps a :class:`~policy_ir.enums.SemanticRole` to the spans that
    support that part of the clause. A clause whose condition has no
    ``condition`` evidence cannot pass the gate, which is what stops a plausible
    but unsupported threshold from reaching a decision table.
    """

    clause_id: str
    modality: Modality
    semantic_kind: SemanticKind
    effect: Effect
    display_text: str
    evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    source_group_id: str | None = None
    lifecycle: Lifecycle = Lifecycle.UNKNOWN
    compilation_intent: CompilationIntent = CompilationIntent.UNRESOLVED
    subject_ref: str | None = None
    action: str | None = None
    object_ref: str | None = None
    condition_ast: Expression | None = None
    effect_ast: Expression | None = None
    exception_ast: Expression | None = None
    temporal_constraint: TemporalConstraint | None = None
    scope: Scope = field(default_factory=Scope)
    effective_period: EffectivePeriod = field(default_factory=EffectivePeriod)
    authority_ref: str | None = None
    cross_reference_targets: tuple[str, ...] = ()
    legacy_rule_ids: tuple[str, ...] = ()

    def evidence_for(self, role: SemanticRole | str) -> tuple[str, ...]:
        key = role.value if isinstance(role, SemanticRole) else role
        return tuple(self.evidence.get(key, ()))

    def all_evidence_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for role in sorted(self.evidence):
            for value in self.evidence[role]:
                if value not in seen:
                    seen.append(value)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "clause_id": self.clause_id,
                "modality": self.modality.value,
                "semantic_kind": self.semantic_kind.value,
                "effect": self.effect.value,
                "display_text": self.display_text,
                "evidence": {k: list(v) for k, v in sorted(self.evidence.items())} or None,
                "source_group_id": self.source_group_id,
                "lifecycle": self.lifecycle.value,
                "compilation_intent": self.compilation_intent.value,
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
                "legacy_rule_ids": list(self.legacy_rule_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AtomicPolicyClause":
        r = "AtomicPolicyClause"
        check_keys(
            data,
            r,
            ["clause_id", "modality", "semantic_kind", "effect", "display_text"],
            [
                "evidence",
                "source_group_id",
                "lifecycle",
                "compilation_intent",
                "subject_ref",
                "action",
                "object_ref",
                "condition_ast",
                "effect_ast",
                "exception_ast",
                "temporal_constraint",
                "scope",
                "effective_period",
                "authority_ref",
                "cross_reference_targets",
                "legacy_rule_ids",
            ],
        )
        raw_evidence = data.get("evidence", {})
        if not isinstance(raw_evidence, Mapping):
            raise SchemaError(f"{r}.evidence must be an object keyed by semantic role")
        evidence: dict[str, tuple[str, ...]] = {}
        for role, ids in raw_evidence.items():
            as_enum(SemanticRole, role, r, "evidence")
            evidence[role] = as_tuple_of_str(ids, r, f"evidence.{role}")
        return cls(
            clause_id=as_str(data["clause_id"], r, "clause_id"),
            modality=as_enum(Modality, data["modality"], r, "modality"),
            semantic_kind=as_enum(SemanticKind, data["semantic_kind"], r, "semantic_kind"),
            effect=as_enum(Effect, data["effect"], r, "effect"),
            display_text=as_str(data["display_text"], r, "display_text"),
            evidence=evidence,
            source_group_id=data.get("source_group_id"),
            lifecycle=as_enum(
                Lifecycle, data.get("lifecycle", Lifecycle.UNKNOWN.value), r, "lifecycle"
            ),
            compilation_intent=as_enum(
                CompilationIntent,
                data.get("compilation_intent", CompilationIntent.UNRESOLVED.value),
                r,
                "compilation_intent",
            ),
            subject_ref=data.get("subject_ref"),
            action=data.get("action"),
            object_ref=data.get("object_ref"),
            condition_ast=_opt_expr(data.get("condition_ast"), r, "condition_ast"),
            effect_ast=_opt_expr(data.get("effect_ast"), r, "effect_ast"),
            exception_ast=_opt_expr(data.get("exception_ast"), r, "exception_ast"),
            temporal_constraint=(
                TemporalConstraint.from_dict(data["temporal_constraint"])
                if data.get("temporal_constraint")
                else None
            ),
            scope=Scope.from_dict(data.get("scope", {})),
            effective_period=EffectivePeriod.from_dict(data.get("effective_period", {})),
            authority_ref=data.get("authority_ref"),
            cross_reference_targets=as_tuple_of_str(
                data.get("cross_reference_targets", ()), r, "cross_reference_targets"
            ),
            legacy_rule_ids=as_tuple_of_str(data.get("legacy_rule_ids", ()), r, "legacy_rule_ids"),
        )


# ---------------------------------------------------------------------------
# Decision and process candidates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionOutput:
    """The single output a decision produces."""

    name: str
    type: DataType
    unit: str | None = None
    allowed_values: tuple[Literal, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "name": self.name,
                "type": self.type.value,
                "unit": self.unit,
                "allowed_values": [v.to_dict() for v in self.allowed_values] or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionOutput":
        r = "DecisionOutput"
        check_keys(data, r, ["name", "type"], ["unit", "allowed_values"])
        allowed = tuple(_expr(v, r, "allowed_values") for v in data.get("allowed_values", ()))
        for value in allowed:
            if not isinstance(value, Literal):
                raise SchemaError(f"{r}.allowed_values entries must be literals")
        return cls(
            name=as_str(data["name"], r, "name"),
            type=as_enum(DataType, data["type"], r, "type"),
            unit=data.get("unit"),
            allowed_values=allowed,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DecisionModelCandidate:
    """A candidate DMN decision. Nothing here is guaranteed compilable.

    ``proposed_hit_policy`` is a proposal only. ``UNIQUE`` is admitted only when
    the compiler can *prove* the rows do not overlap; ``FIRST``/``PRIORITY``
    need ``ordering_evidence_ids``; ``COLLECT`` needs an ``aggregation``.
    """

    decision_id: str
    name: str
    question: str
    output_definition: DecisionOutput
    input_data_refs: tuple[str, ...] = ()
    decision_rule_refs: tuple[str, ...] = ()
    required_decision_refs: tuple[str, ...] = ()
    authority_refs: tuple[str, ...] = ()
    proposed_hit_policy: HitPolicy = HitPolicy.UNIQUE
    aggregation: Aggregation | None = None
    ordering_evidence_ids: tuple[str, ...] = ()
    default_output: Literal | None = None
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "decision_id": self.decision_id,
                "name": self.name,
                "question": self.question,
                "output_definition": self.output_definition.to_dict(),
                "input_data_refs": list(self.input_data_refs) or None,
                "decision_rule_refs": list(self.decision_rule_refs) or None,
                "required_decision_refs": list(self.required_decision_refs) or None,
                "authority_refs": list(self.authority_refs) or None,
                "proposed_hit_policy": self.proposed_hit_policy.value,
                "aggregation": self.aggregation.value if self.aggregation else None,
                "ordering_evidence_ids": list(self.ordering_evidence_ids) or None,
                "default_output": self.default_output.to_dict() if self.default_output else None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionModelCandidate":
        r = "DecisionModelCandidate"
        check_keys(
            data,
            r,
            ["decision_id", "name", "question", "output_definition"],
            [
                "input_data_refs",
                "decision_rule_refs",
                "required_decision_refs",
                "authority_refs",
                "proposed_hit_policy",
                "aggregation",
                "ordering_evidence_ids",
                "default_output",
                "evidence_ids",
            ],
        )
        default = _opt_expr(data.get("default_output"), r, "default_output")
        if default is not None and not isinstance(default, Literal):
            raise SchemaError(f"{r}.default_output must be a literal")
        return cls(
            decision_id=as_str(data["decision_id"], r, "decision_id"),
            name=as_str(data["name"], r, "name"),
            question=as_str(data["question"], r, "question"),
            output_definition=DecisionOutput.from_dict(data["output_definition"]),
            input_data_refs=as_tuple_of_str(data.get("input_data_refs", ()), r, "input_data_refs"),
            decision_rule_refs=as_tuple_of_str(
                data.get("decision_rule_refs", ()), r, "decision_rule_refs"
            ),
            required_decision_refs=as_tuple_of_str(
                data.get("required_decision_refs", ()), r, "required_decision_refs"
            ),
            authority_refs=as_tuple_of_str(data.get("authority_refs", ()), r, "authority_refs"),
            proposed_hit_policy=as_enum(
                HitPolicy,
                data.get("proposed_hit_policy", HitPolicy.UNIQUE.value),
                r,
                "proposed_hit_policy",
            ),
            aggregation=(
                as_enum(Aggregation, data["aggregation"], r, "aggregation")
                if data.get("aggregation")
                else None
            ),
            ordering_evidence_ids=as_tuple_of_str(
                data.get("ordering_evidence_ids", ()), r, "ordering_evidence_ids"
            ),
            default_output=default,  # type: ignore[arg-type]
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class TriggerEvent:
    """An explicit process entry point.

    ``kind`` distinguishes a message arrival from a timer from a plain condition,
    because BPMN gives those different shapes and guessing between them invents
    process semantics the source never stated.
    """

    event_id: str
    name: str
    kind: str = "none"
    evidence_ids: tuple[str, ...] = ()

    KINDS = ("none", "message", "timer", "condition")

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "event_id": self.event_id,
                "name": self.name,
                "kind": self.kind,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TriggerEvent":
        r = "TriggerEvent"
        check_keys(data, r, ["event_id", "name"], ["kind", "evidence_ids"])
        kind = data.get("kind", "none")
        if kind not in cls.KINDS:
            raise SchemaError(f"{r}.kind must be one of {list(cls.KINDS)}, got {kind!r}")
        return cls(
            event_id=as_str(data["event_id"], r, "event_id"),
            name=as_str(data["name"], r, "name"),
            kind=kind,
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class ProcessActivity:
    """One activity in a process fragment."""

    activity_id: str
    name: str
    kind: str = "task"
    actor_ref: str | None = None
    decision_ref: str | None = None
    evidence_ids: tuple[str, ...] = ()

    KINDS = ("task", "business_rule_task", "subprocess")

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "activity_id": self.activity_id,
                "name": self.name,
                "kind": self.kind,
                "actor_ref": self.actor_ref,
                "decision_ref": self.decision_ref,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProcessActivity":
        r = "ProcessActivity"
        check_keys(
            data, r, ["activity_id", "name"], ["kind", "actor_ref", "decision_ref", "evidence_ids"]
        )
        kind = data.get("kind", "task")
        if kind not in cls.KINDS:
            raise SchemaError(f"{r}.kind must be one of {list(cls.KINDS)}, got {kind!r}")
        return cls(
            activity_id=as_str(data["activity_id"], r, "activity_id"),
            name=as_str(data["name"], r, "name"),
            kind=kind,
            actor_ref=data.get("actor_ref"),
            decision_ref=data.get("decision_ref"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class ProcessFragmentCandidate:
    """A candidate BPMN process fragment.

    A ``process`` tag is not enough. Executable BPMN needs an explicit trigger,
    a responsible participant, at least one activity, validated ordering and a
    known end state; anything missing yields a review fragment at best.
    """

    fragment_id: str
    name: str
    activities: tuple[ProcessActivity, ...] = ()
    trigger_event: TriggerEvent | None = None
    responsible_actor_ref: str | None = None
    participant_refs: tuple[str, ...] = ()
    ordering: tuple[tuple[str, str], ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    precondition_ast: Expression | None = None
    postcondition_ast: Expression | None = None
    decision_ref: str | None = None
    temporal_constraint: TemporalConstraint | None = None
    exception_or_escalation: str | None = None
    end_state: str | None = None
    clause_refs: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "fragment_id": self.fragment_id,
                "name": self.name,
                "activities": [a.to_dict() for a in self.activities] or None,
                "trigger_event": self.trigger_event.to_dict() if self.trigger_event else None,
                "responsible_actor_ref": self.responsible_actor_ref,
                "participant_refs": list(self.participant_refs) or None,
                "ordering": [list(pair) for pair in self.ordering] or None,
                "input_refs": list(self.input_refs) or None,
                "output_refs": list(self.output_refs) or None,
                "precondition_ast": (
                    self.precondition_ast.to_dict() if self.precondition_ast else None
                ),
                "postcondition_ast": (
                    self.postcondition_ast.to_dict() if self.postcondition_ast else None
                ),
                "decision_ref": self.decision_ref,
                "temporal_constraint": (
                    self.temporal_constraint.to_dict() if self.temporal_constraint else None
                ),
                "exception_or_escalation": self.exception_or_escalation,
                "end_state": self.end_state,
                "clause_refs": list(self.clause_refs) or None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProcessFragmentCandidate":
        r = "ProcessFragmentCandidate"
        check_keys(
            data,
            r,
            ["fragment_id", "name"],
            [
                "activities",
                "trigger_event",
                "responsible_actor_ref",
                "participant_refs",
                "ordering",
                "input_refs",
                "output_refs",
                "precondition_ast",
                "postcondition_ast",
                "decision_ref",
                "temporal_constraint",
                "exception_or_escalation",
                "end_state",
                "clause_refs",
                "evidence_ids",
            ],
        )
        ordering: list[tuple[str, str]] = []
        for pair in data.get("ordering", ()):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise SchemaError(f"{r}.ordering entries must be [from, to] pairs")
            ordering.append((as_str(pair[0], r, "ordering"), as_str(pair[1], r, "ordering")))
        return cls(
            fragment_id=as_str(data["fragment_id"], r, "fragment_id"),
            name=as_str(data["name"], r, "name"),
            activities=as_tuple(data.get("activities", ()), r, "activities", ProcessActivity.from_dict),
            trigger_event=(
                TriggerEvent.from_dict(data["trigger_event"]) if data.get("trigger_event") else None
            ),
            responsible_actor_ref=data.get("responsible_actor_ref"),
            participant_refs=as_tuple_of_str(
                data.get("participant_refs", ()), r, "participant_refs"
            ),
            ordering=tuple(ordering),
            input_refs=as_tuple_of_str(data.get("input_refs", ()), r, "input_refs"),
            output_refs=as_tuple_of_str(data.get("output_refs", ()), r, "output_refs"),
            precondition_ast=_opt_expr(data.get("precondition_ast"), r, "precondition_ast"),
            postcondition_ast=_opt_expr(data.get("postcondition_ast"), r, "postcondition_ast"),
            decision_ref=data.get("decision_ref"),
            temporal_constraint=(
                TemporalConstraint.from_dict(data["temporal_constraint"])
                if data.get("temporal_constraint")
                else None
            ),
            exception_or_escalation=data.get("exception_or_escalation"),
            end_state=data.get("end_state"),
            clause_refs=as_tuple_of_str(data.get("clause_refs", ()), r, "clause_refs"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class DependencyEdge:
    """A typed, evidenced relation between two IR elements."""

    edge_id: str
    source_id: str
    target_id: str
    kind: DependencyKind
    derivation_method: DerivationMethod
    direction_semantics: str = ""
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "edge_id": self.edge_id,
                "source_id": self.source_id,
                "target_id": self.target_id,
                "kind": self.kind.value,
                "derivation_method": self.derivation_method.value,
                "direction_semantics": self.direction_semantics or None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyEdge":
        r = "DependencyEdge"
        check_keys(
            data,
            r,
            ["edge_id", "source_id", "target_id", "kind", "derivation_method"],
            ["direction_semantics", "evidence_ids"],
        )
        return cls(
            edge_id=as_str(data["edge_id"], r, "edge_id"),
            source_id=as_str(data["source_id"], r, "source_id"),
            target_id=as_str(data["target_id"], r, "target_id"),
            kind=as_enum(DependencyKind, data["kind"], r, "kind"),
            derivation_method=as_enum(
                DerivationMethod, data["derivation_method"], r, "derivation_method"
            ),
            direction_semantics=data.get("direction_semantics", ""),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class SemanticRelation:
    """An evidenced relation in the canonical semantic graph.

    This is deliberately distinct from ``DependencyEdge``: it captures concepts such
    as ``defines`` or ``applies_to`` without asserting executable ordering.
    """

    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    provenance: Provenance = Provenance.PROPOSED
    derivation_method: DerivationMethod = DerivationMethod.MODEL_ASSISTED_CANDIDATE
    qualifiers: Mapping[str, str] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "relation_id": self.relation_id,
                "source_id": self.source_id,
                "target_id": self.target_id,
                "relation_type": self.relation_type,
                "provenance": self.provenance.value,
                "derivation_method": self.derivation_method.value,
                "qualifiers": dict(sorted(self.qualifiers.items())) or None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticRelation":
        r = "SemanticRelation"
        check_keys(
            data,
            r,
            ["relation_id", "source_id", "target_id", "relation_type"],
            ["provenance", "derivation_method", "qualifiers", "evidence_ids"],
        )
        qualifiers = data.get("qualifiers", {})
        if not isinstance(qualifiers, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in qualifiers.items()
        ):
            raise SchemaError(f"{r}.qualifiers must be an object of string values")
        return cls(
            relation_id=as_str(data["relation_id"], r, "relation_id"),
            source_id=as_str(data["source_id"], r, "source_id"),
            target_id=as_str(data["target_id"], r, "target_id"),
            relation_type=as_str(data["relation_type"], r, "relation_type"),
            provenance=as_enum(
                Provenance, data.get("provenance", Provenance.PROPOSED.value), r, "provenance"
            ),
            derivation_method=as_enum(
                DerivationMethod,
                data.get("derivation_method", DerivationMethod.MODEL_ASSISTED_CANDIDATE.value),
                r,
                "derivation_method",
            ),
            qualifiers=dict(qualifiers),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class CoverageEntry:
    """What happened to one chunk during extraction.

    Without this ledger a corpus can look fully processed when half of it
    silently produced nothing.
    """

    chunk_id: str
    status: str
    note: str = ""

    STATUSES = (
        "processed",
        "no_policy_semantics_found",
        "candidates_emitted",
        "extraction_failed",
        "intentionally_excluded",
        "unresolved",
    )

    def to_dict(self) -> dict[str, Any]:
        return drop_none({"chunk_id": self.chunk_id, "status": self.status, "note": self.note or None})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageEntry":
        r = "CoverageEntry"
        check_keys(data, r, ["chunk_id", "status"], ["note"])
        status = data["status"]
        if status not in cls.STATUSES:
            raise SchemaError(f"{r}.status must be one of {list(cls.STATUSES)}, got {status!r}")
        return cls(
            chunk_id=as_str(data["chunk_id"], r, "chunk_id"),
            status=status,
            note=data.get("note", ""),
        )


@dataclass(frozen=True)
class PolicyIR:
    """The canonical Policy IR document."""

    schema_version: str = SCHEMA_VERSION
    documents: tuple[DocumentArtifact, ...] = ()
    chunks: tuple[Chunk, ...] = ()
    evidence_spans: tuple[EvidenceSpan, ...] = ()
    entity_types: tuple[EntityType, ...] = ()
    entity_mentions: tuple[EntityMention, ...] = ()
    scope_dimensions: tuple[ScopeDimensionDefinition, ...] = ()
    authority_sources: tuple[AuthoritySource, ...] = ()
    data_definitions: tuple[DataDefinition, ...] = ()
    functions: tuple[FunctionSignature, ...] = ()
    unit_conversions: tuple[UnitConversion, ...] = ()
    clauses: tuple[AtomicPolicyClause, ...] = ()
    decisions: tuple[DecisionModelCandidate, ...] = ()
    processes: tuple[ProcessFragmentCandidate, ...] = ()
    dependencies: tuple[DependencyEdge, ...] = ()
    semantic_relations: tuple[SemanticRelation, ...] = ()
    coverage: tuple[CoverageEntry, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    # -- indexes ---------------------------------------------------------
    #
    # Each index is built once and memoised. Every field of this record is a tuple, so
    # the document is genuinely immutable and a cached index can never go stale.
    #
    # The memo matters at corpus scale rather than in a fixture. Rebuilding an index
    # inside a per-clause or per-span loop makes the gate and the graph projection
    # O(clauses x spans): a synthetic run showed the time quadrupling on every doubling
    # of input, so a corpus of tens of thousands of clauses never finished.
    #
    # The returned mapping is shared. Treat it as read-only; copy it before mutating.
    def _index(self, name: str, build: Any) -> Any:
        cache = getattr(self, "_index_cache", None)
        if cache is None:
            cache = {}
            # A plain attribute, not a dataclass field, so equality, hashing and
            # to_dict() are unaffected by its presence.
            object.__setattr__(self, "_index_cache", cache)
        if name not in cache:
            cache[name] = build()
        return cache[name]

    def document_index(self) -> dict[str, DocumentArtifact]:
        return self._index("documents", lambda: {d.document_id: d for d in self.documents})

    def chunk_index(self) -> dict[str, Chunk]:
        return self._index("chunks", lambda: {c.chunk_id: c for c in self.chunks})

    def evidence_index(self) -> dict[str, EvidenceSpan]:
        return self._index(
            "evidence", lambda: {e.evidence_id: e for e in self.evidence_spans}
        )

    def data_definition_index(self) -> dict[str, DataDefinition]:
        return self._index(
            "data_definitions",
            lambda: {d.data_definition_id: d for d in self.data_definitions},
        )

    def function_index(self) -> dict[str, FunctionSignature]:
        return self._index("functions", lambda: {f.function_id: f for f in self.functions})

    def clause_index(self) -> dict[str, AtomicPolicyClause]:
        return self._index("clauses", lambda: {c.clause_id: c for c in self.clauses})

    def decision_index(self) -> dict[str, DecisionModelCandidate]:
        return self._index("decisions", lambda: {d.decision_id: d for d in self.decisions})

    def process_index(self) -> dict[str, ProcessFragmentCandidate]:
        return self._index("processes", lambda: {p.fragment_id: p for p in self.processes})

    def entity_index(self) -> dict[str, EntityType]:
        return self._index("entities", lambda: {e.entity_type_id: e for e in self.entity_types})

    def relation_index(self) -> dict[str, SemanticRelation]:
        return self._index(
            "semantic_relations", lambda: {r.relation_id: r for r in self.semantic_relations}
        )

    def scope_dimension_index(self) -> dict[str, ScopeDimensionDefinition]:
        """Declared scope axes, keyed by the name clauses cite."""
        return self._index("scope_dimensions", lambda: {d.name: d for d in self.scope_dimensions})

    def authority_index(self) -> dict[str, AuthoritySource]:
        return self._index(
            "authorities", lambda: {a.authority_id: a for a in self.authority_sources}
        )

    def clause_id_set(self) -> frozenset[str]:
        """Cached set of clause IDs, for the many membership tests over it."""
        return self._index("clause_ids", lambda: frozenset(c.clause_id for c in self.clauses))

    def section_paths(self) -> frozenset[str]:
        """Cached set of non-empty section paths, used to resolve cross references."""
        return self._index(
            "section_paths",
            lambda: frozenset(c.section_path for c in self.chunks if c.section_path),
        )

    def conversion_index(self) -> dict[tuple[str, str], UnitConversion]:
        return self._index(
            "conversions", lambda: {(c.from_unit, c.to_unit): c for c in self.unit_conversions}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "documents": [d.to_dict() for d in self.documents],
            "chunks": [c.to_dict() for c in self.chunks],
            "evidence_spans": [e.to_dict() for e in self.evidence_spans],
            "entity_types": [e.to_dict() for e in self.entity_types],
            "entity_mentions": [m.to_dict() for m in self.entity_mentions],
            "scope_dimensions": [d.to_dict() for d in self.scope_dimensions],
            "authority_sources": [a.to_dict() for a in self.authority_sources],
            "data_definitions": [d.to_dict() for d in self.data_definitions],
            "functions": [f.to_dict() for f in self.functions],
            "unit_conversions": [c.to_dict() for c in self.unit_conversions],
            "clauses": [c.to_dict() for c in self.clauses],
            "decisions": [d.to_dict() for d in self.decisions],
            "processes": [p.to_dict() for p in self.processes],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "semantic_relations": [r.to_dict() for r in self.semantic_relations],
            "coverage": [c.to_dict() for c in self.coverage],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyIR":
        r = "PolicyIR"
        check_keys(
            data,
            r,
            ["schema_version"],
            [
                "documents",
                "chunks",
                "evidence_spans",
                "entity_types",
                "entity_mentions",
                "scope_dimensions",
                "authority_sources",
                "data_definitions",
                "functions",
                "unit_conversions",
                "clauses",
                "decisions",
                "processes",
                "dependencies",
                "semantic_relations",
                "coverage",
                "metadata",
            ],
        )
        version = as_str(data["schema_version"], r, "schema_version")
        if version != SCHEMA_VERSION:
            raise SchemaError(
                f"{r}.schema_version {version!r} does not match this build's {SCHEMA_VERSION!r}"
            )
        return cls(
            schema_version=version,
            documents=as_tuple(data.get("documents", ()), r, "documents", DocumentArtifact.from_dict),
            chunks=as_tuple(data.get("chunks", ()), r, "chunks", Chunk.from_dict),
            evidence_spans=as_tuple(
                data.get("evidence_spans", ()), r, "evidence_spans", EvidenceSpan.from_dict
            ),
            entity_types=as_tuple(
                data.get("entity_types", ()), r, "entity_types", EntityType.from_dict
            ),
            entity_mentions=as_tuple(
                data.get("entity_mentions", ()), r, "entity_mentions", EntityMention.from_dict
            ),
            scope_dimensions=as_tuple(
                data.get("scope_dimensions", ()),
                r,
                "scope_dimensions",
                ScopeDimensionDefinition.from_dict,
            ),
            authority_sources=as_tuple(
                data.get("authority_sources", ()), r, "authority_sources", AuthoritySource.from_dict
            ),
            data_definitions=as_tuple(
                data.get("data_definitions", ()), r, "data_definitions", DataDefinition.from_dict
            ),
            functions=as_tuple(data.get("functions", ()), r, "functions", FunctionSignature.from_dict),
            unit_conversions=as_tuple(
                data.get("unit_conversions", ()), r, "unit_conversions", UnitConversion.from_dict
            ),
            clauses=as_tuple(data.get("clauses", ()), r, "clauses", AtomicPolicyClause.from_dict),
            decisions=as_tuple(
                data.get("decisions", ()), r, "decisions", DecisionModelCandidate.from_dict
            ),
            processes=as_tuple(
                data.get("processes", ()), r, "processes", ProcessFragmentCandidate.from_dict
            ),
            dependencies=as_tuple(
                data.get("dependencies", ()), r, "dependencies", DependencyEdge.from_dict
            ),
            semantic_relations=as_tuple(
                data.get("semantic_relations", ()), r, "semantic_relations", SemanticRelation.from_dict
            ),
            coverage=as_tuple(data.get("coverage", ()), r, "coverage", CoverageEntry.from_dict),
            metadata=dict(data.get("metadata", {})),
        )
