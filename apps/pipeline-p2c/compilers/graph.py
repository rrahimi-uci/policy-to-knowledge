"""The legacy-compatible knowledge graph projection.

Existing Explorer and API consumers read the shape that ``agent-5-optimized``
produces today, so the migration keeps that shape and adds to it rather than
replacing it. Two rules govern this projection:

* **Nothing is lost.** Every clause reaches the graph if it is schema-valid, along
  with all of its supporting spans and its legacy rule IDs, so a historical ID
  keeps resolving.
* **Nothing is overstated.** Each rule carries its real ``compilation_status`` and
  its blockers. A clause that failed the gate appears in the graph — the product
  keeps working — but it is never labelled executable.

The legacy ``rule_type`` field is a single string, which is what forced the
orthogonal axes in the first place. It is populated from ``semantic_kind`` and the
other axes travel alongside it, so no information is discarded on the way out.
"""

from __future__ import annotations

from typing import Any, Mapping

from policy_ir.enums import Modality, Status
from policy_ir.expressions import referenced_variable_ids
from policy_ir.feel import FeelError, feel_name, to_feel
from policy_ir.ids import SCHEMA_VERSION
from policy_ir.models import AtomicPolicyClause, PolicyIR
from validation.evidence_gate import GateReport

ARTIFACT_ROLE = "legacy_projection"
PROJECTOR_VERSION = "p2c-graph-1.0.0"


def _feel_or_empty(clause: AtomicPolicyClause, attribute: str, names: Mapping[str, str]) -> str:
    expression = getattr(clause, attribute)
    if expression is None:
        return ""
    try:
        return to_feel(expression, names)
    except FeelError:
        return ""


def _role_prose(clause: AtomicPolicyClause, ir: PolicyIR, role: str) -> str:
    index = ir.evidence_index()
    parts = [
        index[evidence_id].exact_text
        for evidence_id in clause.evidence.get(role, ())
        if evidence_id in index
    ]
    return " ".join(parts)


def _source_references(clause: AtomicPolicyClause, ir: PolicyIR) -> list[dict[str, Any]]:
    """Emit the multi-span form. A list is first class; nothing is flattened."""
    index = ir.evidence_index()
    documents = ir.document_index()
    references: list[dict[str, Any]] = []
    for evidence_id in clause.all_evidence_ids():
        span = index.get(evidence_id)
        if span is None:
            continue
        document = documents.get(span.document_id)
        references.append(
            {
                "evidence_id": span.evidence_id,
                "document_id": span.document_id,
                "source_uri": document.source_uri if document else None,
                "source_sha256": document.source_sha256 if document else None,
                "chunk_id": span.chunk_id,
                "chunk_sha256": span.chunk_sha256,
                "chunk_path": span.section_path or span.chunk_id,
                "section": span.section_path,
                "char_start": span.char_start,
                "char_end": span.char_end,
                "page_start": span.page_start,
                "page_end": span.page_end,
                "source_text": span.exact_text,
                "semantic_role": span.semantic_role.value,
                "match_status": span.match_status.value,
            }
        )
    return references


