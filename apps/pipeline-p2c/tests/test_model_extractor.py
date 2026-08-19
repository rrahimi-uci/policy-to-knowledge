"""The model extractor, exercised entirely through a fake transport.

No test here touches the network. The transport is a parameter precisely so the retry
policy, the refusal path, the token accounting and the reply parsing can all be tested
deterministically and offline.
"""

from __future__ import annotations

import json

import pytest

from extraction.model_extractor import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    ModelUnavailable,
    Usage,
    build_body,
    call_once,
    extract_output_text,
    parse_reply,
    run_extraction,
)


def _envelope(payload: dict, *, input_tokens: int = 100, output_tokens: int = 50,
              reasoning_tokens: int = 20) -> dict:
    """A response shaped the way the Responses API returns one."""
    return {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message",
             "content": [{"type": "output_text", "text": json.dumps(payload)}]},
        ],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def _empty() -> dict:
    return _envelope({"candidates": []})


def _one_clause(unit: int = 1) -> dict:
    return _envelope({"candidates": [{
        "modality": "obligation",
        "semantic_kind": "decision_rule",
        "effect": "require_action",
        "display_unit": unit,
        "citations": [{"role": "subject", "units": [unit]},
                      {"role": "effect", "units": [unit]}],
    }]})


# ------------------------------------------------------------------- request body


def test_body_requests_strict_structured_output(sample_request) -> None:
    body = build_body(sample_request, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT)
    assert body["model"] == DEFAULT_MODEL
    assert body["reasoning"]["effort"] == DEFAULT_EFFORT
    text_format = body["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"]["additionalProperties"] is False


def test_body_carries_every_numbered_unit(sample_request) -> None:
    body = build_body(sample_request, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT)
    prompt = json.dumps(body["input"])
    for unit in sample_request.units:
        assert f"[{unit.index}]" in prompt
        assert unit.text in prompt


def test_the_schema_admits_only_this_chunks_unit_indexes(sample_request) -> None:
    """A citation to a unit that is not in the request is unexpressible, not refused.

    This is the mechanism that makes a fabricated citation impossible rather than
    merely detected after the fact.
    """
    body = build_body(sample_request, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT)
    indexes = [unit.index for unit in sample_request.units]

    def unit_enums(node):
        if isinstance(node, dict):
            if node.get("type") == "integer" and "enum" in node:
                yield node["enum"]
            for value in node.values():
                yield from unit_enums(value)
        elif isinstance(node, list):
            for item in node:
                yield from unit_enums(item)

    found = list(unit_enums(body["text"]["format"]["schema"]))
    assert found, "no unit-index enum in the schema"
    for enum in found:
        assert enum == indexes


def test_body_never_sends_character_offsets(sample_request) -> None:
    """The model addresses units by index; offsets are resolved locally afterwards."""
    body = build_body(sample_request, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT)
    prompt = json.dumps(body["input"])
    for unit in sample_request.units:
        assert str(unit.char_start) not in prompt


# ------------------------------------------------------------------ reply parsing


def test_extract_output_text_selects_the_message_not_the_reasoning() -> None:
    payload = {"output": [
        {"type": "reasoning", "content": [{"type": "output_text", "text": "thinking"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "answer"}]},
    ]}
    assert extract_output_text(payload) == "answer"


def test_parse_reply_accepts_an_empty_candidate_list() -> None:
    """An empty list is a correct answer for a chunk that states no requirement."""
    assert parse_reply(_empty()) == ()


def test_parse_reply_reads_one_clause() -> None:
    proposals = parse_reply(_one_clause())
    assert len(proposals) == 1
    assert proposals[0].modality.value == "obligation"
    assert proposals[0].cited_units() == (1,)


def test_parse_reply_rejects_a_body_that_is_not_json() -> None:
    payload = {"output": [{"type": "message",
                           "content": [{"type": "output_text", "text": "not json"}]}]}
    with pytest.raises(Exception):
        parse_reply(payload)


def test_parse_reply_rejects_a_reply_without_candidates() -> None:
    with pytest.raises(Exception, match="candidates"):
        parse_reply(_envelope({"clauses": []}))


def test_parse_reply_drops_the_null_placeholders_strict_mode_forces() -> None:
    """Strict mode makes the model emit every key; nulls must read as absent."""
    payload = _envelope({"candidates": [{
        "modality": "obligation", "semantic_kind": "decision_rule",
        "effect": "require_action", "display_unit": 1,
        "citations": [{"role": "subject", "units": [1]}],
        "subject_ref": None, "action": None, "condition_ast": None,
        "scope": None, "missing": None,
    }]})
    proposals = parse_reply(payload)
    assert proposals[0].subject_ref is None
    assert proposals[0].missing == ()


# ----------------------------------------------------------------- retry policy


def test_call_once_retries_a_transport_failure(sample_request) -> None:
    calls = {"n": 0}

    def flaky(body):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ModelUnavailable("connection reset")
        return _empty()

    reply = call_once(sample_request, flaky, attempts=3, backoff_seconds=0.0,
                      sleep=lambda seconds: None)
    assert calls["n"] == 3
    assert reply.error is None
    assert reply.ok


