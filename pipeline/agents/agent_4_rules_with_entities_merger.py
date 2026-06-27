#!/usr/bin/env python3
"""
Agent 4: Business Rules with Entities Merger

Merges the outputs from Agent 2 (entity definitions) and Agent 3 (business rules)
to create a complete knowledge graph with rules enriched with entity information.

Author: Reza Rahimi
Date: December 11, 2025
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Helper for real-time output
def _print(msg):
    """Print with immediate flush for real-time console output."""
    print(msg, flush=True)


class KnowledgeEnricher:
    """
    Enriches business rules with entity definitions to create a complete knowledge graph.
    """
    
    def __init__(self, entity_file: Path, rules_file: Path, output_dir: Path):
        """
        Initialize the Knowledge Enricher.
        
        Args:
            entity_file: Path to entity_types_and_relationships.json (Agent 2 output)
            rules_file: Path to compliance_rules_with_entities.json (Agent 3 output)
            output_dir: Directory to save merged output
        """
        self.entity_file = entity_file
        self.rules_file = rules_file
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.entity_types = {}
        self.relationships = []
        self.business_rules = []
        
    def load_data(self):
        """Load entity definitions and business rules."""
        print("\n" + "=" * 80, flush=True)
        print("🔗 AGENT 4: BUSINESS RULES WITH ENTITIES MERGER", flush=True)
        print("=" * 80, flush=True)
        print(f"\n📋 Purpose: Enrich business rules with entity/relationship definitions", flush=True)
        print(f"   This creates a complete knowledge graph structure.", flush=True)
        print(f"   Input: Entity definitions (Agent 2) + Business rules (Agent 3)", flush=True)
        print(f"   Output: Unified knowledge graph with enriched rules\n", flush=True)
        
        # Load entity definitions (Agent 2 output)
        print(f"{'='*60}", flush=True)
        print(f"📖 STEP 1: LOADING DATA", flush=True)
        print(f"{'='*60}", flush=True)
        print(f"\n   Loading entity definitions from: {self.entity_file.name}", flush=True)
        with open(self.entity_file, 'r', encoding='utf-8') as f:
            entity_data = json.load(f)
        
        # Agent 2 outputs simple entity/relationship definitions.
        # Key may be 'entity_types' (mortgage/base) or 'entities' (AML domain).
        # For list-format entities (AML), convert to a dict keyed by entity name.
        raw_entities = entity_data.get('entity_types') or entity_data.get('entities', {})
        if isinstance(raw_entities, list):
            self.entity_types = {e.get('name', e.get('entity_name', f'entity_{i}')): e for i, e in enumerate(raw_entities)}
        else:
            self.entity_types = raw_entities if isinstance(raw_entities, dict) else {}
        self.relationships = entity_data.get('relationships', {})
        
        print(f"   ✓ Loaded {len(self.entity_types)} entity types", flush=True)
        if self.entity_types:
            entity_names = list(self.entity_types.keys())[:5]
            print(f"     Sample entities: {', '.join(entity_names)}{'...' if len(self.entity_types) > 5 else ''}", flush=True)
        print(f"   ✓ Loaded {len(self.relationships)} relationships", flush=True)
        if self.relationships:
            if isinstance(self.relationships, dict):
                rel_names = list(self.relationships.keys())[:5]
            else:
                rel_names = [r.get('relationship_type', 'UNKNOWN') for r in self.relationships[:5]]
            print(f"     Sample relationships: {', '.join(rel_names)}{'...' if len(self.relationships) > 5 else ''}", flush=True)
        print(flush=True)
        
        # Load business rules (Agent 3 output - nested structure)
        print(f"📖 Loading business rules from: {self.rules_file}", flush=True)
        with open(self.rules_file, 'r', encoding='utf-8') as f:
            rules_data = json.load(f)
        
        # Agent 3 outputs nested structure: business_rules are inside entity_types and relationships
        # We need to extract and flatten them
        all_rules = []
        
        # Extract rules from entity_types
        entity_types_with_rules = rules_data.get('entity_types', {})
        for entity_name, entity_info in entity_types_with_rules.items():
            entity_rules = entity_info.get('business_rules', [])
            for rule in entity_rules:
                rule = dict(rule)  # shallow copy — don't mutate parsed JSON
                rule['entity_or_relationship'] = entity_name
                rule['entity_type'] = 'entity'
                all_rules.append(rule)

        # Extract rules from relationships
        relationships_with_rules = rules_data.get('relationships', {})
        for rel_name, rel_info in relationships_with_rules.items():
            rel_rules = rel_info.get('business_rules', [])
            for rule in rel_rules:
                rule = dict(rule)  # shallow copy — don't mutate parsed JSON
                rule['entity_or_relationship'] = rel_name
                rule['entity_type'] = 'relationship'
                all_rules.append(rule)

        # Normalize entity_or_relationship to Agent 2 canonical names where possible.
        # Agent 3 and Agent 2 often differ in naming convention
        # (e.g. "Financial Institution" vs "FINANCIAL_INSTITUTION"). Build a
        # case/whitespace/hyphen-insensitive lookup over both entity_types and
        # relationships keys, then remap any rule whose name resolves to a
        # canonical key that differs from the original.
        import re as _re
        def _norm(s: str) -> str:
            return _re.sub(r'[\s\-]+', '_', s.strip().upper())
        canonical_map = {_norm(k): k for k in self.entity_types}
        # Relationship names also get canonical lookup (entity keys take priority)
        if isinstance(self.relationships, dict):
            for rel_name in self.relationships:
                norm_key = _norm(rel_name)
                if norm_key not in canonical_map:
                    canonical_map[norm_key] = rel_name
        remapped = 0
        for rule in all_rules:
            orig = rule.get('entity_or_relationship', '')
            if orig:
                canonical = canonical_map.get(_norm(orig))
                if canonical and canonical != orig:
                    rule['entity_or_relationship'] = canonical
                    remapped += 1

        self.business_rules = all_rules
        print(f"   ✓ Extracted {len(all_rules)} business rules from nested structure", flush=True)
        print(f"      ({len([r for r in all_rules if r.get('entity_type') == 'entity'])} entity rules, {len([r for r in all_rules if r.get('entity_type') == 'relationship'])} relationship rules)", flush=True)
        if remapped:
            print(f"   ✓ Normalized {remapped} rule entity references to canonical Agent 2 names", flush=True)
        print(flush=True)
    
    def enrich_rules(self):
        """Enrich rules with entity/relationship information."""
        print("\n" + "="*60, flush=True)
        print("🔗 STEP 2: ENRICHING RULES", flush=True)
        print("="*60, flush=True)
        print(f"\n   📊 Total rules to process: {len(self.business_rules)}", flush=True)
        print(f"   📊 Entity definitions available: {len(self.entity_types)}", flush=True)
        print(f"   📊 Relationship definitions available: {len(self.relationships)}", flush=True)
        print(f"\n   ⏳ Enriching rules with entity/relationship context...", flush=True)
        enriched_rules = []
        enriched_count = 0
        
        for rule in self.business_rules:
            entity_or_rel_name = rule.get('entity_or_relationship', '')
            is_entity = rule.get('entity_type') == 'entity'
            
            # Add entity definition reference if it's an entity rule
            if is_entity and entity_or_rel_name in self.entity_types:
                entity_def = self.entity_types[entity_or_rel_name]
                rule['entity_definition'] = {
                    'description': entity_def.get('description', ''),
                    'key_attributes': entity_def.get('key_attributes', []),
                    'examples': entity_def.get('examples', [])
                }
            # Add relationship definition reference if it's a relationship rule
            elif not is_entity:
                # Find relationship definition
                rel_def = None
                # relationships is a dict keyed by relationship name
                if isinstance(self.relationships, dict):
                    rel_def = self.relationships.get(entity_or_rel_name)
                else:
                    # Fallback for list format
                    for rel in self.relationships:
                        if isinstance(rel, dict) and rel.get('relationship_type') == entity_or_rel_name:
                            rel_def = rel
                            break
                
                if rel_def:
                    rule['relationship_definition'] = {
                        'description': rel_def.get('description', ''),
                        'source_entity': rel_def.get('source_entity', ''),
                        'target_entity': rel_def.get('target_entity', ''),
                        'directionality': rel_def.get('directionality', ''),
                        'examples': rel_def.get('examples', [])
                    }
            
            enriched_rules.append(rule)
            
            # Progress indicator every 50 rules
            if len(enriched_rules) % 50 == 0:
                pct = (len(enriched_rules) / len(self.business_rules)) * 100
                print(f"      [{len(enriched_rules)}/{len(self.business_rules)}] ({pct:.0f}%) rules enriched...", flush=True)
        
        entity_enriched = len([r for r in enriched_rules if 'entity_definition' in r])
        rel_enriched = len([r for r in enriched_rules if 'relationship_definition' in r])
        
        print(f"\n   ✅ Enrichment complete:", flush=True)
        print(f"      • Total rules processed: {len(enriched_rules)}", flush=True)
        print(f"      • Rules with entity definitions: {entity_enriched}", flush=True)
        print(f"      • Rules with relationship definitions: {rel_enriched}", flush=True)
        print(flush=True)
        
        return enriched_rules
    
    def create_merged_output(self, enriched_rules):
        """Create merged output data structure."""
        merged_data = {
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'source_entity_file': str(self.entity_file),
                'source_rules_file': str(self.rules_file),
                'agent': 'Agent 4 - Rules with Entities Merger',
                'description': 'Business rules enriched with entity and relationship definitions',
                'version': '2.0'
            },
            'entity_types': self.entity_types,
            'relationships': self.relationships,
            'business_rules': enriched_rules,
            'statistics': {
                'total_entities': len(self.entity_types),
                'total_relationships': len(self.relationships),
                'total_rules': len(enriched_rules),
                'entity_rules': len([r for r in enriched_rules if r.get('entity_type') == 'entity']),
                'relationship_rules': len([r for r in enriched_rules if r.get('entity_type') == 'relationship']),
                'rules_by_entity': {},
                'rules_by_type': {}
            }
        }
        
        # Calculate rules by entity/relationship
        for rule in enriched_rules:
            entity_or_rel = rule.get('entity_or_relationship', 'Unknown')
            if entity_or_rel not in merged_data['statistics']['rules_by_entity']:
                merged_data['statistics']['rules_by_entity'][entity_or_rel] = 0
            merged_data['statistics']['rules_by_entity'][entity_or_rel] += 1
            
            # Calculate rules by type
            rule_type = rule.get('rule_type', 'unknown')
            if rule_type not in merged_data['statistics']['rules_by_type']:
                merged_data['statistics']['rules_by_type'][rule_type] = 0
            merged_data['statistics']['rules_by_type'][rule_type] += 1
        
        return merged_data
    
    def save_outputs(self, merged_data):
        """Save merged data to JSON and CSV files."""
        print("="*60, flush=True)
        print("💾 STEP 3: SAVING OUTPUTS", flush=True)
        print("="*60, flush=True)
        
        # Save merged JSON
        output_json = self.output_dir / "compliance_knowledge_graph.json"
        print(f"\n   📄 Saving JSON: {output_json.name}", flush=True)
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, indent=2, ensure_ascii=False)
        print(f"      ✓ JSON saved ({len(merged_data['business_rules'])} rules)", flush=True)
        print(flush=True)
        
        return output_json
    
    def print_summary(self, merged_data, output_json):
        """Print summary of merge operation."""
        print("=" * 80, flush=True)
        print("✅ MERGE COMPLETE", flush=True)
        print("=" * 80, flush=True)
        print(flush=True)
        print("📊 Summary:", flush=True)
        print(f"   • Entity Types:        {merged_data['statistics']['total_entities']}", flush=True)
        print(f"   • Relationships:       {merged_data['statistics']['total_relationships']}", flush=True)
        print(f"   • Total Rules:         {merged_data['statistics']['total_rules']}", flush=True)
        print(f"      - Entity Rules:     {merged_data['statistics']['entity_rules']}", flush=True)
        print(f"      - Relationship Rules: {merged_data['statistics']['relationship_rules']}", flush=True)
        print(flush=True)
        print("📁 Output Files:", flush=True)
        print(f"   • {output_json}", flush=True)
        print(flush=True)
        print("📋 Top 10 Rules by Entity/Relationship:", flush=True)
        sorted_rules = sorted(merged_data['statistics']['rules_by_entity'].items(), 
                            key=lambda x: x[1], reverse=True)[:10]
        for entity, count in sorted_rules:
            print(f"   • {entity}: {count} rules", flush=True)
        print(flush=True)
        print("\n📊 Rules by Type:", flush=True)
        for rule_type, count in sorted(merged_data['statistics']['rules_by_type'].items(), 
                                       key=lambda x: x[1], reverse=True):
            print(f"   • {rule_type}: {count}", flush=True)
        print(flush=True)
    
    def run(self):
        """Execute the complete enrichment process."""
        self.load_data()
        enriched_rules = self.enrich_rules()
        merged_data = self.create_merged_output(enriched_rules)
        output_json = self.save_outputs(merged_data)
        self.print_summary(merged_data, output_json)


def main():
    """Main entry point."""
    from utils.config import get_config
    
    config = get_config()
    
    # Input files
    entity_file = config.get_entity_relationship_dir() / "entity_types_and_relationships.json"
    rules_file = config.get_rules_extracted_dir() / "compliance_rules_with_entities.json"
    
    # Output directory
    output_dir = config.get_rules_with_entities_dir()
    
    # Check if input files exist
    if not entity_file.exists():
        print(f"❌ Error: Entity definitions file not found: {entity_file}", flush=True)
        print("   Please run Agent 2 (entity extraction) first.", flush=True)
        sys.exit(1)
    
    if not rules_file.exists():
        print(f"❌ Error: Business rules file not found: {rules_file}", flush=True)
        print("   Please run Agent 3 (rules extraction) first.", flush=True)
        sys.exit(1)
    
    # Create enricher and run
    enricher = KnowledgeEnricher(entity_file, rules_file, output_dir)
    enricher.run()


if __name__ == "__main__":
    main()
