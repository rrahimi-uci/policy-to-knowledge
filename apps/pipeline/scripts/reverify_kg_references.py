#!/usr/bin/env python3
"""
Re-verify and recover source references in existing KG JSON files.

This script applies the improved verification logic (with position recovery)
to already-generated KG files without requiring a full pipeline re-run.

Usage:
    python scripts/reverify_kg_references.py <kg_json> <source_dir>

Examples:
    python scripts/reverify_kg_references.py pipeline-output/sample_guidelines-kg.json \
        ../explorer/kbs/sample-guidelines/

    # Re-verify all KG files:
    for kg in pipeline-output/*-kg.json; do
        domain=$(basename "$kg" -kg.json | tr '_' '-')
        python scripts/reverify_kg_references.py "$kg" "../explorer/kbs/$domain/"
    done
"""
import json
import sys
import os
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, Dict


def _find_text_in_words(words: list, needle: str, threshold: float = 0.6) -> Optional[tuple]:
    """Search for needle text in a word list using sliding-window fuzzy match."""
    if not needle or not words:
        return None
    needle_lower = needle.lower().strip()
    needle_words = needle_lower.split()
    needle_len = len(needle_words)
    if needle_len == 0:
        return None

    content_lower = ' '.join(words).lower()

    # Fast path: exact substring match
    idx = content_lower.find(needle_lower[:min(80, len(needle_lower))])
    if idx >= 0:
        before = content_lower[:idx]
        start_w = len(before.split()) - (1 if before.endswith(' ') or idx == 0 else 0)
        if start_w < 0:
            start_w = 0
        end_w = min(start_w + needle_len, len(words))
        candidate = ' '.join(words[start_w:end_w]).lower()
        ratio = SequenceMatcher(None, needle_lower, candidate).ratio()
        if ratio >= threshold:
            return (start_w, end_w, ratio)

    # Sliding window
    best = None
    margin = max(3, needle_len // 5)
    for window_size in range(max(1, needle_len - margin), needle_len + margin + 1):
        step = max(1, (len(words) - window_size) // 200)
        for i in range(0, len(words) - window_size + 1, step):
            candidate = ' '.join(words[i:i + window_size]).lower()
            if needle_words[0] not in candidate.split()[:3]:
                continue
            ratio = SequenceMatcher(None, needle_lower, candidate).ratio()
            if ratio >= threshold and (best is None or ratio > best[2]):
                best = (i, i + window_size, ratio)
                if ratio > 0.9:
                    return best
    return best


def reverify(kg_path: str, source_dir: str) -> dict:
    """Re-verify all rules in a KG JSON file against source chunks."""
    with open(kg_path, 'r', encoding='utf-8') as f:
        kg = json.load(f)

    # Build chunk lookup
    src = Path(source_dir)
    if not src.is_dir():
        print(f"ERROR: Source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(1)

    chunk_words: Dict[str, list] = {}
    filename_to_paths: Dict[str, list] = {}
    for txt_file in src.rglob("*.txt"):
        if txt_file.name.startswith('_'):
            continue
        try:
            rel = str(txt_file.relative_to(src))
            with open(txt_file, 'r', encoding='utf-8') as f:
                chunk_words[rel] = f.read().split()
            filename_to_paths.setdefault(txt_file.name.lower(), []).append(rel)
        except Exception:
            pass

    print(f"Loaded {len(chunk_words)} chunk files from {source_dir}")

    stats = {"total": 0, "verified": 0, "recovered": 0, "failed": 0, "skipped": 0}

    def _fuzzy_find_chunk(chunk_path: str) -> Optional[str]:
        fname = chunk_path.split('/')[-1].lower() if '/' in chunk_path else chunk_path.lower()
        candidates = filename_to_paths.get(fname, [])
        if len(candidates) == 1:
            return candidates[0]
        segments = [s for s in chunk_path.replace('\\', '/').split('/') if s]
        if len(segments) >= 2:
            suffix = '/'.join(segments[-2:]).lower()
            for real_path in chunk_words:
                if real_path.lower().endswith(suffix):
                    return real_path
        return None

    def verify_rule(rule):
        stats["total"] += 1
        ref = rule.get('source_reference')

        if isinstance(ref, str) or not isinstance(ref, dict):
            stats["skipped"] += 1
            return

        chunk_path = ref.get('chunk_path', '')
        source_text = ref.get('source_text', '')
        start_pos = ref.get('start_word_position', -1)
        end_pos = ref.get('end_word_position', -1)

        # Resolve path
        resolved = chunk_path
        if chunk_path not in chunk_words:
            fuzzy = _fuzzy_find_chunk(chunk_path)
            if fuzzy:
                resolved = fuzzy
                ref['chunk_path'] = resolved
            else:
                rule['reference_verified'] = False
                rule['reference_verification_note'] = f'chunk_not_found:{chunk_path}'
                stats["failed"] += 1
                return

        words = chunk_words[resolved]

        # Check at stated positions first
        positions_valid = (
            isinstance(start_pos, int) and start_pos >= 0
            and isinstance(end_pos, int) and end_pos > 0
            and start_pos < end_pos and start_pos < len(words)
        )
        if positions_valid and end_pos > len(words):
            end_pos = len(words)
            ref['end_word_position'] = end_pos

        if positions_valid and source_text:
            actual = ' '.join(words[start_pos:end_pos])
            ratio = SequenceMatcher(None, source_text.lower(), actual.lower()).ratio()
            ref['text_match_score'] = round(ratio, 3)
            if ratio >= 0.3:
                rule['reference_verified'] = True
                rule['reference_verification_note'] = 'ok'
                stats["verified"] += 1
                return

        # Recovery: search for source_text in chunk
        if source_text:
            found = _find_text_in_words(words, source_text)
            if found:
                new_start, new_end, ratio = found
                ref['start_word_position'] = new_start
                ref['end_word_position'] = new_end
                ref['text_match_score'] = round(ratio, 3)
                rule['reference_verified'] = True
                rule['reference_verification_note'] = 'ok_recovered_position'
                stats["recovered"] += 1
                stats["verified"] += 1
                return

        # Last resort: try description
        desc = rule.get('description', '')
        if desc and len(desc) > 30:
            found = _find_text_in_words(words, desc[:300], threshold=0.4)
            if found:
                new_start, new_end, ratio = found
                ref['start_word_position'] = new_start
                ref['end_word_position'] = new_end
                ref['text_match_score'] = round(ratio, 3)
                ref['source_text'] = ' '.join(words[new_start:new_end])
                rule['reference_verified'] = True
                rule['reference_verification_note'] = 'ok_recovered_from_description'
                stats["recovered"] += 1
                stats["verified"] += 1
                return

        rule['reference_verified'] = False
        rule['reference_verification_note'] = f'text_mismatch:ratio={ref.get("text_match_score", 0):.2f}'
        stats["failed"] += 1

    # Process all rules (only structured dicts, skip plain strings)
    for rule in kg.get('business_rules', []):
        if isinstance(rule, dict):
            verify_rule(rule)
    entity_types = kg.get('entity_types', {})
    if isinstance(entity_types, dict):
        for et in entity_types.values():
            if isinstance(et, dict):
                for rule in et.get('business_rules', []):
                    if isinstance(rule, dict):
                        verify_rule(rule)

    # Save updated KG
    with open(kg_path, 'w', encoding='utf-8') as f:
        json.dump(kg, f, indent=2, ensure_ascii=False)

    return stats


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python reverify_kg_references.py <kg_json> <source_dir>")
        sys.exit(1)

    kg_file = sys.argv[1]
    src_dir = sys.argv[2]

    if not os.path.isfile(kg_file):
        print(f"ERROR: KG file not found: {kg_file}", file=sys.stderr)
        sys.exit(1)

    print(f"\nRe-verifying: {kg_file}")
    print(f"Source dir:   {src_dir}")
    print("-" * 60)

    result = reverify(kg_file, src_dir)

    print(f"\n{'='*60}")
    print(f"  Total rules:    {result['total']}")
    print(f"  Verified:       {result['verified']} (includes {result['recovered']} recovered)")
    print(f"  Failed:         {result['failed']}")
    print(f"  Skipped:        {result['skipped']} (non-dict source_reference)")
    rate = result['verified'] / result['total'] * 100 if result['total'] else 0
    print(f"  Pass rate:      {rate:.0f}%")
    print(f"{'='*60}")
