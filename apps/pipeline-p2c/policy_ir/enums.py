"""Closed vocabularies for Policy IR v2.

Every enum here is part of the versioned contract. Adding a member is a schema
change: bump ``SCHEMA_VERSION`` in :mod:`policy_ir.ids` and regenerate the JSON
Schema, because deterministic clause IDs and the compilers both key off these
values.

The plan this implements deliberately replaces the legacy single ``rule_type``
field with orthogonal axes (modality, semantic kind, effect, lifecycle,
compilation intent), so a clause can be an obligation *and* a temporal
constraint *and* a process fragment without losing information.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Enum whose members serialize as their own string value."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class Modality(StrEnum):
    """What normative force a clause carries."""

    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    RECOMMENDATION = "recommendation"
    DEFINITION = "definition"


class SemanticKind(StrEnum):
    """What kind of statement a clause is, independent of its modality."""

    DECISION_RULE = "decision_rule"
    CALCULATION = "calculation"
    VALIDATION = "validation"
    TEMPORAL_CONSTRAINT = "temporal_constraint"
    DOCUMENTATION_REQUIREMENT = "documentation_requirement"
    PROCESS_FRAGMENT = "process_fragment"
    AUTHORITY_STATEMENT = "authority_statement"
    #: Used by the legacy adapter when the historical record does not say what kind
    #: of statement a rule is. Guessing a kind here would be the adapter inventing
    #: semantics, which the plan forbids.
    UNCLASSIFIED = "unclassified"


class Effect(StrEnum):
    """What happens when a clause fires."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_ACTION = "require_action"
    PRODUCE_VALUE = "produce_value"
    CREATE_RECORD = "create_record"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    NO_DIRECT_EFFECT = "no_direct_effect"


class Lifecycle(StrEnum):
    """Whether a clause is currently in force."""

    ACTIVE = "active"
    FUTURE = "future"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class CompilationIntent(StrEnum):
    """Where the author believes a clause should be projected.

    Intent is a *request*, never a permission: the evidence gate decides
    eligibility independently.
    """

    DMN = "dmn"
    BPMN = "bpmn"
    BOTH = "both"
    GRAPH_ONLY = "graph_only"
    UNRESOLVED = "unresolved"


class MatchStatus(StrEnum):
    """How firmly an evidence span is anchored in immutable source bytes."""

    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    RECOVERED = "recovered"
    UNRESOLVED = "unresolved"


class SemanticRole(StrEnum):
    """Which part of a clause a given evidence span supports."""

    SUBJECT = "subject"
    CONDITION = "condition"
    EFFECT = "effect"
    EXCEPTION = "exception"
    TEMPORAL = "temporal"
    AUTHORITY = "authority"
    CROSS_REFERENCE = "cross_reference"
    SCOPE = "scope"


class Provenance(StrEnum):
    """Whether an element came from the source text or from model invention.

    Only ``OBSERVED`` and ``NORMALIZED`` elements may reach an executable
    projection; ``PROPOSED`` elements stay visible in the graph but can never
    become DMN inputs or BPMN flow nodes.
    """

    OBSERVED = "observed"
    NORMALIZED = "normalized"
    PROPOSED = "proposed"
    UNRESOLVED = "unresolved"


class EntityCategory(StrEnum):
    """Explicit entity semantics, replacing UPPER_CASE naming conventions."""

    ACTOR_OR_ROLE = "actor_or_role"
    ORGANIZATION = "organization"
    SYSTEM = "system"
    BUSINESS_OBJECT = "business_object"
    DOCUMENT_OR_RECORD = "document_or_record"
    DATA_ELEMENT = "data_element"
    EVENT = "event"
    ACTIVITY = "activity"
    DECISION = "decision"
    OUTCOME = "outcome"
    AUTHORITY_OR_POLICY_SOURCE = "authority_or_policy_source"
    TEMPORAL_CONCEPT = "temporal_concept"
    JURISDICTION_OR_SCOPE = "jurisdiction_or_scope"
    #: Legacy entities carry an UPPER_CASE name and nothing else, so their category
    #: is genuinely unknown. An unclassified entity can never own an activity.
    UNCLASSIFIED = "unclassified"


