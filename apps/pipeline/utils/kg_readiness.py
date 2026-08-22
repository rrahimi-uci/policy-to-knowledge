"""Deterministic foundations for the executable knowledge-graph readiness pass.

The LLM completion stage may interpret evidence, but it must not decide whether
the corpus, graph, names, or references are internally consistent.  These
helpers make those claims reproducible and testable without a model call.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import re
from typing import Any, Iterable, Mapping


CANONICAL_ENTITY_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
FINAL_EXCEPTION_BASES = {
    "explicit_in_source",
    "explicitly_none_in_source",
    "unresolved_after_full_document_search",
}
FINAL_SCOPE_BASES = {
    "explicit",
    # See the matching entries (and their rationale) in rule_contract.SCOPE_BASES.
    "explicit_in_source",
    "explicitly_none_in_source",
    "explicitly_universal_in_source",
    "genuinely_unscoped",
    "unresolved_after_source_review",
}
# The subset of FINAL_SCOPE_BASES that asserts something affirmative about the
# source text (as opposed to "genuinely_unscoped"/"unresolved_after_source_review",
# which assert the absence or unavailability of scope language) — these require
# an actual evidence citation before a rule can be marked ready. Named once so
# the two checks below (and any future one) can't drift apart the way
# scope_basis and exception_basis's enums did.
SCOPE_BASES_REQUIRING_EVIDENCE = {"explicit", "explicit_in_source", "explicitly_none_in_source", "explicitly_universal_in_source"}


def canonical_entity_key(value: Any) -> str:
    """Return the lexical SCREAMING_SNAKE_CASE form without semantic aliasing."""
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip())).strip("_").upper()


def _references(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                yield item


def cited_sections(graph: Mapping[str, Any]) -> set[str]:
    """Collect every section cited by rule-level provenance and field evidence."""
    sections: set[str] = set()
    for rule in graph.get("business_rules", []):
        if not isinstance(rule, Mapping):
            continue
        for reference in _references(rule.get("source_reference")):
            if str(reference.get("section_id", "")).strip():
                sections.add(str(reference["section_id"]).strip())
        evidence = rule.get("field_evidence", {})
        if isinstance(evidence, Mapping):
            for entries in evidence.values():
                for reference in _references(entries):
                    if str(reference.get("section_id", "")).strip():
                        sections.add(str(reference["section_id"]).strip())
    return sections


def corpus_manifest(input_graph: Mapping[str, Any], final_graph: Mapping[str, Any], reasons: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Compare cited section sets; callers must supply reasons for differences."""
    before, after = cited_sections(input_graph), cited_sections(final_graph)
    reasons = reasons or {}
    added, removed = sorted(after - before), sorted(before - after)
    missing_reasons = [section for section in added + removed if not str(reasons.get(section, "")).strip()]
    return {
        "input_sections": sorted(before),
        "final_sections": sorted(after),
        "sections_added": [{"section_id": section, "reason": reasons.get(section, "")} for section in added],
        "sections_removed": [{"section_id": section, "reason": reasons.get(section, "")} for section in removed],
        "corpus_unchanged": not added and not removed,
        "pass": not missing_reasons,
        "missing_change_reasons": missing_reasons,
    }


