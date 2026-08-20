"""Tests for the evidence-bounded PolicyIR benchmark system variant."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evaluation.benchmarks import BenchmarkPrediction, load_contract_nli, load_sharc
from evaluation.paired import paired_bootstrap_accuracy_delta, paired_report
from evaluation.policy_ir_runner import run_policy_ir_case, select_query_clauses
from evaluation.protocol import ProtocolError
from evaluation.query_ir import QueryIRError, query_from_dict, query_schema

from .test_benchmark_evaluation import _contract_nli_split, _sharc_split, _write_json


def _candidate() -> dict[str, object]:
    return {
        "modality": "obligation",
        "semantic_kind": "documentation_requirement",
        "effect": "require_action",
        "display_unit": 0,
        "citations": [{"role": "effect", "units": [0]}],
    }


def test_extraction_schema_is_closed_over_offered_units(tmp_path) -> None:
    case = load_contract_nli(_write_json(tmp_path / "contract.json", _contract_nli_split())).cases[0]
    captured: dict[str, object] = {}

    def fake_generate(**kwargs: object) -> str:
        captured.update(kwargs)
        return json.dumps({"candidates": []})

    result = run_policy_ir_case(
        case,
        model="gpt-5.2",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        timeout_seconds=1,
        reasoning_effort="medium",
        generate=fake_generate,
    )
    assert result.prediction == {"case_id": "7:nda-1", "answer": None}
    assert result.trace["status"] == "abstained_no_graph_eligible_clause"
    schema = captured["schema"]
    assert isinstance(schema, dict)
    units = schema["properties"]["candidates"]["items"]["properties"]["display_unit"]["enum"]
    assert units == [0, 1]
    kinds = schema["properties"]["candidates"]["items"]["properties"]["semantic_kind"]["enum"]
    assert "decision_rule" not in kinds


def test_policy_ir_runner_derives_answer_and_evidence_from_admitted_clauses(tmp_path) -> None:
    case = load_contract_nli(_write_json(tmp_path / "contract.json", _contract_nli_split())).cases[0]
    calls: list[dict[str, object]] = []

    def fake_generate(**kwargs: object) -> str:
        calls.append(kwargs)
        if kwargs["schema_name"] == "policy_ir_evidence_slice":
            return json.dumps({"candidates": [_candidate()]})
        schema = kwargs["schema"]
        assert isinstance(schema, dict)
        clause_id = schema["properties"]["clause_ids"]["items"]["enum"][0]
        return json.dumps({"truth_value": "supported", "clause_ids": [clause_id]})

    result = run_policy_ir_case(
        case,
        model="gpt-5.2",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        timeout_seconds=1,
        reasoning_effort="medium",
        generate=fake_generate,
    )
    assert result.prediction == {
        "case_id": "7:nda-1",
        "answer": "Entailment",
        "evidence_ids": ["span:0"],
    }
    assert result.trace["compiler_admitted"] is True
    assert result.trace["query_admitted"] is True
    assert "Entailment" not in str(calls[1]["prompt"])
    assert "Alpha obligation." in str(calls[1]["prompt"])


def test_query_ir_refuses_direct_answers_and_unknown_clause_references() -> None:
    with pytest.raises(QueryIRError, match="exactly"):
        query_from_dict(
            {"truth_value": "supported", "clause_ids": [], "answer": "Entailment"},
            benchmark="contract_nli",
        )
    schema = query_schema(benchmark="contract_nli", clause_ids=["clause-1"])
    assert schema["properties"]["clause_ids"]["items"]["enum"] == ["clause-1"]


def test_protocol_refuses_an_unlocked_model_or_decoding(tmp_path) -> None:
    case = load_contract_nli(_write_json(tmp_path / "contract.json", _contract_nli_split())).cases[0]
    with pytest.raises(ProtocolError, match="requires model"):
        run_policy_ir_case(
            case,
            model="other-model",
            api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            timeout_seconds=1,
            reasoning_effort="medium",
            generate=lambda **_: "{}",
        )


def test_query_prompt_preserves_raw_source_and_uses_medium_reasoning(tmp_path) -> None:
    case = load_contract_nli(_write_json(tmp_path / "contract.json", _contract_nli_split())).cases[0]
    calls: list[dict[str, object]] = []

    def fake_generate(**kwargs: object) -> str:
        calls.append(kwargs)
        if kwargs["schema_name"] == "policy_ir_evidence_slice":
            return json.dumps({"candidates": [_candidate()]})
        schema = kwargs["schema"]
        assert isinstance(schema, dict)
        clause_id = schema["properties"]["clause_ids"]["items"]["enum"][0]
        return json.dumps({"truth_value": "supported", "clause_ids": [clause_id]})

    result = run_policy_ir_case(
        case,
        model="gpt-5.2",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        timeout_seconds=1,
        reasoning_effort="medium",
        generate=fake_generate,
    )
    assert result.trace["selected_clause_count"] == 1
    assert "raw_source=Alpha obligation." in str(calls[1]["prompt"])
    assert calls[0]["reasoning_effort"] == "medium"


def test_query_selection_reserves_an_exception_clause(tmp_path) -> None:
    case = load_contract_nli(_write_json(tmp_path / "contract.json", _contract_nli_split())).cases[0]
    clauses = (
        SimpleNamespace(clause_id="alpha", evidence={"effect": ("span-alpha",)}),
        SimpleNamespace(clause_id="exception", evidence={"condition": ("span-exception",)}),
    )
    spans = (
        SimpleNamespace(evidence_id="span-alpha", char_start=0, char_end=17),
        SimpleNamespace(evidence_id="span-exception", char_start=18, char_end=33),
    )
    selected, retained_exception = select_query_clauses(
        case=case, clauses=clauses, spans=spans, evidence_budget=1
    )
    assert [clause.clause_id for clause in selected] == ["exception"]
    assert retained_exception is True


def test_paired_report_has_deterministic_interval_and_admission_rate(tmp_path) -> None:
    dataset = load_sharc(_write_json(tmp_path / "sharc.json", _sharc_split()))
    report = paired_report(
        dataset=dataset,
        baseline_predictions=(
            BenchmarkPrediction("sharc-yes", "No"),
            BenchmarkPrediction("sharc-question", None),
        ),
        candidate_predictions=(
            BenchmarkPrediction("sharc-yes", "Yes"),
            BenchmarkPrediction("sharc-question", "Are you eligible?"),
        ),
        policy_ir_trace={
            "sharc-yes": {"compiler_admitted": True, "query_admitted": True},
            "sharc-question": {"compiler_admitted": False, "query_admitted": False},
        },
    )
    assert report["paired_accuracy"]["point_estimate"] == 1.0
    assert report["paired_accuracy"]["confidence_interval_95"] == [1.0, 1.0]
    assert report["policy_ir_admission"]["compiler_admission_rate"] == 0.5
    assert report["policy_ir"]["outcome"]["overall_accuracy"] == 1.0
    assert paired_bootstrap_accuracy_delta(
        baseline_correct=(False, False), candidate_correct=(True, True)
    )["seed"] == 20260819
