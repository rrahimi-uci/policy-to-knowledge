"""Expression grammar, type checking and reference evaluation.

The grammar is the only thing a model may emit, so its edges matter: an operator
that silently accepts mismatched types, or a missing value that quietly reads as
false, would let an unsupported decision look supported.
"""

from __future__ import annotations

import datetime as dt

import pytest

from evaluation import UNKNOWN, EvaluationContext, EvaluationError, evaluate
from policy_ir.enums import DataType, NullPolicy
from policy_ir.expressions import (
    All,
    Any_,
    Calendar,
    Comparison,
    ComparisonOperator as Op,
    DateArithmetic,
    DateOperator,
    Exists,
    ExpressionError,
    FunctionRef,
    In,
    Literal,
    Not,
    VariableRef,
    expression_from_dict,
    format_duration,
    parse_duration,
    referenced_variable_ids,
)
from policy_ir.feel import FeelError, parse_unary_test, to_feel, unary_test
from policy_ir.models import DataDefinition, FunctionSignature, UnitConversion
from policy_ir.tabular import decompose, row_condition
from policy_ir.typecheck import TypeContext, check, check_boolean

N, S, B, D, DUR = (
    DataType.NUMBER,
    DataType.STRING,
    DataType.BOOLEAN,
    DataType.DATE,
    DataType.DURATION,
)


def definitions(**kwargs: DataDefinition) -> dict[str, DataDefinition]:
    return kwargs


@pytest.fixture
def context() -> TypeContext:
    return TypeContext(
        data_definitions={
            "score": DataDefinition("score", "score", N, null_policy=NullPolicy.REJECT),
            "amount": DataDefinition("amount", "amount", N, unit="USD"),
            "cents": DataDefinition("cents", "cents", N, unit="USD_cents"),
            "opened": DataDefinition("opened", "opened", D),
            "flag": DataDefinition("flag", "flag", B),
            "tier": DataDefinition("tier", "tier", S),
        },
        functions={
            "round2": FunctionSignature("round2", "round2", (N,), N),
        },
        conversions={("USD_cents", "USD"): UnitConversion("USD_cents", "USD", 0.01)},
    )


# -- grammar ---------------------------------------------------------------


def test_every_node_round_trips_through_its_serialised_form() -> None:
    expression = All(
        (
            Comparison(VariableRef("score"), Op.GE, Literal(620, N)),
            Any_(
                (
                    In(VariableRef("tier"), (Literal("a", S), Literal("b", S))),
                    Not(Exists(VariableRef("flag"))),
                )
            ),
            Comparison(
                DateArithmetic(
                    VariableRef("opened"), DateOperator.PLUS, Literal("P30D", DUR)
                ),
                Op.LE,
                Literal("2026-12-31", D),
            ),
            Comparison(FunctionRef("round2", (Literal(1.5, N),)), Op.EQ, Literal(2, N)),
        )
    )
    assert expression_from_dict(expression.to_dict()) == expression


def test_unknown_node_kinds_and_keys_are_rejected() -> None:
    with pytest.raises(ExpressionError, match="unknown expression kind"):
        expression_from_dict({"kind": "eval"})
    with pytest.raises(ExpressionError, match="unknown key"):
        expression_from_dict({"kind": "variable_ref", "data_definition_id": "x", "extra": 1})
    with pytest.raises(ExpressionError, match="missing key"):
        expression_from_dict({"kind": "comparison", "left": {"kind": "literal", "value": 1, "type": "number"}})


def test_empty_junctions_and_memberships_are_rejected() -> None:
    with pytest.raises(ExpressionError, match="at least one operand"):
        All(())
    with pytest.raises(ExpressionError, match="at least one operand"):
        Any_(())
    with pytest.raises(ExpressionError, match="at least one allowed value"):
        In(VariableRef("tier"), ())


def test_literals_validate_eagerly() -> None:
    with pytest.raises(ExpressionError, match="must be numeric"):
        Literal("620", N)
    with pytest.raises(ExpressionError, match="not an ISO 8601 date"):
        Literal("31/12/2026", D)


def test_year_month_durations_are_refused_rather_than_approximated() -> None:
    """"1 month" is calendar-dependent; guessing 30 days would be silent drift."""
    with pytest.raises(ExpressionError, match="year/month duration"):
        parse_duration("P1M")
    assert parse_duration("P2W") == dt.timedelta(days=14)
    assert format_duration(parse_duration("P5DT2H")) == "P5DT2H"


def test_referenced_variables_are_sorted_and_deduplicated() -> None:
    expression = All(
        (
            Comparison(VariableRef("score"), Op.GE, Literal(1, N)),
            Comparison(VariableRef("amount"), Op.GE, Literal(1, N, unit="USD")),
            Comparison(VariableRef("score"), Op.LE, Literal(9, N)),
        )
    )
    assert referenced_variable_ids(expression) == ("amount", "score")


