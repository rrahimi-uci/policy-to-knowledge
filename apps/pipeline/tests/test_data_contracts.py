"""
Data contract tests for the agent pipeline.

Verifies that prompt output schemas (what we ask the LLM to produce) contain
the exact field names that downstream agent code reads.  Tests cover BOTH the
AML and mortgage domains so that a prompt edit in one domain that breaks the
pipeline is caught immediately.

Contracts validated
──────────────────
 Prompt file                    → Consumer agent(s)
 ──────────────────────────────────────────────────────
 entity_extraction.txt          → Agent 2 / Agent 4
 entity_refinement.txt          → Agent 2 (meta-agent loop)
 business_rules_extraction.txt  → Agent 3 / Agent 4
 rule_deduplication.txt         → Agent 5
 dependency_analysis.txt        → Agent 5 / Agent 6
 rule_matcher_batch.txt         → Agent 8 / Agent 9
 document_structure_analysis.txt→ Agent 1
 entity_resolution.txt          → Agent 2 (multi-doc)
 rule_resolution.txt            → Agent 3 (multi-doc)
"""

import json
import re
import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DOMAINS = ["mortgage", "aml"]
DOMAIN_PROMPTS = PROJECT_ROOT / "domain-prompts"
SHARED_PROMPTS = PROJECT_ROOT / "prompts"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_prompt(domain: str, name: str) -> str:
    """Load a prompt file, domain-specific first, shared fallback."""
    domain_path = DOMAIN_PROMPTS / domain / f"{name}.txt"
    if domain_path.exists():
        return domain_path.read_text(encoding="utf-8")
    shared_path = SHARED_PROMPTS / f"{name}.txt"
    if shared_path.exists():
        return shared_path.read_text(encoding="utf-8")
    pytest.skip(f"Prompt {name}.txt not found for domain={domain}")


def _extract_json_blocks(text: str) -> list[str]:
    """Return all JSON-ish blocks (```json...```) from a prompt file."""
    blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        # Try bare { ... } blocks (some prompts omit fences)
        blocks = re.findall(r"(\{[\s\S]*?\n\})", text)
    return blocks


def _json_field_names(json_text: str) -> set[str]:
    """Extract quoted keys from a JSON-ish template (may contain placeholders)."""
    return set(re.findall(r'"([a-z_][a-z0-9_]*)"(?:\s*:)', json_text, re.IGNORECASE))


def _prompt_contains_field(prompt_text: str, field: str) -> bool:
    """Check whether a field name appears as a JSON key in the prompt."""
    # Match "field_name": or "field_name" : (with optional whitespace)
    return bool(re.search(rf'"{re.escape(field)}"\s*:', prompt_text))


def _prompt_contains_any(prompt_text: str, *values: str) -> bool:
    """Check whether any of the given string values appears in the prompt."""
    return any(v in prompt_text for v in values)


# ─────────────────────────────────────────────────────────────────────────────
# 0. Structural: every domain has all expected prompt files
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_PROMPT_FILES = [
    "business_rules_extraction",
    "dependency_analysis",
    "document_structure_analysis",
    "entity_extraction",
    "entity_refinement",
    "entity_resolution",
    "rule_deduplication",
    "rule_matcher",
    "rule_matcher_batch",
    "rule_resolution",
    "validation_report",
]


class TestPromptFileExistence:
    """Every domain directory must contain all expected prompt files."""

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("prompt_name", EXPECTED_PROMPT_FILES)
    def test_prompt_file_exists(self, domain, prompt_name):
        path = DOMAIN_PROMPTS / domain / f"{prompt_name}.txt"
        assert path.exists(), f"Missing {domain}/{prompt_name}.txt"

    @pytest.mark.parametrize("prompt_name", EXPECTED_PROMPT_FILES)
    def test_shared_prompt_file_exists(self, prompt_name):
        path = SHARED_PROMPTS / f"{prompt_name}.txt"
        assert path.exists(), f"Missing shared prompts/{prompt_name}.txt"

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("prompt_name", EXPECTED_PROMPT_FILES)
    def test_prompt_file_not_empty(self, domain, prompt_name):
        path = DOMAIN_PROMPTS / domain / f"{prompt_name}.txt"
        assert path.stat().st_size > 100, f"{domain}/{prompt_name}.txt is too small"