def project_graph(
    ir: PolicyIR,
    report: GateReport,
    *,
    graph_name: str = "policy_graph",
) -> dict[str, Any]:
    """Build the legacy-shaped graph document from admitted Policy IR."""
    definitions = ir.data_definition_index()
    names = {key: feel_name(value.name) for key, value in definitions.items()}
    entities = ir.entity_index()

    business_rules: list[dict[str, Any]] = []
    for clause in ir.clauses:
        element_report = report.clauses.get(clause.clause_id)
        statuses = element_report.statuses if element_report else frozenset()
        if Status.GRAPH_ELIGIBLE not in statuses:
            # Schema-invalid records are not silently dropped either: they are
            # reported, just not projected as rules.
            continue
        referenced = sorted(
            {
                variable
                for attribute in ("condition_ast", "effect_ast", "exception_ast")
                if getattr(clause, attribute) is not None
                for variable in referenced_variable_ids(getattr(clause, attribute))
            }
        )
        entity = entities.get(clause.subject_ref) if clause.subject_ref else None
        business_rules.append(
            {
                "rule_id": clause.clause_id,
                "rule_name": clause.display_text[:120],
                "rule_type": clause.semantic_kind.value,
                "description": clause.display_text,
                "conditions": _role_prose(clause, ir, "condition"),
                "consequences": _role_prose(clause, ir, "effect"),
                "exceptions": _role_prose(clause, ir, "exception"),
                "conditions_feel": _feel_or_empty(clause, "condition_ast", names),
                "consequences_feel": _feel_or_empty(clause, "effect_ast", names),
                "exceptions_feel": _feel_or_empty(clause, "exception_ast", names),
                "source_reference": _source_references(clause, ir),
                "mandatory": clause.modality in (Modality.OBLIGATION, Modality.PROHIBITION),
                "modality": clause.modality.value,
                "semantic_kind": clause.semantic_kind.value,
                "effect": clause.effect.value,
                "lifecycle": clause.lifecycle.value,
                "compilation_intent": clause.compilation_intent.value,
                "effective_date": clause.effective_period.start,
                "expiration_date": clause.effective_period.end,
                # Legacy consumers read flat lists; the structured form travels
                # alongside so a v2 reader loses nothing.
                "jurisdiction": [
                    value
                    for dimension in clause.scope.dimensions
                    if dimension.name == "jurisdiction"
                    for value in dimension.values
                ],
                "applicability_scope": [
                    f"{dimension.name}{'!=' if dimension.negated else '='}"
                    f"{'|'.join(dimension.values)}"
                    for dimension in clause.scope.dimensions
                ],
                "scope": clause.scope.to_dict(),
                "authority_ref": clause.authority_ref,
                "data_points_required": [names.get(v, v) for v in referenced],
                "data_definitions_required": referenced,
                "entity_or_relationship": entity.name if entity else None,
                "entity_type": entity.category.value if entity else None,
                "related_rules": list(clause.cross_reference_targets),
                "canonical_rule_id": clause.clause_id,
                "legacy_rule_ids": list(clause.legacy_rule_ids),
                "reference_verified": Status.PROVENANCE_EXACT in statuses,
                "reference_verification_note": (
                    "every cited span matches its document hash and offsets"
                    if Status.PROVENANCE_EXACT in statuses
                    else "at least one cited span could not be exactly anchored"
                ),
                "compilation_status": {
                    "graph_eligible": Status.GRAPH_ELIGIBLE in statuses,
                    "provenance_exact": Status.PROVENANCE_EXACT in statuses,
                    "semantic_supported": Status.SEMANTIC_SUPPORTED in statuses,
                    "dmn_eligible": Status.DMN_ELIGIBLE in statuses,
                    "bpmn_eligible": Status.BPMN_ELIGIBLE in statuses,
                },
                "blockers": [b.to_dict() for b in (element_report.blockers if element_report else ())],
            }
        )

    entity_types: dict[str, Any] = {}
    for entity in ir.entity_types:
        legacy_key = entity.name.upper().replace(" ", "_")
        attributes = [
            definitions[data_id].name
            for data_id in entity.data_definition_ids
            if data_id in definitions
        ]
        owned = [
            definition
            for definition in ir.data_definitions
            if definition.owning_entity_id == entity.entity_type_id
        ]
        entity_types[legacy_key] = {
            "definition": entity.definition,
            "attributes": attributes or [definition.name for definition in owned],
            "examples": [],
            "business_rules": [
                clause.clause_id
                for clause in ir.clauses
                if clause.subject_ref == entity.entity_type_id
            ],
            "entity_category": entity.category.value,
            "provenance": entity.provenance.value,
            "attribute_definitions": [
                {
                    "data_definition_id": definition.data_definition_id,
                    "name": definition.name,
                    "type": definition.type.value,
                    "unit": definition.unit,
                    "null_policy": definition.null_policy.value,
                    "provenance": definition.provenance.value,
                }
                for definition in owned
            ],
        }

    dependencies = [
        {
            "edge_id": edge.edge_id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "source_rule_id": edge.source_id,
            "target_rule_id": edge.target_id,
            "dependency_type": edge.kind.value,
            "derivation_method": edge.derivation_method.value,
            "description": edge.direction_semantics,
            "evidence_ids": list(edge.evidence_ids),
            "validated": report.dependency_admitted(edge.edge_id)
            and edge.derivation_method.value
            in ("explicit_cross_reference", "deterministic_shared_variable", "explicit_temporal_language"),
        }
        for edge in ir.dependencies
    ]

    return {
        "metadata": {
            "graph_name": graph_name,
            "policy_ir_version": SCHEMA_VERSION,
            "artifact_role": ARTIFACT_ROLE,
            "projector_version": PROJECTOR_VERSION,
            "total_rules": len(business_rules),
            "total_entity_types": len(entity_types),
            "total_dependencies": len(dependencies),
            "documents": [
                {
                    "document_id": document.document_id,
                    "source_uri": document.source_uri,
                    "source_sha256": document.source_sha256,
                    "canonical_text_sha256": document.canonical_text_sha256,
                    "license_record_id": document.license_record_id,
                }
                for document in ir.documents
            ],
            "note": (
                "Prose fields carry the cited source text; the *_feel fields carry the "
                "typed form. compilation_status is authoritative for executability."
            ),
        },
        "business_rules": business_rules,
        "entity_types": entity_types,
        "relationships": [],
        "dependency_details": {
            "dependencies": dependencies,
            "dependency_chains": [],
            "conflicts": [
                dependency
                for dependency in dependencies
                if dependency["dependency_type"] == "conflict"
            ],
        },
        "optimization_summary": {
            "deduplicated_rules": 0,
            "note": "Policy IR canonicalisation happens before projection.",
        },
    }
