"""
Rule uniqueness enforcement utilities.

The LLM extraction and optimization steps instruct the model to produce unique
rule_id and rule_name values, but LLMs can still generate collisions across
parallel batches or under token pressure.  This module provides a deterministic
post-processing pass that guarantees uniqueness regardless of LLM behaviour.
"""

from typing import Any, Dict, List, Tuple


def enforce_rule_uniqueness(
    rules: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Make every rule_id and rule_name in *rules* globally unique in-place.

    Collision resolution:
    - rule_id  : append ``_v2``, ``_v3``, … (keeps the structural prefix intact)
    - rule_name: append `` (Variant 2)``, `` (Variant 3)``, … (keeps human readability)

    After renaming any rule_ids, dependency references that pointed to the old
    id are updated to the new one.

    Returns the (same) list and a summary dict:
        {"id_fixes": <int>, "name_fixes": <int>}
    """
    seen_ids: Dict[str, int] = {}    # canonical id  -> occurrence count
    seen_names: Dict[str, int] = {}  # lower-cased name -> occurrence count
    id_fixes = 0
    name_fixes = 0

    for rule in rules:
        rid = rule.get("rule_id") or ""
        rname = rule.get("rule_name") or ""

        # ── rule_id uniqueness ────────────────────────────────────────────
        if rid:
            if rid in seen_ids:
                seen_ids[rid] += 1
                new_rid = f"{rid}_v{seen_ids[rid]}"
                # Guard against the vanishingly-rare case where the
                # suffixed id itself already exists in seen_ids.
                while new_rid in seen_ids:
                    seen_ids[rid] += 1
                    new_rid = f"{rid}_v{seen_ids[rid]}"
                # Only the duplicate is renamed; the first occurrence keeps its
                # id, so existing dependency references stay valid (we do NOT
                # rewrite them — doing so would point them at the wrong rule).
                rule["rule_id"] = new_rid
                seen_ids[new_rid] = 1
                id_fixes += 1
            else:
                seen_ids[rid] = 1

        # ── rule_name uniqueness ──────────────────────────────────────────
        if rname:
            key = rname.lower().strip()
            if key in seen_names:
                seen_names[key] += 1
                # Start at "(Variant 2)" so the first occurrence stays plain
                # and the label sequence is 2, 3, … (no phantom "Variant 1")
                rule["rule_name"] = f"{rname} (Variant {seen_names[key]})"
                name_fixes += 1
            else:
                seen_names[key] = 1

    return rules, {"id_fixes": id_fixes, "name_fixes": name_fixes}
