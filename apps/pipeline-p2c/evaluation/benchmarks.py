"""Open-annotation benchmark adapters and deterministic scoring.

This module deliberately does not download or redistribute benchmark corpora. A
researcher obtains each corpus under its own licence, points the adapter at an
official JSON split, and supplies an independently produced prediction artifact.
The adapter then records input hashes and scores only the labels already supplied
by that corpus. It does not manufacture a knowledge-graph or BPMN gold standard.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .run_manifest import RunManifestError, load_evaluation_run_manifest


SCHEMA_VERSION = "p2c-open-benchmark-v1"

# The ten top-level categories in the OPP-115 annotation scheme. The adapter
# intentionally evaluates these observed categories only; it does not infer a
# new ontology from privacy-policy prose.
OPP115_CATEGORIES = (
    "First Party Collection/Use",
    "Third Party Sharing/Collection",
    "User Choice/Control",
    "User Access, Edit and Deletion",
    "Data Retention",
    "Data Security",
    "Policy Change",
    "Do Not Track",
    "International and Specific Audiences",
    "Other",
)
OPP115_CONSOLIDATION = "threshold-0.5-overlap-similarity"
_HTML_TAG = re.compile(r"<[^>]*>")
_HTML_BREAK = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)


class BenchmarkError(ValueError):
    """Raised when an official split or a prediction artifact is malformed."""


def _normalise(value: str) -> str:
    """Compare outputs without turning a different follow-up question into a match."""
    return " ".join(value.casefold().split())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class EvidenceAnchor:
    """One corpus-provided source anchor, never a generated rationale."""

    evidence_id: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.evidence_id, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class BenchmarkCase:
    """A normalized example from an externally labelled benchmark."""

    benchmark: str
    case_id: str
    document_id: str
    source_text: str
    query: str
    expected_answer: str
    evidence_anchors: tuple[EvidenceAnchor, ...] = ()
    gold_evidence: tuple[EvidenceAnchor, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_task_dict(self) -> dict[str, Any]:
        """Return a system-facing task record without gold labels or evidence."""
        return {
            "benchmark": self.benchmark,
            "case_id": self.case_id,
            "document_id": self.document_id,
            "source_text": self.source_text,
            "query": self.query,
            "evidence_anchors": [item.to_dict() for item in self.evidence_anchors],
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class BenchmarkDataset:
    """Normalized cases plus the digest of the source annotation split."""

    benchmark: str
    source_path: Path
    source_sha256: str
    cases: tuple[BenchmarkCase, ...]
    selection: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkPrediction:
    """A system output aligned to a normalized benchmark case.

    ``answer`` is absent for a deliberate abstention. Evidence IDs must use the
    IDs emitted by ``--emit-cases``; the scorer does not accept free-text
    rationales as evidence.
    """

    case_id: str
    answer: str | None
    evidence_ids: tuple[str, ...] = ()


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchmarkError(f"{where} must be an object")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{where} must be a non-empty string")
    return value


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read {path}: {exc}") from exc


def load_sharc(path: Path) -> BenchmarkDataset:
    """Load an official ShARC split such as ``sharc_dev.json``.

    The task answer may be ``Yes``, ``No``, ``Irrelevant``, or the next required
    follow-up question. We retain the scenario and answered history as context;
    neither is relabelled or interpreted as a graph edge by this adapter.
    """
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise BenchmarkError("ShARC root must be a list")
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        entry = _require_mapping(item, f"ShARC example {index}")
        case_id = _require_string(entry.get("utterance_id"), f"ShARC example {index}.utterance_id")
        if case_id in seen:
            raise BenchmarkError(f"duplicate ShARC utterance_id {case_id!r}")
        seen.add(case_id)
        history = entry.get("history", [])
        if not isinstance(history, list):
            raise BenchmarkError(f"ShARC example {case_id!r}.history must be a list")
        evidence = entry.get("evidence", [])
        if not isinstance(evidence, list):
            raise BenchmarkError(f"ShARC example {case_id!r}.evidence must be a list")
        cases.append(
            BenchmarkCase(
                benchmark="sharc",
                case_id=case_id,
                document_id=_require_string(entry.get("tree_id"), f"ShARC example {case_id!r}.tree_id"),
                source_text=_require_string(entry.get("snippet"), f"ShARC example {case_id!r}.snippet"),
                query=_require_string(entry.get("question"), f"ShARC example {case_id!r}.question"),
                expected_answer=_require_string(entry.get("answer"), f"ShARC example {case_id!r}.answer"),
                context={
                    "scenario": entry.get("scenario", ""),
                    "history": history,
                    "gold_follow_up_evidence": evidence,
                    "source_url": entry.get("source_url", ""),
                },
            )
        )
    return BenchmarkDataset("sharc", path, _sha256(path), tuple(cases))


def load_contract_nli(path: Path) -> BenchmarkDataset:
    """Load an official ContractNLI split (``train.json``, ``dev.json``, or ``test.json``)."""
    raw = _require_mapping(_load_json(path), "ContractNLI root")
    labels = _require_mapping(raw.get("labels"), "ContractNLI labels")
    documents = raw.get("documents")
    if not isinstance(documents, list):
        raise BenchmarkError("ContractNLI documents must be a list")
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for position, item in enumerate(documents):
        document = _require_mapping(item, f"ContractNLI document {position}")
        document_id = str(document.get("id", ""))
        text = _require_string(document.get("text"), f"ContractNLI document {document_id!r}.text")
        raw_spans = document.get("spans")
        if not isinstance(raw_spans, list):
            raise BenchmarkError(f"ContractNLI document {document_id!r}.spans must be a list")
        spans: list[tuple[int, int]] = []
        for span_index, raw_span in enumerate(raw_spans):
            if not isinstance(raw_span, list) or len(raw_span) != 2 or not all(
                isinstance(value, int) for value in raw_span
            ):
                raise BenchmarkError(
                    f"ContractNLI document {document_id!r}.spans[{span_index}] must be [start, end]"
                )
            start, end = raw_span
            if start < 0 or end <= start or end > len(text):
                raise BenchmarkError(
                    f"ContractNLI document {document_id!r}.spans[{span_index}] is out of range"
                )
            spans.append((start, end))
        annotation_sets = document.get("annotation_sets")
        if not isinstance(annotation_sets, list) or len(annotation_sets) != 1:
            raise BenchmarkError(
                f"ContractNLI document {document_id!r} must have exactly one annotation set"
            )
        annotations = _require_mapping(
            _require_mapping(annotation_sets[0], f"ContractNLI document {document_id!r}.annotation_sets[0]").get("annotations"),
            f"ContractNLI document {document_id!r}.annotations",
        )
        for label_id, raw_annotation in sorted(annotations.items()):
            label = _require_mapping(labels.get(label_id), f"ContractNLI label {label_id!r}")
            annotation = _require_mapping(raw_annotation, f"ContractNLI annotation {label_id!r}")
            evidence_indices = annotation.get("spans", [])
            if not isinstance(evidence_indices, list) or not all(
                isinstance(value, int) and 0 <= value < len(spans) for value in evidence_indices
            ):
                raise BenchmarkError(
                    f"ContractNLI annotation {label_id!r}.spans contains an unknown source span"
                )
            case_id = f"{document_id}:{label_id}"
            if case_id in seen:
                raise BenchmarkError(f"duplicate ContractNLI case ID {case_id!r}")
            seen.add(case_id)
            evidence_anchors = tuple(
                EvidenceAnchor(f"span:{span_index}", *span)
                for span_index, span in enumerate(spans)
            )
            cases.append(
                BenchmarkCase(
                    benchmark="contract_nli",
                    case_id=case_id,
                    document_id=document_id,
                    source_text=text,
                    query=_require_string(label.get("hypothesis"), f"ContractNLI label {label_id!r}.hypothesis"),
                    expected_answer=_require_string(annotation.get("choice"), f"ContractNLI annotation {case_id!r}.choice"),
                    evidence_anchors=evidence_anchors,
                    gold_evidence=tuple(
                        evidence_anchors[span_index]
                        for span_index in evidence_indices
                    ),
                    context={
                        "label_id": label_id,
                        "label_description": label.get("short_description", ""),
                        "source_url": document.get("url", ""),
                    },
                )
            )
    return BenchmarkDataset("contract_nli", path, _sha256(path), tuple(cases))


def _directory_sha256(root: Path, paths: Iterable[Path]) -> str:
    """Hash a selected corpus view, including stable relative paths and bytes."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _opp115_segments(path: Path) -> tuple[str, ...]:
    """Read the corpus's literal ``|||`` segments without inventing sentence splits."""
    raw = path.read_text(encoding="utf-8")
    decoded = html.unescape(_HTML_BREAK.sub("\n", raw))
    return tuple(_HTML_TAG.sub("", segment).strip() for segment in decoded.split("|||"))


