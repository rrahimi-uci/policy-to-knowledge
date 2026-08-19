"""The fail-closed evidence and semantic gate.

This is the single place that decides what may be compiled. Policy IR records
carry no verdicts of their own, so nothing can mark itself eligible; a compiler
takes an IR *and* the report produced here, and refuses to emit anything the
report has not admitted.

The statuses are independent, not a ladder with one boolean at the end. A clause
can be schema-valid and provenance-exact yet fail semantic support; the legacy
graph projection deliberately accepts far less than the DMN compiler does. Keeping
them separate is what lets the product keep working while the executable subset
stays small and defensible.

Every check is deterministic and offline. Nothing here calls a model, and model
confidence is never consulted: admission depends on hashes, offsets, types and
proofs.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from policy_ir.enums import (
    EXECUTABLE_DEPENDENCY_KINDS,
    TRUSTED_DERIVATION_METHODS,
    DataType,
    DependencyKind,
    EntityCategory,
    HitPolicy,
    Lifecycle,
    MatchStatus,
    NullPolicy,
    Provenance,
    SemanticKind,
    SemanticRole,
    Status,
)
from policy_ir.expressions import Expression, referenced_variable_ids
from policy_ir.ids import sha256_text
from policy_ir.models import (
    AtomicPolicyClause,
    DecisionModelCandidate,
    PolicyIR,
    ProcessFragmentCandidate,
)
from policy_ir.feel import FeelError, feel_name, to_feel
from policy_ir.tabular import (
    NotTabular,
    Row,
    decompose,
    is_scope_input,
    prove_disjoint,
    row_condition,
    scope_atoms,
    scope_dimension_name,
)
from policy_ir.timeline import in_force_on, supersession_cycles, superseded_by
from policy_ir.typecheck import check, check_boolean, context_from_ir
from ingestion.registry import normalize_text

from . import blockers as codes
from .attestation import attested_modalities, unattested_literals
from .blockers import Blocker


@dataclass(frozen=True)
class ElementReport:
    """What the gate concluded about one element."""

    element_id: str
    statuses: frozenset[Status] = frozenset()
    blockers: tuple[Blocker, ...] = ()

    def has(self, status: Status) -> bool:
        return status in self.statuses

    def codes(self) -> tuple[str, ...]:
        return tuple(blocker.code for blocker in self.blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "element_id": self.element_id,
            "statuses": sorted(status.value for status in self.statuses),
            "blockers": [blocker.to_dict() for blocker in self.blockers],
        }


@dataclass(frozen=True)
class GateReport:
    """The complete admission record for one IR."""

    clauses: Mapping[str, ElementReport] = field(default_factory=dict)
    decisions: Mapping[str, ElementReport] = field(default_factory=dict)
    processes: Mapping[str, ElementReport] = field(default_factory=dict)
    dependencies: Mapping[str, ElementReport] = field(default_factory=dict)
    global_blockers: tuple[Blocker, ...] = ()

    # -- queries ---------------------------------------------------------
    def clause_has(self, clause_id: str, status: Status) -> bool:
        report = self.clauses.get(clause_id)
        return bool(report and report.has(status))

    def decision_has(self, decision_id: str, status: Status) -> bool:
        report = self.decisions.get(decision_id)
        return bool(report and report.has(status))

    def process_has(self, fragment_id: str, status: Status) -> bool:
        report = self.processes.get(fragment_id)
        return bool(report and report.has(status))

    def dependency_admitted(self, edge_id: str) -> bool:
        report = self.dependencies.get(edge_id)
        return bool(report and report.has(Status.SCHEMA_VALID) and not report.blockers)

    def admitted_decisions(self) -> tuple[str, ...]:
        return tuple(
            sorted(k for k, v in self.decisions.items() if v.has(Status.DMN_ELIGIBLE))
        )

    def admitted_processes(self) -> tuple[str, ...]:
        return tuple(
            sorted(k for k, v in self.processes.items() if v.has(Status.BPMN_ELIGIBLE))
        )

    @property
    def fatal(self) -> bool:
        """True when the IR itself is malformed, independent of any projection."""
        return bool(self.global_blockers)

    def all_blockers(self) -> tuple[Blocker, ...]:
        out = list(self.global_blockers)
        for group in (self.clauses, self.decisions, self.processes, self.dependencies):
            for report in group.values():
                out.extend(report.blockers)
        return tuple(out)

    def counts_by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for blocker in self.all_blockers():
            counts[blocker.code] = counts.get(blocker.code, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "clauses": {k: v.to_dict() for k, v in sorted(self.clauses.items())},
            "decisions": {k: v.to_dict() for k, v in sorted(self.decisions.items())},
            "processes": {k: v.to_dict() for k, v in sorted(self.processes.items())},
            "dependencies": {k: v.to_dict() for k, v in sorted(self.dependencies.items())},
            "global_blockers": [b.to_dict() for b in self.global_blockers],
            "blocker_counts": self.counts_by_code(),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass
class _Accumulator:
    element_id: str
    blockers: list[Blocker] = field(default_factory=list)

    def add(self, code: str, message: str, role: str | None = None) -> None:
        self.blockers.append(Blocker(code, self.element_id, message, role))

    def has(self, *codes_: str) -> bool:
        return any(blocker.code in codes_ for blocker in self.blockers)


def _duplicate_ids(ir: PolicyIR) -> list[Blocker]:
    seen: dict[str, str] = {}
    duplicates: list[Blocker] = []
    groups: tuple[tuple[str, Iterable[str]], ...] = (
        ("document", (d.document_id for d in ir.documents)),
        ("chunk", (c.chunk_id for c in ir.chunks)),
        ("evidence", (e.evidence_id for e in ir.evidence_spans)),
        ("entity_type", (e.entity_type_id for e in ir.entity_types)),
        ("data_definition", (d.data_definition_id for d in ir.data_definitions)),
        ("clause", (c.clause_id for c in ir.clauses)),
        ("decision", (d.decision_id for d in ir.decisions)),
        ("process", (p.fragment_id for p in ir.processes)),
        ("dependency", (d.edge_id for d in ir.dependencies)),
    )
    for kind, values in groups:
        for value in values:
            if value in seen:
                duplicates.append(
                    Blocker(
                        codes.DUPLICATE_ID,
                        value,
                        f"{kind} id {value!r} is already used by a {seen[value]}",
                    )
                )
            else:
                seen[value] = kind
    return duplicates


def _verify_span(
    span_id: str,
    ir: PolicyIR,
    texts: Mapping[str, str],
    accumulator: _Accumulator,
) -> bool:
    """Verify one evidence span. Returns True when it is exactly anchored."""
    span = ir.evidence_index().get(span_id)
    if span is None:
        accumulator.add(codes.UNKNOWN_EVIDENCE_ID, f"evidence {span_id!r} is not declared")
        return False
    role = span.semantic_role.value
    if span.document_id not in ir.document_index():
        accumulator.add(
            codes.UNKNOWN_DOCUMENT, f"evidence {span_id!r} cites unknown document", role
        )
        return False
    chunk = ir.chunk_index().get(span.chunk_id)
    if chunk is None:
        accumulator.add(codes.UNKNOWN_CHUNK, f"evidence {span_id!r} cites unknown chunk", role)
        return False
    if chunk.document_id != span.document_id:
        accumulator.add(
            codes.CHUNK_DOCUMENT_MISMATCH,
            f"evidence {span_id!r} chunk belongs to {chunk.document_id!r}",
            role,
        )
        return False
    if chunk.chunk_sha256 != span.chunk_sha256:
        accumulator.add(
            codes.CHUNK_HASH_MISMATCH,
            f"evidence {span_id!r} cites chunk hash {span.chunk_sha256[:12]}… but the "
            f"chunk hashes to {chunk.chunk_sha256[:12]}…",
            role,
        )
        return False
    if not (chunk.char_start <= span.char_start <= span.char_end <= chunk.char_end):
        accumulator.add(
            codes.OFFSET_OUTSIDE_CHUNK,
            f"evidence {span_id!r} offsets [{span.char_start},{span.char_end}) fall "
            f"outside chunk [{chunk.char_start},{chunk.char_end})",
            role,
        )
        return False
    text = texts.get(span.document_id)
    if text is None:
        accumulator.add(
            codes.EVIDENCE_TEXT_UNAVAILABLE,
            f"canonical text for {span.document_id!r} was not supplied, so evidence "
            f"{span_id!r} cannot be verified",
            role,
        )
        return False
    if span.char_end > len(text):
        accumulator.add(
            codes.OFFSET_OUTSIDE_DOCUMENT,
            f"evidence {span_id!r} ends at {span.char_end} but the document has "
            f"{len(text)} characters",
            role,
        )
        return False
    # Verify the chunk really hashes to what it claims, so a span cannot be
    # anchored against a chunk record that has drifted from the document.
    body = text[chunk.char_start : chunk.char_end]
    if sha256_text(body) != chunk.chunk_sha256:
        accumulator.add(
            codes.CHUNK_HASH_MISMATCH,
            f"chunk {chunk.chunk_id!r} does not hash to its recorded value",
            role,
        )
        return False
    actual = text[span.char_start : span.char_end]
    if actual == span.exact_text:
        return True
    if normalize_text(actual) == normalize_text(span.exact_text):
        if span.match_status is MatchStatus.EXACT:
            accumulator.add(
                codes.MATCH_STATUS_OVERSTATED,
                f"evidence {span_id!r} declares an exact match but only matches after "
                "normalisation",
                role,
            )
            return False
        return span.match_status is MatchStatus.NORMALIZED_EXACT
    accumulator.add(
        codes.EVIDENCE_TEXT_MISMATCH,
        f"evidence {span_id!r} cites {span.exact_text!r} but the document holds "
        f"{actual!r} at those offsets",
        role,
    )
    return False


def _role_text(clause: AtomicPolicyClause, ir: PolicyIR, roles: Sequence[SemanticRole]) -> str:
    index = ir.evidence_index()
    parts: list[str] = []
    for role in roles:
        for evidence_id in clause.evidence_for(role):
            span = index.get(evidence_id)
            if span is not None:
                parts.append(span.exact_text)
    return " ".join(parts)


#: Reasons a row is legitimately left out of a table rather than being a defect in
#: it. A decision that declares two rows and loses one to a heavier authority should
#: still compile from the winner — otherwise resolving a conflict would achieve
#: nothing.
_ROW_EXCLUDED_BY_DESIGN = frozenset(
    {
        codes.OUTRANKED_BY_AUTHORITY,
        codes.SUPERSEDED_CLAUSE,
        codes.NOT_IN_FORCE,
    }
)

_REQUIRED_EVIDENCE: tuple[tuple[str, SemanticRole], ...] = (
    ("condition_ast", SemanticRole.CONDITION),
    ("effect_ast", SemanticRole.EFFECT),
    ("exception_ast", SemanticRole.EXCEPTION),
    ("subject_ref", SemanticRole.SUBJECT),
    ("temporal_constraint", SemanticRole.TEMPORAL),
    ("authority_ref", SemanticRole.AUTHORITY),
)


def _check_clause(
    clause: AtomicPolicyClause,
    ir: PolicyIR,
    texts: Mapping[str, str],
    as_of: _dt.date | None = None,
) -> ElementReport:
    accumulator = _Accumulator(clause.clause_id)
    statuses: set[Status] = set()

    if not clause.display_text.strip():
        accumulator.add(codes.MISSING_REQUIRED_FIELD, "display_text is empty")
    if clause.semantic_kind is SemanticKind.DECISION_RULE:
        if clause.condition_ast is None:
            accumulator.add(codes.MISSING_REQUIRED_FIELD, "a decision rule needs a condition")
        if clause.effect_ast is None:
            accumulator.add(codes.MISSING_REQUIRED_FIELD, "a decision rule needs an effect")

    # Field-level evidence: a semantic field with no evidence can never be
    # admitted, whatever else is true about the clause.
    for attribute, role in _REQUIRED_EVIDENCE:
        if getattr(clause, attribute) is not None and not clause.evidence_for(role):
            accumulator.add(
                codes.MISSING_FIELD_EVIDENCE,
                f"{attribute} is present but no {role.value} evidence is cited",
                role.value,
            )
    if clause.cross_reference_targets and not clause.evidence_for(SemanticRole.CROSS_REFERENCE):
        accumulator.add(
            codes.MISSING_FIELD_EVIDENCE,
            "cross references are declared but no cross_reference evidence is cited",
            SemanticRole.CROSS_REFERENCE.value,
        )

    exact = True
    for evidence_id in clause.all_evidence_ids():
        if not _verify_span(evidence_id, ir, texts, accumulator):
            exact = False
    if not clause.all_evidence_ids():
        exact = False
        accumulator.add(
            codes.NO_EVIDENCE_CITED,
            "the clause cites no evidence, so it can enter the graph but nothing "
            "executable can follow from it",
        )
    for evidence_id in clause.all_evidence_ids():
        span = ir.evidence_index().get(evidence_id)
        if span is not None and span.match_status in (
            MatchStatus.RECOVERED,
            MatchStatus.UNRESOLVED,
        ):
            exact = False
            accumulator.add(
                codes.EVIDENCE_NOT_EXACT,
                f"evidence {evidence_id!r} is {span.match_status.value}, which cannot "
                "support an executable projection",
                span.semantic_role.value,
            )

    if not accumulator.has(
        codes.MISSING_REQUIRED_FIELD, codes.UNKNOWN_EVIDENCE_ID, codes.MISSING_FIELD_EVIDENCE
    ):
        statuses.add(Status.SCHEMA_VALID)
        statuses.add(Status.GRAPH_ELIGIBLE)
    if exact:
        statuses.add(Status.PROVENANCE_EXACT)

    context = context_from_ir(ir)
    type_errors: list[str] = []
    for attribute in ("condition_ast", "exception_ast"):
        expression = getattr(clause, attribute)
        if expression is not None:
            type_errors.extend(
                f"{attribute}: {error}" for error in check_boolean(expression, context)
            )
    if clause.effect_ast is not None:
        result = check(clause.effect_ast, context)
        type_errors.extend(f"effect_ast: {error}" for error in result.errors)
    for error in type_errors:
        accumulator.add(codes.ILL_TYPED_EXPRESSION, error)

    supporting_text = _role_text(
        clause,
        ir,
        (
            SemanticRole.CONDITION,
            SemanticRole.EFFECT,
            SemanticRole.EXCEPTION,
            SemanticRole.TEMPORAL,
            SemanticRole.SUBJECT,
        ),
    )
    expressions: list[Expression | None] = [
        clause.condition_ast,
        clause.effect_ast,
        clause.exception_ast,
    ]
    if clause.temporal_constraint is not None:
        expressions.append(clause.temporal_constraint.duration)
    for literal in unattested_literals(expressions, supporting_text):
        accumulator.add(
            codes.LITERAL_NOT_ATTESTED,
            f"value {literal.value!r} does not appear in the cited evidence text",
        )

    modal_text = _role_text(clause, ir, (SemanticRole.EFFECT, SemanticRole.SUBJECT,
                                          SemanticRole.CONDITION))
    if modal_text and clause.modality not in attested_modalities(modal_text):
        accumulator.add(
            codes.MODALITY_NOT_ATTESTED,
            f"declared modality {clause.modality.value!r} is not attested by the cited "
            "text",
        )

    clause_ids = set(ir.clause_index())
    section_paths = {chunk.section_path for chunk in ir.chunks if chunk.section_path}
    for target in clause.cross_reference_targets:
        if target not in clause_ids and target not in section_paths:
            accumulator.add(
                codes.UNRESOLVED_CROSS_REFERENCE,
                f"cross reference {target!r} resolves to neither a clause nor a section",
                SemanticRole.CROSS_REFERENCE.value,
            )

    # Scope: every axis must be declared, valued from its vocabulary, and evidenced.
    declared_dimensions = ir.scope_dimension_index()
    for dimension in clause.scope.dimensions:
        definition = declared_dimensions.get(dimension.name)
        if definition is None:
            accumulator.add(
                codes.UNKNOWN_SCOPE_DIMENSION,
                f"scope axis {dimension.name!r} is not a declared scope dimension",
                SemanticRole.SCOPE.value,
            )
            continue
        if definition.allowed_values:
            unknown = sorted(set(dimension.values) - set(definition.allowed_values))
            if unknown:
                accumulator.add(
                    codes.SCOPE_VALUE_NOT_ALLOWED,
                    f"scope axis {dimension.name!r} uses {unknown}, which is outside its "
                    "declared vocabulary",
                    SemanticRole.SCOPE.value,
                )
        if not dimension.evidence_ids:
            accumulator.add(
                codes.MISSING_FIELD_EVIDENCE,
                f"scope axis {dimension.name!r} cites no evidence, so the limit is "
                "unsupported",
                SemanticRole.SCOPE.value,
            )
        for evidence_id in dimension.evidence_ids:
            if not _verify_span(evidence_id, ir, texts, accumulator):
                exact = False

    if clause.authority_ref and clause.authority_ref not in ir.authority_index():
        accumulator.add(
            codes.UNKNOWN_AUTHORITY,
            f"authority {clause.authority_ref!r} is not a declared authority source",
            SemanticRole.AUTHORITY.value,
        )

    # Supersession: a replaced clause must say what replaced it, and must not compile.
    if clause.lifecycle is Lifecycle.SUPERSEDED:
        if not superseded_by(ir, clause.clause_id):
            accumulator.add(
                codes.SUPERSESSION_NOT_RECORDED,
                "the clause is marked superseded but no supersedes edge records the "
                "replacement, so 'what was in force' cannot be answered",
            )
        accumulator.add(
            codes.SUPERSEDED_CLAUSE,
            "a superseded clause stays in the graph but cannot be compiled",
        )

    if as_of is not None:
        verdict = in_force_on(ir, clause.clause_id, as_of)
        if verdict is False:
            accumulator.add(
                codes.NOT_IN_FORCE, f"the clause is not in force on {as_of.isoformat()}"
            )
        elif verdict is None:
            accumulator.add(
                codes.IN_FORCE_UNKNOWN,
                f"whether the clause is in force on {as_of.isoformat()} cannot be "
                "determined from its lifecycle and effective period",
            )

    period = clause.effective_period
    if period.start and period.end and period.start > period.end:
        accumulator.add(
            codes.INVALID_EFFECTIVE_PERIOD,
            f"effective period starts at {period.start} and ends at {period.end}",
        )
    if clause.lifecycle is Lifecycle.EXPIRED and not period.end:
        accumulator.add(
            codes.INVALID_EFFECTIVE_PERIOD, "an expired clause must record an end date"
        )

    semantic_ok = (
        Status.PROVENANCE_EXACT in statuses
        and Status.SCHEMA_VALID in statuses
        and not accumulator.has(
            codes.ILL_TYPED_EXPRESSION,
            codes.LITERAL_NOT_ATTESTED,
            codes.MODALITY_NOT_ATTESTED,
            codes.UNRESOLVED_CROSS_REFERENCE,
            codes.INVALID_EFFECTIVE_PERIOD,
            codes.UNKNOWN_SCOPE_DIMENSION,
            codes.SCOPE_VALUE_NOT_ALLOWED,
            codes.UNKNOWN_AUTHORITY,
            codes.SUPERSESSION_NOT_RECORDED,
        )
    )
    if semantic_ok:
        statuses.add(Status.SEMANTIC_SUPPORTED)

    definitions = ir.data_definition_index()
    if clause.condition_ast is not None:
        try:
            atoms = decompose(row_condition(clause.condition_ast, clause.exception_ast))
        except NotTabular as exc:
            accumulator.add(codes.CONDITION_NOT_TABULAR, str(exc))
            atoms = {}
        for variable_id in sorted(atoms):
            definition = definitions.get(variable_id)
            if definition is None:
                continue
            if definition.null_policy is NullPolicy.UNDEFINED:
                accumulator.add(
                    codes.NULL_POLICY_UNDEFINED,
                    f"input {variable_id!r} does not declare null/unknown behaviour",
                )
            if definition.provenance in (Provenance.PROPOSED, Provenance.UNRESOLVED):
                accumulator.add(
                    codes.PROPOSED_ELEMENT_IN_EXECUTABLE,
                    f"input {variable_id!r} is {definition.provenance.value} and may not "
                    "reach an executable projection",
                )

    names = {
        key: feel_name(value.name) for key, value in definitions.items()
    }
    for attribute in ("condition_ast", "effect_ast", "exception_ast"):
        expression = getattr(clause, attribute)
        if expression is None:
            continue
        try:
            to_feel(expression, names)
        except FeelError as exc:
            accumulator.add(codes.NOT_FEEL_EXPRESSIBLE, f"{attribute}: {exc}")

    dmn_ok = (
        semantic_ok
        and clause.condition_ast is not None
        and clause.effect_ast is not None
        and not accumulator.has(
            codes.CONDITION_NOT_TABULAR,
            codes.NULL_POLICY_UNDEFINED,
            codes.PROPOSED_ELEMENT_IN_EXECUTABLE,
            codes.NOT_FEEL_EXPRESSIBLE,
            codes.SUPERSEDED_CLAUSE,
            codes.NOT_IN_FORCE,
            codes.IN_FORCE_UNKNOWN,
        )
    )
    if dmn_ok:
        statuses.add(Status.DMN_ELIGIBLE)
    if (
        semantic_ok
        and clause.semantic_kind is SemanticKind.PROCESS_FRAGMENT
        and not accumulator.has(
            codes.SUPERSEDED_CLAUSE, codes.NOT_IN_FORCE, codes.IN_FORCE_UNKNOWN
        )
    ):
        statuses.add(Status.BPMN_ELIGIBLE)

    return ElementReport(clause.clause_id, frozenset(statuses), tuple(accumulator.blockers))


def _check_decision(
    decision: DecisionModelCandidate,
    ir: PolicyIR,
    clause_reports: Mapping[str, ElementReport],
) -> ElementReport:
    accumulator = _Accumulator(decision.decision_id)
    statuses: set[Status] = {Status.SCHEMA_VALID}
    definitions = ir.data_definition_index()
    clauses = ir.clause_index()

    if not decision.decision_rule_refs:
        accumulator.add(codes.NO_DECISION_ROWS, "the decision references no clauses")

    for input_id in decision.input_data_refs:
        definition = definitions.get(input_id)
        if definition is None:
            accumulator.add(codes.UNTYPED_INPUT, f"input {input_id!r} is not declared")
            continue
        if definition.null_policy is NullPolicy.UNDEFINED:
            accumulator.add(
                codes.NULL_POLICY_UNDEFINED,
                f"input {input_id!r} does not declare null/unknown behaviour",
            )
        if definition.provenance in (Provenance.PROPOSED, Provenance.UNRESOLVED):
            accumulator.add(
                codes.PROPOSED_ELEMENT_IN_EXECUTABLE,
                f"input {input_id!r} is {definition.provenance.value}",
            )

    declared_inputs = set(decision.input_data_refs)
    # Derived, not declared: the axes are the union of the rows' scopes, so a table's
    # shape cannot drift out of step with the clauses it is built from.
    scope_axes: set[str] = set()
    rows: list[Row] = []
    for clause_id in decision.decision_rule_refs:
        clause = clauses.get(clause_id)
        if clause is None:
            accumulator.add(codes.ROW_NOT_ADMITTED, f"unknown clause {clause_id!r}")
            continue
        report = clause_reports.get(clause_id)
        if report is None or not report.has(Status.DMN_ELIGIBLE):
            excluded_by_design = report is not None and bool(report.blockers) and set(
                report.codes()
            ) <= _ROW_EXCLUDED_BY_DESIGN
            if not excluded_by_design:
                accumulator.add(
                    codes.ROW_NOT_ADMITTED,
                    f"clause {clause_id!r} is not DMN-eligible, so it cannot be a row",
                )
            continue
        if clause.condition_ast is None or clause.effect_ast is None:  # pragma: no cover
            continue
        try:
            atoms = decompose(row_condition(clause.condition_ast, clause.exception_ast))
        except NotTabular as exc:
            accumulator.add(codes.CONDITION_NOT_TABULAR, f"{clause_id}: {exc}")
            continue
        # A scope axis becomes an extra input column, so a row's scope must key on an
        # axis the corpus actually declares.
        for key, dimension_atoms in scope_atoms(clause.scope).items():
            name = scope_dimension_name(key)
            if name not in ir.scope_dimension_index():
                accumulator.add(
                    codes.UNKNOWN_SCOPE_DIMENSION,
                    f"clause {clause_id!r} is scoped on {name!r}, which is not a declared "
                    "scope dimension",
                )
                continue
            atoms[key] = dimension_atoms
            scope_axes.add(key)

        undeclared = sorted(key for key in set(atoms) - declared_inputs if not is_scope_input(key))
        if undeclared:
            accumulator.add(
                codes.ROW_USES_UNDECLARED_INPUT,
                f"clause {clause_id!r} constrains {undeclared} which the decision does "
                "not declare as inputs",
            )
        for variable_id in referenced_variable_ids(clause.effect_ast):
            if variable_id not in declared_inputs:
                accumulator.add(
                    codes.ROW_USES_UNDECLARED_INPUT,
                    f"clause {clause_id!r} output reads undeclared input {variable_id!r}",
                )
        result = check(clause.effect_ast, context_from_ir(ir))
        if result.ok and result.type != decision.output_definition.type:
            accumulator.add(
                codes.OUTPUT_TYPE_MISMATCH,
                f"clause {clause_id!r} produces {result.type} but the decision output is "
                f"{decision.output_definition.type}",
            )
        rows.append(Row(clause_id, atoms))

    for required in decision.required_decision_refs:
        if required not in ir.decision_index():
            accumulator.add(
                codes.UNKNOWN_REQUIRED_DECISION, f"required decision {required!r} is unknown"
            )

    types = {
        input_id: definitions[input_id].type
        for input_id in decision.input_data_refs
        if input_id in definitions
    }
    types.update({axis: DataType.STRING for axis in scope_axes})
    proof_inputs = (*decision.input_data_refs, *sorted(scope_axes))
    if decision.proposed_hit_policy is HitPolicy.UNIQUE:
        proof = prove_disjoint(rows, types, proof_inputs)
        if not proof.disjoint:
            pairs = ", ".join(f"{a}/{b}" for a, b in proof.overlapping_pairs)
            accumulator.add(
                codes.HIT_POLICY_NOT_PROVEN,
                "UNIQUE requires provably non-overlapping rows; these pairs may both "
                f"match: {pairs}",
            )
    elif decision.proposed_hit_policy in (HitPolicy.FIRST, HitPolicy.PRIORITY):
        if not decision.ordering_evidence_ids:
            accumulator.add(
                codes.ORDERING_NOT_EVIDENCED,
                f"{decision.proposed_hit_policy.value} requires source-supported ordering",
            )
    elif decision.proposed_hit_policy is HitPolicy.COLLECT:
        if decision.aggregation is None:
            accumulator.add(
                codes.AGGREGATION_NOT_DECLARED,
                "COLLECT requires a declared aggregation",
            )

    if not accumulator.blockers:
        statuses.add(Status.DMN_ELIGIBLE)
    return ElementReport(decision.decision_id, frozenset(statuses), tuple(accumulator.blockers))


def _detect_cycle(edges: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """Return one cycle if the graph has any, otherwise an empty tuple."""
    visiting: set[str] = set()
    done: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...]:
        if node in done:
            return ()
        if node in visiting:
            index = stack.index(node)
            return tuple(stack[index:]) + (node,)
        visiting.add(node)
        stack.append(node)
        for successor in edges.get(node, ()):
            found = visit(successor)
            if found:
                return found
        stack.pop()
        visiting.discard(node)
        done.add(node)
        return ()

    for node in sorted(edges):
        found = visit(node)
        if found:
            return found
    return ()


def _check_process(
    fragment: ProcessFragmentCandidate,
    ir: PolicyIR,
    texts: Mapping[str, str],
    decision_reports: Mapping[str, ElementReport],
) -> ElementReport:
    accumulator = _Accumulator(fragment.fragment_id)
    statuses: set[Status] = {Status.SCHEMA_VALID}
    entities = ir.entity_index()

    if fragment.trigger_event is None:
        accumulator.add(
            codes.MISSING_TRIGGER,
            "an executable process needs an explicit trigger; a policy date is not one",
        )
    elif not fragment.trigger_event.evidence_ids:
        accumulator.add(
            codes.MISSING_TRIGGER, "the trigger event cites no evidence", "trigger"
        )

    actor = fragment.responsible_actor_ref
    if not actor:
        accumulator.add(codes.MISSING_RESPONSIBLE_ACTOR, "no responsible actor is declared")
    else:
        entity = entities.get(actor)
        if entity is None:
            accumulator.add(
                codes.MISSING_RESPONSIBLE_ACTOR, f"actor {actor!r} is not a declared entity"
            )
        elif entity.category not in (
            EntityCategory.ACTOR_OR_ROLE,
            EntityCategory.ORGANIZATION,
            EntityCategory.SYSTEM,
        ):
            accumulator.add(
                codes.MISSING_RESPONSIBLE_ACTOR,
                f"actor {actor!r} is categorised {entity.category.value}, which cannot "
                "own an activity",
            )

    if not fragment.activities:
        accumulator.add(codes.NO_ACTIVITY, "the fragment declares no activity")

    activity_ids = {activity.activity_id for activity in fragment.activities}
    for activity in fragment.activities:
        if not activity.evidence_ids:
            accumulator.add(
                codes.MISSING_ACTIVITY_EVIDENCE,
                f"activity {activity.activity_id!r} cites no evidence",
            )
        if activity.kind == "business_rule_task":
            if not activity.decision_ref:
                accumulator.add(
                    codes.BUSINESS_RULE_TASK_WITHOUT_DECISION,
                    f"activity {activity.activity_id!r} is a business rule task with no "
                    "decision reference",
                )
            else:
                decision_report = decision_reports.get(activity.decision_ref)
                if decision_report is None or not decision_report.has(Status.DMN_ELIGIBLE):
                    accumulator.add(
                        codes.BUSINESS_RULE_TASK_WITHOUT_DECISION,
                        f"activity {activity.activity_id!r} calls decision "
                        f"{activity.decision_ref!r}, which is not DMN-eligible",
                    )

    validated_precedence: set[tuple[str, str]] = set()
    for edge in ir.dependencies:
        if edge.kind is DependencyKind.TEMPORAL_PRECEDENCE and (
            edge.derivation_method in TRUSTED_DERIVATION_METHODS and edge.evidence_ids
        ):
            validated_precedence.add((edge.source_id, edge.target_id))

    successors: dict[str, list[str]] = {}
    for source, target in fragment.ordering:
        if source not in activity_ids or target not in activity_ids:
            accumulator.add(
                codes.DANGLING_ORDERING,
                f"ordering {source!r}->{target!r} refers to something that is not an "
                "activity of this fragment",
            )
            continue
        if (source, target) not in validated_precedence:
            accumulator.add(
                codes.ORDERING_NOT_VALIDATED,
                f"ordering {source!r}->{target!r} has no validated temporal_precedence "
                "dependency; shared entities do not imply sequence",
            )
        successors.setdefault(source, []).append(target)

    # The BPMN subset emits a single chain. Branching needs gateways with branch
    # conditions and a declared default path; refusing is the plan's rule, since a
    # gateway the source never described would be invented process semantics.
    for source, targets in sorted(successors.items()):
        if len(targets) > 1:
            accumulator.add(
                codes.BRANCHING_NOT_SUPPORTED,
                f"activity {source!r} has {len(targets)} successors; this compiler emits "
                "no gateways, so branching is not compiled",
            )
    predecessor_counts: dict[str, int] = {}
    for _, target in fragment.ordering:
        predecessor_counts[target] = predecessor_counts.get(target, 0) + 1
    for target, count in sorted(predecessor_counts.items()):
        if count > 1:
            accumulator.add(
                codes.BRANCHING_NOT_SUPPORTED,
                f"activity {target!r} has {count} predecessors; merging needs a gateway",
            )

    cycle = _detect_cycle(successors)
    if cycle:
        accumulator.add(codes.ORDERING_CYCLE, f"ordering contains a cycle: {' -> '.join(cycle)}")

    if fragment.activities and not cycle:
        targets = {target for _, target in fragment.ordering if target in activity_ids}
        roots = [a.activity_id for a in fragment.activities if a.activity_id not in targets]
        reachable: set[str] = set()
        frontier = list(roots[:1])
        while frontier:
            current = frontier.pop()
            if current in reachable:
                continue
            reachable.add(current)
            frontier.extend(successors.get(current, ()))
        unreachable = sorted(activity_ids - reachable)
        if unreachable:
            accumulator.add(
                codes.UNREACHABLE_ACTIVITY,
                f"activities {unreachable} are not reachable from the entry activity",
            )

    if not fragment.end_state:
        accumulator.add(
            codes.MISSING_END_STATE, "no end state is known, so completion cannot be modelled"
        )

    for evidence_id in fragment.evidence_ids:
        _verify_span(evidence_id, ir, texts, accumulator)
    for activity in fragment.activities:
        for evidence_id in activity.evidence_ids:
            _verify_span(evidence_id, ir, texts, accumulator)
    if fragment.trigger_event is not None:
        for evidence_id in fragment.trigger_event.evidence_ids:
            _verify_span(evidence_id, ir, texts, accumulator)

    if not accumulator.blockers:
        statuses.add(Status.BPMN_ELIGIBLE)
    return ElementReport(fragment.fragment_id, frozenset(statuses), tuple(accumulator.blockers))


def _check_dependency(edge, ir: PolicyIR) -> ElementReport:
    accumulator = _Accumulator(edge.edge_id)
    known = (
        set(ir.clause_index())
        | set(ir.decision_index())
        | set(ir.process_index())
        | set(ir.entity_index())
        | set(ir.data_definition_index())
        | {activity.activity_id for p in ir.processes for activity in p.activities}
    )
    for endpoint in (edge.source_id, edge.target_id):
        if endpoint not in known:
            accumulator.add(
                codes.UNKNOWN_DEPENDENCY_ENDPOINT, f"endpoint {endpoint!r} is unknown"
            )
    if edge.kind in EXECUTABLE_DEPENDENCY_KINDS:
        if edge.derivation_method not in TRUSTED_DERIVATION_METHODS:
            accumulator.add(
                codes.UNVALIDATED_EXECUTABLE_DEPENDENCY,
                f"{edge.kind.value} edges derived by {edge.derivation_method.value} stay "
                "candidates and cannot carry executable meaning",
            )
        if not edge.evidence_ids:
            accumulator.add(
                codes.UNVALIDATED_EXECUTABLE_DEPENDENCY,
                f"{edge.kind.value} edge cites no evidence",
            )
    statuses = {Status.SCHEMA_VALID} if not accumulator.has(
        codes.UNKNOWN_DEPENDENCY_ENDPOINT
    ) else set()
    return ElementReport(edge.edge_id, frozenset(statuses), tuple(accumulator.blockers))


@dataclass(frozen=True)
class ConflictOutcome:
    """What happened to one declared conflict between two clauses."""

    source_id: str
    target_id: str
    #: "disjoint_scope" | "resolved" | "unresolved"
    kind: str
    loser_id: str | None = None
    reason: str = ""


def _resolve_conflicts(
    ir: PolicyIR, clause_reports: dict[str, ElementReport]
) -> tuple[ConflictOutcome, ...]:
    """Decide each declared conflict, and refuse the losing clause in place.

    Three outcomes, in the order they are tried:

    1. **Disjoint scope** — the two clauses cannot both apply, so there is no real
       conflict. A federal rule limited to California and one limited to New York
       disagree only on paper.
    2. **Resolved by authority** — both can apply and one cites a heavier authority.
       The loser stays in the graph and is refused for executable projection. This is
       the case that used to kill the whole decision.
    3. **Unresolved** — equal weight, or an authority missing on either side.
       Precedence cannot settle it, so both are refused and the decision is blocked.

    The bias is deliberate: a conflict is only resolved when the corpus has declared
    enough to resolve it.
    """
    clauses = ir.clause_index()
    authorities = ir.authority_index()
    outcomes: list[ConflictOutcome] = []

    for edge in ir.dependencies:
        if edge.kind is not DependencyKind.CONFLICT:
            continue
        left = clauses.get(edge.source_id)
        right = clauses.get(edge.target_id)
        if left is None or right is None:
            continue

        if not left.scope.overlaps(right.scope):
            outcomes.append(
                ConflictOutcome(
                    edge.source_id,
                    edge.target_id,
                    "disjoint_scope",
                    reason="the two clauses apply to provably disjoint scopes",
                )
            )
            continue

        left_authority = authorities.get(left.authority_ref or "")
        right_authority = authorities.get(right.authority_ref or "")
        if left_authority is None or right_authority is None:
            missing = [
                clause.clause_id
                for clause, authority in ((left, left_authority), (right, right_authority))
                if authority is None
            ]
            outcomes.append(
                ConflictOutcome(
                    edge.source_id,
                    edge.target_id,
                    "unresolved",
                    reason=f"no declared authority for {missing}, so precedence cannot "
                    "settle the conflict",
                )
            )
            continue
        if left_authority.authority_weight == right_authority.authority_weight:
            outcomes.append(
                ConflictOutcome(
                    edge.source_id,
                    edge.target_id,
                    "unresolved",
                    reason=f"{left_authority.name!r} and {right_authority.name!r} carry "
                    f"equal weight ({left_authority.authority_weight})",
                )
            )
            continue

        if left_authority.outranks(right_authority):
            winner, loser, winning_authority = left, right, left_authority
        else:
            winner, loser, winning_authority = right, left, right_authority
        outcomes.append(
            ConflictOutcome(
                edge.source_id,
                edge.target_id,
                "resolved",
                loser_id=loser.clause_id,
                reason=f"{winning_authority.name!r} outranks the conflicting source",
            )
        )
        report = clause_reports.get(loser.clause_id)
        if report is not None:
            blocker = Blocker(
                codes.OUTRANKED_BY_AUTHORITY,
                loser.clause_id,
                f"conflicts with {winner.clause_id!r}, which cites the heavier authority "
                f"{winning_authority.name!r}; kept in the graph, refused for execution",
            )
            clause_reports[loser.clause_id] = ElementReport(
                report.element_id,
                report.statuses - {Status.DMN_ELIGIBLE, Status.BPMN_ELIGIBLE},
                report.blockers + (blocker,),
            )
    return tuple(outcomes)


def run_gate(
    ir: PolicyIR,
    texts: Mapping[str, str] | None = None,
    *,
    as_of: _dt.date | None = None,
) -> GateReport:
    """Run every gate check and return the admission report.

    ``texts`` maps document IDs to canonical text. Omitting a document's text does
    not make its spans pass: they are refused with
    ``evidence_text_unavailable``, because an unverifiable citation is exactly
    what the gate exists to stop.
    """
    texts = dict(texts or {})
    global_blockers = _duplicate_ids(ir)

    clause_reports = {
        clause.clause_id: _check_clause(clause, ir, texts, as_of) for clause in ir.clauses
    }
    conflict_outcomes = _resolve_conflicts(ir, clause_reports)
    decision_reports = {
        decision.decision_id: _check_decision(decision, ir, clause_reports)
        for decision in ir.decisions
    }
    process_reports = {
        fragment.fragment_id: _check_process(fragment, ir, texts, decision_reports)
        for fragment in ir.processes
    }
    dependency_reports = {
        edge.edge_id: _check_dependency(edge, ir) for edge in ir.dependencies
    }

    # Only conflicts precedence could not settle block a decision. A resolved
    # conflict already refused its loser at clause level, so the decision can still
    # compile from the winner.
    unresolved = {
        (outcome.source_id, outcome.target_id): outcome
        for outcome in conflict_outcomes
        if outcome.kind == "unresolved"
    }
    for decision in ir.decisions:
        members = set(decision.decision_rule_refs)
        for (source, target), outcome in sorted(unresolved.items()):
            if source in members and target in members:
                report = decision_reports[decision.decision_id]
                blocker = Blocker(
                    codes.UNRESOLVED_CONFLICT,
                    decision.decision_id,
                    f"clauses {source!r} and {target!r} are declared to conflict and "
                    f"{outcome.reason}",
                )
                decision_reports[decision.decision_id] = ElementReport(
                    report.element_id,
                    report.statuses - {Status.DMN_ELIGIBLE},
                    report.blockers + (blocker,),
                )
    # An equal-weight tie is a gap in the corpus's own authority configuration, so
    # it is reported once against the IR rather than repeated per decision.
    for outcome in conflict_outcomes:
        if outcome.kind == "unresolved" and "equal weight" in outcome.reason:
            global_blockers.append(
                Blocker(codes.AUTHORITY_TIE, outcome.source_id, outcome.reason)
            )

    for cycle in supersession_cycles(ir):
        global_blockers.append(
            Blocker(
                codes.SUPERSESSION_CYCLE,
                cycle[0],
                f"supersession forms a cycle: {' -> '.join(cycle)}",
            )
        )

    decision_cycle = _detect_cycle(
        {d.decision_id: list(d.required_decision_refs) for d in ir.decisions}
    )
    if decision_cycle:
        global_blockers.append(
            Blocker(
                codes.DECISION_CYCLE,
                decision_cycle[0],
                f"decision requirements form a cycle: {' -> '.join(decision_cycle)}",
            )
        )

    return GateReport(
        clauses=clause_reports,
        decisions=decision_reports,
        processes=process_reports,
        dependencies=dependency_reports,
        global_blockers=tuple(global_blockers),
    )
