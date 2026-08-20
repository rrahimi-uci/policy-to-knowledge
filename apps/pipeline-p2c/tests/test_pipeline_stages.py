"""The stage table and the per-stage output contract.

The stage numbering is part of the user-facing layout on disk (``01_ingestion`` and
so on), so it is asserted rather than assumed: a renumbering that silently changed
where artefacts land would be a breaking change to the output directory.
"""

from __future__ import annotations

import json

import pytest

from pipeline.stages import (
    RUNNERS,
    STAGES,
    count_files,
    read_json,
    stage_dir,
    write_json,
)


def test_stage_numbers_are_contiguous_and_start_at_one() -> None:
    assert [number for number, _, _ in STAGES] == list(range(1, len(STAGES) + 1))


def test_stage_names_are_unique() -> None:
    names = [name for _, name, _ in STAGES]
    assert len(set(names)) == len(names)


def test_every_stage_carries_a_description() -> None:
    for _, name, description in STAGES:
        assert description.strip(), f"{name} has no description"


def test_the_semantic_layer_runs_before_any_executable_projection() -> None:
    """The knowledge graph is the canonical IR; DMN and BPMN are projections of it.

    If projection ran first, or the semantic stage were skippable, the architecture
    would have quietly inverted into DMN-first.
    """
    order = {name: number for number, name, _ in STAGES}
    assert order["semantic_assembly"] < order["gate"] < order["projection"]
    assert order["projection"] < order["visualization"]


def test_the_governance_stage_runs_after_the_gate() -> None:
    """The review queue is built from refusals, so it needs the gate's verdict."""
    order = {name: number for number, name, _ in STAGES}
    assert order["governance"] > order["gate"]


def test_every_stage_has_a_registered_runner() -> None:
    """A stage in the table with no runner would produce an empty directory."""
    assert sorted(RUNNERS) == sorted(name for _, name, _ in STAGES)


def test_stage_dir_uses_the_zero_padded_sequence_number(tmp_path) -> None:
    assert stage_dir(tmp_path, "ingestion").name == "01_ingestion"
    assert stage_dir(tmp_path, "visualization").name == "09_visualization"


def test_stage_dir_refuses_an_unknown_stage(tmp_path) -> None:
    with pytest.raises(KeyError):
        stage_dir(tmp_path, "not_a_stage")


def test_stage_dir_is_created_on_demand(tmp_path) -> None:
    path = stage_dir(tmp_path, "gate")
    assert path.is_dir()


def test_write_json_round_trips(tmp_path) -> None:
    target = tmp_path / "nested" / "value.json"
    write_json(target, {"b": 1, "a": [2, 3]})
    assert read_json(target) == {"b": 1, "a": [2, 3]}


def test_write_json_is_stable_across_calls(tmp_path) -> None:
    """Byte-stable output means a re-run produces a reviewable diff, not noise."""
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    payload = {"z": 1, "a": {"y": 2, "b": [3, 4]}}
    write_json(first, payload)
    write_json(second, json.loads(json.dumps(payload)))
    assert first.read_bytes() == second.read_bytes()


def test_count_files_counts_recursively(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.json").write_text("{}")
    (tmp_path / "two.json").write_text("{}")
    assert count_files(tmp_path) == 2


def test_count_files_of_a_missing_directory_is_zero(tmp_path) -> None:
    assert count_files(tmp_path / "absent") == 0


# ---------------------------------------------------------------------------
# Stage 03 durability
#
# The model pass is the only stage that costs money and the only one that takes an hour.
# A run that persisted replies only at the end lost 45 already-paid-for chunks when it
# was interrupted, so both properties below are asserted rather than assumed.
# ---------------------------------------------------------------------------


def _seed_requests(root, chunk_ids):
    """Write the stage-02 artefacts stage 03 reads, without running stages 01–02."""
    from extraction.offer import ExtractionRequest, TextUnit
    from pipeline.stages import stage_dir as _stage_dir

    out = _stage_dir(root, "extraction_requests")
    (out / "requests").mkdir(exist_ok=True)
    index = []
    for chunk_id in chunk_ids:
        request = ExtractionRequest(
            chunk_id=chunk_id, document_id="doc_test", section_path="A1",
            units=(TextUnit(index=1, char_start=0, char_end=11, text="Must verify."),),
        )
        write_json(out / "requests" / f"{chunk_id}.request.json", request.to_dict())
        index.append({"chunk_id": chunk_id, "units": 1})
    write_json(out / "requests-index.json", index)
    return out


def _reply_envelope():
    return {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"candidates": [{"modality": "obligation", "semantic_kind": "decision_rule",
                             "effect": "require_action", "display_unit": 1,
                             "citations": [{"role": "subject", "units": [1]}]}]})}]}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_stage_03_persists_each_reply_as_it_arrives(tmp_path) -> None:
    """An interruption must not discard replies the run already paid for."""
    from pipeline.runner import stage_model_extraction

    chunk_ids = ["chunk_a", "chunk_b", "chunk_c"]
    _seed_requests(tmp_path, chunk_ids)
    seen_on_disk = []

    calls = {"n": 0}

    def transport(body):
        calls["n"] += 1
        if calls["n"] == 3:
            # By the time the third call happens, the first two must already be on disk.
            seen_on_disk.append(
                count_files(stage_dir(tmp_path, "model_extraction") / "proposals")
            )
        return _reply_envelope()

    stage_model_extraction(root=tmp_path, transport=transport, model="m", effort="high",
                           concurrency=1, progress=False)
    assert seen_on_disk and seen_on_disk[0] >= 2
    assert count_files(stage_dir(tmp_path, "model_extraction") / "proposals") == 3


