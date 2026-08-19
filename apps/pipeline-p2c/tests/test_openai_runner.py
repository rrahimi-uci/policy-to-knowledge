"""Tests for the secret-free OpenAI Responses direct-baseline runner."""

from __future__ import annotations

import json

import pytest

from evaluation.benchmarks import load_sharc
from evaluation.openai_runner import (
    OpenAIRunnerError,
    call_openai,
    configuration_record,
    run_openai_direct_baseline,
)

from .test_benchmark_evaluation import _sharc_split, _write_json


def test_call_openai_uses_responses_structured_output_and_no_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("P2K_TEST_OPENAI_KEY", "test-key")
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
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"] == {
        "model": "gpt-5.2",
        "input": "prompt",
        "store": False,
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
    assert configuration["provider"] == "openai_responses"
    assert configuration["store"] is False
    assert "test-key" not in json.dumps(configuration)
