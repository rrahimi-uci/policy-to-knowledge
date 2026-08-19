"""Deterministic reference evaluation of Policy IR expressions and decisions."""

from .evaluator import (  # noqa: F401
    EvaluationContext,
    EvaluationError,
    UNKNOWN,
    evaluate,
    evaluate_decision,
)