def test_stage_03_resumes_and_does_not_pay_twice(tmp_path) -> None:
    """Re-running after a fix must call only the chunks that still need it."""
    from pipeline.runner import stage_model_extraction

    chunk_ids = ["chunk_a", "chunk_b", "chunk_c"]
    _seed_requests(tmp_path, chunk_ids)
    calls = []

    def transport(body):
        calls.append(1)
        return _reply_envelope()

    stage_model_extraction(root=tmp_path, transport=transport, model="m", effort="high",
                           concurrency=1, progress=False)
    first = len(calls)
    stage_model_extraction(root=tmp_path, transport=transport, model="m", effort="high",
                           concurrency=1, progress=False)
    assert first == 3
    assert len(calls) == 3, "a resumed run called the model again for finished chunks"


def test_stage_03_resume_can_be_turned_off(tmp_path) -> None:
    """Re-running deliberately — after a prompt change — must be possible."""
    from pipeline.runner import stage_model_extraction

    _seed_requests(tmp_path, ["chunk_a"])
    calls = []

    def transport(body):
        calls.append(1)
        return _reply_envelope()

    for _ in range(2):
        stage_model_extraction(root=tmp_path, transport=transport, model="m",
                               effort="high", concurrency=1, progress=False,
                               resume=False)
    assert len(calls) == 2


def test_stage_03_records_a_failure_without_losing_the_other_chunks(tmp_path) -> None:
    from pipeline.runner import stage_model_extraction

    _seed_requests(tmp_path, ["chunk_a", "chunk_b"])

    def transport(body):
        if "chunk_a" in json.dumps(body):
            return {"output": [{"type": "message", "content": [
                {"type": "output_text", "text": '{"candidates": [{"modality": "bogus"}]}'}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}
        return _reply_envelope()

    result = stage_model_extraction(root=tmp_path, transport=transport, model="m",
                                   effort="high", concurrency=1, progress=False)
    assert result.summary["failed_requests"] == 1
    assert result.summary["proposals"] == 1
    failed = read_json(
        stage_dir(tmp_path, "model_extraction") / "proposals" / "chunk_a.proposals.json"
    )
    assert failed["error"]
    assert failed["candidates"] == []


def test_resume_retries_a_stored_failure(tmp_path) -> None:
    """The reason to re-run is that something was fixed, so failures must be retried."""
    from pipeline.runner import stage_model_extraction

    _seed_requests(tmp_path, ["chunk_ok", "chunk_bad"])
    attempts: list[str] = []
    broken = {"still": True}

    def transport(body):
        payload = json.dumps(body)
        chunk = "chunk_bad" if "chunk_bad" in payload else "chunk_ok"
        attempts.append(chunk)
        if chunk == "chunk_bad" and broken["still"]:
            return {"output": [{"type": "message", "content": [{
                "type": "output_text", "text": '{"candidates": [{"modality": "bogus"}]}'}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}
        return _reply_envelope()

    stage_model_extraction(root=tmp_path, transport=transport, model="m", effort="high",
                           concurrency=1, progress=False)
    assert sorted(attempts) == ["chunk_bad", "chunk_ok"]

    # the schema is fixed, and only the failed chunk should be called again
    attempts.clear()
    broken["still"] = False
    result = stage_model_extraction(root=tmp_path, transport=transport, model="m",
                                   effort="high", concurrency=1, progress=False)
    assert attempts == ["chunk_bad"]
    assert result.summary["failed_requests"] == 0
    stored = read_json(
        stage_dir(tmp_path, "model_extraction") / "proposals" / "chunk_bad.proposals.json"
    )
    assert stored["error"] is None
    assert stored["candidates"]


def test_reparse_recovers_a_stored_failure_without_calling_the_model(tmp_path) -> None:
    """Raw replies are kept verbatim precisely so a parsing fix costs nothing.

    Re-calling the model would also change the answer, which makes the fix impossible
    to evaluate.
    """
    from pipeline.runner import stage_model_extraction, stage_reparse_replies

    _seed_requests(tmp_path, ["chunk_a"])
    # A reply the parser refuses only because of a shape it does not yet tolerate.
    stored = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"candidates": [{"modality": "obligation", "semantic_kind": "decision_rule",
                             "effect": "require_action", "display_unit": 1,
                             "citations": {"effect": [1, 1, 1]}}]})}]}],
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    calls = []

    def transport(body):
        calls.append(1)
        return stored

    stage_model_extraction(root=tmp_path, transport=transport, model="m", effort="high",
                           concurrency=1, progress=False)
    assert len(calls) == 1

    result = stage_reparse_replies(root=tmp_path)
    assert result.summary["model_calls"] == 0
    assert len(calls) == 1, "reparse must not call the model"
    assert result.summary["replies_reparsed"] == 1

    stored_proposals = read_json(
        stage_dir(tmp_path, "model_extraction") / "proposals" / "chunk_a.proposals.json"
    )
    assert stored_proposals["error"] is None
    assert stored_proposals["candidates"]


