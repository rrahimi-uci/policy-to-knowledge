"""Deterministic reference evaluation of Policy IR expressions and decisions."""

from importlib import import_module

from .evaluator import (  # noqa: F401
    EvaluationContext,
    EvaluationError,
    UNKNOWN,
    evaluate,
    evaluate_decision,
)

_BENCHMARK_EXPORTS = frozenset(
    {
        "BenchmarkCase",
        "BenchmarkDataset",
        "BenchmarkError",
        "BenchmarkPrediction",
        "evaluate_predictions",
        "load_benchmark",
        "load_contract_nli",
        "load_opp115",
        "load_predictions",
        "load_sharc",
    }
)
_RUN_MANIFEST_EXPORTS = frozenset(
    {
        "EvaluationRunManifest",
        "RUN_MANIFEST_SCHEMA_VERSION",
        "RunManifestError",
        "load_evaluation_run_manifest",
    }
)


def __getattr__(name: str) -> object:
    """Keep package re-exports without pre-importing a ``python -m`` target."""
    if name in _BENCHMARK_EXPORTS:
        return getattr(import_module(".benchmarks", __name__), name)
    if name in _RUN_MANIFEST_EXPORTS:
        return getattr(import_module(".run_manifest", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EvaluationContext",
    "EvaluationError",
    "UNKNOWN",
    "evaluate",
    "evaluate_decision",
    *_BENCHMARK_EXPORTS,
    *_RUN_MANIFEST_EXPORTS,
]