def _load_policy_ids(path: Path) -> frozenset[str]:
    raw = _load_json(path)
    if not isinstance(raw, list) or not raw or not all(isinstance(value, str) and value for value in raw):
        raise BenchmarkError("OPP-115 policy selection must be a non-empty JSON list of policy file stems")
    values = frozenset(raw)
    if len(values) != len(raw):
        raise BenchmarkError("OPP-115 policy selection contains duplicate policy file stems")
    return values


def load_opp115(path: Path, *, policy_ids_path: Path | None = None) -> BenchmarkDataset:
    """Load OPP-115 consolidated category annotations from an unpacked official corpus.

    Each case asks whether one original policy segment describes one of the ten
    OPP-115 top-level categories. Positive labels come directly from the official
    consolidation view; negatives are the deterministic complement over the fixed
    category set. This adapter evaluates category-level semantic extraction only,
    not unlabelled attributes, a gold knowledge graph, or BPMN.
    """
    consolidation = path / "consolidation" / OPP115_CONSOLIDATION
    policies = path / "sanitized_policies"
    if not consolidation.is_dir() or not policies.is_dir():
        raise BenchmarkError(
            "OPP-115 input must be the unpacked corpus root containing consolidation/"
            f"{OPP115_CONSOLIDATION}/ and sanitized_policies/"
        )
    wanted = _load_policy_ids(policy_ids_path) if policy_ids_path else None
    csv_paths = sorted(consolidation.glob("*.csv"))
    if wanted is not None:
        available = {item.stem for item in csv_paths}
        missing = sorted(wanted - available)
        if missing:
            raise BenchmarkError(f"OPP-115 selection names policies absent from consolidation: {missing[:3]}")
        csv_paths = [item for item in csv_paths if item.stem in wanted]
    if not csv_paths:
        raise BenchmarkError("OPP-115 selection contains no consolidated policy files")

    cases: list[BenchmarkCase] = []
    digested_paths: list[Path] = []
    for csv_path in csv_paths:
        html_path = policies / f"{csv_path.stem}.html"
        if not html_path.is_file():
            raise BenchmarkError(f"OPP-115 policy {csv_path.stem!r} has no sanitized policy text")
        segments = _opp115_segments(html_path)
        categories_by_segment: dict[int, set[str]] = {}
        source_urls: dict[int, set[str]] = {}
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = csv.reader(handle)
                for row_number, row in enumerate(rows, start=1):
                    if len(row) < 8:
                        raise BenchmarkError(f"OPP-115 {csv_path.name}:{row_number} has fewer than 8 columns")
                    try:
                        segment_id = int(row[4])
                    except ValueError as exc:
                        raise BenchmarkError(
                            f"OPP-115 {csv_path.name}:{row_number} has a non-integer segment ID"
                        ) from exc
                    category = row[5]
                    if category not in OPP115_CATEGORIES:
                        raise BenchmarkError(
                            f"OPP-115 {csv_path.name}:{row_number} uses unknown category {category!r}"
                        )
                    if not 0 <= segment_id < len(segments):
                        raise BenchmarkError(
                            f"OPP-115 {csv_path.name}:{row_number} references missing segment {segment_id}"
                        )
                    categories_by_segment.setdefault(segment_id, set()).add(category)
                    if row[7]:
                        source_urls.setdefault(segment_id, set()).add(row[7])
        except OSError as exc:
            raise BenchmarkError(f"cannot read OPP-115 consolidation file {csv_path}: {exc}") from exc
        for segment_id, text in enumerate(segments):
            if not text:
                continue
            positives = categories_by_segment.get(segment_id, set())
            for category in OPP115_CATEGORIES:
                cases.append(
                    BenchmarkCase(
                        benchmark="opp115",
                        case_id=f"{csv_path.stem}:{segment_id}:{OPP115_CATEGORIES.index(category)}",
                        document_id=csv_path.stem,
                        source_text=text,
                        query=f"Does this privacy-policy segment describe the OPP-115 category {category}?",
                        expected_answer="Yes" if category in positives else "No",
                        context={
                            "policy_file": csv_path.stem,
                            "segment_id": segment_id,
                            "category": category,
                            "source_urls": sorted(source_urls.get(segment_id, set())),
                        },
                    )
                )
        digested_paths.extend((csv_path, html_path))
    selection: dict[str, Any] = {
        "consolidation": OPP115_CONSOLIDATION,
        "selected_policy_count": len(csv_paths),
        "policy_ids_sha256": _sha256(policy_ids_path) if policy_ids_path else None,
    }
    return BenchmarkDataset(
        "opp115",
        path,
        _directory_sha256(path, digested_paths),
        tuple(cases),
        selection,
    )


