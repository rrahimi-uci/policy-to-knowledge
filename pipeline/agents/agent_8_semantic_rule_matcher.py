#!/usr/bin/env python3
"""
Semantic Rule Matcher (Agent 8)

Compares rules WITHIN each rule behavior (HOW) using LLM to classify relationships:
- IDENTICAL: Same rule, same thresholds
- EQUIVALENT: Same practical effect
- CONTRADICTORY: Same topic, conflicting requirements
- UNRELATED: No meaningful connection

Includes confidence scores for each match.

Author: Reza Rahimi
Date: December 20, 2025
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import get_config
from utils.llm_client import create_llm_client
from utils.prompt_manager import get_prompt_manager


class SemanticRuleMatcher:
    """
    Compares rules within each type using LLM for semantic matching.
    Uses BATCH parallel processing - multiple pairs per LLM call for 10x speedup.
    """
    
    def __init__(self, provider: str = "openai", max_workers: int = None, batch_size: int = None, merge_subfolder: str = None):
        """
        Initialize the matcher.
        
        Args:
            provider: The provider folder (openai/anthropic)
            max_workers: Maximum parallel LLM calls (from config if not set)
            batch_size: Number of pairs per LLM call (from config if not set)
            merge_subfolder: Subfolder name for merged outputs (e.g., 'graphA_graphB')
        """
        self.provider = provider
        self.config = get_config()
        self.max_workers = max_workers if max_workers is not None else self.config.get_matcher_max_workers()
        self.batch_size = batch_size if batch_size is not None else self.config.get_matcher_batch_size()
        self.prompt_manager = get_prompt_manager()
        self.merge_subfolder = merge_subfolder
        self.reasoning_effort = self.config.get_reasoning_effort()
        
        # Thread-safe counter for progress
        self._progress_lock = threading.Lock()
        self._completed_count = 0
        self._total_count = 0
        
        self.base_path = Path(__file__).parent.parent / "pipeline-output" / provider
        self._setup_paths()
        
        # Thread-local storage for LLM clients
        self._thread_local = threading.local()
    
    def _setup_paths(self):
        """Set up input/output paths based on merge_subfolder."""
        if self.merge_subfolder:
            self.input_path = self.base_path / "_merged" / self.merge_subfolder / "agent-7-rule-clusters" / "rule_clusters.json"
            self.output_dir = self.base_path / "_merged" / self.merge_subfolder / "agent-8-rule-matches"
        else:
            # Try to detect from existing agent-7 output
            self.input_path = self.base_path / "_merged" / "agent-7-rule-clusters" / "rule_clusters.json"
            self.output_dir = self.base_path / "_merged" / "agent-8-rule-matches"
    
    def _detect_subfolder_from_metadata(self):
        """Detect subfolder from agent-7 metadata if not set."""
        if self.merge_subfolder:
            return
        
        # Check for subfolders in _merged that contain agent-7-rule-clusters
        merged_dir = self.base_path / "_merged"
        if merged_dir.exists():
            for item in merged_dir.iterdir():
                if item.is_dir() and not item.name.startswith('agent-'):
                    potential_input = item / "agent-7-rule-clusters" / "rule_clusters.json"
                    if potential_input.exists():
                        self.merge_subfolder = item.name
                        self._setup_paths()
                        print(f"   \u2139\ufe0f  Detected merge subfolder: {self.merge_subfolder}")
                        return
    
    def _get_llm_client(self):
        """Get thread-local LLM client."""
        if not hasattr(self._thread_local, 'client'):
            # Use configured reasoning model from config
            from utils.config import get_config
            global_config = get_config()
            model = global_config.get_reasoning_model()
            
            self._thread_local.client = create_llm_client(
                api_key=self.config.get('openai_api_key'),
                anthropic_api_key=self.config.get('anthropic_api_key'),
                model=model
            )
        return self._thread_local.client
        
    def load_clusters(self) -> dict:
        """Load clustered rules from Agent 7."""
        # Try to detect subfolder if not set
        self._detect_subfolder_from_metadata()
        
        if not self.input_path.exists():
            raise FileNotFoundError(f"Rule clusters not found: {self.input_path}\nRun Agent 7 first.")
        
        with open(self.input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Update subfolder from metadata if available
        if not self.merge_subfolder and 'metadata' in data:
            g1_name = data['metadata'].get('g1_name')
            g2_name = data['metadata'].get('g2_name')
            if g1_name and g2_name:
                self.merge_subfolder = f"{g1_name}_{g2_name}"
                self._setup_paths()
        
        return data
    
    def _extract_key_features(self, rule: dict) -> dict:
        """Extract key features from a rule for comparison."""
        return {
            'rule_id': rule.get('rule_id', ''),
            'rule_name': rule.get('rule_name', ''),
            'description': rule.get('description', '')[:500],
            'conditions': rule.get('conditions', ''),
            'consequences': rule.get('consequences', ''),
            'thresholds': self._extract_thresholds(rule),
            'mandatory': rule.get('mandatory', False)
        }
    
    def _extract_thresholds(self, rule: dict) -> List[str]:
        """Extract numeric thresholds from rule text."""
        thresholds = []
        text = f"{rule.get('description', '')} {rule.get('conditions', '')}"
        
        # Find percentages
        percentages = re.findall(r'\d+\.?\d*\s*%', text)
        thresholds.extend(percentages)
        
        # Find dollar amounts
        dollars = re.findall(r'\$[\d,]+\.?\d*', text)
        thresholds.extend(dollars)
        
        # Find year/month durations
        durations = re.findall(r'\d+\s*(?:year|month|day|week)s?', text, re.IGNORECASE)
        thresholds.extend(durations)
        
        # Find score values (credit scores, etc.)
        scores = re.findall(r'(?:score|fico|credit)\s*(?:of|>=?|<=?|minimum|maximum)?\s*(\d{3})', text, re.IGNORECASE)
        thresholds.extend([f"score:{s}" for s in scores])

        # AML-specific patterns
        # Allow up to 50 non-digit, non-$ characters between keyword and amount
        ctr_sar = re.findall(r'(?:ctr|sar|currency\s+transaction|suspicious\s+activity)[^\d$]{0,50}\$?([\d,]{3,})', text, re.IGNORECASE)
        thresholds.extend([f"ctr_sar:${v}" for v in ctr_sar])

        # Allow intervening words between "beneficial owner(ship)" and the percentage
        beneficial_ownership = re.findall(r'(?:beneficial\s*owner(?:ship)?)[^%]{0,60}?(\d+)\s*%', text, re.IGNORECASE)
        thresholds.extend([f"bo_pct:{v}%" for v in beneficial_ownership])

        fatf_refs = re.findall(r'(?:fatf|grey.?list|high.?risk\s+jurisdiction|non.?cooperative)', text, re.IGNORECASE)
        if fatf_refs:
            thresholds.append("fatf_ref")

        sanctions = re.findall(r'(?:ofac|sdn|sanctions?\s+list|specially\s+designated)', text, re.IGNORECASE)
        if sanctions:
            thresholds.append("sanctions_ref")

        return thresholds
    
    def _call_llm_for_batch(self, batch: List[Tuple], g1_name: str, g2_name: str) -> List[dict]:
        """
        Call LLM to compare a BATCH of rule pairs (thread-safe).
        
        Args:
            batch: List of (pair_idx, i, j, rule_a, rule_b) tuples
            g1_name: Name of first knowledge graph
            g2_name: Name of second knowledge graph
            
        Returns:
            List of result dicts, one per pair
        """
        try:
            # Get thread-local LLM client
            llm_client = self._get_llm_client()
            
            # Load batch prompt template
            prompt_template = self.prompt_manager.load_prompt('rule_matcher_batch')
            
            # Format pairs for prompt
            pairs_data = []
            for idx, (pair_idx, i, j, rule_a, rule_b) in enumerate(batch):
                pairs_data.append({
                    "pair_id": idx,
                    "rule_a": self._extract_key_features(rule_a),
                    "rule_b": self._extract_key_features(rule_b)
                })
            
            prompt = prompt_template.format(
                g1_name=g1_name,
                g2_name=g2_name,
                rule_pairs_json=json.dumps(pairs_data, indent=2),
                num_pairs=len(batch)
            )
            
            messages = [
                {"role": "system", "content": "You are an expert at comparing compliance rules. Return ONLY a valid JSON array."},
                {"role": "user", "content": prompt}
            ]
            
            response = llm_client.get_text_response(
                messages=messages,
                max_tokens=self.config.get_matcher_max_tokens(),
                reasoning_effort=self.reasoning_effort
            )
            
            # Parse JSON array response
            response_text = response.strip()
            
            # Extract JSON array from response
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                results = json.loads(json_match.group())
                # Ensure we have results for all pairs
                if len(results) >= len(batch):
                    return results[:len(batch)]
            
            # Fallback: return UNRELATED for all pairs
            return [
                {
                    'pair_id': idx,
                    'relationship': 'UNRELATED',
                    'confidence': 0.5,
                    'similarity_score': 50,
                    'reasoning': 'Failed to parse batch LLM response'
                }
                for idx in range(len(batch))
            ]
            
        except Exception as e:
            print(f"      ⚠ Batch LLM error: {str(e)[:50]}")
            return [
                {
                    'pair_id': idx,
                    'relationship': 'UNRELATED',
                    'confidence': 0.3,
                    'similarity_score': 30,
                    'reasoning': f'Batch LLM error: {str(e)[:50]}'
                }
                for idx in range(len(batch))
            ]
    
    def _match_rules_for_behavior(self, g1_rules: List[dict], g2_rules: List[dict], 
                               rule_behavior: str, g1_name: str, g2_name: str) -> dict:
        """
        Match rules within a single rule behavior (HOW) using BATCH PARALLEL processing.
        
        Creates ALL pairs (G1 × G2), batches them, and processes batches in parallel.
        This is ~10x faster than individual pair processing!
        """
        total_pairs = len(g1_rules) * len(g2_rules)
        num_batches = (total_pairs + self.batch_size - 1) // self.batch_size
        
        print(f"\n   ┌{'─'*60}┐")
        print(f"   │ 📊 Rule Behavior: {rule_behavior.upper():<40}│")
        print(f"   ├{'─'*60}┤")
        print(f"   │ G1 ({g1_name}): {len(g1_rules):>5} rules                              │")
        print(f"   │ G2 ({g2_name}): {len(g2_rules):>5} rules                              │")
        print(f"   │ Total pairs: {total_pairs:>6} ({len(g1_rules)}×{len(g2_rules)})                       │")
        print(f"   │ Batches: {num_batches:>5} (batch_size={self.batch_size})                      │")
        print(f"   │ Workers: {self.max_workers:<5}                                        │")
        print(f"   └{'─'*60}┘")
        
        if total_pairs == 0:
            return {
                'matches': [],
                'contradictions': [],
                'g1_unmatched': g1_rules,
                'g2_unmatched': g2_rules
            }
        
        # Build ALL pairs (G1 × G2) with global indices
        all_pairs = []
        pair_idx = 0
        for i, rule_a in enumerate(g1_rules):
            for j, rule_b in enumerate(g2_rules):
                all_pairs.append((pair_idx, i, j, rule_a, rule_b))
                pair_idx += 1
        
        # Split into batches
        batches = []
        for b in range(0, len(all_pairs), self.batch_size):
            batches.append(all_pairs[b:b + self.batch_size])
        
        # Reset progress counter
        with self._progress_lock:
            self._completed_count = 0
            self._total_count = len(batches)
        
        print(f"\n   🚀 Starting BATCH parallel processing ({len(batches)} batches)...")
        start_time = datetime.now()
        
        def process_batch(batch_data):
            """Process a batch of pairs and update progress."""
            batch_idx, batch = batch_data
            results = self._call_llm_for_batch(batch, g1_name, g2_name)
            
            # Update progress atomically
            with self._progress_lock:
                self._completed_count += 1
                completed = self._completed_count
                total = self._total_count
            
            # Print progress
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = completed / elapsed if elapsed > 0 else 0
            pairs_done = completed * self.batch_size
            pairs_rate = pairs_done / elapsed if elapsed > 0 else 0
            eta = (total - completed) / rate if rate > 0 else 0
            pct = (completed / total) * 100
            
            # Progress bar
            bar_width = 30
            filled = int(bar_width * completed / total)
            bar = '█' * filled + '░' * (bar_width - filled)
            
            print(f"\r   [{bar}] {pct:5.1f}% | {completed:>4}/{total} batches | ~{pairs_rate:.0f} pairs/s | ETA: {eta:.0f}s   ", end='', flush=True)
            
            # Return batch with results
            return [(batch[idx][1], batch[idx][2], batch[idx][3], batch[idx][4], results[idx]) 
                    for idx in range(len(batch)) if idx < len(results)]
        
        # Process all batches in parallel
        results_list = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all batch tasks
            futures = {executor.submit(process_batch, (idx, batch)): idx for idx, batch in enumerate(batches)}
            
            # Collect results as they complete
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    results_list.extend(batch_results)
                except Exception as e:
                    print(f"\n   ⚠ Batch error: {str(e)[:50]}")
        
        elapsed_total = (datetime.now() - start_time).total_seconds()
        actual_pairs = len(results_list)
        print(f"\n\n   ⏱  Completed in {elapsed_total:.1f}s ({actual_pairs/elapsed_total:.1f} pairs/sec)")
        
        # Process results - prioritize high confidence matches
        matches = []
        contradictions = []
        g1_matched = set()
        g2_matched = set()
        
        results_sorted = sorted(
            results_list,
            key=lambda x: x[4].get('confidence', 0) if x[4].get('relationship') in ['IDENTICAL', 'EQUIVALENT'] else 0,
            reverse=True
        )
        
        for i, j, rule_a, rule_b, result in results_sorted:
            # Skip if either rule already matched
            if i in g1_matched or j in g2_matched:
                continue
            
            relationship = result.get('relationship', 'UNRELATED')
            confidence = result.get('confidence', 0.5)
            
            if relationship in ['IDENTICAL', 'EQUIVALENT']:
                matches.append({
                    'g1_rule_id': rule_a.get('rule_id'),
                    'g2_rule_id': rule_b.get('rule_id'),
                    'g1_rule': rule_a,
                    'g2_rule': rule_b,
                    'relationship': relationship,
                    'confidence': confidence,
                    'similarity_score': result.get('similarity_score', 0),
                    'reasoning': result.get('reasoning', ''),
                    'key_comparison': result.get('key_comparison', {})
                })
                g1_matched.add(i)
                g2_matched.add(j)
                
            elif relationship == 'CONTRADICTORY':
                contradictions.append({
                    'g1_rule_id': rule_a.get('rule_id'),
                    'g2_rule_id': rule_b.get('rule_id'),
                    'g1_rule': rule_a,
                    'g2_rule': rule_b,
                    'relationship': relationship,
                    'confidence': confidence,
                    'conflict_detail': result.get('conflict_detail', {}),
                    'reasoning': result.get('reasoning', '')
                })
        
        # Collect unmatched rules
        g1_unmatched = [g1_rules[i] for i in range(len(g1_rules)) if i not in g1_matched]
        g2_unmatched = [g2_rules[j] for j in range(len(g2_rules)) if j not in g2_matched]
        
        print(f"\n   ┌{'─'*60}┐")
        print(f"   │ ✅ RESULTS for {rule_behavior.upper():<42}│")
        print(f"   ├{'─'*60}┤")
        print(f"   │   Matches (IDENTICAL/EQUIVALENT): {len(matches):>5}                  │")
        print(f"   │   Contradictions:                 {len(contradictions):>5}                  │")
        print(f"   │   {g1_name}-only (unmatched):      {len(g1_unmatched):>5}                  │")
        print(f"   │   {g2_name}-only (unmatched):      {len(g2_unmatched):>5}                  │")
        print(f"   └{'─'*60}┘")
        
        return {
            'matches': matches,
            'contradictions': contradictions,
            'g1_unmatched': g1_unmatched,
            'g2_unmatched': g2_unmatched
        }
    
    def run(self) -> dict:
        """Run the semantic matching process with BATCH parallelization."""
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   Semantic Rule Matcher (Agent 8) - BATCH MODE                        ║
║   LLM-Powered Rule Comparison (10x faster with batching!)             ║
║   Workers: {self.max_workers:<5}  |  Batch: {self.batch_size:<3}  |  Model: gpt-5.2 (medium)     ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        
        # Load clusters
        clusters_data = self.load_clusters()
        g1_name = clusters_data['metadata']['g1_name']
        g2_name = clusters_data['metadata']['g2_name']
        
        print(f"📊 Comparing: {g1_name} vs {g2_name}")
        
        # Calculate total pairs and batches across all types
        total_pairs_all = 0
        for rule_type, cluster in clusters_data['clusters'].items():
            g1_count = len(cluster.get('g1_rules', []))
            g2_count = len(cluster.get('g2_rules', []))
            total_pairs_all += g1_count * g2_count
        
        total_batches = (total_pairs_all + self.batch_size - 1) // self.batch_size
        
        print(f"📋 Total pairs: {total_pairs_all:,} → {total_batches:,} batches (×{self.batch_size} pairs/batch)")
        est_time = total_batches / self.max_workers * 10 / 60  # ~10 sec per batch
        print(f"⏱  Estimated time: ~{est_time:.1f} minutes (10x faster than single-pair mode!)")
        
        overall_start = datetime.now()
        
        # Process each rule type
        result = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'g1_name': g1_name,
                'g2_name': g2_name,
                'provider': self.provider
            },
            'g1_entities': clusters_data.get('g1_entities', []),
            'g2_entities': clusters_data.get('g2_entities', []),
            'match_matrix': {},
            'summary': {
                'total_matches': 0,
                'total_contradictions': 0,
                'total_g1_only': 0,
                'total_g2_only': 0,
                'by_behavior': {}
            }
        }
        
        for rule_behavior, cluster in clusters_data['clusters'].items():
            g1_rules = cluster.get('g1_rules', [])
            g2_rules = cluster.get('g2_rules', [])
            
            if not g1_rules and not g2_rules:
                continue
            
            behavior_result = self._match_rules_for_behavior(
                g1_rules, g2_rules, rule_behavior, g1_name, g2_name
            )
            
            result['match_matrix'][rule_behavior] = behavior_result
            
            # Update summary
            result['summary']['total_matches'] += len(behavior_result['matches'])
            result['summary']['total_contradictions'] += len(behavior_result['contradictions'])
            result['summary']['total_g1_only'] += len(behavior_result['g1_unmatched'])
            result['summary']['total_g2_only'] += len(behavior_result['g2_unmatched'])
            result['summary']['by_behavior'][rule_behavior] = {
                'matches': len(behavior_result['matches']),
                'contradictions': len(behavior_result['contradictions']),
                'g1_only': len(behavior_result['g1_unmatched']),
                'g2_only': len(behavior_result['g2_unmatched'])
            }
        
        # Save output
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / "match_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, default=str)
        
        overall_elapsed = (datetime.now() - overall_start).total_seconds()
        
        # Print summary
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   MATCHING COMPLETE - SUMMARY                                         ║
╠══════════════════════════════════════════════════════════════════════╣
║   Total Time: {overall_elapsed:.1f}s ({overall_elapsed/60:.1f} min)                                   ║
║                                                                        ║
║   Matches (IDENTICAL/EQUIVALENT): {result['summary']['total_matches']:>5}                            ║
║   Contradictions:                 {result['summary']['total_contradictions']:>5}                            ║
║   {g1_name}-only:          {result['summary']['total_g1_only']:>5}                            ║
║   {g2_name}-only:          {result['summary']['total_g2_only']:>5}                            ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        
        print(f"✅ Match results saved to: {output_file}")
        
        return result


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Semantic rule matching using LLM (BATCH mode)')
    parser.add_argument('--provider', type=str, default='openai', choices=['openai', 'anthropic'])
    config = get_config()
    parser.add_argument('--workers', type=int, default=None, help=f'Number of parallel workers (default: {config.get_matcher_max_workers()} from config)')
    parser.add_argument('--batch-size', type=int, default=None, help=f'Number of pairs per LLM call (default: {config.get_matcher_batch_size()} from config)')
    
    args = parser.parse_args()
    
    matcher = SemanticRuleMatcher(provider=args.provider, max_workers=args.workers, batch_size=args.batch_size)
    matcher.run()


if __name__ == "__main__":
    main()