# -- type checking ---------------------------------------------------------


def test_well_typed_comparison_checks_clean(context: TypeContext) -> None:
    result = check(Comparison(VariableRef("score"), Op.GE, Literal(620, N)), context)
    assert result.ok and result.type is B


def test_comparing_a_date_to_a_number_is_a_type_error(context: TypeContext) -> None:
    errors = check(Comparison(VariableRef("opened"), Op.GE, Literal(5, N)), context).errors
    assert any("cannot compare" in error for error in errors)


def test_ordering_operators_are_undefined_for_strings(context: TypeContext) -> None:
    errors = check(Comparison(VariableRef("tier"), Op.GT, Literal("a", S)), context).errors
    assert any("not defined for" in error for error in errors)


def test_units_must_match_or_have_a_declared_conversion(context: TypeContext) -> None:
    unmatched = check(
        Comparison(VariableRef("amount"), Op.GT, Literal(5000, N, unit="EUR")), context
    )
    assert any("incompatible units" in error for error in unmatched.errors)
    declared = check(Comparison(VariableRef("amount"), Op.GT, VariableRef("cents")), context)
    assert declared.ok


def test_a_bare_number_is_not_compatible_with_a_currency(context: TypeContext) -> None:
    """Forcing the unit to be stated is the point: $5,000 must not satisfy 5,000."""
    errors = check(Comparison(VariableRef("amount"), Op.GT, Literal(5000, N)), context).errors
    assert any("incompatible units" in error for error in errors)


def test_junction_operands_must_be_boolean(context: TypeContext) -> None:
    errors = check(All((Literal(1, N),)), context).errors
    assert any("must be boolean" in error for error in errors)


def test_unknown_variables_and_functions_are_reported(context: TypeContext) -> None:
    assert check(VariableRef("nope"), context).errors
    assert check(FunctionRef("nope", ()), context).errors


def test_function_arity_and_argument_types_are_checked(context: TypeContext) -> None:
    assert any(
        "expects 1 argument" in error
        for error in check(FunctionRef("round2", ()), context).errors
    )
    assert any(
        "must be number" in error
        for error in check(FunctionRef("round2", (Literal("x", S),)), context).errors
    )


def test_business_day_duration_must_agree_with_the_calendar(context: TypeContext) -> None:
    mismatched = DateArithmetic(
        VariableRef("opened"),
        DateOperator.PLUS,
        Literal("P5D", DUR, unit="business_days"),
        Calendar.CALENDAR_DAYS,
    )
    assert any("disagrees with calendar" in error for error in check(mismatched, context).errors)


def test_check_boolean_rejects_a_value_expression(context: TypeContext) -> None:
    assert check_boolean(VariableRef("score"), context)


# -- evaluation ------------------------------------------------------------


def evaluation_context(**values: object) -> EvaluationContext:
    return EvaluationContext(
        values=values,
        data_definitions={
            "score": DataDefinition("score", "score", N, null_policy=NullPolicy.TREAT_AS_ABSENT),
            "required": DataDefinition("required", "required", N, null_policy=NullPolicy.REJECT),
            "defaulted": DataDefinition(
                "defaulted",
                "defaulted",
                N,
                null_policy=NullPolicy.DEFAULT_VALUE,
                default_value=Literal(0, N),
            ),
            "amount": DataDefinition("amount", "amount", N, unit="USD"),
            "cents": DataDefinition("cents", "cents", N, unit="USD_cents"),
            "opened": DataDefinition("opened", "opened", D),
        },
        conversions={("USD_cents", "USD"): UnitConversion("USD_cents", "USD", 0.01)},
    )


def test_missing_values_are_unknown_not_false() -> None:
    expression = Comparison(VariableRef("score"), Op.GE, Literal(620, N))
    assert evaluate(expression, evaluation_context()) is UNKNOWN
    assert evaluate(expression, evaluation_context(score=700)) is True


def test_unknown_propagates_through_kleene_logic() -> None:
    known_false = Comparison(VariableRef("amount"), Op.GT, Literal(10, N, unit="USD"))
    unknown = Comparison(VariableRef("score"), Op.GE, Literal(620, N))
    context = evaluation_context(amount=5)
    # A definite false short-circuits a conjunction even with an unknown beside it.
    assert evaluate(All((known_false, unknown)), context) is False
    assert evaluate(Any_((known_false, unknown)), context) is UNKNOWN
    assert evaluate(Not(unknown), context) is UNKNOWN