def load_benchmark(
    name: str, path: Path, *, policy_ids_path: Path | None = None
) -> BenchmarkDataset:
    """Load one supported official split without accessing the network."""
    normalised = name.strip().lower().replace("-", "_")
    if normalised == "sharc":
        return load_sharc(path)
    if normalised == "contract_nli":
        return load_contract_nli(path)
    if normalised == "opp115":
        return load_opp115(path, policy_ids_path=policy_ids_path)
    raise BenchmarkError(f"unsupported benchmark {name!r}; choose sharc, contract_nli, or opp115")


def _load_prediction_records(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        records: list[Any] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise BenchmarkError(f"invalid JSONL prediction at line {line_number}: {exc}") from exc
        return records
    if isinstance(decoded, list):
        return decoded
    # A one-line JSONL artifact is also valid JSON. Treating one object as one
    # record makes the documented JSONL form work for single-case smoke tests.
    if isinstance(decoded, Mapping):
        return [decoded]
    raise BenchmarkError("prediction artifact must be a JSON list or JSONL objects")


def load_predictions(path: Path) -> tuple[BenchmarkPrediction, ...]:
    """Load a JSON/JSONL prediction artifact and reject silent duplicate IDs."""
    try:
        records = _load_prediction_records(path)
    except OSError as exc:
        raise BenchmarkError(f"cannot read {path}: {exc}") from exc
    predictions: list[BenchmarkPrediction] = []
    seen: set[str] = set()
    for index, raw in enumerate(records):
        item = _require_mapping(raw, f"prediction {index}")
        case_id = _require_string(item.get("case_id"), f"prediction {index}.case_id")
        if case_id in seen:
            raise BenchmarkError(f"duplicate prediction for case {case_id!r}")
        seen.add(case_id)
        answer = item.get("answer")
        if answer is not None and not isinstance(answer, str):
            raise BenchmarkError(f"prediction {case_id!r}.answer must be a string or null")
        raw_evidence = item.get("evidence_ids", [])
        if not isinstance(raw_evidence, list) or not all(isinstance(value, str) for value in raw_evidence):
            raise BenchmarkError(f"prediction {case_id!r}.evidence_ids must be a list of strings")
        predictions.append(BenchmarkPrediction(case_id, answer, tuple(raw_evidence)))
    return tuple(predictions)


def _safe_divide(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _classification_metrics(expected: Sequence[str], predicted: Sequence[str | None]) -> dict[str, Any]:
    canonical_labels: dict[str, str] = {}
    normalized_expected: list[str] = []
    for label in expected:
        normalized = _normalise(label)
        canonical_labels.setdefault(normalized, label)
        normalized_expected.append(normalized)
    labels = sorted(canonical_labels)
    per_label: dict[str, dict[str, float | int | None]] = {}
    f1_values: list[float] = []
    for label in labels:
        true_positive = sum(want == label and got == label for want, got in zip(normalized_expected, predicted))
        false_positive = sum(want != label and got == label for want, got in zip(normalized_expected, predicted))
        false_negative = sum(want == label and got != label for want, got in zip(normalized_expected, predicted))
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _f1(precision, recall)
        if f1 is not None:
            f1_values.append(f1)
        per_label[canonical_labels[label]] = {
            "support": sum(want == label for want in normalized_expected),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "per_label": per_label,
        "macro_f1": None if not f1_values else sum(f1_values) / len(f1_values),
    }


def evaluate_predictions(
    dataset: BenchmarkDataset,
    predictions: Iterable[BenchmarkPrediction],
    *,
    prediction_sha256: str | None = None,
) -> dict[str, Any]:
    """Score predictions against existing labels, treating omissions as abstentions.

    Predictions for unknown case IDs are errors: accepting them would allow a
    mismatched split to look like a partial, successful run. Evidence metrics are
    micro-averaged exact source-anchor overlap and only apply to cases whose gold
    label provides evidence anchors (currently ContractNLI entailment/contradiction
    examples).
    """
    prediction_items = tuple(predictions)
    by_id = {item.case_id: item for item in prediction_items}
    if len(by_id) != len(prediction_items):
        raise BenchmarkError("prediction sequence contains duplicate case IDs")
    case_ids = {item.case_id for item in dataset.cases}
    unknown = sorted(set(by_id) - case_ids)
    if unknown:
        raise BenchmarkError(f"prediction artifact contains unknown case IDs: {unknown[:3]}")
    expected = [item.expected_answer for item in dataset.cases]
    resolved: list[str | None] = []
    correct = 0
    abstentions = 0
    evidence_tp = evidence_fp = evidence_fn = evidence_cases = 0
    case_results: list[dict[str, Any]] = []
    for item in dataset.cases:
        prediction = by_id.get(item.case_id)
        answer = prediction.answer if prediction else None
        normalized_answer = _normalise(answer) if answer is not None else None
        normalized_expected = _normalise(item.expected_answer)
        is_correct = normalized_answer == normalized_expected if normalized_answer is not None else False
        if answer is None:
            abstentions += 1
        if is_correct:
            correct += 1
        resolved.append(normalized_answer)
        gold_ids = {anchor.evidence_id for anchor in item.gold_evidence}
        predicted_ids = set(prediction.evidence_ids if prediction else ())
        allowed_ids = {anchor.evidence_id for anchor in item.evidence_anchors}
        unsupported_ids = sorted(predicted_ids - allowed_ids)
        if unsupported_ids:
            raise BenchmarkError(
                f"prediction for case {item.case_id!r} cites unknown evidence anchors: {unsupported_ids[:3]}"
            )
        if gold_ids:
            evidence_cases += 1
            evidence_tp += len(gold_ids & predicted_ids)
            evidence_fp += len(predicted_ids - gold_ids)
            evidence_fn += len(gold_ids - predicted_ids)
        case_results.append(
            {
                "case_id": item.case_id,
                "expected_answer": item.expected_answer,
                "predicted_answer": answer,
                "correct": is_correct,
                "abstained": answer is None,
                "gold_evidence_ids": sorted(gold_ids),
                "predicted_evidence_ids": sorted(predicted_ids),
            }
        )
    total = len(dataset.cases)
    answered = total - abstentions
    evidence_precision = _safe_divide(evidence_tp, evidence_tp + evidence_fp)
    evidence_recall = _safe_divide(evidence_tp, evidence_tp + evidence_fn)
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": dataset.benchmark,
        "source": {"path": str(dataset.source_path), "sha256": dataset.source_sha256},
        "selection": dict(dataset.selection),
        "predictions_sha256": prediction_sha256,
        "outcome": {
            "total": total,
            "answered": answered,
            "abstentions": abstentions,
            "coverage": _safe_divide(answered, total),
            "correct": correct,
            "overall_accuracy": _safe_divide(correct, total),
            "answered_accuracy": _safe_divide(correct, answered),
            **_classification_metrics(expected, resolved),
        },
        "evidence": {
            "scored_cases": evidence_cases,
            "true_positives": evidence_tp,
            "false_positives": evidence_fp,
            "false_negatives": evidence_fn,
            "precision": evidence_precision,
            "recall": evidence_recall,
            "f1": _f1(evidence_precision, evidence_recall),
        },
        "case_results": case_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open_benchmark_eval",
        description="Normalize existing benchmark annotations or score system prediction artifacts.",
    )
    parser.add_argument("--benchmark", required=True, choices=("sharc", "contract_nli", "opp115"))
    parser.add_argument("--input", required=True, type=Path, metavar="FILE")
    parser.add_argument(
        "--opp115-policy-ids",
        type=Path,
        metavar="FILE",
        help="With --benchmark opp115: JSON list of policy file stems for a policy-level split.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--emit-cases", type=Path, metavar="FILE")
    action.add_argument("--predictions", type=Path, metavar="FILE")
    parser.add_argument("--out", type=Path, metavar="FILE", help="Required with --predictions.")
    parser.add_argument(
        "--run-manifest",
        type=Path,
        metavar="FILE",
        help="Optional provenance declaration, validated and embedded when scoring predictions.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns 2 for malformed files or invalid option combinations."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.predictions and args.out is None:
        parser.error("--out is required with --predictions")
    if args.opp115_policy_ids and args.benchmark != "opp115":
        parser.error("--opp115-policy-ids requires --benchmark opp115")
    if args.run_manifest and args.emit_cases:
        parser.error("--run-manifest requires --predictions, not --emit-cases")
    try:
        dataset = load_benchmark(args.benchmark, args.input, policy_ids_path=args.opp115_policy_ids)
        if args.emit_cases:
            args.emit_cases.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "benchmark": dataset.benchmark,
                        "source": {"path": str(dataset.source_path), "sha256": dataset.source_sha256},
                        "selection": dict(dataset.selection),
                        "cases": [item.to_task_dict() for item in dataset.cases],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return 0
        predictions = load_predictions(args.predictions)
        predictions_sha256 = _sha256(args.predictions)
        report = evaluate_predictions(dataset, predictions, prediction_sha256=predictions_sha256)
        if args.run_manifest:
            run_manifest = load_evaluation_run_manifest(args.run_manifest)
            run_manifest.validate_for_scoring(
                benchmark=dataset.benchmark,
                source_sha256=dataset.source_sha256,
                selection=dataset.selection,
                predictions_sha256=predictions_sha256,
            )
            report["run_manifest"] = run_manifest.to_report_dict()
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (BenchmarkError, RunManifestError) as exc:
        parser.error(f"benchmark evaluation error: {exc}")


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
