"""Tests for the local, direct-model benchmark baseline runner."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.benchmarks import load_sharc
from evaluation.ollama_runner import (
    OllamaRunnerError,
    call_ollama,
    configuration_record,
    parse_model_answer,
    render_direct_prompt,
    run_direct_baseline,
)

from .test_benchmark_evaluation import _sharc_split, _write_json


def test_prompt_is_label_safe_and_preserves_system_facing_context(tmp_path: Path) -> None:
    dataset = load_sharc(_write_json(tmp_path / "sharc.json", _sharc_split()))
    case = replace(dataset.cases[0], expected_answer="gold-label-must-not-appear")
    prompt = render_direct_prompt(case)
    assert "Can I receive support?" in prompt
    assert "I am eligible." in prompt
    assert case.expected_answer not in prompt
    assert "expected_answer" not in prompt


def test_response_parser_uses_only_public_answer_vocabularies() -> None:
    assert parse_model_answer("contract_nli", '{"answer": "not mentioned"}') == "NotMentioned"
    assert parse_model_answer("sharc", '{"answer": "Are you eligible?"}') == "Are you eligible?"
    with pytest.raises(OllamaRunnerError, match="exactly one key"):
        parse_model_answer("sharc", '{"answer": "Yes", "evidence_ids": []}')


def test_direct_baseline_records_model_failures_as_visible_abstentions(tmp_path: Path) -> None:
    dataset = load_sharc(_write_json(tmp_path / "sharc.json", _sharc_split()))

    def fake_generate(**kwargs: object) -> str:
        if "SCENARIO:\nI am eligible." in str(kwargs["prompt"]):
            return '{"answer": "Yes"}'
        raise OllamaRunnerError("offline")

    results = run_direct_baseline(
        dataset.cases,
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        temperature=0,
        seed=0,
        num_ctx=8192,
        timeout_seconds=10,
        generate=fake_generate,
    )
    assert results[0].prediction == {"case_id": "sharc-yes", "answer": "Yes"}
    assert results[1].prediction == {"case_id": "sharc-question", "answer": None}
    assert results[1].error == "offline"


def test_call_ollama_uses_local_json_contract() -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return b'{"response":"{\\"answer\\": \\"Yes\\"}"}'

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_opener(request: object, *, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["body"] = json.loads(request.data)  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        return FakeResponse()

    assert call_ollama(model="qwen2.5:7b", prompt="prompt", opener=fake_opener) == '{"answer": "Yes"}'
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["body"] == {
        "model": "qwen2.5:7b",
        "prompt": "prompt",
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "seed": 0, "num_ctx": 8192},
    }


def test_configuration_record_is_secret_free_and_binds_runner_settings() -> None:
    configuration = configuration_record(
        benchmark="sharc",
        source_sha256="a" * 64,
        selection={},
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        temperature=0,
        seed=7,
        num_ctx=8192,
        timeout_seconds=120,
        implementation_revision="abc123",
    )
    assert configuration["system"] == {
        "kind": "direct_baseline",
        "implementation_revision": "abc123",
    }
    assert "api_key" not in json.dumps(configuration).casefold()