def dependency_edges(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read canonical top-level edges and fall back to per-rule dependency lists."""
    details = graph.get("dependency_details", {})
    raw = details.get("dependencies", []) if isinstance(details, Mapping) else []
    edges = [dict(edge) for edge in raw if isinstance(edge, Mapping)]
    if edges:
        return edges
    for rule in graph.get("business_rules", []):
        if not isinstance(rule, Mapping):
            continue
        target = rule.get("rule_id")
        for dep in rule.get("dependencies", []) or []:
            if isinstance(dep, Mapping):
                edges.append({"source_rule_id": dep.get("depends_on_rule"), "target_rule_id": target, **dict(dep)})
    return edges


def referential_integrity_issues(graph: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return every dangling rule reference; no mutation or silent removal."""
    ids = {str(rule.get("rule_id")) for rule in graph.get("business_rules", []) if isinstance(rule, Mapping) and rule.get("rule_id")}
    issues: list[dict[str, str]] = []
    for rule in graph.get("business_rules", []):
        if not isinstance(rule, Mapping):
            continue
        rule_id = str(rule.get("rule_id", ""))
        for field, target_field in (("dependencies", "depends_on_rule"), ("dependent_rules", "dependent_rule")):
            for index, ref in enumerate(rule.get(field, []) or []):
                if isinstance(ref, Mapping) and ref.get(target_field) not in ids:
                    issues.append({"rule_id": rule_id, "path": f"{field}[{index}].{target_field}", "missing_rule_id": str(ref.get(target_field))})
    for index, edge in enumerate(dependency_edges(graph)):
        for field in ("source_rule_id", "target_rule_id"):
            if edge.get(field) not in ids:
                issues.append({"rule_id": "<graph>", "path": f"dependency_details.dependencies[{index}].{field}", "missing_rule_id": str(edge.get(field))})
    return issues


def derive_dependency_chains(edges: Iterable[Mapping[str, Any]], max_chains: int = 5000) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """Derive maximal simple paths and cycles from graph edges deterministically."""
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    incoming: set[str] = set()
    nodes: set[str] = set()
    for edge in edges:
        source, target = str(edge.get("source_rule_id", "")), str(edge.get("target_rule_id", ""))
        if not source or not target:
            continue
        adjacency[source].append((target, str(edge.get("dependency_type", "unknown"))))
        incoming.add(target)
        nodes.update((source, target))
    for source in adjacency:
        adjacency[source].sort()
    starts = sorted(nodes - incoming) or sorted(nodes)
    chains: list[dict[str, Any]] = []
    cycles: set[tuple[str, ...]] = set()

    def walk(node: str, path: list[str], types: list[str]) -> None:
        if len(chains) >= max_chains:
            return
        next_edges = adjacency.get(node, [])
        if not next_edges:
            if len(path) > 1:
                chains.append({"rule_ids": path, "dependency_types": types})
            return
        extended = False
        for target, edge_type in next_edges:
            if target in path:
                loop = path[path.index(target):] + [target]
                cycles.add(tuple(loop))
                continue
            extended = True
            walk(target, path + [target], types + [edge_type])
        if not extended and len(path) > 1:
            chains.append({"rule_ids": path, "dependency_types": types})

    for start in starts:
        walk(start, [start], [])
    # A graph containing only cycles has no terminal path; cycles are still evidence.
    return chains, [list(cycle) for cycle in sorted(cycles)]


def entity_rule_groups(graph: Mapping[str, Any]) -> dict[str, list[str]]:
    """Group attached rules by canonical entity key for local conflict analysis."""
    groups: dict[str, list[str]] = defaultdict(list)
    for rule in graph.get("business_rules", []):
        if not isinstance(rule, Mapping) or not rule.get("rule_id"):
            continue
        entities = list(rule.get("related_entities", []) or [])
        entities.extend([rule.get("source_entity"), rule.get("entity_type"), rule.get("responsible_party")])
        for entity in entities:
            if str(entity or "").strip():
                rule_id = str(rule["rule_id"])
                key = canonical_entity_key(entity)
                if rule_id not in groups[key]:
                    groups[key].append(rule_id)
    return {key: sorted(value) for key, value in sorted(groups.items())}


def naming_issues(graph: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate exact canonical naming, including parties, without alias guesses."""
    issues: list[dict[str, str]] = []
    entity_types = graph.get("entity_types", {})
    keys = set(entity_types) if isinstance(entity_types, Mapping) else set()
    for key in sorted(keys):
        if not CANONICAL_ENTITY_RE.fullmatch(key):
            issues.append({"path": f"entity_types.{key}", "value": key, "reason": "entity type key is not SCREAMING_SNAKE_CASE"})
    for rule in graph.get("business_rules", []):
        if not isinstance(rule, Mapping):
            continue
        for field in ("responsible_party",):
            value = rule.get(field)
            if value and (value not in keys or not CANONICAL_ENTITY_RE.fullmatch(str(value))):
                issues.append({"path": f"{rule.get('rule_id')}.{field}", "value": str(value), "reason": "party is not an exact canonical entity key"})
        for index, value in enumerate(rule.get("counterparties", []) or []):
            if value not in keys or not CANONICAL_ENTITY_RE.fullmatch(str(value)):
                issues.append({"path": f"{rule.get('rule_id')}.counterparties[{index}]", "value": str(value), "reason": "party is not an exact canonical entity key"})
    return issues


def source_document_index(organized_dir: str) -> dict[str, Any]:
    """Index every organized chunk, with stable digest evidence of corpus search."""
    from pathlib import Path
    root = Path(organized_dir)
    chunks = []
    for path in sorted(root.rglob("*.txt")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(root)
        chunks.append({"chunk_path": str(relative), "section_id": relative.parent.name or path.stem, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    digest = hashlib.sha256("".join(item["sha256"] for item in chunks).encode()).hexdigest()
    return {"chunks": chunks, "chunk_count": len(chunks), "corpus_sha256": digest}


def _non_empty_list(value: Any) -> list | None:
    return value if isinstance(value, list) and value else None


def _best_evidence(dedicated: Any, field_evidence_entries: Any) -> list | None:
    """Prefer a field's own dedicated evidence list; fall back to the rule's
    field_evidence entries for that same field when the resolver completion
    omitted it.

    The dominant real cause: a candidate rule Agent 3 already marked with a
    final-looking basis (e.g. scope_basis "explicit_in_source") is reasonably
    treated by the completion resolver as not needing further derivation, so
    its response omits scope_derivation/exception_verification entirely —
    leaving whatever shape Agent 3's own extraction happened to put there
    (observed in practice: an ad hoc object with fields like
    "primary_source_reference" that this reader never asked for). Rather than
    depend on every upstream shape matching exactly, fall back to
    field_evidence.scope_basis / field_evidence.exceptions — validate_rule_v2
    already requires those to have this exact {chunk_path, section_id,
    source_text} shape, so this recognizes evidence that was already
    validated, it does not invent anything.
    """
    return _non_empty_list(dedicated) or _non_empty_list(field_evidence_entries)


def final_rule_issues(rule: Mapping[str, Any], entity_keys: Iterable[str]) -> list[dict[str, Any]]:
    """Validate the final-only fields that make a candidate executable."""
    issues: list[dict[str, Any]] = []
    field_evidence = rule.get("field_evidence")
    field_evidence_map = field_evidence if isinstance(field_evidence, Mapping) else {}
    # Computed once up top (not just where the evidence checks need it further
    # down) so the unresolved_reason read a few lines below can't fall into
    # the same `(x or {}).get(...)` trap already fixed for exception_verification
    # — scope_derivation is just as often a malformed non-dict.
    derivation = rule.get("scope_derivation")
    derivation_map = derivation if isinstance(derivation, Mapping) else {}

    scope = rule.get("applicability_scope")
    # A rule that scopes itself with richer, domain-specific keys (e.g.
    # "jurisdiction", "trigger_event") alongside the three standard ones is not
    # thereby less scoped — but a resolver completion that replaces
    # applicability_scope wholesale can drop a standard key it didn't happen to
    # populate. Agent 5.5's own defaulting (`.setdefault(key, [])`) only runs
    # before that replacement, so a missing key here means "not stated", the
    # same as an explicit empty list — `.get(key, [])` treats them alike
    # rather than failing an absent key as if it were a wrong type.
    if not isinstance(scope, Mapping) or any(not isinstance(scope.get(key, []), list) for key in ("loan_types", "occupancy_types", "transaction_types")):
        issues.append({"requirement": "scope", "reason": "scope must contain list-valued loan_types, occupancy_types, and transaction_types"})
    if rule.get("scope_basis") not in FINAL_SCOPE_BASES:
        issues.append({"requirement": "scope", "reason": "scope_basis is not a final evidence state"})
    if rule.get("scope_basis") == "unresolved_after_source_review" and not str(derivation_map.get("unresolved_reason", "")).strip():
        issues.append({"requirement": "scope", "reason": "unresolved scope lacks a specific evidence limit"})
    elif rule.get("scope_basis") == "unresolved_after_source_review":
        issues.append({
            "requirement": "scope",
            "reason": str(derivation_map.get("unresolved_reason")),
            "evidence_limited": True,
        })
    if rule.get("exception_basis") not in FINAL_EXCEPTION_BASES:
        issues.append({"requirement": "exceptions", "reason": "exception_basis is not a completed full-document state"})
    verification = rule.get("exception_verification")
    # `verification` may be malformed (e.g. a plain string, if an upstream
    # completion response didn't match the expected shape) — every read below
    # guards with isinstance rather than `verification or {}`, which only
    # substitutes {} for falsy values and does nothing for a truthy non-dict
    # like a non-empty string.
    verification_map = verification if isinstance(verification, Mapping) else {}
    # Some completions/candidate rules name this list "source_evidence"
    # (entries shaped {chunk_path, section_id, quote}) instead of the
    # documented "evidence" ({chunk_path, section_id, source_text}) — treat
    # them as the same field rather than losing a real citation to a naming
    # difference.
    exception_evidence = _best_evidence(
        verification_map.get("evidence") or verification_map.get("source_evidence"),
        field_evidence_map.get("exceptions"),
    )
    exception_has_positive_citation = rule.get("exception_basis") == "explicit_in_source" and exception_evidence
    if (
        not isinstance(verification_map.get("searched_chunk_count"), int)
        or verification_map.get("searched_chunk_count", 0) < 1
    ) and not exception_has_positive_citation:
        # A rule with field_evidence-backed direct proof of its exception
        # doesn't also need a separate full-corpus-search count — the citation
        # itself is the evidence. An exhaustive-search count is still required
        # for the "nothing found"/unresolved states, where there is no
        # positive citation to point to instead.
        issues.append({"requirement": "exceptions", "reason": "full-document search provenance is missing"})
    if rule.get("exception_basis") == "unresolved_after_full_document_search" and not str(verification_map.get("unresolved_reason", "")).strip():
        issues.append({"requirement": "exceptions", "reason": "unresolved exception lacks a specific evidence limit"})
    elif rule.get("exception_basis") == "unresolved_after_full_document_search":
        issues.append({
            "requirement": "exceptions",
            "reason": str(verification_map.get("unresolved_reason")),
            "evidence_limited": True,
        })
    if rule.get("exception_basis") == "explicit_in_source" and (not isinstance(rule.get("exceptions"), list) or not rule.get("exceptions") or not exception_evidence):
        issues.append({"requirement": "exceptions", "reason": "explicit exception lacks structured predicates or direct source evidence"})
    scope_evidence = _best_evidence(
        derivation_map.get("evidence") or derivation_map.get("source_evidence"),
        field_evidence_map.get("scope_basis"),
    )
    scope_has_positive_citation = rule.get("scope_basis") in SCOPE_BASES_REQUIRING_EVIDENCE and scope_evidence
    if (
        not isinstance(derivation_map.get("reviewed_chunk_count"), int)
        or derivation_map.get("reviewed_chunk_count", 0) < 1
    ) and not scope_has_positive_citation:
        issues.append({"requirement": "scope", "reason": "scope review provenance is missing"})
    if rule.get("scope_basis") in SCOPE_BASES_REQUIRING_EVIDENCE and not scope_evidence:
        issues.append({"requirement": "scope", "reason": "source-derived scope lacks evidence entries"})
    execution = rule.get("execution")
    if not isinstance(execution, Mapping) or not isinstance(execution.get("targets"), list) or not set(execution.get("targets", [])).intersection({"DMN", "BPMN"}):
        issues.append({"requirement": "execution", "reason": "rule has no DMN or BPMN projection"})
    if isinstance(execution, Mapping) and "DMN" in execution.get("targets", []) and not isinstance(execution.get("dmn"), Mapping):
        issues.append({"requirement": "execution", "reason": "DMN target lacks a projection"})
    if isinstance(execution, Mapping) and "BPMN" in execution.get("targets", []) and not isinstance(execution.get("bpmn"), Mapping):
        issues.append({"requirement": "execution", "reason": "BPMN target lacks a projection"})
    return issues


def mark_readiness(rule: Mapping[str, Any], issues: Iterable[Mapping[str, str]]) -> dict[str, Any]:
    """Set review status from concrete findings only; preserve every rule field."""
    result = deepcopy(dict(rule))
    failures = [dict(issue) for issue in issues]
    result["readiness"] = {
        "status": "ready" if not failures else "review_required",
        "failed_requirements": failures,
        "review_reason": None if not failures else "; ".join(sorted({item.get("reason", "") for item in failures if item.get("reason")})),
    }
    result["requires_review"] = bool(failures)
    return result
