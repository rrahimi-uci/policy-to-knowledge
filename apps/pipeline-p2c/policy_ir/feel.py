"""FEEL serialisation, and an independent FEEL unary-test reader.

Two directions, on purpose:

* :func:`to_feel` and :func:`unary_test` render a *validated* AST as FEEL. A model
  never writes FEEL; only this module does, from a tree the type checker has
  already accepted.
* :func:`parse_unary_test` reads FEEL unary tests back into values and
  predicates. That gives the test suite a second, independent route to a
  decision's meaning: compile the IR to XML, read the XML's FEEL back, evaluate
  it, and compare against the Policy IR evaluator. A bug in the serialiser shows
  up as a disagreement rather than as two matching wrong answers, which a
  round-trip through the same code path would hide.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .enums import DataType
from .expressions import (
    All,
    Any_,
    Calendar,
    Comparison,
    ComparisonOperator,
    DateArithmetic,
    DateOperator,
    Exists,
    Expression,
    FunctionRef,
    In,
    Literal,
    Not,
    VariableRef,
)
from .ids import ncname

from .tabular import Atom, NotTabular


class FeelError(ValueError):
    """Raised when an AST cannot be expressed in portable FEEL."""


def feel_name(name: str) -> str:
    """Sanitise a display name into a single-token FEEL name.

    FEEL permits spaces in names, but a name like ``credit score`` forces every
    consumer to disambiguate it from an expression. A single token keeps both the
    emitted XML and the reader here unambiguous.
    """
    return ncname(name.strip().replace(" ", "_"), fallback="value")


def _number(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    if value == int(value):
        return str(int(value))
    return repr(value)


def _string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


def literal_to_feel(node: Literal) -> str:
    """Render a typed literal as a FEEL constant."""
    if node.type is DataType.NUMBER:
        return _number(node.value)
    if node.type is DataType.BOOLEAN:
        return "true" if node.value else "false"
    if node.type is DataType.STRING:
        return _string(node.value)
    if node.type is DataType.DATE:
        return f'date("{node.value}")'
    if node.type is DataType.TIME:
        return f'time("{node.value}")'
    if node.type is DataType.DATE_TIME:
        return f'date and time("{node.value}")'
    if node.type is DataType.DURATION:
        return f'duration("{node.value}")'
    if node.type is DataType.LIST:
        return "[" + ", ".join(literal_to_feel(Literal(v, _infer(v))) for v in node.value) + "]"
    raise FeelError(f"cannot render a {node.type} literal as FEEL")


def _infer(value: Any) -> DataType:
    if isinstance(value, bool):
        return DataType.BOOLEAN
    if isinstance(value, (int, float)):
        return DataType.NUMBER
    if isinstance(value, str):
        return DataType.STRING
    raise FeelError(f"cannot infer a FEEL type for {value!r}")


def to_feel(expression: Expression, names: Mapping[str, str]) -> str:
    """Render a boolean or value expression as a FEEL expression."""
    if isinstance(expression, Literal):
        return literal_to_feel(expression)
    if isinstance(expression, VariableRef):
        try:
            return names[expression.data_definition_id]
        except KeyError as exc:
            raise FeelError(
                f"no FEEL name for data definition {expression.data_definition_id!r}"
            ) from exc
    if isinstance(expression, All):
        return "(" + " and ".join(to_feel(o, names) for o in expression.operands) + ")"
    if isinstance(expression, Any_):
        return "(" + " or ".join(to_feel(o, names) for o in expression.operands) + ")"
    if isinstance(expression, Not):
        return f"not({to_feel(expression.operand, names)})"
    if isinstance(expression, Comparison):
        left = to_feel(expression.left, names)
        right = to_feel(expression.right, names)
        return f"{left} {expression.operator.value} {right}"
    if isinstance(expression, In):
        members = ", ".join(literal_to_feel(m) for m in expression.allowed_values)
        return f"{to_feel(expression.value, names)} in ({members})"
    if isinstance(expression, Exists):
        return f"{to_feel(expression.variable, names)} != null"
    if isinstance(expression, DateArithmetic):
        if expression.calendar is Calendar.BUSINESS_DAYS:
            raise FeelError(
                "business-day arithmetic has no portable FEEL form; declare a "
                "deterministic function instead of compiling it"
            )
        operator = "+" if expression.operator is DateOperator.PLUS else "-"
        base = to_feel(expression.base, names)
        duration = to_feel(expression.duration, names)
        return f"({base} {operator} {duration})"
    if isinstance(expression, FunctionRef):
        arguments = ", ".join(to_feel(a, names) for a in expression.arguments)
        return f"{feel_name(expression.function_id)}({arguments})"
    raise FeelError(f"cannot render {type(expression).__name__} as FEEL")


_RANGE_LOWER = {ComparisonOperator.GE: True, ComparisonOperator.GT: False}
_RANGE_UPPER = {ComparisonOperator.LE: True, ComparisonOperator.LT: False}


def unary_test(atoms: Sequence[Atom]) -> str:
    """Render one variable's atoms as a DMN input entry.

    Returns ``"-"`` for an unconstrained input. Raises :class:`NotTabular` when
    the atoms cannot be expressed as a single unary test, which keeps the caller
    from inventing a shape the standard does not have.
    """
    if not atoms:
        return "-"
    if len(atoms) == 1:
        return _single_unary_test(atoms[0])
    if len(atoms) == 2:
        return _range_unary_test(atoms[0], atoms[1])
    raise NotTabular(
        f"{len(atoms)} constraints on one input cannot form a single unary test"
    )


def _single_unary_test(atom: Atom) -> str:
    if atom.presence:
        return "not(null)" if not atom.negated else "null"
    if atom.is_membership:
        members = ", ".join(literal_to_feel(m) for m in atom.members)
        return f"not({members})" if atom.negated else members
    if atom.literal is None or atom.operator is None:  # pragma: no cover - guarded upstream
        raise NotTabular("incomplete atom")
    value = literal_to_feel(atom.literal)
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
        return value
    if operator is ComparisonOperator.NE:
        return f"not({value})"
    return f"{operator.value} {value}"


def _range_unary_test(first: Atom, second: Atom) -> str:
    if first.negated or second.negated or first.is_membership or second.is_membership:
        raise NotTabular("only two plain comparisons can form an interval unary test")
    if first.operator is None or second.operator is None:
        raise NotTabular("only two plain comparisons can form an interval unary test")
    lower_atom = upper_atom = None
    for atom in (first, second):
        if atom.operator in _RANGE_LOWER:
            lower_atom = atom
        elif atom.operator in _RANGE_UPPER:
            upper_atom = atom
    if lower_atom is None or upper_atom is None:
        raise NotTabular("an interval needs one lower and one upper bound")
    open_bracket = "[" if _RANGE_LOWER[lower_atom.operator] else "("
    close_bracket = "]" if _RANGE_UPPER[upper_atom.operator] else ")"
    low = literal_to_feel(lower_atom.literal)  # type: ignore[arg-type]
    high = literal_to_feel(upper_atom.literal)  # type: ignore[arg-type]
    return f"{open_bracket}{low}..{high}{close_bracket}"


# ---------------------------------------------------------------------------
# The independent reader
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_CALL_RE = re.compile(r'^(date and time|date|time|duration)\(\s*"([^"]*)"\s*\)$')
_STRING_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"$')
_INTERVAL_RE = re.compile(r"^([\[\(])(.+?)\.\.(.+?)([\]\)])$")
_COMPARISON_RE = re.compile(r"^(>=|<=|>|<)\s*(.+)$")

_UNESCAPE = {"\\n": "\n", "\\r": "\r", "\\t": "\t", '\\"': '"', "\\\\": "\\"}


def parse_feel_value(text: str) -> Any:
    """Parse a FEEL constant back into a Python value."""
    text = text.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if _NUMBER_RE.match(text):
        return float(text) if "." in text else int(text)
    match = _STRING_RE.match(text)
    if match:
        body = match.group(1)
        for escaped, raw in _UNESCAPE.items():
            body = body.replace(escaped, raw)
        return body
    match = _CALL_RE.match(text)
    if match:
        kind, payload = match.group(1), match.group(2)
        if kind == "date":
            return _dt.date.fromisoformat(payload)
        if kind == "time":
            return _dt.time.fromisoformat(payload)
        if kind == "date and time":
            return _dt.datetime.fromisoformat(payload)
        from policy_ir.expressions import parse_duration

        return parse_duration(payload)
    raise FeelError(f"cannot parse FEEL value {text!r}")


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    in_string = False
    current: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            current.append(char)
            if char == "\\" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            current.append(char)
        elif char in "([":
            depth += 1
            current.append(char)
        elif char in ")]":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _test_for(item: str) -> Callable[[Any], bool]:
    match = _INTERVAL_RE.match(item)
    if match:
        open_bracket, low_text, high_text, close_bracket = match.groups()
        low = parse_feel_value(low_text)
        high = parse_feel_value(high_text)
        lower_closed = open_bracket == "["
        upper_closed = close_bracket == "]"

        def interval(value: Any) -> bool:
            if value is None:
                return False
            if lower_closed and value < low:
                return False
            if not lower_closed and value <= low:
                return False
            if upper_closed and value > high:
                return False
            if not upper_closed and value >= high:
                return False
            return True

        return interval

    match = _COMPARISON_RE.match(item)
    if match:
        operator, value_text = match.groups()
        bound = parse_feel_value(value_text)
        operations: dict[str, Callable[[Any], bool]] = {
            ">=": lambda v: v is not None and v >= bound,
            "<=": lambda v: v is not None and v <= bound,
            ">": lambda v: v is not None and v > bound,
            "<": lambda v: v is not None and v < bound,
        }
        return operations[operator]

    expected = parse_feel_value(item)
    return lambda value: value == expected


@dataclass(frozen=True)
class UnaryTest:
    """A parsed DMN input entry, evaluable against a single value."""

    text: str
    always_true: bool
    negated: bool
    tests: tuple[Callable[[Any], bool], ...]

    def matches(self, value: Any) -> bool:
        if self.always_true:
            return True
        hit = any(test(value) for test in self.tests)
        return (not hit) if self.negated else hit


def parse_unary_test(text: str) -> UnaryTest:
    """Parse the DMN unary-test subset this compiler emits."""
    stripped = text.strip()
    if stripped in ("-", ""):
        return UnaryTest(stripped, True, False, ())
    negated = False
    if stripped.startswith("not(") and stripped.endswith(")"):
        negated = True
        stripped = stripped[4:-1].strip()
    items = _split_top_level(stripped)
    if not items:
        raise FeelError(f"empty unary test {text!r}")
    return UnaryTest(text.strip(), False, negated, tuple(_test_for(item) for item in items))
