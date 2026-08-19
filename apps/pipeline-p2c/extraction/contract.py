"""The machine-readable contract handed to a model-driven extractor.

Two artefacts per request, both generated rather than written by hand:

* :func:`proposal_schema` — a JSON Schema for the batch of proposals. Unit indices are
  constrained to the exact set the request offered, so a citation to unseen text is not
  merely rejected downstream but **unexpressible**: a structured-output API will not
  produce it. Every vocabulary is a closed enum, and every object sets
  ``additionalProperties: false``.
* :func:`render_instructions` — the prose contract, listing the units and stating what
  must not be attempted.

Generating both from the same definitions the parsers use is the point. A hand-written
prompt drifts from the code that validates its output, and the drift always favours the
looser side.
"""

from __future__ import annotations

from typing import Any

from policy_ir.enums import (
    CompilationIntent,
    Effect,
    Lifecycle,
    Modality,
    SemanticKind,
    SemanticRole,
)
from policy_ir.ids import SCHEMA_VERSION
from policy_ir.jsonschema import enum_defs, expression_defs

from .candidates import DECLARABLE_MISSING
from .offer import ExtractionRequest


def proposal_schema(request: ExtractionRequest) -> dict[str, Any]:
    """Build the JSON Schema for proposals against one request."""
    unit_indices = [unit.index for unit in request.units]
    unit_ref = {"type": "integer", "enum": unit_indices}
    defs: dict[str, Any] = {**enum_defs(), **expression_defs()}
    defs["RoleCitation"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "role": {"enum": [member.value for member in SemanticRole]},
            "units": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": unit_ref,
            },
        },
        "required": ["role", "units"],
    }
    defs["CandidateProposal"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "modality": {"enum": [m.value for m in Modality]},
            "semantic_kind": {"enum": [k.value for k in SemanticKind]},
            "effect": {"enum": [e.value for e in Effect]},
            "display_unit": unit_ref,
            "citations": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/RoleCitation"},
            },
            "subject_ref": {"type": "string"},
            "action": {"type": "string"},
            "object_ref": {"type": "string"},
            "condition_ast": {"$ref": "#/$defs/Expression"},
            "effect_ast": {"$ref": "#/$defs/Expression"},
            "exception_ast": {"$ref": "#/$defs/Expression"},
            "temporal_constraint": {"$ref": "#/$defs/TemporalConstraint"},
            "scope": {"$ref": "#/$defs/Scope"},
            "effective_period": {"$ref": "#/$defs/EffectivePeriod"},
            "lifecycle": {"enum": [value.value for value in Lifecycle]},
            "compilation_intent": {"enum": [i.value for i in CompilationIntent]},
            "authority_ref": {"type": "string"},
            "cross_reference_targets": {"type": "array", "items": {"type": "string"}},
            "missing": {
                "type": "array",
                "items": {"enum": sorted(DECLARABLE_MISSING)},
                "uniqueItems": True,
            },
        },
        "required": ["modality", "semantic_kind", "effect", "display_unit", "citations"],
    }
    # Only the records a proposal may embed; the rest of the IR is not its business.
    for name in ("TemporalConstraint", "Scope", "ScopeDimension", "EffectivePeriod"):
        defs.setdefault(name, _record_stub(name))

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Policy IR extraction proposals for {request.chunk_id}",
        "description": (
            "Zero or more proposed clauses for one chunk. Cite only the offered unit "
            "indices; the application builds every evidence span itself."
        ),
        "policyIrVersion": SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidates": {"type": "array", "items": {"$ref": "#/$defs/CandidateProposal"}}
        },
        "required": ["candidates"],
        "$defs": _narrow_temporal(defs),
    }


#: ISO 8601 days-and-time durations, which is the subset the compiler evaluates. Years
#: and months are deliberately absent: a "month" is not a fixed number of days, so FEEL
#: and this compiler both refuse to approximate one.
DURATION_PATTERN = r"^P(\d+D)?(T(\d+H)?(\d+M)?(\d+S)?)?$"

