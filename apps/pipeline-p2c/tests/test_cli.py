"""CLI behaviour, including the exit codes callers script against.

The distinction the exit codes encode matters: refusing to compile most of a corpus
is a normal outcome and exits 0, while a malformed IR or a structurally broken
artefact is a failure. Conflating them would make the tool either useless in CI or
misleadingly green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.compile_policy import (
    EXIT_CONDITION,
    EXIT_INVALID_IR,
    EXIT_OK,
    load_texts,
    main,
)
from fixtures import all_fixtures
from policy_ir.models import PolicyIR

from .conftest import legacy_graph_paths


def test_fixture_run_writes_every_expected_artefact(tmp_path: Path) -> None:
    code = main(["--fixture", "notice_process", "--out", str(tmp_path), "--quiet"])
    assert code == EXIT_OK
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == [
        "compilation-report.json",
        "decisions.dmn",
        "graph-v2.json",
        "manifest.json",
        "processes-executable.bpmn",
        "traceability.json",
    ]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["compiler_profile"] == "executable_subset"
    assert "run_timestamp" not in manifest


def test_a_supplied_timestamp_is_recorded_but_optional(tmp_path: Path) -> None:
    main(
        [
            "--fixture",
            "notice_process",
            "--out",
            str(tmp_path),
            "--run-timestamp",
            "2026-08-19T00:00:00",
            "--quiet",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_timestamp"] == "2026-08-19T00:00:00"


def test_repeated_runs_write_identical_bytes(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    main(["--fixture", "notice_process", "--out", str(first), "--quiet"])
    main(["--fixture", "notice_process", "--out", str(second), "--quiet"])
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes()


def test_review_profile_names_its_output_differently(tmp_path: Path) -> None:
    main(
        [
            "--fixture",
            "missing_actor_process",
            "--compiler-profile",
            "review",
            "--out",
            str(tmp_path),
            "--quiet",
        ]
    )
    assert (tmp_path / "processes-review.bpmn").exists()
    assert not (tmp_path / "processes-executable.bpmn").exists()


def test_target_selection_limits_what_is_written(tmp_path: Path) -> None:
    main(["--fixture", "notice_process", "--compile", "graph", "--out", str(tmp_path), "--quiet"])
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == [
        "compilation-report.json",
        "graph-v2.json",
        "manifest.json",
        "traceability.json",
    ]


def test_an_unknown_target_is_rejected() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--fixture", "notice_process", "--compile", "sql", "--quiet"])
    assert exit_info.value.code != EXIT_OK


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    code = main(["--fixture", "notice_process", "--out", str(tmp_path), "--dry-run", "--quiet"])
    assert code == EXIT_OK
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_refusals_alone_do_not_fail_the_run(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--fixture", "overlapping_rows", "--dry-run"])
    assert code == EXIT_OK
    output = capsys.readouterr().out
    assert "hit_policy_not_proven" in output


def test_fail_on_blocker_turns_a_refusal_into_an_exit_code() -> None:
    code = main(
        [
            "--fixture",
            "overlapping_rows",
            "--fail-on-blocker",
            "hit_policy_not_proven",
            "--dry-run",
            "--quiet",
        ]
    )
    assert code == EXIT_CONDITION


def test_fail_on_unresolved_reference() -> None:
    assert (
        main(["--fixture", "broken_reference", "--fail-on-unresolved-reference", "--dry-run", "--quiet"])
        == EXIT_CONDITION
    )
    assert main(["--fixture", "broken_reference", "--dry-run", "--quiet"]) == EXIT_OK


def test_fail_on_invalid_ir_detects_a_malformed_document(tmp_path: Path) -> None:
    item = all_fixtures()["eligibility_decision"]
    document = item.ir.to_dict()
    document["clauses"].append(dict(document["clauses"][0]))
    path = tmp_path / "ir.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    code = main(["--ir", str(path), "--fail-on-invalid-ir", "--dry-run", "--quiet"])
    assert code == EXIT_INVALID_IR


def test_ir_from_disk_with_source_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    item = all_fixtures()["eligibility_decision"]
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(item.ir.to_dict()), encoding="utf-8")
    sources = tmp_path / "sources"
    sources.mkdir()
    for document_id, text in item.texts.items():
        (sources / f"{document_id}.txt").write_text(text, encoding="utf-8")
    code = main(
        ["--ir", str(ir_path), "--source-dir", str(sources), "--dry-run", "--compile", "dmn"]
    )
    assert code == EXIT_OK
    assert "1 emitted" in capsys.readouterr().out


def test_missing_source_text_is_warned_about_not_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    item = all_fixtures()["eligibility_decision"]
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(item.ir.to_dict()), encoding="utf-8")
    main(["--ir", str(ir_path), "--dry-run", "--compile", "dmn"])
    output = capsys.readouterr().out
    assert "no canonical text supplied" in output
    assert "0 emitted" in output


def test_source_map_resolves_documents_by_id(tmp_path: Path) -> None:
    item = all_fixtures()["eligibility_decision"]
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(item.ir.to_dict()), encoding="utf-8")
    mapping = {}
    for index, (document_id, text) in enumerate(item.texts.items()):
        target = tmp_path / f"doc{index}.txt"
        target.write_text(text, encoding="utf-8")
        mapping[document_id] = str(target)
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    ir = PolicyIR.from_dict(json.loads(ir_path.read_text(encoding="utf-8")))
    texts, warnings = load_texts(ir, None, map_path)
    assert warnings == []
    assert set(texts) == set(item.texts)


def test_list_fixtures_describes_each_case(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-fixtures"]) == EXIT_OK
    output = capsys.readouterr().out
    assert "eligibility_decision" in output
    assert "retention_obligation" in output


def test_cli_emits_and_applies_semantic_proposals(tmp_path: Path) -> None:
    item = all_fixtures()["notice_process"]
    relation = {
        "relation_id": "rel_cli_governs",
        "source_id": item.ir.entity_types[0].entity_type_id,
        "target_id": item.ir.clauses[0].clause_id,
        "relation_type": "governs",
        "evidence_ids": [item.ir.evidence_spans[0].evidence_id],
    }
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps({"semantic_relations": [relation]}), encoding="utf-8")
    schema = tmp_path / "semantic-proposal.schema.json"
    out = tmp_path / "out"
    code = main(
        [
            "--fixture", "notice_process", "--semantic-proposals", str(proposal),
            "--emit-semantic-proposal-schema", str(schema), "--compile", "graph",
            "--out", str(out), "--quiet",
        ]
    )
    assert code == EXIT_OK
    assert "SemanticRelation" in json.loads(schema.read_text(encoding="utf-8"))["$defs"]
    graph = json.loads((out / "graph-v2.json").read_text(encoding="utf-8"))
    assert [relation["relationship_id"] for relation in graph["relationships"]] == [
        "rel_cli_governs"
    ]


def test_cli_domain_profile_rejects_undeclared_semantic_relation(tmp_path: Path) -> None:
    item = all_fixtures()["notice_process"]
    proposal = tmp_path / "proposal.json"
    proposal.write_text(
        json.dumps(
            {
                "semantic_relations": [
                    {
                        "relation_id": "rel_cli_rejected",
                        "source_id": item.ir.entity_types[0].entity_type_id,
                        "target_id": item.ir.clauses[0].clause_id,
                        "relation_type": "governs",
                        "evidence_ids": [item.ir.evidence_spans[0].evidence_id],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"profile_id": "strict", "version": "1", "relation_types": ["defines"]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main(
            [
                "--fixture", "notice_process", "--semantic-proposals", str(proposal),
                "--domain-profile", str(profile), "--quiet",
            ]
        )


@pytest.mark.skipif(not legacy_graph_paths(), reason="legacy corpora not present")
def test_legacy_graph_import_from_the_cli(capsys: pytest.CaptureFixture[str]) -> None:
    path = legacy_graph_paths()[0]
    code = main(["--legacy-graph", str(path), "--compile", "graph", "--dry-run"])
    assert code == EXIT_OK
    output = capsys.readouterr().out
    assert "no evidence spans" in output
    assert "admitted decisions: 0" in output
