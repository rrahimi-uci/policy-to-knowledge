"""
Tests for Agent 4 entity name normalization.

Verifies that entity_or_relationship values from Agent 3 (mixed naming
conventions) are correctly mapped to Agent 2 canonical UPPER_SNAKE_CASE
names when a normalized match exists, and left unchanged otherwise.

Coverage
────────
  Unit:  normalization rules (spaces, hyphens, case, trailing whitespace)
  Unit:  no-match entities are preserved exactly
  Unit:  relationship rules are normalized alongside entity rules
  Unit:  entity_type field ('entity'/'relationship') survives normalization
  Unit:  enrich_rules() finds schema definitions after normalization
  Unit:  statistics (rules_by_entity) use canonical names
  Unit:  multiple rules under same entity all remapped together
  Edge:  already-canonical names are not double-remapped
  Edge:  empty rule sets produce no errors
  Edge:  AML-realistic naming data (spaces / UPPER_SNAKE_CASE mix)
  Code:  normalization block exists in agent_4 source
"""

import json
import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.agent_4_rules_with_entities_merger import KnowledgeEnricher


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_ENTITY_TYPES = {
    "FINANCIAL_INSTITUTION": {
        "name": "FINANCIAL_INSTITUTION",
        "type": "ORGANIZATION",
        "description": "A bank or financial services entity subject to BSA/AML.",
        "attributes": [{"name": "institution_type", "type": "string"}],
    },
    "CORRESPONDENT_BANKING_RELATIONSHIP": {
        "name": "CORRESPONDENT_BANKING_RELATIONSHIP",
        "type": "RELATIONSHIP_ENTITY",
        "description": "A banking service provided by one bank to another.",
        "attributes": [],
    },
    "SUSPICIOUS_ACTIVITY_REPORT": {
        "name": "SUSPICIOUS_ACTIVITY_REPORT",
        "type": "DOCUMENT",
        "description": "A FinCEN SAR filing.",
        "attributes": [],
    },
}

SCHEMA_RELATIONSHIPS = {
    "FILED_BY": {
        "description": "SAR filed by a financial institution.",
        "source_entity": "SUSPICIOUS_ACTIVITY_REPORT",
        "target_entity": "FINANCIAL_INSTITUTION",
    }
}


def _write_agent2(tmp_path: Path, entity_types=None, relationships=None) -> Path:
    p = tmp_path / "entity_types_and_relationships.json"
    p.write_text(json.dumps({
        "entity_types": entity_types if entity_types is not None else SCHEMA_ENTITY_TYPES,
        "relationships": relationships if relationships is not None else SCHEMA_RELATIONSHIPS,
    }))
    return p


def _write_agent3(tmp_path: Path, entity_types: dict, relationships: dict = None) -> Path:
    p = tmp_path / "compliance_rules_with_entities.json"
    p.write_text(json.dumps({
        "entity_types": entity_types,
        "relationships": relationships or {},
    }))
    return p


def _make_rule(rule_id: str, rule_name: str = "Test Rule") -> dict:
    return {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "rule_type": "compliance",
        "description": "Test description.",
        "conditions": [],
        "consequences": {},
        "confidence_score": 85,
        "mandatory": True,
    }


def _load_enricher(tmp_path: Path, agent3_entity_types: dict,
                   agent3_relationships: dict = None,
                   schema_entity_types=None) -> KnowledgeEnricher:
    """Build and load a KnowledgeEnricher from in-memory test data."""
    entity_file = _write_agent2(tmp_path, entity_types=schema_entity_types)
    rules_file = _write_agent3(tmp_path, agent3_entity_types, agent3_relationships)
    enricher = KnowledgeEnricher(entity_file, rules_file, tmp_path / "output")
    enricher.load_data()
    return enricher


