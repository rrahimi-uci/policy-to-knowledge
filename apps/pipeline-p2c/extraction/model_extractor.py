"""Calling a model against the extraction contract.

Uses the OpenAI Responses API with Structured Outputs, which is the point: the schema is
enforced while the reply is generated, so the enumerated unit indices become a
constraint rather than a check. A fabricated citation cannot be produced.

Two deliberate choices:

* **No SDK.** The call is one POST, so it goes through :mod:`urllib` and the compiler
  keeps its property of having no third-party runtime dependency outside PDF ingestion.
  Retries, timeouts and usage accounting are explicit rather than inherited.
* **The transport is injectable.** Tests drive a fake transport and never touch the
  network, so the parsing, retry and accounting logic is covered without a key.

Nothing here trusts the reply. It is validated against the schema by the API, parsed
strictly by :mod:`extraction.proposals`, resolved against the request that produced it,
and then put through the gate like any other clause.
"""

from __future__ import annotations

import json
import sys
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from .candidates import CandidateRejected
from .contract import proposal_schema, render_instructions
from .offer import ExtractionRequest
from .proposals import CandidateProposal, proposal_from_dict
from .strict_schema import strip_nulls, to_strict

ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.2"
DEFAULT_EFFORT = "high"
SCHEMA_NAME = "policy_ir_proposals"

SYSTEM_PROMPT = (
    "You extract policy clauses into a typed intermediate representation. Follow the "
    "contract in the user message exactly. Cite only the numbered units you are given. "
    "Never state a value that does not appear in the units you cite. If the units state "
    "no requirement, decision, definition or process step, return an empty candidates "
    "list — that is a correct answer, not a failure."
)


class ModelUnavailable(RuntimeError):
    """Raised when the model cannot be reached or refuses the request outright."""


@dataclass(frozen=True)
class Usage:
    """Token accounting for one or more calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    calls: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.reasoning_tokens + other.reasoning_tokens,
            self.calls + other.calls,
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Usage":
        usage = payload.get("usage") or {}
        details = usage.get("output_tokens_details") or {}
        return cls(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            reasoning_tokens=int(details.get("reasoning_tokens") or 0),
            calls=1,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }


@dataclass
class ChunkReply:
    """What one request produced."""

    chunk_id: str
    proposals: tuple[CandidateProposal, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


#: A transport takes a request body and returns the decoded response payload.
Transport = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def http_transport(
    api_key: str | None = None, *, timeout: float = 600.0, endpoint: str = ENDPOINT
) -> Transport:
    """Build the real transport. Reads ``OPENAI_API_KEY`` unless a key is passed."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ModelUnavailable(
            "no OPENAI_API_KEY in the environment; model extraction needs a key, or "
            "use the deterministic extractor instead"
        )

    def send(body: Mapping[str, Any]) -> Mapping[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    return send


def build_body(
    request: ExtractionRequest, *, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT
) -> dict[str, Any]:
    """The request body for one chunk, schema and contract included."""
    return {
        "model": model,
        "reasoning": {"effort": effort},
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_instructions(request)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": SCHEMA_NAME,
                "strict": True,
                "schema": to_strict(proposal_schema(request)),
            }
        },
    }


def extract_output_text(payload: Mapping[str, Any]) -> str:
    """Pull the structured reply out of a Responses API payload.

    Reasoning models interleave reasoning items with the message, so the message items
    are selected explicitly rather than by position.
    """
    parts: list[str] = []
    for item in payload.get("output") or ():
        if item.get("type") != "message":
            continue
        for content in item.get("content") or ():
            if content.get("type") == "output_text":
                parts.append(content.get("text") or "")
    if not parts:
        status = payload.get("status")
        incomplete = (payload.get("incomplete_details") or {}).get("reason")
        raise ModelUnavailable(
            f"reply carried no output text (status={status!r}, reason={incomplete!r}); "
            "this usually means the output token budget was exhausted by reasoning"
        )
    return "".join(parts)


def parse_reply(payload: Mapping[str, Any]) -> tuple[CandidateProposal, ...]:
    """Parse a payload into proposals, refusing anything outside the contract."""
    document = strip_nulls(json.loads(extract_output_text(payload)))
    if not isinstance(document, dict) or "candidates" not in document:
        raise CandidateRejected("reply has no 'candidates' key")
    return tuple(proposal_from_dict(candidate) for candidate in document["candidates"])