class DataType(StrEnum):
    """FEEL-compatible types a :class:`~policy_ir.models.DataDefinition` may take."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    TIME = "time"
    DATE_TIME = "date_time"
    DURATION = "duration"
    LIST = "list"
    CONTEXT = "context"


#: Types on which ``<``, ``<=``, ``>`` and ``>=`` are meaningful.
ORDERED_TYPES = frozenset(
    {
        DataType.NUMBER,
        DataType.DATE,
        DataType.TIME,
        DataType.DATE_TIME,
        DataType.DURATION,
    }
)

#: FEEL type names emitted into DMN ``typeRef`` attributes.
FEEL_TYPE_NAMES = {
    DataType.STRING: "string",
    DataType.NUMBER: "number",
    DataType.BOOLEAN: "boolean",
    DataType.DATE: "date",
    DataType.TIME: "time",
    DataType.DATE_TIME: "date and time",
    DataType.DURATION: "days and time duration",
    DataType.LIST: "Any",
    DataType.CONTEXT: "Any",
}


class NullPolicy(StrEnum):
    """Declared behaviour when an input value is absent or unknown.

    DMN eligibility requires this to be something other than ``UNDEFINED``:
    the plan forbids compiling a decision whose null handling is unstated.
    """

    UNDEFINED = "undefined"
    REJECT = "reject"
    TREAT_AS_ABSENT = "treat_as_absent"
    DEFAULT_VALUE = "default_value"


class HitPolicy(StrEnum):
    """DMN hit policies this compiler is willing to emit.

    ``UNIQUE`` requires a machine-checked non-overlap proof, ``FIRST`` and
    ``PRIORITY`` require source-supported ordering, and ``COLLECT`` requires a
    declared aggregation. Nothing here is ever guessed.
    """

    UNIQUE = "UNIQUE"
    FIRST = "FIRST"
    PRIORITY = "PRIORITY"
    COLLECT = "COLLECT"


class Aggregation(StrEnum):
    """DMN ``COLLECT`` aggregators (the full ``tBuiltinAggregator`` set)."""

    SUM = "SUM"
    COUNT = "COUNT"
    MIN = "MIN"
    MAX = "MAX"


class DependencyKind(StrEnum):
    """Typed replacement for the legacy single inferred-dependency space."""

    SOURCE_REFERENCE = "source_reference"
    INFORMATION_REQUIREMENT = "information_requirement"
    DERIVATION = "derivation"
    TEMPORAL_PRECEDENCE = "temporal_precedence"
    ACTIVATION = "activation"
    EXCEPTION_TO = "exception_to"
    OVERRIDE = "override"
    #: source supersedes target. Paired with the superseding clause's effective
    #: period, this is what makes "what was in force on date X" answerable.
    SUPERSEDES = "supersedes"
    CONFLICT = "conflict"
    RELATED = "related"


class DerivationMethod(StrEnum):
    """How a dependency edge was produced, in descending order of trust."""

    EXPLICIT_CROSS_REFERENCE = "explicit_cross_reference"
    DETERMINISTIC_SHARED_VARIABLE = "deterministic_shared_variable"
    EXPLICIT_TEMPORAL_LANGUAGE = "explicit_temporal_language"
    MODEL_ASSISTED_CANDIDATE = "model_assisted_candidate"
    UNRESOLVED_ASSOCIATION = "unresolved_association"


#: Dependency edges that may carry executable meaning, and only when validated.
EXECUTABLE_DEPENDENCY_KINDS = frozenset(
    {
        DependencyKind.INFORMATION_REQUIREMENT,
        DependencyKind.DERIVATION,
        DependencyKind.TEMPORAL_PRECEDENCE,
        DependencyKind.ACTIVATION,
        DependencyKind.SUPERSEDES,
    }
)

#: Derivation methods trusted enough to admit an executable dependency edge.
TRUSTED_DERIVATION_METHODS = frozenset(
    {
        DerivationMethod.EXPLICIT_CROSS_REFERENCE,
        DerivationMethod.DETERMINISTIC_SHARED_VARIABLE,
        DerivationMethod.EXPLICIT_TEMPORAL_LANGUAGE,
    }
)


class Status(StrEnum):
    """Independent admission statuses, never collapsed into one boolean.

    A clause can be ``SCHEMA_VALID`` and ``PROVENANCE_EXACT`` yet fail
    ``SEMANTIC_SUPPORTED``; the graph projection accepts far less than the DMN
    or BPMN compilers do.
    """

    SCHEMA_VALID = "schema_valid"
    PROVENANCE_EXACT = "provenance_exact"
    SEMANTIC_SUPPORTED = "semantic_supported"
    GRAPH_ELIGIBLE = "graph_eligible"
    DMN_ELIGIBLE = "dmn_eligible"
    BPMN_ELIGIBLE = "bpmn_eligible"


class CompilerProfile(StrEnum):
    """Which BPMN/DMN output profile a run requests.

    ``REVIEW`` emits standards-valid artefacts with unresolved items annotated;
    ``EXECUTABLE_SUBSET`` emits only fully admitted elements. Neither implies
    governance approval.
    """

    REVIEW = "review"
    EXECUTABLE_SUBSET = "executable_subset"


class Assurance(StrEnum):
    """The three assurance levels the plan insists on keeping separate."""

    CONFORMANCE_VERIFIED = "conformance_verified"
    SEMANTICALLY_SUPPORTED = "semantically_supported"
    GOVERNANCE_APPROVED = "governance_approved"
