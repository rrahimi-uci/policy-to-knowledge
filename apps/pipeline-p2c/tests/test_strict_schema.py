"""The strict-schema rewriter.

Structured Outputs strict mode accepts a narrow subset of JSON Schema. Every
constraint asserted here was learned from a rejection by the live API, so each test
names the rejection it prevents from recurring.
"""

from __future__ import annotations

import json

from extraction.contract import proposal_schema
from extraction.strict_schema import (
    ANY_SCALAR,
    UNSUPPORTED_KEYWORDS,
    strip_nulls,
    to_strict,
)


def _walk(schema):
    """Yield every subschema, so assertions can be made over the whole tree."""
    if isinstance(schema, dict):
        yield schema
        for value in schema.values():
            yield from _walk(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _walk(item)


def test_no_unsupported_keyword_survives(sample_request) -> None:
    strict = to_strict(proposal_schema(sample_request))
    for node in _walk(strict):
        for keyword in UNSUPPORTED_KEYWORDS:
            assert keyword not in node, f"{keyword} survived the rewrite"


def test_every_object_is_closed_and_fully_required(sample_request) -> None:
    """Strict mode requires additionalProperties false and required == all keys."""
    strict = to_strict(proposal_schema(sample_request))
    for node in _walk(strict):
        if node.get("type") != "object":
            continue
        properties = node.get("properties")
        if properties is None:
            continue
        assert node.get("additionalProperties") is False
        assert sorted(node.get("required", ())) == sorted(properties)


def test_enums_carry_an_explicit_type(sample_request) -> None:
    """The API rejected a bare enum with no type; every enum must declare one."""
    strict = to_strict(proposal_schema(sample_request))
    for node in _walk(strict):
        if "enum" in node and node.get("enum"):
            assert "type" in node or "anyOf" in node


def test_arrays_are_never_nullable(sample_request) -> None:
    """``{"type": ["array", "null"]}`` was rejected when nested in an array of $ref.

    Optionality for arrays is therefore expressed as an empty array, not as null.
    """
    strict = to_strict(proposal_schema(sample_request))
    for node in _walk(strict):
        type_value = node.get("type")
        if isinstance(type_value, list):
            assert not ("array" in type_value and "null" in type_value)


def test_oneof_becomes_anyof(sample_request) -> None:
    source = {"type": "object", "properties": {"a": {"oneOf": [{"type": "string"}]}}}
    strict = to_strict(source, prune=False)
    assert "anyOf" in strict["properties"]["a"]
    assert "oneOf" not in strict["properties"]["a"]


def test_const_becomes_a_single_member_enum(sample_request) -> None:
    strict = to_strict({"const": "clause"}, prune=False)
    assert strict["enum"] == ["clause"]
    assert strict["type"] == "string"


def test_unreachable_defs_are_pruned(sample_request) -> None:
    """The generated schema carried defs no property referenced; strict mode counts them."""
    source = proposal_schema(sample_request)
    strict = to_strict(source)
    assert len(strict.get("$defs", {})) < len(source.get("$defs", {}))


def test_pruning_keeps_every_referenced_def(sample_request) -> None:
    strict = to_strict(proposal_schema(sample_request))
    available = set(strict.get("$defs", {}))
    for node in _walk(strict):
        ref = node.get("$ref")
        if ref:
            assert ref.split("/")[-1] in available


def test_untyped_value_slot_becomes_a_scalar_union(sample_request) -> None:
    """A value that may be string, number or boolean cannot be `true` in strict mode."""
    strict = to_strict({"type": "object", "properties": {"value": True}}, prune=False)
    assert strict["properties"]["value"] == ANY_SCALAR


def test_strip_nulls_removes_placeholders_but_keeps_falsey_data(sample_request) -> None:
    """Strict mode forces every key present; nulls are placeholders, 0/""/False are data."""
    value = {"a": None, "b": 0, "c": "", "d": False, "e": [None, {"f": None, "g": 1}]}
    assert strip_nulls(value) == {"b": 0, "c": "", "d": False, "e": [{"g": 1}]}


def test_rewrite_is_json_serialisable(sample_request) -> None:
    json.dumps(to_strict(proposal_schema(sample_request)))


# --------------------------------------------------------------- duration narrowing
#
# A live run failed 8 of its first 45 chunks on nothing but the duration slot: the model
# proposed `30`, `"four months"`, and a nested arithmetic node, each of which the open
# schema permitted and the parser then refused. Each refusal cost a call.


def test_duration_is_a_literal_string_not_an_open_expression(sample_request) -> None:
    from extraction.contract import proposal_schema

    strict = to_strict(proposal_schema(sample_request))
    for record in ("TemporalConstraint", "DateArithmetic"):
        slot = strict["$defs"][record]["properties"]["duration"]
        assert slot == {"$ref": "#/$defs/DurationLiteral"}, record


def test_the_duration_literal_admits_no_number(sample_request) -> None:
    from extraction.contract import proposal_schema

    strict = to_strict(proposal_schema(sample_request))
    value = strict["$defs"]["DurationLiteral"]["properties"]["value"]
    assert value["type"] == "string"


def test_the_duration_pattern_accepts_what_the_compiler_parses() -> None:
    """The schema pattern and the parser must agree, or one of them is decoration."""
    import re

    from extraction.contract import DURATION_PATTERN
    from policy_ir.expressions import parse_duration

    pattern = re.compile(DURATION_PATTERN)
    for text in ("P30D", "PT12H", "P1DT6H", "PT45M", "P7D"):
        assert pattern.match(text), text
        parse_duration(text)  # must not raise


def test_the_duration_pattern_rejects_what_the_compiler_refuses() -> None:
    """Months and years are not approximated, so they must not be expressible."""
    import re

    import pytest as _pytest

    from extraction.contract import DURATION_PATTERN
    from policy_ir.expressions import ExpressionError, parse_duration

    pattern = re.compile(DURATION_PATTERN)
    for text in ("P4M", "P1Y", "four months", "30", "P1Y6M"):
        assert not pattern.match(text), text
        with _pytest.raises((ExpressionError, TypeError, AttributeError)):
            parse_duration(text)


def test_the_duration_type_is_pinned_to_duration(sample_request) -> None:
    from extraction.contract import proposal_schema

    strict = to_strict(proposal_schema(sample_request))
    assert strict["$defs"]["DurationLiteral"]["properties"]["type"]["enum"] == ["duration"]


def test_the_instructions_say_what_to_do_with_a_month(sample_request) -> None:
    """A pattern forbids; it does not explain. The prose has to say 'use missing'."""
    from extraction.contract import render_instructions

    text = render_instructions(sample_request).lower()
    assert "month" in text
    assert "missing" in text


def test_effective_period_dates_are_pinned_to_iso_form(sample_request) -> None:
    """A live run met 'July 6, 2010': valid JSON, open slot, refused by the parser."""
    from extraction.contract import proposal_schema

    strict = to_strict(proposal_schema(sample_request))
    for key in ("start", "end"):
        slot = strict["$defs"]["EffectivePeriod"]["properties"][key]
        assert slot["type"] == "string"
        assert slot["pattern"]


def test_the_date_pattern_agrees_with_the_date_parser() -> None:
    import re

    from extraction.contract import DATE_PATTERN
    from policy_ir.timeline import parse_date

    pattern = re.compile(DATE_PATTERN)
    for text in ("2010-07-06", "1999-01-31"):
        assert pattern.match(text)
        parse_date(text)
    for text in ("July 6, 2010", "06/07/2010", "2010-7-6", "2010"):
        assert not pattern.match(text), text


def test_the_instructions_show_how_to_convert_a_prose_date(sample_request) -> None:
    """A pattern rejects; the prose has to demonstrate the conversion."""
    from extraction.contract import render_instructions

    text = render_instructions(sample_request)
    assert "YYYY-MM-DD" in text
    assert "2010-07-06" in text
