"""Tests for adapters over existing, externally labelled benchmark formats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmarks import (
    BenchmarkError,
    BenchmarkPrediction,
    evaluate_predictions,
    load_contract_nli,
    load_predictions,
    load_sharc,
    main,
)


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sharc_split() -> list[dict[str, object]]:
    return [
        {
            "utterance_id": "sharc-yes",
            "tree_id": "tree-1",
            "source_url": "https://example.test/rule",
            "snippet": "You may receive support if you are eligible.",
            "question": "Can I receive support?",
            "scenario": "I am eligible.",
            "answer": "Yes",
            "history": [{"follow_up_question": "Are you eligible?", "follow_up_answer": "Yes"}],
            "evidence": [],
        },
        {
            "utterance_id": "sharc-question",
            "tree_id": "tree-1",
            "source_url": "https://example.test/rule",
            "snippet": "You may receive support if you are eligible.",
            "question": "Can I receive support?",
            "scenario": "",
            "answer": "Are you eligible?",
            "history": [],
            "evidence": [],
        },
    ]


def _contract_nli_split() -> dict[str, object]:
    text = "Alpha obligation. Beta exception."
    return {
        "labels": {
            "nda-1": {"short_description": "Alpha", "hypothesis": "Alpha is required."},
            "nda-2": {"short_description": "Beta", "hypothesis": "Beta is prohibited."},
        },
        "documents": [
            {
                "id": 7,
                "text": text,
                "spans": [[0, 17], [18, len(text)]],
                "annotation_sets": [
                    {
                        "annotations": {
                            "nda-1": {"choice": "Entailment", "spans": [0]},
                            "nda-2": {"choice": "Contradiction", "spans": [1]},
                        }
                    }
                ],
                "url": "https://example.test/contract",
            }
        ],
    }


def test_sharc_adapter_preserves_questions_and_context(tmp_path: Path) -> None:
    dataset = load_sharc(_write_json(tmp_path / "sharc.json", _sharc_split()))
    assert dataset.benchmark == "sharc"
    assert [case.case_id for case in dataset.cases] == ["sharc-yes", "sharc-question"]
    assert dataset.cases[1].expected_answer == "Are you eligible?"
    assert dataset.cases[0].context["history"] == [
        {"follow_up_question": "Are you eligible?", "follow_up_answer": "Yes"}
    ]


def test_contract_nli_adapter_preserves_existing_evidence_anchors(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "contract.json", _contract_nli_split())
    dataset = load_contract_nli(source)
    assert dataset.benchmark == "contract_nli"
    assert [case.case_id for case in dataset.cases] == ["7:nda-1", "7:nda-2"]
    assert dataset.cases[0].evidence_anchors[1].to_dict() == {
        "evidence_id": "span:1", "start": 18, "end": 33
    }
    assert dataset.cases[0].gold_evidence[0].to_dict() == {
        "evidence_id": "span:0", "start": 0, "end": 17
    }
    tasks = tmp_path / "contract-tasks.json"
    assert main(["--benchmark", "contract_nli", "--input", str(source), "--emit-cases", str(tasks)]) == 0
    first_task = json.loads(tasks.read_text(encoding="utf-8"))["cases"][0]
    assert len(first_task["evidence_anchors"]) == 2
    assert "expected_answer" not in first_task
    assert "gold_evidence" not in first_task


def test_scoring_reports_coverage_outcomes_and_existing_evidence_only(tmp_path: Path) -> None:
    dataset = load_contract_nli(_write_json(tmp_path / "contract.json", _contract_nli_split()))
    report = evaluate_predictions(
        dataset,
        [
            BenchmarkPrediction("7:nda-1", "entailment", ("span:0",)),
            BenchmarkPrediction("7:nda-2", "Entailment", ("span:0",)),
        ],
    )
    assert report["outcome"]["coverage"] == 1.0
    assert report["outcome"]["overall_accuracy"] == 0.5
    assert report["outcome"]["answered_accuracy"] == 0.5
    assert report["outcome"]["per_label"]["Entailment"] == {
        "support": 1,
        "precision": 0.5,
        "recall": 1.0,
        "f1": pytest.approx(2 / 3),
    }
    assert report["outcome"]["per_label"]["Contradiction"] == {
        "support": 1,
        "precision": None,
        "recall": 0.0,
        "f1": None,
    }
    assert report["outcome"]["macro_f1"] == pytest.approx(2 / 3)
    assert report["evidence"] == {
        "scored_cases": 2,
        "true_positives": 1,
        "false_positives": 1,
        "false_negatives": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }


def test_missing_predictions_are_visible_abstentions_and_unknown_ids_fail(tmp_path: Path) -> None:
    dataset = load_sharc(_write_json(tmp_path / "sharc.json", _sharc_split()))
    report = evaluate_predictions(dataset, [BenchmarkPrediction("sharc-yes", "Yes")])
    assert report["outcome"]["abstentions"] == 1
    assert report["outcome"]["coverage"] == 0.5
    with pytest.raises(BenchmarkError, match="unknown case IDs"):
        evaluate_predictions(dataset, [BenchmarkPrediction("not-in-split", "Yes")])
    with pytest.raises(BenchmarkError, match="unknown evidence anchors"):
        evaluate_predictions(dataset, [BenchmarkPrediction("sharc-yes", "Yes", ("invented",))])


def test_cli_emits_cases_and_scores_jsonl_predictions(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())
    cases, predictions, report = tmp_path / "cases.json", tmp_path / "predictions.jsonl", tmp_path / "report.json"
    assert main(["--benchmark", "sharc", "--input", str(source), "--emit-cases", str(cases)]) == 0
    emitted = json.loads(cases.read_text(encoding="utf-8"))
    assert emitted["schema_version"] == "p2c-open-benchmark-v1"
    assert "expected_answer" not in emitted["cases"][0]
    assert "gold_evidence" not in emitted["cases"][0]
    predictions.write_text('{"case_id": "sharc-yes", "answer": "Yes"}\n', encoding="utf-8")
    assert main(
        ["--benchmark", "sharc", "--input", str(source), "--predictions", str(predictions), "--out", str(report)]
    ) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["outcome"]["coverage"] == 0.5
    assert load_predictions(predictions) == (BenchmarkPrediction("sharc-yes", "Yes", ()),)


def test_cli_uses_usage_exit_code_for_invalid_option_combinations(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())
    with pytest.raises(SystemExit) as excinfo:
        main(["--benchmark", "sharc", "--input", str(source), "--predictions", str(tmp_path / "predictions.jsonl")])
    assert excinfo.value.code == 2


def test_cli_uses_usage_exit_code_for_benchmark_errors(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "invalid.json", {"not": "a split"})
    with pytest.raises(SystemExit) as excinfo:
        main(["--benchmark", "sharc", "--input", str(source), "--emit-cases", str(tmp_path / "cases.json")])
    assert excinfo.value.code == 2
