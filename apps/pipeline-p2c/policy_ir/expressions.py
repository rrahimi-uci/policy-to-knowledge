"""The restricted expression AST.

The plan forbids a model from emitting raw FEEL, SQL, XML or code. Instead a
model may only propose nodes from this closed grammar, and deterministic code
type-checks the tree and serialises it. Every node is immutable and hashable so
that canonicalisation and byte-stable output are possible.

Grammar::

    Expression =
        all(expressions)
      | any(expressions)
      | not(expression)
      | comparison(left, operator, right)
      | in(value, allowed_values)
      | exists(variable)
      | date_arithmetic(base, operator, duration)
      | variable_ref(data_definition_id)
      | literal(value, type, unit)
      | function_ref(function_id, arguments)
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

from .enums import DataType, StrEnum


class ExpressionError(ValueError):
    """Raised when an expression cannot be built, parsed or interpreted."""


class ComparisonOperator(StrEnum):
    """The only comparison operators the grammar admits."""

    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


#: Operators that require an ordered operand type.
ORDERING_OPERATORS = frozenset(
    {
        ComparisonOperator.LT,
        ComparisonOperator.LE,
        ComparisonOperator.GT,
        ComparisonOperator.GE,
    }
)


class DateOperator(StrEnum):
    """Additive operators permitted in ``date_arithmetic``."""

    PLUS = "+"
    MINUS = "-"


class Calendar(StrEnum):
    """How a duration counts days.

    ``business_days`` is a distinct unit from ``calendar_days``: the plan's
    numeric-drift stress test requires that turning "5 days" into "5 business
    days" either changes the compiled semantics or blocks compilation, so the
    two never silently unify.
    """

    CALENDAR_DAYS = "calendar_days"
    BUSINESS_DAYS = "business_days"


_DURATION_RE = re.compile(
    r"^P(?!$)(?:(?P<weeks>\d+(?:\.\d+)?)W)?(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?!$)(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

_YEAR_MONTH_DURATION_RE = re.compile(r"^P(?:\d+Y)?(?:\d+M)?$")


def parse_duration(text: str) -> _dt.timedelta:
    """Parse the days-and-time ISO 8601 duration subset this compiler supports.

    Year/month durations are rejected rather than approximated: FEEL treats them
    as a separate type whose arithmetic is calendar-dependent, and silently
    guessing "1 month = 30 days" is exactly the kind of drift the evidence gate
    exists to prevent.
    """
    if not isinstance(text, str):
        raise ExpressionError(f"duration must be a string, got {type(text).__name__}")
    if _YEAR_MONTH_DURATION_RE.match(text) and text != "P":
        raise ExpressionError(
            f"year/month duration {text!r} is not supported; express the deadline "
            "in days, weeks or time units"
        )
    match = _DURATION_RE.match(text)
    if not match:
        raise ExpressionError(f"not an ISO 8601 days-and-time duration: {text!r}")
    parts = {k: float(v) for k, v in match.groupdict().items() if v is not None}
    if not parts:
        raise ExpressionError(f"duration {text!r} carries no components")
    return _dt.timedelta(
        weeks=parts.get("weeks", 0.0),
        days=parts.get("days", 0.0),
        hours=parts.get("hours", 0.0),
        minutes=parts.get("minutes", 0.0),
        seconds=parts.get("seconds", 0.0),
    )


def format_duration(delta: _dt.timedelta) -> str:
    """Render a timedelta as a canonical ``PnDTnHnMnS`` string."""
    total = int(delta.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    out = f"{sign}P{days}D"
    if hours or minutes or seconds:
        out += "T"
        if hours:
            out += f"{hours}H"
        if minutes:
            out += f"{minutes}M"
        if seconds:
            out += f"{seconds}S"
    return out


def parse_date(text: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ExpressionError(f"not an ISO 8601 date: {text!r}") from exc


def parse_date_time(text: str) -> _dt.datetime:
    try:
        return _dt.datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ExpressionError(f"not an ISO 8601 date-time: {text!r}") from exc


def parse_time(text: str) -> _dt.time:
    try:
        return _dt.time.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ExpressionError(f"not an ISO 8601 time: {text!r}") from exc


@dataclass(frozen=True)
class Expression:
    """Base class for every AST node."""

    #: Discriminator used in the serialised form.
    kind: str = field(init=False, default="", repr=False)

    def children(self) -> tuple["Expression", ...]:
        return ()

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError

    def walk(self) -> Iterator["Expression"]:
        """Yield this node and every descendant, parents before children."""
        yield self
        for child in self.children():
            yield from child.walk()


@dataclass(frozen=True)
class VariableRef(Expression):
    """A reference to a declared :class:`~policy_ir.models.DataDefinition`."""

    data_definition_id: str
    kind: str = field(init=False, default="variable_ref", repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "data_definition_id": self.data_definition_id}


@dataclass(frozen=True)
class Literal(Expression):
    """A typed constant.

    ``value`` is always stored in its JSON-safe form (ISO strings for temporal
    types) so that serialisation is lossless and byte-stable; call
    :meth:`native` for the Python value.
    """

    value: Any
    type: DataType
    unit: str | None = None
    kind: str = field(init=False, default="literal", repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.value, list):
            object.__setattr__(self, "value", tuple(self.value))
        # Validate eagerly: a literal that cannot be interpreted must never
        # reach the type checker, let alone a compiler.
        self.native()

    def native(self) -> Any:
        """Return the Python value this literal denotes."""
        if self.type is DataType.NUMBER:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ExpressionError(f"number literal must be numeric, got {self.value!r}")
            return self.value
        if self.type is DataType.BOOLEAN:
            if not isinstance(self.value, bool):
                raise ExpressionError(f"boolean literal must be a bool, got {self.value!r}")
            return self.value
        if self.type is DataType.STRING:
            if not isinstance(self.value, str):
                raise ExpressionError(f"string literal must be a str, got {self.value!r}")
            return self.value
        if self.type is DataType.DATE:
            return parse_date(self.value)
        if self.type is DataType.DATE_TIME:
            return parse_date_time(self.value)
        if self.type is DataType.TIME:
            return parse_time(self.value)
        if self.type is DataType.DURATION:
            return parse_duration(self.value)
        if self.type is DataType.LIST:
            if not isinstance(self.value, tuple):
                raise ExpressionError(f"list literal must be a sequence, got {self.value!r}")
            return list(self.value)
        if self.type is DataType.CONTEXT:
            if not isinstance(self.value, Mapping):
                raise ExpressionError(f"context literal must be a mapping, got {self.value!r}")
            return dict(self.value)
        raise ExpressionError(f"unsupported literal type {self.type!r}")

    def to_dict(self) -> dict[str, Any]:
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        out: dict[str, Any] = {"kind": self.kind, "value": value, "type": self.type.value}
        if self.unit is not None:
            out["unit"] = self.unit
        return out


@dataclass(frozen=True)
class All(Expression):
    """Conjunction. Empty conjunctions are rejected as meaningless."""

    operands: tuple[Expression, ...]
    kind: str = field(init=False, default="all", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operands", tuple(self.operands))
        if not self.operands:
            raise ExpressionError("all() requires at least one operand")

    def children(self) -> tuple[Expression, ...]:
        return self.operands

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "operands": [o.to_dict() for o in self.operands]}


@dataclass(frozen=True)
class Any_(Expression):
    """Disjunction. Named ``Any_`` to avoid shadowing :data:`typing.Any`."""

    operands: tuple[Expression, ...]
    kind: str = field(init=False, default="any", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operands", tuple(self.operands))
        if not self.operands:
            raise ExpressionError("any() requires at least one operand")

    def children(self) -> tuple[Expression, ...]:
        return self.operands

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "operands": [o.to_dict() for o in self.operands]}


@dataclass(frozen=True)
class Not(Expression):
    """Negation. Kept as an explicit node so polarity survives every rewrite."""

    operand: Expression
    kind: str = field(init=False, default="not", repr=False)

    def children(self) -> tuple[Expression, ...]:
        return (self.operand,)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "operand": self.operand.to_dict()}


@dataclass(frozen=True)
class Comparison(Expression):
    """A binary comparison between two typed operands."""

    left: Expression
    operator: ComparisonOperator
    right: Expression
    kind: str = field(init=False, default="comparison", repr=False)

    def children(self) -> tuple[Expression, ...]:
        return (self.left, self.right)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "left": self.left.to_dict(),
            "operator": self.operator.value,
            "right": self.right.to_dict(),
        }


@dataclass(frozen=True)
class In(Expression):
    """Set membership against an explicit list of literals."""

    value: Expression
    allowed_values: tuple[Literal, ...]
    kind: str = field(init=False, default="in", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_values", tuple(self.allowed_values))
        if not self.allowed_values:
            raise ExpressionError("in() requires at least one allowed value")
        for item in self.allowed_values:
            if not isinstance(item, Literal):
                raise ExpressionError("in() allowed_values must all be literals")

    def children(self) -> tuple[Expression, ...]:
        return (self.value, *self.allowed_values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value.to_dict(),
            "allowed_values": [v.to_dict() for v in self.allowed_values],
        }


@dataclass(frozen=True)
class Exists(Expression):
    """True when a variable has a value; the explicit form of a presence test."""

    variable: VariableRef
    kind: str = field(init=False, default="exists", repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.variable, VariableRef):
            raise ExpressionError("exists() takes a variable reference")

    def children(self) -> tuple[Expression, ...]:
        return (self.variable,)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "variable": self.variable.to_dict()}


@dataclass(frozen=True)
class DateArithmetic(Expression):
    """``base ± duration``, yielding a date or date-time."""

    base: Expression
    operator: DateOperator
    duration: Expression
    calendar: Calendar = Calendar.CALENDAR_DAYS
    kind: str = field(init=False, default="date_arithmetic", repr=False)

    def children(self) -> tuple[Expression, ...]:
        return (self.base, self.duration)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "base": self.base.to_dict(),
            "operator": self.operator.value,
            "duration": self.duration.to_dict(),
            "calendar": self.calendar.value,
        }


@dataclass(frozen=True)
class FunctionRef(Expression):
    """A call to a declared, deterministic function.

    Functions must be declared in the IR with a typed signature; the grammar has
    no way to define a function body, which keeps model-authored code out.
    """

    function_id: str
    arguments: tuple[Expression, ...] = ()
    kind: str = field(init=False, default="function_ref", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))

    def children(self) -> tuple[Expression, ...]:
        return self.arguments

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "function_id": self.function_id,
            "arguments": [a.to_dict() for a in self.arguments],
        }


_BUILDERS: dict[str, Any] = {}


def expression_from_dict(data: Mapping[str, Any]) -> Expression:
    """Rebuild an expression from its serialised form.

    Unknown node kinds and unknown keys are rejected rather than ignored, so a
    model cannot smuggle an unsupported construct past the parser.
    """
    if not isinstance(data, Mapping):
        raise ExpressionError(f"expression must be an object, got {type(data).__name__}")
    kind = data.get("kind")
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ExpressionError(f"unknown expression kind {kind!r}")
    return builder(data)


def _keys(data: Mapping[str, Any], required: Sequence[str], optional: Sequence[str] = ()) -> None:
    allowed = {"kind", *required, *optional}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ExpressionError(f"unknown key(s) {unknown} for expression kind {data['kind']!r}")
    missing = sorted(k for k in required if k not in data)
    if missing:
        raise ExpressionError(f"missing key(s) {missing} for expression kind {data['kind']!r}")


def _build_variable_ref(data: Mapping[str, Any]) -> VariableRef:
    _keys(data, ["data_definition_id"])
    return VariableRef(data_definition_id=str(data["data_definition_id"]))


def _build_literal(data: Mapping[str, Any]) -> Literal:
    _keys(data, ["value", "type"], ["unit"])
    return Literal(value=data["value"], type=DataType(data["type"]), unit=data.get("unit"))


def _build_all(data: Mapping[str, Any]) -> All:
    _keys(data, ["operands"])
    return All(operands=tuple(expression_from_dict(o) for o in data["operands"]))


def _build_any(data: Mapping[str, Any]) -> Any_:
    _keys(data, ["operands"])
    return Any_(operands=tuple(expression_from_dict(o) for o in data["operands"]))


def _build_not(data: Mapping[str, Any]) -> Not:
    _keys(data, ["operand"])
    return Not(operand=expression_from_dict(data["operand"]))


def _build_comparison(data: Mapping[str, Any]) -> Comparison:
    _keys(data, ["left", "operator", "right"])
    return Comparison(
        left=expression_from_dict(data["left"]),
        operator=ComparisonOperator(data["operator"]),
        right=expression_from_dict(data["right"]),
    )


def _build_in(data: Mapping[str, Any]) -> In:
    _keys(data, ["value", "allowed_values"])
    values = tuple(expression_from_dict(v) for v in data["allowed_values"])
    return In(value=expression_from_dict(data["value"]), allowed_values=values)  # type: ignore[arg-type]


def _build_exists(data: Mapping[str, Any]) -> Exists:
    _keys(data, ["variable"])
    return Exists(variable=expression_from_dict(data["variable"]))  # type: ignore[arg-type]


def _build_date_arithmetic(data: Mapping[str, Any]) -> DateArithmetic:
    _keys(data, ["base", "operator", "duration"], ["calendar"])
    return DateArithmetic(
        base=expression_from_dict(data["base"]),
        operator=DateOperator(data["operator"]),
        duration=expression_from_dict(data["duration"]),
        calendar=Calendar(data.get("calendar", Calendar.CALENDAR_DAYS.value)),
    )


def _build_function_ref(data: Mapping[str, Any]) -> FunctionRef:
    _keys(data, ["function_id"], ["arguments"])
    return FunctionRef(
        function_id=str(data["function_id"]),
        arguments=tuple(expression_from_dict(a) for a in data.get("arguments", ())),
    )


_BUILDERS.update(
    {
        "variable_ref": _build_variable_ref,
        "literal": _build_literal,
        "all": _build_all,
        "any": _build_any,
        "not": _build_not,
        "comparison": _build_comparison,
        "in": _build_in,
        "exists": _build_exists,
        "date_arithmetic": _build_date_arithmetic,
        "function_ref": _build_function_ref,
    }
)


def iter_variables(expression: Expression) -> Iterator[VariableRef]:
    """Yield every variable reference in the tree, in document order."""
    for node in expression.walk():
        if isinstance(node, VariableRef):
            yield node


def iter_literals(expression: Expression) -> Iterator[Literal]:
    """Yield every literal in the tree, in document order."""
    for node in expression.walk():
        if isinstance(node, Literal):
            yield node


def referenced_variable_ids(expression: Expression) -> tuple[str, ...]:
    """Return the distinct data-definition IDs the expression reads, sorted."""
    return tuple(sorted({v.data_definition_id for v in iter_variables(expression)}))
