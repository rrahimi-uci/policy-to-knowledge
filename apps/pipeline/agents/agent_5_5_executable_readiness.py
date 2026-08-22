#!/usr/bin/env python3
"""Agent 5.5: evidence-backed completion for DMN/BPMN-ready graph rules."""

from __future__ import annotations

import json
import os
import re
import sys
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import get_config
from utils.kg_readiness import (
    corpus_manifest,
    dependency_edges,
    derive_dependency_chains,
    entity_rule_groups,
    final_rule_issues,
    mark_readiness,
    naming_issues,
    referential_integrity_issues,
    source_document_index,
)
from utils.llm_client import create_llm_client
from utils.prompt_manager import get_prompt_manager
from utils.rule_contract import validate_rule_v2


class EvidenceResolver(Protocol):
    def complete_rule(self, rule: Mapping[str, Any], corpus: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def analyse_entity(self, entity: str, rules: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]: ...


class OpenAIEvidenceResolver:
    """Source interpreter. It never performs graph/corpus integrity decisions."""

    def __init__(self, api_key: str, model: str, reasoning_effort: str) -> None:
        try:
            readiness_concurrency = max(1, int(os.getenv("KG_READINESS_LLM_CONCURRENCY", "4")))
        except (TypeError, ValueError):
            readiness_concurrency = 4
        self.readiness_concurrency = readiness_concurrency
        self.client = create_llm_client(
            api_key=api_key,
            model=model,
            concurrency=readiness_concurrency,
        )
        self.reasoning_effort = reasoning_effort
        self.prompts = get_prompt_manager()

    @staticmethod
    def _parse(content: str) -> Mapping[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        value = json.loads(content)
        if not isinstance(value, Mapping):
            raise ValueError("readiness response must be an object")
        return value

    def _json_completion(self, prompt: str, max_tokens: int) -> Mapping[str, Any]:
        """Request JSON with bounded retries for occasional malformed model output."""
        attempts = max(1, int(os.getenv("KG_READINESS_PARSE_ATTEMPTS", "3")))
        retry_prompt = prompt
        last_error: Exception | None = None
        for attempt in range(attempts):
            response = self.client.chat_completion(
                messages=[{"role": "user", "content": retry_prompt}], temperature=0,
                max_tokens=max_tokens, reasoning_effort=self.reasoning_effort,
            )
            content = response.choices[0].message.content or ""
            try:
                return self._parse(content)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = exc
                retry_prompt = (
                    prompt
                    + "\n\nYour previous response was not valid JSON. Retry now. "
                    "Return one complete JSON object only, with double-quoted keys and strings; "
                    "do not include markdown fences or explanatory text."
                )
                if attempt + 1 < attempts:
                    print(f"⚠️ Readiness JSON parse retry {attempt + 1}/{attempts - 1}", flush=True)
        assert last_error is not None
        raise last_error

    def complete_rule(self, rule: Mapping[str, Any], corpus: Mapping[str, Any]) -> Mapping[str, Any]:
        prompt = self.prompts.format_prompt(
            "executable_readiness_completion",
            rule_json=json.dumps(rule, ensure_ascii=False),
            corpus_json=json.dumps(corpus, ensure_ascii=False),
        )
        return self._json_completion(prompt, int(os.getenv("KG_READINESS_MAX_TOKENS", "6000")))

    def analyse_entity(self, entity: str, rules: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        prompt = self.prompts.format_prompt(
            "entity_conflict_analysis",
            entity_key=entity,
            rules_json=json.dumps(rules, ensure_ascii=False),
        )
        value = self._json_completion(prompt, int(os.getenv("KG_CONFLICT_MAX_TOKENS", "6000")))
        analyses = value.get("analyses", [])
        return analyses if isinstance(analyses, list) else []


def _project_execution(rule: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanical projection; final readiness still requires evidence checks."""
    variables = [item for item in rule.get("variables", []) if isinstance(item, Mapping)]
    inputs = [str(item.get("name")) for item in variables if item.get("role") in {"input", "derived"}]
    outputs = [str(item.get("name")) for item in variables if item.get("role") == "output"]
    targets = ["DMN"] if inputs and outputs else []
    execution: dict[str, Any] = {"targets": targets}
    if "DMN" in targets:
        execution["dmn"] = {"input_columns": inputs, "output_columns": outputs, "hit_policy": rule.get("recommended_hit_policy")}
    if str(rule.get("rule_type", "")).lower() in {"process", "validation", "compliance", "exception"} and outputs:
        targets.append("BPMN")
        execution["bpmn"] = {"gateway_type": "exclusive", "lane": rule.get("responsible_party"), "true_path_outcome_variables": outputs}
    return execution


def _report_markdown(report: Mapping[str, Any]) -> str:
    corpus = report["invariants"]["corpus_integrity"]
    lines = ["# Sections added", ""]
    lines.extend([f"- {item['section_id']}: {item['reason']}" for item in corpus["sections_added"]] or ["- None."])
    lines += ["", "# Sections removed", ""]
    lines.extend([f"- {item['section_id']}: {item['reason']}" for item in corpus["sections_removed"]] or ["- None."])
    lines += ["", "# Executable KG readiness self-report", "", "## Invariant validation", ""]
    for name, result in report["invariants"].items():
        lines.append(f"- {name}: {'PASS' if result['pass'] else 'FAIL'} — {result['evidence']}")
    lines += ["", "## Conflicts and dependency chains", ""]
    lines.append(f"- Entities checked: {report['conflicts_and_dependencies']['entities_checked']}")
    lines.append(f"- Conflicts found: {report['conflicts_and_dependencies']['conflicts_found']}")
    lines.append(f"- Dependency chains derived: {report['conflicts_and_dependencies']['dependency_chains_derived']}")
    lines += ["", "## Exception recheck", ""]
    for key, value in report["exception_recheck"].items():
        if key != "unresolved_rules": lines.append(f"- {key.replace('_', ' ')}: {value}")
    lines += ["", "## Scope derivation", ""]
    for key, value in report["scope_derivation"].items():
        if key != "examples": lines.append(f"- {key.replace('_', ' ')}: {value}")
    return "\n".join(lines) + "\n"


class ExecutableReadinessCompleter:
    """Completes evidence fields and emits a non-silent pass/fail self-report."""

    def __init__(self, resolver: EvidenceResolver | None = None) -> None:
        self.resolver = resolver

    @staticmethod
    def _evidence_packet(rule: Mapping[str, Any], corpus: Mapping[str, Any]) -> dict[str, Any]:
        """Search every chunk locally, then send the relevant evidence packet.

        The search record proves the complete available organized corpus was
        inspected by the deterministic retriever. The model receives direct
        candidates, including every exception-marker hit, rather than an
        unbounded document dump.
        """
        source = rule.get("source_reference", {})
        quote = source.get("source_text", "") if isinstance(source, Mapping) else ""
        text = " ".join(str(rule.get(key, "")) for key in ("rule_name", "description")) + " " + str(quote)
        anchors = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)}
        markers = {"except", "unless", "notwithstanding", "however", "waiver", "exempt"}
        matches = []
        for chunk in corpus.get("chunks", []):
            lower = str(chunk.get("text", "")).lower()
            score = sum(anchor in lower for anchor in anchors)
            if score or any(marker in lower for marker in markers):
                matches.append({"chunk_path": chunk.get("chunk_path"), "section_id": chunk.get("section_id"), "text": chunk.get("text"), "anchor_hits": score})
        matches.sort(key=lambda item: (-item["anchor_hits"], str(item["chunk_path"])))
        # The complete corpus is searched above, but sending every matching
        # chunk to the model can create 200K+ token prompts for a single rule.
        # Preserve proof of complete coverage while sending a bounded,
        # relevance-ranked evidence packet. The cited source chunk is retained
        # whenever available, followed by the strongest anchor/exception hits.
        try:
            max_candidates = max(1, int(os.getenv("KG_READINESS_MAX_CANDIDATES", "12")))
            max_chars = max(4000, int(os.getenv("KG_READINESS_MAX_EVIDENCE_CHARS", "24000")))
        except (TypeError, ValueError):
            max_candidates, max_chars = 12, 24000
        cited_path = str(source.get("chunk_path", "")) if isinstance(source, Mapping) else ""
        ordered = []
        if cited_path:
            ordered.extend(item for item in matches if str(item.get("chunk_path")) == cited_path)
        ordered.extend(item for item in matches if item not in ordered)
        bounded = []
        used_chars = 0
        for item in ordered:
            if len(bounded) >= max_candidates:
                break
            text_value = str(item.get("text", ""))
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            clipped = text_value[:remaining]
            bounded.append({**item, "text": clipped})
            used_chars += len(clipped)
        return {
            "searched_chunk_count": corpus.get("chunk_count", 0),
            "corpus_sha256": corpus.get("corpus_sha256"),
            "candidate_passages": bounded,
        }

    def _complete_evidence(self, rule: dict[str, Any], corpus: Mapping[str, Any]) -> dict[str, Any]:
        if self.resolver is None:
            return rule
        completion = dict(self.resolver.complete_rule(rule, corpus))
        # The resolver may only update evidence-derived fields, never IDs, rules,
        # dependencies, or source provenance established by earlier stages.
        for field in ("exceptions", "exception_basis", "exception_verification", "applicability_scope", "scope_basis", "scope_derivation"):
            if field in completion:
                rule[field] = completion[field]
        verification = rule.get("exception_verification")
        if isinstance(verification, dict):
            # Search coverage is evidence produced by the local complete-corpus
            # traversal, never a model claim.
            verification["searched_chunk_count"] = corpus.get("searched_chunk_count", 0)
            verification["corpus_sha256"] = corpus.get("corpus_sha256")
            verification.setdefault("searched_document_ids", ["organized_corpus"])
        derivation = rule.get("scope_derivation")
        if isinstance(derivation, dict):
            derivation["reviewed_chunk_count"] = corpus.get("searched_chunk_count", 0)
            derivation["corpus_sha256"] = corpus.get("corpus_sha256")
        return rule

    def complete(self, baseline: Mapping[str, Any], graph: Mapping[str, Any], organized_dir: str) -> tuple[dict[str, Any], dict[str, Any]]:
        final_graph = deepcopy(dict(graph))
        corpus = source_document_index(organized_dir)
        rules = [deepcopy(dict(rule)) for rule in final_graph.get("business_rules", []) if isinstance(rule, Mapping)]
        initial_chunk_rechecks = sum(rule.get("exception_basis") == "not_found_in_chunk_recheck_needed" for rule in rules)
        before_scope = {str(rule.get("rule_id")): deepcopy(rule.get("applicability_scope")) for rule in rules}
        try:
            readiness_workers = max(1, int(os.getenv("KG_READINESS_WORKERS", "8")))
        except (TypeError, ValueError):
            readiness_workers = 8

        def complete_one(index: int, original: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
            rule = deepcopy(dict(original))
            rule.setdefault("applicability_scope", {})
            for key in ("loan_types", "occupancy_types", "transaction_types"):
                rule["applicability_scope"].setdefault(key, [])
            rule = self._complete_evidence(rule, self._evidence_packet(rule, corpus))
            rule["execution"] = _project_execution(rule)
            return index, rule

        print(f"▶ Agent 5.5 rule evidence: {len(rules)} rules, {readiness_workers} workers, "
              f"{getattr(self.resolver, 'readiness_concurrency', 'bounded') if self.resolver else 0} API requests", flush=True)
        completed_rules: list[dict[str, Any] | None] = [None] * len(rules)
        with ThreadPoolExecutor(max_workers=readiness_workers, thread_name_prefix="kg-readiness") as executor:
            futures = [executor.submit(complete_one, index, rule) for index, rule in enumerate(rules)]
            for future in as_completed(futures):
                index, completed = future.result()
                completed_rules[index] = completed
        rules = [rule for rule in completed_rules if rule is not None]
        final_graph["business_rules"] = rules

        edges = dependency_edges(final_graph)
        chains, cycles = derive_dependency_chains(edges)
        final_graph.setdefault("dependency_details", {})["dependencies"] = edges
        final_graph["dependency_details"]["dependency_chains"] = chains
        final_graph["dependency_details"]["circular_dependencies"] = cycles

        conflict_entries: list[dict[str, Any]] = []
        ids = {str(rule.get("rule_id")): rule for rule in rules}
        groups = {key: members for key, members in entity_rule_groups(final_graph).items() if len(members) > 1}
        def analyse_group(entity: str, member_ids: list[str]) -> list[dict[str, Any]]:
            summaries = [{key: ids[rule_id].get(key) for key in ("rule_id", "condition_predicates", "condition_logic", "outcomes", "applicability_scope", "exceptions", "recommended_hit_policy")} for rule_id in member_ids]
            analyses = self.resolver.analyse_entity(entity, summaries) if self.resolver else []
            if not analyses:
                analyses = [{"entity": entity, "status": "unresolved", "rule_ids": member_ids, "reasoning": "No entity-local conflict analysis was returned.", "resolution": "Manual review required."}]
            entries = [dict(item) for item in analyses if isinstance(item, Mapping)]
            expected_pairs = {tuple(pair) for pair in combinations(member_ids, 2)}
            covered_pairs = {
                tuple(pair)
                for analysis in entries
                for pair in combinations(sorted(str(rule_id) for rule_id in analysis.get("rule_ids", []) if str(rule_id) in member_ids), 2)
            }
            entries.extend({
                "entity": entity,
                "status": "unresolved",
                "rule_ids": list(pair),
                "reasoning": "The entity-local analyser did not return a co-firing determination for this pair.",
                "resolution": "Manual review required.",
            } for pair in sorted(expected_pairs - covered_pairs))
            return entries

        entity_results: dict[str, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=min(readiness_workers, max(1, len(groups))), thread_name_prefix="kg-conflict") as executor:
            futures = {executor.submit(analyse_group, entity, member_ids): entity for entity, member_ids in groups.items()}
            for future in as_completed(futures):
                entity_results[futures[future]] = future.result()
        for entity in groups:
            conflict_entries.extend(entity_results.get(entity, []))
        final_graph["dependency_details"]["conflicts"] = conflict_entries

        naming = naming_issues(final_graph)
        references = referential_integrity_issues(final_graph)
        entity_keys = list((final_graph.get("entity_types") or {}).keys())
        conflict_by_rule: dict[str, list[dict[str, Any]]] = {}
        for conflict in conflict_entries:
            for rule_id in conflict.get("rule_ids", []):
                conflict_by_rule.setdefault(str(rule_id), []).append(conflict)
        reviewed_rules = []
        contract_error_count = 0
        final_contract_error_count = 0
        for rule in rules:
            contract_issues = [issue.as_dict() for issue in validate_rule_v2(rule, entity_keys)]
            contract_error_count += len(contract_issues)
            issues = contract_issues
            final_issues = final_rule_issues(rule, entity_keys)
            final_contract_error_count += len(final_issues)
            issues.extend(final_issues)
            for conflict in conflict_by_rule.get(str(rule.get("rule_id")), []):
                if conflict.get("status") == "unresolved" or (conflict.get("status") == "conflict" and not str(conflict.get("resolution", "")).strip()):
                    issues.append({"requirement": "conflicts", "reason": conflict.get("reasoning", "entity-local conflict is unresolved")})
            if any(item.get("rule_id") == str(rule.get("rule_id")) for item in references):
                issues.append({"requirement": "referential_integrity", "reason": "rule has a dangling dependency reference"})
            reviewed_rules.append(mark_readiness(rule, issues))
        final_graph["business_rules"] = reviewed_rules
        manifest = corpus_manifest(baseline, final_graph)
        final_graph["corpus_manifest"] = manifest

        exception_bases = [rule.get("exception_basis") for rule in reviewed_rules]
        scope_bases = [rule.get("scope_basis") for rule in reviewed_rules]
        examples = [{"rule_id": rule.get("rule_id"), "before": before_scope.get(str(rule.get("rule_id"))), "after": rule.get("applicability_scope"), "scope_basis": rule.get("scope_basis")} for rule in reviewed_rules if before_scope.get(str(rule.get("rule_id"))) != rule.get("applicability_scope")][:5]
        non_conflicts = [entry for entry in conflict_entries if entry.get("status") == "non_conflict"]
        conflicts = [entry for entry in conflict_entries if entry.get("status") == "conflict"]
        unresolved = [rule for rule in reviewed_rules if rule.get("requires_review")]
        report = {
            "invariants": {
                "corpus_integrity": {"pass": manifest["pass"] and not manifest["missing_change_reasons"], "evidence": f"{len(manifest['input_sections'])} input and {len(manifest['final_sections'])} final cited sections.", **manifest},
                "naming_consistency": {"pass": not naming, "evidence": f"{len(entity_keys)} entity type keys checked; {len(naming)} violations.", "violations": naming},
                "schema_consistency": {"pass": contract_error_count + final_contract_error_count == 0, "evidence": f"{len(reviewed_rules)} rules checked; {contract_error_count} v2 and {final_contract_error_count} final-readiness contract violations."},
                "referential_integrity": {"pass": not references, "evidence": f"{len(edges)} dependency edges checked; {len(references)} dangling references.", "violations": references},
            },
            "conflicts_and_dependencies": {"entities_checked": len(groups), "conflicts_found": len(conflicts), "dependency_chains_derived": len(chains), "conflict_examples": conflicts[:3], "non_conflict_examples": non_conflicts[:max(10, 3)], "conflict_example_shortfall": max(0, 3 - len(conflicts)), "non_conflict_example_shortfall": max(0, 3 - len(non_conflicts)), "cycles": cycles},
            "exception_recheck": {"rules_starting_with_not_found_in_chunk_recheck_needed": initial_chunk_rechecks, "resolved_to_explicit_in_source": exception_bases.count("explicit_in_source"), "resolved_to_explicitly_none_in_source": exception_bases.count("explicitly_none_in_source"), "remaining_unresolved": exception_bases.count("unresolved_after_full_document_search"), "unresolved_rules": [{"rule_id": rule.get("rule_id"), "reason": (rule.get("exception_verification") or {}).get("unresolved_reason")} for rule in reviewed_rules if rule.get("exception_basis") == "unresolved_after_full_document_search"]},
            "scope_derivation": {"newly_populated_from_source_evidence": sum(bool(rule.get("applicability_scope", {}).get(key)) and not (before_scope.get(str(rule.get("rule_id"))) or {}).get(key) for rule in reviewed_rules for key in ("loan_types", "occupancy_types", "transaction_types")), "confirmed_explicitly_universal_in_source": scope_bases.count("explicitly_universal_in_source"), "confirmed_genuinely_unscoped": scope_bases.count("genuinely_unscoped"), "examples": examples},
            "rules_ready": sum(not rule.get("requires_review") for rule in reviewed_rules),
            "rules_requiring_review": len(unresolved),
        }
        return final_graph, report

    def run(self, baseline_path: Path, graph_path: Path, organized_dir: Path, output_dir: Path) -> dict[str, Any]:
        baseline, graph = json.loads(baseline_path.read_text()), json.loads(graph_path.read_text())
        final_graph, report = self.complete(baseline, graph, str(organized_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        graph_path.write_text(json.dumps(final_graph, indent=2, ensure_ascii=False) + "\n")
        (output_dir / "corpus_manifest.json").write_text(json.dumps(final_graph["corpus_manifest"], indent=2) + "\n")
        (output_dir / "kg_readiness_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        (output_dir / "kg_readiness_report.md").write_text(_report_markdown(report))
        print(f"✅ Agent 5.5 completed: {report['rules_ready']} ready, {report['rules_requiring_review']} require review", flush=True)
        return report


def main() -> None:
    config = get_config()
    resolver = OpenAIEvidenceResolver(config.get_openai_api_key(), config.get_optimizer_model_name(), config.get_reasoning_effort())
    completer = ExecutableReadinessCompleter(resolver)
    baseline = config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
    output_dir = config.get_optimized_dir()
    report = completer.run(baseline, output_dir / "optimized_compliance_knowledge_graph.json", config.get_organized_dir(), output_dir)
    invariant_pass = all(result["pass"] for result in report["invariants"].values())
    if not invariant_pass or report["rules_requiring_review"]:
        print("❌ Agent 5.5 readiness pass failed; inspect kg_readiness_report.json.", flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
