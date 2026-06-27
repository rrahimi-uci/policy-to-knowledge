#!/usr/bin/env python3
"""
JTBD-to-Knowledge-Graph Rule Mapper Agent

Maps each Job-To-Be-Done (JTBD) from a JTBD set to relevant business rules
in a Fannie Mae compliance knowledge graph using GPT-5.2 semantic analysis.

Generates a professional HTML gap analysis report.

Author: Reza Rahimi
Date: June 2026
"""

import json
import sys
import os
import re
import html as html_module
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import create_llm_client

# ─── Constants ───────────────────────────────────────────────────────
BATCH_SIZE = 5           # JTBDs per LLM call
MAX_WORKERS = 10         # Parallel LLM calls
MODEL = "gpt-5.2"
REASONING_EFFORT = "medium"
FORCED_MATCH_MAX_WORKERS = 6
FORCED_CANDIDATE_COUNT = 30

STOP_WORDS = {
    "the", "and", "for", "that", "with", "this", "from", "are", "was", "were",
    "have", "has", "had", "into", "onto", "under", "over", "must", "shall",
    "such", "than", "then", "when", "where", "which", "while", "also", "only",
    "loan", "loans", "rule", "rules", "fannie", "mae", "jtbd", "base", "version",
    "step", "steps", "review", "identify", "validate", "required", "information",
}

SECTION_HINTS = {
    "appraisal review": {"appraisal", "property", "value", "valuation", "comparable", "field", "form"},
    "asset assessment": {"asset", "reserve", "funds", "gift", "donation", "depository", "cash"},
    "credit review & analysis": {"credit", "score", "report", "tradeline", "du", "liability"},
    "liabilities assessment": {"liability", "debt", "obligation", "payment", "dti", "student"},
    "income stability & sufficiency analysis": {"income", "employment", "wage", "self", "rental", "qualifying"},
    "insurance coverage sufficiency & policy assessment": {"insurance", "coverage", "hazard", "flood", "policy"},
    "loan program eligibility": {"eligibility", "program", "ltv", "cltv", "occupancy", "transaction"},
    "identification requirements": {"borrower", "identity", "citizenship", "residency", "ssn"},
    "title review-0": {"title", "endorsement", "ownership", "lien", "vesting", "policy"},
    "title review-1": {"title", "endorsement", "ownership", "lien", "vesting", "policy"},
    "property tax calculation": {"tax", "property", "assessment", "escrow", "monthly"},
    "compliance and closing": {"closing", "compliance", "poa", "delivery", "disclosure"},
}


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html_module.escape(str(text)) if text else ""


# ─── Data Loading ────────────────────────────────────────────────────

def load_knowledge_graph(kg_path: str) -> Dict:
    with open(kg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jtbds(jtbd_path: str) -> Dict:
    with open(jtbd_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_rule_catalog(kg: Dict) -> List[Dict]:
    """Build a compact catalog of rules for the LLM prompt."""
    catalog = []
    for rule in kg.get("business_rules", []):
        src_ref = rule.get("source_reference", {})
        if isinstance(src_ref, list):
            src_ref = src_ref[0] if src_ref else {}
        elif not isinstance(src_ref, dict):
            src_ref = {}
        catalog.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule.get("rule_name", ""),
            "rule_type": rule.get("rule_type", ""),
            "description": rule.get("description", "")[:500],
            "conditions": (rule.get("conditions") or "")[:200],
            "entity_type": rule.get("entity_type", ""),
            "source_reference": src_ref.get("section_id", ""),
        })
    return catalog


def get_jtbd_text(jtbd: Dict) -> str:
    """Extract the effective requirement text for a JTBD (COMMON + FNMA overlay)."""
    common_text = ""
    fnma_text = ""
    for req in jtbd.get("requirements", []):
        inv = req.get("investor", "")
        txt = req.get("requirement_text", "")
        if inv == "COMMON" and txt and txt != "NO_CHANGE":
            common_text = txt
        elif inv == "FNMA" and txt and txt != "NO_CHANGE":
            fnma_text = txt
    combined = common_text
    if fnma_text:
        combined += "\n\n--- FNMA OVERLAY ---\n" + fnma_text
    # Truncate to keep within token limits
    return combined[:3000]


def _source_reference_dict(rule: Dict) -> Dict:
    """Normalize source_reference to a dict."""
    src_ref = rule.get("source_reference", {})
    if isinstance(src_ref, list):
        return src_ref[0] if src_ref else {}
    if isinstance(src_ref, dict):
        return src_ref
    return {}


