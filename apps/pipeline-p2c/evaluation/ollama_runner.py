"""Local-Ollama direct-baseline runner for existing benchmark adapters.

This runner intentionally implements a direct document-and-query baseline only.
It does not claim to construct or query Policy IR; a PolicyIR comparison needs a
task-valid query adapter and must be implemented as a separate system variant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from .benchmarks import BenchmarkCase, BenchmarkError, load_benchmark


RUNNER_SCHEMA_VERSION = "p2c-local-ollama-direct-baseline-v1"
PROMPT_VERSION = "p2c-direct-policy-qa-v1"
_DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaRunnerError(ValueError):
    """Raised for invalid local-model responses or runner configuration."""


@dataclass(frozen=True)
class RunnerResult:
    """One output record plus an optional, visible failure reason."""

    prediction: Mapping[str, Any]
    error: str | None = None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OllamaRunnerError(f"{where} must be a non-empty string")
    return value


def render_direct_prompt(case: BenchmarkCase) -> str:
    """Render a label-safe prompt from a normalized task, never its gold fields."""
    if case.benchmark == "sharc":
        task = (
            "Answer with Yes, No, Irrelevant, or one concise follow-up question that is "
            "necessary to decide."
        )
    elif case.benchmark == "contract_nli":
        task = "Answer with exactly one of Entailment, Contradiction, or NotMentioned."
    elif case.benchmark == "opp115":
        task = "Answer with exactly Yes or No."
    else:  # pragma: no cover - loader currently constrains this set
        raise OllamaRunnerError(f"unsupported benchmark {case.benchmark!r}")
    context = dict(case.context)
    # Corpus metadata is allowed only where it is already system-facing context.
    scenario = context.get("scenario", "")
    history = context.get("history", [])
    return "\n".join(
        (
            "You are a document-grounded policy question-answering system.",
            "Use only the document and supplied context. Do not use outside knowledge.",
            task,
            "Return exactly one JSON object with one key: answer.",
            "",
            "DOCUMENT:",
            case.source_text,
            "",
            "QUESTION:",
            case.query,
            "",
            "SCENARIO:",
            str(scenario),
            "",
            "HISTORY:",
            json.dumps(history, ensure_ascii=False, sort_keys=True),
        )
    )


def _canonical_answer(benchmark: str, answer: str) -> str:
    normalized = " ".join(answer.casefold().split())
    canonical = {
        "sharc": {"yes": "Yes", "no": "No", "irrelevant": "Irrelevant"},
        "contract_nli": {
            "entailment": "Entailment",
            "contradiction": "Contradiction",
            "notmentioned": "NotMentioned",
            "not mentioned": "NotMentioned",
        },
        "opp115": {"yes": "Yes", "no": "No"},
    }
    return canonical.get(benchmark, {}).get(normalized, answer.strip())


def parse_model_answer(benchmark: str, response_text: str) -> str:
    """Accept only the documented JSON response, with public-label canonicalization."""
    try:
        response = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OllamaRunnerError(f"model response is not JSON: {exc.msg}") from exc
    if not isinstance(response, Mapping) or set(response) != {"answer"}:
        raise OllamaRunnerError("model response must be an object with exactly one key: answer")
    answer = _require_string(response.get("answer"), "model response.answer")
    return _canonical_answer(benchmark, answer)


def call_ollama(
    *,
    model: str,
    prompt: str,
    base_url: str = _DEFAULT_BASE_URL,
    temperature: float = 0.0,
    seed: int = 0,
    num_ctx: int = 8192,
    timeout_seconds: float = 120.0,
    opener: Callable[..., Any] = urlopen,
) -> str:
    """Call Ollama's local ``/api/generate`` endpoint without any SDK dependency."""
    if temperature < 0:
        raise OllamaRunnerError("temperature must be non-negative")
    if num_ctx <= 0:
        raise OllamaRunnerError("num_ctx must be positive")
    body = json.dumps(
        {
            "model": _require_string(model, "model"),
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": temperature, "seed": seed, "num_ctx": num_ctx},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except (OSError, URLError) as exc:
        raise OllamaRunnerError(f"cannot call local Ollama endpoint: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaRunnerError(f"Ollama response is not JSON: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise OllamaRunnerError("Ollama response must be an object")
    return _require_string(payload.get("response"), "Ollama response.response")


def run_direct_baseline(
    cases: Sequence[BenchmarkCase],
    *,
    model: str,
    base_url: str,
    temperature: float,
    seed: int,
    num_ctx: int,
    timeout_seconds: float,
    generate: Callable[..., str] = call_ollama,
) -> tuple[RunnerResult, ...]:
    """Generate one answer per case; failures become explicit scorer abstentions."""
    results: list[RunnerResult] = []
    for case in cases:
        try:
            response = generate(
                model=model,
                prompt=render_direct_prompt(case),
                base_url=base_url,
                temperature=temperature,
                seed=seed,
                num_ctx=num_ctx,
                timeout_seconds=timeout_seconds,
            )
            results.append(RunnerResult({"case_id": case.case_id, "answer": parse_model_answer(case.benchmark, response)}))
        except OllamaRunnerError as exc:
            results.append(RunnerResult({"case_id": case.case_id, "answer": None}, str(exc)))
    return tuple(results)


def configuration_record(
    *,
    benchmark: str,
    source_sha256: str,
    selection: Mapping[str, Any],
    model: str,
    base_url: str,
    temperature: float,
    seed: int,
    num_ctx: int,
    timeout_seconds: float,
    implementation_revision: str,
) -> dict[str, Any]:
    """Return a public, non-secret configuration artifact for a run manifest."""
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "system": {"kind": "direct_baseline", "implementation_revision": implementation_revision},
        "benchmark": {"name": benchmark, "source_sha256": source_sha256, "selection": dict(selection)},
        "model": _require_string(model, "model"),
        "base_url": base_url,
        "prompt_version": PROMPT_VERSION,
        "generation": {
            "temperature": temperature,
            "seed": seed,
            "num_ctx": num_ctx,
            "timeout_seconds": timeout_seconds,
        },
    }


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise OllamaRunnerError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local_ollama_benchmark",
        description="Run a local-Ollama direct baseline over an official benchmark split.",
    )
    parser.add_argument("--benchmark", required=True, choices=("sharc", "contract_nli", "opp115"))
    parser.add_argument("--input", required=True, type=Path, metavar="FILE")
    parser.add_argument("--opp115-policy-ids", type=Path, metavar="FILE")
    parser.add_argument("--case-ids", type=Path, metavar="FILE")
    parser.add_argument("--model", required=True)
    parser.add_argument("--predictions-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--config-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--implementation-revision", required=True)
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate a complete prediction artifact; failures remain explicit abstentions."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.opp115_policy_ids and args.benchmark != "opp115":
        parser.error("--opp115-policy-ids requires --benchmark opp115")
    try:
        dataset = load_benchmark(
            args.benchmark,
            args.input,
            policy_ids_path=args.opp115_policy_ids,
            case_ids_path=args.case_ids,
        )
        prediction_path, config_path = args.predictions_out, args.config_out
        if prediction_path == config_path:
            parser.error("--predictions-out and --config-out must be different files")
        if prediction_path.exists() or config_path.exists():
            existing = prediction_path if prediction_path.exists() else config_path
            raise OllamaRunnerError(f"refusing to overwrite existing file: {existing}")
        results = run_direct_baseline(
            dataset.cases,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
            seed=args.seed,
            num_ctx=args.num_ctx,
            timeout_seconds=args.timeout_seconds,
        )
        _write_new(
            prediction_path,
            "\n".join(json.dumps(result.prediction, sort_keys=True) for result in results) + "\n",
        )
        configuration = configuration_record(
            benchmark=dataset.benchmark,
            source_sha256=dataset.source_sha256,
            selection=dataset.selection,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
            seed=args.seed,
            num_ctx=args.num_ctx,
            timeout_seconds=args.timeout_seconds,
            implementation_revision=args.implementation_revision,
        )
        failures = [
            {"case_id": result.prediction["case_id"], "error": result.error}
            for result in results
            if result.error is not None
        ]
        configuration["run"] = {"case_count": len(results), "abstentions_from_runner_error": failures}
        _write_new(config_path, json.dumps(configuration, indent=2, sort_keys=True) + "\n")
        return 0
    except (BenchmarkError, OllamaRunnerError) as exc:
        parser.error(f"local baseline error: {exc}")


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
