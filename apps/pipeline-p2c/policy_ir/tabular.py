"""Decomposing clause conditions into decision-table rows, and proving non-overlap.

Two jobs live here, and both exist to keep guesses out of the DMN compiler.

1. **Decomposition.** A decision table row can only express a conjunction of
   per-input constraints. This module either decomposes a clause condition into
   exactly that shape or reports that it cannot, in which case the decision is
   not table-compilable and is never emitted.

2. **The non-overlap proof.** ``hitPolicy="UNIQUE"`` is an assertion that no two
   rows can both match. The prover below only ever answers "provably disjoint"
   when it is certain; every uncertainty is reported as "may overlap", which
   costs coverage and protects correctness. That asymmetry is the whole point:
   the plan requires that overlapping rows without stated priority be rejected
   rather than quietly relabelled ``FIRST``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .enums import ORDERED_TYPES, DataType
from .scope import Scope
from .expressions import (
    All,
    Comparison,
    ComparisonOperator,
    Exists,
    Expression,
    In,
    Literal,
    Not,
    VariableRef,
)

_FLIPPED = {
    ComparisonOperator.LT: ComparisonOperator.GT,
    ComparisonOperator.LE: ComparisonOperator.GE,
    ComparisonOperator.GT: ComparisonOperator.LT,
    ComparisonOperator.GE: ComparisonOperator.LE,
    ComparisonOperator.EQ: ComparisonOperator.EQ,
    ComparisonOperator.NE: ComparisonOperator.NE,
}


class NotTabular(ValueError):
    """Raised when a condition cannot become a decision-table row."""


@dataclass(frozen=True)
class Atom:
    """One elementary constraint on a single input variable."""

    variable_id: str
    operator: ComparisonOperator | None
    literal: Literal | None = None
    members: tuple[Literal, ...] = ()
    negated: bool = False
    presence: bool = False

    @property
    def is_membership(self) -> bool:
        return bool(self.members)


def _atom_from(node: Expression, negated: bool = False) -> Atom:
    if isinstance(node, Not):
        return _atom_from(node.operand, not negated)
    if isinstance(node, Exists):
        return Atom(node.variable.data_definition_id, None, negated=negated, presence=True)
    if isinstance(node, In):
        if not isinstance(node.value, VariableRef):
            raise NotTabular("in() must test a variable reference to be tabular")
        return Atom(node.value.data_definition_id, None, members=node.allowed_values, negated=negated)
    if isinstance(node, Comparison):
        left, right, operator = node.left, node.right, node.operator
        if isinstance(right, VariableRef) and isinstance(left, Literal):
            left, right, operator = right, left, _FLIPPED[operator]
        if not isinstance(left, VariableRef) or not isinstance(right, Literal):
            raise NotTabular(
                "a tabular comparison must relate one variable to one literal"
            )
        return Atom(left.data_definition_id, operator, literal=right, negated=negated)
    raise NotTabular(f"{type(node).__name__} cannot appear in a decision-table row")


def flatten_conjunction(expression: Expression) -> tuple[Expression, ...]:
    """Flatten nested ``all()`` nodes into a single operand tuple."""
    if isinstance(expression, All):
        out: list[Expression] = []
        for operand in expression.operands:
            out.extend(flatten_conjunction(operand))
        return tuple(out)
    return (expression,)


def row_condition(condition: Expression, exception: Expression | None) -> Expression:
    """Fold a clause's exception into its condition.

    A decision-table row fires when the condition holds *and* the exception does
    not. Folding here rather than at emit time means the exception survives into
    the table, the overlap proof and the reference evaluator identically — the
    plan's "deduplication erases exception" and compound-clause tests both depend
    on the exception never being quietly dropped.
    """
    if exception is None:
        return condition
    return All((condition, Not(exception)))


#: Prefix that turns a scope axis into a decision-table input key. ``:`` cannot occur
#: in a data-definition ID (they are XML NCNames), so a scope axis can never collide
#: with a real variable.
SCOPE_INPUT_PREFIX = "scope:"


def scope_input_key(dimension_name: str) -> str:
    """The decision-table input key for a scope axis."""
    return f"{SCOPE_INPUT_PREFIX}{dimension_name}"


def is_scope_input(key: str) -> bool:
    return key.startswith(SCOPE_INPUT_PREFIX)


def scope_dimension_name(key: str) -> str:
    return key[len(SCOPE_INPUT_PREFIX) :]


def scope_atoms(scope: Scope) -> dict[str, tuple[Atom, ...]]:
    """Express a scope as decision-table atoms, one axis per input.

    This is what stops scope from being decorative. A rule limited to California and
    one limited to New York have overlapping credit-score bands, so on their ASTs
    alone the non-overlap proof fails and ``UNIQUE`` is refused. Treating the
    jurisdiction axis as another input lets the same prover see that the two rows
    can never both match — no special-casing, no separate code path.
    """
    return {
        scope_input_key(dimension.name): (
            Atom(
                variable_id=scope_input_key(dimension.name),
                operator=None,
                members=tuple(
                    Literal(value, DataType.STRING) for value in dimension.values
                ),
                negated=dimension.negated,
            ),
        )
        for dimension in scope.dimensions
    }


def decompose(expression: Expression) -> dict[str, tuple[Atom, ...]]:
    """Decompose a condition into per-variable atoms, or raise :class:`NotTabular`."""
    grouped: dict[str, list[Atom]] = {}
    for operand in flatten_conjunction(expression):
        atom = _atom_from(operand)
        grouped.setdefault(atom.variable_id, []).append(atom)
    return {key: tuple(value) for key, value in grouped.items()}


# ---------------------------------------------------------------------------
# Constraint domains, used only for the non-overlap proof
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Unconstrained:
    """The variable is not mentioned by this row."""


@dataclass(frozen=True)
class Allowed:
    """The variable must take one of a finite set of values."""

    values: frozenset


@dataclass(frozen=True)
class Excluded:
    """The variable must avoid a finite set of values."""

    values: frozenset


@dataclass(frozen=True)
class Range:
    """A one-dimensional interval over an ordered type."""

    lower: Any | None = None
    lower_closed: bool = True
    upper: Any | None = None
    upper_closed: bool = True

    def contains(self, value: Any) -> bool:
        if self.lower is not None:
            if value < self.lower or (value == self.lower and not self.lower_closed):
                return False
        if self.upper is not None:
            if value > self.upper or (value == self.upper and not self.upper_closed):
                return False
        return True


Constraint = Unconstrained | Allowed | Excluded | Range

#: Marker meaning "this row's constraint on this variable is not something the
#: prover models". Treated as possibly overlapping with everything.
OPAQUE = object()


def constraint_for(atoms: Iterable[Atom], data_type: DataType) -> Constraint | object:
    """Reduce a variable's atoms to a single constraint the prover understands."""
    lower: Any | None = None
    lower_closed = True
    upper: Any | None = None
    upper_closed = True
    allowed: frozenset | None = None
    excluded: set = set()
    saw_range = False

    for atom in atoms:
        if atom.presence:
            # exists()/not exists() is about absence, which the interval model
            # does not represent; refuse to reason about it.
            return OPAQUE
        if atom.is_membership:
            members = frozenset(m.native() for m in atom.members)
            if atom.negated:
                excluded |= members
            else:
                allowed = members if allowed is None else (allowed & members)
            continue
        if atom.operator is None or atom.literal is None:  # pragma: no cover - guarded above
            return OPAQUE
        value = atom.literal.native()
        operator = atom.operator
        if atom.negated:
            operator = {
                ComparisonOperator.EQ: ComparisonOperator.NE,
                ComparisonOperator.NE: ComparisonOperator.EQ,
                ComparisonOperator.LT: ComparisonOperator.GE,
                ComparisonOperator.GE: ComparisonOperator.LT,
                ComparisonOperator.LE: ComparisonOperator.GT,
                ComparisonOperator.GT: ComparisonOperator.LE,
            }[operator]
        if operator is ComparisonOperator.EQ:
            single = frozenset({value})
            allowed = single if allowed is None else (allowed & single)
        elif operator is ComparisonOperator.NE:
            excluded.add(value)
        elif data_type not in ORDERED_TYPES:
            return OPAQUE
        elif operator is ComparisonOperator.GE:
            saw_range = True
            if lower is None or value > lower:
                lower, lower_closed = value, True
        elif operator is ComparisonOperator.GT:
            saw_range = True
            if lower is None or value >= lower:
                lower, lower_closed = value, False
        elif operator is ComparisonOperator.LE:
            saw_range = True
            if upper is None or value < upper:
                upper, upper_closed = value, True
        else:  # ComparisonOperator.LT
            saw_range = True
            if upper is None or value <= upper:
                upper, upper_closed = value, False

    if allowed is not None:
        remaining = allowed - excluded
        if saw_range:
            span = Range(lower, lower_closed, upper, upper_closed)
            remaining = frozenset(v for v in remaining if span.contains(v))
        return Allowed(remaining)
    if saw_range:
        if excluded:
            # A range minus points is representable but the prover would have to
            # reason about punctured intervals; stay conservative instead.
            return OPAQUE
        return Range(lower, lower_closed, upper, upper_closed)
    if excluded:
        return Excluded(frozenset(excluded))
    return Unconstrained()