def test_call_once_reports_the_last_error_when_attempts_run_out(sample_request) -> None:
    def always_fails(body):
        raise ModelUnavailable("gateway timeout")

    reply = call_once(sample_request, always_fails, attempts=2, backoff_seconds=0.0,
                      sleep=lambda seconds: None)
    assert reply.error is not None
    assert "gateway timeout" in reply.error
    assert reply.proposals == ()


def test_a_rejected_reply_is_not_retried(sample_request) -> None:
    """Asking again with the same input invites the same violation and spends a call."""
    calls = {"n": 0}

    def malformed(body):
        calls["n"] += 1
        return _envelope({"candidates": [{"modality": "obligation"}]})

    reply = call_once(sample_request, malformed, attempts=4, backoff_seconds=0.0,
                      sleep=lambda seconds: None)
    assert calls["n"] == 1
    assert reply.error is not None


def test_a_rejected_reply_still_reports_the_tokens_it_cost(sample_request) -> None:
    """A refusal is not free; the accounting must not lose it."""
    reply = call_once(
        sample_request,
        lambda body: _envelope({"candidates": [{"modality": "nonsense"}]},
                               input_tokens=300, output_tokens=90),
        attempts=1, sleep=lambda seconds: None,
    )
    assert reply.error is not None
    assert reply.usage.input_tokens == 300
    assert reply.usage.output_tokens == 90


# ------------------------------------------------------------------- accounting


def test_usage_adds_and_tolerates_a_missing_reasoning_detail() -> None:
    a = Usage.from_payload({"usage": {"input_tokens": 10, "output_tokens": 5,
                                      "output_tokens_details": {"reasoning_tokens": 3}}})
    b = Usage.from_payload({"usage": {"input_tokens": 7, "output_tokens": 2}})
    total = a + b
    assert (total.input_tokens, total.output_tokens) == (17, 7)
    assert total.reasoning_tokens == 3
    assert total.calls == 2


# --------------------------------------------------------------------- the run


def test_run_extraction_returns_one_reply_per_request(sample_requests) -> None:
    run = run_extraction(sample_requests, lambda body: _empty(), concurrency=2, attempts=1)
    assert len(run.replies) == len(sample_requests)
    assert run.usage.calls == len(sample_requests)
    assert run.failures == ()


def test_run_extraction_preserves_request_order(sample_requests) -> None:
    """Replies are indexed by request, not by completion time."""
    run = run_extraction(sample_requests, lambda body: _empty(), concurrency=3, attempts=1)
    assert [r.chunk_id for r in run.replies] == [r.chunk_id for r in sample_requests]


def test_run_extraction_isolates_a_failing_chunk(sample_requests) -> None:
    """One chunk failing must not lose the others."""
    target = sample_requests[0].chunk_id

    def selective(body):
        if target in json.dumps(body):
            raise ModelUnavailable("boom")
        return _one_clause()

    run = run_extraction(sample_requests, selective, concurrency=2, attempts=1)
    assert len(run.replies) == len(sample_requests)
    assert len(run.failures) == 1
    assert run.failures[0].chunk_id == target
    assert run.proposal_count == len(sample_requests) - 1


def test_run_extraction_reports_progress_per_reply(sample_requests) -> None:
    seen: list[tuple[str, int, int]] = []
    run_extraction(sample_requests, lambda body: _empty(), concurrency=1, attempts=1,
                   on_reply=lambda reply, done, total: seen.append(
                       (reply.chunk_id, done, total)))
    assert len(seen) == len(sample_requests)
    assert [entry[1] for entry in seen] == [1, 2, 3]
    assert {entry[2] for entry in seen} == {len(sample_requests)}


def test_run_extraction_handles_an_empty_batch() -> None:
    run = run_extraction((), lambda body: _empty())
    assert run.replies == ()
    assert run.usage.calls == 0


def test_the_run_summary_omits_the_raw_payloads(sample_requests) -> None:
    """The summary is written to disk next to the replies; it must stay small."""
    run = run_extraction(sample_requests, lambda body: _one_clause(), attempts=1)
    as_dict = run.to_dict()
    assert as_dict["requests"] == len(sample_requests)
    assert as_dict["proposals"] == len(sample_requests)
    assert as_dict["failed_requests"] == 0
    assert "output_text" not in json.dumps(as_dict)


def test_a_broken_progress_callback_does_not_discard_the_run(sample_requests) -> None:
    """Reporting is not the work. A callback that raises loses its notification only.

    Learned the hard way: a progress lambda with the wrong arity aborted a live run
    and threw away replies that had already been paid for.
    """
    def broken(reply):  # wrong arity on purpose
        raise TypeError("takes 1 positional argument but 3 were given")

    run = run_extraction(sample_requests, lambda body: _one_clause(), attempts=1,
                         on_reply=broken)
    assert len(run.replies) == len(sample_requests)
    assert run.proposal_count == len(sample_requests)
    assert run.failures == ()
