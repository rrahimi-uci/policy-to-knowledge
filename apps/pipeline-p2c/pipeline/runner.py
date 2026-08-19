"""Stage implementations for the staged pipeline.

Every stage is a pure function of the artefacts already on disk plus its own inputs, so
the run is reproducible and any stage can be re-run alone. The only stage that reaches
outside is the model pass.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from compilers.bpmn import compile_bpmn
from compilers.dmn import compile_dmn
from compilers.graph import project_graph
from compilers.traceability import (
    build_compilation_report,
    build_manifest,
    build_traceability,
)
from compilers.verify import validate_bpmn, validate_dmn
from extraction.contract import proposal_schema, render_instructions
from extraction.model_extractor import (
    ExtractionRun,
    Transport,
    admit_run,
    run_extraction,
)
from extraction.offer import ExtractionRequest, build_requests
from extraction.proposals import proposal_from_dict
from ingestion.pdf import ingest_pdf
from ingestion.registry import SourceRegistry
from policy_ir.enums import CompilerProfile, Status
from policy_ir.models import Chunk, CoverageEntry, DocumentArtifact, PolicyIR
from validation import run_gate

from .stages import RUNNERS, StageResult, count_files, read_json, stage_dir, write_json

TEXT_DIR = "canonical-text"
REQUEST_DIR = "requests"
REPLY_DIR = "replies"
PROPOSAL_DIR = "proposals"


# ---------------------------------------------------------------------------
# 01 ingestion
# ---------------------------------------------------------------------------


def stage_ingestion(
    *, root: Path, inputs: Sequence[Path], max_chunk_chars: int = 20_000
) -> StageResult:
    """PDF bytes to hashed canonical text, chunks and coverage."""
    started = time.monotonic()
    out = stage_dir(root, "ingestion")
    (out / TEXT_DIR).mkdir(exist_ok=True)

    registry = SourceRegistry()
    coverage: list[CoverageEntry] = []
    per_document: list[dict[str, Any]] = []

    for path in inputs:
        result = ingest_pdf(
            registry,
            path,
            retrieval_timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            license_record_id=f"local:{path.parent.name}",
            max_chunk_chars=max_chunk_chars,
        )
        coverage.extend(result.coverage)
        # The canonical text is what every later offset indexes into, so it is stored
        # verbatim beside its hash rather than re-derived.
        (out / TEXT_DIR / f"{result.document.document_id}.txt").write_text(
            result.canonical_text, encoding="utf-8"
        )
        per_document.append(
            {
                "source": str(path),
                "document_id": result.document.document_id,
                "pages": result.page_count,
                "canonical_chars": len(result.canonical_text),
                "headings": len(result.headings),
                "chunks": len(result.chunks),
                "pages_without_text": list(result.pages_without_text),
                "extraction_gap": round(result.extraction_gap, 4),
                "source_sha256": result.document.source_sha256,
                "canonical_text_sha256": result.document.canonical_text_sha256,
                "parser_version": result.document.parser_version,
            }
        )

    skeleton = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        coverage=tuple(coverage),
        metadata={"artifact_role": "ingestion_skeleton"},
    )
    write_json(out / "documents.json", [d.to_dict() for d in skeleton.documents])
    write_json(out / "chunks.json", [c.to_dict() for c in skeleton.chunks])
    write_json(out / "coverage.json", [c.to_dict() for c in skeleton.coverage])
    write_json(out / "policy-ir-skeleton.json", skeleton.to_dict())
    summary = {
        "documents": len(skeleton.documents),
        "chunks": len(skeleton.chunks),
        "canonical_chars": sum(d["canonical_chars"] for d in per_document),
        "pages": sum(d["pages"] for d in per_document),
        "pages_without_text": sum(len(d["pages_without_text"]) for d in per_document),
        "per_document": per_document,
    }
    write_json(out / "ingestion-summary.json", summary)
    return StageResult(
        "ingestion", 1, out, count_files(out), time.monotonic() - started,
        {k: v for k, v in summary.items() if k != "per_document"},
    )


def restore_registry(root: Path) -> SourceRegistry:
    """Rebuild the registry from stage 01, without re-extracting any PDF."""
    ingestion = stage_dir(root, "ingestion")
    documents = [DocumentArtifact.from_dict(d) for d in read_json(ingestion / "documents.json")]
    chunks = [Chunk.from_dict(c) for c in read_json(ingestion / "chunks.json")]
    texts = {
        document.document_id: (
            ingestion / TEXT_DIR / f"{document.document_id}.txt"
        ).read_text(encoding="utf-8")
        for document in documents
    }
    return SourceRegistry.restore(documents, chunks, texts)


# ---------------------------------------------------------------------------
# 02 extraction requests
# ---------------------------------------------------------------------------


def stage_extraction_requests(*, root: Path) -> StageResult:
    """Numbered units, the generated schema and the prose contract, per chunk."""
    started = time.monotonic()
    out = stage_dir(root, "extraction_requests")
    (out / REQUEST_DIR).mkdir(exist_ok=True)

    registry = restore_registry(root)
    requests = build_requests(registry, registry.chunk_tuple())
    index: list[dict[str, Any]] = []
    for request in requests:
        stem = out / REQUEST_DIR / request.chunk_id
        write_json(stem.with_suffix(".request.json"), request.to_dict())
        write_json(stem.with_suffix(".schema.json"), proposal_schema(request))
        stem.with_suffix(".instructions.md").write_text(
            render_instructions(request), encoding="utf-8"
        )
        index.append(
            {
                "chunk_id": request.chunk_id,
                "document_id": request.document_id,
                "section_path": request.section_path,
                "units": request.unit_count,
            }
        )
    write_json(out / "requests-index.json", index)
    summary = {
        "requests": len(requests),
        "units": sum(item["units"] for item in index),
        "chunks_with_no_units": len(registry.chunks) - len(requests),
    }
    write_json(out / "requests-summary.json", summary)
    return StageResult(
        "extraction_requests", 2, out, count_files(out), time.monotonic() - started, summary
    )


def load_requests(root: Path, *, limit: int | None = None) -> tuple[ExtractionRequest, ...]:
    """Read the persisted requests back, in index order."""
    out = stage_dir(root, "extraction_requests")
    index = read_json(out / "requests-index.json")
    if limit is not None:
        index = index[:limit]
    return tuple(
        ExtractionRequest.from_dict(
            read_json(out / REQUEST_DIR / f"{item['chunk_id']}.request.json")
        )
        for item in index
    )


# ---------------------------------------------------------------------------
# 03 model extraction
# ---------------------------------------------------------------------------


def stage_model_extraction(
    *,
    root: Path,
    transport: Transport,
    model: str,
    effort: str,
    limit: int | None = None,
    concurrency: int = 6,
    select: Sequence[str] | None = None,
    progress: bool = True,
    resume: bool = True,
) -> StageResult:
    """Call the model for each request, keeping raw replies verbatim.

    Resumes by default: a chunk whose proposals file is already on disk is not called
    again. Re-running after a fix therefore costs only the chunks that still need it.
    """
    started = time.monotonic()
    out = stage_dir(root, "model_extraction")
    (out / REPLY_DIR).mkdir(exist_ok=True)
    (out / PROPOSAL_DIR).mkdir(exist_ok=True)

    requests = load_requests(root, limit=limit)
    if select:
        wanted = set(select)
        requests = tuple(r for r in requests if r.chunk_id in wanted)

    if resume:
        # A *successful* reply is skipped; a stored failure is retried. The reason to
        # re-run is almost always that the schema or the prompt was fixed, so the failed
        # chunks are exactly the ones that still need calling — and paying again for the
        # chunks that already worked is pure waste.
        succeeded: set[str] = set()
        failed: set[str] = set()
        for path in (out / PROPOSAL_DIR).glob("*.proposals.json"):
            chunk_id = path.name.removesuffix(".proposals.json")
            (failed if read_json(path).get("error") else succeeded).add(chunk_id)
        if succeeded or failed:
            requests = tuple(r for r in requests if r.chunk_id not in succeeded)
            print(
                f"  resuming: {len(succeeded)} chunks already succeeded and are skipped, "
                f"{len(failed)} stored failures will be retried, "
                f"{len(requests)} to call",
                flush=True,
            )

    def persist(reply: Any) -> None:
        """Write one reply the moment it arrives.

        This call cost money and minutes. Writing only at the end of the batch means an
        interruption two thirds of the way through a 324-chunk run discards every reply
        already paid for — which is exactly what happened once.
        """
        if reply.raw:
            # The raw payload is kept so a parsing or admission fix can be re-run
            # without paying for the call again.
            write_json(out / REPLY_DIR / f"{reply.chunk_id}.reply.json", reply.raw)
        write_json(
            out / PROPOSAL_DIR / f"{reply.chunk_id}.proposals.json",
            {
                "chunk_id": reply.chunk_id,
                "error": reply.error,
                "elapsed_seconds": round(reply.elapsed_seconds, 2),
                "usage": reply.usage.to_dict(),
                "candidates": [p.to_dict() for p in reply.proposals],
            },
        )

    def report(reply: Any, done: int, total: int) -> None:
        persist(reply)
        if progress:
            state = "ok" if reply.ok else f"ERROR {reply.error}"
            print(
                f"  [{done:>4}/{total}] {reply.chunk_id[:22]} {state} "
                f"{len(reply.proposals)} proposals {reply.elapsed_seconds:.0f}s "
                f"in={reply.usage.input_tokens} out={reply.usage.output_tokens}",
                flush=True,
            )

    run = run_extraction(
        requests, transport, model=model, effort=effort,
        concurrency=concurrency, on_reply=report,
    )
    summary = {
        "model": model,
        "reasoning_effort": effort,
        "concurrency": concurrency,
        "requests_attempted": len(run.replies),
        "requests_available": len(read_json(stage_dir(root, "extraction_requests") / "requests-index.json")),
        **run.to_dict(),
    }
    write_json(out / "run-summary.json", summary)
    return StageResult(
        "model_extraction", 3, out, count_files(out), time.monotonic() - started,
        {k: summary[k] for k in ("model", "reasoning_effort", "requests_attempted",
                                 "failed_requests", "proposals", "usage")},
    )


def load_run(root: Path) -> ExtractionRun:
    """Rebuild an ExtractionRun from the persisted proposals."""
    from extraction.model_extractor import ChunkReply, Usage

    out = stage_dir(root, "model_extraction")
    replies: list[ChunkReply] = []
    for path in sorted((out / PROPOSAL_DIR).glob("*.proposals.json")):
        payload = read_json(path)
        usage = payload.get("usage") or {}
        replies.append(
            ChunkReply(
                chunk_id=payload["chunk_id"],
                proposals=tuple(proposal_from_dict(c) for c in payload.get("candidates", ())),
                raw={},
                usage=Usage(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    reasoning_tokens=usage.get("reasoning_tokens", 0),
                    calls=usage.get("calls", 0),
                ),
                error=payload.get("error"),
                elapsed_seconds=payload.get("elapsed_seconds", 0.0),
            )
        )
    total = Usage()
    for reply in replies:
        total = total + reply.usage
    return ExtractionRun(tuple(replies), total, 0.0)


# ---------------------------------------------------------------------------
# 04 admission
# ---------------------------------------------------------------------------


def stage_admission(*, root: Path) -> StageResult:
    """Resolve proposals into evidenced clauses, recording every refusal."""
    started = time.monotonic()
    out = stage_dir(root, "admission")

    registry = restore_registry(root)
    requests = load_requests(root)
    run = load_run(root)
    clauses, spans, refusals = admit_run(
        run, requests, registry, documents=registry.documents
    )

    ingestion = stage_dir(root, "ingestion")
    coverage = [CoverageEntry.from_dict(c) for c in read_json(ingestion / "coverage.json")]
    cited_chunks = {clause.source_group_id for clause in clauses if clause.source_group_id}
    read_chunks = {reply.chunk_id for reply in run.replies}
    refreshed = [
        entry
        for entry in coverage
        if entry.chunk_id not in read_chunks
    ] + [
        CoverageEntry(
            chunk_id=chunk_id,
            status="candidates_emitted" if chunk_id in cited_chunks else "no_policy_semantics_found",
            note="model extraction",
        )
        for chunk_id in sorted(read_chunks)
    ]

    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        evidence_spans=spans,
        clauses=clauses,
        coverage=tuple(refreshed),
        metadata={"artifact_role": "model_extraction"},
    )
    write_json(out / "clauses.json", [c.to_dict() for c in clauses])
    write_json(out / "evidence-spans.json", [s.to_dict() for s in spans])
    write_json(out / "refusals.json", list(refusals))
    write_json(out / "policy-ir.json", ir.to_dict())
    summary = {
        "clauses": len(clauses),
        "evidence_spans": len(spans),
        "refused_batches": len(refusals),
        "chunks_read": len(read_chunks),
        "chunks_yielding_clauses": len(cited_chunks),
    }
    write_json(out / "admission-summary.json", summary)
    return StageResult("admission", 4, out, count_files(out), time.monotonic() - started, summary)


def load_ir(root: Path) -> tuple[PolicyIR, dict[str, str]]:
    """Load the admitted IR and the canonical texts its spans index into."""
    ir = PolicyIR.from_dict(read_json(stage_dir(root, "admission") / "policy-ir.json"))
    ingestion = stage_dir(root, "ingestion")
    texts = {
        document.document_id: (
            ingestion / TEXT_DIR / f"{document.document_id}.txt"
        ).read_text(encoding="utf-8")
        for document in ir.documents
    }
    return ir, texts


# ---------------------------------------------------------------------------
# 05 semantic assembly
# ---------------------------------------------------------------------------


def stage_semantic_assembly(*, root: Path, profile_path: Path | None = None) -> StageResult:
    """Record the semantic layer over the admitted clauses.

    This runs before the gate and before any executable projection, because the
    knowledge graph is the canonical representation and DMN/BPMN are narrow projections
    of the subset that qualifies. The synthesis report is the honest statement of that
    subset: for each clause that *declares* an intent to become a decision or a process,
    it says either "ready" or exactly which semantic field is still missing.

    Nothing here turns a clause into a workflow. A clause with no declared intent is a
    first-class part of the graph and simply does not appear as an opportunity.
    """
    from semantic.profiles import load_profile
    from semantic.synthesis import synthesis_report

    started = time.monotonic()
    out = stage_dir(root, "semantic_assembly")
    ir, _ = load_ir(root)

    opportunities = synthesis_report(ir)
    write_json(
        out / "synthesis-report.json",
        [opportunity.to_dict() for opportunity in opportunities],
    )

    profile = load_profile(profile_path)
    write_json(out / "domain-profile.json", profile.to_dict())

    by_target: dict[str, dict[str, int]] = {}
    missing_counts: dict[str, int] = {}
    for opportunity in opportunities:
        bucket = by_target.setdefault(opportunity.target, {})
        bucket[opportunity.status] = bucket.get(opportunity.status, 0) + 1
        for field_name in opportunity.missing:
            missing_counts[field_name] = missing_counts.get(field_name, 0) + 1
    write_json(out / "missing-by-field.json", missing_counts)

    summary = {
        "clauses": len(ir.clauses),
        "semantic_relations": len(ir.semantic_relations),
        "opportunities": len(opportunities),
        "by_target": by_target,
        "missing_by_field": missing_counts,
        "profile": profile.name,
        # Stated explicitly: a clause with no declared intent is not a shortfall.
        "clauses_with_no_declared_projection": len(ir.clauses)
        - len({opportunity.clause_id for opportunity in opportunities}),
    }
    write_json(out / "semantic-summary.json", summary)
    return StageResult(
        "semantic_assembly", 5, out, count_files(out), time.monotonic() - started, summary
    )


# ---------------------------------------------------------------------------
# 06 gate
# ---------------------------------------------------------------------------


def stage_gate(*, root: Path) -> StageResult:
    """Run the fail-closed gate and persist its verdict per element."""
    started = time.monotonic()
    out = stage_dir(root, "gate")
    ir, texts = load_ir(root)
    report = run_gate(ir, texts)

    write_json(out / "gate-report.json", report.to_dict())
    write_json(out / "blockers-by-code.json", report.counts_by_code())
    statuses: dict[str, int] = {}
    for element in report.clauses.values():
        for status in element.statuses:
            statuses[status.value] = statuses.get(status.value, 0) + 1
    write_json(out / "clause-status-counts.json", statuses)
    summary = {
        "clauses_checked": len(report.clauses),
        "fatal": report.fatal,
        "blocker_counts": report.counts_by_code(),
        "status_counts": statuses,
        "admitted_decisions": len(report.admitted_decisions()),
        "admitted_processes": len(report.admitted_processes()),
    }
    write_json(out / "gate-summary.json", summary)
    return StageResult("gate", 6, out, count_files(out), time.monotonic() - started, summary)


# ---------------------------------------------------------------------------
# 07 governance
# ---------------------------------------------------------------------------


def stage_governance(*, root: Path) -> StageResult:
    """Turn every refusal into a reviewer-facing queue, and count what was covered.

    The queue is the deliverable of a fail-closed gate: a refusal that is only a log
    line is not actionable. Every metric here is a count of what happened, never a
    score — nothing in this stage claims a clause was read correctly.
    """
    from semantic.governance import review_queue, semantic_metrics

    started = time.monotonic()
    out = stage_dir(root, "governance")
    ir, texts = load_ir(root)
    report = run_gate(ir, texts)

    queue = review_queue(ir, report)
    metrics = semantic_metrics(ir, report)
    write_json(out / "review-queue.json", queue)
    write_json(out / "semantic-metrics.json", metrics)

    by_kind: dict[str, int] = {}
    for item in queue["items"]:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    summary = {
        "review_items": queue["total"],
        "review_items_by_kind": by_kind,
        "clauses": metrics["clauses"],
        "graph_eligible_clauses": metrics["graph_eligible_clauses"],
        "admitted_decisions": metrics["admitted_decisions"],
        "admitted_processes": metrics["admitted_processes"],
        "synthesis": metrics["synthesis"],
    }
    write_json(out / "governance-summary.json", summary)
    return StageResult(
        "governance", 7, out, count_files(out), time.monotonic() - started, summary
    )


# ---------------------------------------------------------------------------
# 08 projection
# ---------------------------------------------------------------------------


def stage_projection(
    *, root: Path, graph_name: str, profile: CompilerProfile = CompilerProfile.EXECUTABLE_SUBSET
) -> StageResult:
    """Emit the knowledge graph, DMN, BPMN, traceability and manifest."""
    started = time.monotonic()
    out = stage_dir(root, "projection")
    ir, texts = load_ir(root)
    report = run_gate(ir, texts)

    graph = project_graph(ir, report, graph_name=graph_name)
    dmn = compile_dmn(ir, report, profile=profile)
    bpmn = compile_bpmn(ir, report, profile=profile)
    problems = [f"{dmn.filename}: {p}" for p in validate_dmn(dmn.xml)]
    problems += [
        f"{bpmn.filename}: {p}"
        for p in validate_bpmn(bpmn.xml, emitted_decision_ids=frozenset(dmn.emitted_ids))
    ]

    write_json(out / "graph-v2.json", graph)
    (out / dmn.filename).write_text(dmn.xml, encoding="utf-8")
    (out / bpmn.filename).write_text(bpmn.xml, encoding="utf-8")
    write_json(out / "traceability.json", build_traceability(ir, report, [dmn, bpmn]))
    write_json(
        out / "compilation-report.json", build_compilation_report(ir, report, [dmn, bpmn])
    )
    write_json(
        out / "manifest.json",
        build_manifest(
            ir, report, [dmn, bpmn], profile=profile.value,
            extra={"structural_problems": problems} if problems else None,
        ),
    )
    summary = {
        "graph_rules": graph["metadata"]["total_rules"],
        "entity_types": graph["metadata"]["total_entity_types"],
        "dmn_decisions": len(dmn.emitted_ids),
        "bpmn_processes": len(bpmn.emitted_ids),
        "structural_problems": problems,
    }
    write_json(out / "projection-summary.json", summary)
    return StageResult("projection", 8, out, count_files(out), time.monotonic() - started, summary)


# ---------------------------------------------------------------------------
# 09 visualization
# ---------------------------------------------------------------------------


def stage_visualization(*, root: Path, title: str) -> StageResult:
    """Render the HTML report over everything the earlier stages produced."""
    from visualization.report import ReportData, write_report

    started = time.monotonic()
    out = stage_dir(root, "visualization")
    ir, _ = load_ir(root)

    def optional(stage: str, filename: str) -> dict[str, Any]:
        """Read a stage artefact if that stage ran, so a partial run still renders."""
        path = stage_dir(root, stage) / filename
        return read_json(path) if path.exists() else {}

    compilation = optional("projection", "compilation-report.json")

    def emitted(suffix: str) -> list[str]:
        for artifact in compilation.get("artifacts", ()):
            if artifact.get("filename", "").endswith(suffix):
                return list(artifact.get("emitted", ()))
        return []

    stages = read_json(root / "run-summary.json").get("stages", []) if (
        root / "run-summary.json"
    ).exists() else []

    data = ReportData(
        title=title,
        ir=ir,
        gate=optional("gate", "gate-report.json"),
        graph=optional("projection", "graph-v2.json"),
        stages=stages,
        model=optional("model_extraction", "run-summary.json"),
        ingestion=optional("ingestion", "ingestion-summary.json"),
        semantic=optional("semantic_assembly", "semantic-summary.json"),
        governance=optional("governance", "governance-summary.json"),
        dmn_ids=emitted(".dmn"),
        bpmn_ids=emitted(".bpmn"),
        generated_at=_dt.datetime.now(_dt.timezone.utc).strftime("%d %B %Y %H:%M UTC"),
    )
    report = write_report(
        data, out / f"{title.lower().replace(' ', '_')}_knowledge_graph.html"
    )
    summary = {
        "report": report.name,
        "bytes": report.stat().st_size,
        "clauses_rendered": len(ir.clauses),
        "graph_library": "vis-network (CDN)",
    }
    write_json(out / "visualization-summary.json", summary)
    return StageResult(
        "visualization", 9, out, count_files(out), time.monotonic() - started, summary
    )


RUNNERS.update(
    {
        "ingestion": stage_ingestion,
        "extraction_requests": stage_extraction_requests,
        "model_extraction": stage_model_extraction,
        "admission": stage_admission,
        "gate": stage_gate,
        "semantic_assembly": stage_semantic_assembly,
        "governance": stage_governance,
        "projection": stage_projection,
        "visualization": stage_visualization,
    }
)
