"""Run the staged pipeline end to end, or any contiguous span of it.

Each stage writes into ``<root>/<NN>_<stage_name>/`` and reads what it needs from the
directories before it, so ``--from`` and ``--to`` can restart a run anywhere without
repeating the expensive parts. Ingestion costs minutes and the model pass costs money;
everything else is free to re-run.

    # everything, from the PDFs to the HTML report
    python -m cli.run_pipeline --input compliance-files/fannie_mae --output outputs

    # re-run only the deterministic tail after fixing a compiler
    python -m cli.run_pipeline --output outputs --from admission

The model pass is the one stage that reaches the network. It is skipped unless
``OPENAI_API_KEY`` is set, and ``--dry-run`` prints the plan without calling anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extraction.model_extractor import (  # noqa: E402
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    http_transport,
)
from pipeline.stages import STAGES, StageResult, run_stage, write_json  # noqa: E402

STAGE_NAMES = tuple(name for _, name, _ in STAGES)

#: Extra arguments a stage needs beyond ``root``. Everything else is read from disk.
_NEEDS_INPUTS = {"ingestion"}
_NEEDS_MODEL = {"model_extraction"}
_NEEDS_NAME = {"projection", "visualization"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", type=Path, default=None,
                        help="Directory of source documents, or a single file. "
                             "Required only when the run includes ingestion.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Run root; each stage creates its own NN_<name> directory.")
    parser.add_argument("--from", dest="start", choices=STAGE_NAMES, default=STAGE_NAMES[0],
                        help="First stage to run (default: %(default)s).")
    parser.add_argument("--to", dest="end", choices=STAGE_NAMES, default=STAGE_NAMES[-1],
                        help="Last stage to run (default: %(default)s).")
    parser.add_argument("--only", choices=STAGE_NAMES, default=None,
                        help="Run exactly one stage.")
    parser.add_argument("--name", default=None,
                        help="Corpus name used in artefact filenames and the report "
                             "title (default: the input directory's name).")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Model for the extraction pass (default: %(default)s).")
    parser.add_argument("--effort", default=DEFAULT_EFFORT,
                        choices=("minimal", "low", "medium", "high"),
                        help="Reasoning effort (default: %(default)s).")
    parser.add_argument("--concurrency", type=int, default=6,
                        help="Concurrent model calls (default: %(default)s).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Send only the first N chunks to the model. For a costed "
                             "pilot before committing to a full corpus.")
    parser.add_argument("--no-resume", action="store_true",
                        help="Call the model again for chunks that already have a reply. "
                             "Use after changing the prompt or the schema.")
    parser.add_argument("--profile", type=Path, default=None,
                        help="Domain profile JSON for the semantic layer.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the stages that would run, and stop.")
    return parser


def selected_stages(args: argparse.Namespace) -> tuple[str, ...]:
    if args.only:
        return (args.only,)
    start = STAGE_NAMES.index(args.start)
    end = STAGE_NAMES.index(args.end)
    if end < start:
        raise SystemExit(f"--to {args.end!r} comes before --from {args.start!r}")
    return STAGE_NAMES[start : end + 1]


def collect_inputs(path: Path) -> tuple[Path, ...]:
    """Every source document under ``path``, in a stable order."""
    if path.is_file():
        return (path,)
    found = tuple(sorted(p for p in path.rglob("*.pdf") if p.is_file()))
    if not found:
        raise SystemExit(f"no PDFs found under {path}")
    return found


def stage_kwargs(name: str, args: argparse.Namespace, corpus: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"root": args.output}
    if name in _NEEDS_INPUTS:
        if args.input is None:
            raise SystemExit("--input is required to run the ingestion stage")
        kwargs["inputs"] = collect_inputs(args.input)
    if name in _NEEDS_MODEL:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise SystemExit(
                "the model_extraction stage needs OPENAI_API_KEY in the environment; "
                "use --from admission to run the deterministic stages against replies "
                "already on disk"
            )
        kwargs.update(
            transport=http_transport(key), model=args.model, effort=args.effort,
            concurrency=args.concurrency, limit=args.limit,
            resume=not args.no_resume,
        )
    if name == "projection":
        kwargs["graph_name"] = corpus
    if name == "visualization":
        kwargs["title"] = corpus.replace("_", " ").title()
    if name == "semantic_assembly":
        kwargs["profile_path"] = args.profile
    return kwargs


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stages = selected_stages(args)
    corpus = args.name or (args.input.name if args.input else args.output.name)

    print(f"run root : {args.output}")
    print(f"corpus   : {corpus}")
    print(f"stages   : {', '.join(stages)}")
    if args.dry_run:
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    results: list[StageResult] = []
    started = time.monotonic()
    for name in stages:
        number, description = next((n, d) for n, s, d in STAGES if s == name)
        print(f"\n── {number:02d} {name} ─ {description}", flush=True)
        result = run_stage(name, **stage_kwargs(name, args, corpus))
        results.append(result)
        print(json.dumps(result.to_dict(), indent=2), flush=True)
        # Written after every stage, not at the end: a run that dies in stage 7 must
        # still leave a record of stages 1 to 6.
        write_json(
            args.output / "run-summary.json",
            {
                "corpus": corpus,
                "stages": [r.to_dict() for r in results],
                "elapsed_seconds": round(time.monotonic() - started, 2),
            },
        )

    print(f"\ndone in {time.monotonic() - started:.0f}s → {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