def test_reparse_keeps_a_genuine_failure_failing(tmp_path) -> None:
    """It must never turn a refusal into a silent success."""
    from pipeline.runner import stage_model_extraction, stage_reparse_replies

    _seed_requests(tmp_path, ["chunk_a"])
    bad = {"output": [{"type": "message", "content": [{"type": "output_text",
            "text": '{"candidates": [{"modality": "not-a-modality"}]}'}]}],
           "usage": {"input_tokens": 1, "output_tokens": 1}}
    stage_model_extraction(root=tmp_path, transport=lambda body: bad, model="m",
                           effort="high", concurrency=1, progress=False)
    result = stage_reparse_replies(root=tmp_path)
    assert result.summary["still_failing"] == 1
    assert result.summary["recovered_from_error"] == 0


def test_reparse_without_stored_replies_says_so(tmp_path) -> None:
    from pipeline.runner import stage_reparse_replies

    with pytest.raises(FileNotFoundError, match="no stored replies"):
        stage_reparse_replies(root=tmp_path)


def test_reparse_preserves_the_original_token_accounting(tmp_path) -> None:
    """The call was paid for once; re-parsing must not double-count or zero it."""
    from pipeline.runner import stage_model_extraction, stage_reparse_replies

    _seed_requests(tmp_path, ["chunk_a"])
    stage_model_extraction(root=tmp_path, transport=lambda body: _reply_envelope(),
                           model="m", effort="high", concurrency=1, progress=False)
    before = read_json(stage_dir(tmp_path, "model_extraction") / "proposals"
                       / "chunk_a.proposals.json")["usage"]
    stage_reparse_replies(root=tmp_path)
    after = read_json(stage_dir(tmp_path, "model_extraction") / "proposals"
                      / "chunk_a.proposals.json")["usage"]
    assert after == before


# ---------------------------------------------------------------------------
# The deterministic stages, exercised against a real IR
#
# The stage-table tests above check wiring; these check the runners actually run.
# Stage 05 shipped a wrong attribute name that only a real invocation could catch.
# ---------------------------------------------------------------------------


def _seed_ir(root, fixture):
    """Write the stage-04 artefacts the deterministic tail reads."""
    from pipeline.stages import stage_dir as _stage_dir

    out = _stage_dir(root, "admission")
    write_json(out / "policy-ir.json", fixture.ir.to_dict())
    text_dir = _stage_dir(root, "ingestion") / "canonical-text"
    text_dir.mkdir(parents=True, exist_ok=True)
    for document_id, text in fixture.texts.items():
        (text_dir / f"{document_id}.txt").write_text(text, encoding="utf-8")
    write_json(
        _stage_dir(root, "ingestion") / "documents.json",
        [document.to_dict() for document in fixture.ir.documents],
    )
    return out


def test_stage_semantic_assembly_runs_and_names_its_profile(tmp_path, fixtures) -> None:
    from pipeline.runner import stage_semantic_assembly

    _seed_ir(tmp_path, fixtures["eligibility_decision"])
    result = stage_semantic_assembly(root=tmp_path)
    assert result.number == 5
    assert result.summary["profile"] == "generic"
    assert result.summary["profile_version"]
    assert "clauses_with_no_declared_projection" in result.summary
    assert (stage_dir(tmp_path, "semantic_assembly") / "synthesis-report.json").exists()
    assert (stage_dir(tmp_path, "semantic_assembly") / "domain-profile.json").exists()


def test_a_clause_with_no_declared_intent_is_not_counted_as_a_shortfall(
    tmp_path, fixtures
) -> None:
    """A definition or constraint belongs in the graph and nowhere else."""
    from pipeline.runner import stage_semantic_assembly

    fixture = fixtures["eligibility_decision"]
    _seed_ir(tmp_path, fixture)
    summary = stage_semantic_assembly(root=tmp_path).summary
    accounted = summary["clauses_with_no_declared_projection"]
    assert accounted == len(fixture.ir.clauses) - len(
        {item["clause_id"] for item in
         read_json(stage_dir(tmp_path, "semantic_assembly") / "synthesis-report.json")}
    )


