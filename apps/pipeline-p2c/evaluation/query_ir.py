"""Evidence-bounded QueryIR and deterministic tri-valued benchmark projection.

The query adapter may classify the relationship between a benchmark question and
admitted PolicyIR clauses.  It cannot return a benchmark answer directly.  This
module validates the closed relation vocabulary, ensures clause references exist,
and projects that relation to the benchmark's public answer vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from extraction.candidates import CandidateRejected
from policy_ir.models import AtomicPolicyClause, EvidenceSpan

from .benchmarks import BenchmarkCase, BenchmarkPrediction


class QueryIRError(ValueError):
    """Raised when a query relation has unsupported structure or evidence."""


class TruthValue(str, Enum):
    """The only semantic outcomes a query adapter may propose."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class SharcResolution(str, Enum):
    """Public ShARC response forms, constrained by a tri-valued relation."""

    YES = "yes"
    NO = "no"
    IRRELEVANT = "irrelevant"
    FOLLOW_UP = "follow_up"


@dataclass(frozen=True)
class QueryIR:
    """A query relation over admitted PolicyIR clause identifiers.

    ``follow_up`` is only legal for ShARC's ``follow_up`` resolution and remains
    an output string because that corpus evaluates the next question literally.
    """

    truth_value: TruthValue
    clause_ids: tuple[str, ...] = ()
    sharc_resolution: SharcResolution | None = None
    follow_up: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "truth_value": self.truth_value.value,
            "clause_ids": list(self.clause_ids),
        }
        if self.sharc_resolution is not None:
            value["sharc_resolution"] = self.sharc_resolution.value
        if self.follow_up is not None:
            value["follow_up"] = self.follow_up
        return value


def query_schema(*, benchmark: str, clause_ids: Iterable[str]) -> dict[str, Any]:
    """Create a strict structured-output schema over application-derived clause IDs."""
    clause_values = sorted(set(clause_ids))
    base: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "truth_value": {"type": "string", "enum": [value.value for value in TruthValue]},
            "clause_ids": {
                "type": "array",
                "items": {"type": "string", "enum": clause_values},
            },
        },
        "required": ["truth_value", "clause_ids"],
    }
    if benchmark == "sharc":
        base["properties"].update(
            {
                "sharc_resolution": {
                    "type": "string",
                    "enum": [value.value for value in SharcResolution],
                },
                "follow_up": {"type": ["string", "null"]},
            }
        )
        base["required"].extend(("sharc_resolution", "follow_up"))
    return base


