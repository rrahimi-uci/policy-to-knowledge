"""The pipeline driver's argument handling and stage selection.

Nothing here runs a stage or touches the network; the point is that a mistaken
invocation fails immediately and says why, rather than half-running an expensive
pipeline and leaving the output directory in a state nobody can interpret.
"""

from __future__ import annotations

import pytest

from cli.run_pipeline import (
    STAGE_NAMES,
    build_parser,
    collect_inputs,
    selected_stages,
    stage_kwargs,
)
from pipeline.stages import STAGES


def _args(*argv):
    return build_parser().parse_args(["--output", "outputs", *argv])


def test_stage_names_match_the_stage_table() -> None:
    assert STAGE_NAMES == tuple(name for _, name, _ in STAGES)


def test_the_default_span_is_the_whole_pipeline() -> None:
    assert selected_stages(_args()) == STAGE_NAMES


def test_from_starts_where_asked_and_runs_to_the_end() -> None:
    stages = selected_stages(_args("--from", "gate"))
    assert stages[0] == "gate"
    assert stages[-1] == STAGE_NAMES[-1]


def test_a_span_is_contiguous_and_in_execution_order() -> None:
    """Skipping a stage in the middle would leave a later one reading missing files."""
    stages = selected_stages(_args("--from", "admission", "--to", "projection"))
    order = [STAGE_NAMES.index(name) for name in stages]
    assert order == list(range(order[0], order[-1] + 1))


def test_a_reversed_span_is_refused_before_anything_runs() -> None:
    with pytest.raises(SystemExit, match="comes before"):
        selected_stages(_args("--from", "visualization", "--to", "ingestion"))


def test_only_runs_exactly_one_stage() -> None:
    assert selected_stages(_args("--only", "gate")) == ("gate",)


def test_ingestion_without_an_input_is_refused_with_a_reason() -> None:
    with pytest.raises(SystemExit, match="--input is required"):
        stage_kwargs("ingestion", _args(), "corpus")


def test_the_model_stage_without_a_key_says_what_to_do_instead(monkeypatch) -> None:
    """A missing key must not read as "the model found nothing"."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        stage_kwargs("model_extraction", _args(), "corpus")


def test_the_model_stage_passes_the_model_and_effort_through(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    kwargs = stage_kwargs(
        "model_extraction",
        _args("--model", "gpt-5.2", "--effort", "high", "--concurrency", "9"),
        "corpus",
    )
    assert kwargs["model"] == "gpt-5.2"
    assert kwargs["effort"] == "high"
    assert kwargs["concurrency"] == 9
    assert kwargs["resume"] is True


def test_no_resume_is_passed_through(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    kwargs = stage_kwargs("model_extraction", _args("--no-resume"), "corpus")
    assert kwargs["resume"] is False


def test_a_limit_makes_a_costed_pilot_possible(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    assert stage_kwargs("model_extraction", _args("--limit", "4"), "corpus")["limit"] == 4


def test_the_report_title_is_derived_from_the_corpus_name() -> None:
    assert stage_kwargs("visualization", _args(), "fannie_mae")["title"] == "Fannie Mae"


def test_the_deterministic_stages_need_nothing_but_the_root() -> None:
    for name in ("admission", "gate", "governance"):
        assert set(stage_kwargs(name, _args(), "corpus")) == {"root"}


def test_collect_inputs_is_stable_and_recursive(tmp_path) -> None:
    """Two runs over the same directory must ingest in the same order."""
    (tmp_path / "sub").mkdir()
    for name in ("b.pdf", "a.pdf", "sub/c.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4")
    found = collect_inputs(tmp_path)
    assert [p.name for p in found] == ["a.pdf", "b.pdf", "c.pdf"]
    assert collect_inputs(tmp_path) == found


def test_collect_inputs_accepts_a_single_file(tmp_path) -> None:
    target = tmp_path / "one.pdf"
    target.write_bytes(b"%PDF-1.4")
    assert collect_inputs(target) == (target,)


def test_an_empty_input_directory_is_refused(tmp_path) -> None:
    with pytest.raises(SystemExit, match="no PDFs"):
        collect_inputs(tmp_path)
