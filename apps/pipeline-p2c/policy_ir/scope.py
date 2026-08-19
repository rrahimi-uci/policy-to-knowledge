"""Contextual scope and authority precedence.

Two related concerns that decide *whether* a clause applies and *which* clause
wins when two of them disagree.

**Scope** answers "where and to what does this apply". Real policy scoping is
multidimensional — a mortgage rule may be limited by state, product, channel and
occupancy at once; a healthcare rule by payer, facility type and state. Modelling
those as fixed fields would hard-code one domain into the schema, so a scope is a
list of *named dimensions* whose vocabularies are declared as data
(:class:`ScopeDimensionDefinition`). The engine only ever compares values it was
given; it knows nothing about mortgages or payers.

**Authority** answers "which source says so, and does it outrank another". A
regulated corpus routinely contains a statute, a regulation, an agency guide and a
bulletin that disagree, and the resolution is a domain fact, not a computable one.
So precedence is declared per corpus as an integer weight and the engine only
compares weights.

Both use the same asymmetry as the rest of the compiler: an answer is given only
when it is certain. Unknown context yields ``None`` rather than a guess, and two
scopes are called disjoint only when they provably cannot both apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

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
from .enums import Provenance

#: Three-valued applicability. ``None`` means "the context does not say".
#:
#: The evaluator has its own ``UNKNOWN`` sentinel, but ``evaluation`` depends on
#: ``policy_ir`` and not the other way round, so importing it here would invert the
#: layering. ``None`` carries the same meaning at this level.
Applicability = bool | None


@dataclass(frozen=True)
class ScopeDimensionDefinition:
    """A declared scope axis and its permitted vocabulary.

    This is the configuration seam the architecture depends on: a new domain adds
    dimension definitions, not pipeline code.
    """

    dimension_id: str
    name: str
    description: str = ""
    allowed_values: tuple[str, ...] = ()
    provenance: Provenance = Provenance.OBSERVED
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "dimension_id": self.dimension_id,
                "name": self.name,
                "description": self.description or None,
                "allowed_values": list(self.allowed_values) or None,
                "provenance": self.provenance.value,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScopeDimensionDefinition":
        r = "ScopeDimensionDefinition"
        check_keys(
            data,
            r,
            ["dimension_id", "name"],
            ["description", "allowed_values", "provenance", "evidence_ids"],
        )
        return cls(
            dimension_id=as_str(data["dimension_id"], r, "dimension_id"),
            name=as_str(data["name"], r, "name"),
            description=data.get("description", ""),
            allowed_values=as_tuple_of_str(data.get("allowed_values", ()), r, "allowed_values"),
            provenance=as_enum(
                Provenance, data.get("provenance", Provenance.OBSERVED.value), r, "provenance"
            ),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


@dataclass(frozen=True)
class ScopeDimension:
    """A constraint on one scope axis.

    ``negated`` expresses "everywhere except these values", which policy text uses
    constantly ("except in California"). Keeping it as a flag rather than expanding
    to a complement set matters: the complement of a declared vocabulary is only
    knowable if the vocabulary is complete, and it usually is not.
    """

    name: str
    values: tuple[str, ...]
    negated: bool = False
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        if not self.values:
            raise SchemaError("a scope dimension must constrain at least one value")

    def applies_to(self, context_value: str | Iterable[str] | None) -> Applicability:
        """Test this dimension against a context value, three-valued."""
        if context_value is None:
            return None
        given = (
            frozenset({context_value})
            if isinstance(context_value, str)
            else frozenset(context_value)
        )
        if not given:
            return None
        hit = bool(given & frozenset(self.values))
        return (not hit) if self.negated else hit

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "name": self.name,
                "values": list(self.values),
                "negated": self.negated or None,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScopeDimension":
        r = "ScopeDimension"
        check_keys(data, r, ["name", "values"], ["negated", "evidence_ids"])
        negated = data.get("negated", False)
        if not isinstance(negated, bool):
            raise SchemaError(f"{r}.negated must be a boolean, got {negated!r}")
        return cls(
            name=as_str(data["name"], r, "name"),
            values=as_tuple_of_str(data["values"], r, "values"),
            negated=negated,
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )


def _provably_disjoint(left: ScopeDimension, right: ScopeDimension) -> bool:
    """True only when the two constraints on one axis cannot both hold."""
    left_values, right_values = frozenset(left.values), frozenset(right.values)
    if not left.negated and not right.negated:
        return not (left_values & right_values)
    if left.negated and right.negated:
        # Each admits everything outside its own set. Unless the axis vocabulary is
        # closed — which this model does not assume — some third value satisfies
        # both, so disjointness cannot be proven.
        return False
    positive, negative = (right, left) if left.negated else (left, right)
    # The positive set is entirely excluded by the negation.
    return frozenset(positive.values) <= frozenset(negative.values)


@dataclass(frozen=True)
class Scope:
    """A conjunction of dimension constraints. An empty scope applies everywhere."""

    dimensions: tuple[ScopeDimension, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimensions", tuple(self.dimensions))
        names = [dimension.name for dimension in self.dimensions]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise SchemaError(
                f"scope constrains {duplicates} more than once; combine the values "
                "into a single dimension so the constraint is unambiguous"
            )

    @property
    def is_universal(self) -> bool:
        return not self.dimensions

    def dimension(self, name: str) -> ScopeDimension | None:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(dimension.name for dimension in self.dimensions)

    def applies_to(self, context: Mapping[str, str | Iterable[str]]) -> Applicability:
        """Test the whole scope against a context, using Kleene conjunction.

        A definite ``False`` on any axis settles it; otherwise an unknown axis makes
        the answer unknown. This is the same three-valued discipline the expression
        evaluator uses, and for the same reason: "we were not told the state" must
        not read as "it does not apply here".
        """
        if self.is_universal:
            return True
        saw_unknown = False
        for dimension in self.dimensions:
            verdict = dimension.applies_to(context.get(dimension.name))
            if verdict is None:
                saw_unknown = True
            elif not verdict:
                return False
        return None if saw_unknown else True

    def overlaps(self, other: "Scope") -> bool:
        """False only when the two scopes provably cannot both apply.

        Only shared axes can prove disjointness: an axis one scope is silent about
        is unconstrained there, so it cannot separate them. As everywhere else, an
        unprovable case reports overlap, which costs coverage and protects
        correctness — two clauses that might both apply stay in conflict.
        """
        for dimension in self.dimensions:
            counterpart = other.dimension(dimension.name)
            if counterpart is not None and _provably_disjoint(dimension, counterpart):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {"dimensions": [dimension.to_dict() for dimension in self.dimensions]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scope":
        r = "Scope"
        check_keys(data, r, [], ["dimensions"])
        return cls(
            dimensions=as_tuple(
                data.get("dimensions", ()), r, "dimensions", ScopeDimension.from_dict
            )
        )


@dataclass(frozen=True)
class AuthoritySource:
    """A policy source, with a declared weight used only to break ties.

    ``authority_weight`` is **higher wins**. The values are configuration: a corpus
    declares that its statute outranks its regulation which outranks its bulletin.
    The engine never infers a hierarchy from a document's name or kind, because that
    inference is a legal judgement rather than a computation.

    ``kind`` is a free string on purpose — "statute", "regulation", "guide",
    "bulletin", "interpretive letter" and their equivalents differ by jurisdiction
    and industry, and a closed enum would encode one domain's vocabulary.
    """

    authority_id: str
    name: str
    authority_weight: int
    kind: str = ""
    parent_authority_id: str | None = None
    citation: str = ""
    effective_from: str | None = None
    effective_to: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def outranks(self, other: "AuthoritySource") -> bool:
        return self.authority_weight > other.authority_weight

    def to_dict(self) -> dict[str, Any]:
        return drop_none(
            {
                "authority_id": self.authority_id,
                "name": self.name,
                "authority_weight": self.authority_weight,
                "kind": self.kind or None,
                "parent_authority_id": self.parent_authority_id,
                "citation": self.citation or None,
                "effective_from": self.effective_from,
                "effective_to": self.effective_to,
                "evidence_ids": list(self.evidence_ids) or None,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthoritySource":
        r = "AuthoritySource"
        check_keys(
            data,
            r,
            ["authority_id", "name", "authority_weight"],
            [
                "kind",
                "parent_authority_id",
                "citation",
                "effective_from",
                "effective_to",
                "evidence_ids",
            ],
        )
        return cls(
            authority_id=as_str(data["authority_id"], r, "authority_id"),
            name=as_str(data["name"], r, "name"),
            authority_weight=as_int(data["authority_weight"], r, "authority_weight"),
            kind=data.get("kind", ""),
            parent_authority_id=data.get("parent_authority_id"),
            citation=data.get("citation", ""),
            effective_from=data.get("effective_from"),
            effective_to=data.get("effective_to"),
            evidence_ids=as_tuple_of_str(data.get("evidence_ids", ()), r, "evidence_ids"),
        )