# ─────────────────────────────────────────────────────────────────────────────
# 1. Core normalization behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestEntityNameNormalization:
    """entity_or_relationship is mapped to the canonical Agent-2 name."""

    def test_spaces_normalized_to_canonical(self, tmp_path):
        """'Financial Institution' (spaces) → 'FINANCIAL_INSTITUTION'."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001")]}
        })
        rule = enricher.business_rules[0]
        assert rule["entity_or_relationship"] == "FINANCIAL_INSTITUTION"

    def test_hyphens_normalized_to_canonical(self, tmp_path):
        """'Correspondent-Banking-Relationship' (hyphens) → canonical."""
        enricher = _load_enricher(tmp_path, {
            "Correspondent-Banking-Relationship": {"business_rules": [_make_rule("R001")]}
        })
        assert enricher.business_rules[0]["entity_or_relationship"] == "CORRESPONDENT_BANKING_RELATIONSHIP"

    def test_mixed_case_normalized(self, tmp_path):
        """Lower/mixed-case name normalizes to canonical."""
        enricher = _load_enricher(tmp_path, {
            "financial_institution": {"business_rules": [_make_rule("R001")]}
        })
        assert enricher.business_rules[0]["entity_or_relationship"] == "FINANCIAL_INSTITUTION"

    def test_trailing_whitespace_stripped(self, tmp_path):
        """Leading/trailing whitespace is stripped before comparison."""
        enricher = _load_enricher(tmp_path, {
            "  Financial Institution  ": {"business_rules": [_make_rule("R001")]}
        })
        assert enricher.business_rules[0]["entity_or_relationship"] == "FINANCIAL_INSTITUTION"

    def test_exact_canonical_match_unchanged(self, tmp_path):
        """An already-canonical name is not remapped (idempotent)."""
        enricher = _load_enricher(tmp_path, {
            "FINANCIAL_INSTITUTION": {"business_rules": [_make_rule("R001")]}
        })
        assert enricher.business_rules[0]["entity_or_relationship"] == "FINANCIAL_INSTITUTION"

    def test_no_match_preserved(self, tmp_path):
        """An entity with no schema match keeps its original Agent-3 name."""
        enricher = _load_enricher(tmp_path, {
            "AML_CFT_COMPLIANCE_OFFICER": {"business_rules": [_make_rule("R001")]}
        })
        assert enricher.business_rules[0]["entity_or_relationship"] == "AML_CFT_COMPLIANCE_OFFICER"

    def test_camelcase_without_match_preserved(self, tmp_path):
        """CamelCase that doesn't normalize to a schema entity is unchanged."""
        enricher = _load_enricher(tmp_path, {
            "FinancialInstitution": {"business_rules": [_make_rule("R001")]}
        })
        # 'FINANCIALINSTITUTION' ≠ 'FINANCIAL_INSTITUTION' — no underscore inserted
        assert enricher.business_rules[0]["entity_or_relationship"] == "FinancialInstitution"

    def test_multiple_rules_under_same_entity_all_remapped(self, tmp_path):
        """All rules under the same non-canonical entity name are remapped."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {
                "business_rules": [_make_rule("R001"), _make_rule("R002"), _make_rule("R003")]
            }
        })
        for rule in enricher.business_rules:
            assert rule["entity_or_relationship"] == "FINANCIAL_INSTITUTION"

    def test_mixed_entities_normalized_selectively(self, tmp_path):
        """Only matching entities are remapped; non-matching ones stay."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001")]},
            "AML_CFT_COMPLIANCE_OFFICER": {"business_rules": [_make_rule("R002")]},
            "Suspicious Activity Report": {"business_rules": [_make_rule("R003")]},
        })
        by_id = {r["rule_id"]: r["entity_or_relationship"] for r in enricher.business_rules}
        assert by_id["R001"] == "FINANCIAL_INSTITUTION"
        assert by_id["R002"] == "AML_CFT_COMPLIANCE_OFFICER"
        assert by_id["R003"] == "SUSPICIOUS_ACTIVITY_REPORT"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Relationship rules are normalized too
# ─────────────────────────────────────────────────────────────────────────────

class TestRelationshipNormalization:
    """entity_or_relationship normalization applies to relationship rules."""

    def test_relationship_name_normalized(self, tmp_path):
        """'filed by' → 'FILED_BY' when schema has FILED_BY."""
        enricher = _load_enricher(
            tmp_path,
            agent3_entity_types={},
            agent3_relationships={"filed by": {"business_rules": [_make_rule("R001")]}},
        )
        rule = enricher.business_rules[0]
        assert rule["entity_or_relationship"] == "FILED_BY"
        assert rule["entity_type"] == "relationship"

    def test_unmatched_relationship_preserved(self, tmp_path):
        """An unrecognized relationship name is kept as-is."""
        enricher = _load_enricher(
            tmp_path,
            agent3_entity_types={},
            agent3_relationships={"APPROVES": {"business_rules": [_make_rule("R001")]}},
        )
        assert enricher.business_rules[0]["entity_or_relationship"] == "APPROVES"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Metadata fields survive normalization
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleMetadataIntact:
    """Normalization must not alter other rule fields."""

    def test_entity_type_field_preserved(self, tmp_path):
        """entity_type ('entity' / 'relationship') is untouched."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001")]}
        })
        assert enricher.business_rules[0]["entity_type"] == "entity"

    def test_rule_payload_fields_intact(self, tmp_path):
        """rule_id, rule_type, description, confidence_score survive normalization."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {
                "business_rules": [_make_rule("R001", "Specific AML Rule")]
            }
        })
        rule = enricher.business_rules[0]
        assert rule["rule_id"] == "R001"
        assert rule["rule_name"] == "Specific AML Rule"
        assert rule["rule_type"] == "compliance"
        assert rule["confidence_score"] == 85