def _normalize_tokens(text: str) -> List[str]:
    """Tokenize text for lexical candidate retrieval."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return [tok for tok in cleaned.split() if len(tok) > 2 and tok not in STOP_WORDS]


def _rule_search_text(rule: Dict) -> str:
    """Build rule text used for lexical retrieval and fallback ranking."""
    src_ref = _source_reference_dict(rule)
    return " ".join([
        rule.get("rule_id", ""),
        rule.get("rule_name", ""),
        rule.get("rule_type", ""),
        rule.get("description", "") or "",
        rule.get("conditions", "") or "",
        src_ref.get("section_id", ""),
        src_ref.get("source_text", "")[:300],
    ])


def _safe_float(value: Any, default: float = 0.5) -> float:
    """Convert a value to float with bounds [0,1]."""
    try:
        val = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, val))


def rank_candidate_rules(jtbd: Dict, rules: List[Dict], top_n: int = FORCED_CANDIDATE_COUNT) -> List[Dict]:
    """Rank KG rules by lexical similarity to a JTBD for fallback matching."""
    section = (jtbd.get("section", "") or "").lower()
    section_hints = SECTION_HINTS.get(section, set())
    jtbd_blob = " ".join([
        jtbd.get("mnemonic", ""),
        jtbd.get("skill", ""),
        jtbd.get("section", ""),
        get_jtbd_text(jtbd),
    ])
    jtbd_tokens = set(_normalize_tokens(jtbd_blob))

    ranked = []
    for rule in rules:
        rule_text = _rule_search_text(rule)
        rule_tokens = set(_normalize_tokens(rule_text))
        overlap = jtbd_tokens.intersection(rule_tokens)
        union = jtbd_tokens.union(rule_tokens)
        containment = len(overlap) / max(1, len(jtbd_tokens))
        jaccard = len(overlap) / max(1, len(union))
        score = 0.7 * containment + 0.3 * jaccard

        lower_rule_text = rule_text.lower()
        if section_hints and any(h in lower_rule_text for h in section_hints):
            score += 0.08

        ranked.append((score, rule))

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:max(1, top_n)]

    candidates = []
    for score, rule in top:
        src_ref = _source_reference_dict(rule)
        candidates.append({
            "rule_id": rule.get("rule_id", ""),
            "rule_name": rule.get("rule_name", ""),
            "rule_type": rule.get("rule_type", ""),
            "description": (rule.get("description", "") or "")[:300],
            "conditions": (rule.get("conditions", "") or "")[:200],
            "source_reference": src_ref.get("section_id", ""),
            "lexical_score": round(score, 4),
        })
    return candidates


def normalize_mappings(mappings: List[Dict], jtbds: List[Dict], rules_by_id: Dict[str, Dict]) -> List[Dict]:
    """Normalize mapping shape, enforce one mapping per JTBD, and clean rule IDs."""
    mapping_by_mnemonic: Dict[str, Dict] = {}
    for m in mappings:
        mnemonic = m.get("jtbd_mnemonic", "")
        if mnemonic:
            mapping_by_mnemonic[mnemonic] = m

    normalized = []
    for jtbd in jtbds:
        mnemonic = jtbd.get("mnemonic", "")
        raw = mapping_by_mnemonic.get(
            mnemonic,
            {
                "jtbd_mnemonic": mnemonic,
                "matched_rules": [],
                "coverage_assessment": "NONE",
                "gap_notes": "No mapping returned by model.",
            },
        )

        seen = set()
        cleaned_rules = []
        for rm in raw.get("matched_rules", []) or []:
            rid = rm.get("rule_id", "")
            if not rid or rid not in rules_by_id or rid in seen:
                continue
            seen.add(rid)
            cleaned_rules.append({
                "rule_id": rid,
                "rule_name": rm.get("rule_name") or rules_by_id[rid].get("rule_name", ""),
                "confidence": _safe_float(rm.get("confidence", 0.6), default=0.6),
                "reasoning": rm.get("reasoning", ""),
            })

        cleaned_rules.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
        coverage = raw.get("coverage_assessment", "PARTIAL" if cleaned_rules else "NONE")
        if cleaned_rules and coverage == "NONE":
            coverage = "PARTIAL"

        normalized.append({
            "jtbd_mnemonic": mnemonic,
            "matched_rules": cleaned_rules,
            "coverage_assessment": coverage,
            "gap_notes": raw.get("gap_notes", ""),
        })

    return normalized


def build_forced_mapping_prompt(jtbd: Dict, candidates: List[Dict]) -> List[Dict]:
    """Build a strict second-pass prompt that guarantees at least one mapped rule."""
    system_msg = """You are a mortgage compliance expert.

Your task: map ONE JTBD to the best matching Fannie Mae rules from the provided candidate list.

Rules:
1) You MUST return at least one matched rule.
2) You MUST only use rule_id values from the provided candidate list.
3) If no direct rule exists, choose the closest proxy rule and explain the gap clearly.
4) Use confidence 0.35-0.95.

Return ONLY valid JSON object:
{
  "jtbd_mnemonic": "...",
  "matched_rules": [
    {
      "rule_id": "BR_...",
      "rule_name": "...",
      "confidence": 0.42,
      "reasoning": "..."
    }
  ],
  "coverage_assessment": "FULL|PARTIAL",
  "gap_notes": "..."
}
"""

    user_msg = f"""JTBD to map:
{json.dumps({
    'mnemonic': jtbd.get('mnemonic', ''),
    'skill': jtbd.get('skill', ''),
    'section': jtbd.get('section', ''),
    'requirement_text': get_jtbd_text(jtbd)[:2200],
}, indent=2)}

Candidate rules (ranked):
{json.dumps(candidates, indent=2)}
"""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def deterministic_fallback_mapping(jtbd: Dict, candidates: List[Dict]) -> Dict:
    """Create a safe fallback mapping when LLM forced matching fails."""
    best = candidates[0] if candidates else {
        "rule_id": "",
        "rule_name": "",
    }
    matched_rules = []
    if best.get("rule_id"):
        matched_rules = [{
            "rule_id": best.get("rule_id", ""),
            "rule_name": best.get("rule_name", ""),
            "confidence": 0.35,
            "reasoning": "Lexical nearest-neighbor fallback mapping used to ensure JTBD-to-rule traceability.",
        }]

    return {
        "jtbd_mnemonic": jtbd.get("mnemonic", ""),
        "matched_rules": matched_rules,
        "coverage_assessment": "PARTIAL" if matched_rules else "NONE",
        "gap_notes": "No explicit direct rule found in first pass; fallback best-match mapping applied.",
    }


def force_map_single_jtbd(llm_client, jtbd: Dict, candidates: List[Dict], rules_by_id: Dict[str, Dict]) -> Dict:
    """Second-pass LLM mapping for a single previously unmatched JTBD."""
    messages = build_forced_mapping_prompt(jtbd, candidates)
    candidate_ids = {c.get("rule_id", "") for c in candidates}
    try:
        response = llm_client.chat_completion(
            messages=messages,
            max_tokens=4096,
            response_format={"type": "json_object"},
            reasoning_effort=REASONING_EFFORT,
        )
        content = response.choices[0].message.content or ""
        parsed = parse_llm_response(content, expected_count=1)
        if not parsed:
            return deterministic_fallback_mapping(jtbd, candidates)

        mapping = parsed[0] if isinstance(parsed[0], dict) else {}
        mapping["jtbd_mnemonic"] = jtbd.get("mnemonic", "")

        cleaned = []
        seen = set()
        for rm in mapping.get("matched_rules", []) or []:
            rid = rm.get("rule_id", "")
            if rid in seen or rid not in candidate_ids or rid not in rules_by_id:
                continue
            seen.add(rid)
            cleaned.append({
                "rule_id": rid,
                "rule_name": rm.get("rule_name") or rules_by_id[rid].get("rule_name", ""),
                "confidence": _safe_float(rm.get("confidence", 0.5), default=0.5),
                "reasoning": rm.get("reasoning", ""),
            })

        if not cleaned:
            return deterministic_fallback_mapping(jtbd, candidates)

        cleaned.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
        return {
            "jtbd_mnemonic": jtbd.get("mnemonic", ""),
            "matched_rules": cleaned,
            "coverage_assessment": mapping.get("coverage_assessment", "PARTIAL") or "PARTIAL",
            "gap_notes": mapping.get("gap_notes", ""),
        }
    except Exception:
        return deterministic_fallback_mapping(jtbd, candidates)


def ensure_complete_mappings(
    mappings: List[Dict],
    jtbds: List[Dict],
    kg: Dict,
    max_workers: int = FORCED_MATCH_MAX_WORKERS,
) -> List[Dict]:
    """Guarantee every JTBD has at least one mapped rule using second-pass matching."""
    rules = kg.get("business_rules", [])
    rules_by_id = {r.get("rule_id", ""): r for r in rules if r.get("rule_id")}
    normalized = normalize_mappings(mappings, jtbds, rules_by_id)

    mapping_by_mnemonic = {m.get("jtbd_mnemonic", ""): m for m in normalized}
    unmatched_jtbds = [j for j in jtbds if not mapping_by_mnemonic.get(j.get("mnemonic", ""), {}).get("matched_rules")]

    if not unmatched_jtbds:
        return normalized

    print(f"  Complete-match pass: forcing best match for {len(unmatched_jtbds)} unmatched JTBDs")
    llm_client = create_llm_client(model=MODEL, timeout=300)
    progress_lock = threading.Lock()
    progress_counter = [0]

    def _work(jtbd: Dict) -> Tuple[str, Dict]:
        candidates = rank_candidate_rules(jtbd, rules, top_n=FORCED_CANDIDATE_COUNT)
        forced = force_map_single_jtbd(llm_client, jtbd, candidates, rules_by_id)
        with progress_lock:
            progress_counter[0] += 1
            print(
                f"  ↺ Complete-match {progress_counter[0]}/{len(unmatched_jtbds)}: {jtbd.get('mnemonic', '')}",
                flush=True,
            )
        return jtbd.get("mnemonic", ""), forced

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = [pool.submit(_work, j) for j in unmatched_jtbds]
        for fut in as_completed(futures):
            mnemonic, forced_mapping = fut.result()
            mapping_by_mnemonic[mnemonic] = forced_mapping

    # Return in original JTBD order
    return [mapping_by_mnemonic[j.get("mnemonic", "")] for j in jtbds]


# ─── LLM Mapping ────────────────────────────────────────────────────

def build_mapping_prompt(jtbd_batch: List[Dict], rule_catalog_json: str) -> List[Dict]:
    """Build the prompt messages for mapping a batch of JTBDs to KG rules."""
    system_msg = """You are a mortgage compliance expert. Your task is to map Jobs-To-Be-Done (JTBDs) 