def query_from_dict(data: Mapping[str, Any], *, benchmark: str) -> QueryIR:
    """Parse a query proposal and refuse extra fields before any projection."""
    expected = {"truth_value", "clause_ids"}
    if benchmark == "sharc":
        expected.update(("sharc_resolution", "follow_up"))
    if set(data) != expected:
        raise QueryIRError(f"QueryIR must contain exactly {sorted(expected)}")
    try:
        truth_value = TruthValue(data["truth_value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QueryIRError("QueryIR.truth_value is invalid") from exc
    raw_clause_ids = data.get("clause_ids")
    if not isinstance(raw_clause_ids, list) or not all(
        isinstance(item, str) and item for item in raw_clause_ids
    ):
        raise QueryIRError("QueryIR.clause_ids must be a list of non-empty strings")
    if len(set(raw_clause_ids)) != len(raw_clause_ids):
        raise QueryIRError("QueryIR.clause_ids must not repeat a clause")
    if benchmark != "sharc":
        return QueryIR(truth_value=truth_value, clause_ids=tuple(raw_clause_ids))
    try:
        resolution = SharcResolution(data["sharc_resolution"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QueryIRError("QueryIR.sharc_resolution is invalid") from exc
    follow_up = data.get("follow_up")
    if follow_up is not None and (not isinstance(follow_up, str) or not follow_up.strip()):
        raise QueryIRError("QueryIR.follow_up must be a non-empty string or null")
    return QueryIR(
        truth_value=truth_value,
        clause_ids=tuple(raw_clause_ids),
        sharc_resolution=resolution,
        follow_up=follow_up,
    )


def _validate_sharc_relation(query: QueryIR) -> None:
    if query.sharc_resolution is SharcResolution.YES and query.truth_value is not TruthValue.SUPPORTED:
        raise QueryIRError("ShARC yes requires a supported relation")
    if query.sharc_resolution is SharcResolution.NO and query.truth_value is not TruthValue.CONTRADICTED:
        raise QueryIRError("ShARC no requires a contradicted relation")
    if query.sharc_resolution in {SharcResolution.IRRELEVANT, SharcResolution.FOLLOW_UP} and query.truth_value is not TruthValue.UNKNOWN:
        raise QueryIRError("ShARC irrelevant/follow_up requires an unknown relation")
    if query.sharc_resolution is SharcResolution.FOLLOW_UP and query.follow_up is None:
        raise QueryIRError("ShARC follow_up requires QueryIR.follow_up")
    if query.sharc_resolution is not SharcResolution.FOLLOW_UP and query.follow_up is not None:
        raise QueryIRError("only ShARC follow_up may supply QueryIR.follow_up")


def evaluate_query(
    *,
    case: BenchmarkCase,
    query: QueryIR,
    clauses: Iterable[AtomicPolicyClause],
    spans: Iterable[EvidenceSpan],
) -> BenchmarkPrediction:
    """Project a valid relation to a public benchmark answer and source anchors.

    The evaluator never compares with gold annotations.  It only checks that every
    referenced clause was admitted from the offered units, then derives corpus anchor
    identifiers through application-owned character offsets.
    """
    clause_by_id = {clause.clause_id: clause for clause in clauses}
    unknown = sorted(set(query.clause_ids) - set(clause_by_id))
    if unknown:
        raise QueryIRError(f"QueryIR references clauses not admitted by the application: {unknown}")
    if query.truth_value is not TruthValue.UNKNOWN and not query.clause_ids:
        raise QueryIRError("supported or contradicted QueryIR requires admitted clause evidence")
    if case.benchmark == "contract_nli":
        answer = {
            TruthValue.SUPPORTED: "Entailment",
            TruthValue.CONTRADICTED: "Contradiction",
            TruthValue.UNKNOWN: "NotMentioned",
        }[query.truth_value]
    elif case.benchmark == "opp115":
        answer = "Yes" if query.truth_value is TruthValue.SUPPORTED else "No"
    elif case.benchmark == "sharc":
        _validate_sharc_relation(query)
        answer = {
            SharcResolution.YES: "Yes",
            SharcResolution.NO: "No",
            SharcResolution.IRRELEVANT: "Irrelevant",
            SharcResolution.FOLLOW_UP: query.follow_up,
        }[query.sharc_resolution]
        if answer is None:  # pragma: no cover - guarded by _validate_sharc_relation
            raise QueryIRError("ShARC follow_up was not supplied")
    else:  # pragma: no cover - benchmark loaders constrain this vocabulary
        raise QueryIRError(f"unsupported benchmark {case.benchmark!r}")

    span_by_id = {span.evidence_id: span for span in spans}
    selected_span_ids = {
        evidence_id
        for clause_id in query.clause_ids
        for evidence_ids in clause_by_id[clause_id].evidence.values()
        for evidence_id in evidence_ids
    }
    missing_spans = sorted(selected_span_ids - set(span_by_id))
    if missing_spans:
        raise CandidateRejected(f"admitted clause names missing evidence span(s): {missing_spans}")
    anchor_ids = tuple(
        anchor.evidence_id
        for anchor in case.evidence_anchors
        if any(
            max(anchor.start, span_by_id[evidence_id].char_start)
            < min(anchor.end, span_by_id[evidence_id].char_end)
            for evidence_id in selected_span_ids
        )
    )
    return BenchmarkPrediction(case.case_id, str(answer), anchor_ids)
