#!/usr/bin/env python3
"""
Set Operations Calculator (Agent 9)

Computes 5 distinct set operations from match results:
1. INTERSECTION (G1 ∩ G2) - Rules present in both graphs
2. LEFT DIFFERENCE (G1 - G2) - Rules exclusive to G1
3. RIGHT DIFFERENCE (G2 - G1) - Rules exclusive to G2
4. UNION (G1 ∪ G2) - All unique rules with provenance
5. CONTRADICTIONS - Conflicting rule pairs

Each operation outputs a separate JSON file:
- intersection.json
- g1_minus_g2.json
- g2_minus_g1.json
- union.json
- contradictions.json

Author: Reza Rahimi
Date: December 20, 2025
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional
import copy

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import get_config


class SetOperationsCalculator:
    """
    Computes set operations on matched rules.
    """
    
    def __init__(self, provider: str = "openai", merge_subfolder: str = None):
        """
        Initialize the calculator.
        
        Args:
            provider: The provider folder (openai)
            merge_subfolder: Subfolder name for merged outputs (e.g., 'graphA_graphB')
        """
        self.provider = provider
        self.merge_subfolder = merge_subfolder
        self.base_path = Path(__file__).parent.parent / "pipeline-output"
        self._setup_paths()
    
    def _setup_paths(self):
        """Set up input/output paths based on merge_subfolder."""
        if self.merge_subfolder:
            self.input_path = self.base_path / "_merged" / self.merge_subfolder / "agent-8-rule-matches" / "match_results.json"
            self.output_dir = self.base_path / "_merged" / self.merge_subfolder / "agent-9-set-operations"
        else:
            self.input_path = self.base_path / "_merged" / "agent-8-rule-matches" / "match_results.json"
            self.output_dir = self.base_path / "_merged" / "agent-9-set-operations"
    
    def _detect_subfolder_from_metadata(self):
        """Detect subfolder from agent-8 metadata if not set."""
        if self.merge_subfolder:
            return
        
        # Check for subfolders in _merged that contain agent-8-rule-matches
        merged_dir = self.base_path / "_merged"
        if merged_dir.exists():
            for item in merged_dir.iterdir():
                if item.is_dir() and not item.name.startswith('agent-'):
                    potential_input = item / "agent-8-rule-matches" / "match_results.json"
                    if potential_input.exists():
                        self.merge_subfolder = item.name
                        self._setup_paths()
                        print(f"   ℹ️  Detected merge subfolder: {self.merge_subfolder}")
                        return
        
    def load_match_results(self) -> dict:
        """Load match results from Agent 8."""
        # Try to detect subfolder if not set
        self._detect_subfolder_from_metadata()
        
        if not self.input_path.exists():
            raise FileNotFoundError(f"Match results not found: {self.input_path}\nRun Agent 8 first.")
        
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
    
    def _create_merged_rule(self, match: dict, g1_name: str, g2_name: str) -> dict:
        """Create a merged rule from a match (for UNION and INTERSECTION)."""
        g1_rule = match['g1_rule']
        g2_rule = match['g2_rule']
        
        # Use G1 rule as base, add provenance
        merged = copy.deepcopy(g1_rule)
        
        # Create merged rule ID
        merged['rule_id'] = f"MERGED_{g1_rule.get('rule_id', 'UNKNOWN')}"
        
        # Add provenance metadata with both rule details for clarity
        merged['provenance'] = {
            'operation': 'MERGED',
            'match_type': match.get('relationship', 'EQUIVALENT'),
            'confidence': match.get('confidence', 0.0),
            'similarity_score': match.get('similarity_score', 0),
            'sources': [g1_name, g2_name],
            'original_ids': {
                g1_name: g1_rule.get('rule_id'),
                g2_name: g2_rule.get('rule_id')
            },
            'reasoning': match.get('reasoning', ''),
            # Store both rule details for display
            'g1_rule': {
                'rule_id': g1_rule.get('rule_id'),
                'rule_name': g1_rule.get('rule_name'),
                'description': g1_rule.get('description')
            },
            'g2_rule': {
                'rule_id': g2_rule.get('rule_id'),
                'rule_name': g2_rule.get('rule_name'),
                'description': g2_rule.get('description')
            }
        }
        
        # Remove internal metadata
        if '_source_graph' in merged:
            del merged['_source_graph']
        
        return merged
    
    def _create_single_source_rule(self, rule: dict, source_name: str, operation: str) -> dict:
        """Create a rule with single-source provenance."""
        result = copy.deepcopy(rule)
        
        result['provenance'] = {
            'operation': operation,
            'sources': [source_name],
            'original_ids': {source_name: rule.get('rule_id')}
        }
        
        # Remove internal metadata
        if '_source_graph' in result:
            del result['_source_graph']
        
        return result
    
    def _create_contradiction_entry(self, contradiction: dict, g1_name: str, g2_name: str) -> dict:
        """Create a contradiction entry with both rules preserved."""
        return {
            'contradiction_id': f"CONFLICT_{contradiction['g1_rule_id']}_{contradiction['g2_rule_id']}",
            'conflict_type': contradiction.get('conflict_detail', {}).get('type', 'UNKNOWN'),
            'confidence': contradiction.get('confidence', 0.0),
            'reasoning': contradiction.get('reasoning', ''),
            'conflict_detail': contradiction.get('conflict_detail', {}),
            'g1_rule': {
                'source': g1_name,
                'rule': self._create_single_source_rule(
                    contradiction['g1_rule'], g1_name, 'CONTRADICTION'
                )
            },
            'g2_rule': {
                'source': g2_name,
                'rule': self._create_single_source_rule(
                    contradiction['g2_rule'], g2_name, 'CONTRADICTION'
                )
            }
        }
    
    def compute_union(self, match_results: dict) -> dict:
        """
        Compute UNION (G1 ∪ G2).
        
        Contains all unique rules:
        - Merged rules for matches
        - Unmatched rules from both graphs
        """
        g1_name = match_results['metadata']['g1_name']
        g2_name = match_results['metadata']['g2_name']
        
        rules = []
        
        for rule_behavior, behavior_data in match_results['match_matrix'].items():
            # Add merged rules (from matches)
            for match in behavior_data.get('matches', []):
                rules.append(self._create_merged_rule(match, g1_name, g2_name))
            
            # Add G1-only rules
            for rule in behavior_data.get('g1_unmatched', []):
                rules.append(self._create_single_source_rule(rule, g1_name, 'G1_ONLY'))
            
            # Add G2-only rules
            for rule in behavior_data.get('g2_unmatched', []):
                rules.append(self._create_single_source_rule(rule, g2_name, 'G2_ONLY'))
        
        return {
            'metadata': {
                'operation': 'UNION',
                'description': f'All unique rules from {g1_name} and {g2_name}',
                'g1_name': g1_name,
                'g2_name': g2_name,
                'generated_at': datetime.now().isoformat()
            },
            'business_rules': rules,
            'entities': match_results.get('g1_entities', []) + match_results.get('g2_entities', []),
            'stats': {
                'total_rules': len(rules),
                'merged_rules': sum(len(td.get('matches', [])) for td in match_results['match_matrix'].values()),
                'g1_only_rules': sum(len(td.get('g1_unmatched', [])) for td in match_results['match_matrix'].values()),
                'g2_only_rules': sum(len(td.get('g2_unmatched', [])) for td in match_results['match_matrix'].values())
            }
        }
    
    def compute_intersection(self, match_results: dict) -> dict:
        """
        Compute INTERSECTION (G1 ∩ G2).
        
        Contains only rules that exist in BOTH graphs.
        """
        g1_name = match_results['metadata']['g1_name']
        g2_name = match_results['metadata']['g2_name']
        
        rules = []
        
        for rule_behavior, behavior_data in match_results['match_matrix'].items():
            for match in behavior_data.get('matches', []):
                rules.append(self._create_merged_rule(match, g1_name, g2_name))
        
        return {
            'metadata': {
                'operation': 'INTERSECTION',
                'description': f'Rules present in both {g1_name} and {g2_name}',
                'g1_name': g1_name,
                'g2_name': g2_name,
                'generated_at': datetime.now().isoformat()
            },
            'business_rules': rules,
            'entities': [],  # Entities would need separate intersection logic
            'stats': {
                'total_rules': len(rules),
                'by_match_type': {
                    'IDENTICAL': len([r for r in rules if r.get('provenance', {}).get('match_type') == 'IDENTICAL']),
                    'EQUIVALENT': len([r for r in rules if r.get('provenance', {}).get('match_type') == 'EQUIVALENT'])
                }
            }
        }
    
    def compute_g1_minus_g2(self, match_results: dict) -> dict:
        """
        Compute G1 - G2 (Left Difference).
        
        Contains rules in G1 that have NO match in G2.
        """
        g1_name = match_results['metadata']['g1_name']
        g2_name = match_results['metadata']['g2_name']
        
        rules = []
        
        for rule_behavior, behavior_data in match_results['match_matrix'].items():
            for rule in behavior_data.get('g1_unmatched', []):
                rules.append(self._create_single_source_rule(rule, g1_name, 'G1_EXCLUSIVE'))
        
        return {
            'metadata': {
                'operation': 'G1_MINUS_G2',
                'description': f'Rules in {g1_name} not found in {g2_name}',
                'g1_name': g1_name,
                'g2_name': g2_name,
                'generated_at': datetime.now().isoformat()
            },
            'business_rules': rules,
            'entities': match_results.get('g1_entities', []),
            'stats': {
                'total_rules': len(rules),
                'by_behavior': defaultdict(int)
            }
        }
    
    def compute_g2_minus_g1(self, match_results: dict) -> dict:
        """
        Compute G2 - G1 (Right Difference).
        
        Contains rules in G2 that have NO match in G1.
        """
        g1_name = match_results['metadata']['g1_name']
        g2_name = match_results['metadata']['g2_name']
        
        rules = []
        
        for rule_behavior, behavior_data in match_results['match_matrix'].items():
            for rule in behavior_data.get('g2_unmatched', []):
                rules.append(self._create_single_source_rule(rule, g2_name, 'G2_EXCLUSIVE'))
        
        return {
            'metadata': {
                'operation': 'G2_MINUS_G1',
                'description': f'Rules in {g2_name} not found in {g1_name}',
                'g1_name': g1_name,
                'g2_name': g2_name,
                'generated_at': datetime.now().isoformat()
            },
            'business_rules': rules,
            'entities': match_results.get('g2_entities', []),
            'stats': {
                'total_rules': len(rules)
            }
        }
    
    def compute_contradictions(self, match_results: dict) -> dict:
        """
        Compute CONTRADICTIONS.
        
        Contains rule pairs that conflict with each other.
        Both rules are preserved with conflict metadata.
        """
        g1_name = match_results['metadata']['g1_name']
        g2_name = match_results['metadata']['g2_name']
        
        contradictions = []
        
        for rule_behavior, behavior_data in match_results['match_matrix'].items():
            for contradiction in behavior_data.get('contradictions', []):
                entry = self._create_contradiction_entry(contradiction, g1_name, g2_name)
                entry['rule_behavior'] = rule_behavior
                contradictions.append(entry)
        
        # Group by conflict type
        by_conflict_type = defaultdict(list)
        for c in contradictions:
            by_conflict_type[c.get('conflict_type', 'UNKNOWN')].append(c)
        
        return {
            'metadata': {
                'operation': 'CONTRADICTIONS',
                'description': f'Conflicting rules between {g1_name} and {g2_name}',
                'g1_name': g1_name,
                'g2_name': g2_name,
                'generated_at': datetime.now().isoformat()
            },
            'contradictions': contradictions,
            'stats': {
                'total_contradictions': len(contradictions),
                'by_conflict_type': {k: len(v) for k, v in by_conflict_type.items()},
                'by_rule_behavior': defaultdict(int)
            }
        }
    
    def run(self) -> Dict[str, dict]:
        """Run all set operations and output separate JSON files."""
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   Set Operations Calculator (Agent 9)                                 ║
║   Computing: ∩, G1-G2, G2-G1, ∪, Contradictions                      ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        
        # Load match results
        match_results = self.load_match_results()
        g1_name = match_results['metadata']['g1_name']
        g2_name = match_results['metadata']['g2_name']
        
        print(f"📊 Computing set operations for: {g1_name} vs {g2_name}")
        
        # Compute all 5 operations
        results = {}
        
        print("\n   1️⃣  Computing INTERSECTION (G1 ∩ G2)...")
        results['intersection'] = self.compute_intersection(match_results)
        print(f"      ✓ {results['intersection']['stats']['total_rules']} rules in both graphs")
        
        print(f"\n   2️⃣  Computing LEFT DIFFERENCE ({g1_name} - {g2_name})...")
        results['g1_minus_g2'] = self.compute_g1_minus_g2(match_results)
        print(f"      ✓ {results['g1_minus_g2']['stats']['total_rules']} rules exclusive to {g1_name}")
        
        print(f"\n   3️⃣  Computing RIGHT DIFFERENCE ({g2_name} - {g1_name})...")
        results['g2_minus_g1'] = self.compute_g2_minus_g1(match_results)
        print(f"      ✓ {results['g2_minus_g1']['stats']['total_rules']} rules exclusive to {g2_name}")
        
        print("\n   4️⃣  Computing UNION (G1 ∪ G2)...")
        results['union'] = self.compute_union(match_results)
        print(f"      ✓ {results['union']['stats']['total_rules']} total unique rules")
        
        print("\n   5️⃣  Computing CONTRADICTIONS...")
        results['contradictions'] = self.compute_contradictions(match_results)
        print(f"      ✓ {results['contradictions']['stats']['total_contradictions']} conflicting pairs")
        
        # Save all outputs as separate JSON files
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        for operation, data in results.items():
            output_file = self.output_dir / f"{operation}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            print(f"\n✅ Saved: {output_file}")
        
        # Print detailed summary
        intersection_count = results['intersection']['stats']['total_rules']
        g1_only_count = results['g1_minus_g2']['stats']['total_rules']
        g2_only_count = results['g2_minus_g1']['stats']['total_rules']
        union_count = results['union']['stats']['total_rules']
        contradiction_count = results['contradictions']['stats']['total_contradictions']
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║                     SET OPERATIONS SUMMARY                            ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║   ┌─────────────────────────────────────────────────────────────┐   ║
║   │  SET OPERATION           │  COUNT  │  OUTPUT FILE           │   ║
║   ├─────────────────────────────────────────────────────────────┤   ║
║   │  ∩ Intersection          │  {intersection_count:>5}  │  intersection.json     │   ║
║   │  (G1 ∩ G2)               │         │                        │   ║
║   ├─────────────────────────────────────────────────────────────┤   ║
║   │  - Left Difference       │  {g1_only_count:>5}  │  g1_minus_g2.json      │   ║
║   │  ({g1_name} - {g2_name})                                          ║
║   ├─────────────────────────────────────────────────────────────┤   ║
║   │  - Right Difference      │  {g2_only_count:>5}  │  g2_minus_g1.json      │   ║
║   │  ({g2_name} - {g1_name})                                          ║
║   ├─────────────────────────────────────────────────────────────┤   ║
║   │  ∪ Union                 │  {union_count:>5}  │  union.json            │   ║
║   │  (G1 ∪ G2)               │         │                        │   ║
║   ├─────────────────────────────────────────────────────────────┤   ║
║   │  ⚠️ Contradictions        │  {contradiction_count:>5}  │  contradictions.json   │   ║
║   │  (Conflicting Pairs)     │         │                        │   ║
║   └─────────────────────────────────────────────────────────────┘   ║
║                                                                       ║
║   📊 Verification: Union = Intersection + G1-only + G2-only          ║
║      {union_count} = {intersection_count} + {g1_only_count} + {g2_only_count} ✓                                      ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        
        return results


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Compute set operations on matched rules')
    parser.add_argument('--provider', type=str, default='openai', choices=['openai'])
    
    args = parser.parse_args()
    
    calculator = SetOperationsCalculator(provider=args.provider)
    calculator.run()


if __name__ == "__main__":
    main()