to Fannie Mae Knowledge Graph business rules.

For each JTBD, identify ALL rules from the Knowledge Graph that are relevant to that job.
A rule is relevant if:
- It directly governs the compliance check described in the JTBD
- It defines eligibility criteria, constraints, calculations, or validations that the JTBD must enforce
- It specifies documentation or process requirements that the JTBD covers
- If no direct rule exists, choose the closest proxy rule(s) and explain the remaining gap

Return ONLY valid JSON. The response must be a JSON object with a "mappings" key containing an array of objects, one per JTBD in the batch:
{
  "mappings": [
    {
      "jtbd_mnemonic": "...",
      "matched_rules": [
        {
          "rule_id": "BR_...",
          "rule_name": "...",
          "confidence": 0.95,
          "reasoning": "Brief explanation of why this rule maps to this JTBD"
        }
      ],
      "coverage_assessment": "FULL|PARTIAL|NONE",
      "gap_notes": "Any compliance gaps or areas where KG rules don't fully cover the JTBD"
    }
  ]
}

IMPORTANT: You MUST return one mapping object for EACH JTBD in the batch. Do not skip or merge JTBDs.
IMPORTANT: Prefer at least one matched rule per JTBD. Use proxy matches with lower confidence when direct matches are unavailable.

Confidence scoring:
- 0.9-1.0: Direct, explicit match between JTBD requirements and rule
- 0.7-0.89: Strong thematic match with clear relevance
- 0.5-0.69: Partial or indirect relevance
- 0.35-0.49: Weak proxy mapping (use only when no direct match exists)

Be thorough but precise. Include all genuinely relevant rules but avoid false positives."""

    jtbd_descriptions = []
    for jtbd in jtbd_batch:
        jtbd_text = get_jtbd_text(jtbd)
        jtbd_descriptions.append({
            "mnemonic": jtbd.get("mnemonic", "UNKNOWN"),
            "skill": jtbd.get("skill", ""),
            "section": jtbd.get("section", ""),
            "requirement_text": jtbd_text[:2000],
        })

    user_msg = f"""Map the following JTBDs to the Knowledge Graph rules.

=== JTBD BATCH ===
{json.dumps(jtbd_descriptions, indent=2)}

=== KNOWLEDGE GRAPH RULES CATALOG ===
{rule_catalog_json}

