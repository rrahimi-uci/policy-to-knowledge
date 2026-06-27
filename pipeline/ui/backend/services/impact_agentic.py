"""
Agentic Impact Analysis — LLM-powered regulatory change impact engine.

Five-step agentic workflow:
  Step 1 — Document Parsing & Structuring (LLM)
  Step 2 — Semantic Diff Analysis (LLM)
  Step 3 — Rule Impact Mapping (LLM + KG data)
  Step 4 — Severity & Risk Scoring (LLM)
  Step 5 — Executive Summary & Recommendations (LLM)

Each step streams progress via an async callback, enabling real-time
WebSocket updates to the frontend.
"""

import asyncio
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from . import graph_service, impact_store

# ── LLM client ---------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

def _create_client(provider: str = "openai"):
    """Create an LLM client using the project's existing abstraction."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from utils.config import get_config
    from utils.llm_client import create_llm_client

    config = get_config(provider=provider)
    api_key = config.get_openai_api_key() if provider == "openai" else config.get_anthropic_api_key()
    return create_llm_client(
        api_key=api_key,
        model=config.get_reasoning_model(),
        timeout=config.get_timeout(),
        max_retries=config.get_max_retries(),
    ), config


# ── Workflow Steps -----------------------------------------------------------

STEPS = [
    {"id": "parse",     "name": "Document Parsing & Structuring",       "order": 1},
    {"id": "diff",      "name": "Semantic Diff Analysis",               "order": 2},
    {"id": "map",       "name": "Rule Impact Mapping",                  "order": 3},
    {"id": "score",     "name": "Severity & Risk Scoring",              "order": 4},
    {"id": "summarize", "name": "Executive Summary & Recommendations",  "order": 5},
]

ProgressCallback = Optional[Callable[[dict], Coroutine[Any, Any, None]]]


async def _emit(cb: ProgressCallback, payload: dict):
    """Fire progress callback if provided."""
    if cb:
        await cb(payload)


def _truncate(text: str, max_chars: int = 6000) -> str:
    """Truncate text to fit within token budgets."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[...truncated, {len(text) - max_chars} chars omitted]"


