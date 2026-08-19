"""``compile_policy`` - gate a Policy IR document and emit its projections.

Usage examples::

    # Compile a built-in conformance fixture end to end
    python -m cli.compile_policy --fixture notice_process --out build/

    # Compile a Policy IR file, supplying the canonical texts its spans cite
    python -m cli.compile_policy --ir ir.json --source-dir sources/ --out build/

    # Import a legacy knowledge graph as unevidenced candidates
    python -m cli.compile_policy --legacy-graph optimized_compliance_knowledge_graph.json \\
        --compile graph --out build/

Exit codes are meaningful, because "we refused to compile most of this" and "the
run is broken" are different outcomes:

* ``0`` - the run completed; refusals are reported, not fatal.
* ``1`` - something that *was* emitted failed a structural check.
* ``2`` - the Policy IR itself is malformed (duplicate IDs, requirement cycles).
* ``3`` - a ``--fail-on-*`` condition the caller asked about was met.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(_ROOT))

from adapters import import_legacy_graph  # noqa: E402
from compilers.run import TARGETS, CompileResult, compile_all  # noqa: E402
from policy_ir.enums import CompilerProfile  # noqa: E402
from policy_ir.models import PolicyIR  # noqa: E402
from validation import blockers as codes  # noqa: E402

def drop_empty(data: dict) -> dict:
    """Omit empty metadata values so an ingest-only run has no misleading keys."""
    return {key: value for key, value in data.items() if value}


EXIT_OK = 0
EXIT_STRUCTURAL = 1
EXIT_INVALID_IR = 2
EXIT_CONDITION = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compile_policy",
        description="Gate Policy IR v2 and compile the graph, DMN and BPMN projections.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--ir", type=Path, help="Path to a Policy IR v2 JSON document.")
    source.add_argument("--fixture", help="Name of a built-in conformance fixture.")
    source.add_argument(
        "--legacy-graph",
        type=Path,
        help="Path to a legacy optimized_compliance_knowledge_graph.json to import.",
    )
    source.add_argument(
        "--ingest",
        type=Path,
        nargs="+",
        metavar="PDF",
        help="Ingest one or more PDFs into a Policy IR skeleton: hashed canonical "
        "text, section-aligned chunks with real character offsets, and a coverage "
        "ledger. Emits policy-ir-v2.json alongside the projections.",
    )
    parser.add_argument(
        "--list-fixtures", action="store_true", help="List the built-in fixtures and exit."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Directory of canonical texts named <document_id>.txt.",
    )
    parser.add_argument(
        "--source-map",
        type=Path,
        help="JSON object mapping document_id to a canonical text file path.",
    )
    parser.add_argument("--out", type=Path, help="Directory to write artefacts into.")
    parser.add_argument(
        "--compile",
        default=",".join(TARGETS),
        help=f"Comma-separated targets. Choose from {list(TARGETS)}. "
        "'graph' is the legacy-compatible projection.",
    )
    parser.add_argument(
        "--compiler-profile",
        choices=[profile.value for profile in CompilerProfile],
        default=CompilerProfile.EXECUTABLE_SUBSET.value,
        help="'review' annotates unresolved items; 'executable_subset' emits only "
        "fully admitted elements.",
    )
    parser.add_argument(
        "--graph-name", default="policy_graph", help="Name recorded in graph metadata."
    )
    parser.add_argument(
        "--run-timestamp",
        help="Optional ISO timestamp recorded in the manifest. Omit for byte-stable output.",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="After --ingest, run the deterministic model-free extractor: normative "
        "sentences become evidenced, untyped, graph-only clauses. This is the baseline "
        "a model-driven extractor has to beat; it types nothing and so reaches neither "
        "DMN nor BPMN.",
    )
    parser.add_argument(
        "--emit-requests",
        type=Path,
        metavar="DIR",
        help="With --ingest: write one extraction request per chunk, each with the JSON "
        "Schema and prose contract a model-driven extractor should be given. The schema "
        "constrains citations to the offered unit indices, so a citation to unseen text "
        "cannot be produced.",
    )
    parser.add_argument(
        "--proposals",
        type=Path,
        nargs="+",
        metavar="FILE",
        help="With --ingest: admit extractor proposals. Ingestion is deterministic, so "
        "re-ingesting rebuilds byte-identical requests and the unit indices still resolve.",
    )
    parser.add_argument(
        "--emit-semantic-proposal-schema",
        type=Path,
        metavar="FILE",
        help="Write the generated JSON Schema for file-backed semantic additions. Providers may "
        "propose typed records but cannot create documents, chunks, or evidence spans.",
    )
    parser.add_argument(
        "--semantic-proposals",
        type=Path,
        nargs="+",
        metavar="FILE",
        help="Apply one or more schema-constrained semantic proposal files after loading the IR. "
        "Every citation must resolve to application-owned evidence; the evidence gate still "
        "decides graph, DMN, and BPMN admission.",
    )
    parser.add_argument(
        "--domain-profile",
        type=Path,
        metavar="FILE",
        help="Optional data-only domain profile. It can narrow accepted source formats and "
        "semantic relation types but cannot relax compiler admission.",
    )
    parser.add_argument(
        "--emit-synthesis-report",
        type=Path,
        metavar="FILE",
        help="Write conservative DMN/BPMN synthesis opportunities and abstention reasons. "
        "This report never creates executable models by itself.",
    )
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=20_000,
        help="Cap on chunk length when a section is long (default 20000). Offsets are "
        "absolute, so the cap cannot move a span.",
    )
    parser.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        help="Restrict executable projections to clauses in force on this date. "
        "Explicit by design: the compiler never reads the clock.",
    )
    parser.add_argument(
        "--fail-on-invalid-ir",
        action="store_true",
        help="Exit non-zero when the Policy IR itself is malformed.",
    )
    parser.add_argument(
        "--fail-on-unresolved-reference",
        action="store_true",
        help="Exit non-zero when any cross reference does not resolve.",
    )
    parser.add_argument(
        "--fail-on-blocker",
        action="append",
        default=[],
        metavar="CODE",
        help="Exit non-zero if this blocker code appears. Repeatable.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compile and report without writing files."
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress the summary.")
    return parser


def load_texts(
    ir: PolicyIR, source_dir: Path | None, source_map: Path | None
) -> tuple[dict[str, str], list[str]]:
    """Load canonical texts for the IR's documents.

    A missing text is reported rather than silently tolerated: without it the gate
    refuses every span in that document, and the caller deserves to know why.
    """
    texts: dict[str, str] = {}
    warnings: list[str] = []
    mapping: dict[str, Path] = {}
    if source_map is not None:
        raw = json.loads(source_map.read_text(encoding="utf-8"))
        mapping.update({key: Path(value) for key, value in raw.items()})
    for document in ir.documents:
        path = mapping.get(document.document_id)
        if path is None and source_dir is not None:
            candidate = source_dir / f"{document.document_id}.txt"
            path = candidate if candidate.exists() else None
        if path is None:
            warnings.append(
                f"no canonical text supplied for {document.document_id} "
                f"({document.source_uri}); its spans cannot be verified"
            )
            continue
        texts[document.document_id] = path.read_text(encoding="utf-8")
    return texts, warnings


def _summarise(result: CompileResult, warnings: Sequence[str]) -> str:
    lines = [
        f"profile: {result.profile.value}",
        *([f"as of: {result.manifest['as_of']}"] if result.manifest.get("as_of") else []),
        f"admitted decisions: {len(result.report.admitted_decisions())}",
        f"admitted processes: {len(result.report.admitted_processes())}",
    ]
    if result.graph is not None:
        lines.append(f"graph rules projected: {result.graph['metadata']['total_rules']}")
    for artifact in result.artifacts:
        lines.append(
            f"{artifact.filename}: {len(artifact.emitted_ids)} emitted, "
            f"{len(artifact.skipped)} refused"
        )
    counts = result.report.counts_by_code()
    if counts:
        lines.append("blockers: " + ", ".join(f"{code}={count}" for code, count in counts.items()))
    else:
        lines.append("blockers: none")
    for warning in warnings:
        lines.append(f"warning: {warning}")
    for problem in result.structural_problems:
        lines.append(f"STRUCTURAL: {problem}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_fixtures:
        from fixtures import all_fixtures

        for name, item in sorted(all_fixtures().items()):
            print(f"{name}\n    {item.description}")
        return EXIT_OK

    as_of: _dt.date | None = None
    if args.as_of:
        try:
            as_of = _dt.date.fromisoformat(args.as_of)
        except ValueError:
            parser.error(f"--as-of must be an ISO date (YYYY-MM-DD), got {args.as_of!r}")

    targets = tuple(part.strip() for part in args.compile.split(",") if part.strip())
    profile = CompilerProfile(args.compiler_profile)
    warnings: list[str] = []

    if args.fixture:
        from fixtures import fixture as load_fixture

        selected = load_fixture(args.fixture)
        ir, texts = selected.ir, dict(selected.texts)
    elif args.ingest:
        # Imported here so the optional pypdf dependency is only needed by an
        # ingest run. PolicyIR is already imported at module scope: rebinding it
        # locally would shadow it for every other branch of this function.
        from ingestion import SourceRegistry
        from ingestion.pdf import PdfSupportUnavailable, ingest_pdf

        registry = SourceRegistry()
        coverage: list = []
        try:
            for pdf_path in args.ingest:
                if not pdf_path.exists():
                    parser.error(f"{pdf_path} does not exist")
                result = ingest_pdf(
                    registry, pdf_path, max_chunk_chars=args.max_chunk_chars
                )
                coverage.extend(result.coverage)
                warnings.append(
                    f"{pdf_path.name}: {result.page_count} pages, "
                    f"{len(result.canonical_text):,} canonical characters, "
                    f"{len(result.headings)} headings, {len(result.chunks)} chunks"
                )
                if result.pages_without_text:
                    warnings.append(
                        f"{pdf_path.name}: {len(result.pages_without_text)} page(s) "
                        f"produced no extractable text "
                        f"({result.extraction_gap:.1%} of the document) and are recorded "
                        "as extraction_failed, not silently dropped"
                    )
        except PdfSupportUnavailable as exc:
            parser.error(str(exc))
            return EXIT_CONDITION  # pragma: no cover - argparse exits
        clauses: tuple = ()
        spans: tuple = ()
        role = "ingestion_skeleton"
        extraction_stats: dict = {}

        if args.emit_requests:
            from extraction.contract import proposal_schema, render_instructions
            from extraction.offer import build_requests

            requests = build_requests(registry, registry.chunk_tuple())
            args.emit_requests.mkdir(parents=True, exist_ok=True)
            for request in requests:
                stem = args.emit_requests / request.chunk_id
                stem.with_suffix(".request.json").write_text(
                    json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                stem.with_suffix(".schema.json").write_text(
                    json.dumps(proposal_schema(request), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                stem.with_suffix(".instructions.md").write_text(
                    render_instructions(request), encoding="utf-8"
                )
            warnings.append(
                f"emitted {len(requests)} extraction request(s) with schema and "
                f"instructions to {args.emit_requests}"
            )

        if args.proposals:
            from extraction.candidates import CandidateRejected
            from extraction.offer import build_requests
            from extraction.proposals import admit_proposals, proposal_from_dict

            requests = {r.chunk_id: r for r in build_requests(registry, registry.chunk_tuple())}
            admitted: list = []
            admitted_spans: dict = {}
            refused = 0
            for path in args.proposals:
                payload = json.loads(path.read_text(encoding="utf-8"))
                batches = payload if isinstance(payload, list) else [payload]
                for batch in batches:
                    chunk_id = batch.get("chunk_id")
                    request = requests.get(chunk_id)
                    if request is None:
                        parser.error(
                            f"{path}: chunk {chunk_id!r} is not part of this ingestion; "
                            "the proposals and the ingest arguments must match"
                        )
                    try:
                        batch_clauses, batch_spans = admit_proposals(
                            [proposal_from_dict(c) for c in batch.get("candidates", ())],
                            request,
                            registry,
                            document_sha256=registry.documents[
                                request.document_id
                            ].canonical_text_sha256,
                        )
                    except CandidateRejected as exc:
                        refused += 1
                        warnings.append(f"refused proposals for {chunk_id}: {exc}")
                        continue
                    admitted.extend(batch_clauses)
                    admitted_spans.update({s.evidence_id: s for s in batch_spans})
            clauses = tuple(admitted)
            spans = tuple(admitted_spans[k] for k in sorted(admitted_spans))
            role = "model_extraction"
            warnings.append(
                f"admitted {len(clauses)} clause(s) from proposals"
                + (f"; {refused} batch(es) refused" if refused else "")
            )
        if args.extract and not args.proposals:
            from extraction.deterministic import extract_deterministic

            extracted = extract_deterministic(registry, registry.chunk_tuple())
            clauses, spans = extracted.clauses, extracted.spans
            # Extraction coverage supersedes the ingestion note for a chunk it read.
            read = {entry.chunk_id for entry in extracted.coverage}
            coverage = [e for e in coverage if e.chunk_id not in read] + list(
                extracted.coverage
            )
            role = "deterministic_extraction"
            extraction_stats = extracted.stats.to_dict()
            warnings.append(
                f"extraction: {extraction_stats['clauses_emitted']} clause(s) from "
                f"{extraction_stats['normative_sentences']} normative of "
                f"{extraction_stats['sentences_scanned']} sentence(s) "
                f"({extraction_stats['normative_rate']:.1%} normative)"
            )
            warnings.append(
                "extraction: clauses are untyped by construction — no condition, effect "
                "or threshold is typed, so none can reach DMN or BPMN"
            )
        ir = PolicyIR(
            documents=registry.document_tuple(),
            chunks=registry.chunk_tuple(),
            evidence_spans=spans,
            clauses=clauses,
            coverage=tuple(coverage),
            metadata=drop_empty(
                {"artifact_role": role, "extraction_stats": extraction_stats}
            ),
        )
        texts = dict(registry.texts)
    elif args.legacy_graph:
        graph = json.loads(args.legacy_graph.read_text(encoding="utf-8"))
        imported = import_legacy_graph(graph, graph_name=args.legacy_graph.stem)
        ir, texts = imported.ir, {}
        warnings.extend(imported.notes)
    elif args.ir:
        ir = PolicyIR.from_dict(json.loads(args.ir.read_text(encoding="utf-8")))
        texts, text_warnings = load_texts(ir, args.source_dir, args.source_map)
        warnings.extend(text_warnings)
    else:
        parser.error("one of --ir, --fixture or --legacy-graph is required")
        return EXIT_CONDITION  # pragma: no cover - argparse exits

    if args.emit_semantic_proposal_schema:
        from semantic import proposal_schema as semantic_proposal_schema

        args.emit_semantic_proposal_schema.write_text(
            json.dumps(semantic_proposal_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        warnings.append(f"wrote semantic proposal schema to {args.emit_semantic_proposal_schema}")

    if args.semantic_proposals:
        from semantic import AssemblyError, assemble_proposal

        for path in args.semantic_proposals:
            payload = json.loads(path.read_text(encoding="utf-8"))
            batches = payload if isinstance(payload, list) else [payload]
            for batch in batches:
                if not isinstance(batch, dict):
                    parser.error(f"{path}: semantic proposal must be an object or a list of objects")
                try:
                    ir = assemble_proposal(ir, batch)
                except AssemblyError as exc:
                    parser.error(f"{path}: {exc}")
        warnings.append(f"applied {len(args.semantic_proposals)} semantic proposal file(s)")

    if args.domain_profile:
        from semantic import ProfileError, load_profile

        try:
            domain_profile = load_profile(args.domain_profile)
        except ProfileError as exc:
            parser.error(str(exc))
        profile_errors = domain_profile.validate(ir)
        if profile_errors:
            parser.error("domain profile rejected Policy IR: " + "; ".join(profile_errors))
        warnings.append(
            f"domain profile: {domain_profile.profile_id}@{domain_profile.version}"
        )

    if args.emit_synthesis_report:
        from semantic import synthesis_report

        opportunities = synthesis_report(ir)
        args.emit_synthesis_report.write_text(
            json.dumps(
                {"opportunities": [item.to_dict() for item in opportunities]},
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        warnings.append(f"wrote {len(opportunities)} synthesis opportunity record(s)")

    try:
        result = compile_all(
            ir,
            texts,
            profile=profile,
            targets=targets,
            graph_name=args.graph_name,
            run_timestamp=args.run_timestamp,
            as_of=as_of,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return EXIT_CONDITION  # pragma: no cover - argparse exits

    if args.out and not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        files = dict(result.files())
        if args.ingest:
            # The IR is the point of an ingest run: either a skeleton for extraction to
            # consume, or the extracted clauses themselves.
            files["policy-ir-v2.json"] = (
                json.dumps(ir.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            )
        for filename, content in sorted(files.items()):
            (args.out / filename).write_text(content, encoding="utf-8")

    if not args.quiet:
        print(_summarise(result, warnings))

    seen = set(result.report.counts_by_code())
    if args.fail_on_invalid_ir and result.report.fatal:
        return EXIT_INVALID_IR
    if result.structural_problems:
        return EXIT_STRUCTURAL
    if args.fail_on_unresolved_reference and codes.UNRESOLVED_CROSS_REFERENCE in seen:
        return EXIT_CONDITION
    if any(code in seen for code in args.fail_on_blocker):
        return EXIT_CONDITION
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