Return the mapping as a JSON array."""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def parse_llm_response(response_text: str, expected_count: int = 0) -> List[Dict]:
    """Parse the LLM response, handling potential markdown fences and wrapper objects."""
    text = response_text.strip()
    # Remove markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    parsed = json.loads(text)

    # If it's already a list, return it
    if isinstance(parsed, list):
        return parsed

    # If it's a dict, look for the array inside
    if isinstance(parsed, dict):
        # Check common wrapper keys
        for key in ("mappings", "results", "jtbd_mappings", "data", "mapping",
                     "jtbd_mapping", "response", "items"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        # If only one key and it's a list, use it
        keys = list(parsed.keys())
        if len(keys) == 1 and isinstance(parsed[keys[0]], list):
            return parsed[keys[0]]
        # If it looks like a single mapping item (has jtbd_mnemonic), wrap it
        if "jtbd_mnemonic" in parsed:
            return [parsed]

    return [parsed] if isinstance(parsed, dict) else []


def map_batch(
    llm_client,
    jtbd_batch: List[Dict],
    rule_catalog_json: str,
    batch_idx: int,
    total_batches: int,
    progress_lock: threading.Lock,
    progress_counter: List[int],
) -> List[Dict]:
    """Map a single batch of JTBDs to KG rules via LLM."""
    messages = build_mapping_prompt(jtbd_batch, rule_catalog_json)
    try:
        response = llm_client.chat_completion(
            messages=messages,
            max_tokens=8192,
            response_format={"type": "json_object"},
            reasoning_effort=REASONING_EFFORT,
        )
        content = response.choices[0].message.content or ""
        results = parse_llm_response(content, expected_count=len(jtbd_batch))

        # Rebuild output in batch JTBD order so each JTBD always has one entry.
        expected_mnemonics = [j.get("mnemonic", "UNKNOWN") for j in jtbd_batch]
        result_by_mnemonic: Dict[str, Dict] = {}
        for r in results:
            if not isinstance(r, dict):
                continue
            mn = r.get("jtbd_mnemonic", "")
            if mn:
                result_by_mnemonic[mn] = r

        ordered_results = []
        for mn in expected_mnemonics:
            if mn in result_by_mnemonic:
                ordered_results.append(result_by_mnemonic[mn])
            else:
                ordered_results.append({
                    "jtbd_mnemonic": mn,
                    "matched_rules": [],
                    "coverage_assessment": "NONE",
                    "gap_notes": "No mapping returned by primary batch response.",
                })

        # Validate we got the right number of results
        if len(result_by_mnemonic) < len(jtbd_batch):
            print(
                f"  ⚠ Batch {batch_idx + 1}: expected {len(jtbd_batch)} mappings, got {len(result_by_mnemonic)}",
                file=sys.stderr, flush=True,
            )

        with progress_lock:
            progress_counter[0] += len(jtbd_batch)
            print(
                f"  ✓ Batch {batch_idx + 1}/{total_batches} done "
                f"({progress_counter[0]} JTBDs mapped)",
                flush=True,
            )
        return ordered_results
    except Exception as exc:
        print(
            f"  ✗ Batch {batch_idx + 1}/{total_batches} failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        # Return empty mappings for each JTBD in the failed batch
        return [
            {
                "jtbd_mnemonic": j.get("mnemonic", "UNKNOWN"),
                "matched_rules": [],
                "coverage_assessment": "ERROR",
                "gap_notes": f"LLM call failed: {exc}",
            }
            for j in jtbd_batch
        ]


def run_mapping(jtbds: List[Dict], kg: Dict, batch_size: int = BATCH_SIZE, max_workers: int = MAX_WORKERS) -> List[Dict]:
    """Run the full mapping pipeline."""
    rule_catalog = build_rule_catalog(kg)
    rule_catalog_json = json.dumps(rule_catalog, indent=1)

    print(f"  Rule catalog: {len(rule_catalog)} rules, {len(rule_catalog_json)} chars")

    # If the catalog is too large, chunk rules and do two-pass
    # For ~391 rules with truncated descriptions, it should fit within context
    llm_client = create_llm_client(model=MODEL, timeout=600)

    # Split JTBDs into batches
    batches = []
    for i in range(0, len(jtbds), batch_size):
        batches.append(jtbds[i : i + batch_size])

    print(f"  Processing {len(jtbds)} JTBDs in {len(batches)} batches "
          f"({batch_size}/batch, {max_workers} workers)")

    all_results = [None] * len(batches)
    progress_lock = threading.Lock()
    progress_counter = [0]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for idx, batch in enumerate(batches):
            fut = pool.submit(
                map_batch,
                llm_client,
                batch,
                rule_catalog_json,
                idx,
                len(batches),
                progress_lock,
                progress_counter,
            )
            futures[fut] = idx

        for fut in as_completed(futures):
            idx = futures[fut]
            all_results[idx] = fut.result()

    # Flatten
    flat = []
    for batch_result in all_results:
        if batch_result:
            flat.extend(batch_result)
    return flat


# ─── Analysis ────────────────────────────────────────────────────────

def analyze_results(
    mappings: List[Dict], jtbds: List[Dict], kg: Dict
) -> Dict:
    """Analyze mapping results to compute statistics."""
    all_rule_ids = {r["rule_id"] for r in kg.get("business_rules", [])}
    rules_by_id = {r["rule_id"]: r for r in kg.get("business_rules", [])}

    # Build mnemonic -> JTBD lookup
    jtbd_by_mnemonic = {j["mnemonic"]: j for j in jtbds}

    # Merge mappings with JTBD metadata
    used_rule_ids = set()
    jtbd_with_rules = 0
    jtbd_without_rules = 0
    section_mappings: Dict[str, List[Dict]] = {}

    for m in mappings:
        mnemonic = m.get("jtbd_mnemonic", "")
        jtbd = jtbd_by_mnemonic.get(mnemonic, {})
        section = jtbd.get("section", "Other")
        matched = m.get("matched_rules", [])

        if matched:
            jtbd_with_rules += 1
        else:
            jtbd_without_rules += 1

        for rule_match in matched:
            used_rule_ids.add(rule_match.get("rule_id", ""))

        entry = {
            "mnemonic": mnemonic,
            "skill": jtbd.get("skill", mnemonic),
            "section": section,
            "coverage": m.get("coverage_assessment", "NONE"),
            "gap_notes": m.get("gap_notes", ""),
            "matched_rules": matched,
        }
        section_mappings.setdefault(section, []).append(entry)

    unused_rule_ids = all_rule_ids - used_rule_ids

    # Categorize unused rules
    _rule_type_names = {
        "CONSTRAINT", "PROCESS", "PROHIBITION", "VALIDATION", "ELIGIBILITY",
        "DOCUMENTATION", "EXCEPTION", "CALCULATION", "COMPLIANCE", "DEFINITION",
    }
    unused_rules_by_category: Dict[str, List[Dict]] = {}
    for rid in unused_rule_ids:
        rule = rules_by_id.get(rid, {})
        # Extract category from rule_id: BR_CATEGORY_RULETYPE_NNN_NNN
        parts = rid.split("_")
        cat_parts = []
        for p in parts[1:]:  # skip 'BR'
            if p.upper() in _rule_type_names:
                break
            cat_parts.append(p)
        cat = "_".join(cat_parts) if cat_parts else "UNKNOWN"
        unused_rules_by_category.setdefault(cat, []).append(rule)

    # Determine critical categories (those relevant to underwriting/origination)
    critical_keywords = {
        "BORROWER", "CREDIT", "INCOME", "MORTGAGE_LOAN", "APPRAISAL",
        "PROPERTY", "UNDERWRITING", "UNDERWRITES", "LOAN_APPLICATION",
        "LOAN_PROGRAM", "DESKTOP_UNDERWRITER", "PROMISSORY_NOTE",
    }
    critical_categories = {}
    non_critical_categories = {}
    for cat, rules in sorted(unused_rules_by_category.items(), key=lambda x: -len(x[1])):
        cat_upper = cat.upper()
        is_critical = any(kw in cat_upper for kw in critical_keywords)
        if is_critical:
            critical_categories[cat] = rules
        else:
            non_critical_categories[cat] = rules

    total_critical = sum(len(v) for v in critical_categories.values())
    total_non_critical = sum(len(v) for v in non_critical_categories.values())

    return {
        "total_jtbds": len(jtbds),
        "jtbd_with_rules": jtbd_with_rules,
        "jtbd_without_rules": jtbd_without_rules,
        "total_kg_rules": len(all_rule_ids),
        "used_rules": len(used_rule_ids),
        "unused_rules": len(unused_rule_ids),
        "critical_categories": critical_categories,
        "non_critical_categories": non_critical_categories,
        "total_critical": total_critical,
        "total_non_critical": total_non_critical,
        "section_mappings": section_mappings,
        "rules_by_id": rules_by_id,
    }


# ─── HTML Report Generator ──────────────────────────────────────────

def _section_id(section: str) -> str:
    """Turn a section name into a safe HTML anchor id."""
    return "section-" + re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")


def _cat_id(cat: str) -> str:
    return "cat-" + re.sub(r"[^a-zA-Z0-9]+", "", cat)


def generate_html_report(analysis: Dict, jtbd_title: str) -> str:
    """Generate the full HTML report."""

    total_jtbds = analysis["total_jtbds"]
    jtbd_with = analysis["jtbd_with_rules"]
    jtbd_without = analysis["jtbd_without_rules"]
    total_kg = analysis["total_kg_rules"]
    used = analysis["used_rules"]
    unused = analysis["unused_rules"]
    critical_cats = analysis["critical_categories"]
    non_critical_cats = analysis["non_critical_categories"]
    total_critical = analysis["total_critical"]
    section_mappings = analysis["section_mappings"]
    rules_by_id = analysis["rules_by_id"]

    pct_jtbd_covered = round(jtbd_with / total_jtbds * 100, 1) if total_jtbds else 0
    pct_kg_used = round(used / total_kg * 100, 1) if total_kg else 0
    pct_critical = round(total_critical / total_kg * 100, 1) if total_kg else 0
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Build nav dropdown items for sections ──
    section_nav = ""
    for section in sorted(section_mappings.keys()):
        sid = _section_id(section)
        section_nav += f'                        <a href="#{sid}">{_esc(section)}</a>\n'

    # ── Build nav dropdown items for critical categories ──
    critical_nav = ""
    for cat in sorted(critical_cats.keys(), key=lambda c: -len(critical_cats[c])):
        cid = _cat_id(cat)
        cnt = len(critical_cats[cat])
        critical_nav += f'                        <a href="#{cid}" class="critical-item">{_esc(cat)} ({cnt} rules)</a>\n'

    non_critical_nav = ""
    for cat in sorted(non_critical_cats.keys(), key=lambda c: -len(non_critical_cats[c])):
        cid = _cat_id(cat)
        cnt = len(non_critical_cats[cat])
        non_critical_nav += f'                        <a href="#{cid}">{_esc(cat)} ({cnt} rules)</a>\n'

    # ── Build JTBD mapping sections ──
    mapping_html = ""
    for section in sorted(section_mappings.keys()):
        sid = _section_id(section)
        entries = section_mappings[section]
        mapping_html += f'\n    <h3 id="{sid}">{_esc(section)}</h3>\n'

        for entry in entries:
            mnemonic = _esc(entry["mnemonic"])
            skill = _esc(entry["skill"])
            gap = _esc(entry.get("gap_notes", ""))
            matched = entry.get("matched_rules", [])

            mapping_html += f'''
    <div class="rule-card">
        <div class="rule-id">{mnemonic}: {skill}</div>
'''
            if gap:
                mapping_html += f'        <div class="rule-detail"><span class="rule-label">Gap Notes:</span> <span class="rule-value">{gap}</span></div>\n'

            if matched:
                mapping_html += '        <div class="rule-detail"><span class="rule-label">Mapped KG Rules:</span></div>\n        <ul>\n'
                for rm in matched:
                    rid = _esc(rm.get("rule_id", ""))
                    rname = _esc(rm.get("rule_name", ""))
                    conf = rm.get("confidence", 0)
                    reasoning = _esc(rm.get("reasoning", ""))
                    # Get full rule details from KG
                    full_rule = rules_by_id.get(rm.get("rule_id", ""), {})
                    rtype = _esc(full_rule.get("rule_type", ""))
                    rdesc = _esc((full_rule.get("description", "") or "")[:300])
                    src_ref = full_rule.get("source_reference", {})
                    if isinstance(src_ref, list):
                        src_ref = src_ref[0] if src_ref else {}
                    elif not isinstance(src_ref, dict):
                        src_ref = {}
                    ref = _esc(src_ref.get("section_id", ""))

                    conf_color = "#22543d" if conf >= 0.9 else "#744210" if conf >= 0.7 else "#742a2a"
                    mapping_html += f'''            <li>
                <strong>{rid}</strong><br>
                <small>Name: {rname}</small><br>
                <small>Type: <span class="badge badge-type">{rtype}</span> | Confidence: <span style="color:{conf_color};font-weight:bold;">{conf:.0%}</span></small><br>
                <small>Description: {rdesc}</small><br>
                <small>Reasoning: <em>{reasoning}</em></small>
                {f'<br><small>Reference: {ref}</small>' if ref else ''}
            </li>
'''
                mapping_html += "        </ul>\n"
            else:
                mapping_html += '        <p class="no-rules">No matching KG rules found. This JTBD may cover operational/LOS procedures.</p>\n'

            mapping_html += "    </div>\n"

    # ── Build unused rules sections ──
    unused_html = ""

    if critical_cats:
        unused_html += f'\n    <div class="category-header critical">Critical Unused Rules <span class="category-count">{total_critical} rules in {len(critical_cats)} categories</span></div>\n'
        for cat in sorted(critical_cats.keys(), key=lambda c: -len(critical_cats[c])):
            cid = _cat_id(cat)
            rules = critical_cats[cat]
            unused_html += f'\n    <h3 id="{cid}"><span class="badge badge-critical">CRITICAL</span> {_esc(cat)} ({len(rules)} rules)</h3>\n'
            unused_html += '    <table>\n        <tr><th>Rule ID</th><th>Name</th><th>Type</th><th>Description</th></tr>\n'
            for r in rules:
                unused_html += f'        <tr class="critical-row"><td>{_esc(r.get("rule_id",""))}</td><td>{_esc(r.get("rule_name",""))}</td><td><span class="badge badge-type">{_esc(r.get("rule_type",""))}</span></td><td>{_esc((r.get("description","") or "")[:200])}</td></tr>\n'
            unused_html += "    </table>\n"

    if non_critical_cats:
        total_nc = sum(len(v) for v in non_critical_cats.values())
        unused_html += f'\n    <div class="category-header">Non-Critical Unused Rules <span class="category-count">{total_nc} rules in {len(non_critical_cats)} categories</span></div>\n'
        for cat in sorted(non_critical_cats.keys(), key=lambda c: -len(non_critical_cats[c])):
            cid = _cat_id(cat)
            rules = non_critical_cats[cat]
            unused_html += f'\n    <h3 id="{cid}">{_esc(cat)} ({len(rules)} rules)</h3>\n'
            unused_html += '    <table>\n        <tr><th>Rule ID</th><th>Name</th><th>Type</th><th>Description</th></tr>\n'
            for r in rules:
                unused_html += f'        <tr><td>{_esc(r.get("rule_id",""))}</td><td>{_esc(r.get("rule_name",""))}</td><td><span class="badge badge-type">{_esc(r.get("rule_type",""))}</span></td><td>{_esc((r.get("description","") or "")[:200])}</td></tr>\n'
            unused_html += "    </table>\n"

    # ── Critical categories stats table ──
    critical_stats_rows = ""
    for cat in sorted(critical_cats.keys(), key=lambda c: -len(critical_cats[c])):
        cnt = len(critical_cats[cat])
        critical_stats_rows += f'        <tr class="critical-row"><td>{_esc(cat)}</td><td>{cnt}</td><td><span class="badge badge-critical">CRITICAL</span></td></tr>\n'

    # ── Assemble full HTML ──
    report = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JTBD Gap Analysis Using Fannie Mae Knowledge Graph</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6; color: #333;
            max-width: 1200px; margin: 0 auto;
            padding: 80px 20px 20px 20px; background-color: #f5f5f5;
        }}
        h1 {{ color: #1a365d; text-align: center; border-bottom: 3px solid #2c5282; padding-bottom: 15px; margin-bottom: 10px; }}
        .subtitle {{ text-align: center; color: #4a5568; font-size: 1.1em; margin-bottom: 30px; }}
        h2 {{ color: #2c5282; border-left: 4px solid #4299e1; padding-left: 15px; margin-top: 40px; }}
        h3 {{ color: #2d3748; background-color: #e2e8f0; padding: 10px 15px; border-radius: 5px; }}
        .category-header {{
            background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%);
            color: white; padding: 20px 25px; margin: 40px 0 20px 0;
            border-radius: 8px; font-size: 1.5em; font-weight: bold;
        }}
        .category-header.critical {{ background: linear-gradient(135deg, #742a2a 0%, #c53030 100%); }}
        .category-count {{ background-color: rgba(255,255,255,0.2); padding: 5px 15px; border-radius: 20px; font-size: 0.7em; margin-left: 15px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background-color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background-color: #2c5282; color: white; font-weight: 600; }}
        tr:hover {{ background-color: #f7fafc; }}
        tr.critical-row {{ background-color: #fff5f5; }}
        tr.critical-row:hover {{ background-color: #fed7d7; }}
        .stats-table {{ max-width: 700px; margin: 20px auto; }}
        .rule-card {{
            background-color: white; border: 1px solid #e2e8f0; border-radius: 8px;
            padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .rule-id {{
            font-family: 'Courier New', monospace; font-weight: bold; color: #2c5282;
            font-size: 1.1em; background-color: #ebf8ff; padding: 5px 10px;
            border-radius: 4px; display: inline-block; margin-bottom: 10px;
        }}
        .rule-detail {{ margin: 8px 0; }}
        .rule-label {{ font-weight: 600; color: #4a5568; display: inline-block; min-width: 140px; }}
        .rule-value {{ color: #2d3748; }}
        .no-rules {{ color: #718096; font-style: italic; }}
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.85em; font-weight: 500; }}
        .badge-used {{ background-color: #c6f6d5; color: #22543d; }}
        .badge-unused {{ background-color: #fed7d7; color: #742a2a; }}
        .badge-critical {{ background-color: #c53030; color: white; font-weight: bold; }}
        .badge-type {{ background-color: #e9d8fd; color: #44337a; }}
        hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }}
        .section-divider {{ border-top: 3px solid #4299e1; margin: 50px 0; }}
        .exec-summary {{ background-color: white; padding: 25px 30px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .exec-summary h3 {{ background: none; padding: 0; margin-top: 20px; color: #2c5282; }}
        .highlight-box {{ background-color: #ebf8ff; border-left: 4px solid #4299e1; padding: 15px; margin: 15px 0; }}
        .critical-box {{ background-color: #fff5f5; border-left: 4px solid #c53030; padding: 15px; margin: 15px 0; }}
        .critical-alert {{ background: linear-gradient(135deg, #742a2a 0%, #c53030 100%); color: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .critical-alert h4 {{ margin: 0 0 10px 0; font-size: 1.2em; }}
        .toc {{ background-color: white; padding: 20px 30px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .toc h2 {{ margin-top: 0; }}
        .toc ul {{ list-style-type: none; padding-left: 0; }}
        .toc li {{ padding: 5px 0; }}
        .toc a {{ color: #2c5282; text-decoration: none; }}
        .toc a:hover {{ text-decoration: underline; }}
        @media print {{ body {{ background-color: white; }} .category-header {{ break-before: page; }} .navbar {{ display: none !important; }} }}
        html {{ scroll-behavior: smooth; }}
        .navbar {{
            position: fixed; top: 0; left: 0; right: 0;
            background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%);
            padding: 0; z-index: 1000; box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }}
        .navbar-container {{ max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; }}
        .navbar-brand {{ color: white; font-weight: bold; font-size: 1.1em; padding: 12px 0; text-decoration: none; white-space: nowrap; }}
        .navbar-nav {{ display: flex; list-style: none; margin: 0; padding: 0; gap: 5px; }}
        .nav-link {{ color: rgba(255,255,255,0.9); text-decoration: none; padding: 15px 12px; display: block; font-size: 0.9em; transition: all 0.2s ease; border-bottom: 3px solid transparent; }}
        .nav-link:hover {{ background-color: rgba(255,255,255,0.1); color: white; }}
        .nav-link.active {{ border-bottom-color: #4299e1; color: white; }}
        .dropdown-menu {{ display: none; position: absolute; top: 100%; left: 0; background: white; min-width: 280px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); border-radius: 0 0 8px 8px; max-height: 70vh; overflow-y: auto; z-index: 1001; }}
        .nav-item:hover .dropdown-menu {{ display: block; }}
        .dropdown-menu a {{ display: block; padding: 10px 15px; color: #2d3748; text-decoration: none; font-size: 0.85em; border-bottom: 1px solid #e2e8f0; transition: background-color 0.2s; }}
        .dropdown-menu a:hover {{ background-color: #f7fafc; }}
        .dropdown-menu a.critical-item {{ background-color: #fff5f5; color: #c53030; font-weight: 500; }}
        .dropdown-menu a.critical-item:hover {{ background-color: #fed7d7; }}
        .dropdown-header {{ padding: 10px 15px; background-color: #edf2f7; font-weight: bold; font-size: 0.8em; color: #4a5568; text-transform: uppercase; letter-spacing: 0.5px; }}
        .nav-item {{ position: relative; }}
        .dropdown-toggle::after {{ content: " \\25BE"; font-size: 0.7em; }}
        .back-to-top {{
            position: fixed; bottom: 30px; right: 30px; width: 50px; height: 50px;
            background: linear-gradient(135deg, #2c5282 0%, #4299e1 100%);
            color: white; border: none; border-radius: 50%; cursor: pointer; font-size: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3); opacity: 0; visibility: hidden;
            transition: all 0.3s ease; z-index: 999;
        }}
        .back-to-top.visible {{ opacity: 1; visibility: visible; }}
        .back-to-top:hover {{ transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.4); }}
        @media (max-width: 1024px) {{
            .navbar-container {{ flex-direction: column; align-items: flex-start; padding: 10px 15px; }}
            .navbar-nav {{ flex-wrap: wrap; gap: 0; }}
            .nav-link {{ padding: 10px 8px; font-size: 0.8em; }}
            body {{ padding-top: 100px; }}
        }}
    </style>
</head>
<body>
    <!-- Navigation Bar -->
    <nav class="navbar">
        <div class="navbar-container">
            <a href="#" class="navbar-brand">JTBD Gap Analysis</a>
            <ul class="navbar-nav">
                <li class="nav-item">
                    <a href="#executive-summary" class="nav-link">Executive Summary</a>
                </li>
                <li class="nav-item">
                    <a href="#coverage-statistics" class="nav-link">Summary Stats</a>
                </li>
                <li class="nav-item">
                    <a href="#jtbd-mappings" class="nav-link dropdown-toggle">JTBD Mappings</a>
                    <div class="dropdown-menu">
                        <div class="dropdown-header">Underwriting Domains</div>
{section_nav}
                    </div>
                </li>
                <li class="nav-item">
                    <a href="#unused-rules" class="nav-link dropdown-toggle">Unused Rules</a>
                    <div class="dropdown-menu">
                        <div class="dropdown-header">Critical Categories ({len(critical_cats)})</div>
{critical_nav}
                        <div class="dropdown-header">Non-Critical Categories</div>
{non_critical_nav}
                    </div>
                </li>
            </ul>
        </div>
    </nav>

    <!-- Back to Top Button -->
    <button class="back-to-top" onclick="window.scrollTo({{top: 0, behavior: 'smooth'}})" title="Back to top">&uarr;</button>

    <h1>JTBD Gap Analysis Using Fannie Mae Knowledge Graph</h1>
    <p class="subtitle">Comprehensive Analysis of Jobs-To-Be-Done Coverage Against Knowledge Graph Business Rules<br>
    <small>Source: {_esc(jtbd_title)} | Generated: {timestamp} | Model: {MODEL}</small></p>

    <!-- TL;DR Section -->
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px 30px; border-radius: 10px; margin: 20px 0 30px 0; box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);">
        <h2 style="color: white; border: none; padding: 0; margin: 0 0 15px 0; font-size: 1.5em;">TL;DR</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px;">
            <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px;">
                <h4 style="margin: 0 0 10px 0; font-size: 1.1em;">Knowledge Graph Coverage Gap</h4>
                <p style="margin: 0; font-size: 0.95em;">Only <strong>{used} of {total_kg} KG rules ({pct_kg_used}%)</strong> are mapped to JTBDs. <strong>{unused} rules ({round(100 - pct_kg_used, 1)}%)</strong> remain unused.</p>
            </div>
            <div style="background: rgba(255,0,0,0.3); padding: 15px; border-radius: 8px; border: 2px solid rgba(255,255,255,0.5);">
                <h4 style="margin: 0 0 10px 0; font-size: 1.1em;">CRITICAL GAP</h4>
                <p style="margin: 0; font-size: 0.95em;"><strong>{total_critical} rules</strong> in <strong>{len(critical_cats)} critical categories</strong> are NOT covered by JTBDs.</p>
            </div>
        </div>
    </div>

    <div class="toc">
        <h2>Table of Contents</h2>
        <ul>
            <li><a href="#executive-summary">1. Executive Summary</a></li>
            <li><a href="#coverage-statistics">2. Summary Statistics</a></li>
            <li><a href="#jtbd-mappings">3. JTBD Rule Mappings by Section</a></li>
            <li><a href="#unused-rules">4. Unused Rules from Knowledge Graph ({unused} rules)</a></li>
        </ul>
    </div>

    <div class="exec-summary" id="executive-summary">
        <h2 style="margin-top: 0; border: none; padding: 0;">1. Executive Summary</h2>

        <h3>Purpose</h3>
        <p>This report maps each Job-To-Be-Done from the <strong>{_esc(jtbd_title)}</strong> to Fannie Mae Knowledge Graph business rules using <strong>{MODEL}</strong> semantic analysis. It identifies coverage gaps and unmapped rules requiring attention.</p>

        <h3>Scope of Analysis</h3>
        <div class="highlight-box">
            <ul style="margin: 0;">
                <li><strong>JTBD Inventory:</strong> {total_jtbds} Jobs-To-Be-Done across {len(section_mappings)} underwriting domains</li>
                <li><strong>Knowledge Graph Rules:</strong> {total_kg} business rules extracted from Fannie Mae Selling Guide</li>
                <li><strong>Mapping Methodology:</strong> {MODEL} semantic analysis matching JTBD requirements to KG rule implementations</li>
            </ul>
        </div>

        {"" if total_critical == 0 else f'''<div class="critical-alert">
            <h4>CRITICAL GAP ALERT</h4>
            <p style="margin: 0;"><strong>{total_critical} rules</strong> across <strong>{len(critical_cats)} critical categories</strong> are NOT covered by any JTBD. These rules represent <strong>{pct_critical}%</strong> of the total Knowledge Graph and directly impact core underwriting functions.</p>
        </div>'''}

        <h3>Key Findings</h3>
        <p><strong>1. Knowledge Graph Utilization ({pct_kg_used}%):</strong> {used} of {total_kg} KG rules are referenced by JTBDs. The unused {unused} rules ({round(100 - pct_kg_used, 1)}%) include both non-critical back-office rules and critical underwriting rules.</p>
        <p><strong>2. Critical Unused Rules ({total_critical} rules across {len(critical_cats)} categories):</strong></p>
        <div class="critical-box">
            <table style="margin: 0; box-shadow: none;">
                <tr><th>Critical Category</th><th># Unused Rules</th></tr>
{critical_stats_rows}
            </table>
        </div>
    </div>

    <h2 id="coverage-statistics">2. Summary Statistics</h2>
    <table class="stats-table">
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Total JTBDs</td><td>{total_jtbds}</td></tr>
        <tr><td colspan="2" style="background-color: #e2e8f0; font-weight: bold;">Knowledge Graph Statistics</td></tr>
        <tr><td>Total KG Rules</td><td>{total_kg}</td></tr>
        <tr><td><strong>Unique KG Rules Used</strong></td><td><span class="badge badge-used">{used} ({pct_kg_used}%)</span></td></tr>
        <tr><td><strong>KG Rules NOT Used</strong></td><td><span class="badge badge-unused">{unused} ({round(100 - pct_kg_used, 1)}%)</span></td></tr>
        <tr><td colspan="2" style="background-color: #fed7d7; font-weight: bold;">Critical Gap Analysis</td></tr>
        <tr class="critical-row"><td><strong>Critical Categories NOT Covered</strong></td><td><span class="badge badge-critical">{len(critical_cats)} categories</span></td></tr>
        <tr class="critical-row"><td><strong>Critical Rules NOT Covered by JTBDs</strong></td><td><span class="badge badge-critical">{total_critical} rules ({pct_critical}% of total KG)</span></td></tr>
    </table>

    <h3>Critical Categories Breakdown</h3>
    <table>
        <tr><th>Category</th><th># Unused Rules</th><th>Status</th></tr>
{critical_stats_rows}
    </table>

    <div class="section-divider"></div>
    <h2 id="jtbd-mappings">3. JTBD Rule Mappings by Section</h2>
{mapping_html}

    <div class="section-divider"></div>
    <h2 id="unused-rules">4. Unused Rules from Knowledge Graph ({unused} rules)</h2>
{unused_html}

    <script>
        // Back to top button visibility
        const backToTopBtn = document.querySelector('.back-to-top');
        window.addEventListener('scroll', () => {{
            if (window.scrollY > 500) {{
                backToTopBtn.classList.add('visible');
            }} else {{
                backToTopBtn.classList.remove('visible');
            }}
        }});

        // Active section highlighting
        const sections = document.querySelectorAll('[id]');
        const navLinks = document.querySelectorAll('.nav-link');

        function updateActiveLink() {{
            let current = '';
            sections.forEach(section => {{
                const sectionTop = section.offsetTop - 100;
                if (window.scrollY >= sectionTop) {{
                    current = section.getAttribute('id');
                }}
            }});

            navLinks.forEach(link => {{
                link.classList.remove('active');
                const href = link.getAttribute('href');
                if (href && href.slice(1) === current) {{
                    link.classList.add('active');
                }}
                if (current.startsWith('section-') && href === '#jtbd-mappings') {{
                    link.classList.add('active');
                }}
                if (current.startsWith('cat-') && href === '#unused-rules') {{
                    link.classList.add('active');
                }}
            }});
        }}

        window.addEventListener('scroll', updateActiveLink);
        updateActiveLink();

        document.addEventListener('click', (e) => {{
            if (!e.target.closest('.nav-item')) {{
                document.querySelectorAll('.dropdown-menu').forEach(menu => {{
                    menu.classList.remove('show');
                }});
            }}
        }});

        document.querySelectorAll('.dropdown-toggle').forEach(toggle => {{
            toggle.addEventListener('click', (e) => {{
                if (window.innerWidth <= 1024) {{
                    e.preventDefault();
                    const dropdown = toggle.nextElementSibling;
                    dropdown.classList.toggle('show');
                }}
            }});
        }});
    </script>
</body>
</html>"""

    return report


