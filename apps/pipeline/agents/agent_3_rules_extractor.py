"""
Enhanced Business Rules Extractor using Entity-Relationship Definitions.
Uses entity definitions from meta-agent and GPT-5 reasoning for detailed rule extraction.
Supports parallel batch processing for improved speed.

Author: Reza Rahimi
Date: December 20, 2025
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import time
import threading
from dataclasses import dataclass, asdict
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


@dataclass
class RulesExtractionConfig:
    """Configuration for business rules extraction."""
    target_rules_count: int = 100
    batch_size: int = 8
    max_content_length: int = 8000
    reasoning_model: Optional[str] = None
    optimization_model: Optional[str] = None
    

class BusinessRulesExtractor:
    """Extract detailed business rules using entity-relationship definitions and GPT-5 reasoning."""
    
    def __init__(
        self, 
        api_key: str, 
        entity_relationship_file: str,
        target_rules_count: int = 100,
        reasoning_effort: str = "medium",
        config: Optional[RulesExtractionConfig] = None
    ):
        self.config = config or RulesExtractionConfig(target_rules_count=target_rules_count)
        self.global_config = get_config()
        if not self.config.reasoning_model:
            self.config.reasoning_model = self.global_config.get_reasoning_model()
        if not self.config.optimization_model:
            self.config.optimization_model = self.global_config.get_optimizer_model()
        self.client = create_llm_client(
            api_key=api_key,
            model=self.config.reasoning_model,
            timeout=self.global_config.get_timeout(),
            max_retries=self.global_config.get_max_retries()
        )
        self.reasoning_effort = reasoning_effort or self.global_config.get_reasoning_effort()
        self.entity_relationship_file = entity_relationship_file
        self.entity_definitions = {}
        self.relationship_definitions = {}
        self.all_entity_types = {}
        self.all_relationships = {}
        self.prompt_manager = get_prompt_manager()
        self._merge_lock = threading.Lock()  # Thread-safe merging
        
        # Load existing entity-relationship definitions
        self._load_entity_definitions()
    
    def _load_entity_definitions(self):
        """Load entity and relationship definitions from the meta-agent output."""
        try:
            with open(self.entity_relationship_file, 'r', encoding='utf-8') as f:
                definitions = json.load(f)
                self.entity_definitions = definitions.get('entity_types', {})
                self.relationship_definitions = definitions.get('relationships', {})
                
            print(f"✓ Loaded {len(self.entity_definitions)} entity definitions", flush=True)
            print(f"✓ Loaded {len(self.relationship_definitions)} relationship definitions", flush=True)
            
            # Display entity and relationship names
            if self.entity_definitions:
                if isinstance(self.entity_definitions, dict):
                    print(f"  Entities: {', '.join(self.entity_definitions.keys())}", flush=True)
                elif isinstance(self.entity_definitions, list):
                    print(f"  Entities: {len(self.entity_definitions)} entities loaded", flush=True)
            if self.relationship_definitions:
                if isinstance(self.relationship_definitions, dict):
                    print(f"  Relationships: {', '.join(self.relationship_definitions.keys())}", flush=True)
                elif isinstance(self.relationship_definitions, list):
                    rel_types = [r.get('relationship_type', 'UNKNOWN') for r in self.relationship_definitions[:5]]
                    print(f"  Relationships: {', '.join(rel_types)}{'...' if len(self.relationship_definitions) > 5 else ''}", flush=True)
                
        except FileNotFoundError:
            print(f"⚠ Warning: Entity-relationship file not found: {self.entity_relationship_file}", flush=True)
            print(f"  Will extract entities and rules from scratch.", flush=True)
        except Exception as e:
            print(f"⚠ Error loading entity definitions: {e}", flush=True)
    
    def read_text_files_batch(self, directory: str, batch_size: Optional[int] = None) -> List[List[Dict[str, str]]]:
        """Read text files and organize into word-balanced batches.
        
        Instead of grouping a fixed number of files per batch, this method
        balances batches by total word count so each batch has roughly equal
        content for the LLM to process. This prevents one oversized chunk
        from dominating a batch while small chunks get crowded out.
        """
        if batch_size is None:
            batch_size = self.config.batch_size
            
        all_files = []
        directory_path = Path(directory)
        
        for txt_file in directory_path.rglob("*.txt"):
            try:
                # Skip metadata files
                if txt_file.name.startswith('_'):
                    continue
                    
                with open(txt_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        relative_path = txt_file.relative_to(directory_path)
                        truncated = content[:self.config.max_content_length]
                        all_files.append({
                            'path': str(relative_path),
                            'content': truncated,
                            'word_count': len(truncated.split())
                        })
            except Exception as e:
                print(f"Error reading {txt_file}: {e}", flush=True)
        
        # Sort by word count (largest first) for better bin-packing
        all_files.sort(key=lambda f: f['word_count'], reverse=True)
        
        # Build word-balanced batches
        # Target ~batch_size files per batch, but also cap total words per batch
        # to keep LLM context usage consistent
        target_words_per_batch = self.global_config.get_rules_target_words_per_batch()
        batches = []
        current_batch = []
        current_words = 0
        
        for file_info in all_files:
            wc = file_info['word_count']
            
            # If this single file exceeds target, it gets its own batch
            if wc >= target_words_per_batch:
                if current_batch:
                    batches.append(current_batch)
                batches.append([file_info])
                current_batch = []
                current_words = 0
            elif current_words + wc > target_words_per_batch or len(current_batch) >= batch_size:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [file_info]
                current_words = wc
            else:
                current_batch.append(file_info)
                current_words += wc
        
        if current_batch:
            batches.append(current_batch)
        
        # Calculate how many batches needed based on target rules
        # Get rules_per_batch from config (4 for smaller models, 10 for OpenAI by default)
        rules_per_batch = self.global_config.get_rules_per_batch()
        needed_batches = min(len(batches), (self.config.target_rules_count // rules_per_batch) + 10)  # +10 for safety/failures
        batches_to_process = needed_batches
        
        # Log batch statistics
        batch_word_counts = [sum(f['word_count'] for f in b) for b in batches[:batches_to_process]]
        avg_words = sum(batch_word_counts) / len(batch_word_counts) if batch_word_counts else 0
        print(f"✓ Loaded {len(all_files)} files organized into {len(batches)} word-balanced batches", flush=True)
        print(f"  Processing {batches_to_process} batches to reach ~{self.config.target_rules_count} rules", flush=True)
        print(f"  Batch word counts: avg={int(avg_words)}, min={min(batch_word_counts) if batch_word_counts else 0}, max={max(batch_word_counts) if batch_word_counts else 0}", flush=True)
        
        return batches[:batches_to_process]
    
    def create_entity_context(self) -> str:
        """Create context from existing entity and relationship definitions."""
        if not self.entity_definitions and not self.relationship_definitions:
            return ""
        
        context = "\n\nEXISTING ENTITY AND RELATIONSHIP DEFINITIONS TO USE:\n\n"
        
        if self.entity_definitions:
            context += "ENTITIES:\n"
            for entity_name, entity_info in self.entity_definitions.items():
                context += f"\n{entity_name}:\n"
                context += f"  Definition: {entity_info.get('definition', 'N/A')}\n"
                context += f"  Attributes: {', '.join(entity_info.get('attributes', []))}\n"
        
        if self.relationship_definitions:
            context += "\n\nRELATIONSHIPS:\n"
            # Handle both dict and list formats
            if isinstance(self.relationship_definitions, dict):
                for rel_name, rel_info in self.relationship_definitions.items():
                    context += f"\n{rel_name}:\n"
                    context += f"  From: {rel_info.get('source_entity', 'N/A')} → To: {rel_info.get('target_entity', 'N/A')}\n"
                    context += f"  Definition: {rel_info.get('definition', 'N/A')}\n"
            elif isinstance(self.relationship_definitions, list):
                for rel_info in self.relationship_definitions:
                    rel_type = rel_info.get('relationship_type', 'UNKNOWN')
                    context += f"\n{rel_type}:\n"
                    context += f"  From: {rel_info.get('from', 'N/A')} → To: {rel_info.get('to', 'N/A')}\n"
                    context += f"  Definition: {rel_info.get('description', 'N/A')}\n"
        
        return context
    
    def create_batch_prompt(self, documents: List[Dict[str, str]], batch_num: int, total_batches: int) -> str:
        """Create reasoning-focused prompt for GPT-5 model."""
        sample_content = "\n\n---DOCUMENT---\n\n".join([
            f"FILE: {doc['path']}\n{doc['content']}"
            for doc in documents
        ])
        
        entity_context = self.create_entity_context()
        rules_per_batch = self.global_config.get_rules_per_batch()
        
        return self.prompt_manager.format_prompt(
            "business_rules_extraction",
            entity_context=entity_context,
            sample_content=sample_content,
            batch_num=batch_num,
            rules_per_batch=rules_per_batch
        )
    
    def extract_batch(self, prompt: str, batch_num: int) -> Dict[str, Any]:
        """Extract from a single batch using reasoning model."""
        import time as _time
        batch_start = _time.time()
        try:
            response = self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.global_config.get_rules_temperature(),
                max_tokens=self.global_config.get_rules_max_tokens(),
                reasoning_effort=self.reasoning_effort
            )
            
            content = response.choices[0].message.content
            if not content:
                return {"entity_types": {}, "relationships": {}, "batch_num": batch_num, "error": "Empty response"}
            
            # Try to parse JSON from response
            try:
                # Try direct JSON parse first
                result = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                if "```json" in content:
                    json_str = content.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in content:
                    json_str = content.split("```", 1)[1].split("```", 1)[0].strip()
                else:
                    # Try to find JSON object directly
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                    else:
                        print(f"  DEBUG Batch {batch_num}: No JSON found in response", flush=True)
                        print(f"  Response preview: {content[:500]}", flush=True)
                        return {"entity_types": {}, "relationships": {}, "batch_num": batch_num, "error": "No JSON in response"}
                
                result = json.loads(json_str)
            
            # Normalize flat 'rules' format (used by domain-specific prompts like AML)
            # into the nested entity_types/relationships format expected by the rest of the pipeline.
            if 'rules' in result and 'entity_types' not in result:
                flat_rules = result.get('rules', [])
                entity_types: Dict[str, Any] = {}
                relationships: Dict[str, Any] = {}
                for r in flat_rules:
                    rel_name = r.get('relationship') if r.get('relationship') not in (None, '', 'null', 'NULL', 'None') else None
                    ent_name = r.get('entity', 'UNKNOWN_ENTITY')
                    if rel_name:
                        if rel_name not in relationships:
                            relationships[rel_name] = {'business_rules': []}
                        relationships[rel_name]['business_rules'].append(r)
                    else:
                        if ent_name not in entity_types:
                            entity_types[ent_name] = {'business_rules': []}
                        entity_types[ent_name]['business_rules'].append(r)
                result['entity_types'] = entity_types
                result['relationships'] = relationships

            # Count rules extracted
            entity_rules = sum(len(e.get('business_rules', [])) for e in result.get('entity_types', {}).values())
            rels = result.get('relationships', {})
            rel_rules = sum(len(r.get('business_rules', [])) for r in (rels.values() if isinstance(rels, dict) else []))
            total_rules = entity_rules + rel_rules
            
            result['batch_num'] = batch_num
            result['total_rules'] = total_rules
            result['entity_rules'] = entity_rules
            result['rel_rules'] = rel_rules
            result['extraction_time'] = _time.time() - batch_start
            
            # Debug: check if we have rules
            if total_rules == 0:
                print(f"  DEBUG Batch {batch_num}: Parsed JSON but 0 rules found", flush=True)
                print(f"  Entity types: {list(result.get('entity_types', {}).keys())}", flush=True)
                print(f"  Relationships: {list(result.get('relationships', {}).keys())}", flush=True)
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"  DEBUG Batch {batch_num}: JSON parse error: {e}", flush=True)
            if content:
                print(f"  Response preview: {content[:500]}", flush=True)
            return {"entity_types": {}, "relationships": {}, "batch_num": batch_num, "error": f"JSON parsing error: {e}"}
        except Exception as e:
            print(f"  DEBUG Batch {batch_num}: Exception: {e}", flush=True)
            return {"entity_types": {}, "relationships": {}, "batch_num": batch_num, "error": str(e)}
    
    def merge_results(self, batch_result: Dict[str, Any]):
        """Merge batch results into accumulated results (thread-safe)."""
        with self._merge_lock:
            # Merge entity types
            for entity_name, entity_info in batch_result.get('entity_types', {}).items():
                if entity_name in self.all_entity_types:
                    existing_rules = self.all_entity_types[entity_name].get('business_rules', [])
                    new_rules = entity_info.get('business_rules', [])
                    existing_ids = {r.get('rule_id') for r in existing_rules}
                    existing_names = {r.get('rule_name', '').lower() for r in existing_rules}
                    for rule in new_rules:
                        if rule.get('rule_id') not in existing_ids and rule.get('rule_name', '').lower() not in existing_names:
                            existing_rules.append(rule)
                    self.all_entity_types[entity_name]['business_rules'] = existing_rules
                else:
                    self.all_entity_types[entity_name] = entity_info

            # Merge relationships
            for rel_name, rel_info in batch_result.get('relationships', {}).items():
                if rel_name in self.all_relationships:
                    existing_rules = self.all_relationships[rel_name].get('business_rules', [])
                    new_rules = rel_info.get('business_rules', [])
                    existing_ids = {r.get('rule_id') for r in existing_rules}
                    existing_names = {r.get('rule_name', '').lower() for r in existing_rules}
                    for rule in new_rules:
                        if rule.get('rule_id') not in existing_ids and rule.get('rule_name', '').lower() not in existing_names:
                            existing_rules.append(rule)
                    self.all_relationships[rel_name]['business_rules'] = existing_rules
                else:
                    self.all_relationships[rel_name] = rel_info
    
    def _calculate_confidence_score(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate overall confidence score from breakdown if present."""
        if 'confidence_breakdown' in rule:
            breakdown = rule['confidence_breakdown']
            weights = self.global_config.get_rules_confidence_weights()
            
            score = sum(
                breakdown.get(key, 0) * weight
                for key, weight in weights.items()
            )
            
            rule['confidence_score'] = round(score, 2)
            
            # Flag low confidence rules
            if score < self.global_config.get_rules_low_confidence_threshold():
                rule['requires_review'] = True
                rule['review_reason'] = 'Low confidence score'
        elif 'confidence_score' not in rule:
            # Set default if missing
            rule['confidence_score'] = self.global_config.get_rules_default_confidence_score()
        
        return rule
    
    def extract_rules_parallel(self, batches: List[List[Dict[str, str]]], max_workers: int = None) -> None:
        """Extract rules from batches in parallel."""
        max_workers = max_workers or self.global_config.get_max_workers()
        print(f"\n{'='*70}", flush=True)
        print(f"🚀 AGENT 3: PARALLEL BUSINESS RULES EXTRACTION", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"\n📋 Configuration:", flush=True)
        print(f"   • Workers: {max_workers}", flush=True)
        print(f"   • Total batches: {len(batches)}", flush=True)
        print(f"   • Target rules: {self.config.target_rules_count}", flush=True)
        print(f"   • Model: {self.config.reasoning_model}", flush=True)
        print(f"   • Rules per batch: {self.global_config.get_rules_per_batch()}", flush=True)
        print(f"\n⏳ Preparing prompts for {len(batches)} batches...", flush=True)
        
        # Create prompts for all batches
        batch_prompts = [
            (self.create_batch_prompt(batch, i+1, len(batches)), i+1)
            for i, batch in enumerate(batches)
        ]
        print(f"   ✓ Prompts prepared\n", flush=True)
        
        results = []
        completed = 0
        start_time = time.time()
        
        print(f"📡 Starting extraction (this may take several minutes)...", flush=True)
        print(f"   Progress will be shown as batches complete.\n", flush=True)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all batch extraction tasks
            future_to_batch = {
                executor.submit(self.extract_batch, prompt, batch_num): batch_num
                for prompt, batch_num in batch_prompts
            }
            print(f"   ✓ {len(future_to_batch)} tasks submitted to executor\n", flush=True)
            
            # Process results as they complete
            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future]
                try:
                    result = future.result()
                    completed += 1
                    
                    # Display progress
                    error = result.get('error')
                    extraction_time = result.get('extraction_time', 0)
                    if error:
                        print(f"  [{completed}/{len(batches)}] Batch {batch_num}: ✗ {error}", flush=True)
                    else:
                        total_rules = result.get('total_rules', 0)
                        entity_rules = result.get('entity_rules', 0)
                        rel_rules = result.get('rel_rules', 0)
                        print(f"  [{completed}/{len(batches)}] Batch {batch_num}: ✓ {total_rules} rules ({entity_rules} entity + {rel_rules} relationship) [{extraction_time:.1f}s]", flush=True)
                    
                    results.append((batch_num, result))
                    
                except Exception as e:
                    completed += 1
                    print(f"  [{completed}/{len(batches)}] Batch {batch_num}: ✗ Exception: {e}", flush=True)
        
        # Sort results by batch number and merge
        results.sort(key=lambda x: x[0])
        elapsed_time = time.time() - start_time
        
        print(f"\n{'='*70}", flush=True)
        print(f"📊 MERGING RESULTS", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"   • Successful batches: {len([r for r in results if 'error' not in r[1]])}", flush=True)
        print(f"   • Failed batches: {len([r for r in results if 'error' in r[1]])}", flush=True)
        print(f"   • Elapsed time: {elapsed_time:.1f} seconds", flush=True)
        print(f"\n   Merging {len(results)} batch results...", flush=True)
        
        merged_count = 0
        for batch_num, result in results:
            if 'error' not in result or result.get('entity_types') or result.get('relationships'):
                self.merge_results(result)
                merged_count += 1

        print(f"   ✓ Merged {merged_count} batches successfully", flush=True)

        # Enforce global uniqueness across all batches — the LLM may produce
        # duplicate rule_id or rule_name values under parallel execution or
        # token pressure even when explicitly told not to.
        print(f"\n   Enforcing global rule_id / rule_name uniqueness...", flush=True)
        all_rules = []
        for entity_info in self.all_entity_types.values():
            all_rules.extend(entity_info.get('business_rules', []))
        for rel_info in self.all_relationships.values():
            all_rules.extend(rel_info.get('business_rules', []))
        _, fixes = enforce_rule_uniqueness(all_rules)
        if fixes['id_fixes'] or fixes['name_fixes']:
            print(f"   ⚠️  Fixed {fixes['id_fixes']} duplicate rule_id(s), "
                  f"{fixes['name_fixes']} duplicate rule_name(s)", flush=True)
        else:
            print(f"   ✓ All rule_id and rule_name values are globally unique", flush=True)

        print(f"\n{'='*70}", flush=True)
        print(f"✅ EXTRACTION COMPLETE", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"   • Total rules extracted: {self.count_rules()}", flush=True)
        print(f"   • Total time: {elapsed_time:.1f} seconds", flush=True)
        print(f"   • Avg time per batch: {elapsed_time/len(batches):.1f} seconds", flush=True)
        print(f"{'='*70}\n", flush=True)
    
    def count_rules(self) -> int:
        """Count total business rules."""
        total = 0
        for entity in self.all_entity_types.values():
            total += len(entity.get('business_rules', []))
        for rel in self.all_relationships.values():
            total += len(rel.get('business_rules', []))
        return total

    # ── Entity-coverage validation with bounded retries ──────────────
    def validate_entity_coverage(self, max_retries: int = 3) -> Dict[str, int]:
        """Re-classify rules whose bucket key is not in Agent 2's catalog.

        After parallel extraction completes, every rule lives under either
        ``self.all_entity_types[<entity_name>]`` or
        ``self.all_relationships[<rel_name>]``. If that bucket key does not
        match any canonical name from Agent 2 (case/punctuation insensitive),
        the rule is an *orphan* and will not get a ``belongs_to_category``
        edge in the published graph.

        This method calls the LLM up to ``max_retries`` times with **only the
        orphan rules** (not the source chunks) and asks it to remap each one
        to a canonical entity/relationship name or mark it ``DROP``. Optimal:
        rules already in valid buckets are never re-processed.

        Returns a stats dict: ``{"orphans_initial", "remapped", "dropped",
        "remaining"}``.
        """
        import re as _re

        def _norm(s: str) -> str:
            return _re.sub(r"[\s\-]+", "_", str(s).strip().upper())

        canonical_entities = {_norm(k): k for k in (self.entity_definitions or {})}
        canonical_rels: Dict[str, str] = {}
        if isinstance(self.relationship_definitions, dict):
            canonical_rels = {_norm(k): k for k in self.relationship_definitions}
        elif isinstance(self.relationship_definitions, list):
            for r in self.relationship_definitions:
                if isinstance(r, dict):
                    name = r.get("relationship_type") or r.get("name")
                    if name:
                        canonical_rels[_norm(name)] = name
        canonical_all = {**canonical_entities, **canonical_rels}

        if not canonical_all:
            print("   ⚠️  No canonical entity/relationship catalog loaded — skipping entity-coverage validation", flush=True)
            return {"orphans_initial": 0, "remapped": 0, "dropped": 0, "remaining": 0}

        def _collect_orphans():
            """Return list of (bucket_kind, bucket_key, rule_index, rule)."""
            orphans = []
            for ent_name, ent_info in self.all_entity_types.items():
                if _norm(ent_name) in canonical_all:
                    continue
                for idx, rule in enumerate(ent_info.get("business_rules", [])):
                    orphans.append(("entity_types", ent_name, idx, rule))
            for rel_name, rel_info in self.all_relationships.items():
                if _norm(rel_name) in canonical_all:
                    continue
                for idx, rule in enumerate(rel_info.get("business_rules", [])):
                    orphans.append(("relationships", rel_name, idx, rule))
            return orphans

        initial_orphans = _collect_orphans()
        if not initial_orphans:
            print("   ✓ All rules are connected to a canonical entity/relationship — no validation retries needed", flush=True)
            return {"orphans_initial": 0, "remapped": 0, "dropped": 0, "remaining": 0}

        print(f"\n{'='*70}", flush=True)
        print(f"🔁 ENTITY-COVERAGE VALIDATION", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"   • Orphan rules detected: {len(initial_orphans)} / {self.count_rules()}", flush=True)
        print(f"   • Allowed entities: {len(canonical_entities)}", flush=True)
        print(f"   • Allowed relationships: {len(canonical_rels)}", flush=True)
        print(f"   • Max retries: {max_retries}", flush=True)

        remapped_total = 0
        dropped_total = 0

        allowed_entity_list = sorted(canonical_entities.values())
        allowed_rel_list = sorted(canonical_rels.values())

        for attempt in range(1, max_retries + 1):
            orphans = _collect_orphans()
            if not orphans:
                print(f"   ✓ Attempt {attempt}: no orphans remain — exiting early", flush=True)
                break

            print(f"\n   ⏳ Attempt {attempt}/{max_retries}: re-classifying {len(orphans)} orphan rule(s)...", flush=True)

            # Build a compact prompt: only orphan rule metadata, plus the
            # allowed canonical lists. We do NOT re-send chunk content —
            # the rule's name/description/conditions/consequences carry
            # enough signal for re-classification, and this keeps the call
            # cheap regardless of orphan count.
            orphan_payload = []
            for kind, bucket, _idx, rule in orphans:
                orphan_payload.append({
                    "rule_id": rule.get("rule_id", ""),
                    "rule_name": rule.get("rule_name", ""),
                    "current_bucket": bucket,
                    "current_kind": kind,
                    "description": (rule.get("description") or "")[:400],
                    "conditions": (rule.get("conditions") or "")[:200],
                    "entity_or_relationship_hint": rule.get("entity_or_relationship", ""),
                })

            prompt = (
                "You are validating business rules extracted from compliance documents. "
                "Each rule below was bucketed under a name that is NOT in the canonical "
                "entity/relationship catalog. Re-classify each rule to ONE canonical name "
                "from the allowed lists, or mark it DROP if no plausible mapping exists.\n\n"
                "Allowed entity names (use exact spelling):\n"
                f"{json.dumps(allowed_entity_list, indent=2)}\n\n"
                "Allowed relationship names (use exact spelling):\n"
                f"{json.dumps(allowed_rel_list, indent=2)}\n\n"
                "Orphan rules to re-classify:\n"
                f"{json.dumps(orphan_payload, indent=2)}\n\n"
                "Respond with ONLY a JSON object of the form:\n"
                '{"mappings": [{"rule_id": "...", "kind": "entity"|"relationship"|"DROP", "name": "<canonical>"}]}\n'
                "Use kind=\"DROP\" with name=\"\" to drop a rule that cannot be mapped."
            )

            try:
                response = self.client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.global_config.get_rules_temperature(),
                    max_tokens=self.global_config.get_rules_max_tokens(),
                    reasoning_effort=self.reasoning_effort,
                )
                content = response.choices[0].message.content or ""
            except Exception as exc:
                print(f"   ❌ Attempt {attempt}: LLM call failed: {exc}", flush=True)
                continue

            # Parse JSON (with code-block fallback)
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                if "```json" in content:
                    js = content.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in content:
                    js = content.split("```", 1)[1].split("```", 1)[0].strip()
                else:
                    s, e = content.find("{"), content.rfind("}") + 1
                    js = content[s:e] if 0 <= s < e else "{}"
                try:
                    payload = json.loads(js)
                except Exception as exc:
                    print(f"   ❌ Attempt {attempt}: could not parse LLM response: {exc}", flush=True)
                    continue

            mappings = {m.get("rule_id"): m for m in payload.get("mappings", []) if isinstance(m, dict) and m.get("rule_id")}
            if not mappings:
                print(f"   ⚠️  Attempt {attempt}: LLM returned no mappings — moving on", flush=True)
                continue

            # Apply mappings: pop each orphan rule from its current bucket
            # and re-insert under the canonical bucket (creating it if
            # missing). DROP just removes the rule.
            attempt_remapped = 0
            attempt_dropped = 0
            for kind, bucket, _idx, rule in orphans:
                rid = rule.get("rule_id")
                mapping = mappings.get(rid)
                if not mapping:
                    continue
                target_kind = (mapping.get("kind") or "").strip().lower()
                target_name = (mapping.get("name") or "").strip()

                # Locate and remove the rule from its current bucket
                container = self.all_entity_types if kind == "entity_types" else self.all_relationships
                bucket_info = container.get(bucket) or {}
                bucket_rules = bucket_info.get("business_rules", [])
                try:
                    bucket_rules.remove(rule)
                except ValueError:
                    continue

                if target_kind == "drop" or not target_name:
                    attempt_dropped += 1
                    continue

                # Resolve target name to canonical via _norm lookup
                if target_kind == "entity":
                    canonical = canonical_entities.get(_norm(target_name))
                    target_container = self.all_entity_types
                    rule["entity_type"] = "entity"
                elif target_kind == "relationship":
                    canonical = canonical_rels.get(_norm(target_name))
                    target_container = self.all_relationships
                    rule["entity_type"] = "relationship"
                else:
                    # Unknown kind — try entity then relationship
                    canonical = canonical_entities.get(_norm(target_name)) or canonical_rels.get(_norm(target_name))
                    target_container = self.all_entity_types if canonical in canonical_entities.values() else self.all_relationships
                    rule["entity_type"] = "entity" if target_container is self.all_entity_types else "relationship"

                if not canonical:
                    # LLM proposed a name not in catalog — put rule back where it was
                    bucket_rules.append(rule)
                    continue

                rule["entity_or_relationship"] = canonical
                target_container.setdefault(canonical, {"business_rules": []}).setdefault("business_rules", []).append(rule)
                attempt_remapped += 1

            remapped_total += attempt_remapped
            dropped_total += attempt_dropped
            print(
                f"   • Attempt {attempt}: remapped {attempt_remapped}, dropped {attempt_dropped}, "
                f"orphans now {len(_collect_orphans())}",
                flush=True,
            )

        remaining = len(_collect_orphans())
        print(f"\n   ✅ Validation complete:", flush=True)
        print(f"      • Initial orphans: {len(initial_orphans)}", flush=True)
        print(f"      • Remapped:        {remapped_total}", flush=True)
        print(f"      • Dropped:         {dropped_total}", flush=True)
        print(f"      • Remaining:       {remaining} (will fall through to data_loader fallback)", flush=True)
        print(f"{'='*70}\n", flush=True)

        return {
            "orphans_initial": len(initial_orphans),
            "remapped": remapped_total,
            "dropped": dropped_total,
            "remaining": remaining,
        }

    def _verify_source_references(self, source_directory: str):
        """Verify and stamp all source_reference objects against actual chunk content.

        When the LLM-provided word positions produce a text mismatch, this method
        attempts to *recover* by searching for the source_text anywhere in the
        chunk content and auto-correcting the positions.  This dramatically
        improves verification rates (from ~15-30% up to 70-90%) because the LLM
        usually quotes verbatim text but gets word offsets wrong.
        """
        from pathlib import Path
        from difflib import SequenceMatcher

        # Build a lookup of chunk_path -> (content, words) from the source directory
        directory_path = Path(source_directory)
        chunk_contents: Dict[str, str] = {}
        chunk_words: Dict[str, list] = {}
        # Also build a mapping from filename-only to full relative paths for fuzzy path recovery
        filename_to_paths: Dict[str, list] = {}
        for txt_file in directory_path.rglob("*.txt"):
            if txt_file.name.startswith('_'):
                continue
            try:
                relative_path = str(txt_file.relative_to(directory_path))
                with open(txt_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                chunk_contents[relative_path] = content
                chunk_words[relative_path] = content.split()
                fname = txt_file.name.lower()
                filename_to_paths.setdefault(fname, []).append(relative_path)
            except Exception:
                pass

        verified = 0
        failed = 0
        coerced = 0
        recovered = 0
        total = 0

        def _find_text_in_words(words: list, needle: str, threshold: float = 0.6) -> Optional[tuple]:
            """Search for needle text in a word list using sliding-window fuzzy match.

            Returns (start_word, end_word, ratio) or None.
            Uses an optimized approach: first try exact substring match on the
            joined content (fast), then fall back to word-level sliding window.
            """
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
                # Convert char offset to word offset
                before = content_lower[:idx]
                start_w = len(before.split()) - (1 if before.endswith(' ') or idx == 0 else 0)
                if start_w < 0:
                    start_w = 0
                # Determine end by matching word count of the needle
                end_w = min(start_w + needle_len, len(words))
                # Verify this is actually a good match
                candidate = ' '.join(words[start_w:end_w]).lower()
                ratio = SequenceMatcher(None, needle_lower, candidate).ratio()
                if ratio >= threshold:
                    return (start_w, end_w, ratio)

            # Sliding window: try windows of size needle_len ± 20%
            best = None
            margin = max(3, needle_len // 5)
            for window_size in range(max(1, needle_len - margin), needle_len + margin + 1):
                # Sample at intervals to keep this fast for large documents
                step = max(1, (len(words) - window_size) // 200)
                for i in range(0, len(words) - window_size + 1, step):
                    candidate = ' '.join(words[i:i + window_size]).lower()
                    # Quick rejection: check if first/last words overlap
                    if needle_words[0] not in candidate.split()[:3]:
                        continue
                    ratio = SequenceMatcher(None, needle_lower, candidate).ratio()
                    if ratio >= threshold and (best is None or ratio > best[2]):
                        best = (i, i + window_size, ratio)
                        if ratio > 0.9:
                            return best
            return best

        def _fuzzy_find_chunk(chunk_path: str) -> Optional[str]:
            """Try to find the correct chunk path when the exact path doesn't match."""
            # Try matching by filename
            fname = chunk_path.split('/')[-1].lower() if '/' in chunk_path else chunk_path.lower()
            candidates = filename_to_paths.get(fname, [])
            if len(candidates) == 1:
                return candidates[0]
            # Try matching by path suffix (last 2-3 segments)
            segments = [s for s in chunk_path.replace('\\', '/').split('/') if s]
            if len(segments) >= 2:
                suffix = '/'.join(segments[-2:]).lower()
                for real_path in chunk_contents:
                    if real_path.lower().endswith(suffix):
                        return real_path
            return None

        def _verify_rule(rule):
            nonlocal verified, failed, coerced, recovered, total
            total += 1
            ref = rule.get('source_reference')

            # Backward compat: if it's a plain string (legacy format), coerce to structured
            if isinstance(ref, str):
                coerced += 1
                parts = ref.split('|', 1)
                chunk_path = parts[0].strip() if parts else ref.strip()
                section_id = parts[1].strip() if len(parts) > 1 else 'N/A'
                ref = {
                    "chunk_path": chunk_path,
                    "section_id": section_id,
                    "start_word_position": 0,
                    "end_word_position": 0,
                    "source_text": ""
                }
                rule['source_reference'] = ref
                rule['reference_verified'] = False
                rule['reference_verification_note'] = 'coerced_from_string'
                return

            if not isinstance(ref, dict):
                rule['reference_verified'] = False
                rule['reference_verification_note'] = 'missing_or_invalid_type'
                failed += 1
                return

            chunk_path = ref.get('chunk_path', '')
            start_pos = ref.get('start_word_position', -1)
            end_pos = ref.get('end_word_position', -1)
            source_text = ref.get('source_text', '')

            # 1. Resolve chunk_path — try exact, then fuzzy
            resolved_path = chunk_path
            if chunk_path not in chunk_contents:
                fuzzy_match = _fuzzy_find_chunk(chunk_path)
                if fuzzy_match:
                    resolved_path = fuzzy_match
                    ref['chunk_path'] = resolved_path
                else:
                    rule['reference_verified'] = False
                    rule['reference_verification_note'] = f'chunk_not_found:{chunk_path}'
                    failed += 1
                    return

            words = chunk_words[resolved_path]

            # 2. Validate word positions and check text match at stated positions
            positions_valid = (
                isinstance(start_pos, int) and start_pos >= 0
                and isinstance(end_pos, int) and end_pos > 0
                and start_pos < end_pos
                and start_pos < len(words)
            )

            # Clamp end position if slightly out of bounds
            if positions_valid and end_pos > len(words):
                ref['end_word_position'] = len(words)
                end_pos = len(words)

            matched_at_positions = False
            if positions_valid and source_text:
                actual_slice = ' '.join(words[start_pos:end_pos])
                ratio = SequenceMatcher(None, source_text.lower(), actual_slice.lower()).ratio()
                ref['text_match_score'] = round(ratio, 3)
                if ratio >= 0.3:
                    matched_at_positions = True

            if matched_at_positions:
                rule['reference_verified'] = True
                rule['reference_verification_note'] = 'ok'
                verified += 1
                return

            # 3. Recovery: search for source_text anywhere in the chunk
            if source_text:
                found = _find_text_in_words(words, source_text)
                if found:
                    new_start, new_end, ratio = found
                    ref['start_word_position'] = new_start
                    ref['end_word_position'] = new_end
                    ref['text_match_score'] = round(ratio, 3)
                    rule['reference_verified'] = True
                    rule['reference_verification_note'] = 'ok_recovered_position'
                    recovered += 1
                    verified += 1
                    return

            # 4. Last resort: try matching using the rule description as source_text
            description = rule.get('description', '')
            if description and len(description) > 30:
                found = _find_text_in_words(words, description[:300], threshold=0.4)
                if found:
                    new_start, new_end, ratio = found
                    ref['start_word_position'] = new_start
                    ref['end_word_position'] = new_end
                    ref['text_match_score'] = round(ratio, 3)
                    ref['source_text'] = ' '.join(words[new_start:new_end])
                    rule['reference_verified'] = True
                    rule['reference_verification_note'] = 'ok_recovered_from_description'
                    recovered += 1
                    verified += 1
                    return

            # All recovery attempts failed
            issues = []
            if not positions_valid:
                if not isinstance(start_pos, int) or start_pos < 0:
                    issues.append('invalid_start_position')
                elif start_pos >= len(words):
                    issues.append(f'start_position_out_of_bounds:{start_pos}>={len(words)}')
                if not isinstance(end_pos, int) or end_pos <= 0:
                    issues.append('invalid_end_position')
                if isinstance(start_pos, int) and isinstance(end_pos, int) and start_pos >= end_pos:
                    issues.append('start_position_gte_end_position')
            else:
                issues.append(f'text_mismatch:ratio={ref.get("text_match_score", 0):.2f}')

            rule['reference_verified'] = False
            rule['reference_verification_note'] = '; '.join(issues) if issues else 'unverified'
            failed += 1

        # Iterate all rules in entity_types and relationships
        for entity_info in self.all_entity_types.values():
            for rule in entity_info.get('business_rules', []):
                _verify_rule(rule)
        for rel_info in self.all_relationships.values():
            for rule in rel_info.get('business_rules', []):
                _verify_rule(rule)

        print(f"\n{'='*70}", flush=True)
        print(f"📎 SOURCE REFERENCE VERIFICATION", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"   • Total rules: {total}", flush=True)
        print(f"   • Verified ✓: {verified} (includes {recovered} recovered)", flush=True)
        print(f"   • Failed ✗: {failed}", flush=True)
        print(f"   • Coerced from string (unverified): {coerced}", flush=True)
        print(f"   • Verification rate: {verified}/{total} ({(verified/total*100) if total else 0:.0f}%)", flush=True)
        print(f"   • Recovery rate: {recovered}/{total} ({(recovered/total*100) if total else 0:.0f}%)", flush=True)
        print(f"{'='*70}\n", flush=True)

    def save_results(self, output_file: str):
        """Save combined results with detailed statistics."""
        # Calculate confidence scores for all rules before saving
        for entity_name, entity_info in self.all_entity_types.items():
            for rule in entity_info.get('business_rules', []):
                self._calculate_confidence_score(rule)
        
        for rel_name, rel_info in self.all_relationships.items():
            for rule in rel_info.get('business_rules', []):
                self._calculate_confidence_score(rule)
        
        results = {
            "entity_types": self.all_entity_types,
            "relationships": self.all_relationships,
            "extraction_metadata": {
                "total_entities": len(self.all_entity_types),
                "total_relationships": len(self.all_relationships),
                "total_business_rules": self.count_rules(),
                "target_rules": self.config.target_rules_count,
                "extraction_model": self.config.reasoning_model,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        total_rules = self.count_rules()
        print(f"\n✓ Results saved to: {output_file}", flush=True)
        
        print(f"✓ Total business rules extracted: {total_rules}", flush=True)
        
        # Show breakdown by entity and relationship
        print(f"\n📊 Extraction Breakdown:", flush=True)
        for entity_name, entity_info in self.all_entity_types.items():
            rule_count = len(entity_info.get('business_rules', []))
            print(f"  {entity_name}: {rule_count} rules", flush=True)
        
        for rel_name, rel_info in self.all_relationships.items():
            rule_count = len(rel_info.get('business_rules', []))
            print(f"  {rel_name}: {rule_count} rules", flush=True)
    
    def generate_summary_report(self) -> str:
        """Generate a detailed summary report of extracted rules."""
        total_rules = self.count_rules()
        
        # Count by rule type
        rule_types_count = {}
        for entity in self.all_entity_types.values():
            for rule in entity.get('business_rules', []):
                rule_type = rule.get('rule_type', 'unknown')
                rule_types_count[rule_type] = rule_types_count.get(rule_type, 0) + 1
        
        for rel in self.all_relationships.values():
            for rule in rel.get('business_rules', []):
                rule_type = rule.get('rule_type', 'unknown')
                rule_types_count[rule_type] = rule_types_count.get(rule_type, 0) + 1
        
        # Count rules by entity (for coverage info)
        entity_rules_count = {}
        for entity_name, entity_data in self.all_entity_types.items():
            count = len(entity_data.get('business_rules', []))
            if count > 0:
                entity_rules_count[entity_name] = count
        
        report = f"\n{'='*80}\n"
        report += "BUSINESS RULES EXTRACTION SUMMARY\n"
        report += f"{'='*80}\n\n"
        report += f"📊 Total Business Rules Extracted: {total_rules}\n"
        report += f"🎯 Target Rules: {self.config.target_rules_count}\n"
        report += f"🤖 Model Used: {self.config.reasoning_model}\n\n"
        
        report += "📋 Rules by Type:\n"
        for rule_type, count in sorted(rule_types_count.items(), key=lambda x: x[1], reverse=True):
            report += f"  • {rule_type.title()}: {count} rules\n"
        
        report += f"\n🏷️  Coverage:\n"
        report += f"  • Entity Types with Rules: {len(self.all_entity_types)}\n"
        report += f"  • Relationship Types with Rules: {len(self.all_relationships)}\n"
        
        report += f"\n📌 Top Entities by Rule Count:\n"
        for entity_name, count in sorted(entity_rules_count.items(), key=lambda x: x[1], reverse=True)[:5]:
            report += f"  • {entity_name}: {count} rules\n"
        
        return report


def main():
    """Main extraction function with enhanced configuration."""
    # Load configuration
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils.config import get_config
    
    config = get_config()
    
    # Configuration from config file
    OPENAI_API_KEY = config.get_openai_api_key()
    REASONING_EFFORT = config.get_reasoning_effort()
    REASONING_MODEL = config.get_reasoning_model()
    OPTIMIZER_MODEL = config.get_optimizer_model()
    ENTITY_RELATIONSHIP_FILE = str(config.get_entity_relationship_dir() / "entity_types_and_relationships.json")
    SOURCE_DIRECTORY = str(config.get_organized_dir())
    OUTPUT_FILE = str(config.get_rules_extracted_dir() / "compliance_rules_with_entities.json")
    TARGET_RULES = config.get_target_rules()
    
    print("="*80, flush=True)
    print("ENHANCED BUSINESS RULES EXTRACTOR", flush=True)
    print(f"Using Entity-Relationship Definitions + {REASONING_MODEL} Reasoning", flush=True)
    print("="*80, flush=True)
    print(f"\nConfiguration:", flush=True)
    print(f"  Entity Definitions: {ENTITY_RELATIONSHIP_FILE}", flush=True)
    print(f"  Source Directory: {SOURCE_DIRECTORY}", flush=True)
    print(f"  Target Rules: {TARGET_RULES}", flush=True)
    print(f"  Reasoning Model: {REASONING_MODEL}", flush=True)
    print(f"  Reasoning Effort: {REASONING_EFFORT}", flush=True)
    print(f"  Output File: {OUTPUT_FILE}", flush=True)
    print("="*80 + "\n", flush=True)
    
    rules_config = RulesExtractionConfig(
        target_rules_count=TARGET_RULES,
        reasoning_model=REASONING_MODEL,
        optimization_model=OPTIMIZER_MODEL
    )
    
    # Initialize extractor
    extractor = BusinessRulesExtractor(
        api_key=OPENAI_API_KEY,
        entity_relationship_file=ENTITY_RELATIONSHIP_FILE,
        target_rules_count=TARGET_RULES,
        reasoning_effort=REASONING_EFFORT,
        config=rules_config
    )
    
    # Load documents in batches
    batches = extractor.read_text_files_batch(SOURCE_DIRECTORY)
    
    if not batches:
        print("❌ Error: No documents found!", flush=True)
        print(f"   Please check if {SOURCE_DIRECTORY} exists and contains .txt files", flush=True)
        return
    
    print(f"\n{'='*80}", flush=True)
    print(f"PROCESSING {len(batches)} BATCHES (PARALLEL MODE)", flush=True)
    print(f"{'='*80}\n", flush=True)
    
    # Process batches in parallel (simultaneous API calls)
    # This reduces extraction time significantly
    max_workers = int(os.environ.get('MAX_WORKERS', '20'))  # Default to 20 workers, override with MAX_WORKERS env var
    extractor.extract_rules_parallel(batches, max_workers=max_workers)

    # Validate that every rule is bucketed under a canonical Agent 2
    # entity/relationship name and re-classify (or drop) any orphans.
    # Set AGENT3_VALIDATE_ENTITY_RETRIES=0 to disable. Default: 3 retries.
    validate_retries = int(os.environ.get('AGENT3_VALIDATE_ENTITY_RETRIES', '3'))
    if validate_retries > 0:
        extractor.validate_entity_coverage(max_retries=validate_retries)

    # Verify source references against actual chunk files
    extractor._verify_source_references(SOURCE_DIRECTORY)
    
    # Save final results
    extractor.save_results(OUTPUT_FILE)
    
    # Generate and display summary
    summary = extractor.generate_summary_report()
    print(summary, flush=True)
    
    print("\n" + "="*80, flush=True)
    print("EXTRACTION COMPLETE", flush=True)
    print("="*80, flush=True)
    print(f"\n✓ Detailed rules saved to: {OUTPUT_FILE}", flush=True)
    print(f"✓ Run 'python view_business_rules.py {OUTPUT_FILE}' to view results", flush=True)
    print(f"✓ Use this output for knowledge graph construction", flush=True)


if __name__ == "__main__":
    main()