# ─────────────────────────────────────────────────────────────────────────────
# 4. Downstream: enrich_rules() and create_merged_output()
# ─────────────────────────────────────────────────────────────────────────────

class TestDownstreamEffects:
    """Normalization enables schema enrichment and correct statistics."""

    def test_enrich_rules_finds_definition_after_normalization(self, tmp_path):
        """After normalization, enrich_rules() attaches the schema entity_definition."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001")]}
        })
        enriched = enricher.enrich_rules()
        rule = enriched[0]
        assert "entity_definition" in rule
        assert rule["entity_definition"]["description"] == SCHEMA_ENTITY_TYPES["FINANCIAL_INSTITUTION"]["description"]

    def test_enrich_rules_no_definition_for_unmatched(self, tmp_path):
        """Rules whose entity still has no schema match get no entity_definition."""
        enricher = _load_enricher(tmp_path, {
            "AML_CFT_COMPLIANCE_OFFICER": {"business_rules": [_make_rule("R001")]}
        })
        enriched = enricher.enrich_rules()
        assert "entity_definition" not in enriched[0]

    def test_merged_output_rules_by_entity_uses_canonical_name(self, tmp_path):
        """statistics.rules_by_entity is keyed by the canonical name after normalization."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {
                "business_rules": [_make_rule("R001"), _make_rule("R002")]
            }
        })
        enriched = enricher.enrich_rules()
        merged = enricher.create_merged_output(enriched)
        stats = merged["statistics"]["rules_by_entity"]
        assert "FINANCIAL_INSTITUTION" in stats
        assert stats["FINANCIAL_INSTITUTION"] == 2
        assert "Financial Institution" not in stats

    def test_merged_output_total_rules_count_unchanged(self, tmp_path):
        """Normalization never drops or duplicates rules."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001"), _make_rule("R002")]},
            "AML_CFT_OFFICER": {"business_rules": [_make_rule("R003")]},
        })
        enriched = enricher.enrich_rules()
        merged = enricher.create_merged_output(enriched)
        assert merged["statistics"]["total_rules"] == 3

    def test_merged_output_entity_types_preserved(self, tmp_path):
        """entity_types in merged output still contains all Agent-2 schema entities."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001")]}
        })
        enriched = enricher.enrich_rules()
        merged = enricher.create_merged_output(enriched)
        assert set(merged["entity_types"].keys()) == set(SCHEMA_ENTITY_TYPES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# 5. Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Normalization is safe in degenerate inputs."""

    def test_empty_rules_no_error(self, tmp_path):
        """Agent 3 with no rules produces an empty business_rules list."""
        enricher = _load_enricher(tmp_path, {})
        assert enricher.business_rules == []

    def test_entity_with_empty_business_rules(self, tmp_path):
        """An entity_type with no business_rules produces no output rules."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": []}
        })
        assert enricher.business_rules == []

    def test_multiple_spaces_collapsed(self, tmp_path):
        """Multiple consecutive spaces are collapsed to a single underscore."""
        enricher = _load_enricher(tmp_path, {
            "Financial  Institution": {"business_rules": [_make_rule("R001")]}
        })
        # "Financial  Institution" → upper → sub [\s\-]+ → "FINANCIAL_INSTITUTION"
        assert enricher.business_rules[0]["entity_or_relationship"] == "FINANCIAL_INSTITUTION"

    def test_no_duplicate_remapping(self, tmp_path):
        """Two different Agent-3 names that normalize to the same canonical name
        are both remapped — no collision, no loss of rules."""
        enricher = _load_enricher(tmp_path, {
            "Financial Institution": {"business_rules": [_make_rule("R001")]},
            "financial institution": {"business_rules": [_make_rule("R002")]},
        })
        for rule in enricher.business_rules:
            assert rule["entity_or_relationship"] == "FINANCIAL_INSTITUTION"
        assert len(enricher.business_rules) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 6. AML-realistic data
# ─────────────────────────────────────────────────────────────────────────────

class TestAmlRealisticData:
    """Validates normalization with the naming patterns seen in real AML output."""

    AML_SCHEMA = {
        "FINANCIAL_INSTITUTION": {
            "name": "FINANCIAL_INSTITUTION", "type": "ORGANIZATION",
            "description": "BSA/AML-covered financial entity.", "attributes": [],
        },
        "CORRESPONDENT_BANKING_RELATIONSHIP": {
            "name": "CORRESPONDENT_BANKING_RELATIONSHIP", "type": "RELATIONSHIP_ENTITY",
            "description": "Inter-bank service relationship.", "attributes": [],
        },
        "SUSPICIOUS_ACTIVITY_REPORT": {
            "name": "SUSPICIOUS_ACTIVITY_REPORT", "type": "DOCUMENT",
            "description": "FinCEN SAR filing.", "attributes": [],
        },
        "CUSTOMER_LEGAL_PERSON": {
            "name": "CUSTOMER_LEGAL_PERSON", "type": "ENTITY",
            "description": "A legal person customer.", "attributes": [],
        },
    }

    # Agent-3 entity names as seen in practice (from the real AML pipeline run)
    AML_AGENT3_ENTITIES = {
        # These two normalize to schema keys:
        "Financial Institution": {"business_rules": [_make_rule("R001"), _make_rule("R002")]},
        "Correspondent Banking Relationship": {"business_rules": [_make_rule("R003")]},
        # These have no schema match — preserved as-is:
        "AML_CFT_COMPLIANCE_OFFICER": {"business_rules": [_make_rule("R004")]},
        "BeneficialOwner": {"business_rules": [_make_rule("R005")]},
        "Covered Financial Institution": {"business_rules": [_make_rule("R006")]},
        "CUSTOMER_LEGAL_PERSON": {"business_rules": [_make_rule("R007")]},  # exact match
    }

    def test_normalized_count(self, tmp_path):
        """Exactly 3 rules should be remapped to canonical names."""
        enricher = _load_enricher(
            tmp_path, self.AML_AGENT3_ENTITIES,
            schema_entity_types=self.AML_SCHEMA
        )
        remapped = [
            r for r in enricher.business_rules
            if r["entity_or_relationship"] in self.AML_SCHEMA
               and r["entity_or_relationship"] != r.get("_original_name", r["entity_or_relationship"])
        ]
        # Check by canonical presence: R001, R002 → FINANCIAL_INSTITUTION; R003 → CORRESPONDENT_BANKING_RELATIONSHIP
        by_id = {r["rule_id"]: r["entity_or_relationship"] for r in enricher.business_rules}
        assert by_id["R001"] == "FINANCIAL_INSTITUTION"
        assert by_id["R002"] == "FINANCIAL_INSTITUTION"
        assert by_id["R003"] == "CORRESPONDENT_BANKING_RELATIONSHIP"

    def test_unmatched_preserved(self, tmp_path):
        """Agent-3 entities with no schema match keep their original names."""
        enricher = _load_enricher(
            tmp_path, self.AML_AGENT3_ENTITIES,
            schema_entity_types=self.AML_SCHEMA
        )
        by_id = {r["rule_id"]: r["entity_or_relationship"] for r in enricher.business_rules}
        assert by_id["R004"] == "AML_CFT_COMPLIANCE_OFFICER"
        assert by_id["R005"] == "BeneficialOwner"
        assert by_id["R006"] == "Covered Financial Institution"

    def test_exact_canonical_already_in_schema_unchanged(self, tmp_path):
        """CUSTOMER_LEGAL_PERSON is already canonical — unchanged."""
        enricher = _load_enricher(
            tmp_path, self.AML_AGENT3_ENTITIES,
            schema_entity_types=self.AML_SCHEMA
        )
        by_id = {r["rule_id"]: r["entity_or_relationship"] for r in enricher.business_rules}
        assert by_id["R007"] == "CUSTOMER_LEGAL_PERSON"

    def test_total_rule_count_preserved(self, tmp_path):
        """Normalization never loses or duplicates rules."""
        enricher = _load_enricher(
            tmp_path, self.AML_AGENT3_ENTITIES,
            schema_entity_types=self.AML_SCHEMA
        )
        assert len(enricher.business_rules) == 7


# ─────────────────────────────────────────────────────────────────────────────
# 7. Source-code inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent4SourceContainsNormalization:
    """The normalization block must be present in agent_4 source."""

    AGENT4 = (PROJECT_ROOT / "agents" / "agent_4_rules_with_entities_merger.py").read_text()

    def test_canonical_map_built(self):
        assert "canonical_map" in self.AGENT4, (
            "Agent 4 must build a canonical_map from entity_types keys"
        )

    def test_normalization_regex_present(self):
        assert r"[\s\-]+" in self.AGENT4 or r"[\s\\-]+" in self.AGENT4, (
            "Agent 4 must normalize spaces/hyphens via regex sub"
        )

    def test_remapped_counter_logged(self):
        assert "remapped" in self.AGENT4, (
            "Agent 4 must track and log the remapped count"
        )

    def test_canonical_lookup_applied(self):
        assert "canonical_map.get" in self.AGENT4, (
            "Agent 4 must look up canonical names via canonical_map.get()"
        )

    def test_only_remap_when_name_changes(self):
        """Guard: 'canonical != orig' prevents no-op remaps and double-remapping."""
        assert "canonical != orig" in self.AGENT4, (
            "Agent 4 must guard remapping with 'canonical != orig' so already-canonical "
            "names are never counted as remapped"
        )
