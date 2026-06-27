#!/usr/bin/env python3
"""
Rule Behavior Clusterer (Agent 7)

Groups rules from two knowledge graphs by their 8 rule behaviors (HOW):
- formula      - Defines a calculation
- classification - Defines a category or type
- threshold    - Specifies a numeric min/max limit
- prohibition  - Forbids something
- timing       - Specifies a deadline or time window
- sequence     - Requires a specific order of operations
- method       - Specifies HOW to verify or execute
- mandate      - Requires something to exist or be provided

This enables efficient behavior-specific comparison in the next stage.

Author: Reza Rahimi
Date: December 20, 2025
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import get_config


# Valid rule behaviors (HOW dimension) - 8 mutually exclusive categories
RULE_BEHAVIORS = [
    'formula',
    'classification',
    'threshold',
    'prohibition',
    'timing',
    'sequence',
    'method',
    'mandate'
]

# Legacy rule_type mapping to new rule_behavior (for backward compatibility)
LEGACY_TYPE_TO_BEHAVIOR = {
    'eligibility': 'threshold',  # Most eligibility rules are thresholds
    'constraint': 'threshold',   # Constraints are typically thresholds
    'compliance': 'mandate',     # Compliance rules are mandates
    'validation': 'method',      # Validation specifies how to verify
    'documentation': 'mandate',  # Documentation rules require forms
    'process': 'sequence',       # Process rules define sequences
    'calculation': 'formula',    # Calculation rules define formulas
    # Mortgage-specific rule types
    'prohibition': 'prohibition',# Explicit prohibitions (OFAC, shell companies)
    'definition': 'classification', # Term definitions classify concepts
    'exception': 'classification',  # Exceptions classify special-case waivers
    # AML-specific rule types
    'reporting': 'mandate',      # CTR/SAR/FBAR filing obligations
    'monitoring': 'method',      # Transaction monitoring rules
    'screening': 'method',       # OFAC/PEP/sanctions screening
    'investigation': 'sequence', # SAR investigation workflows
    'onboarding': 'sequence',    # KYC/CDD onboarding procedures
    # Healthcare-specific rule types
    'clinical_guideline': 'mandate',       # Evidence-based clinical standards
    'patient_safety': 'prohibition',       # Safety protocols & adverse event prevention
    'hipaa_privacy': 'mandate',            # PHI privacy & security requirements
    'billing_compliance': 'method',        # Coding accuracy & claims compliance
    'consent_requirement': 'mandate',      # Informed consent & authorization
    'credentialing': 'mandate',            # Provider credentialing & privileging
    'quality_measure': 'method',           # Quality reporting & performance metrics
    'regulatory': 'mandate',              # CMS/TJC/state regulatory requirements
    # Commercial lending-specific rule types
    'credit_policy': 'threshold',          # Borrower qualification & underwriting standards
    'collateral': 'threshold',             # LTV/LTC limits & appraisal requirements
    'covenant': 'threshold',               # Financial maintenance covenants & tests
    'underwriting': 'method',              # DSCR/cash flow methodology & stress testing
    'risk_assessment': 'method',           # Loan grading, concentration & portfolio monitoring
    'compliance': 'mandate',               # BSA/AML/OFAC & fair lending requirements
    'pricing': 'threshold',                # Rate floors, spreads & pricing exception rules
}


class RuleBehaviorClusterer:
    """
    Groups rules from two knowledge graphs by rule type for efficient comparison.
    """
    
    def __init__(self, provider: str = "openai", g1_name: str = None, g2_name: str = None):
        """
        Initialize the clusterer.
        
        Args:
            provider: The provider folder (openai/anthropic)
            g1_name: Name of the first graph (for subfolder naming)
            g2_name: Name of the second graph (for subfolder naming)
        """
        self.provider = provider
        self.g1_name = g1_name
        self.g2_name = g2_name
        self.base_path = Path(__file__).parent.parent / "pipeline-output" / provider
        
        # Create subfolder based on graph names if provided
        if g1_name and g2_name:
            self.merge_subfolder = f"{g1_name}_{g2_name}"
        else:
            self.merge_subfolder = None
        
        self._setup_output_dir()
        
    def _setup_output_dir(self):
        """Set up output directory based on graph names."""
        if self.merge_subfolder:
            self.output_dir = self.base_path / "_merged" / self.merge_subfolder / "agent-7-rule-clusters"
        else:
            self.output_dir = self.base_path / "_merged" / "agent-7-rule-clusters"
    
    def set_graph_names(self, g1_name: str, g2_name: str):
        """Set graph names and update output directory."""
        self.g1_name = g1_name
        self.g2_name = g2_name
        self.merge_subfolder = f"{g1_name}_{g2_name}"
        self._setup_output_dir()
    
    def get_available_graphs(self) -> List[str]:
        """Get list of available knowledge graphs (document folders)."""
        graphs = []
        for item in self.base_path.iterdir():
            if item.is_dir() and not item.name.startswith('_'):
                kg_path = item / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
                if kg_path.exists():
                    graphs.append(item.name)
        return sorted(graphs)
    
    def load_knowledge_graph(self, graph_name: str) -> dict:
        """Load a knowledge graph by name."""
        kg_path = self.base_path / graph_name / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
        if not kg_path.exists():
            raise FileNotFoundError(f"Knowledge graph not found: {kg_path}")
        
        with open(kg_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def cluster_rules_by_behavior(self, kg: dict, graph_name: str) -> Dict[str, List[dict]]:
        """
        Cluster rules by their rule_behavior (HOW dimension).
        
        Args:
            kg: Knowledge graph dict
            graph_name: Name of the source graph
            
        Returns:
            Dict mapping rule_behavior to list of rules
        """
        clusters = {rb: [] for rb in RULE_BEHAVIORS}
        clusters['unknown'] = []  # For rules without valid behavior
        
        rules = kg.get('business_rules', [])
        
        for rule in rules:
            # Support both new rule_behavior and legacy rule_type
            rule_behavior = rule.get('rule_behavior', '').lower().strip()
            
            # Fallback to legacy rule_type with mapping
            if not rule_behavior or rule_behavior not in RULE_BEHAVIORS:
                legacy_type = rule.get('rule_type', '').lower().strip()
                rule_behavior = LEGACY_TYPE_TO_BEHAVIOR.get(legacy_type, '')
            
            # Add source graph metadata
            rule_with_source = rule.copy()
            rule_with_source['_source_graph'] = graph_name
            
            if rule_behavior in RULE_BEHAVIORS:
                clusters[rule_behavior].append(rule_with_source)
            else:
                clusters['unknown'].append(rule_with_source)
        
        return clusters
    
    def run(self, g1_name: str, g2_name: str) -> dict:
        """
        Run the clustering process for two graphs.
        
        Args:
            g1_name: Name of the first graph
            g2_name: Name of the second graph
            
        Returns:
            Clustering results dict
        """
        # Update graph names and output directory
        self.set_graph_names(g1_name, g2_name)
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   Rule Behavior Clusterer (Agent 7)                                   ║
║   Grouping Rules by Behavior for Pairwise Comparison                  ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        
        print(f"📊 Loading knowledge graphs...")
        print(f"   G1: {g1_name}")
        print(f"   G2: {g2_name}")
        print(f"   Output: {self.output_dir}")
        
        # Load both graphs
        kg1 = self.load_knowledge_graph(g1_name)
        kg2 = self.load_knowledge_graph(g2_name)
        
        # Cluster by behavior (HOW dimension)
        print(f"\n🔄 Clustering rules by behavior (HOW)...")
        clusters_g1 = self.cluster_rules_by_behavior(kg1, g1_name)
        clusters_g2 = self.cluster_rules_by_behavior(kg2, g2_name)
        
        # Build output
        result = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'g1_name': g1_name,
                'g2_name': g2_name,
                'provider': self.provider
            },
            'g1_entities': kg1.get('entities', []),
            'g2_entities': kg2.get('entities', []),
            'clusters': {},
            'stats': {
                'g1_total': sum(len(clusters_g1[rb]) for rb in RULE_BEHAVIORS),
                'g2_total': sum(len(clusters_g2[rb]) for rb in RULE_BEHAVIORS),
                'g1_unknown': len(clusters_g1['unknown']),
                'g2_unknown': len(clusters_g2['unknown']),
                'by_behavior': {}
            }
        }
        
        # Build clusters for each behavior
        print(f"\n📋 Rule counts by behavior (HOW):")
        print(f"   {'Behavior':<15} {'G1':>8} {'G2':>8} {'Total':>8}")
        print(f"   {'-'*15} {'-'*8} {'-'*8} {'-'*8}")
        
        for rule_behavior in RULE_BEHAVIORS:
            g1_rules = clusters_g1[rule_behavior]
            g2_rules = clusters_g2[rule_behavior]
            
            result['clusters'][rule_behavior] = {
                'g1_rules': g1_rules,
                'g2_rules': g2_rules,
                'g1_count': len(g1_rules),
                'g2_count': len(g2_rules)
            }
            
            result['stats']['by_behavior'][rule_behavior] = {
                'g1': len(g1_rules),
                'g2': len(g2_rules)
            }
            
            print(f"   {rule_behavior:<15} {len(g1_rules):>8} {len(g2_rules):>8} {len(g1_rules) + len(g2_rules):>8}")
        
        # Handle unknown behaviors
        if clusters_g1['unknown'] or clusters_g2['unknown']:
            result['clusters']['unknown'] = {
                'g1_rules': clusters_g1['unknown'],
                'g2_rules': clusters_g2['unknown'],
                'g1_count': len(clusters_g1['unknown']),
                'g2_count': len(clusters_g2['unknown'])
            }
            print(f"   {'unknown':<15} {len(clusters_g1['unknown']):>8} {len(clusters_g2['unknown']):>8}")
        
        print(f"\n   {'TOTAL':<15} {result['stats']['g1_total']:>8} {result['stats']['g2_total']:>8}")
        
        # Save output
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / "rule_clusters.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, default=str)
        
        print(f"\n✅ Clusters saved to: {output_file}")
        
        return result


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Cluster rules by behavior for two knowledge graphs')
    parser.add_argument('--provider', type=str, default='openai', choices=['openai', 'anthropic'])
    parser.add_argument('--g1', type=str, help='Name of first graph (folder name)')
    parser.add_argument('--g2', type=str, help='Name of second graph (folder name)')
    parser.add_argument('--list', action='store_true', help='List available graphs')
    
    args = parser.parse_args()
    
    clusterer = RuleBehaviorClusterer(provider=args.provider)
    
    if args.list:
        print("Available knowledge graphs:")
        for g in clusterer.get_available_graphs():
            print(f"  - {g}")
        return
    
    if not args.g1 or not args.g2:
        available = clusterer.get_available_graphs()
        print("Available knowledge graphs:")
        for i, g in enumerate(available):
            print(f"  {i+1}. {g}")
        
        if len(available) >= 2:
            print(f"\nUsage: python {__file__} --g1 {available[0]} --g2 {available[1]}")
        return
    
    clusterer.run(args.g1, args.g2)


if __name__ == "__main__":
    main()
