"""OpenAI direct-baseline runner for existing benchmark adapters.

The runner uses the Responses API with structured JSON and ``store: false``. It
accepts its secret only through a named environment variable and writes no key,
prompt, or API response into its experiment configuration artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .benchmarks import BenchmarkCase, BenchmarkError, load_benchmark
from .ollama_runner import OllamaRunnerError, RunnerResult, parse_model_answer, render_direct_prompt
from .protocol import DIRECT_PROMPT_VERSION, ProtocolError, protocol_record, validate_model_and_decoding
from .run_manifest import build_run_manifest_record


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
    temperature: float = 0.0,
    schema: Mapping[str, Any] | None = None,
    schema_name: str = "benchmark_answer",
    max_output_tokens: int = 200,
    opener: Callable[..., Any] = urlopen,
) -> str:
    """Call Responses API without printing, persisting, or accepting a raw key flag."""
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise OpenAIRunnerError(f"no API key found in environment variable {api_key_env!r}")
    if temperature < 0 or temperature > 2:
        raise OpenAIRunnerError("temperature must be between 0 and 2")
    if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
        raise OpenAIRunnerError("max_output_tokens must be a positive integer")
    body = json.dumps(
        {
            "model": _require_string(model, "model"),
            "input": prompt,
            "store": False,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _require_string(schema_name, "schema_name"),
                    "strict": True,
                    "schema": dict(schema or _ANSWER_SCHEMA),
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
    temperature: float = 0.0,
    generate: Callable[..., str] = call_openai,
) -> tuple[RunnerResult, ...]:
    """Generate one answer per case; provider failures remain explicit abstentions."""
    validate_model_and_decoding(model=model, decoding={"temperature": temperature})
    results: list[RunnerResult] = []
    for case in cases:
        try:
            response = generate(
                model=model,
                prompt=render_direct_prompt(case),
                api_key_env=api_key_env,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
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
    temperature: float = 0.0,
    implementation_revision: str,
) -> dict[str, Any]:
    """Return a secret-free OpenAI configuration for run-manifest hashing."""
    decoding = {"temperature": temperature}
    validate_model_and_decoding(model=model, decoding=decoding)
    return {
        "schema_version": OPENAI_RUNNER_SCHEMA_VERSION,
        "system": {"kind": "direct_baseline", "implementation_revision": implementation_revision},
        "benchmark": {"name": benchmark, "source_sha256": source_sha256, "selection": dict(selection)},
        "api_backend": "openai_responses",
        "model": _require_string(model, "model"),
        "api_key_env": _require_string(api_key_env, "api_key_env"),
        "base_url": base_url,
        "store": False,
        "protocol": protocol_record(prompt_versions=(DIRECT_PROMPT_VERSION,)),
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
    parser.add_argument("--model", default="gpt-5.2")
    parser.add_argument("--predictions-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--config-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--run-manifest-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--implementation-revision", required=True)
    parser.add_argument("--system-id", default="policy-to-knowledge")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate complete prediction/configuration artifacts for a direct baseline."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.opp115_policy_ids and args.benchmark != "opp115":
        parser.error("--opp115-policy-ids requires --benchmark opp115")
    try:
        validate_model_and_decoding(model=args.model, decoding={"temperature": args.temperature})
        dataset = load_benchmark(
            args.benchmark,
            args.input,
            policy_ids_path=args.opp115_policy_ids,
            case_ids_path=args.case_ids,
        )
        paths = (args.predictions_out, args.config_out, args.run_manifest_out)
        if len(set(paths)) != len(paths):
            parser.error("prediction, configuration, and run-manifest outputs must differ")
        if any(path.exists() for path in paths):
            existing = next(path for path in paths if path.exists())
            raise OpenAIRunnerError(f"refusing to overwrite existing file: {existing}")
        results = run_openai_direct_baseline(
            dataset.cases,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            temperature=args.temperature,
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
            temperature=args.temperature,
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
        manifest = build_run_manifest_record(
            run_id=args.run_id,
            system_id=args.system_id,
            system_kind="direct_baseline",
            implementation_revision=args.implementation_revision,
            configuration_sha256=hashlib.sha256(args.config_out.read_bytes()).hexdigest(),
            benchmark=dataset.benchmark,
            benchmark_source_sha256=dataset.source_sha256,
            selection=dataset.selection,
            predictions_sha256=hashlib.sha256(args.predictions_out.read_bytes()).hexdigest(),
        )
        _write_new(args.run_manifest_out, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return 0
    except (BenchmarkError, OpenAIRunnerError, ProtocolError) as exc:
        parser.error(f"OpenAI baseline error: {exc}")


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