#: A calendar date, which every date field in the IR parses with ``date.fromisoformat``.
#: Left open, the model writes dates the way the source document does — "July 6, 2010" —
#: which is valid JSON, valid against an open string slot, and refused by the parser.
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def _narrow_temporal(defs: dict[str, Any]) -> dict[str, Any]:
    """Constrain every duration slot to a literal ISO 8601 days-and-time string.

    The IR's own schema leaves a duration as any expression holding any literal value,
    which is correct for the IR: a duration can legitimately come from a variable at
    evaluation time. It is wrong for an *extraction contract*. Given the open slot the
    model proposed ``30``, ``"four months"``, and a nested arithmetic node — all three
    parsed as valid JSON, all three were refused downstream, and each refusal cost a
    call. 18% of a live run failed this way on nothing else.

    Narrowing the slot moves the failure from "refused after the fact" to "impossible to
    express", which is the same move the unit-index citation contract makes.
    """
    narrowed = dict(defs)

    period = narrowed.get("EffectivePeriod")
    if isinstance(period, dict):
        dated = {
            key: {
                "type": "string",
                "pattern": DATE_PATTERN,
                "description": "Calendar date as YYYY-MM-DD, exactly as ISO 8601 writes it.",
            }
            for key in ("start", "end")
            if key in period.get("properties", {})
        }
        narrowed["EffectivePeriod"] = {
            **period,
            "properties": {**period["properties"], **dated},
        }

    narrowed["DurationLiteral"] = {
        "type": "object",
        "additionalProperties": False,
        "description": (
            "A duration stated in the cited text, as an ISO 8601 days-and-time string: "
            "P30D for thirty days, PT12H for twelve hours, P1DT6H for a day and six "
            "hours. Years and months cannot be expressed; see the instructions."
        ),
        "properties": {
            "kind": {"const": "literal"},
            "value": {"type": "string", "pattern": DURATION_PATTERN},
            "type": {"const": "duration"},
        },
        "required": ["kind", "value", "type"],
    }
    duration_ref = {"$ref": "#/$defs/DurationLiteral"}
    for name in ("TemporalConstraint", "DateArithmetic"):
        record = narrowed.get(name)
        if isinstance(record, dict) and "duration" in record.get("properties", {}):
            record = {**record, "properties": {**record["properties"],
                                               "duration": duration_ref}}
            narrowed[name] = record
    return narrowed


def _record_stub(name: str) -> dict[str, Any]:
    """Schema for an IR record a proposal may embed, derived from the dataclass.

    Generated by the same code that generates the IR's own schema, so the two cannot
    describe the same record differently.
    """
    from policy_ir import models, scope
    from policy_ir.jsonschema import record_schema

    return record_schema(getattr(models, name, None) or getattr(scope, name))


#: What a proposal must never do. Stated in the instructions because a schema can forbid
#: a shape but not an intention.
PROHIBITIONS = (
    "Do not write FEEL, SQL, XML, JavaScript, Python or any other code. Expressions are "
    "built only from the closed grammar in this schema, and the compiler serialises them.",
    "Do not cite a unit that is not listed below. There is no other way to reference the "
    "document, and an index outside the list will be refused.",
    "Do not state a number, date or duration that does not appear in the units you cite. "
    "Every value is checked against the cited text.",
    "Write every date as YYYY-MM-DD, whatever form the source uses. 'July 6, 2010' is "
    "2010-07-06. A date in any other form will be refused.",
    "Express a duration only in days, hours, minutes or seconds, as ISO 8601: P30D, "
    "PT12H, P1DT6H. A duration in months or years cannot be represented, because a "
    "month is not a fixed number of days and approximating one would change the "
    "deadline. If the text says 'within four months', omit the temporal constraint and "
    "name it in `missing` instead of converting it.",
    "Do not invent an attribute, actor, threshold or process step that the units do not "
    "state. If a semantic field is not stated, name it in `missing` instead.",
    "Do not supply a field you have also named in `missing`; that is a contradiction and "
    "the proposal will be refused.",
    "Do not choose an identifier. Identity is derived from the cited units.",
    "Return an empty `candidates` list if these units state no requirement, decision, "
    "definition or process step. That is a valid and expected answer.",
)


def render_instructions(request: ExtractionRequest) -> str:
    """Render the prose contract for one request, listing its offered units."""
    lines = [
        f"# Extraction request for chunk {request.chunk_id}",
        "",
        f"Section: {request.section_path or '(none recorded)'}",
        f"Document: {request.document_id}",
        f"Policy IR version: {SCHEMA_VERSION}",
        "",
        "## Task",
        "",
        "Propose zero or more clauses supported by the numbered units below. For each "
        "clause, cite the units that support each part of it by index, and choose values "
        "only from the enumerated vocabularies in the accompanying JSON Schema.",
        "",
        "## Rules",
        "",
    ]
    lines.extend(f"{index}. {rule}" for index, rule in enumerate(PROHIBITIONS, start=1))
    lines.extend(["", "## Units", ""])
    for unit in request.units:
        lines.append(f"[{unit.index}] {unit.text}")
    return "\n".join(lines) + "\n"
