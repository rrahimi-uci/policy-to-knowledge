"""OpenAI runner for the evidence-bounded PolicyIR-to-QueryIR system variant.

This is deliberately a two-stage system.  The first model call can name only
numbered units offered by the application; the application turns those units into
evidence spans and runs the existing evidence gate.  The second call sees only the
resulting graph-eligible PolicyIR clause slice and the benchmark query.  It returns a
tri-valued QueryIR relation, never a benchmark label.  The deterministic evaluator
then produces the benchmark answer and evidence anchors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from extraction.offer import ExtractionRequest, build_request
from extraction.proposals import CandidateProposal, admit_proposals, proposal_from_dict
from ingestion.registry import SourceRegistry
from policy_ir.enums import Effect, Modality, SemanticKind, SemanticRole, Status
from policy_ir.models import PolicyIR
from validation import run_gate

from .benchmarks import BenchmarkCase, BenchmarkError, load_benchmark
from .openai_runner import OpenAIRunnerError, _DEFAULT_BASE_URL, call_openai
from .protocol import (
    OPENAI_DECODING,
    POLICY_IR_EXTRACTION_PROMPT_VERSION,
    POLICY_IR_QUERY_PROMPT_VERSION,
    protocol_record,
    validate_model_and_decoding,
)
from .query_ir import QueryIRError, evaluate_query, query_from_dict, query_schema
from .run_manifest import build_run_manifest_record


POLICY_IR_RUNNER_SCHEMA_VERSION = "p2c-openai-policy-ir-query-v1"
EXTRACTION_MAX_OUTPUT_TOKENS = 4_000
QUERY_MAX_OUTPUT_TOKENS = 400


class PolicyIRRunnerError(ValueError):
    """Raised for malformed model output or a non-reproducible PolicyIR run."""


@dataclass(frozen=True)
class PolicyIRRunnerResult:
    """One public prediction plus safe, aggregate trace information."""

    prediction: Mapping[str, Any]
    trace: Mapping[str, Any]
    error: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(text: str, *, where: str) -> Mapping[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyIRRunnerError(f"{where} is not JSON: {exc.msg}") from exc
    if not isinstance(value, Mapping):
        raise PolicyIRRunnerError(f"{where} must be a JSON object")
    return value


def extraction_schema(request: ExtractionRequest) -> dict[str, Any]:
    """Return a strict, minimal PolicyIR proposal schema for offered unit indices."""
    unit_indices = [unit.index for unit in request.units]
    candidate = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "modality": {"type": "string", "enum": [item.value for item in Modality]},
            # This evidence-slice schema intentionally excludes decision_rule: a
            # decision rule requires typed condition/effect ASTs, which this small
            # source-only request does not permit.  Advertising it would make an
            # otherwise well-evidenced response fail the gate for missing ASTs.
            "semantic_kind": {
                "type": "string",
                "enum": [
                    item.value for item in SemanticKind if item is not SemanticKind.DECISION_RULE
                ],
            },
            "effect": {"type": "string", "enum": [item.value for item in Effect]},
            "display_unit": {"type": "integer", "enum": unit_indices},
            "citations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "role": {"type": "string", "enum": [item.value for item in SemanticRole]},
                        "units": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "integer", "enum": unit_indices},
                        },
                    },
                    "required": ["role", "units"],
                },
            },
        },
        "required": ["modality", "semantic_kind", "effect", "display_unit", "citations"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"candidates": {"type": "array", "items": candidate}},
        "required": ["candidates"],
    }


def render_extraction_prompt(case: BenchmarkCase, request: ExtractionRequest) -> str:
    """Render the label-free source-unit task for the first model call."""
    units = "\n".join(f"[{unit.index}] {unit.text}" for unit in request.units)
    return "\n".join(
        (
            "You are constructing an evidence-bounded PolicyIR slice for one question.",
            "Return only candidate clauses relevant to deciding the question.",
            "Each candidate must cite offered unit indices. Do not use outside knowledge,",
            "invent entities or conditions, or return an answer to the question.",
            "If no offered unit supports a relevant clause, return an empty candidates list.",
            "",
            "QUESTION:",
            case.query,
            "",
            "OFFERED SOURCE UNITS:",
            units,
        )
    )


def render_query_prompt(case: BenchmarkCase, clauses: Sequence[Any]) -> str:
    """Render a QueryIR-only task; raw source text is intentionally absent."""
    records: list[str] = []
    for clause in clauses:
        evidence = ", ".join(
            f"{role}={','.join(ids)}" for role, ids in sorted(clause.evidence.items())
        )
        records.extend(
            (
                f"CLAUSE {clause.clause_id}",
                f"kind={clause.semantic_kind.value}; modality={clause.modality.value}; effect={clause.effect.value}",
                f"text={clause.display_text}",
                f"evidence={evidence}",
            )
        )
    lines = [
        "You are a PolicyIR query adapter.",
        "Use only the admitted PolicyIR clauses below. Do not use outside knowledge.",
        "Return a tri-valued relationship: supported, contradicted, or unknown.",
        "Reference only clause identifiers shown below. Do not return a benchmark answer.",
        "",
        "QUESTION:",
        case.query,
    ]
    if case.benchmark == "sharc":
        lines.extend(
            (
                "",
                "SCENARIO:",
                str(case.context.get("scenario", "")),
                "",
                "HISTORY:",
                json.dumps(case.context.get("history", []), sort_keys=True, ensure_ascii=False),
                "",
                "For ShARC choose yes, no, irrelevant, or follow_up. A follow_up must be necessary to decide.",
            )
        )
    lines.extend(("", "ADMITTED POLICY IR:", "\n".join(records)))
    return "\n".join(lines)


def _parse_candidates(payload: Mapping[str, Any]) -> tuple[CandidateProposal, ...]:
    if set(payload) != {"candidates"} or not isinstance(payload["candidates"], list):
        raise PolicyIRRunnerError("PolicyIR extraction output must contain exactly a candidates list")
    try:
        return tuple(proposal_from_dict(item) for item in payload["candidates"])
    except (TypeError, ValueError) as exc:
        raise PolicyIRRunnerError(f"PolicyIR extraction proposal is invalid: {exc}") from exc


def _case_registry(case: BenchmarkCase) -> tuple[SourceRegistry, ExtractionRequest]:
    registry = SourceRegistry()
    artifact = registry.register_document(
        source_uri=f"benchmark://{case.benchmark}/{case.document_id}/{case.case_id}",
        raw_bytes=case.source_text.encode("utf-8"),
        canonical_text=case.source_text,
        license_record_id=f"external:{case.benchmark}",
    )
    return registry, build_request(registry, registry.chunk_whole_document(artifact.document_id))


def run_policy_ir_case(
    case: BenchmarkCase,
    *,
    model: str,
    api_key_env: str,
    base_url: str,
    timeout_seconds: float,
    temperature: float,
    generate: Callable[..., str] = call_openai,
) -> PolicyIRRunnerResult:
    """Run one case through offered units, graph admission, QueryIR, and evaluation."""
    validate_model_and_decoding(model=model, decoding={"temperature": temperature})
    registry, request = _case_registry(case)
    trace: dict[str, Any] = {
        "case_id": case.case_id,
        "offered_unit_count": request.unit_count,
        "proposed_clause_count": 0,
        "admitted_clause_count": 0,
        "graph_eligible_clause_count": 0,
        "compiler_admitted": False,
        "query_admitted": False,
    }
    try:
        extraction = generate(
            model=model,
            prompt=render_extraction_prompt(case, request),
            api_key_env=api_key_env,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            schema=extraction_schema(request),
            schema_name="policy_ir_evidence_slice",
            max_output_tokens=EXTRACTION_MAX_OUTPUT_TOKENS,
        )
        proposals = _parse_candidates(_load_object(extraction, where="PolicyIR extraction output"))
        trace["proposed_clause_count"] = len(proposals)
        artifact = registry.documents[request.document_id]
        clauses, spans = admit_proposals(
            proposals, request, registry, document_sha256=artifact.source_sha256
        )
        trace["admitted_clause_count"] = len(clauses)
        ir = PolicyIR(
            documents=registry.document_tuple(),
            chunks=registry.chunk_tuple(),
            evidence_spans=spans,
            clauses=clauses,
        )
        gate = run_gate(ir, registry.texts)
        eligible = tuple(
            clause
            for clause in clauses
            if gate.clause_has(clause.clause_id, Status.GRAPH_ELIGIBLE)
        )
        trace["graph_eligible_clause_count"] = len(eligible)
        trace["compiler_admitted"] = bool(eligible)
        if not eligible:
            trace["status"] = "abstained_no_graph_eligible_clause"
            return PolicyIRRunnerResult({"case_id": case.case_id, "answer": None}, trace)
        query_response = generate(
            model=model,
            prompt=render_query_prompt(case, eligible),
            api_key_env=api_key_env,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            schema=query_schema(benchmark=case.benchmark, clause_ids=[item.clause_id for item in eligible]),
            schema_name="policy_ir_query",
            max_output_tokens=QUERY_MAX_OUTPUT_TOKENS,
        )
        query = query_from_dict(
            _load_object(query_response, where="PolicyIR query output"), benchmark=case.benchmark
        )
        prediction = evaluate_query(case=case, query=query, clauses=eligible, spans=spans)
        trace["query_admitted"] = True
        trace["status"] = "answered"
        return PolicyIRRunnerResult(
            {
                "case_id": prediction.case_id,
                "answer": prediction.answer,
                "evidence_ids": list(prediction.evidence_ids),
            },
            trace,
        )
    except (OpenAIRunnerError, PolicyIRRunnerError, QueryIRError, ValueError) as exc:
        trace["status"] = "abstained_error"
        return PolicyIRRunnerResult({"case_id": case.case_id, "answer": None}, trace, str(exc))


def run_policy_ir(
    cases: Sequence[BenchmarkCase],
    **kwargs: Any,
) -> tuple[PolicyIRRunnerResult, ...]:
    """Run all cases independently so one error remains one visible abstention."""
    return tuple(run_policy_ir_case(case, **kwargs) for case in cases)


def configuration_record(
    *,
    benchmark: str,
    source_sha256: str,
    selection: Mapping[str, Any],
    model: str,
    api_key_env: str,
    base_url: str,
    timeout_seconds: float,
    temperature: float,
    implementation_revision: str,
) -> dict[str, Any]:
    """Return a secret-free, protocol-bound PolicyIR run configuration."""
    validate_model_and_decoding(model=model, decoding={"temperature": temperature})
    return {
        "schema_version": POLICY_IR_RUNNER_SCHEMA_VERSION,
        "system": {"kind": "policy_ir", "implementation_revision": implementation_revision},
        "benchmark": {"name": benchmark, "source_sha256": source_sha256, "selection": dict(selection)},
        "api_backend": "openai_responses",
        "model": model,
        "api_key_env": api_key_env,
        "base_url": base_url,
        "store": False,
        "protocol": protocol_record(
            prompt_versions=(POLICY_IR_EXTRACTION_PROMPT_VERSION, POLICY_IR_QUERY_PROMPT_VERSION)
        ),
        "extraction": {"structured_output_schema": "policy_ir_evidence_slice-v1", "max_output_tokens": EXTRACTION_MAX_OUTPUT_TOKENS},
        "query": {"structured_output_schema": "policy_ir_query-v1", "max_output_tokens": QUERY_MAX_OUTPUT_TOKENS},
        "timeout_seconds": timeout_seconds,
    }


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise PolicyIRRunnerError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openai_policy_ir_benchmark",
        description="Run the evidence-bounded PolicyIR-to-QueryIR system over an official split.",
    )
    parser.add_argument("--benchmark", required=True, choices=("sharc", "contract_nli", "opp115"))
    parser.add_argument("--input", required=True, type=Path, metavar="FILE")
    parser.add_argument("--opp115-policy-ids", type=Path, metavar="FILE")
    parser.add_argument("--case-ids", type=Path, metavar="FILE")
    parser.add_argument("--predictions-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--trace-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--config-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--run-manifest-out", required=True, type=Path, metavar="FILE")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--implementation-revision", required=True)
    parser.add_argument("--system-id", default="policy-to-knowledge")
    parser.add_argument("--model", default="gpt-5.2")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write immutable prediction, trace, configuration, and run-manifest artifacts."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.opp115_policy_ids and args.benchmark != "opp115":
        parser.error("--opp115-policy-ids requires --benchmark opp115")
    paths = (args.predictions_out, args.trace_out, args.config_out, args.run_manifest_out)
    if len(set(paths)) != len(paths):
        parser.error("prediction, trace, configuration, and run-manifest outputs must differ")
    try:
        validate_model_and_decoding(model=args.model, decoding={"temperature": args.temperature})
        if any(path.exists() for path in paths):
            existing = next(path for path in paths if path.exists())
            raise PolicyIRRunnerError(f"refusing to overwrite existing file: {existing}")
        dataset = load_benchmark(
            args.benchmark,
            args.input,
            policy_ids_path=args.opp115_policy_ids,
            case_ids_path=args.case_ids,
        )
        results = run_policy_ir(
            dataset.cases,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            temperature=args.temperature,
        )
        _write_new(args.predictions_out, "\n".join(json.dumps(item.prediction, sort_keys=True) for item in results) + "\n")
        _write_new(args.trace_out, "\n".join(json.dumps(item.trace, sort_keys=True) for item in results) + "\n")
        configuration = configuration_record(
            benchmark=dataset.benchmark,
            source_sha256=dataset.source_sha256,
            selection=dataset.selection,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            temperature=args.temperature,
            implementation_revision=args.implementation_revision,
        )
        configuration["run"] = {
            "case_count": len(results),
            "abstentions_from_runner_error": [
                {"case_id": item.prediction["case_id"], "error": item.error}
                for item in results
                if item.error is not None
            ],
            "trace_sha256": _sha256(args.trace_out),
        }
        _write_new(args.config_out, json.dumps(configuration, indent=2, sort_keys=True) + "\n")
        manifest = build_run_manifest_record(
            run_id=args.run_id,
            system_id=args.system_id,
            system_kind="policy_ir",
            implementation_revision=args.implementation_revision,
            configuration_sha256=_sha256(args.config_out),
            benchmark=dataset.benchmark,
            benchmark_source_sha256=dataset.source_sha256,
            selection=dataset.selection,
            predictions_sha256=_sha256(args.predictions_out),
        )
        _write_new(args.run_manifest_out, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return 0
    except (BenchmarkError, PolicyIRRunnerError, OpenAIRunnerError, ValueError) as exc:
        parser.error(f"PolicyIR benchmark error: {exc}")


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
