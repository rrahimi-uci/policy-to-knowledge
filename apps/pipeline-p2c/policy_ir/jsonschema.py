"""Generate the Policy IR v2 JSON Schema from the dataclasses themselves.

A hand-written schema beside hand-written parsers is two contracts that drift
apart, and the drift always favours the looser one. So the schema is derived by
introspecting the records: field names, optionality and enum vocabularies come
from the same definitions the parsers use. A committed copy lives at
``policy_ir/schema/policy-ir-v2.schema.json`` and a test fails if it falls out of
step with the code.

Every object sets ``additionalProperties: false``, mirroring the parsers' refusal
to ignore unknown keys.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import typing
from typing import Any, Mapping, get_args, get_origin

from . import models
from .expressions import ComparisonOperator, DateOperator
from .ids import SCHEMA_VERSION

SCHEMA_ID = "https://policy-to-knowledge.example/schema/policy-ir-v2.schema.json"

#: Records that appear in the schema, in dependency order for readability.
_RECORDS: tuple[type, ...] = (
    models.DocumentArtifact,
    models.Chunk,
    models.EvidenceSpan,
    models.DataDefinition,
    models.FunctionSignature,
    models.UnitConversion,
    models.EntityType,
    models.EntityMention,
    models.ScopeDimensionDefinition,
    models.ScopeDimension,
    models.Scope,
    models.AuthoritySource,
    models.EffectivePeriod,
    models.TemporalConstraint,
    models.AtomicPolicyClause,
    models.DecisionOutput,
    models.DecisionModelCandidate,
    models.TriggerEvent,
    models.ProcessActivity,
    models.ProcessFragmentCandidate,
    models.DependencyEdge,
    models.SemanticRelation,
    models.CoverageEntry,
    models.PolicyIR,
)

#: Fields whose serialised form is an expression tree rather than a scalar.
_EXPRESSION_FIELDS = frozenset(
    {"condition_ast", "effect_ast", "exception_ast", "precondition_ast", "postcondition_ast"}
)
#: Keyed by ``(record, field)`` rather than field name alone. Two records can use the
#: same field name for different things — ``allowed_values`` is a list of typed
#: literals on a DataDefinition and a list of plain strings on a scope dimension.
_LITERAL_FIELDS = frozenset(
    {
        ("DataDefinition", "minimum"),
        ("DataDefinition", "maximum"),
        ("DataDefinition", "default_value"),
        ("TemporalConstraint", "duration"),
        ("DecisionModelCandidate", "default_output"),
    }
)
_LITERAL_LIST_FIELDS = frozenset(
    {("DataDefinition", "allowed_values"), ("DecisionOutput", "allowed_values")}
)

#: Members constrained by a class-level tuple rather than an Enum.
_STRING_ENUM_FIELDS: Mapping[tuple[str, str], tuple[str, ...]] = {
    ("TriggerEvent", "kind"): models.TriggerEvent.KINDS,
    ("ProcessActivity", "kind"): models.ProcessActivity.KINDS,
    ("CoverageEntry", "status"): models.CoverageEntry.STATUSES,
}


def _expression_defs() -> dict[str, Any]:
    """The recursive expression grammar, written out once by hand.

    Introspection cannot express a recursive discriminated union, and the grammar
    is small and stable enough that stating it explicitly is clearer than
    generating it.
    """
    expression_ref = {"$ref": "#/$defs/Expression"}
    literal_ref = {"$ref": "#/$defs/Literal"}

    def node(kind: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {"kind": {"const": kind}, **properties},
            "required": ["kind", *required],
        }

    return {
        "Literal": node(
            "literal",
            {
                "value": {},
                "type": {"$ref": "#/$defs/DataType"},
                "unit": {"type": "string"},
            },
            ["value", "type"],
        ),
        "VariableRef": node(
            "variable_ref", {"data_definition_id": {"type": "string"}}, ["data_definition_id"]
        ),
        "All": node(
            "all",
            {"operands": {"type": "array", "minItems": 1, "items": expression_ref}},
            ["operands"],
        ),
        "AnyOf": node(
            "any",
            {"operands": {"type": "array", "minItems": 1, "items": expression_ref}},
            ["operands"],
        ),
        "Not": node("not", {"operand": expression_ref}, ["operand"]),
        "Comparison": node(
            "comparison",
            {
                "left": expression_ref,
                "operator": {"enum": [member.value for member in ComparisonOperator]},
                "right": expression_ref,
            },
            ["left", "operator", "right"],
        ),
        "In": node(
            "in",
            {
                "value": expression_ref,
                "allowed_values": {"type": "array", "minItems": 1, "items": literal_ref},
            },
            ["value", "allowed_values"],
        ),
        "Exists": node("exists", {"variable": {"$ref": "#/$defs/VariableRef"}}, ["variable"]),
        "DateArithmetic": node(
            "date_arithmetic",
            {
                "base": expression_ref,
                "operator": {"enum": [member.value for member in DateOperator]},
                "duration": expression_ref,
                "calendar": {"$ref": "#/$defs/Calendar"},
            },
            ["base", "operator", "duration"],
        ),
        "FunctionRef": node(
            "function_ref",
            {
                "function_id": {"type": "string"},
                "arguments": {"type": "array", "items": expression_ref},
            },
            ["function_id"],
        ),
        "Expression": {
            "oneOf": [
                {"$ref": f"#/$defs/{name}"}
                for name in (
                    "Literal",
                    "VariableRef",
                    "All",
                    "AnyOf",
                    "Not",
                    "Comparison",
                    "In",
                    "Exists",
                    "DateArithmetic",
                    "FunctionRef",
                )
            ]
        },
    }


def _enum_defs() -> dict[str, Any]:
    from . import enums as enum_module
    from .expressions import Calendar

    collected: dict[str, Any] = {}
    for name in dir(enum_module):
        candidate = getattr(enum_module, name)
        if (
            isinstance(candidate, type)
            and issubclass(candidate, enum.Enum)
            and candidate is not enum_module.StrEnum
        ):
            collected[name] = {"enum": [member.value for member in candidate]}
    collected["Calendar"] = {"enum": [member.value for member in Calendar]}
    return collected


def _scalar_schema(annotation: Any) -> dict[str, Any]:
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is datetime.date:
        return {"type": "string", "format": "date"}
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {"$ref": f"#/$defs/{annotation.__name__}"}
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        return {"$ref": f"#/$defs/{annotation.__name__}"}
    return {}


def _field_schema(record_name: str, field: dataclasses.Field, annotation: Any) -> dict[str, Any]:
    override = _STRING_ENUM_FIELDS.get((record_name, field.name))
    if override is not None:
        return {"enum": list(override)}
    if field.name in _EXPRESSION_FIELDS:
        return {"$ref": "#/$defs/Expression"}
    if (record_name, field.name) in _LITERAL_FIELDS:
        return {"$ref": "#/$defs/Literal"}
    if (record_name, field.name) in _LITERAL_LIST_FIELDS:
        return {"type": "array", "items": {"$ref": "#/$defs/Literal"}}

    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _field_schema(record_name, field, non_none[0])
        return {"anyOf": [_scalar_schema(arg) for arg in non_none]}
    if origin in (tuple, list):
        item = args[0] if args else Any
        if item is Ellipsis:  # pragma: no cover - defensive
            item = Any
        return {"type": "array", "items": _scalar_schema(item)}
    if origin in (dict, Mapping) or annotation is Mapping:
        return {"type": "object"}
    if field.name == "evidence":
        return {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        }
    return _scalar_schema(annotation)


def _record_schema(record: type) -> dict[str, Any]:
    hints = typing.get_type_hints(record)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(record):
        annotation = hints.get(field.name, Any)
        properties[field.name] = _field_schema(record.__name__, field, annotation)
        has_default = (
            field.default is not dataclasses.MISSING
            or field.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        )
        if not has_default:
            required.append(field.name)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def record_schema(record: type) -> dict[str, Any]:
    """Schema for one IR record, for schemas that embed a subset of the IR."""
    return _record_schema(record)


def expression_defs() -> dict[str, Any]:
    """The recursive expression grammar, for schemas that embed it."""
    return _expression_defs()


def enum_defs() -> dict[str, Any]:
    """Every closed vocabulary, for schemas that constrain against them."""
    return _enum_defs()


def build_schema() -> dict[str, Any]:
    """Build the complete JSON Schema document."""
    defs: dict[str, Any] = {}
    defs.update(_enum_defs())
    defs.update(_expression_defs())
    for record in _RECORDS:
        defs[record.__name__] = _record_schema(record)
    root = dict(defs["PolicyIR"])
    root["properties"] = dict(root["properties"])
    root["properties"]["schema_version"] = {"const": SCHEMA_VERSION}
    # schema_version has a dataclass default but the parser demands it, so the
    # schema must demand it too.
    root["required"] = ["schema_version"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Policy IR v2",
        "description": (
            "Canonical intermediate representation for evidence-bound policy "
            "compilation. Generated from policy_ir.models; edit the dataclasses, not "
            "this file."
        ),
        "policyIrVersion": SCHEMA_VERSION,
        **root,
        "$defs": defs,
    }


def schema_json() -> str:
    """Render the schema exactly as the committed copy stores it."""
    import json

    return json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
