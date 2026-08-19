"""Deterministic type checking for the restricted expression AST.

An ill-typed expression must never reach a compiler: DMN would happily serialise
``date >= 5`` into syntactically valid FEEL that means nothing. The checker
collects *all* errors rather than raising on the first, so a gate report can tell
an author everything that is wrong with a clause in one pass.

Unit handling is deliberately strict. Two quantities may be compared only when
their units are identical or a :class:`~policy_ir.models.UnitConversion` has been
declared between them, and a bare number is not compatible with a number that
carries a unit. That is what makes the "$5,000 becomes €5,000" drift test fail
closed instead of silently passing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .enums import ORDERED_TYPES, DataType
from .expressions import (
    All,
    Any_,
    Calendar,
    Comparison,
    DateArithmetic,
    Exists,
    Expression,
    FunctionRef,
    In,
    Literal,
    Not,
    ORDERING_OPERATORS,
    VariableRef,
)
from .models import DataDefinition, FunctionSignature, UnitConversion


@dataclass(frozen=True)
class TypeContext:
    """Symbols the checker resolves references against."""

    data_definitions: Mapping[str, DataDefinition] = field(default_factory=dict)
    functions: Mapping[str, FunctionSignature] = field(default_factory=dict)
    conversions: Mapping[tuple[str, str], UnitConversion] = field(default_factory=dict)

    def units_compatible(self, left: str | None, right: str | None) -> bool:
        if left == right:
            return True
        if left is None or right is None:
            return False
        return (left, right) in self.conversions or (right, left) in self.conversions


@dataclass(frozen=True)
class CheckResult:
    """The inferred type of an expression plus any errors found beneath it."""

    type: DataType | None
    unit: str | None = None
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _merge(*results: CheckResult) -> tuple[str, ...]:
    errors: list[str] = []
    for result in results:
        errors.extend(result.errors)
    return tuple(errors)


def check(expression: Expression, context: TypeContext) -> CheckResult:
    """Infer the type of ``expression``, accumulating every error found."""
    if isinstance(expression, Literal):
        return _check_literal(expression)
    if isinstance(expression, VariableRef):
        return _check_variable(expression, context)
    if isinstance(expression, (All, Any_)):
        return _check_junction(expression, context)
    if isinstance(expression, Not):
        return _check_not(expression, context)
    if isinstance(expression, Comparison):
        return _check_comparison(expression, context)
    if isinstance(expression, In):
        return _check_in(expression, context)
    if isinstance(expression, Exists):
        return _check_exists(expression, context)
    if isinstance(expression, DateArithmetic):
        return _check_date_arithmetic(expression, context)
    if isinstance(expression, FunctionRef):
        return _check_function(expression, context)
    return CheckResult(None, None, (f"unsupported expression node {type(expression).__name__}",))


def _check_literal(node: Literal) -> CheckResult:
    try:
        node.native()
    except ValueError as exc:
        return CheckResult(None, node.unit, (f"invalid literal: {exc}",))
    return CheckResult(node.type, node.unit)


def _check_variable(node: VariableRef, context: TypeContext) -> CheckResult:
    definition = context.data_definitions.get(node.data_definition_id)
    if definition is None:
        return CheckResult(
            None, None, (f"unknown data definition {node.data_definition_id!r}",)
        )
    return CheckResult(definition.type, definition.unit)


def _check_junction(node: All | Any_, context: TypeContext) -> CheckResult:
    results = [check(operand, context) for operand in node.operands]
    errors = list(_merge(*results))
    for index, result in enumerate(results):
        if result.ok and result.type is not DataType.BOOLEAN:
            errors.append(
                f"{node.kind}() operand {index} must be boolean, got {result.type}"
            )
    return CheckResult(DataType.BOOLEAN, None, tuple(errors))


def _check_not(node: Not, context: TypeContext) -> CheckResult:
    result = check(node.operand, context)
    errors = list(result.errors)
    if result.ok and result.type is not DataType.BOOLEAN:
        errors.append(f"not() operand must be boolean, got {result.type}")
    return CheckResult(DataType.BOOLEAN, None, tuple(errors))


def _check_comparison(node: Comparison, context: TypeContext) -> CheckResult:
    left = check(node.left, context)
    right = check(node.right, context)
    errors = list(_merge(left, right))
    if left.ok and right.ok:
        if left.type != right.type:
            errors.append(
                f"cannot compare {left.type} with {right.type} using {node.operator.value!r}"
            )
        elif node.operator in ORDERING_OPERATORS and left.type not in ORDERED_TYPES:
            errors.append(f"operator {node.operator.value!r} is not defined for {left.type}")
        if not context.units_compatible(left.unit, right.unit):
            errors.append(
                f"incompatible units {left.unit!r} and {right.unit!r}; declare a unit conversion"
            )
    return CheckResult(DataType.BOOLEAN, None, tuple(errors))


def _check_in(node: In, context: TypeContext) -> CheckResult:
    value = check(node.value, context)
    errors = list(value.errors)
    for index, member in enumerate(node.allowed_values):
        member_result = _check_literal(member)
        errors.extend(member_result.errors)
        if value.ok and member_result.ok:
            if member_result.type != value.type:
                errors.append(
                    f"in() member {index} has type {member_result.type}, expected {value.type}"
                )
            if not context.units_compatible(value.unit, member_result.unit):
                errors.append(
                    f"in() member {index} has unit {member_result.unit!r}, "
                    f"incompatible with {value.unit!r}"
                )
    return CheckResult(DataType.BOOLEAN, None, tuple(errors))


def _check_exists(node: Exists, context: TypeContext) -> CheckResult:
    result = _check_variable(node.variable, context)
    return CheckResult(DataType.BOOLEAN, None, result.errors)


def _check_date_arithmetic(node: DateArithmetic, context: TypeContext) -> CheckResult:
    base = check(node.base, context)
    duration = check(node.duration, context)
    errors = list(_merge(base, duration))
    if base.ok and base.type not in (DataType.DATE, DataType.DATE_TIME):
        errors.append(f"date_arithmetic base must be a date or date-time, got {base.type}")
    if duration.ok and duration.type is not DataType.DURATION:
        errors.append(f"date_arithmetic duration must be a duration, got {duration.type}")
    # A duration literal may name its calendar, but it must agree with the node:
    # "5 business days" added on a calendar-day basis is a different deadline.
    if duration.unit is not None and duration.unit != node.calendar.value:
        errors.append(
            f"duration unit {duration.unit!r} disagrees with calendar {node.calendar.value!r}"
        )
    return CheckResult(base.type if base.ok else None, base.unit, tuple(errors))


def _check_function(node: FunctionRef, context: TypeContext) -> CheckResult:
    signature = context.functions.get(node.function_id)
    argument_results = [check(argument, context) for argument in node.arguments]
    errors = list(_merge(*argument_results))
    if signature is None:
        errors.append(f"unknown function {node.function_id!r}")
        return CheckResult(None, None, tuple(errors))
    if len(node.arguments) != len(signature.parameter_types):
        errors.append(
            f"function {node.function_id!r} expects {len(signature.parameter_types)} "
            f"argument(s), got {len(node.arguments)}"
        )
    else:
        for index, (result, expected) in enumerate(
            zip(argument_results, signature.parameter_types)
        ):
            if result.ok and result.type != expected:
                errors.append(
                    f"function {node.function_id!r} argument {index} must be {expected}, "
                    f"got {result.type}"
                )
    return CheckResult(signature.return_type, signature.return_unit, tuple(errors))


def check_boolean(expression: Expression, context: TypeContext) -> tuple[str, ...]:
    """Type-check an expression that must evaluate to a boolean."""
    result = check(expression, context)
    errors = list(result.errors)
    if result.ok and result.type is not DataType.BOOLEAN:
        errors.append(f"expression must be boolean, got {result.type}")
    return tuple(errors)


def context_from_ir(ir: "object") -> TypeContext:
    """Build a :class:`TypeContext` from a :class:`~policy_ir.models.PolicyIR`."""
    return TypeContext(
        data_definitions=ir.data_definition_index(),  # type: ignore[attr-defined]
        functions=ir.function_index(),  # type: ignore[attr-defined]
        conversions=ir.conversion_index(),  # type: ignore[attr-defined]
    )
