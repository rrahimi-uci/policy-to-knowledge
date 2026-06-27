"""
Tests for Regulatory Change Impact Analysis — impact_store, impact_service, and router.
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Setup path ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = tmp_path / "test_impact.db"
    monkeypatch.setattr(
        "ui.backend.services.impact_store._DB_PATH", db_path
    )
    # Reset thread-local connections
    import ui.backend.services.impact_store as store
    if hasattr(store._local, "conn"):
        store._local.conn = None
    store.init_tables()
    yield db_path


@pytest.fixture
def store():
    import ui.backend.services.impact_store as s
    return s


@pytest.fixture
def service():
    import ui.backend.services.impact_service as s
    return s


@pytest.fixture
def sample_graph_data():
    """Realistic graph data matching the actual schema."""
    return {
        "metadata": {
            "original_rule_count": 10,
            "optimized_rule_count": 8,
            "rules_removed_count": 2,
            "dependencies_added_count": 5,
        },
        "business_rules": [
            {
                "rule_id": "R001",
                "rule_name": "Loan-to-Value Ratio Must Not Exceed 80%",
                "rule_type": "eligibility",
                "confidence_score": 0.92,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
                "dependencies": [],
                "dependent_rules": [],
                "description": "The loan-to-value ratio for conventional mortgage must not exceed 80 percent without PMI.",
            },
            {
                "rule_id": "R002",
                "rule_name": "Borrower Must Complete Credit Counseling",
                "rule_type": "process",
                "confidence_score": 0.85,
                "risk_level": "high",
                "mandatory": True,
                "entity_type": "borrower",
                "dependencies": [],
                "dependent_rules": [],
                "description": "All borrowers shall complete approved credit counseling within 12 months of application.",
            },
            {
                "rule_id": "R003",
                "rule_name": "Property Appraisal Required",
                "rule_type": "compliance",
                "confidence_score": 0.95,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
                "dependencies": [],
                "dependent_rules": [],
                "description": "An independent appraisal must be obtained for all properties securing the mortgage loan.",
            },
            {
                "rule_id": "R004",
                "rule_name": "Income Documentation Checklist",
                "rule_type": "documentation",
                "confidence_score": 0.78,
                "risk_level": "medium",
                "mandatory": False,
                "entity_type": "borrower",
                "dependencies": [],
                "dependent_rules": [],
                "description": "Recommended documentation includes recent pay stubs, W-2 forms, and tax returns.",
            },
            {
                "rule_id": "R005",
                "rule_name": "Wire Transfer Must Have Dual Authorization",
                "rule_type": "prohibition",
                "confidence_score": 0.91,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "transaction",
                "dependencies": [],
                "dependent_rules": [],
                "description": "All wire transfers exceeding $10,000 must have dual authorization from senior staff.",
            },
        ],
        "entity_types": {},
        "dependency_details": {"dependencies": [], "conflicts": []},
    }


# ═══════════════════════════════════════════════════════════════════
# IMPACT STORE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestImpactStoreInit:
    def test_tables_created(self, store, temp_db):
        conn = sqlite3.connect(str(temp_db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "impact_analyses" in tables
        assert "impact_items" in tables

    def test_idempotent_init(self, store):
        # Should not raise on re-init
        store.init_tables()
        store.init_tables()


class TestImpactStoreAnalysisCRUD:
    def test_create_analysis(self, store):
        a = store.create_analysis("Fannie_Mae", "openai", "old.txt", "new.txt")
        assert a is not None
        assert a["graph_name"] == "Fannie_Mae"
        assert a["provider"] == "openai"
        assert a["old_doc_name"] == "old.txt"
        assert a["new_doc_name"] == "new.txt"
        assert a["status"] == "pending"
        assert a["summary"] is None
        assert a["stats"] is None

    def test_get_analysis(self, store):
        created = store.create_analysis("TestGraph", "openai", "a.txt", "b.txt")
        fetched = store.get_analysis(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["graph_name"] == "TestGraph"

    def test_get_nonexistent_analysis(self, store):
        assert store.get_analysis("nonexistent") is None

    def test_list_analyses(self, store):
        store.create_analysis("G1", "openai", "a.txt", "b.txt")
        store.create_analysis("G2", "openai", "c.txt", "d.txt")
        result = store.list_analyses()
        assert len(result) == 2

    def test_list_analyses_by_graph(self, store):
        store.create_analysis("G1", "openai", "a.txt", "b.txt")
        store.create_analysis("G2", "openai", "c.txt", "d.txt")
        store.create_analysis("G1", "openai", "e.txt", "f.txt")
        result = store.list_analyses(graph_name="G1")
        assert len(result) == 2

    def test_update_analysis(self, store):
        a = store.create_analysis("G1", "openai", "a.txt", "b.txt")
        store.update_analysis(a["id"], status="completed", summary={"headline": "test"})
        updated = store.get_analysis(a["id"])
        assert updated["status"] == "completed"
        assert updated["summary"]["headline"] == "test"

    def test_delete_analysis(self, store):
        a = store.create_analysis("G1", "openai", "a.txt", "b.txt")
        assert store.delete_analysis(a["id"]) is True
        assert store.get_analysis(a["id"]) is None

    def test_delete_nonexistent_analysis(self, store):
        assert store.delete_analysis("nope") is False


class TestImpactStoreItems:
    def test_add_and_get_items(self, store):
        a = store.create_analysis("G1", "openai", "a.txt", "b.txt")
        store.add_impact_item(
            a["id"], "added", "New provision about LTV", "breaking",
            [{"rule_id": "R001", "rule_name": "LTV Rule"}],
            "Added provision", "Update immediately",
        )
        store.add_impact_item(
            a["id"], "removed", "Old documentation requirement", "cosmetic",
            [], "Removed provision", "Verify",
        )
        items = store.get_impact_items(a["id"])
        assert len(items) == 2
        assert items[0]["change_type"] == "added"
        assert items[0]["severity"] == "breaking"
        assert len(items[0]["affected_rules"]) == 1
        assert items[1]["change_type"] == "removed"

    def test_items_cascade_on_delete(self, store):
        a = store.create_analysis("G1", "openai", "a.txt", "b.txt")
        store.add_impact_item(a["id"], "added", "prov", "cosmetic", [], "", "")
        store.delete_analysis(a["id"])
        items = store.get_impact_items(a["id"])
        assert len(items) == 0


# ═══════════════════════════════════════════════════════════════════
# IMPACT SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestProvisionSplitting:
    def test_splits_on_double_newline(self, service):
        text = "First provision about mortgages being important.\n\nSecond provision about interest rates calculation."
        result = service._split_provisions(text)
        assert len(result) == 2

    def test_splits_on_numbered_sections(self, service):
        text = "1. First section about rules\n2. Second section about compliance\n3. Third section about process steps"
        result = service._split_provisions(text)
        assert len(result) >= 2

    def test_ignores_short_fragments(self, service):
        text = "Short.\n\nThis is a sufficiently long provision about mortgage rules.\n\nToo short."
        result = service._split_provisions(text)
        # Only the long one should survive
        assert all(len(p) > 20 for p in result)


class TestDiffEngine:
    def test_detects_added_provisions(self, service):
        old = ["Existing provision about loan requirements and documentation."]
        new = [
            "Existing provision about loan requirements and documentation.",
            "New provision about maximum loan-to-value ratio calculation.",
        ]
        diff = service._compute_diff(old, new)
        assert len(diff["added"]) == 1
        assert "loan-to-value" in diff["added"][0].lower()
        assert len(diff["removed"]) == 0

    def test_detects_removed_provisions(self, service):
        old = [
            "First provision about mortgage processing.",
            "Second provision about interest rate caps.",
        ]
        new = ["First provision about mortgage processing."]
        diff = service._compute_diff(old, new)
        assert len(diff["removed"]) == 1
        assert "interest rate" in diff["removed"][0].lower()

    def test_detects_modifications(self, service):
        old = ["The maximum loan-to-value ratio is 80% for conventional loans."]
        new = ["The maximum loan-to-value ratio is 90% for conventional loans."]
        diff = service._compute_diff(old, new)
        assert len(diff["modified"]) == 1

    def test_handles_empty_old(self, service):
        diff = service._compute_diff([], ["New provision about compliance requirements and documentation."])
        assert len(diff["added"]) == 1
        assert len(diff["removed"]) == 0

    def test_handles_empty_new(self, service):
        diff = service._compute_diff(["Old provision about mortgage processing requirements."], [])
        assert len(diff["removed"]) == 1
        assert len(diff["added"]) == 0

    def test_handles_both_empty(self, service):
        diff = service._compute_diff([], [])
        assert diff == {"added": [], "removed": [], "modified": []}


class TestSeverityClassification:
    def test_breaking_keywords(self, service):
        assert service._classify_severity("This shall be prohibited at all times", 0) == "breaking"
        assert service._classify_severity("Borrower must complete this mandatory step", 0) == "breaking"

    def test_material_keywords(self, service):
        assert service._classify_severity("The recommended threshold is 80 percent", 0) == "material"
        assert service._classify_severity("Process for calculating eligibility", 0) == "material"

    def test_cosmetic_default(self, service):
        assert service._classify_severity("Updated formatting of the document header", 0) == "cosmetic"

    def test_high_affected_count_escalates(self, service):
        assert service._classify_severity("Minor text change in guidelines", 5) == "material"


class TestRuleMatching:
    def test_finds_matching_rules(self, service, sample_graph_data):
        rules = sample_graph_data["business_rules"]
        matches = service._find_affected_rules(
            "The loan-to-value ratio must not exceed 80 percent for conventional mortgage",
            rules,
        )
        assert len(matches) > 0
        rule_ids = [m["rule_id"] for m in matches]
        assert "R001" in rule_ids

    def test_returns_empty_for_unrelated(self, service, sample_graph_data):
        rules = sample_graph_data["business_rules"]
        matches = service._find_affected_rules(
            "Regulations governing international maritime shipping safety protocols",
            rules,
        )
        assert len(matches) == 0

    def test_match_score_ordering(self, service, sample_graph_data):
        rules = sample_graph_data["business_rules"]
        matches = service._find_affected_rules(
            "Independent property appraisal must be completed for mortgage loan compliance",
            rules,
        )
        if len(matches) >= 2:
            assert matches[0]["match_score"] >= matches[1]["match_score"]

    def test_limited_to_20(self, service):
        rules = [
            {"rule_id": f"R{i}", "rule_name": f"loan mortgage property rule {i}",
             "rule_type": "compliance", "risk_level": "high",
             "confidence_score": 0.8, "description": "loan mortgage property compliance"}
            for i in range(50)
        ]
        matches = service._find_affected_rules(
            "loan mortgage property compliance regulation",
            rules,
        )
        assert len(matches) <= 20


class TestFullAnalysis:
    def test_successful_analysis(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            a = store.create_analysis("TestGraph", "openai", "old.txt", "new.txt")
            old_text = (
                "Section 1: Loan-to-Value\n\n"
                "The maximum loan-to-value ratio is 80% for conventional loans.\n\n"
                "Section 2: Appraisal\n\n"
                "An independent appraisal is recommended for properties."
            )
            new_text = (
                "Section 1: Loan-to-Value\n\n"
                "The maximum loan-to-value ratio is 90% for conventional loans. "
                "This change shall be mandatory for all new applications.\n\n"
                "Section 2: Appraisal\n\n"
                "An independent appraisal must be obtained for all properties.\n\n"
                "Section 3: Wire Transfers\n\n"
                "All wire transfers exceeding $5,000 must have dual authorization."
            )
            result = service.run_analysis(a["id"], old_text, new_text, "TestGraph", "openai")

            assert result["status"] == "completed"
            assert result["stats"] is not None
            assert result["stats"]["total_changes"] > 0
            assert result["summary"] is not None
            assert "headline" in result["summary"]

            items = store.get_impact_items(a["id"])
            assert len(items) > 0

    def test_analysis_with_missing_graph(self, store, service):
        with patch.object(service.graph_service, "get_graph_data", return_value=None):
            a = store.create_analysis("Missing", "openai", "old.txt", "new.txt")
            result = service.run_analysis(a["id"], "old", "new", "Missing", "openai")
            assert result["status"] == "failed"
            assert "not found" in result["error"]

    def test_analysis_records_stats(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            a = store.create_analysis("G", "openai", "old.txt", "new.txt")
            result = service.run_analysis(
                a["id"],
                "Old provision about general lending guidelines and procedures.",
                "New provision about property appraisal must be mandatory for all mortgage loans.",
                "G", "openai",
            )
            assert result["status"] == "completed"
            stats = result["stats"]
            assert "total_changes" in stats
            assert "added_count" in stats
            assert "removed_count" in stats
            assert "modified_count" in stats
            assert "affected_rules_count" in stats
            assert "impact_percentage" in stats
            assert "severity_breaking" in stats
            assert "severity_material" in stats
            assert "severity_cosmetic" in stats


class TestExport:
    def test_export_json(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            a = store.create_analysis("G", "openai", "old.txt", "new.txt")
            service.run_analysis(
                a["id"],
                "Old provision about general requirements.",
                "New provision about mandatory compliance rules.",
                "G", "openai",
            )
            result = service.export_analysis(a["id"], "json")
            assert result is not None
            assert "items" in result
            assert result["graph_name"] == "G"

    def test_export_csv(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            a = store.create_analysis("G", "openai", "old.txt", "new.txt")
            service.run_analysis(
                a["id"],
                "Old provision about documentation requirements.",
                "New provision about updated documentation requirements.",
                "G", "openai",
            )
            csv_str = service.export_analysis(a["id"], "csv")
            assert csv_str is not None
            assert "change_type" in csv_str  # header row
            assert "severity" in csv_str

    def test_export_nonexistent(self, service):
        assert service.export_analysis("nope", "json") is None

    def test_export_unsupported_format(self, service):
        assert service.export_analysis("any", "xml") is None


class TestHeadlineGeneration:
    def test_breaking_headline(self, service):
        stats = {
            "total_changes": 5, "affected_rules_count": 10,
            "severity_breaking": 2, "impact_percentage": 25.0,
        }
        h = service._generate_headline(stats)
        assert "breaking" in h.lower()
        assert "10 rules" in h

    def test_no_breaking_headline(self, service):
        stats = {
            "total_changes": 3, "affected_rules_count": 5,
            "severity_breaking": 0, "impact_percentage": 12.5,
        }
        h = service._generate_headline(stats)
        assert "breaking" not in h.lower()
        assert "5 rules" in h

    def test_no_affected_headline(self, service):
        stats = {
            "total_changes": 2, "affected_rules_count": 0,
            "severity_breaking": 0, "impact_percentage": 0.0,
        }
        h = service._generate_headline(stats)
        assert "no rules" in h.lower()


class TestRecommendationGeneration:
    def test_breaking_recommendation(self, service):
        r = service._generate_recommendation(
            "added", "breaking",
            [{"rule_name": "LTV Rule"}, {"rule_name": "Appraisal Rule"}],
        )
        assert "URGENT" in r
        assert "LTV Rule" in r

    def test_material_recommendation(self, service):
        r = service._generate_recommendation(
            "modified", "material",
            [{"rule_name": "Income Rule"}],
        )
        assert "review" in r.lower()

    def test_no_affected_recommendation(self, service):
        r = service._generate_recommendation("removed", "cosmetic", [])
        assert "indirect" in r.lower()
