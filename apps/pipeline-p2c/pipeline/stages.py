"""Stage definitions and the on-disk layout they share.

Stages are numbered in execution order and each owns a directory named
``<NN>_<stage_name>``. A stage reads what it needs from earlier directories and writes
everything it produces into its own, so the run is inspectable at every step and
resumable from any of them.

The split follows where the costs and the risks are, not tidiness:

* ingestion is slow (minutes of PDF extraction) and perfectly deterministic, so it is
  paid once and cached;
* the offer is cheap and deterministic, but persisting it is what lets a model pass be
  reproduced or audited later;
* the model pass costs money and can fail per chunk, so raw replies are kept verbatim
  alongside the parsed proposals;
* admission, the semantic layer, gating, governance and projection are all
  deterministic, so a mistake in any of them can be fixed and re-run for free against
  the stored replies.

The semantic layer sits deliberately *before* the executable projections and is never
skipped. The knowledge graph is the canonical representation; DMN and BPMN are narrow
projections of the subset that qualifies for them, which is why a clause can be a
first-class part of the graph while being ineligible for either.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

#: Stage sequence, in execution order. The number is part of the directory name so a
#: listing shows the pipeline order without needing this file.
STAGES: tuple[tuple[int, str, str], ...] = (
    (1, "ingestion", "PDF bytes to hashed canonical text, section-aligned chunks and coverage"),
    (2, "extraction_requests", "Numbered text units, generated JSON Schema and prose contract per chunk"),
    (3, "model_extraction", "Model replies and parsed proposals, with token accounting"),
    (4, "admission", "Proposals resolved into evidenced clauses, refusals recorded"),
    (5, "semantic_assembly", "The semantic layer: declared intent, what each clause still lacks, active domain profile"),
    (6, "gate", "Fail-closed evidence and semantic gate; statuses and blockers"),
    (7, "governance", "Reviewer queue for every refusal, and coverage metrics that claim no correctness"),
    (8, "projection", "Knowledge graph, DMN, BPMN, traceability and run manifest"),
    (9, "visualization", "Interactive HTML report over the compiled knowledge graph"),
)

STAGE_BY_NAME = {name: (number, description) for number, name, description in STAGES}


def stage_dir(root: Path, name: str) -> Path:
    """The directory a stage owns, created on demand."""
    if name not in STAGE_BY_NAME:
        raise KeyError(f"unknown stage {name!r}; known: {[s[1] for s in STAGES]}")
    number, _ = STAGE_BY_NAME[name]
    path = root / f"{number:02d}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class StageResult:
    """What a stage produced, for the run summary."""

    name: str
    number: int
    directory: Path
    files: int = 0
    elapsed_seconds: float = 0.0
    summary: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": f"{self.number:02d}_{self.name}",
            "directory": str(self.directory),
            "files_written": self.files,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "summary": dict(self.summary),
        }


def write_json(path: Path, payload: Any) -> None:
    """Write deterministic JSON: sorted keys, two-space indent, trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def count_files(directory: Path) -> int:
    return sum(1 for path in directory.rglob("*") if path.is_file())


#: Registered stage implementations, filled in by :mod:`pipeline.runner`.
RUNNERS: dict[str, Callable[..., StageResult]] = {}


def _load_runners() -> None:
    """Import the module that registers the runners, if it has not been imported yet.

    ``stages`` cannot import ``runner`` at module scope — ``runner`` imports this
    module — so registration is triggered on first use instead.
    """
    if len(RUNNERS) < len(STAGES):
        from . import runner  # noqa: F401


def run_stage(name: str, **kwargs: Any) -> StageResult:
    """Run one stage by name."""
    _load_runners()
    try:
        runner = RUNNERS[name]
    except KeyError as exc:
        raise KeyError(
            f"stage {name!r} has no runner registered; known: {sorted(RUNNERS)}"
        ) from exc
    return runner(**kwargs)