# ─────────────────────────────────────────────────────────────────────────────
# 1. rule_deduplication  →  Agent 5 (deduplicate_rules)
#
#    Agent 5 reads:
#      dedup_result.get("duplicate_groups", [])
#      group["primary_rule_id"]
#      group["duplicate_rule_ids"]
#      group["merged_description"]
#      group["rationale"]
#      group.get("confidence", "medium")
#      group.get("similarity_score")
#      group.get("score_breakdown", {})
#      group.get("primary_selection_reason", "")
#      group.get("merged_examples", [])
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleDeduplicationContract:
    """rule_deduplication.txt must produce fields that Agent 5 reads."""

    REQUIRED_TOP_LEVEL = ["duplicate_groups"]
    REQUIRED_GROUP_FIELDS = [
        "primary_rule_id",
        "duplicate_rule_ids",
        "merged_description",
        "rationale",
    ]
    OPTIONAL_GROUP_FIELDS = [
        "confidence",
        "similarity_score",
        "score_breakdown",
        "primary_selection_reason",
        "merged_examples",
    ]

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_top_level_duplicate_groups_key(self, domain):
        prompt = _load_prompt(domain, "rule_deduplication")
        assert _prompt_contains_field(prompt, "duplicate_groups"), (
            f"{domain}/rule_deduplication.txt must instruct LLM to output "
            f'"duplicate_groups" (Agent 5 line ~213)'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", REQUIRED_GROUP_FIELDS)
    def test_required_group_field_present(self, domain, field):
        prompt = _load_prompt(domain, "rule_deduplication")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/rule_deduplication.txt must include "{field}" in '
            f"duplicate_groups (Agent 5 reads it)"
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", OPTIONAL_GROUP_FIELDS)
    def test_optional_group_field_present(self, domain, field):
        prompt = _load_prompt(domain, "rule_deduplication")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/rule_deduplication.txt should include "{field}" in '
            f"duplicate_groups for full Agent 5 compatibility"
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_no_legacy_merge_decisions_key(self, domain):
        """Ensure old 'merge_decisions' key is NOT present (Agent 5 never reads it)."""
        prompt = _load_prompt(domain, "rule_deduplication")
        assert not _prompt_contains_field(prompt, "merge_decisions"), (
            f'{domain}/rule_deduplication.txt still contains "merge_decisions" — '
            f"Agent 5 reads duplicate_groups, not merge_decisions"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. dependency_analysis  →  Agent 5 (analyze_dependencies) + Agent 6
#
#    Agent 5 reads from LLM response:
#      dep_result.get("dependencies", [])
#      dep["source_rule_id"]
#      dep["target_rule_id"]
#      dep["dependency_type"]
#      dep["rationale"]
#      dep["impact"]
#      dep.get("strength", 3)
#      dep_result.get("dependency_chains", [])
#      dep_result.get("circular_dependencies", [])
#
#    Agent 5 writes to rule (Agent 6 reads):
#      rule["dependencies"][i]["depends_on_rule"]
#      rule["dependencies"][i]["dependency_type"]
# ─────────────────────────────────────────────────────────────────────────────

class TestDependencyAnalysisContract:
    """dependency_analysis.txt must produce fields that Agent 5 reads."""

    REQUIRED_DEP_FIELDS = [
        "source_rule_id",
        "target_rule_id",
        "dependency_type",
        "rationale",
        "impact",
    ]
    VALID_DEPENDENCY_TYPES = [
        "prerequisite",
        "sequential",
        "conditional",
        "complementary",
        "contradictory",
        "override",
        "validation",
    ]

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_top_level_dependencies_key(self, domain):
        prompt = _load_prompt(domain, "dependency_analysis")
        assert _prompt_contains_field(prompt, "dependencies"), (
            f'{domain}/dependency_analysis.txt must instruct "dependencies" array'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", REQUIRED_DEP_FIELDS)
    def test_required_dependency_field(self, domain, field):
        prompt = _load_prompt(domain, "dependency_analysis")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/dependency_analysis.txt must include "{field}" '
            f"(Agent 5 reads dep[\"{field}\"])"
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_strength_field(self, domain):
        prompt = _load_prompt(domain, "dependency_analysis")
        assert _prompt_contains_field(prompt, "strength"), (
            f'{domain}/dependency_analysis.txt must include "strength" '
            f"(Agent 5 reads dep.get('strength', 3))"
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_circular_dependencies_key(self, domain):
        prompt = _load_prompt(domain, "dependency_analysis")
        assert _prompt_contains_field(prompt, "circular_dependencies") or \
               _prompt_contains_any(prompt, "circular_dependencies"), (
            f'{domain}/dependency_analysis.txt should include "circular_dependencies"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_dependency_chains_key(self, domain):
        prompt = _load_prompt(domain, "dependency_analysis")
        assert _prompt_contains_field(prompt, "dependency_chains") or \
               _prompt_contains_any(prompt, "dependency_chains"), (
            f'{domain}/dependency_analysis.txt should include "dependency_chains"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_all_seven_dependency_types_mentioned(self, domain):
        prompt = _load_prompt(domain, "dependency_analysis")
        for dep_type in self.VALID_DEPENDENCY_TYPES:
            assert dep_type in prompt.lower(), (
                f'{domain}/dependency_analysis.txt must mention dependency type '
                f'"{dep_type}". Agent 5 expects all 7 types.'
            )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_no_legacy_field_names(self, domain):
        """Ensure old broken field names are NOT present."""
        prompt = _load_prompt(domain, "dependency_analysis")
        for legacy in ["prerequisite_rule_id", "dependent_rule_id"]:
            assert not _prompt_contains_field(prompt, legacy), (
                f'{domain}/dependency_analysis.txt contains legacy field '
                f'"{legacy}" — Agent 5 reads source_rule_id/target_rule_id'
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. rule_matcher_batch  →  Agent 8 (SemanticRuleMatcher)
#
#    Agent 8 reads from each result:
#      result.get("relationship", "UNRELATED")
#      result.get("confidence", 0.5)
#      result.get("similarity_score", 0)
#      result.get("reasoning", "")
#      result.get("key_comparison", {})
#      result.get("conflict_detail", {})
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleMatcherBatchContract:
    """rule_matcher_batch.txt must produce fields that Agent 8 reads."""

    REQUIRED_FIELDS = [
        "pair_id",
        "relationship",
        "confidence",
        "similarity_score",
        "reasoning",
    ]
    VALID_RELATIONSHIPS = ["IDENTICAL", "EQUIVALENT", "CONTRADICTORY", "UNRELATED"]

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", REQUIRED_FIELDS)
    def test_required_field_present(self, domain, field):
        prompt = _load_prompt(domain, "rule_matcher_batch")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/rule_matcher_batch.txt must include "{field}" '
            f"(Agent 8 reads it)"
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_relationship_enum_values(self, domain):
        prompt = _load_prompt(domain, "rule_matcher_batch")
        for value in self.VALID_RELATIONSHIPS:
            assert value in prompt, (
                f'{domain}/rule_matcher_batch.txt must mention "{value}" '
                f"as a valid relationship value"
            )

    def test_key_comparison_present_aml(self):
        """Agent 8 reads result.get('key_comparison', {}). AML prompt has it; mortgage is optional."""
        prompt = _load_prompt("aml", "rule_matcher_batch")
        assert _prompt_contains_field(prompt, "key_comparison") or \
               _prompt_contains_any(prompt, "key_comparison"), (
            'aml/rule_matcher_batch.txt should include "key_comparison" '
            '(Agent 8 stores it in match results)'
        )

    def test_conflict_detail_present_aml(self):
        """Agent 8 reads result.get('conflict_detail', {}) for contradictions. AML prompt has it."""
        prompt = _load_prompt("aml", "rule_matcher_batch")
        assert _prompt_contains_field(prompt, "conflict_detail") or \
               _prompt_contains_any(prompt, "conflict_detail"), (
            'aml/rule_matcher_batch.txt should include "conflict_detail" '
            '(Agent 8 stores it in contradiction results)'
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. entity_extraction  →  Agent 2 / Agent 4
#
#    Agent 2 reads:
#      result.get("entity_types", {})
#      result.get("relationships", {})
#    Agent 4 reads:
#      entity_data.get("entity_types") or entity_data.get("entities", {})
#      entity_data.get("relationships", {})
#      entity_info.get("business_rules", [])
# ─────────────────────────────────────────────────────────────────────────────

class TestEntityExtractionContract:
    """entity_extraction.txt must produce fields that Agent 2 and Agent 4 read."""

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_entity_types_key(self, domain):
        prompt = _load_prompt(domain, "entity_extraction")
        has_entity_types = _prompt_contains_field(prompt, "entity_types")
        has_entities = _prompt_contains_field(prompt, "entities")
        assert has_entity_types or has_entities, (
            f'{domain}/entity_extraction.txt must include "entity_types" or '
            f'"entities" (Agent 2/4 read one or both)'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_relationships_key(self, domain):
        prompt = _load_prompt(domain, "entity_extraction")
        assert _prompt_contains_field(prompt, "relationships"), (
            f'{domain}/entity_extraction.txt must include "relationships"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_business_rules_in_entities(self, domain):
        """Entities must have rule summaries: 'business_rules' (mortgage) or 'business_rule_summaries' (AML)."""
        prompt = _load_prompt(domain, "entity_extraction")
        has_business_rules = _prompt_contains_field(prompt, "business_rules")
        has_summaries = _prompt_contains_field(prompt, "business_rule_summaries")
        assert has_business_rules or has_summaries, (
            f'{domain}/entity_extraction.txt must include "business_rules" or '
            f'"business_rule_summaries" within each entity (used as context for Agent 3)'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_entity_attributes(self, domain):
        """Each entity should have definition/description, attributes/key_attributes."""
        prompt = _load_prompt(domain, "entity_extraction")
        has_definition = _prompt_contains_field(prompt, "definition")
        has_description = _prompt_contains_field(prompt, "description")
        assert has_definition or has_description, (
            f'{domain}/entity_extraction.txt must include "definition" or "description" '
            f"for each entity type"
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_relationship_source_target(self, domain):
        """Relationships must have source/target: mortgage uses source_entity/target_entity,
        AML uses source/target.  Agent 4 reads with .get() defaults."""
        prompt = _load_prompt(domain, "entity_extraction")
        has_source_entity = _prompt_contains_field(prompt, "source_entity")
        has_source = _prompt_contains_field(prompt, "source")
        assert has_source_entity or has_source, (
            f'{domain}/entity_extraction.txt must include "source_entity" or "source" '
            f"in relationships"
        )
        has_target_entity = _prompt_contains_field(prompt, "target_entity")
        has_target = _prompt_contains_field(prompt, "target")
        assert has_target_entity or has_target, (
            f'{domain}/entity_extraction.txt must include "target_entity" or "target" '
            f"in relationships"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. business_rules_extraction  →  Agent 3 / Agent 4
#
#    Agent 3 reads:
#      result.get("rules", [])      # flat format (AML)
#      result.get("entity_types")   # nested format (mortgage)
#      r.get("relationship")
#      r.get("entity", "UNKNOWN_ENTITY")
#    Agent 3.5 reads:
#      rule.get("rule_id")
#      rule.get("rule_type")
#      rule.get("description")
#      rule.get("conditions")
#      rule.get("consequences")
#      rule.get("confidence_score")
#      rule.get("mandatory")
#      rule.get("source_reference")
# ─────────────────────────────────────────────────────────────────────────────

class TestBusinessRulesExtractionContract:
    """business_rules_extraction.txt must contain rule field names that Agent 3/3.5/4 read."""

    CORE_RULE_FIELDS = [
        "rule_id",
        "rule_type",
        "description",
        "conditions",
        "consequences",
    ]

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_has_output_container(self, domain):
        """Must instruct LLM to output either 'rules' array or 'entity_types' dict."""
        prompt = _load_prompt(domain, "business_rules_extraction")
        has_rules = _prompt_contains_field(prompt, "rules")
        has_entity_types = _prompt_contains_field(prompt, "entity_types")
        assert has_rules or has_entity_types, (
            f'{domain}/business_rules_extraction.txt must output "rules" or "entity_types"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", CORE_RULE_FIELDS)
    def test_core_rule_field(self, domain, field):
        prompt = _load_prompt(domain, "business_rules_extraction")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/business_rules_extraction.txt must include "{field}" '
            f"in each rule (Agent 3.5 validates it)"
        )

    def test_confidence_score_field_mortgage(self):
        """Mortgage prompt must include confidence_score (Agent 3.5 validates confidence ranges)."""
        prompt = _load_prompt("mortgage", "business_rules_extraction")
        assert _prompt_contains_field(prompt, "confidence_score"), (
            'mortgage/business_rules_extraction.txt must include "confidence_score"'
        )

    def test_source_reference_field_mortgage(self):
        """Mortgage prompt must include source_reference (Agent 3.5 validates it)."""
        prompt = _load_prompt("mortgage", "business_rules_extraction")
        assert _prompt_contains_field(prompt, "source_reference"), (
            'mortgage/business_rules_extraction.txt must include "source_reference"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_regulatory_or_source_reference(self, domain):
        """Each domain must have provenance: source_reference (mortgage) or regulatory_source (AML)."""
        prompt = _load_prompt(domain, "business_rules_extraction")
        has_src_ref = _prompt_contains_field(prompt, "source_reference")
        has_reg_src = _prompt_contains_field(prompt, "regulatory_source")
        assert has_src_ref or has_reg_src, (
            f'{domain}/business_rules_extraction.txt must include "source_reference" '
            f'or "regulatory_source" for rule provenance'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_mandatory_field(self, domain):
        prompt = _load_prompt(domain, "business_rules_extraction")
        assert _prompt_contains_field(prompt, "mandatory"), (
            f'{domain}/business_rules_extraction.txt must include "mandatory" '
            f"(Agent 3.5/6 read it)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. document_structure_analysis  →  Agent 1
#
#    Agent 1 reads:
#      result.get("sections", [])
#      section.get("start_marker")
#      section.get("end_marker")
# ─────────────────────────────────────────────────────────────────────────────

class TestDocumentStructureContract:
    """document_structure_analysis.txt must produce fields Agent 1 reads."""

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_sections_key(self, domain):
        prompt = _load_prompt(domain, "document_structure_analysis")
        assert _prompt_contains_field(prompt, "sections"), (
            f'{domain}/document_structure_analysis.txt must include "sections"'
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Cross-domain structural consistency
#
#    These tests verify that the AML and mortgage prompt schemas are
#    structurally consistent (same top-level keys, same required fields).
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossDomainConsistency:
    """AML and mortgage prompts must share the same structural contract."""

    CRITICAL_PAIRS = [
        ("rule_deduplication", ["duplicate_groups"]),
        ("dependency_analysis", ["dependencies", "circular_dependencies", "dependency_chains"]),
        ("rule_matcher_batch", ["pair_id", "relationship", "confidence", "similarity_score", "reasoning"]),
        ("entity_extraction", ["relationships"]),
    ]

    @pytest.mark.parametrize("prompt_name,fields", CRITICAL_PAIRS)
    def test_both_domains_have_same_critical_fields(self, prompt_name, fields):
        aml = _load_prompt("aml", prompt_name)
        mortgage = _load_prompt("mortgage", prompt_name)
        for field in fields:
            aml_has = _prompt_contains_field(aml, field) or field in aml
            mort_has = _prompt_contains_field(mortgage, field) or field in mortgage
            assert aml_has == mort_has, (
                f'Field "{field}" in {prompt_name}.txt: '
                f"AML={'present' if aml_has else 'MISSING'}, "
                f"mortgage={'present' if mort_has else 'MISSING'} — "
                f"both must match for pipeline compatibility"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Agent 5 output → Agent 6 input contract
#
#    Agent 6 reads from the optimized graph:
#      data.get("business_rules", [])
#      rule.get("rule_id")
#      rule.get("rule_type")
#      rule.get("rule_name")
#      rule.get("mandatory")
#      rule.get("dependencies", [])
#        dep.get("depends_on_rule")
#        dep.get("dependency_type")
#      rule.get("source_reference") or rule.get("legacy_source_reference")
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent5ToAgent6Contract:
    """Verify Agent 5 output structure matches what Agent 6 reads.

    We test this by verifying Agent 5 code writes the correct keys that
    Agent 6 accesses, using import-level introspection of the code.
    """

    def test_agent5_writes_depends_on_rule(self):
        """Agent 5 must write 'depends_on_rule' (not 'source_rule_id') into rule deps."""
        agent5_code = (PROJECT_ROOT / "agents" / "agent_5_knowledge_graph_optimizer.py").read_text()
        assert '"depends_on_rule"' in agent5_code or "'depends_on_rule'" in agent5_code, (
            "Agent 5 must write 'depends_on_rule' key into rule dependencies "
            "(Agent 6 reads dep.get('depends_on_rule'))"
        )

    def test_agent5_writes_dependency_type(self):
        agent5_code = (PROJECT_ROOT / "agents" / "agent_5_knowledge_graph_optimizer.py").read_text()
        assert '"dependency_type"' in agent5_code or "'dependency_type'" in agent5_code

    def test_agent5_writes_deduplication_info(self):
        agent5_code = (PROJECT_ROOT / "agents" / "agent_5_knowledge_graph_optimizer.py").read_text()
        assert '"deduplication_info"' in agent5_code or "'deduplication_info'" in agent5_code

    def test_agent6_reads_depends_on_rule(self):
        """Agent 6 must read 'depends_on_rule' for dependency edges."""
        agent6_code = (PROJECT_ROOT / "agents" / "agent_6_visualization_and_report.py").read_text()
        assert "depends_on_rule" in agent6_code

    def test_agent6_reads_dependency_type(self):
        agent6_code = (PROJECT_ROOT / "agents" / "agent_6_visualization_and_report.py").read_text()
        assert "dependency_type" in agent6_code


# ─────────────────────────────────────────────────────────────────────────────
# 9. Agent 8 output → Agent 9 input contract
#
#    Agent 9 reads from match_results:
#      behavior_data.get("matches", [])
#      behavior_data.get("contradictions", [])
#      behavior_data.get("g1_unmatched", [])
#      behavior_data.get("g2_unmatched", [])
#      match.get("relationship")
#      match.get("confidence")
#      match.get("similarity_score")
#      match.get("reasoning")
#      contradiction.get("conflict_detail", {})
#      contradiction["g1_rule_id"]
#      contradiction["g2_rule_id"]
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent8ToAgent9Contract:
    """Verify Agent 8 output keys that Agent 9 reads."""

    def test_agent8_writes_match_keys(self):
        agent8_code = (PROJECT_ROOT / "agents" / "agent_8_semantic_rule_matcher.py").read_text()
        for key in ["g1_rule_id", "g2_rule_id", "relationship", "confidence",
                     "similarity_score", "reasoning", "key_comparison"]:
            assert f"'{key}'" in agent8_code or f'"{key}"' in agent8_code, (
                f"Agent 8 must write '{key}' to match results (Agent 9 reads it)"
            )

    def test_agent8_writes_contradiction_keys(self):
        agent8_code = (PROJECT_ROOT / "agents" / "agent_8_semantic_rule_matcher.py").read_text()
        for key in ["g1_rule_id", "g2_rule_id", "conflict_detail", "reasoning"]:
            assert f"'{key}'" in agent8_code or f'"{key}"' in agent8_code, (
                f"Agent 8 must write '{key}' to contradiction results (Agent 9 reads it)"
            )

    def test_agent9_reads_match_keys(self):
        agent9_code = (PROJECT_ROOT / "agents" / "agent_9_set_operations.py").read_text()
        for key in ["matches", "contradictions", "g1_unmatched", "g2_unmatched"]:
            assert key in agent9_code, (
                f"Agent 9 must read '{key}' from match results"
            )

    def test_agent9_reads_contradiction_detail(self):
        agent9_code = (PROJECT_ROOT / "agents" / "agent_9_set_operations.py").read_text()
        assert "conflict_detail" in agent9_code, (
            "Agent 9 must read 'conflict_detail' from contradictions"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Agent 9 output → Agent 10 input contract
#
#    Agent 10 reads:
#      data["metadata"].get("g1_name")
#      data["metadata"].get("g2_name")
#      rule.get("rule_id")
#      rule.get("rule_name")
#      rule.get("rule_type")
#      rule.get("provenance", {}).get("operation")
#      rule.get("provenance", {}).get("match_type")
#      rule.get("provenance", {}).get("sources", [])
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent9ToAgent10Contract:
    """Verify Agent 9 output keys that Agent 10 reads."""

    def test_agent9_writes_provenance(self):
        agent9_code = (PROJECT_ROOT / "agents" / "agent_9_set_operations.py").read_text()
        assert "provenance" in agent9_code, (
            "Agent 9 must write 'provenance' object to merged rules (Agent 10 reads it)"
        )

    def test_agent9_writes_provenance_fields(self):
        agent9_code = (PROJECT_ROOT / "agents" / "agent_9_set_operations.py").read_text()
        for key in ["operation", "match_type", "sources"]:
            assert key in agent9_code, (
                f"Agent 9 must include '{key}' in provenance (Agent 10 reads it)"
            )

    def test_agent10_reads_provenance(self):
        agent10_code = (PROJECT_ROOT / "agents" / "agent_10_set_visualization.py").read_text()
        assert "provenance" in agent10_code, (
            "Agent 10 must read 'provenance' from set operation results"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Agent 3 normalization shim
#
#    Agent 3 must handle BOTH:
#      - Nested format: {"entity_types": {...}, "relationships": {...}}
#      - Flat format:   {"rules": [...]}  (AML)
#    And normalize flat → nested so Agent 4 always gets entity_types.
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent3NormalizationContract:
    """Agent 3 must handle both flat and nested rule formats."""

    def test_agent3_handles_flat_rules(self):
        agent3_code = (PROJECT_ROOT / "agents" / "agent_3_rules_extractor.py").read_text()
        assert "'rules'" in agent3_code or '"rules"' in agent3_code, (
            "Agent 3 must check for flat 'rules' array format"
        )

    def test_agent3_handles_entity_types(self):
        agent3_code = (PROJECT_ROOT / "agents" / "agent_3_rules_extractor.py").read_text()
        assert "'entity_types'" in agent3_code or '"entity_types"' in agent3_code, (
            "Agent 3 must handle nested 'entity_types' format"
        )

    def test_agent3_normalizes_flat_to_nested(self):
        """Agent 3 must convert flat rules → entity_types/relationships."""
        agent3_code = (PROJECT_ROOT / "agents" / "agent_3_rules_extractor.py").read_text()
        # Must have normalization: if 'rules' in result and 'entity_types' not in result
        assert "entity_types" in agent3_code and "rules" in agent3_code, (
            "Agent 3 must normalize flat rules to entity_types structure"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 12. Agent 4 entity format flexibility
#
#    Agent 4 must handle both:
#      entity_data.get("entity_types") — dict keyed by entity name
#      entity_data.get("entities")     — list of entity objects
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent4EntityFormatContract:
    """Agent 4 must accept both dict and list entity formats."""

    def test_agent4_handles_entity_types_dict(self):
        agent4_code = (PROJECT_ROOT / "agents" / "agent_4_rules_with_entities_merger.py").read_text()
        assert "entity_types" in agent4_code

    def test_agent4_handles_entities_list(self):
        agent4_code = (PROJECT_ROOT / "agents" / "agent_4_rules_with_entities_merger.py").read_text()
        # Agent 4 must have fallback: entity_data.get('entity_types') or entity_data.get('entities', {})
        assert "entities" in agent4_code, (
            "Agent 4 must support 'entities' list format as fallback"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 13. entity_resolution / rule_resolution cross-domain parity
# ─────────────────────────────────────────────────────────────────────────────

class TestResolutionPromptContracts:
    """entity_resolution and rule_resolution must have consistent schemas."""

    ENTITY_RESOLUTION_FIELDS = [
        "entity_clusters",
        "resolution_summary",
    ]
    RULE_RESOLUTION_FIELDS = [
        "rule_clusters",
        "resolution_summary",
    ]

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", ENTITY_RESOLUTION_FIELDS)
    def test_entity_resolution_fields(self, domain, field):
        prompt = _load_prompt(domain, "entity_resolution")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/entity_resolution.txt must include "{field}"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", RULE_RESOLUTION_FIELDS)
    def test_rule_resolution_fields(self, domain, field):
        prompt = _load_prompt(domain, "rule_resolution")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/rule_resolution.txt must include "{field}"'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_rule_resolution_has_conflicts_detected(self, domain):
        prompt = _load_prompt(domain, "rule_resolution")
        assert _prompt_contains_field(prompt, "conflicts_detected"), (
            f'{domain}/rule_resolution.txt must include "conflicts_detected"'
        )


# ─────────────────────────────────────────────────────────────────────────────
# 14. rule_matcher (single-pair) consistency with batch
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleMatcherSingleVsBatch:
    """rule_matcher.txt and rule_matcher_batch.txt must share core output fields."""

    SHARED_FIELDS = ["relationship", "confidence", "similarity_score", "reasoning"]

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", SHARED_FIELDS)
    def test_single_matcher_has_field(self, domain, field):
        prompt = _load_prompt(domain, "rule_matcher")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/rule_matcher.txt must include "{field}" (shared with batch)'
        )

    @pytest.mark.parametrize("domain", DOMAINS)
    @pytest.mark.parametrize("field", SHARED_FIELDS)
    def test_batch_matcher_has_field(self, domain, field):
        prompt = _load_prompt(domain, "rule_matcher_batch")
        assert _prompt_contains_field(prompt, field), (
            f'{domain}/rule_matcher_batch.txt must include "{field}" (shared with single)'
        )


# ─────────────────────────────────────────────────────────────────────────────
# 15. validation_report does NOT need cross-domain parity
#     (domain-specific scoring is intentional)
#     but it must contain the core output structure.
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationReportContract:
    """validation_report.txt must produce a structured report."""

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_has_scoring_section(self, domain):
        prompt = _load_prompt(domain, "validation_report")
        has_score = _prompt_contains_any(prompt, "score", "rating", "assessment")
        assert has_score, (
            f"{domain}/validation_report.txt must include scoring criteria"
        )
