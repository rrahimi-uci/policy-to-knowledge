"""Traceability, the compilation report and the run manifest.

Three separate documents because they answer three separate questions:

* **traceability.json** — for any emitted model element, which clause produced it
  and which exact source span supports that clause. This is what makes an audit
  possible without re-running anything.
* **compilation-report.json** — what was refused and why, counted by blocker code.
  Coverage and blocker distribution are first-class results, not omissions: a run
  that admits three rules out of a hundred has to say so.
* **manifest.json** — the hashes and versions needed to reproduce the run.

The manifest carries no timestamp unless the caller supplies one, so identical
inputs produce an identical manifest. Reproducibility is checkable only if the
record of the run is itself deterministic.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from policy_ir.ids import SCHEMA_VERSION, sha256_text
from policy_ir.models import PolicyIR
from validation.evidence_gate import GateReport

from .bpmn import BPMN_SPEC
from .dmn import DMN_SPEC, CompiledArtifact

TOOL_NAME = "pipeline-p2c"


def build_traceability(
    ir: PolicyIR,
    report: GateReport,
    artifacts: Sequence[CompiledArtifact],
) -> dict[str, Any]:
    """Link every emitted element back to clauses, evidence and legacy IDs."""
    evidence = ir.evidence_index()
    documents = ir.document_index()
    clauses = ir.clause_index()

    def evidence_detail(evidence_id: str) -> dict[str, Any]:
        span = evidence.get(evidence_id)
        if span is None:
            return {"evidence_id": evidence_id, "resolved": False}
        document = documents.get(span.document_id)
        return {
            "evidence_id": evidence_id,
            "resolved": True,
            "document_id": span.document_id,
            "source_uri": document.source_uri if document else None,
            "source_sha256": document.source_sha256 if document else None,
            "chunk_sha256": span.chunk_sha256,
            "char_start": span.char_start,
            "char_end": span.char_end,
            "section": span.section_path,
            "semantic_role": span.semantic_role.value,
            "match_status": span.match_status.value,
            "exact_text": span.exact_text,
        }

    clause_trace = {
        clause_id: {
            "display_text": clause.display_text,
            "modality": clause.modality.value,
            "semantic_kind": clause.semantic_kind.value,
            "legacy_rule_ids": list(clause.legacy_rule_ids),
            "statuses": sorted(
                status.value
                for status in (
                    report.clauses[clause_id].statuses if clause_id in report.clauses else ()
                )
            ),
            "evidence": [evidence_detail(e) for e in clause.all_evidence_ids()],
        }
        for clause_id, clause in sorted(clauses.items())
    }

    return {
        "policy_ir_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "specifications": {"dmn": DMN_SPEC, "bpmn": BPMN_SPEC},
        "artifacts": {
            artifact.filename: dict(artifact.trace) for artifact in artifacts
        },
        "clauses": clause_trace,
    }


def build_compilation_report(
    ir: PolicyIR,
    report: GateReport,
    artifacts: Sequence[CompiledArtifact],
) -> dict[str, Any]:
    """Summarise admission, coverage and every refusal."""
    coverage_counts: dict[str, int] = {}
    for entry in ir.coverage:
        coverage_counts[entry.status] = coverage_counts.get(entry.status, 0) + 1

    skipped_by_code: dict[str, int] = {}
    for artifact in artifacts:
        for blocker in artifact.skipped:
            skipped_by_code[blocker.code] = skipped_by_code.get(blocker.code, 0) + 1

    return {
        "policy_ir_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "totals": {
            "documents": len(ir.documents),
            "chunks": len(ir.chunks),
            "evidence_spans": len(ir.evidence_spans),
            "clauses": len(ir.clauses),
            "decisions": len(ir.decisions),
            "processes": len(ir.processes),
            "dependencies": len(ir.dependencies),
        },
        "admitted": {
            "decisions": list(report.admitted_decisions()),
            "processes": list(report.admitted_processes()),
        },
        "gate": report.to_dict(),
        "coverage": coverage_counts,
        "artifacts": [
            {
                "filename": artifact.filename,
                "emitted": list(artifact.emitted_ids),
                "emitted_count": len(artifact.emitted_ids),
                "skipped_count": len(artifact.skipped),
                "sha256": sha256_text(artifact.xml),
            }
            for artifact in artifacts
        ],
        "skipped_by_code": dict(sorted(skipped_by_code.items())),
        "assurance": {
            "conformance_verified": "structural checks in this run",
            "semantically_supported": "not claimed by this run",
            "governance_approved": "not claimed by this run",
        },
    }


def build_manifest(
    ir: PolicyIR,
    report: GateReport,
    artifacts: Sequence[CompiledArtifact],
    *,
    profile: str,
    run_timestamp: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the reproducibility manifest for one compile run."""
    manifest: dict[str, Any] = {
        "tool": TOOL_NAME,
        "policy_ir_version": SCHEMA_VERSION,
        "compiler_profile": profile,
        "specifications": {"dmn": DMN_SPEC, "bpmn": BPMN_SPEC},
        "inputs": {
            "documents": [
                {
                    "document_id": document.document_id,
                    "source_uri": document.source_uri,
                    "source_sha256": document.source_sha256,
                    "canonical_text_sha256": document.canonical_text_sha256,
                    "parser_version": document.parser_version,
                    "license_record_id": document.license_record_id,
                }
                for document in ir.documents
            ],
            "policy_ir_sha256": sha256_text(_canonical_json(ir.to_dict())),
        },
        "outputs": [
            {"filename": artifact.filename, "sha256": sha256_text(artifact.xml)}
            for artifact in artifacts
        ],
        "gate_summary": {
            "global_blockers": len(report.global_blockers),
            "blocker_counts": report.counts_by_code(),
            "admitted_decisions": len(report.admitted_decisions()),
            "admitted_processes": len(report.admitted_processes()),
        },
        "determinism": {
            "timestamps_in_outputs": False,
            "note": (
                "Compiling the same Policy IR with the same profile produces "
                "byte-identical artefacts."
            ),
        },
    }
    if run_timestamp is not None:
        manifest["run_timestamp"] = run_timestamp
    if extra:
        manifest["extra"] = dict(extra)
    return manifest


def _canonical_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
