"""Rewrite a generated JSON Schema into the strict Structured Outputs subset.

Structured Outputs guarantees a reply conforms to a schema, which is what turns the
unit-index bound from a check into a constraint: the enumeration of offered indices is
enforced while the reply is generated, so a fabricated citation cannot be produced at
all. Earning that guarantee costs a rewrite, because the strict subset is narrower than
JSON Schema:

* every property must be listed in ``required``, and an optional one is expressed as a
  union with ``null`` instead;
* ``oneOf`` is not supported, though ``anyOf`` is;
* ``const`` is not supported, though a single-member ``enum`` is;
* ``uniqueItems`` and the composition keywords (``allOf``, ``not``, ``if``/``then``/
  ``else``, ``dependent*``) are not supported;
* an empty schema — "any JSON value" — has no strict equivalent and must be narrowed;
* an ``enum`` must be accompanied by a ``type``, which the generator omits because plain
  JSON Schema does not need it.

Unreachable ``$defs`` are also pruned. The IR's vocabulary generator emits every closed
enum, but a proposal references only a handful; carrying the rest costs input tokens on
every call and gives the strict validator more surface to reject.

The rewrite is mechanical and lossless in the direction that matters: it never *widens*
what the schema accepts, except where an optional field gains ``null``, which the parser
already treats as absent. Constraints that carry the integrity properties — the index
enumerations, the closed vocabularies, ``additionalProperties: false`` — pass through
untouched.
"""

from __future__ import annotations

from typing import Any

#: Keywords the strict subset does not accept. Dropped rather than translated, because
#: each would need a semantics the subset cannot express.
UNSUPPORTED_KEYWORDS = (
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "dependentRequired",
    "dependentSchemas",
    "uniqueItems",
    "patternProperties",
    "propertyNames",
    "unevaluatedProperties",
)

#: What an untyped ("any value") schema becomes. A literal in policy text is a number, a
#: string or a boolean; list and context literals exist in the IR but an extractor has no
#: use for them, and admitting them here would cost the strict guarantee for everything.
ANY_SCALAR: dict[str, Any] = {
    "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]
}


def to_strict(schema: Any, *, prune: bool = True) -> Any:
    """Return ``schema`` rewritten into the strict subset.

    ``prune`` drops ``$defs`` no ``$ref`` can reach, which is most of them.
    """
    rewritten = _rewrite(schema)
    if prune and isinstance(rewritten, dict) and "$defs" in rewritten:
        rewritten["$defs"] = _reachable_defs(rewritten)
    return rewritten


def _enum_type(members: list[Any]) -> Any:
    """Infer the ``type`` an enum needs, from its own members."""
    kinds = {type(member) for member in members if member is not None}
    if kinds == {bool}:
        return "boolean"
    if kinds == {int}:
        return "integer"
    if kinds == {float} or kinds == {int, float}:
        return "number"
    if kinds == {str}:
        return "string"
    return ["string", "number", "boolean"]


def _reachable_defs(root: dict[str, Any]) -> dict[str, Any]:
    """Keep only the definitions some ``$ref`` can actually reach."""
    defs = root["$defs"]
    wanted: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.split("/")[-1]
                if name not in wanted and name in defs:
                    wanted.add(name)
                    visit(defs[name])
            for key, value in node.items():
                if key != "$defs":
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit({key: value for key, value in root.items() if key != "$defs"})
    return {name: defs[name] for name in sorted(wanted)}


def _rewrite(schema: Any) -> Any:
    if schema is True:
        # `true` accepts anything, which strict mode has no way to express. The only
        # place it appears is an open value slot, so it becomes the scalar union that
        # slot can actually hold.
        return dict(ANY_SCALAR)
    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in UNSUPPORTED_KEYWORDS:
            continue
        if key == "oneOf":
            # Same meaning for a discriminated union: exactly one branch matches
            # anyway, because each carries a distinct `kind`.
            out["anyOf"] = [_rewrite(branch) for branch in value]
        elif key == "const":
            out["enum"] = [value]
        elif key == "properties":
            out["properties"] = {name: _rewrite(sub) for name, sub in value.items()}
        elif key == "$defs":
            out["$defs"] = {name: _rewrite(sub) for name, sub in value.items()}
        elif key in ("items", "additionalProperties"):
            out[key] = _rewrite(value) if isinstance(value, dict) else value
        elif key == "anyOf":
            out["anyOf"] = [_rewrite(branch) for branch in value]
        else:
            out[key] = value

    if "properties" in out:
        declared = list(out["properties"])
        previously_required = set(schema.get("required", declared))
        for name in declared:
            if name not in previously_required:
                out["properties"][name] = _nullable(out["properties"][name])
        # Strict mode requires every property to be listed; optionality now lives in
        # the union with null, which the parsers already read as absent.
        out["required"] = declared
        out["additionalProperties"] = False

    if "enum" in out and "type" not in out and "anyOf" not in out:
        # Plain JSON Schema infers the type from the members; strict mode wants it said.
        out["type"] = _enum_type(list(out["enum"]))

    if not out or set(out) <= {"description", "title"}:
        # An empty schema means "any JSON value", which strict mode cannot express.
        return {**out, **ANY_SCALAR}
    return out


def _nullable(subschema: dict[str, Any]) -> dict[str, Any]:
    """Allow ``null`` for a property that used to be optional.

    Arrays are exempt: an empty array already means "nothing here", so they stay
    non-nullable. That is not only tidier — ``{"type": ["array", "null"]}`` is rejected
    outright when it appears inside an array of ``$ref``, though it is accepted at the
    top level, so relying on it makes acceptance depend on nesting depth. Any
    ``minItems`` is dropped with the nullability, since an absent list must be able to
    arrive as ``[]``.
    """
    if subschema.get("type") == "array" or "array" in (subschema.get("type") or ()):
        return {key: value for key, value in subschema.items() if key != "minItems"}
    if "anyOf" in subschema:
        branches = list(subschema["anyOf"])
        if {"type": "null"} not in branches:
            branches.append({"type": "null"})
        return {**subschema, "anyOf": branches}
    if "type" in subschema and isinstance(subschema["type"], str):
        return {**subschema, "type": [subschema["type"], "null"]}
    # A `$ref` or an `enum` cannot carry a type union, so wrap it.
    return {"anyOf": [subschema, {"type": "null"}]}


def strip_nulls(value: Any) -> Any:
    """Remove the ``null`` placeholders strict mode forced into a reply.

    Strict mode makes the model emit every property, using ``null`` for the ones it has
    nothing to say about. The parsers treat a missing key and a ``null`` differently —
    an unknown key is refused — so the nulls are dropped before parsing rather than
    teaching every parser to ignore them.
    """
    if isinstance(value, dict):
        return {k: strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        # A null element is a placeholder for the same reason a null property is: no
        # array in this contract admits null members, so keeping one would only push
        # the failure into a parser that reports it less clearly.
        return [strip_nulls(item) for item in value if item is not None]
    return value
