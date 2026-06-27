"""
Compliance Knowledge Graph Optimizer Agent

This agent optimizes the extracted business rules by:
1. Deduplicating rationally identical rules (keeping minor variations)
2. Analyzing dependencies between rules
3. Creating optimized output with dependency graph and rationale

Uses OpenAI GPT-5 reasoning model for deep analysis.

Author: Reza Rahimi
Date: December 20, 2025
"""

import json
import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.prompt_manager import get_prompt_manager
from utils.llm_client import create_llm_client
from utils.config import get_config
from utils.rule_uniqueness import enforce_rule_uniqueness

# Helper for real-time output
def _print(msg):
    """Print with immediate flush for real-time console output."""
    print(msg, flush=True)


class KnowledgeGraphOptimizer:
    """
    Agent that optimizes business rules knowledge graph using LLM reasoning.
    
    Features:
    - Conservative deduplication (only removes truly identical rules)
    - Dependency analysis (prerequisite, sequential, conditional, etc.)
    - Detailed rationale for all optimization decisions
    """
    
    def __init__(self, api_key: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None):
        """
        Initialize the optimizer.
        
        Args:
            api_key: API key for LLM provider
            model: Optional override for reasoning model
            reasoning_effort: Optional override for reasoning effort level (low/medium/high)
        """
        self.config = get_config()
        self.model = model or self.config.get_optimizer_model_name()
        self.reasoning_effort = reasoning_effort or self.config.get_reasoning_effort()
        self.client = create_llm_client(
            api_key=api_key,
            model=self.model,
            timeout=self.config.get_timeout(),
            max_retries=self.config.get_max_retries()
        )
        self.prompt_manager = get_prompt_manager()
        self.max_workers = int(os.environ.get('MAX_WORKERS', '1'))
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   Compliance Knowledge Graph Optimizer                              ║
║   Deduplication + Dependency Analysis with LLM Reasoning            ║
╚══════════════════════════════════════════════════════════════════════╝
""", flush=True)
        print(f"Configuration:", flush=True)
        print(f"  Model: {self.model}", flush=True)
        print(f"  Reasoning Effort: {self.reasoning_effort}", flush=True)
        print(f"  Workers: {self.max_workers}", flush=True)
    
    def _calculate_dependency_confidence(self, confidence_breakdown: dict) -> dict:
        """Calculate overall dependency confidence score from breakdown components."""
        if isinstance(confidence_breakdown, (int, float)):
            return {'overall_score': confidence_breakdown}
        
        weights = {
            'semantic_similarity': 0.25,
            'logical_connection': 0.30,
            'temporal_ordering': 0.20,
            'cross_reference': 0.15,
            'domain_relevance': 0.10
        }
        
        total_score = 0
        total_weight = 0
        
        for key, weight in weights.items():
            if key in confidence_breakdown:
                total_score += confidence_breakdown[key] * weight
                total_weight += weight
        
        # If no standard keys found, try to average whatever is there
        if total_weight == 0 and confidence_breakdown:
            values = [v for v in confidence_breakdown.values() if isinstance(v, (int, float))]
            if values:
                total_score = sum(values) / len(values)
                total_weight = 1
        
        overall = round(total_score / total_weight, 2) if total_weight > 0 else 50
        
        return {
            'overall_score': overall,
            'breakdown': confidence_breakdown
        }
    
    def load_business_rules(self, input_file: Path) -> Dict[str, Any]:
        """Load business rules from consolidated JSON file."""
        print(f"\n{'='*70}", flush=True)
        print(f"📖 LOADING BUSINESS RULES", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"   Source file: {input_file.name}", flush=True)
        print(f"   Full path: {input_file}", flush=True)
        
        if not input_file.exists():
            raise FileNotFoundError(f"Business rules file not found: {input_file}")
        
        print(f"\n   ⏳ Reading JSON file...", flush=True)
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Use top-level business_rules array (Agent 4 output format)
        # entity_types.business_rules contains rule IDs, not full rule objects
        rules = data.get('business_rules', [])
        
        print(f"\n   ✅ Data loaded successfully!", flush=True)
        print(f"   ┌──────────────────────────────────────┐", flush=True)
        print(f"   │ Business Rules:  {len(rules):>6}              │", flush=True)
        print(f"   │ Entity Types:    {len(data.get('entity_types', {})):>6}              │", flush=True)
        print(f"   │ Relationships:   {len(data.get('relationships', {})):>6}              │", flush=True)
        print(f"   └──────────────────────────────────────┘", flush=True)
        
        # Show rule type distribution if available
        if rules:
            rule_types = {}
            for rule in rules:
                rt = rule.get('rule_type', 'unknown')
                rule_types[rt] = rule_types.get(rt, 0) + 1
            print(f"\n   📊 Rule Distribution:", flush=True)
            print(f"      By Type: {', '.join(f'{k}({v})' for k, v in sorted(rule_types.items(), key=lambda x: -x[1])[:7])}", flush=True)
        
        return data
    
    def deduplicate_rules(self, rules: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Deduplicate rationally identical rules using GPT-5 reasoning.
        
        Returns:
            - Deduplicated rules list
            - Deduplication metadata with rationale
        """
        print(f"\n{'='*70}", flush=True)
        print(f"STEP 1: Deduplicating Business Rules", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"Analyzing {len(rules)} rules for rational duplicates...", flush=True)
        print(f"Strategy: Conservative - only remove truly identical rules", flush=True)
        print(f"📊 Preparing {len(rules)} rules for deduplication analysis...", flush=True)
        
        # Prepare rules summary for analysis
        rules_summary = []
        for rule in rules:
            rules_summary.append({
                'rule_id': rule.get('rule_id'),
                'rule_type': rule.get('rule_type'),
                'title': rule.get('title'),
                'description': rule.get('description', '')[:self.config.get_optimizer_description_truncation_length()],
                'conditions': rule.get('conditions', []),
                'consequences': rule.get('consequences', [])
            })
        
        rules_json = json.dumps(rules_summary, indent=2)
        total_rules = len(rules)
        
        prompt = self.prompt_manager.format_prompt(
            "rule_deduplication",
            rules_json=rules_json,
            total_rules=total_rules
        )
        
        print(f"\n🤖 Calling LLM for deduplication analysis...", flush=True)
        print(f"   • Model: {self.model}", flush=True)
        print(f"   • Rules to analyze: {len(rules)}", flush=True)
        print(f"   • Prompt size: ~{len(rules_json)//4:,} tokens", flush=True)
        print(f"   • Strategy: Conservative (only remove truly identical rules)", flush=True)
        print(f"\n   ⏳ Processing (this may take 1-2 minutes)...", flush=True)
        print(f"      → Sending request to {self.model}...", flush=True)
        
        try:
            # Use configured reasoning model for deduplication
            print(f"      → Using {self.model} for deduplication...", flush=True)
            
            response = self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.get_optimizer_dedup_temperature(),
                max_tokens=self.config.get_optimizer_dedup_max_tokens(),
                reasoning_effort=self.reasoning_effort
            )
            result_text = response.choices[0].message.content
            if not result_text:
                print(f"      ⚠️ Empty response from model (reasoning may have exhausted token budget)", flush=True)
                return rules, {"error": "Empty response from model", "duplicate_groups": [], "statistics": {}}
            print(f"      ✓ Response received ({len(result_text):,} characters)", flush=True)
            print(f"      → Parsing JSON response...", flush=True)
            
            # Parse JSON response
            dedup_result = self._parse_json_response(result_text)
            dup_groups = len(dedup_result.get('duplicate_groups', []))
            print(f"      ✓ Found {dup_groups} duplicate groups", flush=True)
            
        except Exception as e:
            print(f"❌ Error during deduplication: {e}", flush=True)
            return rules, {"error": str(e), "duplicate_groups": [], "statistics": {}}
        
        # Apply deduplication
        rules_to_remove = set()
        enhanced_rules = {}
        
        # Build rule lookup for collecting source_references from duplicates
        rule_lookup = {rule.get("rule_id"): rule for rule in rules}
        
        for group in dedup_result.get("duplicate_groups", []):
            primary_id = group["primary_rule_id"]
            duplicates = group["duplicate_rule_ids"]
            rules_to_remove.update(duplicates)
            
            # Collect all source_references from primary + duplicates into an array
            collected_refs = []
            for rid in [primary_id] + duplicates:
                r = rule_lookup.get(rid)
                if not r:
                    continue
                ref = r.get('source_reference', r.get('fannie_mae_reference', ''))
                if isinstance(ref, dict) and ref.get('chunk_path'):
                    collected_refs.append(ref)
                elif isinstance(ref, list):
                    collected_refs.extend(ref)
                elif isinstance(ref, str) and ref:
                    collected_refs.append(ref)
            
            # Store enhanced information for primary rule
            enhanced_rules[primary_id] = {
                "merged_description": group["merged_description"],
                "deduplication_info": {
                    "merged_from": duplicates,
                    "merge_count": len(duplicates),
                    "rationale": group["rationale"],
                    "confidence": group.get("confidence", "medium"),
                    "similarity_score": group.get("similarity_score"),
                    "score_breakdown": group.get("score_breakdown", {}),
                    "primary_selection_reason": group.get("primary_selection_reason", "")
                },
                "merged_examples": group.get("merged_examples", []),
                "collected_references": collected_refs
            }
        
        # Build deduplicated list
        deduplicated_rules = []
        for rule in rules:
            rule_id = rule.get("rule_id")
            
            if rule_id in rules_to_remove:
                continue  # Skip removed duplicates
            
            # Enhance primary rules with merged information
            if rule_id in enhanced_rules:
                rule["description"] = enhanced_rules[rule_id]["merged_description"]
                rule["deduplication_info"] = enhanced_rules[rule_id]["deduplication_info"]
                # Apply merged examples if available
                if enhanced_rules[rule_id].get("merged_examples"):
                    rule["examples"] = enhanced_rules[rule_id]["merged_examples"]
                # Update source_reference with collected references from all merged rules
                collected = enhanced_rules[rule_id].get("collected_references", [])
                if collected:
                    if len(collected) == 1:
                        # Single reference — keep as-is (object or string)
                        rule["source_reference"] = collected[0]
                    else:
                        # Multiple references — store as array
                        rule["source_reference"] = collected
            
            deduplicated_rules.append(rule)
        
        metadata = {
            "deduplication_analysis": dedup_result,
            "rules_removed_ids": list(rules_to_remove),
            "total_removed": len(rules_to_remove),
            "rules_remaining": len(deduplicated_rules)
        }
        
        print(f"\n{'='*50}", flush=True)
        print(f"✅ DEDUPLICATION COMPLETE", flush=True)
        print(f"{'='*50}", flush=True)
        print(f"   • Original rules:       {len(rules):>6}", flush=True)
        print(f"   • Duplicate groups:     {len(dedup_result.get('duplicate_groups', [])):>6}", flush=True)
        print(f"   • Rules removed:        {len(rules_to_remove):>6}", flush=True)
        print(f"   • Rules remaining:      {len(deduplicated_rules):>6}", flush=True)
        print(f"   • Reduction:            {(len(rules_to_remove)/len(rules)*100):.1f}%" if len(rules) > 0 else "   • Reduction:            0.0%", flush=True)
        
        return deduplicated_rules, metadata
    
    def analyze_dependencies(self, rules: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Analyze dependencies between business rules using GPT-5 reasoning.
        Uses batching for large rule sets to avoid token limits.
        
        Returns:
            - Rules with dependency information added
            - Dependency analysis metadata
        """
        print(f"\n{'='*70}", flush=True)
        print(f"STEP 2: Analyzing Rule Dependencies", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"Analyzing {len(rules)} rules for dependencies...", flush=True)
        
        # Determine if batching is needed (threshold: 100 rules)
        BATCH_SIZE = self.config.get_optimizer_batch_size()
        if len(rules) > 100:
            print(f"📦 Large rule set detected - using batched analysis", flush=True)
            print(f"   Batch size: {BATCH_SIZE} rules per batch", flush=True)
            print(f"   Using {self.model} for dependency analysis", flush=True)
            return self._analyze_dependencies_batched(rules, BATCH_SIZE)
        
        # Original single-batch analysis for smaller rule sets
        print(f"📊 Preparing {len(rules)} rules for dependency analysis...", flush=True)
        
        # Prepare rules for analysis
        rules_summary = []
        for rule in rules:
            rules_summary.append({
                'rule_id': rule.get('rule_id'),
                'rule_type': rule.get('rule_type'),
                'title': rule.get('title'),
                'description': rule.get('description', '')[:self.config.get_optimizer_description_truncation_length()],
                'conditions': rule.get('conditions', []),
                'consequences': rule.get('consequences', []),
                'related_entities': rule.get('related_entities', [])
            })
        
        rules_json = json.dumps(rules_summary, indent=2)
        total_rules = len(rules)
        
        prompt = self.prompt_manager.format_prompt(
            "dependency_analysis",
            rules_json=rules_json,
            total_rules=total_rules
        )
        
        prompt_size = len(prompt)
        print(f"\n🤖 Calling {self.model} for dependency analysis...", flush=True)
        print(f"   • Rules to analyze: {len(rules)}", flush=True)
        print(f"   • Prompt size: {prompt_size:,} characters (~{prompt_size//4:,} tokens)", flush=True)
        print(f"   • Looking for: prerequisite, sequential, conditional, complementary relationships", flush=True)
        print(f"\n   ⏳ Processing (this may take 1-2 minutes)...", flush=True)
        print(f"      → Sending request to {self.model}...", flush=True)
        
        try:
            response = self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.get_optimizer_dependency_temperature(),
                max_tokens=self.config.get_optimizer_dependency_max_tokens(),
                reasoning_effort=self.reasoning_effort
            )
            
            if not response or not response.choices:
                print(f"⚠️  Warning: Empty or invalid response from model", flush=True)
                return rules, {"error": "Empty or invalid response from model", "dependencies": [], "statistics": {}}
            
            result_text = response.choices[0].message.content
            
            # Debug: Log response for troubleshooting
            if not result_text or len(result_text.strip()) == 0:
                print(f"⚠️  Warning: Empty response from model", flush=True)
                return rules, {"error": "Empty response from model", "dependencies": [], "statistics": {}}
            
            print(f"      ✓ Response received ({len(result_text):,} characters)", flush=True)
            print(f"      → Parsing JSON response...", flush=True)
            
            # Parse JSON response
            dep_result = self._parse_json_response(result_text)
            dep_count = len(dep_result.get('dependencies', []))
            print(f"      ✓ Found {dep_count} dependencies", flush=True)
            
        except Exception as e:
            print(f"❌ Error during dependency analysis: {e}", flush=True)
            return rules, {"error": str(e), "dependencies": [], "statistics": {}}
        
        # Add dependencies to rules with confidence calculation
        rule_dependencies_map = {}
        rule_dependents_map = {}
        
        for dep in dep_result.get("dependencies", []):
            source_id = dep["source_rule_id"]
            target_id = dep["target_rule_id"]
            
            # Calculate confidence if breakdown provided
            if 'confidence' in dep and isinstance(dep['confidence'], dict):
                dep['confidence'] = self._calculate_dependency_confidence(dep['confidence'])
            elif 'confidence' not in dep:
                # Default confidence as int (consistent with batched path)
                dep['confidence'] = dep.get('strength', 3) * 20

            # Track what each rule depends on
            if target_id not in rule_dependencies_map:
                rule_dependencies_map[target_id] = []
            rule_dependencies_map[target_id].append({
                "depends_on_rule": source_id,
                "dependency_type": dep["dependency_type"],
                "rationale": dep["rationale"],
                "impact_if_fails": dep.get("impact", "Unknown"),
                "strength": dep.get("strength", "medium"),
                "confidence": dep.get("confidence", 60),
            })
            
            # Track what depends on each rule
            if source_id not in rule_dependents_map:
                rule_dependents_map[source_id] = []
            rule_dependents_map[source_id].append({
                "dependent_rule": target_id,
                "dependency_type": dep["dependency_type"]
            })
        
        # Enhance rules with dependency information
        rules_with_deps = []
        for rule in rules:
            rule_id = rule.get("rule_id")
            
            # Add dependencies (what this rule depends on)
            if rule_id in rule_dependencies_map:
                rule["dependencies"] = rule_dependencies_map[rule_id]
            
            # Add dependents (what depends on this rule)
            if rule_id in rule_dependents_map:
                rule["dependent_rules"] = rule_dependents_map[rule_id]
            
            rules_with_deps.append(rule)
        
        metadata = {
            "dependency_analysis": dep_result,
            "total_dependencies": len(dep_result.get("dependencies", [])),
            "dependency_chains": dep_result.get("dependency_chains", []),
            "circular_dependencies": dep_result.get("circular_dependencies", []),
            "conflicts": dep_result.get("conflict_groups", []),
            "rules_with_dependencies": len(rule_dependencies_map),
            "rules_with_dependents": len(rule_dependents_map)
        }
        
        print(f"\n{'='*50}", flush=True)
        print(f"✅ DEPENDENCY ANALYSIS COMPLETE", flush=True)
        print(f"{'='*50}", flush=True)
        print(f"   • Dependencies found:      {len(dep_result.get('dependencies', [])):>5}", flush=True)
        print(f"   • Dependency chains:       {len(dep_result.get('dependency_chains', [])):>5}", flush=True)
        print(f"   • Circular dependencies:   {len(dep_result.get('circular_dependencies', [])):>5}", flush=True)
        print(f"   • Potential conflicts:     {len(dep_result.get('conflict_groups', [])):>5}", flush=True)
        print(f"   • Rules with dependencies: {len(rule_dependencies_map):>5}", flush=True)
        print(f"   • Rules with dependents:   {len(rule_dependents_map):>5}", flush=True)
        
        return rules_with_deps, metadata
    
    def _analyze_dependencies_batched(self, rules: List[Dict[str, Any]], batch_size: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Analyze dependencies in batches to handle large rule sets.
        
        Process:
        1. Split rules into batches of `batch_size`
        2. Analyze dependencies within each batch
        3. Analyze cross-batch dependencies (batch A rules → batch B rules)
        4. Merge all results
        """
        import math
        
        num_batches = math.ceil(len(rules) / batch_size)
        print(f"   Total batches: {num_batches}", flush=True)
        print(f"   Rules per batch: ~{batch_size}", flush=True)
        
        all_dependencies = []
        
        # Create rule batches
        batches = []
        for i in range(0, len(rules), batch_size):
            batch = rules[i:i + batch_size]
            batches.append(batch)
        
        # Step 1: Analyze within-batch dependencies (parallelised)
        workers = min(self.max_workers, num_batches)
        print(f"\n📦 Step 1: Analyzing within-batch dependencies ({num_batches} batches, {workers} workers)...", flush=True)

        def _call_within_batch(args):
            batch_idx, batch = args
            rules_summary = []
            for rule in batch:
                rules_summary.append({
                    'rule_id': rule.get('rule_id'),
                    'rule_type': rule.get('rule_type'),
                    'title': rule.get('title'),
                    'description': rule.get('description', '')[:self.config.get_optimizer_description_truncation_length()],
                    'conditions': rule.get('conditions', []),
                    'consequences': rule.get('consequences', []),
                    'related_entities': rule.get('related_entities', [])
                })
            rules_json = json.dumps(rules_summary, indent=2)
            prompt = self.prompt_manager.format_prompt(
                "dependency_analysis",
                rules_json=rules_json,
                total_rules=len(batch)
            )
            print(f"\n   Batch {batch_idx}/{num_batches}: {len(batch)} rules → Using {self.model}...", flush=True)
            try:
                response = self.client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.get_optimizer_batched_temperature(),
                    max_tokens=self.config.get_optimizer_batched_max_tokens(),
                    reasoning_effort=self.reasoning_effort
                )
                if response and response.choices and response.choices[0].message.content:
                    dep_result = self._parse_json_response(response.choices[0].message.content)
                    batch_deps = dep_result.get("dependencies", [])
                    print(f"   ✓ Found {len(batch_deps)} dependencies in batch {batch_idx}", flush=True)
                    return batch_deps
                else:
                    print(f"   ⚠️ Empty response for batch {batch_idx}", flush=True)
                    return []
            except Exception as e:
                print(f"   ❌ Error analyzing batch {batch_idx}: {e}", flush=True)
                return []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for batch_deps in executor.map(_call_within_batch, enumerate(batches, 1)):
                all_dependencies.extend(batch_deps)
        