def _ranges_intersect(a: Range, b: Range) -> bool:
    lower, lower_closed = a.lower, a.lower_closed
    if b.lower is not None and (lower is None or b.lower > lower):
        lower, lower_closed = b.lower, b.lower_closed
    elif b.lower is not None and b.lower == lower:
        lower_closed = lower_closed and b.lower_closed
    upper, upper_closed = a.upper, a.upper_closed
    if b.upper is not None and (upper is None or b.upper < upper):
        upper, upper_closed = b.upper, b.upper_closed
    elif b.upper is not None and b.upper == upper:
        upper_closed = upper_closed and b.upper_closed
    if lower is None or upper is None:
        return True
    if lower < upper:
        return True
    return lower == upper and lower_closed and upper_closed


def constraints_may_overlap(
    left: Constraint | object, right: Constraint | object, data_type: DataType
) -> bool:
    """Return ``False`` only when the two constraints are *provably* disjoint."""
    if left is OPAQUE or right is OPAQUE:
        return True
    if isinstance(left, Unconstrained) or isinstance(right, Unconstrained):
        return True
    if isinstance(left, Allowed) and isinstance(right, Allowed):
        return bool(left.values & right.values)
    if isinstance(left, Allowed) and isinstance(right, Excluded):
        return bool(left.values - right.values)
    if isinstance(left, Excluded) and isinstance(right, Allowed):
        return bool(right.values - left.values)
    if isinstance(left, Allowed) and isinstance(right, Range):
        return any(right.contains(v) for v in left.values)
    if isinstance(left, Range) and isinstance(right, Allowed):
        return any(left.contains(v) for v in right.values)
    if isinstance(left, Range) and isinstance(right, Range):
        return _ranges_intersect(left, right)
    if isinstance(left, Excluded) and isinstance(right, Excluded):
        if data_type is DataType.BOOLEAN:
            return bool({True, False} - left.values - right.values)
        return True
    # Excluded against Range: only provably disjoint when the range collapses to
    # a single excluded point.
    excluded, span = (left, right) if isinstance(left, Excluded) else (right, left)
    if (
        isinstance(span, Range)
        and span.lower is not None
        and span.lower == span.upper
        and span.lower_closed
        and span.upper_closed
    ):
        return span.lower not in excluded.values
    return True


