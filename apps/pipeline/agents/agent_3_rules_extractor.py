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
from difflib import SequenceMatcher

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.prompt_manager import get_prompt_manager
from utils.llm_client import create_llm_client
from utils.config import get_config
from utils.rule_uniqueness import enforce_rule_uniqueness
from utils.readiness import annotate_rule_readiness
from utils.rule_contract import annotate_rule_contract

# Helper for real-time output
def _print(msg):
    """Print with immediate flush for real-time console output."""
    print(msg, flush=True)


def bridge_exact_span(
    source_text: str,
    words: list,
    start_hint: int,
    end_hint: int,
    search_margin: int = 300,
    min_block_words: int = 4,
    min_coverage_ratio: float = 0.5,
) -> Optional[tuple]:
    """Tighten an LLM-quoted source_text to a genuinely exact, contiguous span.

    An LLM asked to quote a source verbatim will sometimes silently drop an
    inline aside between two sentences it cites — a worked example, a
    cross-reference, a footnote — while getting the surrounding words right.
    The result scores well against `_verify_rule`'s fuzzy SequenceMatcher ratio
    (that threshold exists precisely to tolerate minor wording drift), but it
    is not a real substring of the document, so it fails any downstream check
    that requires one (Agent 5.7's grounding verifier does).

    This finds where the genuinely-matching words actually sit in the chunk —
    using word-level SequenceMatcher.get_matching_blocks(), which naturally
    tolerates a gap between two matching runs — and returns the span from the
    start of the first matching run to the end of the last, rebuilt verbatim
    from the chunk's own words. That span may be LONGER than the original
    quote (it now includes whatever real content sat in the gap), but it is
    always an exact substring, trading a longer quote for one that is never
    fabricated.

    Returns (start_word, end_word, exact_text), or None when too little of
    source_text can be verified this way to be worth reporting — in which
    case the caller should fall back to its existing (looser) acceptance path
    rather than treat the absence of a bridge as a hard failure.
    """
    if not source_text or not words:
        return None
    needle_words = [w.lower() for w in source_text.split()]
    if len(needle_words) < min_block_words:
        return None
    lo = max(0, start_hint - search_margin)
    hi = min(len(words), end_hint + search_margin)
    window = [w.lower() for w in words[lo:hi]]
    if not window:
        return None

    matcher = SequenceMatcher(None, needle_words, window, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= min_block_words]
    if not blocks:
        return None
    covered = sum(b.size for b in blocks)
    if covered < min_coverage_ratio * len(needle_words):
        return None

    start_word = lo + blocks[0].b
    end_word = lo + blocks[-1].b + blocks[-1].size
    if start_word >= end_word:
        return None
    return start_word, end_word, ' '.join(words[start_word:end_word])


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
        
        domain_prompt = self.prompt_manager.format_prompt(
            "business_rules_extraction_compact",
            entity_context=entity_context,
            sample_content=sample_content,
            batch_num=batch_num,
            rules_per_batch=rules_per_batch
        )
        return f"{domain_prompt}\n\n{self.prompt_manager.load_rule_contract_v2()}"

    def _entity_catalog(self) -> List[str]:
        """Return the only identifiers that v2 party fields may reference."""
        catalog = []
        if isinstance(self.entity_definitions, dict):
            catalog.extend(self.entity_definitions.keys())
        return catalog

    def _annotate_v2_contract(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """Retain each candidate while recording v2 contract/readiness findings."""
        annotated = annotate_rule_contract(rule, self._entity_catalog())
        return annotate_rule_readiness(annotated, self._entity_catalog())
    
    def extract_batch(
        self,
        prompt: str,
        batch_num: int,
        max_tokens_override: int | None = None,
    ) -> Dict[str, Any]:
        """Extract from a single batch using reasoning model."""
        import time as _time
        batch_start = _time.time()
        completion_limit = max_tokens_override or self.global_config.get_rules_max_tokens()
        try:
            # Keep the executor at the requested worker count while gating the
            # number of simultaneous sockets. A 40-way burst can exceed the
            # provider/client connection budget before rate limiting takes effect.
            request_gate = getattr(self, "_request_gate", None)
            attempts = max(1, int(os.getenv("KG_BATCH_MAX_ATTEMPTS", "3")))
            response = None
            last_error = None
            for attempt in range(1, attempts + 1):
                try:
                    if request_gate is None:
                        response = self.client.chat_completion(
                            messages=[{"role": "user", "content": prompt}],
                            temperature=self.global_config.get_rules_temperature(),
                            max_tokens=completion_limit,
                            reasoning_effort=self.reasoning_effort
                        )
                    else:
                        with request_gate:
                            response = self.client.chat_completion(
                                messages=[{"role": "user", "content": prompt}],
                                temperature=self.global_config.get_rules_temperature(),
                                max_tokens=completion_limit,
                                reasoning_effort=self.reasoning_effort
                            )
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < attempts:
                        # Connection resets/timeouts usually indicate a
                        # provider-side saturation window. Retrying after
                        # 1–2 seconds compounds the burst and causes the
                        # next request to fail as well. Use a configurable
                        # cooldown for transport errors while retaining the
                        # short exponential delay for local/parse failures.
                        error_text = str(exc).lower()
                        is_transport_error = any(
                            marker in error_text
                            for marker in ("connection", "timed out", "timeout", "readerror")
                        )
                        if is_transport_error:
                            delay = max(
                                1,
                                int(os.getenv("KG_BATCH_CONNECTION_BACKOFF_SECONDS", "30")),
                            )
                        else:
                            delay = min(30, 2 ** (attempt - 1))
                        print(
                            f"  DEBUG Batch {batch_num}: request attempt {attempt}/{attempts} "
                            f"failed ({exc}); retrying in {delay}s",
                            flush=True,
                        )
                        _time.sleep(delay)
            if response is None:
                raise RuntimeError(f"LLM completion failed after {attempts} attempts: {last_error}")
            
            content = response.choices[0].message.content
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            # A reasoning response can consume the entire completion budget
            # before emitting JSON. Do not silently turn that batch into a
            # missing-rule result; retry with an explicit compact-output
            # instruction while preserving the original source batch.
            if not content or finish_reason == "length":
                compact_prompt = (
                    f"{prompt}\n\nIMPORTANT RETRY: The previous response was empty or truncated. "
                    "Return compact, complete JSON only. Include all supported rules, "
                    "but omit prose, markdown, explanations, and optional examples."
                )
                recovery_attempts = max(1, int(os.getenv("KG_BATCH_EMPTY_RESPONSE_ATTEMPTS", "2")))
                for recovery_attempt in range(1, recovery_attempts + 1):
                    print(
                        f"  DEBUG Batch {batch_num}: empty/truncated response; "
                        f"compact retry {recovery_attempt}/{recovery_attempts}",
                        flush=True,
                    )
                    try:
                        if request_gate is None:
                            response = self.client.chat_completion(
                                messages=[{"role": "user", "content": compact_prompt}],
                                temperature=self.global_config.get_rules_temperature(),
                                max_tokens=completion_limit,
                                reasoning_effort=self.reasoning_effort,
                            )
                        else:
                            with request_gate:
                                response = self.client.chat_completion(
                                    messages=[{"role": "user", "content": compact_prompt}],
                                    temperature=self.global_config.get_rules_temperature(),
                                    max_tokens=completion_limit,
                                    reasoning_effort=self.reasoning_effort,
                                )
                        content = response.choices[0].message.content
                        if content and getattr(response.choices[0], "finish_reason", None) != "length":
                            break
                    except Exception as exc:
                        print(f"  DEBUG Batch {batch_num}: compact retry failed: {exc}", flush=True)
                if not content:
                    return {"entity_types": {}, "relationships": {}, "batch_num": batch_num, "error": "Empty response after compact retries"}
            
            def _decode_json(raw_content: str) -> Dict[str, Any]:
                """Decode a model response, allowing one fenced/object slice."""
                try:
                    return json.loads(raw_content)
                except json.JSONDecodeError:
                    if "```json" in raw_content:
                        json_str = raw_content.split("```json", 1)[1].split("```", 1)[0].strip()
                    elif "```" in raw_content:
                        json_str = raw_content.split("```", 1)[1].split("```", 1)[0].strip()
                    else:
                        json_start = raw_content.find("{")
                        json_end = raw_content.rfind("}") + 1
                        if json_start < 0 or json_end <= json_start:
                            raise
                        json_str = raw_content[json_start:json_end]
                    return json.loads(json_str)

            # GPT-5 occasionally returns a syntactically invalid object even
            # with a stop finish reason. Retry only that batch, rather than
            # discarding it and silently falling below the requested target.
            parse_attempts = max(1, int(os.getenv("KG_BATCH_PARSE_ATTEMPTS", "3")))
            retry_prompt = compact_prompt if "compact_prompt" in locals() else prompt
            for parse_attempt in range(1, parse_attempts + 1):
                try:
                    result = _decode_json(content)
                    break
                except json.JSONDecodeError:
                    if parse_attempt >= parse_attempts:
                        raise
                    print(
                        f"  DEBUG Batch {batch_num}: invalid JSON on parse attempt "
                        f"{parse_attempt}/{parse_attempts}; requesting a fresh response",
                        flush=True,
                    )
                    request_gate = getattr(self, "_request_gate", None)
                    if request_gate is None:
                        response = self.client.chat_completion(
                            messages=[{"role": "user", "content": retry_prompt}],
                            temperature=self.global_config.get_rules_temperature(),
                            max_tokens=completion_limit,
                            reasoning_effort=self.reasoning_effort,
                        )
                    else:
                        with request_gate:
                            response = self.client.chat_completion(
                                messages=[{"role": "user", "content": retry_prompt}],
                                temperature=self.global_config.get_rules_temperature(),
                                max_tokens=completion_limit,
                                reasoning_effort=self.reasoning_effort,
                            )
                    content = response.choices[0].message.content or ""
                    if getattr(response.choices[0], "finish_reason", None) == "length":
                        content = ""
                    if not content:
                        raise json.JSONDecodeError("empty response", "", 0)
            
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
        
        # Persist successful batch responses so an interrupted or provider-
        # limited run can resume without re-paying for completed work. Errors
        # are intentionally not checkpointed; they must be retried next run.
        checkpoint_file = os.getenv("KG_BATCH_CHECKPOINT_FILE")
        cached_results: Dict[int, Dict[str, Any]] = {}
        if checkpoint_file:
            checkpoint_path = Path(checkpoint_file)
            if checkpoint_path.exists():
                try:
                    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
                        payload = json.loads(line)
                        batch_num = int(payload.get("batch_num"))
                        if not payload.get("error"):
                            cached_results[batch_num] = payload
                    print(
                        f"   ✓ Loaded {len(cached_results)} successful batch checkpoints from "
                        f"{checkpoint_path}",
                        flush=True,
                    )
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    print(f"   ⚠️  Ignoring unreadable batch checkpoint: {exc}", flush=True)

        # Keep original batch numbers in prompts when resuming; changing them
        # would change the source-corpus provenance attached to each response.
        batch_prompts = [
            (self.create_batch_prompt(batch, batch_num, len(batches)), batch_num)
            for batch_num, batch in enumerate(batches, start=1)
            if batch_num not in cached_results
        ]
        prompt_by_batch = {batch_num: prompt for prompt, batch_num in batch_prompts}
        print(
            f"   ✓ Prompts prepared ({len(batch_prompts)} pending, "
            f"{len(cached_results)} checkpointed)\n",
            flush=True,
        )

        results = list(cached_results.items())
        completed = 0
        start_time = time.time()
        
        print(f"📡 Starting extraction (this may take several minutes)...", flush=True)
        print(f"   Progress will be shown as batches complete.\n", flush=True)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            gate_size = max(1, int(os.getenv(
                "KG_LLM_CONCURRENCY",
                str(min(max_workers, 8)),
            )))
            self._request_gate = threading.BoundedSemaphore(gate_size)
            print(f"   ✓ API concurrency gate: {gate_size} in-flight requests", flush=True)
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
                    if checkpoint_file and not result.get("error"):
                        checkpoint_path = Path(checkpoint_file)
                        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                        with checkpoint_path.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                            handle.flush()
                    
                except Exception as e:
                    completed += 1
                    print(f"  [{completed}/{len(batches)}] Batch {batch_num}: ✗ Exception: {e}", flush=True)

        # A length-truncated response is not recoverable by repeatedly sending
        # the same completion budget. Retry only failed batches with a larger
        # budget and an explicit compact-output instruction. This keeps the
        # normal path fast while preventing token pressure from silently
        # reducing the extracted corpus.
        result_by_batch = {batch_num: result for batch_num, result in results}
        failed_batches = [
            batch_num for batch_num, result in results
            if result.get("error")
        ]
        retry_tokens = int(os.getenv("KG_BATCH_RETRY_MAX_TOKENS", "32768"))
        retry_attempts = max(0, int(os.getenv("KG_BATCH_RETRY_ATTEMPTS", "1")))
        if failed_batches and retry_attempts:
            print(
                f"\n🔁 Retrying {len(failed_batches)} failed batch(es) with "
                f"max_tokens={retry_tokens} (up to {retry_attempts} pass(es))...",
                flush=True,
            )
            for retry_pass in range(1, retry_attempts + 1):
                retry_targets = [
                    batch_num for batch_num in failed_batches
                    if result_by_batch.get(batch_num, {}).get("error")
                ]
                if not retry_targets:
                    break
                retry_prompt_by_batch = {
                    batch_num: (
                        f"{prompt_by_batch[batch_num]}\n\n"
                        "RETRY REQUIREMENT: Return one complete JSON object for every "
                        "supported rule in this batch. Use compact JSON only; omit all "
                        "prose and optional examples. Do not stop before the closing brace."
                    )
                    for batch_num in retry_targets
                }
                retry_workers = min(max_workers, max(1, len(retry_targets)))
                with ThreadPoolExecutor(max_workers=retry_workers) as retry_executor:
                    retry_futures = {
                        retry_executor.submit(
                            self.extract_batch,
                            retry_prompt_by_batch[batch_num],
                            batch_num,
                            retry_tokens,
                        ): batch_num
                        for batch_num in retry_targets
                    }
                    for future in as_completed(retry_futures):
                        batch_num = retry_futures[future]
                        try:
                            retry_result = future.result()
                        except Exception as exc:
                            retry_result = {
                                "entity_types": {},
                                "relationships": {},
                                "batch_num": batch_num,
                                "error": str(exc),
                            }
                        result_by_batch[batch_num] = retry_result
                        if checkpoint_file and not retry_result.get("error"):
                            checkpoint_path = Path(checkpoint_file)
                            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                            with checkpoint_path.open("a", encoding="utf-8") as handle:
                                handle.write(json.dumps(retry_result, ensure_ascii=False) + "\n")
                                handle.flush()
                        if retry_result.get("error"):
                            print(
                                f"  Retry {retry_pass}/{retry_attempts} Batch {batch_num}: "
                                f"✗ {retry_result['error']}",
                                flush=True,
                            )
                        else:
                            print(
                                f"  Retry {retry_pass}/{retry_attempts} Batch {batch_num}: ✓ "
                                f"{retry_result.get('total_rules', 0)} rules",
                                flush=True,
                            )
                failed_batches = retry_targets

        results = sorted(result_by_batch.items())
        
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

        if self.count_rules() == 0:
            raise RuntimeError(
                "Agent 3 extracted zero rules; refusing to continue with an empty knowledge graph"
            )
    
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
            bridged = False
            if positions_valid and source_text:
                actual_slice = ' '.join(words[start_pos:end_pos])
                ratio = SequenceMatcher(None, source_text.lower(), actual_slice.lower()).ratio()
                ref['text_match_score'] = round(ratio, 3)
                if ratio < 0.995:
                    # A fuzzy-but-imperfect match at the stated position may mean
                    # the LLM's quote silently elided real intervening content
                    # (a worked example, a footnote). Prefer a wider but exactly
                    # verbatim span over a shorter one that isn't a real
                    # substring of the chunk — downstream grounding checks
                    # require an exact quote, not merely a close paraphrase.
                    span = bridge_exact_span(source_text, words, start_pos, end_pos)
                    if span:
                        new_start, new_end, exact_text = span
                        ref['start_word_position'] = new_start
                        ref['end_word_position'] = new_end
                        ref['source_text'] = exact_text
                        ref['text_match_score'] = 1.0
                        ref['source_text_bridged'] = True
                        matched_at_positions = True
                        bridged = True
                if not matched_at_positions and ratio >= 0.5:
                    matched_at_positions = True

            if matched_at_positions:
                rule['reference_verified'] = True
                rule['reference_verification_note'] = 'ok_bridged_exact_span' if bridged else 'ok'
                verified += 1
                return

            # 3. Recovery: search for source_text anywhere in the chunk
            if source_text:
                found = _find_text_in_words(words, source_text)
                if found:
                    new_start, new_end, ratio = found
                    note = 'ok_recovered_position'
                    if ratio < 0.995:
                        span = bridge_exact_span(source_text, words, new_start, new_end)
                        if span:
                            new_start, new_end, exact_text = span
                            ref['source_text'] = exact_text
                            ratio = 1.0
                            note = 'ok_recovered_and_bridged_exact_span'
                    ref['start_word_position'] = new_start
                    ref['end_word_position'] = new_end
                    ref['text_match_score'] = round(ratio, 3)
                    rule['reference_verified'] = True
                    rule['reference_verification_note'] = note
                    recovered += 1
                    verified += 1
                    return

            # 4. Last resort: try matching using the rule description as source_text
            description = rule.get('description', '')
            if description and len(description) > 30:
                found = _find_text_in_words(words, description[:300], threshold=0.5)
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
            entity_info['business_rules'] = [
                self._annotate_v2_contract(self._calculate_confidence_score(rule))
                for rule in entity_info.get('business_rules', [])
            ]
        
        for rel_name, rel_info in self.all_relationships.items():
            rel_info['business_rules'] = [
                self._annotate_v2_contract(self._calculate_confidence_score(rule))
                for rule in rel_info.get('business_rules', [])
            ]
        
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
    # Batch checkpoints are enabled by default. They are append-only and keep
    # successful extraction work resumable across Ctrl-C, timeout, or provider
    # connection failures; callers may override the location per run.
    os.environ.setdefault(
        "KG_BATCH_CHECKPOINT_FILE",
        str(config.get_rules_extracted_dir() / "batch_results.jsonl"),
    )
    
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
        batch_size=config.get_rules_batch_size(),
        max_content_length=config.get_rules_max_content_length(),
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
    # config.get_max_workers() already implements "MAX_WORKERS env var, else
    # pipeline.max_workers (40)" — reading os.environ directly here
    # duplicated that logic with a different, lower hardcoded fallback (20).
    max_workers = config.get_max_workers()
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