def test_stage_governance_runs_and_queues_every_refusal(tmp_path, fixtures) -> None:
    from pipeline.runner import stage_governance

    _seed_ir(tmp_path, fixtures["eligibility_decision"])
    result = stage_governance(root=tmp_path)
    assert result.number == 7
    assert "review_items" in result.summary
    assert (stage_dir(tmp_path, "governance") / "review-queue.json").exists()
    assert (stage_dir(tmp_path, "governance") / "semantic-metrics.json").exists()


def test_the_deterministic_tail_runs_end_to_end(tmp_path, fixtures) -> None:
    """Stages 05 to 09 in order, against a real IR, writing real files."""
    from pipeline.runner import (
        stage_gate,
        stage_governance,
        stage_projection,
        stage_semantic_assembly,
        stage_visualization,
    )

    _seed_ir(tmp_path, fixtures["eligibility_decision"])
    for runner, kwargs in (
        (stage_semantic_assembly, {}),
        (stage_gate, {}),
        (stage_governance, {}),
        (stage_projection, {"graph_name": "test_corpus"}),
        (stage_visualization, {"title": "Test Corpus"}),
    ):
        result = runner(root=tmp_path, **kwargs)
        assert result.files > 0, result.name

    report = next(stage_dir(tmp_path, "visualization").glob("*.html"))
    html = report.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    # the two stages added in this change must reach the page
    assert "The semantic layer" in html
    assert "Queued for human review" in html


def test_the_run_summary_describes_the_corpus_not_the_last_invocation(tmp_path) -> None:
    """A retry overwrote the summary with its own slice, and the report then said
    "19 of 324 chunks sent" when all 324 had replies."""
    from pipeline.runner import stage_model_extraction

    chunk_ids = ["chunk_a", "chunk_b", "chunk_c"]
    _seed_requests(tmp_path, chunk_ids)
    fail_for = {"chunk_c"}

    def transport(body):
        payload = json.dumps(body)
        if any(chunk in payload for chunk in fail_for):
            return {"output": [{"type": "message", "content": [{
                "type": "output_text", "text": '{"candidates": [{"modality": "bogus"}]}'}]}],
                "usage": {"input_tokens": 5, "output_tokens": 2}}
        return _reply_envelope()

    stage_model_extraction(root=tmp_path, transport=transport, model="m", effort="high",
                           concurrency=1, progress=False)
    fail_for.clear()
    result = stage_model_extraction(root=tmp_path, transport=transport, model="m",
                                   effort="high", concurrency=1, progress=False)

    # the retry called exactly one chunk, but the summary must describe all three
    assert result.summary["this_invocation"]["requests_attempted"] == 1
    summary = read_json(stage_dir(tmp_path, "model_extraction") / "run-summary.json")
    assert summary["requests_attempted"] == 3
    assert summary["requests_available"] == 3
    assert summary["failed_requests"] == 0
    assert summary["proposals"] == 3


def test_corpus_totals_sum_the_tokens_of_every_stored_reply(tmp_path) -> None:
    from pipeline.runner import corpus_totals, stage_model_extraction

    _seed_requests(tmp_path, ["chunk_a", "chunk_b"])
    stage_model_extraction(root=tmp_path, transport=lambda body: _reply_envelope(),
                           model="m", effort="high", concurrency=1, progress=False)
    totals = corpus_totals(tmp_path)
    assert totals["usage"]["calls"] == 2
    assert totals["usage"]["input_tokens"] == 20
    assert totals["usage"]["output_tokens"] == 10
    assert totals["usage"]["total_tokens"] == 30


def test_reparse_refreshes_the_summary_the_report_reads(tmp_path) -> None:
    """Recovering a chunk must update the totals, or the page keeps reporting a failure."""
    from pipeline.runner import stage_model_extraction, stage_reparse_replies

    _seed_requests(tmp_path, ["chunk_a"])
    stored = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"candidates": [{"modality": "obligation", "semantic_kind": "decision_rule",
                             "effect": "require_action", "display_unit": 1,
                             "citations": {"effect": [1, 1]}}]})}]}],
        "usage": {"input_tokens": 3, "output_tokens": 4},
    }
    stage_model_extraction(root=tmp_path, transport=lambda body: stored, model="m",
                           effort="high", concurrency=1, progress=False)
    stage_reparse_replies(root=tmp_path)
    summary = read_json(stage_dir(tmp_path, "model_extraction") / "run-summary.json")
    assert summary["failed_requests"] == 0
    assert summary["proposals"] == 1
