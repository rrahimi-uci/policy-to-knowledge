"""The DMN 1.5 compiler.

Deterministic and non-agentic: it consumes admitted Policy IR plus the gate
report and emits XML. It never calls a model, never invents a hit policy, and
never widens what the gate admitted.

Target: OMG DMN 1.5, ``formal/24-01-01`` (adopted August 2024), namespace
``https://www.omg.org/spec/DMN/20230324/MODEL/``. DMN 1.6 and 1.7 exist but are
listed by OMG as beta, so they are deliberately not targeted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from policy_ir.enums import FEEL_TYPE_NAMES, CompilerProfile, HitPolicy, Status
from policy_ir.ids import SCHEMA_VERSION, ncname
from policy_ir.models import (
    AtomicPolicyClause,
    DataDefinition,
    DecisionModelCandidate,
    PolicyIR,
)
from policy_ir.feel import feel_name, literal_to_feel, to_feel, unary_test
from policy_ir.tabular import decompose, row_condition
from validation import blockers as codes
from validation.evidence_gate import Blocker, GateReport

from .xmlwriter import Element, serialize

DMN_MODEL_NS = "https://www.omg.org/spec/DMN/20230324/MODEL/"
DMN_DI_NS = "https://www.omg.org/spec/DMN/20230324/DMNDI/"
FEEL_NS = "https://www.omg.org/spec/DMN/20230324/FEEL/"
DMN_SPEC = "OMG DMN 1.5 (formal/24-01-01)"

EXPORTER = "pipeline-p2c"
EXPORTER_VERSION = SCHEMA_VERSION

#: Blockers that make an artefact reviewable but not executable. Everything else
#: is structural: emitting it would produce a model whose meaning is unknown.
REVIEWABLE_CODES = frozenset(
    {
        codes.EVIDENCE_NOT_EXACT,
        codes.MATCH_STATUS_OVERSTATED,
        codes.LITERAL_NOT_ATTESTED,
        codes.MODALITY_NOT_ATTESTED,
        codes.PROPOSED_ELEMENT_IN_EXECUTABLE,
    }
)


@dataclass(frozen=True)
class CompiledArtifact:
    """One emitted file plus what went into it and what was left out."""

    filename: str
    xml: str
    emitted_ids: tuple[str, ...] = ()
    skipped: tuple[Blocker, ...] = ()
    trace: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.emitted_ids


def _reviewable(report_blockers: Iterable[Blocker]) -> bool:
    return all(blocker.code in REVIEWABLE_CODES for blocker in report_blockers)


def _decision_is_emittable(
    decision: DecisionModelCandidate,
    report: GateReport,
    profile: CompilerProfile,
) -> tuple[bool, tuple[Blocker, ...]]:
    """Decide whether a decision may be emitted under ``profile``."""
    decision_report = report.decisions.get(decision.decision_id)
    if decision_report is None:
        return False, (
            Blocker(codes.ROW_NOT_ADMITTED, decision.decision_id, "no gate report"),
        )
    if decision_report.has(Status.DMN_ELIGIBLE):
        return True, ()
    if profile is CompilerProfile.EXECUTABLE_SUBSET:
        return False, decision_report.blockers
    row_blockers: list[Blocker] = []
    for clause_id in decision.decision_rule_refs:
        clause_report = report.clauses.get(clause_id)
        if clause_report is not None:
            row_blockers.extend(clause_report.blockers)
    hard = [
        blocker
        for blocker in (*decision_report.blockers, *row_blockers)
        # A decision-level ROW_NOT_ADMITTED is explained by the row's own
        # blockers, which are judged here directly.
        if blocker.code != codes.ROW_NOT_ADMITTED
    ]
    if _reviewable(hard):
        return True, ()
    return False, tuple(hard)


def _review_reasons(
    decision: DecisionModelCandidate, report: GateReport
) -> tuple[str, ...]:
    """Collect the codes a reviewer needs, including the ones on the rows.

    A decision-level ``row_not_admitted`` only says "look at the row"; the useful
    reason lives on the clause. Surfacing both means the annotation in the emitted
    file explains itself without cross-referencing the report.
    """
    found: set[str] = set()
    element_report = report.decisions.get(decision.decision_id)
    if element_report is not None:
        found.update(
            blocker.code
            for blocker in element_report.blockers
            if blocker.code != codes.ROW_NOT_ADMITTED
        )
    for clause_id in decision.decision_rule_refs:
        clause_report = report.clauses.get(clause_id)
        if clause_report is not None:
            found.update(blocker.code for blocker in clause_report.blockers)
    return tuple(sorted(found))


def _emittable_rows(
    decision: DecisionModelCandidate,
    ir: PolicyIR,
    report: GateReport,
    profile: CompilerProfile,
) -> tuple[tuple[AtomicPolicyClause, ...], tuple[Blocker, ...]]:
    clauses = ir.clause_index()
    kept: list[AtomicPolicyClause] = []
    skipped: list[Blocker] = []
    for clause_id in decision.decision_rule_refs:
        clause = clauses.get(clause_id)
        clause_report = report.clauses.get(clause_id)
        if clause is None or clause_report is None:
            skipped.append(Blocker(codes.ROW_NOT_ADMITTED, clause_id, "clause is unknown"))
            continue
        if clause_report.has(Status.DMN_ELIGIBLE):
            kept.append(clause)
            continue
        if profile is CompilerProfile.REVIEW and _reviewable(clause_report.blockers):
            kept.append(clause)
            continue
        skipped.extend(clause_report.blockers)
    return tuple(kept), tuple(skipped)


def _item_definition_name(definition: DataDefinition) -> str:
    return ncname(f"t{feel_name(definition.name)}")


def _needs_item_definition(definition: DataDefinition) -> bool:
    return bool(definition.allowed_values) or definition.minimum is not None or definition.maximum is not None


def _type_ref(definition: DataDefinition) -> str:
    if _needs_item_definition(definition):
        return _item_definition_name(definition)
    return FEEL_TYPE_NAMES[definition.type]


def _allowed_values_text(definition: DataDefinition) -> str | None:
    if definition.allowed_values:
        return ", ".join(literal_to_feel(value) for value in definition.allowed_values)
    if definition.minimum is not None and definition.maximum is not None:
        return f"[{literal_to_feel(definition.minimum)}..{literal_to_feel(definition.maximum)}]"
    if definition.minimum is not None:
        return f">= {literal_to_feel(definition.minimum)}"
    if definition.maximum is not None:
        return f"<= {literal_to_feel(definition.maximum)}"
    return None


def _resolved_hit_policy(decision: DecisionModelCandidate) -> HitPolicy:
    return decision.proposed_hit_policy


def compile_dmn(
    ir: PolicyIR,
    report: GateReport,
    *,
    profile: CompilerProfile = CompilerProfile.EXECUTABLE_SUBSET,
    model_name: str = "PolicyDecisions",
    namespace: str = "urn:p2c:decisions",
    filename: str = "decisions.dmn",
) -> CompiledArtifact:
    """Compile admitted decisions into a single DMN 1.5 definitions document."""
    definitions_index = ir.data_definition_index()
    names = {key: feel_name(value.name) for key, value in definitions_index.items()}

    emitted: list[DecisionModelCandidate] = []
    skipped: list[Blocker] = []
    row_map: dict[str, tuple[AtomicPolicyClause, ...]] = {}
    for decision in sorted(ir.decisions, key=lambda d: d.decision_id):
        allowed, why = _decision_is_emittable(decision, report, profile)
        if not allowed:
            skipped.extend(why)
            continue
        rows, row_skips = _emittable_rows(decision, ir, report, profile)
        skipped.extend(row_skips)
        if not rows:
            skipped.append(
                Blocker(
                    codes.NO_DECISION_ROWS,
                    decision.decision_id,
                    "no row survived admission, so the decision is not emitted",
                )
            )
            continue
        emitted.append(decision)
        row_map[decision.decision_id] = rows

    used_inputs: set[str] = set()
    for decision in emitted:
        used_inputs.update(decision.input_data_refs)

    root = Element(
        "definitions",
        {
            "xmlns": DMN_MODEL_NS,
            "xmlns:dmndi": DMN_DI_NS,
            "id": ncname(f"definitions_{model_name}"),
            "name": model_name,
            "namespace": namespace,
            "expressionLanguage": FEEL_NS,
            "typeLanguage": FEEL_NS,
            "exporter": EXPORTER,
            "exporterVersion": EXPORTER_VERSION,
        },
    )

    # itemDefinition* must precede drgElement* in tDefinitions.
    for input_id in sorted(used_inputs):
        definition = definitions_index.get(input_id)
        if definition is None or not _needs_item_definition(definition):
            continue
        item = root.child(
            "itemDefinition",
            {"id": ncname(f"item_{input_id}"), "name": _item_definition_name(definition)},
        )
        item.child("typeRef", None, FEEL_TYPE_NAMES[definition.type])
        allowed_text = _allowed_values_text(definition)
        if allowed_text:
            item.child("allowedValues", {"id": ncname(f"allowed_{input_id}")}).child(
                "text", None, allowed_text
            )

    for decision in emitted:
        output = decision.output_definition
        if output.allowed_values:
            item = root.child(
                "itemDefinition",
                {
                    "id": ncname(f"item_out_{decision.decision_id}"),
                    "name": ncname(f"t{feel_name(output.name)}"),
                },
            )
            item.child("typeRef", None, FEEL_TYPE_NAMES[output.type])
            item.child("allowedValues", {"id": ncname(f"allowed_out_{decision.decision_id}")}).child(
                "text", None, ", ".join(literal_to_feel(v) for v in output.allowed_values)
            )

    for input_id in sorted(used_inputs):
        definition = definitions_index.get(input_id)
        if definition is None:
            continue
        node = root.child(
            "inputData", {"id": input_id, "name": names.get(input_id, input_id)}
        )
        node.child(
            "variable",
            {
                "id": ncname(f"var_{input_id}"),
                "name": names.get(input_id, input_id),
                "typeRef": _type_ref(definition),
            },
        )

    authorities = sorted(
        {
            authority
            for decision in emitted
            for authority in decision.authority_refs
        }
    )
    entities = ir.entity_index()
    for authority in authorities:
        entity = entities.get(authority)
        root.child(
            "knowledgeSource",
            {
                "id": ncname(f"ks_{authority}"),
                "name": entity.name if entity else authority,
            },
        )

    trace: dict[str, object] = {"specification": DMN_SPEC, "profile": profile.value, "decisions": {}}

    for decision in emitted:
        rows = row_map[decision.decision_id]
        decision_report = report.decisions.get(decision.decision_id)
        executable = bool(decision_report and decision_report.has(Status.DMN_ELIGIBLE))
        node = Element("decision", {"id": decision.decision_id, "name": decision.name})
        if not executable:
            reasons = ", ".join(_review_reasons(decision, report))
            node.child(
                "description",
                None,
                "REVIEW ONLY - not admitted for execution"
                + (f" ({reasons})" if reasons else ""),
            )
        node.child("question", None, decision.question)
        output = decision.output_definition
        output_type_ref = (
            ncname(f"t{feel_name(output.name)}")
            if output.allowed_values
            else FEEL_TYPE_NAMES[output.type]
        )
        node.child(
            "variable",
            {
                "id": ncname(f"var_out_{decision.decision_id}"),
                "name": feel_name(output.name),
                "typeRef": output_type_ref,
            },
        )
        for input_id in decision.input_data_refs:
            requirement = node.child(
                "informationRequirement",
                {"id": ncname(f"ir_{decision.decision_id}_{input_id}")},
            )
            requirement.child("requiredInput", {"href": f"#{input_id}"})
        for required in decision.required_decision_refs:
            requirement = node.child(
                "informationRequirement",
                {"id": ncname(f"ird_{decision.decision_id}_{required}")},
            )
            requirement.child("requiredDecision", {"href": f"#{required}"})
        for authority in decision.authority_refs:
            requirement = node.child(
                "authorityRequirement",
                {"id": ncname(f"ar_{decision.decision_id}_{authority}")},
            )
            requirement.child("requiredAuthority", {"href": f"#{ncname('ks_' + authority)}"})

        table_attributes = {
            "id": ncname(f"table_{decision.decision_id}"),
            "hitPolicy": _resolved_hit_policy(decision).value,
            "outputLabel": output.name,
            "typeRef": output_type_ref,
        }
        if decision.aggregation is not None:
            table_attributes["aggregation"] = decision.aggregation.value
        table = node.child("decisionTable", table_attributes)

        for input_id in decision.input_data_refs:
            definition = definitions_index.get(input_id)
            clause_element = table.child(
                "input",
                {
                    "id": ncname(f"in_{decision.decision_id}_{input_id}"),
                    "label": definition.name if definition else input_id,
                },
            )
            expression = clause_element.child(
                "inputExpression",
                {
                    "id": ncname(f"inexpr_{decision.decision_id}_{input_id}"),
                    "typeRef": _type_ref(definition) if definition else "Any",
                },
            )
            expression.child("text", None, names.get(input_id, input_id))

        table.child(
            "output",
            {
                "id": ncname(f"out_{decision.decision_id}"),
                "name": feel_name(output.name),
                "typeRef": output_type_ref,
            },
        )
        table.child("annotation", {"name": "policy_clause"})

        rule_trace: list[dict[str, object]] = []
        for clause in rows:
            rule = table.child("rule", {"id": ncname(f"rule_{clause.clause_id}")})
            condition = clause.condition_ast
            assert condition is not None  # guaranteed by DMN eligibility
            atoms = decompose(row_condition(condition, clause.exception_ast))
            for input_id in decision.input_data_refs:
                entries = list(atoms.get(input_id, ()))
                text = unary_test(entries)
                rule.child(
                    "inputEntry",
                    {"id": ncname(f"ie_{clause.clause_id}_{input_id}")},
                ).child("text", None, text)
            rule.child(
                "outputEntry", {"id": ncname(f"oe_{clause.clause_id}")}
            ).child("text", None, to_feel(clause.effect_ast, names))  # type: ignore[arg-type]
            annotation_text = clause.clause_id
            if clause.exception_ast is not None:
                annotation_text += " (exception folded into the row)"
            rule.child("annotationEntry").child("text", None, annotation_text)
            rule_trace.append(
                {
                    "rule_id": ncname(f"rule_{clause.clause_id}"),
                    "clause_id": clause.clause_id,
                    "evidence_ids": list(clause.all_evidence_ids()),
                    "legacy_rule_ids": list(clause.legacy_rule_ids),
                }
            )
        root.append(node)
        trace["decisions"][decision.decision_id] = {  # type: ignore[index]
            "executable": executable,
            "hit_policy": _resolved_hit_policy(decision).value,
            "inputs": list(decision.input_data_refs),
            "rules": rule_trace,
        }

    return CompiledArtifact(
        filename=filename,
        xml=serialize(root),
        emitted_ids=tuple(decision.decision_id for decision in emitted),
        skipped=tuple(skipped),
        trace=trace,
    )
