"""
Impact Service — Regulatory Change Impact Analysis engine.

Compares old and new regulatory document text, identifies added/removed/modified
provisions, and maps each change to affected rules in an existing knowledge graph.
Assigns severity: breaking | material | cosmetic.
"""

import difflib
import re
from typing import List, Dict, Any, Optional

from . import graph_service, impact_store


# ── Severity keywords ────────────────────────────────────────────────────────

_BREAKING_KEYWORDS = {
    "must", "shall", "required", "prohibited", "forbid", "mandatory",
    "not permitted", "violation", "penalty", "cease", "revoke", "terminate",
}
_MATERIAL_KEYWORDS = {
    "should", "recommend", "material", "significant", "threshold",
    "limit", "maximum", "minimum", "deadline", "timeframe", "calculate",
    "eligibility", "qualify", "condition", "process", "procedure",
}


def _classify_severity(text: str, affected_count: int) -> str:
    """Heuristic severity classification based on provision text and blast radius."""
    lower = text.lower()
    for kw in _BREAKING_KEYWORDS:
        if kw in lower:
            return "breaking"
    for kw in _MATERIAL_KEYWORDS:
        if kw in lower:
            return "material"
    if affected_count >= 5:
        return "material"
    return "cosmetic"


# ── Text diffing ─────────────────────────────────────────────────────────────

def _split_provisions(text: str) -> List[str]:
    """Split regulatory text into individual provisions / paragraphs."""
    # Split on double newlines, numbered sections, or lettered subsections
    chunks = re.split(r'\n\s*\n|\n(?=\d+[\.\)]\s)|\n(?=[a-z]\)\s)|\n(?=\([a-z]+\)\s)', text)
    return [c.strip() for c in chunks if c and c.strip() and len(c.strip()) > 20]


def _compute_diff(old_provisions: List[str], new_provisions: List[str]) -> Dict[str, List[str]]:
    """Compute added, removed, and modified provisions between old and new text."""
    matcher = difflib.SequenceMatcher(None, old_provisions, new_provisions)
    added = []
    removed = []
    modified = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        elif tag == "insert":
            added.extend(new_provisions[j1:j2])
        elif tag == "delete":
            removed.extend(old_provisions[i1:i2])
        elif tag == "replace":
            # Pair up replacements
            old_chunk = old_provisions[i1:i2]
            new_chunk = new_provisions[j1:j2]
            for k in range(max(len(old_chunk), len(new_chunk))):
                old_text = old_chunk[k] if k < len(old_chunk) else ""
                new_text = new_chunk[k] if k < len(new_chunk) else ""
                if old_text and new_text:
                    ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
                    if ratio > 0.3:
                        modified.append(
                            f"CHANGED FROM: {old_text[:200]}... → TO: {new_text[:200]}..."
                            if len(old_text) > 200 or len(new_text) > 200
                            else f"CHANGED FROM: {old_text} → TO: {new_text}"
                        )
                    else:
                        if old_text:
                            removed.append(old_text)
                        if new_text:
                            added.append(new_text)
                elif old_text:
                    removed.append(old_text)
                elif new_text:
                    added.append(new_text)

    return {"added": added, "removed": removed, "modified": modified}


# ── Rule matching ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower().strip())


def _extract_key_phrases(text: str) -> List[str]:
    """Extract meaningful phrases (3+ word sequences) from provision text."""
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    # Remove very common stop words
    stops = {"the", "and", "for", "are", "but", "not", "you", "all", "can",
             "had", "her", "was", "one", "our", "out", "has", "have", "that",
             "this", "from", "with", "they", "been", "will", "each", "make",
             "like", "than", "them", "then", "into", "some", "when", "which"}
    return [w for w in words if w not in stops]


