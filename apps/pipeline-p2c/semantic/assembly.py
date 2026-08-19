"""Schema-constrained, file-backed semantic proposal assembly.

Providers may propose semantic records, but they cannot add source documents, chunks,
or evidence spans.  All citations must resolve to evidence already constructed by the
application.  The normal evidence gate remains the only authority for admission.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from policy_ir._parsing import SchemaError, as_tuple, check_keys
from policy_ir.models import (
    AtomicPolicyClause, DataDefinition, DecisionModelCandidate, DependencyEdge,
    EntityMention, EntityType, PolicyIR, ProcessFragmentCandidate, SemanticRelation,
)


class AssemblyError(ValueError):
    """A proposal attempts to alter source-owned state or is structurally invalid."""


_FIELDS = {
    "entity_types": EntityType,
    "entity_mentions": EntityMention,
    "data_definitions": DataDefinition,
    "clauses": AtomicPolicyClause,
    "decisions": DecisionModelCandidate,
    "processes": ProcessFragmentCandidate,
    "dependencies": DependencyEdge,
    "semantic_relations": SemanticRelation,
}


def proposal_schema() -> dict[str, Any]:
    """Generated JSON Schema for a provider's semantic additions."""
    from policy_ir.jsonschema import record_schema

    defs = {
        record.__name__: record_schema(record)
        for record in sorted(set(_FIELDS.values()), key=lambda item: item.__name__)
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Policy IR semantic proposal",
        "description": "Typed additions only; source artifacts and evidence spans are application-owned.",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            name: {"type": "array", "items": {"$ref": f"#/$defs/{record.__name__}"}}
            for name, record in sorted(_FIELDS.items())
        },
        "$defs": defs,
    }


def assemble_proposal(ir: PolicyIR, proposal: Mapping[str, Any]) -> PolicyIR:
    """Return a new IR with parsed additions, rejecting ID and evidence fabrication."""
    try:
        check_keys(proposal, "SemanticProposal", [], list(_FIELDS))
        additions = {
            name: as_tuple(proposal.get(name, ()), "SemanticProposal", name, record.from_dict)
            for name, record in _FIELDS.items()
        }
    except SchemaError as exc:
        raise AssemblyError(str(exc)) from exc

    known_evidence = set(ir.evidence_index())
    for name, records in additions.items():
        for record in records:
            cited = getattr(record, "evidence_ids", ())
            if name == "clauses":
                cited = record.all_evidence_ids()
            unknown = sorted(set(cited) - known_evidence)
            if unknown:
                raise AssemblyError(f"{name} cites evidence not owned by this IR: {unknown}")

    merged = {
        name: tuple(getattr(ir, name)) + tuple(records) for name, records in additions.items()
    }
    out = replace(ir, **merged)
    ids: list[str] = []
    for name, records in _FIELDS.items():
        key = {
            "entity_types": "entity_type_id", "entity_mentions": "mention_id",
            "data_definitions": "data_definition_id", "clauses": "clause_id",
            "decisions": "decision_id", "processes": "fragment_id",
            "dependencies": "edge_id", "semantic_relations": "relation_id",
        }[name]
        ids.extend(getattr(item, key) for item in getattr(out, name))
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise AssemblyError(f"semantic proposal creates duplicate IDs: {duplicates}")
    return out
