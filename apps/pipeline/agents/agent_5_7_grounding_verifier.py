#!/usr/bin/env python3
"""Agent 5.7: independent, claim-level source-grounding certification."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Iterable, Mapping, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.agent_5_6_readiness_remediator import JsonlCheckpoint, _stable_hash
from utils.config import get_config
from utils.kg_readiness import mark_readiness, source_document_index
from utils.llm_client import create_llm_client
from utils.prompt_manager import get_prompt_manager
from utils.rule_contract import validate_rule_v2


VERDICTS = {"supported", "contradicted", "insufficient_evidence"}
MODEL_CLAIM_TYPES = {
    "description", "condition", "outcome", "party", "scope", "exception",
}
# condition_logic and test_vector are excluded on purpose: both are values the
# pipeline DERIVES from a rule's own condition_predicates/outcomes rather than
# facts a policy sentence ever states in those terms. Asking the grounding
# model for a literal source quote for "Conditions combine as {predicate_ref:
# p1}" or a synthesized {inputs -> expected_output} example has no possible
# verbatim answer, so it was scoring near-100% insufficient_evidence on every
# graph regardless of how well-grounded the rule actually was. Both are
# instead verified structurally in deterministic_rule_claims: condition_logic
# against validate_rule_v2's own predicate-coverage check, and test_vector
# against the rule's own declared variables/outcomes. See
# GroundingVerifier._verify_test_vector.


def _normalise_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u00ad", "").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


def _iter_references(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                yield item


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_text_atomic(path: Path, content: str) -> None:
    """Replace an artifact only after its complete content reaches disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def extract_claims(rule: Mapping[str, Any], graph: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Project every executable/source-bearing rule field into atomic claims."""
    claims: list[dict[str, Any]] = []

    def add(claim_id: str, field_path: str, claim_type: str, statement: str, structured: Any) -> None:
        claims.append({
            "claim_id": claim_id,
            "field_path": field_path,
            "claim_type": claim_type,
            "statement": statement,
            "structured": deepcopy(structured),
        })

    rule_name = str(rule.get("rule_name", "")).strip()
    if rule_name:
        add("rule_name", "rule_name", "description", rule_name, rule_name)
    description = str(rule.get("description", "")).strip()
    if description:
        add("description", "description", "description", description, description)

    for index, predicate in enumerate(rule.get("condition_predicates", []) or []):
        if not isinstance(predicate, Mapping):
            continue
        predicate_id = str(predicate.get("predicate_id") or index)
        statement = f"{predicate.get('variable')} {predicate.get('operator')} {_json_value(predicate.get('value'))}"
        add(f"condition:{predicate_id}", f"condition_predicates[{index}]", "condition", statement, predicate)

    if rule.get("condition_logic") is not None:
        add(
            "condition_logic", "condition_logic", "condition_logic",
            f"Conditions combine as {_json_value(rule.get('condition_logic'))}", rule.get("condition_logic"),
        )

    for index, variable in enumerate(rule.get("variables", []) or []):
        if not isinstance(variable, Mapping):
            continue
        add(
            f"variable:{index}", f"variables[{index}]", "variable",
            f"Variable {variable.get('name')} has contract {_json_value(variable)}", variable,
        )

    for index, outcome in enumerate(rule.get("outcomes", []) or []):
        if not isinstance(outcome, Mapping):
            continue
        statement = f"{outcome.get('variable')} {outcome.get('operator')} {_json_value(outcome.get('value'))}"
        add(f"outcome:{index}", f"outcomes[{index}]", "outcome", statement, outcome)

    party = str(rule.get("responsible_party", "")).strip()
    if party:
        add("responsible_party", "responsible_party", "party", f"Responsible party is {party}", party)
    for index, party in enumerate(rule.get("counterparties", []) or []):
        if str(party).strip():
            add(f"counterparty:{index}", f"counterparties[{index}]", "party", f"Counterparty is {party}", party)
    for field in ("entity_type", "source_entity"):
        if str(rule.get(field, "")).strip():
            add(f"entity:{field}", field, "entity_attachment", f"{field} is {rule[field]}", rule[field])
    for index, entity in enumerate(rule.get("related_entities", []) or []):
        if str(entity).strip():
            add(
                f"entity:related:{index}", f"related_entities[{index}]", "entity_attachment",
                f"Rule is attached to entity {entity}", entity,
            )

    scope = rule.get("applicability_scope") or {}
    if isinstance(scope, Mapping):
        for key in ("loan_types", "occupancy_types", "transaction_types"):
            for index, value in enumerate(scope.get(key, []) or []):
                add(f"scope:{key}:{index}", f"applicability_scope.{key}[{index}]", "scope", f"Applies to {key}: {value}", value)
    scope_basis = rule.get("scope_basis")
    if scope_basis in {"explicitly_universal_in_source", "genuinely_unscoped"}:
        add("scope_basis", "scope_basis", "scope", f"Scope basis is {scope_basis}", scope_basis)

    for index, exception in enumerate(rule.get("exceptions", []) or []):
        if not isinstance(exception, Mapping):
            continue
        predicate_id = str(exception.get("predicate_id") or index)
        statement = f"Exception when {exception.get('variable')} {exception.get('operator')} {_json_value(exception.get('value'))}"
        add(f"exception:{predicate_id}", f"exceptions[{index}]", "exception", statement, exception)
    if rule.get("exception_basis") == "explicitly_none_in_source":
        add(
            "exception_basis", "exception_basis", "exception",
            "The complete cited source contains no exception to this rule", "explicitly_none_in_source",
        )

    for field in ("rule_type", "rule_category", "versioning_status"):
        if rule.get(field) is not None:
            add(field, field, "classification", f"{field} is {_json_value(rule[field])}", rule[field])
    if rule.get("recommended_hit_policy") is not None:
        add(
            "recommended_hit_policy", "recommended_hit_policy", "execution",
            f"The derived DMN hit policy is {rule['recommended_hit_policy']}", rule["recommended_hit_policy"],
        )
    if isinstance(rule.get("execution"), Mapping):
        add(
            "execution", "execution", "execution",
            f"The executable DMN/BPMN projection is {_json_value(rule['execution'])}", rule["execution"],
        )

    for index, vector in enumerate(rule.get("test_vectors", []) or []):
        if isinstance(vector, Mapping):
            add(
                f"test_vector:{index}", f"test_vectors[{index}]", "test_vector",
                f"Inputs {_json_value(vector.get('inputs'))} produce {_json_value(vector.get('expected_output'))}", vector,
            )

    return claims


class GroundingResolver(Protocol):
    model: str
    reasoning_effort: str

    def verify(self, packets: list[Mapping[str, Any]]) -> list[dict[str, Any]]: ...


class OpenAIGroundingResolver:
    def __init__(self, api_key: str, model: str, reasoning_effort: str) -> None:
        concurrency = max(1, int(os.getenv("KG_GROUNDING_LLM_CONCURRENCY", "8")))
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = create_llm_client(api_key=api_key, model=model, concurrency=concurrency)
        self.prompts = get_prompt_manager()

    @staticmethod
    def _parse(content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        value = json.loads(content)
        if not isinstance(value, dict) or not isinstance(value.get("verifications"), list):
            raise ValueError("Agent 5.7 response must contain a verifications list")
        return value

    def verify(self, packets: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        prompt = self.prompts.format_prompt(
            "grounding_verification_batch",
            packets_json=json.dumps(packets, ensure_ascii=False),
        )
        attempts = max(1, int(os.getenv("KG_GROUNDING_PARSE_ATTEMPTS", "3")))
        max_tokens = max(2000, int(os.getenv("KG_GROUNDING_MAX_TOKENS", "16000")))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )
                value = self._parse(response.choices[0].message.content or "")
                results = [dict(item) for item in value["verifications"] if isinstance(item, Mapping)]
                expected = Counter(
                    (str(packet["rule_id"]), str(claim["claim_id"]))
                    for packet in packets for claim in packet.get("claims", [])
                )
                returned = Counter((str(item.get("rule_id")), str(item.get("claim_id"))) for item in results)
                if returned != expected:
                    raise ValueError(
                        f"verifier response coverage mismatch: expected {sum(expected.values())}, "
                        f"received {sum(returned.values())}"
                    )
                return results
            except Exception as exc:
                last_error = exc
                prompt += "\n\nReturn complete valid JSON only, with every requested rule_id and claim_id exactly once."
                print(f"⚠️ Agent 5.7 request retry {attempt}/{attempts}: {exc}", flush=True)
        assert last_error is not None
        raise last_error


class GroundingVerifier:
    """Certify claims without modifying their substantive content."""

    CHECKPOINT_VERSION = 3

    def __init__(self, resolver: GroundingResolver | None) -> None:
        self.resolver = resolver

    @staticmethod
    def _chunk_for_path(corpus: Mapping[str, Any], path_value: str) -> Mapping[str, Any] | None:
        wanted = str(path_value or "").replace("\\", "/").lstrip("./")
        if not wanted:
            return None
        exact = [item for item in corpus.get("chunks", []) if str(item.get("chunk_path", "")).replace("\\", "/") == wanted]
        if exact:
            return exact[0]
        suffix = [
            item for item in corpus.get("chunks", [])
            if wanted.endswith(str(item.get("chunk_path", "")).replace("\\", "/"))
            or str(item.get("chunk_path", "")).replace("\\", "/").endswith(wanted)
        ]
        return suffix[0] if len(suffix) == 1 else None

    @classmethod
    def _evidence_records(
        cls,
        rules: Mapping[str, Any] | Iterable[Mapping[str, Any]],
        corpus: Mapping[str, Any],
        max_chars: int,
    ) -> list[dict[str, Any]]:
        candidates: list[Mapping[str, Any]] = []
        source_rules = [rules] if isinstance(rules, Mapping) else list(rules)
        for rule in source_rules:
            candidates.extend(_iter_references(rule.get("source_reference")))
            field_evidence = rule.get("field_evidence")
            if isinstance(field_evidence, Mapping):
                for value in field_evidence.values():
                    candidates.extend(_iter_references(value))
            for parent in (rule.get("exception_verification"), rule.get("scope_derivation")):
                if isinstance(parent, Mapping):
                    candidates.extend(_iter_references(parent.get("evidence")))

        unique: dict[tuple[str, str, str], Mapping[str, Any]] = {}
        for item in candidates:
            key = (
                str(item.get("chunk_path", "")), str(item.get("section_id", "")),
                str(item.get("source_text", item.get("text", ""))),
            )
            if any(key):
                unique[key] = item

        records = []
        used_chars = 0
        for index, ((chunk_path, section_id, quote), _) in enumerate(sorted(unique.items()), 1):
            chunk = cls._chunk_for_path(corpus, chunk_path)
            chunk_text = str((chunk or {}).get("text", ""))
            quote_found = bool(quote and chunk and _normalise_text(quote) in _normalise_text(chunk_text))
            remaining = max(0, max_chars - used_chars)
            context = ""
            if remaining and chunk_text:
                normal_quote = _normalise_text(quote)
                normal_chunk = _normalise_text(chunk_text)
                position = normal_chunk.find(normal_quote) if normal_quote else -1
                # Character offsets in normalized text are approximate but
                # sufficient to center a bounded context window.
                start = max(0, position - remaining // 3) if position >= 0 else 0
                context = chunk_text[start:start + remaining]
                used_chars += len(context)
            records.append({
                "evidence_id": f"E{index}",
                "chunk_path": chunk_path,
                "section_id": section_id,
                "source_text": quote,
                "source_text_found_in_chunk": quote_found,
                "context": context,
            })
        return records

    @classmethod
    def build_packet(
        cls,
        rule: Mapping[str, Any],
        corpus: Mapping[str, Any],
        max_chars: int,
        graph: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        claims = [claim for claim in extract_claims(rule) if claim.get("claim_type") in MODEL_CLAIM_TYPES]

        def provenance(parent: Any, count_field: str) -> dict[str, Any] | None:
            if not isinstance(parent, Mapping):
                return None
            return {
                "status": parent.get("status"),
                count_field: parent.get(count_field),
                "corpus_sha256": parent.get("corpus_sha256"),
                "searched_document_ids": parent.get("searched_document_ids"),
                "unresolved_reason": parent.get("unresolved_reason"),
            }

        return {
            "rule_id": str(rule.get("rule_id", "")),
            "claims": claims,
            "rule_logic": {
                "condition_predicates": rule.get("condition_predicates"),
                "condition_logic": rule.get("condition_logic"),
                "outcomes": rule.get("outcomes"),
                "exceptions": rule.get("exceptions"),
            },
            "search_provenance": {
                "current_corpus_sha256": corpus.get("corpus_sha256"),
                "current_chunk_count": corpus.get("chunk_count"),
                "exception_verification": provenance(rule.get("exception_verification"), "searched_chunk_count"),
                "scope_derivation": provenance(rule.get("scope_derivation"), "reviewed_chunk_count"),
            },
            "evidence": cls._evidence_records(rule, corpus, max_chars),
        }

    @classmethod
    def build_relationship_packets(
        cls,
        graph: Mapping[str, Any],
        corpus: Mapping[str, Any],
        max_chars: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build bounded model packets and deterministic relationship checks."""
        rules = {
            str(rule.get("rule_id")): rule
            for rule in graph.get("business_rules", [])
            if isinstance(rule, Mapping) and rule.get("rule_id")
        }

        def logic(rule_id: str) -> dict[str, Any]:
            rule = rules[rule_id]
            return {
                "rule_id": rule_id,
                "condition_predicates": rule.get("condition_predicates"),
                "condition_logic": rule.get("condition_logic"),
                "outcomes": rule.get("outcomes"),
                "exceptions": rule.get("exceptions"),
                "applicability_scope": rule.get("applicability_scope"),
            }

        def primary_evidence(rule_ids: Iterable[str]) -> list[dict[str, Any]]:
            minimal = [
                {"source_reference": rules[rule_id].get("source_reference")}
                for rule_id in rule_ids if rule_id in rules
            ]
            return cls._evidence_records(minimal, corpus, max_chars)

        packets: list[dict[str, Any]] = []
        deterministic: list[dict[str, Any]] = []
        details = graph.get("dependency_details")
        details = details if isinstance(details, Mapping) else {}
        for index, dependency in enumerate(details.get("dependencies", []) or []):
            if not isinstance(dependency, Mapping):
                continue
            rule_ids = [str(dependency.get("source_rule_id", "")), str(dependency.get("target_rule_id", ""))]
            structured = {**dict(dependency), "affected_rule_ids": rule_ids}
            packets.append({
                "rule_id": f"@dependency:{index}",
                "packet_kind": "graph_relationship",
                "claims": [{
                    "claim_id": "relationship", "field_path": f"dependency_details.dependencies[{index}]",
                    "claim_type": "dependency",
                    "statement": f"Rule {rule_ids[0]} has a {dependency.get('dependency_type')} dependency on rule {rule_ids[1]}",
                    "structured": structured,
                }],
                "rule_logic": {"related_rules": [logic(value) for value in rule_ids if value in rules]},
                "evidence": primary_evidence(rule_ids),
            })

        for index, conflict in enumerate(details.get("conflicts", []) or []):
            if not isinstance(conflict, Mapping):
                continue
            rule_ids = [str(value) for value in conflict.get("rule_ids", []) if str(value) in rules]
            outcome_names = {
                rule_id: {
                    str(item.get("variable"))
                    for item in rules[rule_id].get("outcomes", [])
                    if isinstance(item, Mapping) and item.get("variable")
                }
                for rule_id in rule_ids
            }
            all_disjoint = len(rule_ids) >= 2 and all(
                outcome_names[left].isdisjoint(outcome_names[right])
                for left_index, left in enumerate(rule_ids)
                for right in rule_ids[left_index + 1:]
            )
            anchor_disjoint = len(rule_ids) >= 2 and all(
                outcome_names[rule_ids[0]].isdisjoint(outcome_names[other])
                for other in rule_ids[1:]
            )
            deterministic_disjoint_record = "disjoint outcome variable" in str(
                conflict.get("reasoning", "")
            ).casefold()
            if (
                conflict.get("status") == "non_conflict"
                and deterministic_disjoint_record
                and (all_disjoint or anchor_disjoint)
            ):
                deterministic.append({
                    "relationship_id": f"@conflict:{index}",
                    "field_path": f"dependency_details.conflicts[{index}]",
                    "status": "supported",
                    "affected_rule_ids": rule_ids,
                    "reasoning": "Independent outcome-variable comparison confirms the recorded disjoint-output non-conflict.",
                })
                continue
            structured = {**dict(conflict), "affected_rule_ids": rule_ids}
            packets.append({
                "rule_id": f"@conflict:{index}",
                "packet_kind": "graph_relationship",
                "claims": [{
                    "claim_id": "relationship", "field_path": f"dependency_details.conflicts[{index}]",
                    "claim_type": "conflict",
                    "statement": f"Rules {', '.join(rule_ids)} are classified as {conflict.get('status')}; "
                    f"resolution: {conflict.get('resolution')}",
                    "structured": structured,
                }],
                "rule_logic": {"related_rules": [logic(value) for value in rule_ids]},
                "evidence": primary_evidence(rule_ids),
            })
        return packets, deterministic

    @staticmethod
    def make_batches(
        packets: list[dict[str, Any]],
        max_rules: int,
        max_claims: int,
    ) -> list[list[dict[str, Any]]]:
        # A single unusually rich rule may exceed the claim ceiling. Split its
        # claim list into independently checkpointed fragments while repeating
        # the immutable rule/evidence context.
        fragments: list[dict[str, Any]] = []
        for packet in packets:
            claims = list(packet.get("claims", []))
            if not claims:
                fragments.append(packet)
                continue
            for start in range(0, len(claims), max_claims):
                fragment = dict(packet)
                fragment["claims"] = claims[start:start + max_claims]
                fragments.append(fragment)
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        claim_count = 0
        for packet in fragments:
            packet_claims = len(packet.get("claims", []))
            if current and (len(current) >= max_rules or claim_count + packet_claims > max_claims):
                batches.append(current)
                current, claim_count = [], 0
            current.append(packet)
            claim_count += packet_claims
        if current:
            batches.append(current)
        return batches

    @staticmethod
    def _quote_is_authentic(result: Mapping[str, Any], packet: Mapping[str, Any]) -> bool:
        evidence_id = str(result.get("evidence_id") or "")
        quote = str(result.get("supporting_quote") or "")
        if not evidence_id or not quote:
            return False
        evidence = next((item for item in packet.get("evidence", []) if item.get("evidence_id") == evidence_id), None)
        if not evidence or evidence.get("source_text_found_in_chunk") is not True:
            return False
        haystack = f"{evidence.get('source_text', '')}\n{evidence.get('context', '')}"
        return _normalise_text(quote) in _normalise_text(haystack)

    @classmethod
    def _verdict_has_valid_evidence(
        cls,
        result: Mapping[str, Any],
        claim: Mapping[str, Any],
        packet: Mapping[str, Any],
    ) -> bool:
        if claim.get("claim_type") in {"dependency", "conflict"}:
            return bool(str(result.get("reasoning", "")).strip())
        if claim.get("claim_id") == "exception_basis" and claim.get("structured") == "explicitly_none_in_source":
            provenance = (packet.get("search_provenance") or {}).get("exception_verification") or {}
            return cls._quote_is_authentic(result, packet) or (
                provenance.get("status") == "explicitly_none_in_source"
                and provenance.get("corpus_sha256") == (packet.get("search_provenance") or {}).get("current_corpus_sha256")
                and provenance.get("searched_chunk_count") == (packet.get("search_provenance") or {}).get("current_chunk_count")
            )
        return cls._quote_is_authentic(result, packet)

    @staticmethod
    def _verify_test_vector(claim: Mapping[str, Any], rule: Mapping[str, Any]) -> tuple[str, str]:
        """Check a test vector references only variables/outcomes the rule itself declares.

        This is a referential-integrity check, not an arithmetic one: it does not
        evaluate condition_predicates against the vector's inputs to confirm the
        expected_output actually follows. It catches a test vector that names a
        variable or outcome the rule never declared — a real defect — without
        requiring the vector to be quotable from source prose, which it never is.
        """
        vector = claim.get("structured") if isinstance(claim.get("structured"), Mapping) else {}
        inputs = vector.get("inputs") if isinstance(vector.get("inputs"), Mapping) else {}
        expected = vector.get("expected_output") if isinstance(vector.get("expected_output"), Mapping) else {}
        variable_names = {
            str(v.get("name")) for v in (rule.get("variables") or [])
            if isinstance(v, Mapping) and v.get("name")
        }
        outcome_names = {
            str(o.get("variable")) for o in (rule.get("outcomes") or [])
            if isinstance(o, Mapping) and o.get("variable")
        }
        unknown_inputs = sorted(set(inputs) - variable_names)
        unknown_outputs = sorted(set(expected) - outcome_names)
        if unknown_inputs or unknown_outputs:
            parts = []
            if unknown_inputs:
                parts.append(f"input(s) {unknown_inputs} are not declared in this rule's variables")
            if unknown_outputs:
                parts.append(f"expected_output key(s) {unknown_outputs} match no declared outcome variable")
            return "insufficient_evidence", "; ".join(parts)
        if not inputs and not expected:
            return "insufficient_evidence", "Test vector has no inputs or expected_output to verify."
        return (
            "supported",
            "Test vector inputs and expected_output reference only variables and outcomes "
            "this rule itself declares; verified structurally against the rule's own "
            "contract, not against source prose.",
        )

    @classmethod
    def deterministic_rule_claims(cls, rule: Mapping[str, Any], entity_keys: Iterable[str]) -> list[dict[str, Any]]:
        """Verify derived contract fields structurally after source claims."""
        issues = validate_rule_v2(rule, entity_keys)
        default_reason = "Derived field is internally consistent with the uniform v2 rule contract."
        default_verdict = "supported" if not issues else "insufficient_evidence"
        default_bad_reason = "; ".join(f"{issue.path}: {issue.message}" for issue in issues) or default_reason

        logic_issues = [issue for issue in issues if issue.path == "condition_logic"]
        logic_verdict = "supported" if not logic_issues else "insufficient_evidence"
        logic_reason = (
            "; ".join(f"{issue.path}: {issue.message}" for issue in logic_issues)
            if logic_issues else
            "Condition logic references each declared predicate exactly once; verified "
            "structurally against condition_predicates, not against source prose."
        )

        results = []
        for claim in extract_claims(rule):
            claim_type = claim.get("claim_type")
            if claim_type in MODEL_CLAIM_TYPES:
                continue
            if claim_type == "condition_logic":
                verdict, reason = logic_verdict, logic_reason
            elif claim_type == "test_vector":
                verdict, reason = cls._verify_test_vector(claim, rule)
            else:
                verdict, reason = default_verdict, (default_reason if not issues else default_bad_reason)
            results.append({
                **claim,
                "verdict": verdict,
                "evidence_id": None,
                "supporting_quote": None,
                "reasoning": reason,
            })
        return results

    @classmethod
    def _finalize_rule_results(
        cls,
        packet: Mapping[str, Any],
        raw_results: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        rule_id = str(packet.get("rule_id"))
        returned = {
            str(item.get("claim_id")): item
            for item in raw_results
            if str(item.get("rule_id")) == rule_id and item.get("claim_id")
        }
        finalized = []
        for claim in packet.get("claims", []):
            claim_id = str(claim.get("claim_id"))
            item = dict(returned.get(claim_id, {}))
            verdict = str(item.get("verdict", ""))
            reason = str(item.get("reasoning", "")).strip()
            if verdict not in VERDICTS:
                verdict, reason = "insufficient_evidence", "Verifier omitted this claim or returned an invalid verdict."
            if verdict in {"supported", "contradicted"} and not cls._verdict_has_valid_evidence(item, claim, packet):
                verdict = "insufficient_evidence"
                reason = "Verifier did not provide an authentic quote from a source record present in the corpus."
            finalized.append({
                "claim_id": claim_id,
                "field_path": claim.get("field_path"),
                "claim_type": claim.get("claim_type"),
                "statement": claim.get("statement"),
                "structured": deepcopy(claim.get("structured")),
                "verdict": verdict,
                "evidence_id": item.get("evidence_id"),
                "supporting_quote": item.get("supporting_quote"),
                "reasoning": reason or "No verifier reasoning supplied.",
            })
        return finalized

    @staticmethod
    def _subject_hash(graph: Mapping[str, Any]) -> str:
        subject = deepcopy(dict(graph))
        metadata = subject.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("grounding_certification", None)
        return _stable_hash(subject)

    def verify_graph(
        self,
        graph: Mapping[str, Any],
        organized_dir: Path,
        output_dir: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        working = deepcopy(dict(graph))
        corpus = source_document_index(str(organized_dir))
        rules = [dict(rule) for rule in working.get("business_rules", []) if isinstance(rule, Mapping)]
        workers = max(1, int(os.getenv("KG_GROUNDING_WORKERS", "40")))
        max_rules = max(1, int(os.getenv("KG_GROUNDING_RULES_PER_REQUEST", "4")))
        max_claims = max(1, int(os.getenv("KG_GROUNDING_CLAIMS_PER_REQUEST", "48")))
        max_chars = max(4000, int(os.getenv("KG_GROUNDING_EVIDENCE_CHARS_PER_RULE", "8000")))
        max_relationships = max(1, int(os.getenv("KG_GROUNDING_RELATIONSHIPS_PER_REQUEST", "12")))
        working["business_rules"] = rules
        rule_packets = [self.build_packet(rule, corpus, max_chars) for rule in rules]
        relationship_packets, deterministic_relationships = self.build_relationship_packets(
            working, corpus, max_chars
        )
        packets = rule_packets + relationship_packets
        batches = self.make_batches(rule_packets, max_rules, max_claims)
        batches.extend(self.make_batches(relationship_packets, max_relationships, max_claims))
        checkpoint = JsonlCheckpoint(output_dir / "agent_5_7_grounding_checkpoint.jsonl")
        raw_by_rule: dict[str, list[dict[str, Any]]] = {}
        unexpected_responses: list[dict[str, Any]] = []

        def verify_batch(batch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            key = "grounding:" + _stable_hash({
                "checkpoint_version": self.CHECKPOINT_VERSION,
                "model": getattr(self.resolver, "model", None),
                "reasoning": getattr(self.resolver, "reasoning_effort", None),
                "corpus_sha256": corpus.get("corpus_sha256"),
                "batch": batch,
            })
            cached = checkpoint.get(key)
            if isinstance(cached, list):
                print(f"↪ Agent 5.7 checkpoint hit ({len(batch)} rules)", flush=True)
                return batch, cached
            result = self.resolver.verify(batch) if self.resolver is not None else []
            checkpoint.put(key, result)
            return batch, result

        print(
            f"▶ Agent 5.7 grounding: {len(rules)} rules, {sum(len(p['claims']) for p in packets)} model claims, "
            f"{len(deterministic_relationships)} deterministic relationship checks, "
            f"{len(batches)} batches, {workers} workers",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(batches))), thread_name_prefix="kg-grounding") as executor:
            futures = [executor.submit(verify_batch, batch) for batch in batches]
            for future in as_completed(futures):
                batch, results = future.result()
                batch_pairs = {
                    (str(packet["rule_id"]), str(claim["claim_id"]))
                    for packet in batch for claim in packet.get("claims", [])
                }
                unexpected_responses.extend(
                    {"rule_id": item.get("rule_id"), "claim_id": item.get("claim_id")}
                    for item in results
                    if (str(item.get("rule_id")), str(item.get("claim_id"))) not in batch_pairs
                )
                for packet in batch:
                    rule_id = str(packet["rule_id"])
                    raw_by_rule.setdefault(rule_id, []).extend(
                        dict(item)
                        for item in results
                        if str(item.get("rule_id")) == rule_id
                        and str(item.get("claim_id")) in {
                            str(claim.get("claim_id")) for claim in packet.get("claims", [])
                        }
                    )

        packet_by_id = {str(packet["rule_id"]): packet for packet in packets}
        duplicate_responses = 0
        missing_responses = 0
        returned_responses = 0
        finalized_by_id: dict[str, list[dict[str, Any]]] = {}
        protocol_by_id: dict[str, dict[str, int]] = {}
        for subject_id, packet in packet_by_id.items():
            raw_results = raw_by_rule.get(subject_id, [])
            expected_ids = {str(item["claim_id"]) for item in packet["claims"]}
            returned_ids = [str(item.get("claim_id")) for item in raw_results if str(item.get("claim_id")) in expected_ids]
            returned_unique = set(returned_ids)
            duplicates = len(returned_ids) - len(returned_unique)
            missing = len(expected_ids - returned_unique)
            duplicate_responses += duplicates
            missing_responses += missing
            returned_responses += len(returned_unique)
            finalized_by_id[subject_id] = self._finalize_rule_results(packet, raw_results)
            protocol_by_id[subject_id] = {"returned": len(returned_unique), "missing": missing, "duplicates": duplicates}

        relationship_failures: list[dict[str, Any]] = []
        relationship_failures_by_rule: dict[str, list[str]] = {}
        relationship_results: list[dict[str, Any]] = []
        relationship_invalid_evidence = 0
        for packet in relationship_packets:
            subject_id = str(packet["rule_id"])
            results = finalized_by_id[subject_id]
            protocol = protocol_by_id[subject_id]
            invalid_records = sum(item.get("source_text_found_in_chunk") is not True for item in packet["evidence"])
            relationship_invalid_evidence += invalid_records
            supported_relationship = (
                bool(results)
                and all(item["verdict"] == "supported" for item in results)
                and protocol["missing"] == 0
                and protocol["duplicates"] == 0
            )
            result = {
                "relationship_id": subject_id,
                "field_path": results[0].get("field_path") if results else None,
                "status": "supported" if supported_relationship else "failed",
                "invalid_evidence_records": invalid_records,
                "claims": results,
            }
            relationship_results.append(result)
            if not supported_relationship:
                affected = list((packet["claims"][0].get("structured") or {}).get("affected_rule_ids", []))
                failure = {**result, "affected_rule_ids": affected}
                relationship_failures.append(failure)
                for affected_rule_id in affected:
                    relationship_failures_by_rule.setdefault(str(affected_rule_id), []).append(subject_id)

        failures = []
        rule_results: list[dict[str, Any]] = []
        deterministic_rule_results: list[dict[str, Any]] = []
        entity_keys = (working.get("entity_types") or {}).keys() if isinstance(working.get("entity_types"), Mapping) else []
        for rule in rules:
            rule_id = str(rule.get("rule_id"))
            packet = packet_by_id[rule_id]
            results = finalized_by_id[rule_id]
            deterministic_results = self.deterministic_rule_claims(rule, entity_keys)
            protocol = protocol_by_id[rule_id]
            combined_results = results + deterministic_results
            counts = {verdict: sum(item["verdict"] == verdict for item in combined_results) for verdict in VERDICTS}
            authentic_records = sum(item.get("source_text_found_in_chunk") is True for item in packet["evidence"])
            invalid_records = len(packet["evidence"]) - authentic_records
            failed_relationship_ids = relationship_failures_by_rule.get(rule_id, [])
            certified = (
                bool(combined_results)
                and counts["contradicted"] == 0
                and counts["insufficient_evidence"] == 0
                and invalid_records == 0
                and protocol["missing"] == 0
                and protocol["duplicates"] == 0
                and not failed_relationship_ids
            )
            rule["grounding"] = {
                "status": "certified" if certified else "failed",
                "corpus_sha256": corpus.get("corpus_sha256"),
                "claim_count": len(combined_results),
                "model_claim_count": len(results),
                "deterministic_claim_count": len(deterministic_results),
                "counts": counts,
                "evidence_records": len(packet["evidence"]),
                "invalid_evidence_records": invalid_records,
                "response_claims_returned": protocol["returned"],
                "missing_claim_responses": protocol["missing"],
                "duplicate_claim_responses": protocol["duplicates"],
                "failed_relationship_ids": failed_relationship_ids,
                "claims": results,
                "deterministic_claims": deterministic_results,
            }
            prior_failures = [
                dict(item) for item in (rule.get("readiness") or {}).get("failed_requirements", [])
                if isinstance(item, Mapping) and item.get("requirement") != "grounding"
            ]
            if not certified:
                grounding_failure = {
                    "requirement": "grounding",
                    "reason": (
                        f"{counts['contradicted']} contradicted and {counts['insufficient_evidence']} insufficient claims; "
                        f"{invalid_records} evidence quotes not found in the cited corpus; "
                        f"{protocol['missing']} missing and {protocol['duplicates']} duplicate verifier responses; "
                        f"{len(failed_relationship_ids)} graph relationships failed independent verification"
                    ),
                }
                prior_failures.append(grounding_failure)
                failures.append({
                    "rule_id": rule_id,
                    **grounding_failure,
                    "claims": [item for item in combined_results if item["verdict"] != "supported"],
                })
            reviewed = mark_readiness(rule, prior_failures)
            rule.clear()
            rule.update(reviewed)
            rule_results.extend(results)
            deterministic_rule_results.extend(deterministic_results)

        working["business_rules"] = rules
        model_results = rule_results + [item for result in relationship_results for item in result["claims"]]
        deterministic_results = deterministic_rule_results + [
            {**item, "verdict": item.get("status")} for item in deterministic_relationships
        ]
        total_claims = len(model_results) + len(deterministic_results)
        supported = sum(item["verdict"] == "supported" for item in model_results + deterministic_results)
        contradicted = sum(item["verdict"] == "contradicted" for item in model_results + deterministic_results)
        insufficient = sum(item["verdict"] == "insufficient_evidence" for item in model_results + deterministic_results)
        invalid_evidence = sum((rule.get("grounding") or {}).get("invalid_evidence_records", 0) for rule in rules)
        passed = (
            not failures
            and not relationship_failures
            and total_claims > 0
            and supported == total_claims
            and invalid_evidence == 0
            and not unexpected_responses
            and missing_responses == 0
            and duplicate_responses == 0
        )
        certification = {
            "pass": passed,
            "verifier_model": getattr(self.resolver, "model", None),
            "reasoning_effort": getattr(self.resolver, "reasoning_effort", None),
            "corpus_sha256": corpus.get("corpus_sha256"),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        working.setdefault("metadata", {})["grounding_certification"] = certification
        certification["certified_graph_sha256"] = self._subject_hash(working)
        report = {
            **certification,
            "total_rules": len(rules),
            "rules_certified": len(rules) - len(failures),
            "rules_failed": len(failures),
            "total_claims": total_claims,
            "model_claims": len(model_results),
            "deterministic_claims": len(deterministic_results),
            "rule_claims": len(rule_results) + len(deterministic_rule_results),
            "relationship_claims": len(relationship_results) + len(deterministic_relationships),
            "supported_claims": supported,
            "contradicted_claims": contradicted,
            "insufficient_evidence_claims": insufficient,
            "invalid_evidence_records": invalid_evidence,
            "response_claims_returned": returned_responses,
            "missing_claim_responses": missing_responses,
            "duplicate_claim_responses": duplicate_responses,
            "unexpected_claim_responses": len(unexpected_responses),
            "unexpected_responses": unexpected_responses,
            "claim_coverage_percent": round((returned_responses / max(1, len(model_results))) * 100, 2),
            "failures": failures,
            "relationship_verification": {
                "total_relationships": len(deterministic_relationships) + len(relationship_packets),
                "deterministically_supported": len(deterministic_relationships),
                "model_verified": len(relationship_packets),
                "model_failures": len(relationship_failures),
                "repeated_invalid_evidence_records": relationship_invalid_evidence,
                "deterministic_checks": deterministic_relationships,
                "model_results": relationship_results,
                "failures": relationship_failures,
            },
            "checkpoint_file": str(checkpoint.path),
        }
        return working, report

    @staticmethod
    def report_markdown(report: Mapping[str, Any]) -> str:
        lines = [
            "# Knowledge Graph Grounding Certification", "",
            f"- Overall: {'PASS' if report.get('pass') else 'FAIL'}",
            f"- Rules certified: {report.get('rules_certified')} / {report.get('total_rules')}",
            f"- Claims supported: {report.get('supported_claims')} / {report.get('total_claims')}",
            f"- Contradicted claims: {report.get('contradicted_claims')}",
            f"- Insufficient-evidence claims: {report.get('insufficient_evidence_claims')}",
            f"- Invalid evidence records: {report.get('invalid_evidence_records')}", "",
            f"- Verifier response coverage: {report.get('response_claims_returned')} / {report.get('total_claims')} "
            f"({report.get('claim_coverage_percent')}%)",
            f"- Missing / duplicate / unexpected responses: {report.get('missing_claim_responses')} / "
            f"{report.get('duplicate_claim_responses')} / {report.get('unexpected_claim_responses')}", "",
            f"- Graph relationships checked: {(report.get('relationship_verification') or {}).get('total_relationships')}",
            f"- Deterministic / model relationship checks: "
            f"{(report.get('relationship_verification') or {}).get('deterministically_supported')} / "
            f"{(report.get('relationship_verification') or {}).get('model_verified')}",
            f"- Relationship failures: {(report.get('relationship_verification') or {}).get('model_failures')}", "",
        ]
        if report.get("failures"):
            lines.extend(["## Failed Rules", ""])
            for failure in report["failures"]:
                lines.append(f"- `{failure.get('rule_id')}` — {failure.get('reason')}")
        return "\n".join(lines) + "\n"

    def run(self, graph_path: Path, organized_dir: Path, output_dir: Path) -> dict[str, Any]:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        final_graph, report = self.verify_graph(graph, organized_dir, output_dir)
        _write_text_atomic(graph_path, json.dumps(final_graph, indent=2, ensure_ascii=False) + "\n")
        _write_text_atomic(
            output_dir / "kg_grounding_report.json",
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        )
        _write_text_atomic(output_dir / "kg_grounding_report.md", self.report_markdown(report))
        print(
            f"{'✅' if report['pass'] else '❌'} Agent 5.7 completed: "
            f"{report['rules_certified']}/{report['total_rules']} rules and "
            f"{report['supported_claims']}/{report['total_claims']} claims certified",
            flush=True,
        )
        return report


def certification_issues(
    graph: Mapping[str, Any],
    report: Mapping[str, Any],
    corpus_sha256: str,
) -> list[str]:
    """Return deterministic reasons an Agent 5.7 certificate is not reusable."""
    issues: list[str] = []
    metadata = graph.get("metadata")
    certificate = metadata.get("grounding_certification") if isinstance(metadata, Mapping) else None
    if report.get("pass") is not True:
        issues.append("grounding report does not pass")
    if not isinstance(certificate, Mapping) or certificate.get("pass") is not True:
        issues.append("graph metadata does not contain a passing grounding certificate")
        certificate = {}
    if not str(report.get("verifier_model") or "").strip():
        issues.append("grounding report does not identify the verifier model")
    if report.get("corpus_sha256") != corpus_sha256 or certificate.get("corpus_sha256") != corpus_sha256:
        issues.append("source corpus has changed since grounding verification")
    expected_hash = GroundingVerifier._subject_hash(graph)
    report_hash = report.get("certified_graph_sha256")
    certificate_hash = certificate.get("certified_graph_sha256")
    if report_hash != expected_hash or certificate_hash != expected_hash:
        issues.append("optimized graph has changed since grounding verification")
    rules = [rule for rule in graph.get("business_rules", []) if isinstance(rule, Mapping)]
    failed_rules = []
    for rule in rules:
        grounding = rule.get("grounding")
        if not isinstance(grounding, Mapping) or grounding.get("status") != "certified":
            failed_rules.append(str(rule.get("rule_id", "")))
    if failed_rules:
        issues.append(f"{len(failed_rules)} rules do not have certified claim-level grounding")
    if report.get("total_rules") != len(rules) or report.get("rules_certified") != len(rules):
        issues.append("grounding report rule totals do not match the optimized graph")
    if report.get("claim_coverage_percent") != 100.0:
        issues.append("verifier response coverage is below 100 percent")
    if isinstance(certificate, Mapping):
        for field in ("pass", "verifier_model", "reasoning_effort", "corpus_sha256", "certified_graph_sha256"):
            if certificate.get(field) != report.get(field):
                issues.append(f"graph certificate and grounding report disagree on {field}")
    per_rule_claim_counts = [
        rule["grounding"].get("claim_count")
        for rule in rules
        if isinstance(rule.get("grounding"), Mapping)
    ]
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in per_rule_claim_counts):
        issues.append("one or more rules have an invalid grounding claim count")
    claim_count = sum(value for value in per_rule_claim_counts if isinstance(value, int) and not isinstance(value, bool))
    if report.get("rule_claims") != claim_count:
        issues.append("grounding report claim totals do not match the optimized graph")
    relationship_report = report.get("relationship_verification")
    if not isinstance(relationship_report, Mapping) or relationship_report.get("model_failures") != 0:
        issues.append("one or more graph relationships failed independent verification")
    for field in (
        "contradicted_claims",
        "insufficient_evidence_claims",
        "invalid_evidence_records",
        "missing_claim_responses",
        "duplicate_claim_responses",
        "unexpected_claim_responses",
    ):
        if report.get(field) != 0:
            issues.append(f"grounding report has nonzero {field}")
    return issues


def main() -> None:
    config = get_config()
    resolver = OpenAIGroundingResolver(
        config.get_openai_api_key(), config.get_optimizer_model_name(), config.get_reasoning_effort()
    )
    output_dir = config.get_optimized_dir()
    report = GroundingVerifier(resolver).run(
        output_dir / "optimized_compliance_knowledge_graph.json",
        config.get_organized_dir(),
        output_dir,
    )
    if not report["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