def call_once(
    request: ExtractionRequest,
    transport: Transport,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> ChunkReply:
    """Call the model for one chunk, retrying transport failures.

    A refused *reply* is not retried: the contract was violated, and asking again with
    the same input invites the same violation while spending another call. Transport
    failures — timeouts, 429s, 5xx — are retried with linear backoff.
    """
    body = build_body(request, model=model, effort=effort)
    last_error = ""
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            payload = transport(body)
        except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
            detail = exc.read().decode("utf-8", "replace")[:400]
            last_error = f"HTTP {exc.code}: {detail}"
            if exc.code in (400, 401, 403, 404, 422):
                break  # a bad request will not become good on a retry
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            elapsed = time.monotonic() - started
            usage = Usage.from_payload(payload)
            try:
                proposals = parse_reply(payload)
            except (CandidateRejected, ModelUnavailable, json.JSONDecodeError) as exc:
                return ChunkReply(
                    request.chunk_id, (), payload, usage, str(exc), elapsed
                )
            return ChunkReply(request.chunk_id, proposals, payload, usage, None, elapsed)
        if attempt < attempts:
            sleep(backoff_seconds * attempt)
    return ChunkReply(request.chunk_id, (), {}, Usage(), last_error, 0.0)


@dataclass
class ExtractionRun:
    """The result of calling the model for a batch of requests."""

    replies: tuple[ChunkReply, ...] = ()
    usage: Usage = field(default_factory=Usage)
    elapsed_seconds: float = 0.0

    @property
    def failures(self) -> tuple[ChunkReply, ...]:
        return tuple(reply for reply in self.replies if not reply.ok)

    @property
    def proposal_count(self) -> int:
        return sum(len(reply.proposals) for reply in self.replies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": len(self.replies),
            "failed_requests": len(self.failures),
            "proposals": self.proposal_count,
            "usage": self.usage.to_dict(),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "failures": [
                {"chunk_id": reply.chunk_id, "error": reply.error}
                for reply in self.failures
            ],
        }


def run_extraction(
    requests: Sequence[ExtractionRequest],
    transport: Transport,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    concurrency: int = 6,
    attempts: int = 3,
    on_reply: Callable[[ChunkReply, int, int], None] | None = None,
) -> ExtractionRun:
    """Call the model for every request, concurrently.

    A failed chunk does not abort the run. Coverage and the failure list record it, so a
    partial corpus is reported as partial rather than silently short.
    """
    started = time.monotonic()
    total = len(requests)
    replies: list[ChunkReply | None] = [None] * total

    def work(index: int) -> None:
        replies[index] = call_once(
            requests[index], transport, model=model, effort=effort, attempts=attempts
        )
        if on_reply is not None:
            try:
                on_reply(replies[index], index + 1, total)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001 - reporting is not the work
                # A broken callback must not discard replies the run already paid for,
                # so the reply is kept. It is reported rather than swallowed: the
                # callback is also what persists the reply, and a silent failure there
                # would lose it anyway.
                print(
                    f"  WARNING on_reply failed for {replies[index].chunk_id}: "  # type: ignore[union-attr]
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    if total:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            list(pool.map(work, range(total)))

    finished = tuple(reply for reply in replies if reply is not None)
    usage = Usage()
    for reply in finished:
        usage = usage + reply.usage
    return ExtractionRun(finished, usage, time.monotonic() - started)


def admit_run(
    run: ExtractionRun,
    requests: Iterable[ExtractionRequest],
    registry: Any,
    *,
    documents: Mapping[str, Any],
) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[str, ...]]:
    """Resolve every reply into clauses and spans, collecting refusals.

    Returns clauses, spans and human-readable refusals. A refusal is not an exception:
    one chunk violating the contract must not discard the rest of the corpus.
    """
    from .proposals import admit_proposals

    by_id = {request.chunk_id: request for request in requests}
    clauses: dict[str, Any] = {}
    spans: dict[str, Any] = {}
    refusals: list[str] = []
    for reply in run.replies:
        request = by_id.get(reply.chunk_id)
        if request is None or not reply.proposals:
            continue
        document = documents[request.document_id]
        try:
            chunk_clauses, chunk_spans = admit_proposals(
                reply.proposals,
                request,
                registry,
                document_sha256=document.canonical_text_sha256,
            )
        except CandidateRejected as exc:
            refusals.append(f"{reply.chunk_id}: {exc}")
            continue
        for clause in chunk_clauses:
            clauses.setdefault(clause.clause_id, clause)
        for span in chunk_spans:
            spans.setdefault(span.evidence_id, span)
    return (
        tuple(clauses[key] for key in sorted(clauses)),
        tuple(spans[key] for key in sorted(spans)),
        tuple(refusals),
    )
