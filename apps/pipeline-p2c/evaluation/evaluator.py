"""The reference Policy IR evaluator.

This is the semantic yardstick for the whole app. The DMN compiler is only
trusted when an *independent* path — parse the emitted XML, parse its FEEL unary
tests, evaluate the table — agrees with this evaluator on the conformance
fixtures. If the two disagree, the compiler is wrong, not the evaluator.

Missing values are ``UNKNOWN`` rather than false, and unknown propagates through
Kleene three-valued logic. Collapsing unknown into false is the single easiest
way to turn "we have no income figure" into "the applicant is ineligible", which
would be an unsupported decision dressed up as a supported one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Mapping

from policy_ir.enums import NullPolicy
from policy_ir.expressions import (
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
from policy_ir.models import DataDefinition, PolicyIR, UnitConversion


class EvaluationError(ValueError):
    """Raised when an expression cannot be evaluated deterministically."""


class _Unknown:
    """The third truth value, distinct from ``None`` as a legitimate datum."""

    _instance: "_Unknown | None" = None

    def __new__(cls) -> "_Unknown":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNKNOWN"

    def __bool__(self) -> bool:
        raise EvaluationError("UNKNOWN has no truth value; handle it explicitly")


#: Sentinel for "not known", used for both absent inputs and undecidable results.
UNKNOWN = _Unknown()


def _is_unknown(value: Any) -> bool:
    return value is UNKNOWN


@dataclass(frozen=True)
class EvaluationContext:
    """Inputs and declarations for one evaluation.

    ``holidays`` is only consulted for ``business_days`` durations. Business-day
    arithmetic is defined here as "Monday to Friday, minus the supplied holiday
    dates" — stated explicitly because a business day is a policy choice, not a
    fact, and a compiler that guessed it would be inventing semantics.
    """

    values: Mapping[str, Any] = field(default_factory=dict)
    data_definitions: Mapping[str, DataDefinition] = field(default_factory=dict)
    functions: Mapping[str, Any] = field(default_factory=dict)
    conversions: Mapping[tuple[str, str], UnitConversion] = field(default_factory=dict)
    holidays: frozenset[_dt.date] = frozenset()

    @classmethod
    def for_ir(
        cls,
        ir: PolicyIR,
        values: Mapping[str, Any],
        *,
        functions: Mapping[str, Any] | None = None,
        holidays: frozenset[_dt.date] = frozenset(),
    ) -> "EvaluationContext":
        return cls(
            values=dict(values),
            data_definitions=ir.data_definition_index(),
            functions=dict(functions or {}),
            conversions=ir.conversion_index(),
            holidays=holidays,
        )

    def lookup(self, data_definition_id: str) -> Any:
        """Resolve a variable, applying the declared null policy when absent."""
        if data_definition_id in self.values:
            value = self.values[data_definition_id]
            return UNKNOWN if value is None else value
        definition = self.data_definitions.get(data_definition_id)
        if definition is None:
            raise EvaluationError(f"unknown data definition {data_definition_id!r}")
        if definition.null_policy is NullPolicy.DEFAULT_VALUE:
            if definition.default_value is None:
                raise EvaluationError(
                    f"{data_definition_id!r} declares DEFAULT_VALUE but defines no default"
                )
            return definition.default_value.native()
        if definition.null_policy is NullPolicy.REJECT:
            raise EvaluationError(f"required input {data_definition_id!r} is missing")
        return UNKNOWN


def _convert(value: float, from_unit: str | None, to_unit: str | None, context: EvaluationContext) -> float:
    if from_unit == to_unit or from_unit is None or to_unit is None:
        return value
    direct = context.conversions.get((from_unit, to_unit))
    if direct is not None:
        return value * direct.factor
    inverse = context.conversions.get((to_unit, from_unit))
    if inverse is not None:
        if inverse.factor == 0:
            raise EvaluationError(f"unit conversion {to_unit}->{from_unit} has a zero factor")
        return value / inverse.factor
    raise EvaluationError(f"no declared conversion between {from_unit!r} and {to_unit!r}")


def _unit_of(node: Expression, context: EvaluationContext) -> str | None:
    if isinstance(node, Literal):
        return node.unit
    if isinstance(node, VariableRef):
        definition = context.data_definitions.get(node.data_definition_id)
        return definition.unit if definition else None
    return None


def _add_business_days(base: _dt.date, days: int, context: EvaluationContext) -> _dt.date:
    step = 1 if days >= 0 else -1
    remaining = abs(days)
    current = base
    while remaining:
        current += _dt.timedelta(days=step)
        if current.weekday() < 5 and current not in context.holidays:
            remaining -= 1
    return current


def evaluate(expression: Expression, context: EvaluationContext) -> Any:
    """Evaluate an expression, returning a value, a bool, or :data:`UNKNOWN`."""
    if isinstance(expression, Literal):
        return expression.native()
    if isinstance(expression, VariableRef):
        return context.lookup(expression.data_definition_id)
    if isinstance(expression, All):
        return _evaluate_all(expression, context)
    if isinstance(expression, Any_):
        return _evaluate_any(expression, context)
    if isinstance(expression, Not):
        inner = evaluate(expression.operand, context)
        return UNKNOWN if _is_unknown(inner) else (not inner)
    if isinstance(expression, Comparison):
        return _evaluate_comparison(expression, context)
    if isinstance(expression, In):
        return _evaluate_in(expression, context)
    if isinstance(expression, Exists):
        return not _is_unknown(context.lookup(expression.variable.data_definition_id))
    if isinstance(expression, DateArithmetic):
        return _evaluate_date_arithmetic(expression, context)
    if isinstance(expression, FunctionRef):
        return _evaluate_function(expression, context)
    raise EvaluationError(f"cannot evaluate node {type(expression).__name__}")


def _evaluate_all(node: All, context: EvaluationContext) -> Any:
    saw_unknown = False
    for operand in node.operands:
        value = evaluate(operand, context)
        if _is_unknown(value):
            saw_unknown = True
        elif not value:
            return False
    return UNKNOWN if saw_unknown else True


def _evaluate_any(node: Any_, context: EvaluationContext) -> Any:
    saw_unknown = False
    for operand in node.operands:
        value = evaluate(operand, context)
        if _is_unknown(value):
            saw_unknown = True
        elif value:
            return True
    return UNKNOWN if saw_unknown else False


def _evaluate_comparison(node: Comparison, context: EvaluationContext) -> Any:
    left = evaluate(node.left, context)
    right = evaluate(node.right, context)
    if _is_unknown(left) or _is_unknown(right):
        return UNKNOWN
    left_unit = _unit_of(node.left, context)
    right_unit = _unit_of(node.right, context)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        right = _convert(float(right), right_unit, left_unit, context)
    if node.operator is ComparisonOperator.EQ:
        return left == right
    if node.operator is ComparisonOperator.NE:
        return left != right
    try:
        if node.operator is ComparisonOperator.LT:
            return left < right
        if node.operator is ComparisonOperator.LE:
            return left <= right
        if node.operator is ComparisonOperator.GT:
            return left > right
        return left >= right
    except TypeError as exc:
        raise EvaluationError(
            f"cannot order {type(left).__name__} against {type(right).__name__}"
        ) from exc


def _evaluate_in(node: In, context: EvaluationContext) -> Any:
    value = evaluate(node.value, context)
    if _is_unknown(value):
        return UNKNOWN
    value_unit = _unit_of(node.value, context)
    for member in node.allowed_values:
        member_value = member.native()
        if isinstance(value, (int, float)) and isinstance(member_value, (int, float)):
            member_value = _convert(float(member_value), member.unit, value_unit, context)
        if value == member_value:
            return True
    return False


def _evaluate_date_arithmetic(node: DateArithmetic, context: EvaluationContext) -> Any:
    base = evaluate(node.base, context)
    delta = evaluate(node.duration, context)
    if _is_unknown(base) or _is_unknown(delta):
        return UNKNOWN
    if not isinstance(delta, _dt.timedelta):
        raise EvaluationError("date_arithmetic duration did not evaluate to a duration")
    sign = 1 if node.operator is DateOperator.PLUS else -1
    if node.calendar is Calendar.BUSINESS_DAYS:
        if delta % _dt.timedelta(days=1):
            raise EvaluationError("business-day durations must be whole days")
        anchor = base.date() if isinstance(base, _dt.datetime) else base
        shifted = _add_business_days(anchor, sign * delta.days, context)
        if isinstance(base, _dt.datetime):
            return _dt.datetime.combine(shifted, base.time(), tzinfo=base.tzinfo)
        return shifted
    return base + sign * delta


def _evaluate_function(node: FunctionRef, context: EvaluationContext) -> Any:
    implementation = context.functions.get(node.function_id)
    if implementation is None:
        raise EvaluationError(
            f"function {node.function_id!r} has no registered implementation"
        )
    arguments = [evaluate(argument, context) for argument in node.arguments]
    if any(_is_unknown(argument) for argument in arguments):
        return UNKNOWN
    return implementation(*arguments)


@dataclass(frozen=True)
class DecisionResult:
    """The outcome of evaluating one decision table."""

    matched_clause_ids: tuple[str, ...]
    value: Any
    unknown_clause_ids: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return bool(self.matched_clause_ids)


def evaluate_decision(
    ir: PolicyIR,
    decision_id: str,
    context: EvaluationContext,
) -> DecisionResult:
    """Evaluate a decision by testing each referenced clause in order.

    Rows whose condition is ``UNKNOWN`` are reported separately from rows that
    definitely did not match, so a caller can tell "no rule applies" apart from
    "we could not tell whether a rule applies".
    """
    decision = ir.decision_index().get(decision_id)
    if decision is None:
        raise EvaluationError(f"unknown decision {decision_id!r}")
    clauses = ir.clause_index()
    matched: list[str] = []
    unknown: list[str] = []
    values: list[Any] = []
    for clause_id in decision.decision_rule_refs:
        clause = clauses.get(clause_id)
        if clause is None:
            raise EvaluationError(f"decision {decision_id!r} references unknown clause {clause_id!r}")
        if clause.condition_ast is None:
            raise EvaluationError(f"clause {clause_id!r} has no condition to evaluate")
        outcome = evaluate(clause.condition_ast, context)
        if _is_unknown(outcome):
            unknown.append(clause_id)
            continue
        if not outcome:
            continue
        if clause.exception_ast is not None:
            exception = evaluate(clause.exception_ast, context)
            if _is_unknown(exception):
                unknown.append(clause_id)
                continue
            if exception:
                continue
        if clause.effect_ast is None:
            raise EvaluationError(f"clause {clause_id!r} has no effect to produce")
        matched.append(clause_id)
        values.append(evaluate(clause.effect_ast, context))
    if not matched:
        default = decision.default_output.native() if decision.default_output else UNKNOWN
        return DecisionResult((), default, tuple(unknown))
    return DecisionResult(tuple(matched), values[0], tuple(unknown))