# Step 2: Analyze cross-batch dependencies (parallelised)
        cross_batch_sample_size = min(20, batch_size // 4)  # Sample ~25% of each batch
        pairs = [(i, j) for i in range(len(batches)) for j in range(i + 1, len(batches))]
        cross_workers = min(self.max_workers, len(pairs)) if pairs else 1
        print(f"\n📦 Step 2: Analyzing cross-batch dependencies ({len(pairs)} pairs, {cross_workers} workers)...", flush=True)
        print(f"   (Checking if rules in one batch depend on rules in another batch)", flush=True)

        def _call_cross_batch(args):
            i, j = args
            sample_i = batches[i][:cross_batch_sample_size]
            sample_j = batches[j][:cross_batch_sample_size]
            combined_sample = sample_i + sample_j
            print(f"   Cross-batch {i+1}↔{j+1}: {len(combined_sample)} sampled rules", flush=True)
            rules_summary = []
            for rule in combined_sample:
                rules_summary.append({
                    'rule_id': rule.get('rule_id'),
                    'rule_type': rule.get('rule_type'),
                    'title': rule.get('title'),
                    'description': rule.get('description', '')[:self.config.get_optimizer_description_truncation_length()],
                    'conditions': rule.get('conditions', []),
                    'consequences': rule.get('consequences', []),
                    'related_entities': rule.get('related_entities', [])
                })
            rules_json = json.dumps(rules_summary, indent=2)
            prompt = self.prompt_manager.format_prompt(
                "dependency_analysis",
                rules_json=rules_json,
                total_rules=len(combined_sample)
            )
            try:
                response = self.client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.get_optimizer_cross_batch_temperature(),
                    max_tokens=self.config.get_optimizer_cross_batch_max_tokens(),
                    reasoning_effort=self.reasoning_effort
                )
                if response and response.choices and response.choices[0].message.content:
                    dep_result = self._parse_json_response(response.choices[0].message.content)
                    cross_deps = dep_result.get("dependencies", [])
                    batch_i_ids = {r.get('rule_id') for r in batches[i]}
                    batch_j_ids = {r.get('rule_id') for r in batches[j]}
                    true_cross_deps = [
                        d for d in cross_deps
                        if (d['source_rule_id'] in batch_i_ids and d['target_rule_id'] in batch_j_ids) or
                           (d['source_rule_id'] in batch_j_ids and d['target_rule_id'] in batch_i_ids)
                    ]
                    if true_cross_deps:
                        print(f"   ✓ Found {len(true_cross_deps)} cross-batch dependencies ({i+1}↔{j+1})", flush=True)
                    return true_cross_deps
                return []
            except Exception as e:
                print(f"   ⚠️ Error analyzing cross-batch {i+1}↔{j+1}: {e}", flush=True)
                return []

        if pairs:
            with ThreadPoolExecutor(max_workers=cross_workers) as executor:
                for cross_deps in executor.map(_call_cross_batch, pairs):
                    all_dependencies.extend(cross_deps)
        
        # Step 3: Merge results and apply to rules
        print(f"\n✓ Batched analysis complete:", flush=True)
        print(f"  • Total dependencies found: {len(all_dependencies)}", flush=True)
        
        # Create maps
        rule_dependencies_map = {}
        rule_dependents_map = {}
        
        for dep in all_dependencies:
            source_id = dep["source_rule_id"]
            target_id = dep["target_rule_id"]
            
            # Calculate confidence if breakdown provided
            if 'confidence' in dep and isinstance(dep['confidence'], dict):
                dep['confidence'] = self._calculate_dependency_confidence(dep['confidence'])
            elif 'confidence' not in dep:
                # Default confidence based on strength
                strength = dep.get('strength', 3)
                dep['confidence'] = {
                    5: 95, 4: 85, 3: 75, 2: 65, 1: 55
                }.get(strength, 70)
            
            # Track what this rule depends on
            if target_id not in rule_dependencies_map:
                rule_dependencies_map[target_id] = []
            rule_dependencies_map[target_id].append({
                "depends_on_rule": source_id,
                "dependency_type": dep["dependency_type"],
                "rationale": dep["rationale"],
                "impact_if_fails": dep.get("impact", "Unknown"),
                "strength": dep.get("strength", "medium"),
                "confidence": dep.get("confidence", 70)
            })
            
            # Track what depends on this rule
            if source_id not in rule_dependents_map:
                rule_dependents_map[source_id] = []
            rule_dependents_map[source_id].append({
                "dependent_rule": target_id,
                "dependency_type": dep["dependency_type"]
            })
        
        # Apply to rules
        rules_with_deps = []
        for rule in rules:
            rule_id = rule.get("rule_id")
            
            if rule_id in rule_dependencies_map:
                rule["dependencies"] = rule_dependencies_map[rule_id]
            
            if rule_id in rule_dependents_map:
                rule["dependent_rules"] = rule_dependents_map[rule_id]
            
            rules_with_deps.append(rule)
        
        metadata = {
            "dependency_analysis": {
                "dependencies": all_dependencies,
                "batched_analysis": True,
                "num_batches": num_batches,
                "batch_size": batch_size
            },
            "total_dependencies": len(all_dependencies),
            "dependency_chains": [],
            "circular_dependencies": [],
            "conflicts": [],
            "rules_with_dependencies": len(rule_dependencies_map),
            "rules_with_dependents": len(rule_dependents_map)
        }
        
        print(f"  • Rules with dependencies: {len(rule_dependencies_map)}", flush=True)
        print(f"  • Rules with dependents: {len(rule_dependents_map)}", flush=True)
        
        return rules_with_deps, metadata
    
    def optimize_parallel(self, rules: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Run deduplication and dependency analysis in parallel (thread-safe).
        
        Returns:
            - Deduplicated rules with dependencies
            - Deduplication metadata
            - Dependency metadata
        """
        print(f"\n{'='*70}", flush=True)
        print(f"🚀 PARALLEL OPTIMIZATION: Deduplication + Dependency Analysis", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"Running both analyses in parallel (2 threads)...\n", flush=True)
        
        dedup_result = None
        dep_result = None
        dedup_error = None
        dep_error = None

        print("📄 Launching Task 1 (Deduplication) + Task 2 (Dependency Analysis) in parallel...", flush=True)
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_dedup = executor.submit(self.deduplicate_rules, rules)
            fut_dep = executor.submit(self.analyze_dependencies, rules)

            try:
                dedup_result = fut_dedup.result()
                print("✓ Task 1: Deduplication completed", flush=True)
            except Exception as e:
                dedup_error = str(e)
                print(f"✗ Task 1: Deduplication failed: {e}", flush=True)

            try:
                dep_result = fut_dep.result()
                print("✓ Task 2: Dependency analysis completed", flush=True)
            except Exception as e:
                dep_error = str(e)
                print(f"✗ Task 2: Dependency analysis failed: {e}", flush=True)
        
        # Handle results
        if dedup_error and dep_error:
            print(f"\n❌ Both optimization steps failed", flush=True)
            return rules, {"error": dedup_error}, {"error": dep_error}
        
        # Get deduplicated rules
        if dedup_result:
            deduplicated_rules, dedup_metadata = dedup_result
        else:
            deduplicated_rules, dedup_metadata = rules, {"error": dedup_error, "total_removed": 0}
        
        # Apply dependency analysis to deduplicated rules
        if dep_result:
            # Dependency analysis was run on original rules, need to map to deduplicated
            _, dep_metadata = dep_result
            
            # Re-apply dependencies to deduplicated rules
            deduplicated_rule_ids = {r.get('rule_id') for r in deduplicated_rules}
            
            # Filter dependencies to only include non-removed rules
            filtered_deps = []
            for dep in dep_metadata.get('dependency_analysis', {}).get('dependencies', []):
                if (dep['source_rule_id'] in deduplicated_rule_ids and 
                    dep['target_rule_id'] in deduplicated_rule_ids):
                    filtered_deps.append(dep)
            
            if dep_metadata.get('dependency_analysis'):
                dep_metadata['dependency_analysis']['dependencies'] = filtered_deps
                dep_metadata['total_dependencies'] = len(filtered_deps)
            
            # Add dependency info to deduplicated rules
            rule_dependencies_map = {}
            rule_dependents_map = {}
            
            for dep in filtered_deps:
                source_id = dep["source_rule_id"]
                target_id = dep["target_rule_id"]
                
                if target_id not in rule_dependencies_map:
                    rule_dependencies_map[target_id] = []
                rule_dependencies_map[target_id].append({
                    "depends_on_rule": source_id,
                    "dependency_type": dep["dependency_type"],
                    "rationale": dep["rationale"],
                    "impact_if_fails": dep.get("impact", "Unknown"),
                    "strength": dep.get("strength", "medium")
                })
                
                if source_id not in rule_dependents_map:
                    rule_dependents_map[source_id] = []
                rule_dependents_map[source_id].append({
                    "dependent_rule": target_id,
                    "dependency_type": dep["dependency_type"]
                })
            
            # Enhance deduplicated rules with dependencies
            for rule in deduplicated_rules:
                rule_id = rule.get("rule_id")
                if rule_id in rule_dependencies_map:
                    rule["dependencies"] = rule_dependencies_map[rule_id]
                if rule_id in rule_dependents_map:
                    rule["dependent_rules"] = rule_dependents_map[rule_id]
        else:
            dep_metadata = {"error": dep_error, "total_dependencies": 0}
        
        print(f"\n{'='*70}", flush=True)
        print(f"✅ PARALLEL OPTIMIZATION COMPLETE", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"Results:", flush=True)
        print(f"  • Original rules: {len(rules)}", flush=True)
        print(f"  • Rules after deduplication: {len(deduplicated_rules)}", flush=True)
        print(f"  • Rules removed: {dedup_metadata.get('total_removed', 0)}", flush=True)
        print(f"  • Dependencies found: {dep_metadata.get('total_dependencies', 0)}", flush=True)
        print(f"  • Time saved: ~50% (parallel execution)", flush=True)
        
        return deduplicated_rules, dedup_metadata, dep_metadata
    
    def save_optimized_results(self,
                               optimized_rules: List[Dict[str, Any]],
                               dedup_metadata: Dict[str, Any],
                               dep_metadata: Dict[str, Any],
                               original_data: Dict[str, Any],
                               output_dir: Path):
        """Save optimized results with all metadata and rationale."""
        print(f"\n{'='*70}", flush=True)
        print(f"STEP 3: Saving Optimized Results", flush=True)
        print(f"{'='*70}", flush=True)
        
        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Create comprehensive optimized output
        optimized_output = {
            "metadata": {
                "optimizer_version": "1.0",
                "timestamp": timestamp,
                "model_used": self.model,
                "reasoning_effort": self.reasoning_effort,
                "original_rule_count": len(original_data.get("business_rules", [])),
                "optimized_rule_count": len(optimized_rules),
                "rules_removed_count": dedup_metadata.get("total_removed", 0),
                "dependencies_added_count": dep_metadata.get("total_dependencies", 0)
            },
            "optimization_summary": {
                "deduplication": {
                    "strategy": "Conservative - only remove rationally identical rules",
                    "duplicate_groups": len(dedup_metadata.get("deduplication_analysis", {}).get("duplicate_groups", [])),
                    "rules_removed": dedup_metadata.get("total_removed", 0),
                    "rationale": "Analyzed all rules for rational duplicates. Removed only those expressing identical business logic while preserving rules with meaningful differences in thresholds, contexts, or conditions.",
                    "analysis_notes": dedup_metadata.get("deduplication_analysis", {}).get("analysis_notes", "")
                },
                "dependency_analysis": {
                    "strategy": "Comprehensive relationship mapping",
                    "dependencies_found": dep_metadata.get("total_dependencies", 0),
                    "dependency_chains": len(dep_metadata.get("dependency_chains", [])),
                    "conflicts_identified": len(dep_metadata.get("conflicts", [])),
                    "rules_with_dependencies": dep_metadata.get("rules_with_dependencies", 0),
                    "rationale": "Identified prerequisite, sequential, conditional, complementary, contradictory, and override relationships between rules to enable proper execution ordering and conflict resolution.",
                    "analysis_notes": dep_metadata.get("dependency_analysis", {}).get("analysis_notes", "")
                }
            },
            "business_rules": optimized_rules,
            "deduplication_details": dedup_metadata.get("deduplication_analysis", {}),
            "dependency_details": {
                "dependencies": dep_metadata.get("dependency_analysis", {}).get("dependencies", []),
                "dependency_chains": dep_metadata.get("dependency_chains", []),
                "conflicts": dep_metadata.get("conflicts", [])
            },
            "entity_types": original_data.get("entity_types", {}),
            "relationships": original_data.get("relationships", [])
        }
        
        # Save optimized JSON
        json_file = output_dir / "optimized_compliance_knowledge_graph.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(optimized_output, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved: {json_file.name}", flush=True)
        
        print(f"\n✅ All optimized files saved to: {output_dir}", flush=True)
    
    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON from response, handling markdown code blocks."""
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Try to extract JSON from markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError as e2:
                print(f"⚠️  JSON parse error: {e}", flush=True)
                print(f"   First 500 chars of response: {text[:500]}", flush=True)
                print(f"⚠️  Failed to parse JSON even after extracting from code blocks: {e2}", flush=True)
                raise e2 from e
    
    def optimize(self, input_file: Path, output_dir: Path) -> Dict[str, Any]:
        """
        Main optimization workflow.
        
        Args:
            input_file: Path to compliance_knowledge_graph.json
            output_dir: Directory to save optimized outputs
            
        Returns:
            Summary statistics
        """
        print("\n" + "=" * 80, flush=True)
        print("🧠 AGENT 5: COMPLIANCE KNOWLEDGE GRAPH OPTIMIZER", flush=True)
        print("=" * 80, flush=True)
        print(f"\n📋 Purpose: Optimize the knowledge graph for quality and usability", flush=True)
        print(f"\n   This agent performs two key optimizations:", flush=True)
        print(f"   ┌─────────────────────────────────────────────────────────────┐", flush=True)
        print(f"   │ Step 1: DEDUPLICATION                                       │", flush=True)
        print(f"   │   • Identify rationally identical rules                     │", flush=True)
        print(f"   │   • Merge duplicates while preserving unique information    │", flush=True)
        print(f"   │   • Conservative approach - only remove true duplicates     │", flush=True)
        print(f"   ├─────────────────────────────────────────────────────────────┤", flush=True)
        print(f"   │ Step 2: DEPENDENCY ANALYSIS                                 │", flush=True)
        print(f"   │   • Map prerequisite relationships between rules            │", flush=True)
        print(f"   │   • Identify sequential, conditional dependencies           │", flush=True)
        print(f"   │   • Detect potential conflicts and circular references      │", flush=True)
        print(f"   ├─────────────────────────────────────────────────────────────┤", flush=True)
        print(f"   │ Step 3: SAVE OPTIMIZED OUTPUTS                              │", flush=True)
        print(f"   │   • Optimized knowledge graph JSON                          │", flush=True)
        print(f"   └─────────────────────────────────────────────────────────────┘", flush=True)
        print(flush=True)
        
        # Load original data
        original_data = self.load_business_rules(input_file)
        
        # Extract all business rules - try top-level first, then entity_types structure
        rules = original_data.get("business_rules", [])
        
        # If no top-level rules, try extracting from entity_types structure
        if not rules and 'entity_types' in original_data:
            for entity_name, entity_data in original_data['entity_types'].items():
                entity_rules = entity_data.get('business_rules', [])
                # Add entity context to each rule
                for rule in entity_rules:
                    rule['entity_type'] = entity_name
                    rules.append(rule)
        
        if not rules:
            print("\n❌ No business rules found to optimize", flush=True)
            return {
                "original_count": 0,
                "optimized_count": 0,
                "removed_count": 0,
                "dependencies_count": 0
            }
        
        # Run both deduplication and dependency analysis in PARALLEL
        # This reduces optimization time by ~50% (from ~4 min to ~2 min)
        optimized_rules, dedup_metadata, dep_metadata = self.optimize_parallel(rules)

        # Deterministic uniqueness enforcement after LLM deduplication
        optimized_rules, fixes = enforce_rule_uniqueness(optimized_rules)
        if fixes['id_fixes'] or fixes['name_fixes']:
            print(f"   ⚠️  Uniqueness enforcement: fixed {fixes['id_fixes']} duplicate rule_id(s), "
                  f"{fixes['name_fixes']} duplicate rule_name(s)", flush=True)
        else:
            print(f"   ✓ All rule_id and rule_name values are unique after optimization", flush=True)

        # Step 3: Save Results
        self.save_optimized_results(
            optimized_rules,
            dedup_metadata,
            dep_metadata,
            original_data,
            output_dir
        )
        
        return {
            "original_count": len(rules),
            "optimized_count": len(optimized_rules),
            "removed_count": dedup_metadata.get("total_removed", 0),
            "dependencies_count": dep_metadata.get("total_dependencies", 0)
        }


def main():
    """Main entry point for the optimizer agent."""
    # Load configuration
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils.config import get_config
    
    config = get_config()
    
    # Configuration
    API_KEY = config.get_openai_api_key()
    MODEL = config.get_optimizer_model_name()  # From config.json optimizer.model
    REASONING_EFFORT = config.get_reasoning_effort()
    OUTPUT_DIR = config.get_optimized_dir()
    
    # Input file from Agent 4 output
    input_file = config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
    
    if not input_file.exists():
        print(f"❌ Error: Input file not found: {input_file}", flush=True)
        print(f"   Please run the pipeline up to step 4 (consolidation) first.", flush=True)
        sys.exit(1)
    
    # Initialize optimizer
    optimizer = KnowledgeGraphOptimizer(
        api_key=API_KEY,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT
    )
    
    # Run optimization
    try:
        result = optimizer.optimize(input_file, OUTPUT_DIR)
        
        print("\n" + "=" * 80, flush=True)
        print("✅ OPTIMIZATION COMPLETE", flush=True)
        print("=" * 80, flush=True)
        print(f"Results:", flush=True)
        print(f"  • Original rules:        {result['original_count']}", flush=True)
        print(f"  • Duplicates removed:    {result['removed_count']}", flush=True)
        print(f"  • Optimized rules:       {result['optimized_count']}", flush=True)
        print(f"  • Dependencies added:    {result['dependencies_count']}", flush=True)
        print(f"\nOptimized files (with 'optimized-' prefix):", flush=True)
        print(f"  • optimized_compliance_knowledge_graph.json", flush=True)
        print(f"\nLocation: {OUTPUT_DIR}", flush=True)
        
    except Exception as e:
        print(f"\n❌ Error during optimization: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
