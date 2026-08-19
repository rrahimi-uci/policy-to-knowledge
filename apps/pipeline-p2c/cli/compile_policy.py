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
        ir = PolicyIR(
            documents=registry.document_tuple(),
            chunks=registry.chunk_tuple(),
            coverage=tuple(coverage),
            metadata={"artifact_role": "ingestion_skeleton"},
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
            # The skeleton is the point of an ingest run: it is what clause
            # extraction consumes next.
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
