"""Paired, manifest-bound comparison reporting for benchmark system variants."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .benchmarks import (
    BenchmarkDataset,
    BenchmarkError,
    BenchmarkPrediction,
    evaluate_predictions,
    load_benchmark,
    load_predictions,
)
from .protocol import PAIRED_BOOTSTRAP_SAMPLES, PAIRED_BOOTSTRAP_SEED
from .run_manifest import RunManifestError, load_evaluation_run_manifest


PAIRED_REPORT_SCHEMA_VERSION = "p2c-paired-benchmark-report-v1"


class PairedEvaluationError(ValueError):
    """Raised when a comparison is not a paired, protocol-compatible experiment."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prediction_by_id(predictions: Iterable[BenchmarkPrediction]) -> dict[str, BenchmarkPrediction]:
    items = tuple(predictions)
    by_id = {item.case_id: item for item in items}
    if len(by_id) != len(items):
        raise PairedEvaluationError("prediction artifact contains duplicate case IDs")
    return by_id


def _correctness(dataset: BenchmarkDataset, predictions: Iterable[BenchmarkPrediction]) -> tuple[bool, ...]:
    by_id = _prediction_by_id(predictions)
    unknown = sorted(set(by_id) - {case.case_id for case in dataset.cases})
    if unknown:
        raise PairedEvaluationError(f"prediction artifact contains unknown case IDs: {unknown[:3]}")
    return tuple(
        bool(item.case_id in by_id and by_id[item.case_id].answer is not None and " ".join(by_id[item.case_id].answer.casefold().split()) == " ".join(item.expected_answer.casefold().split()))
        for item in dataset.cases
    )


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise PairedEvaluationError("cannot compute a bootstrap interval for no cases")
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def paired_bootstrap_accuracy_delta(
    *,
    baseline_correct: Sequence[bool],
    candidate_correct: Sequence[bool],
    samples: int = PAIRED_BOOTSTRAP_SAMPLES,
    seed: int = PAIRED_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Compute an iid paired-bootstrap interval for candidate minus baseline accuracy."""
    if not baseline_correct or len(baseline_correct) != len(candidate_correct):
        raise PairedEvaluationError("paired bootstrap requires equal, non-empty case sequences")
    if samples <= 0:
        raise PairedEvaluationError("paired bootstrap samples must be positive")
    deltas = [int(candidate) - int(baseline) for baseline, candidate in zip(baseline_correct, candidate_correct)]
    rng = random.Random(seed)
    draws = [
        sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas)
        for _ in range(samples)
    ]
    return {
        "point_estimate": sum(deltas) / len(deltas),
        "confidence_interval_95": [_percentile(draws, 0.025), _percentile(draws, 0.975)],
        "samples": samples,
        "seed": seed,
        "candidate_wins": sum(delta == 1 for delta in deltas),
        "candidate_losses": sum(delta == -1 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
    }


def load_policy_ir_trace(path: Path, dataset: BenchmarkDataset) -> dict[str, Mapping[str, Any]]:
    """Load a safe PolicyIR trace and ensure it covers exactly the paired cases."""
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise PairedEvaluationError(f"cannot read PolicyIR trace {path}: {exc}") from exc
    trace: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(records):
        if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
            raise PairedEvaluationError(f"PolicyIR trace record {index} must contain case_id")
        if not isinstance(item.get("compiler_admitted"), bool):
            raise PairedEvaluationError(f"PolicyIR trace record {index} lacks boolean compiler_admitted")
        if item["case_id"] in trace:
            raise PairedEvaluationError(f"PolicyIR trace repeats case {item['case_id']!r}")
        trace[item["case_id"]] = item
    expected = {case.case_id for case in dataset.cases}
    if set(trace) != expected:
        missing = sorted(expected - set(trace))
        extra = sorted(set(trace) - expected)
        raise PairedEvaluationError(
            f"PolicyIR trace must cover exactly the paired cases (missing={missing[:3]}, extra={extra[:3]})"
        )
    return trace


def paired_report(
    *,
    dataset: BenchmarkDataset,
    baseline_predictions: Iterable[BenchmarkPrediction],
    candidate_predictions: Iterable[BenchmarkPrediction],
    policy_ir_trace: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Score paired direct and PolicyIR outputs without changing either artifact."""
    baseline_items = tuple(baseline_predictions)
    candidate_items = tuple(candidate_predictions)
    baseline_correct = _correctness(dataset, baseline_items)
    candidate_correct = _correctness(dataset, candidate_items)
    compiler_admitted = sum(bool(policy_ir_trace[case.case_id]["compiler_admitted"]) for case in dataset.cases)
    query_admitted = sum(bool(policy_ir_trace[case.case_id].get("query_admitted", False)) for case in dataset.cases)
    return {
        "schema_version": PAIRED_REPORT_SCHEMA_VERSION,
        "benchmark": dataset.benchmark,
        "source": {"path": str(dataset.source_path), "sha256": dataset.source_sha256},
        "selection": dict(dataset.selection),
        "baseline": evaluate_predictions(dataset, baseline_items),
        "policy_ir": evaluate_predictions(dataset, candidate_items),
        "paired_accuracy": paired_bootstrap_accuracy_delta(
            baseline_correct=baseline_correct, candidate_correct=candidate_correct
        ),
        "policy_ir_admission": {
            "total_cases": len(dataset.cases),
            "compiler_admitted_cases": compiler_admitted,
            "compiler_admission_rate": compiler_admitted / len(dataset.cases),
            "query_admitted_cases": query_admitted,
            "query_admission_rate": query_admitted / len(dataset.cases),
        },
    }


def _validate_manifest(path: Path, *, dataset: BenchmarkDataset, predictions_path: Path, kind: str) -> Mapping[str, Any]:
    manifest = load_evaluation_run_manifest(path)
    manifest.validate_for_scoring(
        benchmark=dataset.benchmark,
        source_sha256=dataset.source_sha256,
        selection=dataset.selection,
        predictions_sha256=_sha256(predictions_path),
    )
    if manifest.system_kind != kind:
        raise PairedEvaluationError(
            f"run manifest {path} declares {manifest.system_kind!r}; paired comparison requires {kind!r}"
        )
    return manifest.to_report_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paired_policy_ir_benchmark",
        description="Compare manifest-bound direct and PolicyIR runs on identical official cases.",
    )
    parser.add_argument("--benchmark", required=True, choices=("sharc", "contract_nli", "opp115"))
    parser.add_argument("--input", required=True, type=Path, metavar="FILE")
    parser.add_argument("--opp115-policy-ids", type=Path, metavar="FILE")
    parser.add_argument("--case-ids", type=Path, metavar="FILE")
    parser.add_argument("--baseline-predictions", required=True, type=Path, metavar="FILE")
    parser.add_argument("--baseline-run-manifest", required=True, type=Path, metavar="FILE")
    parser.add_argument("--policy-ir-predictions", required=True, type=Path, metavar="FILE")
    parser.add_argument("--policy-ir-run-manifest", required=True, type=Path, metavar="FILE")
    parser.add_argument("--policy-ir-trace", required=True, type=Path, metavar="FILE")
    parser.add_argument("--out", required=True, type=Path, metavar="FILE")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write one immutable paired report after strict manifest compatibility checks."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.opp115_policy_ids and args.benchmark != "opp115":
        parser.error("--opp115-policy-ids requires --benchmark opp115")
    try:
        if args.out.exists():
            raise PairedEvaluationError(f"refusing to overwrite existing file: {args.out}")
        dataset = load_benchmark(
            args.benchmark,
            args.input,
            policy_ids_path=args.opp115_policy_ids,
            case_ids_path=args.case_ids,
        )
        baseline_manifest = _validate_manifest(
            args.baseline_run_manifest,
            dataset=dataset,
            predictions_path=args.baseline_predictions,
            kind="direct_baseline",
        )
        policy_ir_manifest = _validate_manifest(
            args.policy_ir_run_manifest,
            dataset=dataset,
            predictions_path=args.policy_ir_predictions,
            kind="policy_ir",
        )
        report = paired_report(
            dataset=dataset,
            baseline_predictions=load_predictions(args.baseline_predictions),
            candidate_predictions=load_predictions(args.policy_ir_predictions),
            policy_ir_trace=load_policy_ir_trace(args.policy_ir_trace, dataset),
        )
        report["run_manifests"] = {"baseline": baseline_manifest, "policy_ir": policy_ir_manifest}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (BenchmarkError, RunManifestError, PairedEvaluationError) as exc:
        parser.error(f"paired benchmark error: {exc}")


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