def _safe_json_parse(text: str) -> Any:
    """Extract and parse JSON from LLM response that may include markdown fences."""
    cleaned = text.strip()
    # Remove markdown fences
    match = re.search(r'```(?:json)?\s*\n?(.*?)```', cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
    return json.loads(cleaned)


# ── Step 1: Document Parsing & Structuring ------------------------------------

async def _step_parse(
    client, old_text: str, new_text: str, cb: ProgressCallback
) -> Dict[str, Any]:
    """Use LLM to parse regulatory documents into structured provisions."""
    await _emit(cb, {"step": "parse", "status": "running",
                     "message": "Parsing regulatory documents into structured provisions..."})

    prompt = f"""You are a regulatory document analyst. Parse the following two regulatory documents
into structured lists of numbered provisions. Each provision should be a distinct regulatory
requirement, rule, or guideline.

Return JSON with this exact structure:
{{
  "old_provisions": [
    {{"id": "P1", "text": "provision text", "section": "section heading if available", "category": "eligibility|process|compliance|documentation|calculation|constraint|prohibition|exception|definition|validation"}}
  ],
  "new_provisions": [
    {{"id": "P1", "text": "provision text", "section": "section heading if available", "category": "eligibility|process|compliance|documentation|calculation|constraint|prohibition|exception|definition|validation"}}
  ],
  "document_summary": {{
    "old_doc_topic": "brief description",
    "new_doc_topic": "brief description",
    "regulatory_domain": "mortgage|aml|healthcare|lending|insurance|general"
  }}
}}

=== OLD DOCUMENT ===
{_truncate(old_text)}

=== NEW DOCUMENT ===
{_truncate(new_text)}"""

    response = client.get_text_response(
        messages=[
            {"role": "system", "content": "You are an expert regulatory document parser. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    result = _safe_json_parse(response)
    old_count = len(result.get("old_provisions", []))
    new_count = len(result.get("new_provisions", []))
    await _emit(cb, {"step": "parse", "status": "completed",
                     "message": f"Parsed {old_count} old + {new_count} new provisions",
                     "data": {"old_count": old_count, "new_count": new_count,
                              "summary": result.get("document_summary", {})}})
    return result


# ── Step 2: Semantic Diff Analysis --------------------------------------------

async def _step_diff(
    client, parsed: Dict[str, Any], cb: ProgressCallback
) -> Dict[str, Any]:
    """Use LLM to perform semantic diff between old and new provisions."""
    await _emit(cb, {"step": "diff", "status": "running",
                     "message": "Performing semantic diff analysis..."})

    old_provisions = parsed.get("old_provisions", [])
    new_provisions = parsed.get("new_provisions", [])

    prompt = f"""You are a regulatory change analyst. Compare the old and new provisions below
and identify ALL changes: additions, removals, and modifications.

For modifications, explain WHAT changed semantically (not just text differences).

Return JSON:
{{
  "changes": [
    {{
      "change_id": "C1",
      "change_type": "added|removed|modified",
      "old_provision_id": "P3 or null",
      "new_provision_id": "P5 or null",
      "description": "clear description of what changed",
      "old_text": "original text (for modified/removed)",
      "new_text": "new text (for modified/added)",
      "semantic_impact": "brief explanation of regulatory impact",
      "category": "eligibility|process|compliance|documentation|calculation|constraint|prohibition|exception|definition|validation"
    }}
  ],
  "unchanged_count": 5,
  "diff_summary": "high-level summary of changes"
}}

=== OLD PROVISIONS ===
{json.dumps(old_provisions[:60], indent=1)}

=== NEW PROVISIONS ===
{json.dumps(new_provisions[:60], indent=1)}"""

    response = client.get_text_response(
        messages=[
            {"role": "system", "content": "You are an expert at regulatory change analysis. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    result = _safe_json_parse(response)
    changes = result.get("changes", [])
    await _emit(cb, {"step": "diff", "status": "completed",
                     "message": f"Found {len(changes)} changes ({sum(1 for c in changes if c.get('change_type')=='added')} added, "
                                f"{sum(1 for c in changes if c.get('change_type')=='removed')} removed, "
                                f"{sum(1 for c in changes if c.get('change_type')=='modified')} modified)",
                     "data": {"change_count": len(changes),
                              "summary": result.get("diff_summary", "")}})
    return result


# ── Step 3: Rule Impact Mapping -----------------------------------------------

async def _step_map(
    client, diff_result: Dict[str, Any], rules: List[dict],
    graph_name: str, cb: ProgressCallback,
) -> Dict[str, Any]:
    """Use LLM to map each change to affected rules in the knowledge graph."""
    await _emit(cb, {"step": "map", "status": "running",
                     "message": f"Mapping changes to {len(rules)} rules in '{graph_name}'..."})

    changes = diff_result.get("changes", [])

    # Prepare a compact rule index for the LLM
    rule_index = []
    for r in rules[:200]:  # Cap for token limits
        rule_index.append({
            "rule_id": r.get("rule_id", ""),
            "rule_name": r.get("rule_name", ""),
            "rule_type": r.get("rule_type", ""),
            "risk_level": r.get("risk_level", ""),
            "entity_type": r.get("entity_type", ""),
        })

    prompt = f"""You are a compliance rule-mapping specialist. For each regulatory change below,
identify which rules in the knowledge graph are AFFECTED by that change.

A rule is affected if:
- The change directly modifies requirements the rule enforces
- The change alters thresholds, conditions, or criteria the rule checks
- The change adds/removes obligations that the rule depends on
- The change affects the entity type the rule governs

Return JSON:
{{
  "mappings": [
    {{
      "change_id": "C1",
      "affected_rules": [
        {{
          "rule_id": "R001",
          "rule_name": "rule name",
          "relevance": "high|medium|low",
          "reasoning": "one sentence explaining why this rule is affected"
        }}
      ],
      "blast_radius": "isolated|moderate|widespread"
    }}
  ],
  "total_affected_rules": 15,
  "most_affected_rule_types": ["eligibility", "process"]
}}

=== CHANGES ===
{json.dumps(changes[:40], indent=1)}

=== KNOWLEDGE GRAPH RULES ===
{json.dumps(rule_index, indent=1)}"""

    response = client.get_text_response(
        messages=[
            {"role": "system", "content": "You are an expert at mapping regulatory changes to compliance rules. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    result = _safe_json_parse(response)
    total = result.get("total_affected_rules", 0)
    await _emit(cb, {"step": "map", "status": "completed",
                     "message": f"Mapped changes to {total} affected rules",
                     "data": {"total_affected": total,
                              "top_rule_types": result.get("most_affected_rule_types", [])}})
    return result


# ── Step 4: Severity & Risk Scoring ------------------------------------------

async def _step_score(
    client, diff_result: Dict[str, Any], map_result: Dict[str, Any],
    cb: ProgressCallback,
) -> Dict[str, Any]:
    """Use LLM to assign severity and risk scores to each change."""
    await _emit(cb, {"step": "score", "status": "running",
                     "message": "Scoring severity and risk for each change..."})

    changes = diff_result.get("changes", [])
    mappings = map_result.get("mappings", [])

    prompt = f"""You are a regulatory risk analyst. Score the severity of each regulatory change
based on the change itself AND how many/which rules it affects.

Severity levels:
- **breaking**: Mandatory compliance change, requires immediate rule updates. Keywords: must, shall, required, prohibited.
- **material**: Significant change affecting thresholds, eligibility, processes. Needs review and likely updates.
- **cosmetic**: Minor wording, formatting, or clarification. Rules may need minor or no updates.

Return JSON:
{{
  "scored_changes": [
    {{
      "change_id": "C1",
      "severity": "breaking|material|cosmetic",
      "risk_score": 0.0-1.0,
      "confidence": 0.0-1.0,
      "rationale": "brief explanation of severity assignment",
      "urgency": "immediate|short-term|routine",
      "affected_rule_count": 5
    }}
  ],
  "severity_distribution": {{
    "breaking": 2,
    "material": 5,
    "cosmetic": 3
  }},
  "overall_risk_level": "critical|high|medium|low"
}}

=== CHANGES ===
{json.dumps(changes[:40], indent=1)}

=== RULE MAPPINGS ===
{json.dumps(mappings[:40], indent=1)}"""

    response = client.get_text_response(
        messages=[
            {"role": "system", "content": "You are a regulatory risk scoring expert. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    result = _safe_json_parse(response)
    dist = result.get("severity_distribution", {})
    await _emit(cb, {"step": "score", "status": "completed",
                     "message": f"Scored: {dist.get('breaking',0)} breaking, "
                                f"{dist.get('material',0)} material, {dist.get('cosmetic',0)} cosmetic — "
                                f"overall risk: {result.get('overall_risk_level','unknown')}",
                     "data": {"distribution": dist,
                              "overall_risk": result.get("overall_risk_level", "")}})
    return result


# ── Step 5: Executive Summary & Recommendations ------------------------------

async def _step_summarize(
    client, parsed: Dict[str, Any], diff_result: Dict[str, Any],
    score_result: Dict[str, Any], map_result: Dict[str, Any],
    graph_name: str, cb: ProgressCallback,
) -> Dict[str, Any]:
    """Use LLM to generate executive summary, recommendations, and action items."""
    await _emit(cb, {"step": "summarize", "status": "running",
                     "message": "Generating executive summary and recommendations..."})

    doc_summary = parsed.get("document_summary", {})
    scored = score_result.get("scored_changes", [])
    dist = score_result.get("severity_distribution", {})
    total_affected = map_result.get("total_affected_rules", 0)

    prompt = f"""You are a Chief Compliance Officer reviewing a regulatory change impact analysis.
Generate an executive summary and actionable recommendations.

Context:
- Graph: {graph_name}
- Domain: {doc_summary.get('regulatory_domain', 'general')}
- Total changes: {len(scored)}
- Severity: {dist.get('breaking',0)} breaking, {dist.get('material',0)} material, {dist.get('cosmetic',0)} cosmetic
- Rules affected: {total_affected}
- Overall risk: {score_result.get('overall_risk_level', 'unknown')}

Return JSON:
{{
  "executive_summary": "2-3 paragraph summary suitable for senior management",
  "headline": "one-line headline (max 120 chars)",
  "key_findings": [
    "finding 1",
    "finding 2"
  ],
  "recommendations": [
    {{
      "priority": "P1|P2|P3",
      "action": "specific action to take",
      "owner": "suggested responsible team/role",
      "timeline": "immediate|1-2 weeks|1 month|quarterly"
    }}
  ],
  "risk_assessment": {{
    "overall_risk": "critical|high|medium|low",
    "impact_percentage": {round(total_affected / max(1, 1) * 100, 1)},
    "requires_board_review": true/false,
    "regulatory_deadline_risk": true/false
  }}
}}

=== SCORED CHANGES (top 20) ===
{json.dumps(scored[:20], indent=1)}"""

    response = client.get_text_response(
        messages=[
            {"role": "system", "content": "You are an expert Chief Compliance Officer. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    result = _safe_json_parse(response)
    rec_count = len(result.get("recommendations", []))
    await _emit(cb, {"step": "summarize", "status": "completed",
                     "message": f"Generated {rec_count} recommendations — {result.get('headline', '')}",
                     "data": {"headline": result.get("headline", ""),
                              "recommendation_count": rec_count,
                              "risk_assessment": result.get("risk_assessment", {})}})
    return result


# ── Orchestrator — full agentic workflow --------------------------------------

async def run_agentic_analysis(
    analysis_id: str,
    old_text: str,
    new_text: str,
    graph_name: str,
    provider: str = "openai",
    progress_cb: ProgressCallback = None,
) -> dict:
    """
    Execute the full 5-step agentic impact analysis.

    Each step uses the LLM for semantic understanding, not just keyword matching.
    Progress is streamed via progress_cb.
    """
    try:
        impact_store.update_analysis(analysis_id, status="running")
        await _emit(progress_cb, {
            "step": "init", "status": "running",
            "message": "Initializing agentic impact analysis...",
            "steps": STEPS,
        })

        # Load graph rules
        graph_data = graph_service.get_graph_data(graph_name, provider)
        if not graph_data:
            impact_store.update_analysis(
                analysis_id, status="failed",
                error=f"Graph '{graph_name}' not found",
            )
            await _emit(progress_cb, {"step": "init", "status": "failed",
                                       "message": f"Graph '{graph_name}' not found"})
            return impact_store.get_analysis(analysis_id)

        rules = graph_data.get("business_rules", [])
        if not rules:
            for et in graph_data.get("entity_types", {}).values():
                rules.extend(r for r in et.get("business_rules", []) if isinstance(r, dict))

        await _emit(progress_cb, {
            "step": "init", "status": "completed",
            "message": f"Loaded {len(rules)} rules from '{graph_name}'",
        })

        # Create LLM client
        client, config = _create_client(provider)

        # Step 1: Parse documents
        parsed = await _step_parse(client, old_text, new_text, progress_cb)

        # Step 2: Semantic diff
        diff_result = await _step_diff(client, parsed, progress_cb)

        # Step 3: Map to rules
        map_result = await _step_map(client, diff_result, rules, graph_name, progress_cb)

        # Step 4: Score severity
        score_result = await _step_score(client, diff_result, map_result, progress_cb)

        # Step 5: Executive summary
        summary_result = await _step_summarize(
            client, parsed, diff_result, score_result, map_result, graph_name, progress_cb
        )

        # ── Persist results ──────────────────────────────────────────────
        changes = diff_result.get("changes", [])
        scored = {s["change_id"]: s for s in score_result.get("scored_changes", [])}
        mappings = {m["change_id"]: m for m in map_result.get("mappings", [])}

        all_affected_rule_ids = set()
        severity_counts = {"breaking": 0, "material": 0, "cosmetic": 0}

        for change in changes:
            cid = change.get("change_id", "")
            score_info = scored.get(cid, {})
            map_info = mappings.get(cid, {})

            severity = score_info.get("severity", "cosmetic")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

            affected_rules = []
            for ar in map_info.get("affected_rules", []):
                all_affected_rule_ids.add(ar.get("rule_id", ""))
                affected_rules.append({
                    "rule_id": ar.get("rule_id", ""),
                    "rule_name": ar.get("rule_name", ""),
                    "rule_type": ar.get("rule_type", ""),
                    "risk_level": ar.get("risk_level", ""),
                    "relevance": ar.get("relevance", ""),
                    "reasoning": ar.get("reasoning", ""),
                    "match_score": 0.9 if ar.get("relevance") == "high" else 0.6 if ar.get("relevance") == "medium" else 0.3,
                    "matching_terms": [],
                })

            recommendation = score_info.get("rationale", "")
            if severity == "breaking":
                recommendation = f"URGENT: {recommendation}"

            impact_store.add_impact_item(
                analysis_id=analysis_id,
                change_type=change.get("change_type", "modified"),
                provision_text=change.get("description", change.get("new_text", ""))[:2000],
                severity=severity,
                affected_rules=affected_rules,
                description=change.get("semantic_impact", change.get("description", "")),
                recommendation=recommendation,
            )

        stats = {
            "total_changes": len(changes),
            "added_count": sum(1 for c in changes if c.get("change_type") == "added"),
            "removed_count": sum(1 for c in changes if c.get("change_type") == "removed"),
            "modified_count": sum(1 for c in changes if c.get("change_type") == "modified"),
            "total_rules_in_graph": len(rules),
            "affected_rules_count": len(all_affected_rule_ids),
            "severity_breaking": severity_counts.get("breaking", 0),
            "severity_material": severity_counts.get("material", 0),
            "severity_cosmetic": severity_counts.get("cosmetic", 0),
            "impact_percentage": round(
                len(all_affected_rule_ids) / max(len(rules), 1) * 100, 1
            ),
        }

        summary = {
            "headline": summary_result.get("headline", ""),
            "executive_summary": summary_result.get("executive_summary", ""),
            "key_findings": summary_result.get("key_findings", []),
            "recommendations": summary_result.get("recommendations", []),
            "risk_assessment": summary_result.get("risk_assessment", {}),
            "old_provision_count": len(parsed.get("old_provisions", [])),
            "new_provision_count": len(parsed.get("new_provisions", [])),
        }

        impact_store.update_analysis(
            analysis_id,
            status="completed",
            summary=summary,
            stats=stats,
            finished_at=impact_store._now(),
        )

        await _emit(progress_cb, {
            "step": "done", "status": "completed",
            "message": summary_result.get("headline", "Analysis complete"),
            "data": {"stats": stats, "summary": summary},
        })

        return impact_store.get_analysis(analysis_id)

    except Exception as exc:
        tb = traceback.format_exc().replace("\n", " | ")
        impact_store.update_analysis(
            analysis_id,
            status="failed",
            error=str(exc),
            finished_at=impact_store._now(),
        )
        await _emit(progress_cb, {
            "step": "error", "status": "failed",
            "message": f"Analysis failed: {exc}",
        })
        return impact_store.get_analysis(analysis_id)


# ── Sync wrappers for asyncio.to_thread usage --------------------------------

async def _step_parse_sync(client, old_text, new_text, cb):
    return await _step_parse(client, old_text, new_text, cb)

async def _step_diff_sync(client, parsed, cb):
    return await _step_diff(client, parsed, cb)

async def _step_map_sync(client, diff_result, rules, graph_name, cb):
    return await _step_map(client, diff_result, rules, graph_name, cb)

async def _step_score_sync(client, diff_result, map_result, cb):
    return await _step_score(client, diff_result, map_result, cb)

async def _step_summarize_sync(client, parsed, diff_result, score_result, map_result, graph_name, cb):
    return await _step_summarize(client, parsed, diff_result, score_result, map_result, graph_name, cb)