# ─── Main ────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Map JTBDs to Fannie Mae Knowledge Graph rules using GPT-5.2"
    )
    parser.add_argument(
        "--kg",
        default="pipeline-output/sample/agent-5-optimized/optimized_compliance_knowledge_graph.json",
        help="Path to the knowledge graph JSON",
    )
    parser.add_argument(
        "--jtbds",
        default="jtbds.json",
        help="Path to the JTBDs JSON",
    )
    parser.add_argument(
        "--output",
        default="pipeline-output/sample/JTBD_Gap_Analysis_Report.html",
        help="Path for the output HTML report",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Path for the raw mapping JSON (defaults to same dir as HTML)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"JTBDs per LLM call (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Parallel LLM calls (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--skip-mapping",
        action="store_true",
        help="Skip LLM mapping step, regenerate HTML from existing JSON",
    )
    parser.add_argument(
        "--no-complete-match",
        action="store_true",
        help="Disable strict fallback pass that guarantees at least one rule per JTBD",
    )
    parser.add_argument(
        "--fallback-workers",
        type=int,
        default=FORCED_MATCH_MAX_WORKERS,
        help=f"Parallel fallback workers for unmatched JTBDs (default: {FORCED_MATCH_MAX_WORKERS})",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("JTBD-to-KG Rule Mapper Agent")
    print(f"  Model: {MODEL}")
    print(f"  Reasoning effort: {REASONING_EFFORT}")
    print("=" * 60)

    # Load data
    print("\n[1/5] Loading data...")
    kg = load_knowledge_graph(args.kg)
    jtbds_data = load_jtbds(args.jtbds)
    jtbds = jtbds_data.get("values", [])
    jtbd_title = jtbds_data.get("title", "JTBD Set")
    print(f"  KG: {len(kg.get('business_rules', []))} rules")
    print(f"  JTBDs: {len(jtbds)} items from '{jtbd_title}'")

    # Run mapping or load existing
    json_path = args.output_json or args.output.replace(".html", "_mappings.json")
    if args.skip_mapping:
        print("\n[2/5] Loading existing mappings...")
        with open(json_path, "r", encoding="utf-8") as f:
            mappings = json.load(f)
        print(f"  Loaded {len(mappings)} mappings from {json_path}")
    else:
        print("\n[2/5] Running GPT-5.2 semantic mapping...")
        mappings = run_mapping(jtbds, kg, batch_size=args.batch_size, max_workers=args.max_workers)

    if args.no_complete_match:
        print("\n[3/5] Complete-match fallback disabled by flag.")
    else:
        print("\n[3/5] Ensuring complete JTBD coverage...")
        mappings = ensure_complete_mappings(
            mappings,
            jtbds,
            kg,
            max_workers=max(1, args.fallback_workers),
        )

    # Save raw JSON (always, including skip-mapping mode)
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)
    print(f"\n[4/5] Raw mappings saved: {json_path}")

    # Analyze & generate report
    print("\n[5/5] Generating HTML report...")
    analysis = analyze_results(mappings, jtbds, kg)
    html = generate_html_report(analysis, jtbd_title)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  Report saved: {args.output}")
    print(f"\n  Summary:")
    print(f"    JTBDs with mappings: {analysis['jtbd_with_rules']}/{analysis['total_jtbds']}")
    print(f"    KG rules used:      {analysis['used_rules']}/{analysis['total_kg_rules']}")
    print(f"    Critical gaps:      {analysis['total_critical']} rules in {len(analysis['critical_categories'])} categories")
    print("=" * 60)


if __name__ == "__main__":
    main()