def test_null_policies_are_honoured() -> None:
    assert evaluate(VariableRef("defaulted"), evaluation_context()) == 0
    with pytest.raises(EvaluationError, match="is missing"):
        evaluate(VariableRef("required"), evaluation_context())


def test_declared_unit_conversion_is_applied() -> None:
    expression = Comparison(VariableRef("amount"), Op.EQ, VariableRef("cents"))
    assert evaluate(expression, evaluation_context(amount=50, cents=5000)) is True


def test_undeclared_unit_conversion_raises_rather_than_guessing() -> None:
    expression = Comparison(VariableRef("amount"), Op.GT, Literal(1, N, unit="EUR"))
    with pytest.raises(EvaluationError, match="no declared conversion"):
        evaluate(expression, evaluation_context(amount=5))


def test_exists_distinguishes_absence_from_falsehood() -> None:
    assert evaluate(Exists(VariableRef("score")), evaluation_context()) is False
    assert evaluate(Exists(VariableRef("score")), evaluation_context(score=0)) is True


def test_calendar_and_business_day_arithmetic_differ() -> None:
    wednesday = dt.date(2026, 8, 19)
    context = evaluation_context(opened=wednesday)
    calendar = DateArithmetic(VariableRef("opened"), DateOperator.PLUS, Literal("P5D", DUR))
    business = DateArithmetic(
        VariableRef("opened"),
        DateOperator.PLUS,
        Literal("P5D", DUR, unit="business_days"),
        Calendar.BUSINESS_DAYS,
    )
    assert evaluate(calendar, context) == dt.date(2026, 8, 24)
    assert evaluate(business, context) == dt.date(2026, 8, 26)


def test_business_days_skip_supplied_holidays() -> None:
    context = EvaluationContext(
        values={"opened": dt.date(2026, 8, 19)},
        data_definitions={"opened": DataDefinition("opened", "opened", D)},
        holidays=frozenset({dt.date(2026, 8, 20)}),
    )
    expression = DateArithmetic(
        VariableRef("opened"),
        DateOperator.PLUS,
        Literal("P1D", DUR, unit="business_days"),
        Calendar.BUSINESS_DAYS,
    )
    assert evaluate(expression, context) == dt.date(2026, 8, 21)


# -- FEEL ------------------------------------------------------------------


def test_feel_rendering_and_unary_tests_agree_on_a_range() -> None:
    names = {"score": "credit_score"}
    band = All(
        (
            Comparison(VariableRef("score"), Op.GE, Literal(620, N)),
            Comparison(VariableRef("score"), Op.LT, Literal(740, N)),
        )
    )
    assert to_feel(band, names) == "(credit_score >= 620 and credit_score < 740)"
    test = unary_test(decompose(band)["score"])
    assert test == "[620..740)"
    parsed = parse_unary_test(test)
    assert parsed.matches(620) and parsed.matches(739) and not parsed.matches(740)


def test_membership_and_negation_render_and_parse() -> None:
    members = In(VariableRef("tier"), (Literal("a", S), Literal("b", S)))
    text = unary_test(decompose(members)["tier"])
    assert parse_unary_test(text).matches("a")
    assert not parse_unary_test(text).matches("c")
    negated = unary_test(decompose(Not(members))["tier"])
    assert negated.startswith("not(")
    assert not parse_unary_test(negated).matches("a")
    assert parse_unary_test(negated).matches("c")


def test_an_unconstrained_input_renders_as_a_dash() -> None:
    assert unary_test(()) == "-"
    assert parse_unary_test("-").matches(None)


def test_source_text_is_escaped_as_data_not_markup() -> None:
    from compilers.xmlwriter import Element, serialize

    root = Element("t", {"a": 'x"&<'}, text="<script>&</script>")
    xml = serialize(root)
    assert "<script>" not in xml.replace("&lt;script&gt;", "")
    assert "&quot;" in xml and "&amp;" in xml


def test_business_day_arithmetic_has_no_portable_feel_form() -> None:
    """Refusing beats emitting FEEL that means something else."""
    expression = DateArithmetic(
        VariableRef("opened"),
        DateOperator.PLUS,
        Literal("P5D", DUR, unit="business_days"),
        Calendar.BUSINESS_DAYS,
    )
    with pytest.raises(FeelError, match="no portable FEEL form"):
        to_feel(expression, {"opened": "opened"})


def test_row_condition_folds_the_exception_in() -> None:
    condition = Comparison(VariableRef("score"), Op.GE, Literal(620, N))
    exception = Comparison(VariableRef("tier"), Op.EQ, Literal("restricted", S))
    folded = row_condition(condition, exception)
    atoms = decompose(folded)
    assert set(atoms) == {"score", "tier"}
    assert atoms["tier"][0].negated is True
    assert row_condition(condition, None) is condition
