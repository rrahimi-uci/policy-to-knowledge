"""Tests for the secret-free OpenAI Responses direct-baseline runner."""

from __future__ import annotations

import hashlib
import json

import pytest

from evaluation.benchmarks import load_sharc
from evaluation.openai_runner import (
    OpenAIRunnerError,
    call_openai,
    configuration_record,
    main,
    run_openai_direct_baseline,
)
from evaluation.ollama_runner import RunnerResult
from evaluation.run_manifest import load_evaluation_run_manifest

from .test_benchmark_evaluation import _sharc_split, _write_json


def test_call_openai_uses_responses_structured_output_and_no_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_api_key = "test-key"
    monkeypatch.setenv("P2K_TEST_OPENAI_KEY", test_api_key)
    captured: dict[str, object] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return b'{"output":[{"type":"message","content":[{"type":"output_text","text":"{\\"answer\\": \\"Yes\\"}"}]}]}'

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_opener(request: object, *, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["authorization"] = request.get_header("Authorization")  # type: ignore[attr-defined]
        captured["body"] = json.loads(request.data)  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        return FakeResponse()

    assert call_openai(
        model="gpt-5.2", prompt="prompt", api_key_env="P2K_TEST_OPENAI_KEY", opener=fake_opener
    ) == '{"answer": "Yes"}'
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["authorization"] == f"Bearer {test_api_key}"
    assert captured["body"] == {
        "model": "gpt-5.2",
            "input": "prompt",
            "store": False,
            "temperature": 0.0,
            "max_output_tokens": 200,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "benchmark_answer",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
            }
        },
    }


def test_openai_runner_records_failures_as_abstentions(tmp_path) -> None:
    dataset = load_sharc(_write_json(tmp_path / "sharc.json", _sharc_split()))

    def fake_generate(**kwargs: object) -> str:
        if "SCENARIO:\nI am eligible." in str(kwargs["prompt"]):
            return '{"answer": "Yes"}'
        raise OpenAIRunnerError("rate limited")

    results = run_openai_direct_baseline(
        dataset.cases,
        model="gpt-5.2",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        generate=fake_generate,
    )
    assert [result.prediction for result in results] == [
        {"case_id": "sharc-yes", "answer": "Yes"},
        {"case_id": "sharc-question", "answer": None},
    ]
    assert results[1].error == "rate limited"


def test_openai_configuration_is_secret_free() -> None:
    configuration = configuration_record(
        benchmark="sharc",
        source_sha256="a" * 64,
        selection={"selected_case_count": 20},
        model="gpt-5.2",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        timeout_seconds=120,
        implementation_revision="abc123",
    )
    assert configuration["api_backend"] == "openai_responses"
    assert configuration["store"] is False
    assert configuration["protocol"]["model"] == "gpt-5.2"
    assert configuration["protocol"]["decoding"] == {"temperature": 0.0}
    assert "test-key" not in json.dumps(configuration)


def test_openai_cli_writes_hash_bound_run_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())

    def fake_run(cases, **kwargs):
        return tuple(RunnerResult({"case_id": case.case_id, "answer": "Yes"}) for case in cases)

    monkeypatch.setattr("evaluation.openai_runner.run_openai_direct_baseline", fake_run)
    predictions = tmp_path / "predictions.jsonl"
    config = tmp_path / "config.json"
    manifest = tmp_path / "manifest.json"
    assert main(
        [
            "--benchmark", "sharc", "--input", str(source), "--run-id", "sharc-direct-test",
            "--implementation-revision", "test-revision", "--predictions-out", str(predictions),
            "--config-out", str(config), "--run-manifest-out", str(manifest),
        ]
    ) == 0
    loaded = load_evaluation_run_manifest(manifest)
    loaded.validate_for_scoring(
        benchmark="sharc",
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        selection={},
        predictions_sha256=hashlib.sha256(predictions.read_bytes()).hexdigest(),
    )