@dataclass(frozen=True)
class Row:
    """A decomposed decision-table row."""

    clause_id: str
    atoms: Mapping[str, tuple[Atom, ...]]


@dataclass(frozen=True)
class OverlapProof:
    """Whether the rows are provably pairwise disjoint, and where they are not."""

    disjoint: bool
    overlapping_pairs: tuple[tuple[str, str], ...] = ()


def prove_disjoint(
    rows: Iterable[Row], types: Mapping[str, DataType], inputs: Iterable[str]
) -> OverlapProof:
    """Attempt to prove that no two rows can match the same input vector.

    Two rows are disjoint when *some* input's constraints cannot both hold. If no
    such input exists for a pair, that pair is reported as possibly overlapping
    and ``UNIQUE`` must not be emitted.
    """
    input_ids = tuple(inputs)
    rows = list(rows)
    constraints: list[dict[str, Constraint | object]] = []
    for row in rows:
        per_variable: dict[str, Constraint | object] = {}
        for variable_id in input_ids:
            atoms = row.atoms.get(variable_id, ())
            data_type = types.get(variable_id)
            if data_type is None:
                per_variable[variable_id] = OPAQUE
            else:
                per_variable[variable_id] = constraint_for(atoms, data_type)
        constraints.append(per_variable)

    overlapping: list[tuple[str, str]] = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            disjoint_here = False
            for variable_id in input_ids:
                data_type = types.get(variable_id, DataType.STRING)
                if not constraints_may_overlap(
                    constraints[i][variable_id], constraints[j][variable_id], data_type
                ):
                    disjoint_here = True
                    break
            if not disjoint_here:
                overlapping.append((rows[i].clause_id, rows[j].clause_id))
    return OverlapProof(not overlapping, tuple(overlapping))
