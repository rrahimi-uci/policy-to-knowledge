"""Import a legacy ``optimized_compliance_knowledge_graph.json`` into Policy IR.

The adapter's whole job is to import without overclaiming. Historical records hold
prose conditions, untyped attribute names, model-inferred dependencies and source
references whose offsets were sometimes repaired by fuzzy search. None of that can
become a typed expression, so this adapter:

* **fabricates no expressions.** Prose stays prose in ``display_text``; no
  ``condition_ast`` is ever synthesised from a sentence.
* **fabricates no evidence.** The original bytes are not available, so no
  :class:`~policy_ir.models.EvidenceSpan` is created. Legacy clauses therefore
  cannot be provenance-exact, which is the honest outcome.
* **guesses no classifications.** Unrecognised rule types become
  ``SemanticKind.UNCLASSIFIED`` and unrecognised entities become
  ``EntityCategory.UNCLASSIFIED`` rather than a plausible-looking label.
* **downgrades every dependency.** Legacy edges are model-inferred, so they arrive
  as ``RELATED`` candidates (except declared contradictions and overrides, which
  keep their meaning) with ``MODEL_ASSISTED_CANDIDATE`` derivation. The gate then
  refuses to give any of them executable force.

The expected outcome for most legacy rules is ``graph_only``. That is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from policy_ir.enums import (
    CompilationIntent,
    DependencyKind,
    DerivationMethod,
    Effect,
    EntityCategory,
    Lifecycle,
    Modality,
    Provenance,
    SemanticKind,
)
from policy_ir.ids import SCHEMA_VERSION, derived_id, ncname
from policy_ir.scope import Scope
from policy_ir.models import (
    AtomicPolicyClause,
    DataDefinition,
    DependencyEdge,
    EffectivePeriod,
    EntityType,
    PolicyIR,
)
from policy_ir.enums import DataType

#: Legacy ``rule_type`` values that map cleanly onto a semantic kind. Everything
#: else becomes UNCLASSIFIED; the original value is preserved in
#: ``legacy_rule_types`` on the IR metadata.
#:
#: ``eligibility`` and ``constraint`` are deliberately absent. A decision rule
#: needs a typed condition and a typed effect, and a legacy record has neither, so
#: classifying one as ``DECISION_RULE`` would create a clause that is guaranteed to
#: fail its own contract and drop out of the graph. Leaving it UNCLASSIFIED keeps
#: the rule visible and honest about what is known.
_KIND_MAP: Mapping[str, SemanticKind] = {
    "process": SemanticKind.PROCESS_FRAGMENT,
    "calculation": SemanticKind.CALCULATION,
    "validation": SemanticKind.VALIDATION,
    "documentation": SemanticKind.DOCUMENTATION_REQUIREMENT,
    "reporting": SemanticKind.DOCUMENTATION_REQUIREMENT,
    "definition": SemanticKind.AUTHORITY_STATEMENT,
    "regulatory": SemanticKind.AUTHORITY_STATEMENT,
    "compliance": SemanticKind.VALIDATION,
}

#: Legacy ``rule_type`` values that also imply a modality.
_MODALITY_MAP: Mapping[str, Modality] = {
    "prohibition": Modality.PROHIBITION,
    "definition": Modality.DEFINITION,
    "exception": Modality.PERMISSION,
}

#: Legacy dependency types keep their meaning only where it is unambiguous.
_DEPENDENCY_MAP: Mapping[str, DependencyKind] = {
    "contradictory": DependencyKind.CONFLICT,
    "override": DependencyKind.OVERRIDE,
}


@dataclass
class LegacyImport:
    """The result of importing one legacy graph."""

    ir: PolicyIR
    imported_rules: int = 0
    imported_entities: int = 0
    imported_dependencies: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def _first_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        for item in value:
            if isinstance(item, str) and item:
                return item
    return ""


def _legacy_source_texts(rule: Mapping[str, Any]) -> tuple[str, ...]:
    """Collect whatever source text the legacy record kept, in either shape.

    Legacy records store ``source_reference`` as an object in most corpora and as
    an array in a minority. Both are read here so the import loses nothing.
    """
    reference = rule.get("source_reference")
    candidates: list[Mapping[str, Any]] = []
    if isinstance(reference, Mapping):
        candidates.append(reference)
    elif isinstance(reference, Sequence) and not isinstance(reference, (str, bytes)):
        candidates.extend(item for item in reference if isinstance(item, Mapping))
    texts: list[str] = []
    for candidate in candidates:
        for key in ("source_text", "text", "quote"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
                break
    return tuple(texts)


def _clause_for(rule: Mapping[str, Any], index: int) -> AtomicPolicyClause:
    legacy_id = str(rule.get("rule_id") or f"legacy_rule_{index}")
    legacy_type = str(rule.get("rule_type") or "").lower()
    semantic_kind = _KIND_MAP.get(legacy_type, SemanticKind.UNCLASSIFIED)
    modality = _MODALITY_MAP.get(legacy_type)
    if modality is None:
        modality = Modality.OBLIGATION if rule.get("mandatory") else Modality.PERMISSION
    display = _first_str(rule.get("description")) or _first_str(rule.get("rule_name")) or legacy_id
    return AtomicPolicyClause(
        clause_id=derived_id("legacy", legacy_id, legacy_type),
        modality=modality,
        semantic_kind=semantic_kind,
        # A legacy record does not state its effect in a typed way; recording
        # NO_DIRECT_EFFECT is the honest placeholder and blocks nothing that was
        # not already blocked.
        effect=Effect.NO_DIRECT_EFFECT,
        display_text=display,
        evidence={},
        lifecycle=Lifecycle.UNKNOWN,
        compilation_intent=CompilationIntent.GRAPH_ONLY,
        # Legacy jurisdiction and applicability are free text with no declared axis,
        # so they cannot become a typed Scope without inventing a dimension. They are
        # preserved as prose in the projection and the clause scope stays universal.
        scope=Scope(),
        effective_period=EffectivePeriod(
            start=rule.get("effective_date") if isinstance(rule.get("effective_date"), str) else None,
            end=rule.get("expiration_date") if isinstance(rule.get("expiration_date"), str) else None,
        ),
        legacy_rule_ids=(legacy_id,),
    )


def _entity_for(name: str, body: Mapping[str, Any]) -> EntityType:
    return EntityType(
        entity_type_id=ncname(f"legacy_entity_{name}"),
        name=name,
        category=EntityCategory.UNCLASSIFIED,
        provenance=Provenance.UNRESOLVED,
        definition=_first_str(body.get("definition")),
    )


def _data_definitions_for(name: str, body: Mapping[str, Any], entity_id: str) -> tuple[DataDefinition, ...]:
    """Import attribute *names* only.

    A legacy attribute is a bare string, so its type is unknown. Importing it as
    ``STRING`` with ``Provenance.UNRESOLVED`` keeps it visible in the graph while
    guaranteeing the gate refuses it as a DMN input.
    """
    attributes = body.get("attributes")
    if not isinstance(attributes, Sequence) or isinstance(attributes, (str, bytes)):
        return ()
    out: list[DataDefinition] = []
    for attribute in attributes:
        if not isinstance(attribute, str) or not attribute.strip():
            continue
        out.append(
            DataDefinition(
                data_definition_id=derived_id("legacy_data", name, attribute),
                name=attribute,
                type=DataType.STRING,
                provenance=Provenance.UNRESOLVED,
                owning_entity_id=entity_id,
            )
        )
    return tuple(out)


def import_legacy_graph(graph: Mapping[str, Any], *, graph_name: str = "legacy") -> LegacyImport:
    """Import a legacy optimized knowledge graph as unevidenced IR candidates."""
    rules = graph.get("business_rules")
    rules = rules if isinstance(rules, Sequence) else []
    clauses: list[AtomicPolicyClause] = []
    legacy_types: dict[str, int] = {}
    source_text_count = 0
    for index, rule in enumerate(rules):
        if not isinstance(rule, Mapping):
            continue
        clauses.append(_clause_for(rule, index))
        legacy_type = str(rule.get("rule_type") or "")
        legacy_types[legacy_type] = legacy_types.get(legacy_type, 0) + 1
        source_text_count += len(_legacy_source_texts(rule))

    entity_types: list[EntityType] = []
    data_definitions: list[DataDefinition] = []
    raw_entities = graph.get("entity_types")
    if isinstance(raw_entities, Mapping):
        for name, body in sorted(raw_entities.items()):
            if not isinstance(body, Mapping):
                continue
            entity = _entity_for(str(name), body)
            entity_types.append(entity)
            data_definitions.extend(
                _data_definitions_for(str(name), body, entity.entity_type_id)
            )

    clause_by_legacy: dict[str, str] = {}
    for clause in clauses:
        for legacy_id in clause.legacy_rule_ids:
            clause_by_legacy[legacy_id] = clause.clause_id

    dependencies: list[DependencyEdge] = []
    details = graph.get("dependency_details")
    raw_edges = details.get("dependencies") if isinstance(details, Mapping) else None
    if isinstance(raw_edges, Sequence):
        for index, edge in enumerate(raw_edges):
            if not isinstance(edge, Mapping):
                continue
            legacy_type = str(edge.get("dependency_type") or "related")
            source = clause_by_legacy.get(str(edge.get("source_rule_id") or edge.get("source_id")))
            target = clause_by_legacy.get(str(edge.get("target_rule_id") or edge.get("target_id")))
            if not source or not target:
                continue
            dependencies.append(
                DependencyEdge(
                    edge_id=derived_id("legacy_dep", source, target, legacy_type, str(index)),
                    source_id=source,
                    target_id=target,
                    kind=_DEPENDENCY_MAP.get(legacy_type, DependencyKind.RELATED),
                    derivation_method=DerivationMethod.MODEL_ASSISTED_CANDIDATE,
                    direction_semantics=f"legacy dependency_type={legacy_type}",
                )
            )

    ir = PolicyIR(
        schema_version=SCHEMA_VERSION,
        entity_types=tuple(entity_types),
        data_definitions=tuple(data_definitions),
        clauses=tuple(clauses),
        dependencies=tuple(dependencies),
        metadata={
            "imported_from": graph_name,
            "artifact_role": "legacy_import_candidates",
            "legacy_rule_types": dict(sorted(legacy_types.items())),
            "legacy_source_texts_seen": source_text_count,
            "warning": (
                "No evidence spans were created: the original bytes are not available "
                "from a legacy graph, so these candidates can never be provenance-exact."
            ),
        },
    )
    notes = (
        f"imported {len(clauses)} rules with no evidence spans",
        f"{sum(1 for c in clauses if c.semantic_kind is SemanticKind.UNCLASSIFIED)} rules "
        "could not be classified",
        f"{len(dependencies)} dependencies downgraded to model-assisted candidates",
    )
    return LegacyImport(
        ir=ir,
        imported_rules=len(clauses),
        imported_entities=len(entity_types),
        imported_dependencies=len(dependencies),
        notes=notes,
    )
