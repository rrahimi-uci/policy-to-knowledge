#!/usr/bin/env python3
"""
Knowledge Graph Joins Pipeline

Orchestrates the rule-behavior-centric set operations process:
1. Agent 7: Cluster rules by behavior (HOW dimension)
2. Agent 8: Semantic rule matching with confidence
3. Agent 9: Set operations (G1 ∩ G2, G1 - G2, G2 - G1, G1 ∪ G2, CONTRADICTIONS)
4. Agent 10: Beautiful HTML visualizations for each operation

Set Operations:
    • Intersection (G1 ∩ G2): Rules present in both graphs
    • Left Difference (G1 - G2): Rules exclusive to G1
    • Right Difference (G2 - G1): Rules exclusive to G2
    • Union (G1 ∪ G2): All unique rules from both graphs
    • Contradictions: Conflicting rule pairs

Usage:
    python joins_pipeline.py --g1 <graph1> --g2 <graph2>
    python joins_pipeline.py --list  # List available graphs
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.agent_7_rule_type_clusterer import RuleBehaviorClusterer
from agents.agent_8_semantic_rule_matcher import SemanticRuleMatcher
from agents.agent_9_set_operations import SetOperationsCalculator
from agents.agent_10_set_visualization import SetOperationsVisualizer
from utils.config import get_config


def list_available_graphs(provider: str = "openai"):
    """List available knowledge graphs."""
    clusterer = RuleBehaviorClusterer(provider=provider)
    graphs = clusterer.get_available_graphs()
    
    print("\n📂 Available Knowledge Graphs:")
    print("=" * 50)
    
    for name in graphs:
        try:
            kg = clusterer.load_knowledge_graph(name)
            entity_count = len(kg.get('entities', []))
            rule_count = len(kg.get('business_rules', []))
            print(f"\n   📊 {name}")
            print(f"      Entities: {entity_count}")
            print(f"      Rules: {rule_count}")
        except Exception as e:
            print(f"\n   📊 {name}")
            print(f"      (Error loading: {e})")
    
    print("\n💡 Usage: python joins_pipeline.py --g1 <name> --g2 <name>")


def run_joins_pipeline(g1_name: str, g2_name: str, provider: str = "openai", workers: int = None, batch_size: int = None):
    """Run the full joins pipeline with BATCH processing."""
    config = get_config()
    workers = workers if workers is not None else config.get_join_max_workers()
    batch_size = batch_size if batch_size is not None else config.get_join_batch_size()
    # Create joins subfolder name
    joins_subfolder = f"{g1_name}_{g2_name}"
    
    print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║             KNOWLEDGE GRAPH JOINS PIPELINE                            ║
║             Set Operations: ∩, -, ∪, Contradictions (BATCH MODE)      ║
╚══════════════════════════════════════════════════════════════════════╝

📊 Comparing: {g1_name} vs {g2_name}
📁 Provider: {provider}
📂 Output folder: _joined/{joins_subfolder}/
👷 Workers: {workers}  |  📦 Batch size: {batch_size} pairs/call
🧠 Reasoning Effort: {get_config().get_reasoning_effort()}
""")
    
    # Step 1: Cluster rules by behavior (HOW)
    print("\n" + "=" * 70)
    print("STEP 1/4: Rule Behavior Clustering (HOW dimension)")
    print("=" * 70)
    
    clusterer = RuleBehaviorClusterer(provider=provider, g1_name=g1_name, g2_name=g2_name)
    cluster_result = clusterer.run(g1_name, g2_name)
    
    # Step 2: Semantic rule matching with BATCH processing
    print("\n" + "=" * 70)
    print("STEP 2/4: Semantic Rule Matching (LLM-based, BATCH PARALLEL)")
    print("=" * 70)
    
    matcher = SemanticRuleMatcher(provider=provider, max_workers=workers, batch_size=batch_size, merge_subfolder=joins_subfolder)
    match_result = matcher.run()
    
    # Step 3: Set operations (∩, -, ∪)
    print("\n" + "=" * 70)
    print("STEP 3/4: Computing Set Operations (∩, G1-G2, G2-G1, ∪)")
    print("=" * 70)
    
    calculator = SetOperationsCalculator(provider=provider, merge_subfolder=joins_subfolder)
    calculator.run()
    
    # Step 4: Visualizations for each operation
    print("\n" + "=" * 70)
    print("STEP 4/4: Generating Visualizations for All Operations")
    print("=" * 70)
    
    visualizer = SetOperationsVisualizer(provider=provider, merge_subfolder=joins_subfolder)
    visualizer.run()
    
    # Summary - use the dynamic joins_subfolder path
    output_dir = Path(__file__).parent / "pipeline-output" / provider / "_joined" / joins_subfolder / "agent-10-visualizations"
    
    print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║                     JOINS COMPLETE!                                   ║
╚══════════════════════════════════════════════════════════════════════╝

📊 Set Operations Results:
   ∩ Intersection (G1 ∩ G2): Rules present in both graphs
   - Left Difference (G1 - G2): Rules exclusive to {g1_name}
   - Right Difference (G2 - G1): Rules exclusive to {g2_name}
   ∪ Union (G1 ∪ G2): All unique rules from both graphs
   ⚠️ Contradictions: Conflicting rule pairs

📁 Output Location: {output_dir}

🌐 View Results:
   file://{(output_dir / 'index.html').absolute()}

📄 Individual Reports:
   • intersection.html - Shared rules (G1 ∩ G2)
   • g1_minus_g2.html  - {g1_name} exclusive rules
   • g2_minus_g1.html  - {g2_name} exclusive rules  
   • union.html        - All unique rules (G1 ∪ G2)
   • contradictions.html - Conflicting pairs
""")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Knowledge Graph Joins Pipeline - Set Operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List available graphs
    python joins_pipeline.py --list
    
    # Join two graphs (computes all set operations)
    python joins_pipeline.py --g1 optimized --g2 agent-4-rules
    
    # Use anthropic provider
    python joins_pipeline.py --g1 optimized --g2 agent-4-rules --provider anthropic
    
    # Use 20 parallel workers
    python joins_pipeline.py --g1 graphA --g2 FM --workers 20

Set Operations Computed:
    ∩ Intersection (G1 ∩ G2)  - Rules in both graphs
    - Left Diff (G1 - G2)     - Rules only in G1
    - Right Diff (G2 - G1)    - Rules only in G2
    ∪ Union (G1 ∪ G2)         - All unique rules
    ⚠️ Contradictions          - Conflicting pairs
        """
    )
    
    parser.add_argument('--list', action='store_true', help='List available knowledge graphs')
    parser.add_argument('--g1', type=str, help='First knowledge graph name')
    parser.add_argument('--g2', type=str, help='Second knowledge graph name')
    parser.add_argument('--provider', type=str, default='openai', choices=['openai', 'anthropic'],
                        help='LLM provider (default: openai)')
    config = get_config()
    parser.add_argument('--workers', type=int, default=None, 
                        help=f'Number of parallel workers for LLM calls (default: {config.get_join_max_workers()} from config)')
    parser.add_argument('--batch-size', type=int, default=None,
                        help=f'Number of pairs per LLM call for 10x speedup (default: {config.get_join_batch_size()} from config)')
    
    args = parser.parse_args()
    
    if args.list:
        list_available_graphs(args.provider)
    elif args.g1 and args.g2:
        run_joins_pipeline(args.g1, args.g2, args.provider, args.workers, args.batch_size)
    else:
        parser.print_help()
        print("\n❌ Error: Please provide --g1 and --g2, or use --list to see available graphs")
        sys.exit(1)


if __name__ == "__main__":
    main()
