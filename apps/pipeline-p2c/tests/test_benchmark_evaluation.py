"""Tests for adapters over existing, externally labelled benchmark formats."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.benchmarks import (
    BenchmarkError,
    BenchmarkPrediction,
    evaluate_predictions,
    load_contract_nli,
    load_opp115,
    load_predictions,
    load_sharc,
    main,
)
from evaluation.run_manifest import RunManifestError, load_evaluation_run_manifest


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_manifest(
    path: Path,
    *,
    source: Path,
    predictions: Path,
    selection: dict[str, object] | None = None,
    source_sha256: str | None = None,
    predictions_sha256: str | None = None,
) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "p2c-evaluation-run-v1",
            "run_id": "sharc-dev-policy-ir-v1",
            "system": {
                "system_id": "policy-to-knowledge",
                "kind": "policy_ir",
                "implementation_revision": "test-revision",
            },
            "configuration": {"sha256": "c" * 64},
            "benchmark": {
                "name": "sharc",
                "source_sha256": source_sha256 or _sha256(source),
                "selection": selection or {},
            },
            "predictions_sha256": predictions_sha256 or _sha256(predictions),
        },
    )


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


def _opp115_root(tmp_path: Path) -> Path:
    root = tmp_path / "OPP-115"
    consolidated = root / "consolidation" / "threshold-0.5-overlap-similarity"
    policies = root / "sanitized_policies"
    consolidated.mkdir(parents=True)
    policies.mkdir()
    policies.joinpath("1_example.com.html").write_text(
        "Introduction|||We collect contact data.<br>|||We retain contact data.",
        encoding="utf-8",
    )
    with consolidated.joinpath("1_example.com.csv").open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "C1,batch,worker,1,1,First Party Collection/Use,{},https://example.test/privacy\n"
            "C2,batch,worker,1,2,Data Retention,{},https://example.test/privacy\n"
        )
    return root


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


def test_opp115_adapter_uses_consolidated_categories_and_policy_level_selection(tmp_path: Path) -> None:
    root = _opp115_root(tmp_path)
    selection = _write_json(tmp_path / "policies.json", ["1_example.com"])
    dataset = load_opp115(root, policy_ids_path=selection)
    assert dataset.benchmark == "opp115"
    assert len(dataset.cases) == 30
    collection = next(case for case in dataset.cases if case.case_id == "1_example.com:1:0")
    retention = next(case for case in dataset.cases if case.case_id == "1_example.com:2:4")
    assert collection.expected_answer == "Yes"
    assert retention.expected_answer == "Yes"
    assert collection.source_text == "We collect contact data."
    assert collection.evidence_anchors == ()
    assert dataset.selection["selected_policy_count"] == 1
    assert dataset.selection["policy_ids_sha256"]
    report = evaluate_predictions(
        dataset,
        [BenchmarkPrediction(case.case_id, case.expected_answer) for case in dataset.cases],
    )
    assert report["outcome"]["overall_accuracy"] == 1.0
    assert report["evidence"]["scored_cases"] == 0
    assert report["selection"] == dataset.selection


def test_opp115_cli_exports_label_safe_tasks_and_records_selection(tmp_path: Path) -> None:
    root = _opp115_root(tmp_path)
    selection = _write_json(tmp_path / "policies.json", ["1_example.com"])
    tasks = tmp_path / "opp-tasks.json"
    assert main(
        [
            "--benchmark", "opp115", "--input", str(root),
            "--opp115-policy-ids", str(selection), "--emit-cases", str(tasks),
        ]
    ) == 0
    emitted = json.loads(tasks.read_text(encoding="utf-8"))
    assert emitted["selection"]["consolidation"] == "threshold-0.5-overlap-similarity"
    assert emitted["selection"]["policy_ids_sha256"]
    assert "expected_answer" not in emitted["cases"][0]


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


def test_run_manifest_binds_scored_report_to_artifacts_and_system_declaration(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text('{"case_id": "sharc-yes", "answer": "Yes"}\n', encoding="utf-8")
    manifest = _run_manifest(tmp_path / "run-manifest.json", source=source, predictions=predictions)
    report = tmp_path / "report.json"

    assert main(
        [
            "--benchmark", "sharc", "--input", str(source), "--predictions", str(predictions),
            "--run-manifest", str(manifest), "--out", str(report),
        ]
    ) == 0

    run = json.loads(report.read_text(encoding="utf-8"))["run_manifest"]
    assert run["sha256"] == _sha256(manifest)
    assert run["system"] == {
        "system_id": "policy-to-knowledge",
        "kind": "policy_ir",
        "implementation_revision": "test-revision",
    }
    assert run["configuration"] == {"sha256": "c" * 64}
    assert run["benchmark"]["source_sha256"] == _sha256(source)
    assert run["predictions_sha256"] == _sha256(predictions)


def test_run_manifest_rejects_mismatched_or_malformed_artifacts(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text('{"case_id": "sharc-yes", "answer": "Yes"}\n', encoding="utf-8")
    manifest = _run_manifest(
        tmp_path / "run-manifest.json",
        source=source,
        predictions=predictions,
        source_sha256="d" * 64,
    )
    loaded = load_evaluation_run_manifest(manifest)
    with pytest.raises(RunManifestError, match="does not match the input corpus"):
        loaded.validate_for_scoring(
            benchmark="sharc",
            source_sha256=_sha256(source),
            selection={},
            predictions_sha256=_sha256(predictions),
        )
    _write_json(
        manifest,
        {
            "schema_version": "p2c-evaluation-run-v1",
            "run_id": "bad-kind",
            "system": {"system_id": "p2k", "kind": "unknown", "implementation_revision": "r"},
            "configuration": {"sha256": "c" * 64},
            "benchmark": {"name": "sharc", "source_sha256": _sha256(source), "selection": {}},
            "predictions_sha256": _sha256(predictions),
        },
    )
    with pytest.raises(RunManifestError, match="system.kind"):
        load_evaluation_run_manifest(manifest)


@pytest.mark.parametrize(
    ("manifest_selection", "scoring_selection", "manifest_predictions_sha256", "error"),
    [
        ({"selected_policy_count": 1}, {}, None, "selection does not match"),
        ({}, {}, "d" * 64, "predictions_sha256 does not match"),
    ],
)
def test_run_manifest_rejects_split_and_prediction_mismatches(
    tmp_path: Path,
    manifest_selection: dict[str, object],
    scoring_selection: dict[str, object],
    manifest_predictions_sha256: str | None,
    error: str,
) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text('{"case_id": "sharc-yes", "answer": "Yes"}\n', encoding="utf-8")
    manifest = _run_manifest(
        tmp_path / "run-manifest.json",
        source=source,
        predictions=predictions,
        selection=manifest_selection,
        predictions_sha256=manifest_predictions_sha256,
    )
    with pytest.raises(RunManifestError, match=error):
        load_evaluation_run_manifest(manifest).validate_for_scoring(
            benchmark="sharc",
            source_sha256=_sha256(source),
            selection=scoring_selection,
            predictions_sha256=_sha256(predictions),
        )


def test_cli_rejects_run_manifest_without_a_scoring_action(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "sharc.json", _sharc_split())
    manifest = _write_json(tmp_path / "run-manifest.json", {})
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--benchmark", "sharc", "--input", str(source), "--emit-cases", str(tmp_path / "cases.json"),
                "--run-manifest", str(manifest),
            ]
        )
    assert excinfo.value.code == 2


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