def _find_affected_rules(
    provision_text: str, rules: List[dict], threshold: float = 0.15
) -> List[dict]:
    """Find rules affected by a provision change using keyword overlap scoring."""
    provision_words = set(_extract_key_phrases(provision_text))
    if not provision_words:
        return []

    matches = []
    for rule in rules:
        rule_text = f"{rule.get('rule_name', '')} {rule.get('description', '')} {rule.get('entity_type', '')}"
        rule_words = set(_extract_key_phrases(rule_text))
        if not rule_words:
            continue

        overlap = provision_words & rule_words
        score = len(overlap) / max(len(provision_words), 1)

        if score >= threshold:
            matches.append({
                "rule_id": rule.get("rule_id", ""),
                "rule_name": rule.get("rule_name", ""),
                "rule_type": rule.get("rule_type", ""),
                "risk_level": rule.get("risk_level", ""),
                "confidence_score": rule.get("confidence_score", 0),
                "match_score": round(score, 3),
                "matching_terms": sorted(overlap)[:10],
            })

    matches.sort(key=lambda m: m["match_score"], reverse=True)
    return matches[:20]  # limit to top 20 per provision


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis(
    analysis_id: str,
    old_text: str,
    new_text: str,
    graph_name: str,
    provider: str = "openai",
) -> dict:
    """Execute full impact analysis: diff provisions → match rules → score severity."""
    try:
        impact_store.update_analysis(analysis_id, status="running")

        # 1. Load graph rules
        graph_data = graph_service.get_graph_data(graph_name, provider)
        if not graph_data:
            impact_store.update_analysis(
                analysis_id, status="failed", error=f"Graph '{graph_name}' not found"
            )
            return impact_store.get_analysis(analysis_id)

        rules = graph_data.get("business_rules", [])
        if not rules:
            # Try nested entity_types
            for et in graph_data.get("entity_types", {}).values():
                rules.extend(r for r in et.get("business_rules", []) if isinstance(r, dict))

        # 2. Split into provisions & diff
        old_provisions = _split_provisions(old_text)
        new_provisions = _split_provisions(new_text)
        diff = _compute_diff(old_provisions, new_provisions)

        # 3. Map changes to affected rules
        all_affected_rule_ids = set()
        severity_counts = {"breaking": 0, "material": 0, "cosmetic": 0}

        for change_type, provisions in diff.items():
            for provision in provisions:
                affected = _find_affected_rules(provision, rules)
                severity = _classify_severity(provision, len(affected))
                severity_counts[severity] += 1

                for r in affected:
                    all_affected_rule_ids.add(r["rule_id"])

                impact_store.add_impact_item(
                    analysis_id=analysis_id,
                    change_type=change_type,
                    provision_text=provision[:2000],
                    severity=severity,
                    affected_rules=affected,
                    description=f"{change_type.upper()} provision affecting {len(affected)} rules",
                    recommendation=_generate_recommendation(change_type, severity, affected),
                )

        # 4. Compute stats
        total_changes = sum(len(v) for v in diff.values())
        stats = {
            "total_changes": total_changes,
            "added_count": len(diff["added"]),
            "removed_count": len(diff["removed"]),
            "modified_count": len(diff["modified"]),
            "total_rules_in_graph": len(rules),
            "affected_rules_count": len(all_affected_rule_ids),
            "severity_breaking": severity_counts["breaking"],
            "severity_material": severity_counts["material"],
            "severity_cosmetic": severity_counts["cosmetic"],
            "impact_percentage": round(
                len(all_affected_rule_ids) / max(len(rules), 1) * 100, 1
            ),
        }

        summary = {
            "headline": _generate_headline(stats),
            "old_provision_count": len(old_provisions),
            "new_provision_count": len(new_provisions),
        }

        impact_store.update_analysis(
            analysis_id,
            status="completed",
            summary=summary,
            stats=stats,
            finished_at=impact_store._now(),
        )

        return impact_store.get_analysis(analysis_id)

    except Exception as exc:
        impact_store.update_analysis(
            analysis_id,
            status="failed",
            error=str(exc),
            finished_at=impact_store._now(),
        )
        return impact_store.get_analysis(analysis_id)


def _generate_headline(stats: dict) -> str:
    total = stats["total_changes"]
    affected = stats["affected_rules_count"]
    breaking = stats["severity_breaking"]
    if breaking > 0:
        return f"{total} regulatory changes detected — {breaking} breaking change{'s' if breaking != 1 else ''} affecting {affected} rules ({stats['impact_percentage']}% of graph)"
    if affected > 0:
        return f"{total} regulatory changes detected — {affected} rules potentially affected ({stats['impact_percentage']}% of graph)"
    return f"{total} regulatory changes detected — no rules directly affected"


def _generate_recommendation(change_type: str, severity: str, affected: list) -> str:
    if not affected:
        return "No rules directly affected. Review for indirect upstream/downstream impact."
    rule_names = [r["rule_name"] for r in affected[:3]]
    names_str = ", ".join(rule_names)
    if severity == "breaking":
        return f"URGENT: Review and update rules immediately: {names_str}"
    if severity == "material":
        return f"Review for compliance within next review cycle: {names_str}"
    return f"Minor update — verify accuracy: {names_str}"


def export_analysis(analysis_id: str, fmt: str = "json") -> Optional[Any]:
    """Export impact analysis as JSON or CSV."""
    analysis = impact_store.get_analysis(analysis_id)
    if not analysis:
        return None

    items = impact_store.get_impact_items(analysis_id)

    if fmt == "json":
        return {**analysis, "items": items}

    if fmt == "csv":
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "change_type", "severity", "provision_text",
            "affected_rule_count", "affected_rule_names",
            "description", "recommendation",
        ])
        for item in items:
            rule_names = ", ".join(r.get("rule_name", "") for r in item["affected_rules"])
            writer.writerow([
                item["change_type"],
                item["severity"],
                item["provision_text"][:500],
                len(item["affected_rules"]),
                rule_names[:500],
                item.get("description", ""),
                item.get("recommendation", ""),
            ])
        return output.getvalue()

    return None
