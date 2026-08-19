"""OpenAI direct-baseline runner for existing benchmark adapters.

The runner uses the Responses API with structured JSON and ``store: false``. It
accepts its secret only through a named environment variable and writes no key,
prompt, or API response into its experiment configuration artifact.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .benchmarks import BenchmarkCase, BenchmarkError, load_benchmark
from .ollama_runner import OllamaRunnerError, RunnerResult, parse_model_answer, render_direct_prompt


OPENAI_RUNNER_SCHEMA_VERSION = "p2c-openai-direct-baseline-v1"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


class OpenAIRunnerError(ValueError):
    """Raised for unavailable credentials or invalid OpenAI API responses."""


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenAIRunnerError(f"{where} must be a non-empty string")
    return value


def _output_text(payload: Mapping[str, Any]) -> str:
    """Read text from the documented Responses output-item shape."""
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if not isinstance(output, list):
        raise OpenAIRunnerError("OpenAI response has no output items")
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                return _require_string(part.get("text"), "OpenAI output text")
    raise OpenAIRunnerError("OpenAI response contains no output_text item")


def call_openai(
    *,
    model: str,
    prompt: str,
    api_key_env: str = "OPENAI_API_KEY",
    base_url: str = _DEFAULT_BASE_URL,
    timeout_seconds: float = 120.0,
    opener: Callable[..., Any] = urlopen,
) -> str:
    """Call Responses API without printing, persisting, or accepting a raw key flag."""
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise OpenAIRunnerError(f"no API key found in environment variable {api_key_env!r}")
    body = json.dumps(
        {
            "model": _require_string(model, "model"),
            "input": prompt,
            "store": False,
            "max_output_tokens": 200,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "benchmark_answer",
                    "strict": True,
                    "schema": _ANSWER_SCHEMA,
                }
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/responses",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise OpenAIRunnerError(f"OpenAI Responses API returned HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise OpenAIRunnerError(f"cannot call OpenAI Responses API: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenAIRunnerError(f"OpenAI response is not JSON: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise OpenAIRunnerError("OpenAI response must be an object")
    return _output_text(payload)


def run_openai_direct_baseline(
    cases: Sequence[BenchmarkCase],
    *,
    model: str,
    api_key_env: str,
    base_url: str,
    timeout_seconds: float,
    generate: Callable[..., str] = call_openai,
) -> tuple[RunnerResult, ...]:
    """Generate one answer per case; provider failures remain explicit abstentions."""
    results: list[RunnerResult] = []
    for case in cases:
        try:
            response = generate(
                model=model,
                prompt=render_direct_prompt(case),
                api_key_env=api_key_env,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
            results.append(RunnerResult({"case_id": case.case_id, "answer": parse_model_answer(case.benchmark, response)}))
        except (OpenAIRunnerError, OllamaRunnerError) as exc:
            results.append(RunnerResult({"case_id": case.case_id, "answer": None}, str(exc)))
    return tuple(results)


def configuration_record(
    *,
    benchmark: str,
    source_sha256: str,
    selection: Mapping[str, Any],
    model: str,
    api_key_env: str,
    base_url: str,
    timeout_seconds: float,
    implementation_revision: str,
) -> dict[str, Any]:
    """Return a secret-free OpenAI configuration for run-manifest hashing."""
    return {
        "schema_version": OPENAI_RUNNER_SCHEMA_VERSION,
        "system": {"kind": "direct_baseline", "implementation_revision": implementation_revision},
        "benchmark": {"name": benchmark, "source_sha256": source_sha256, "selection": dict(selection)},
        "provider": "openai_responses",
        "model": _require_string(model, "model"),
        "api_key_env": _require_string(api_key_env, "api_key_env"),
        "base_url": base_url,
        "store": False,
        "structured_output_schema": "benchmark_answer-v1",
        "max_output_tokens": 200,
        "timeout_seconds": timeout_seconds,
    }


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise OpenAIRunnerError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openai_benchmark",
        description="Run an OpenAI Responses direct baseline over an official benchmark split.",
    )
    parser.add_argument("--benchmark", required=True, choices=("sharc", "contract_nli", "opp115"))
    parser.add_argument("--input", required=True, type=Path, metavar="FILE")
    parser.add_argument("--opp115-policy-ids", type=Path, metavar="FILE")
    parser.add_argument("--case-ids", type=Path, metavar="FILE")
    parser.add_argument("--model", required=True)
    parser.add_argument("--predictions-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--config-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--implementation-revision", required=True)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate complete prediction/configuration artifacts for a direct baseline."""
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
        if args.predictions_out == args.config_out:
            parser.error("--predictions-out and --config-out must be different files")
        if args.predictions_out.exists() or args.config_out.exists():
            existing = args.predictions_out if args.predictions_out.exists() else args.config_out
            raise OpenAIRunnerError(f"refusing to overwrite existing file: {existing}")
        results = run_openai_direct_baseline(
            dataset.cases,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
        )
        _write_new(
            args.predictions_out,
            "\n".join(json.dumps(result.prediction, sort_keys=True) for result in results) + "\n",
        )
        configuration = configuration_record(
            benchmark=dataset.benchmark,
            source_sha256=dataset.source_sha256,
            selection=dataset.selection,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            implementation_revision=args.implementation_revision,
        )
        configuration["run"] = {
            "case_count": len(results),
            "abstentions_from_runner_error": [
                {"case_id": result.prediction["case_id"], "error": result.error}
                for result in results
                if result.error is not None
            ],
        }
        _write_new(args.config_out, json.dumps(configuration, indent=2, sort_keys=True) + "\n")
        return 0
    except (BenchmarkError, OpenAIRunnerError) as exc:
        parser.error(f"OpenAI baseline error: {exc}")


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
