"""
Tests for Obligation Register & Gap Analysis — obligation_store, obligation_service, and router.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Setup path ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = tmp_path / "test_obligations.db"
    monkeypatch.setattr(
        "ui.backend.services.obligation_store._DB_PATH", db_path
    )
    import ui.backend.services.obligation_store as store
    if hasattr(store._local, "conn"):
        store._local.conn = None
    store.init_tables()
    yield db_path


@pytest.fixture
def store():
    import ui.backend.services.obligation_store as s
    return s


@pytest.fixture
def service():
    import ui.backend.services.obligation_service as s
    return s


@pytest.fixture
def sample_graph_data():
    return {
        "metadata": {
            "original_rule_count": 5,
            "optimized_rule_count": 5,
        },
        "business_rules": [
            {
                "rule_id": "R001",
                "rule_name": "LTV Ratio Must Not Exceed 80%",
                "rule_type": "eligibility",
                "confidence_score": 0.92,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
            },
            {
                "rule_id": "R002",
                "rule_name": "Complete Credit Counseling",
                "rule_type": "process",
                "confidence_score": 0.85,
                "risk_level": "high",
                "mandatory": True,
                "entity_type": "borrower",
            },
            {
                "rule_id": "R003",
                "rule_name": "Property Appraisal Required",
                "rule_type": "compliance",
                "confidence_score": 0.95,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
            },
            {
                "rule_id": "R004",
                "rule_name": "Income Documentation Checklist",
                "rule_type": "documentation",
                "confidence_score": 0.78,
                "risk_level": "medium",
                "mandatory": False,
                "entity_type": "borrower",
            },
            {
                "rule_id": "R005",
                "rule_name": "Wire Transfer Dual Authorization",
                "rule_type": "prohibition",
                "confidence_score": 0.91,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "transaction",
            },
        ],
        "entity_types": {},
    }


# ═══════════════════════════════════════════════════════════════════
# OBLIGATION STORE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestObligationStoreInit:
    def test_tables_created(self, store, temp_db):
        conn = sqlite3.connect(str(temp_db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "obligations" in tables
        assert "obligation_controls" in tables

    def test_idempotent_init(self, store):
        store.init_tables()
        store.init_tables()


class TestObligationCRUD:
    def test_upsert_creates_new(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Test Rule", "eligibility", "high")
        assert ob is not None
        assert ob["rule_id"] == "R001"
        assert ob["status"] == "unmapped"
        assert ob["graph_name"] == "G1"
        assert ob["controls"] == []

    def test_upsert_updates_existing(self, store):
        store.upsert_obligation("G1", "openai", "R001", "Test Rule", "eligibility", "high")
        store.upsert_obligation("G1", "openai", "R001", "Updated Rule", "process", "critical", "mapped", "Updated notes")
        ob = store.get_obligation("G1", "openai", "R001")
        assert ob["rule_name"] == "Updated Rule"
        # ON CONFLICT preserves status/notes (re-seed safe) — use update_obligation_status instead
        assert ob["status"] == "unmapped"
        assert ob["notes"] == ""

    def test_get_nonexistent(self, store):
        assert store.get_obligation("G1", "openai", "NOPE") is None

    def test_list_obligations(self, store):
        store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        store.upsert_obligation("G1", "openai", "R002", "Rule 2")
        store.upsert_obligation("G2", "openai", "R003", "Rule 3")
        result = store.list_obligations("G1", "openai")
        assert len(result) == 2

    def test_update_status(self, store):
        store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        result = store.update_obligation_status("G1", "openai", "R001", "mapped", "Done")
        assert result is not None
        assert result["status"] == "mapped"
        assert result["notes"] == "Done"

    def test_update_status_nonexistent(self, store):
        assert store.update_obligation_status("G1", "openai", "NOPE", "mapped") is None

    def test_delete_obligations(self, store):
        store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        store.upsert_obligation("G1", "openai", "R002", "Rule 2")
        count = store.delete_obligations("G1", "openai")
        assert count == 2
        assert store.list_obligations("G1", "openai") == []


class TestControlCRUD:
    def test_add_control(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        ctrl = store.add_control(ob["id"], "SOC2 Audit", "audit", "Annual SOC2 audit", "", "John")
        assert ctrl["control_name"] == "SOC2 Audit"
        assert ctrl["control_type"] == "audit"
        assert ctrl["owner"] == "John"

    def test_get_controls(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        store.add_control(ob["id"], "Control A", "policy")
        store.add_control(ob["id"], "Control B", "procedure")
        controls = store.get_controls(ob["id"])
        assert len(controls) == 2

    def test_controls_in_obligation(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        store.add_control(ob["id"], "Control A", "policy")
        refreshed = store.get_obligation("G1", "openai", "R001")
        assert len(refreshed["controls"]) == 1

    def test_delete_control(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        ctrl = store.add_control(ob["id"], "Control A", "policy")
        assert store.delete_control(ctrl["id"]) is True
        assert store.get_controls(ob["id"]) == []

    def test_delete_nonexistent_control(self, store):
        assert store.delete_control(99999) is False

    def test_controls_cascade_on_obligation_delete(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Rule 1")
        store.add_control(ob["id"], "Control A", "policy")
        store.delete_obligations("G1", "openai")
        assert store.get_controls(ob["id"]) == []


class TestHeatmap:
    def test_empty_heatmap(self, store):
        h = store.get_heatmap("G1", "openai")
        assert h["total_obligations"] == 0
        assert h["compliance_score"] == 0.0
        assert h["by_status"] == {}

    def test_heatmap_with_data(self, store):
        store.upsert_obligation("G1", "openai", "R001", "A", "eligibility", "critical", "mapped")
        store.upsert_obligation("G1", "openai", "R002", "B", "process", "high", "unmapped")
        store.upsert_obligation("G1", "openai", "R003", "C", "compliance", "critical", "partially-mapped")
        store.upsert_obligation("G1", "openai", "R004", "D", "documentation", "medium", "exempted")

        h = store.get_heatmap("G1", "openai")
        assert h["total_obligations"] == 4
        assert h["by_status"]["mapped"] == 1
        assert h["by_status"]["unmapped"] == 1
        assert h["by_status"]["partially-mapped"] == 1
        assert h["by_status"]["exempted"] == 1
        # Score: (1 mapped + 0.5 * 1 partial) / 4 * 100 = 37.5
        assert h["compliance_score"] == 37.5

    def test_heatmap_by_risk(self, store):
        store.upsert_obligation("G1", "openai", "R001", "A", "e", "critical", "mapped")
        store.upsert_obligation("G1", "openai", "R002", "B", "p", "critical", "unmapped")
        store.upsert_obligation("G1", "openai", "R003", "C", "c", "high", "mapped")

        h = store.get_heatmap("G1", "openai")
        assert "critical" in h["by_risk_level"]
        assert h["by_risk_level"]["critical"]["mapped"] == 1
        assert h["by_risk_level"]["critical"]["unmapped"] == 1
        assert "high" in h["by_risk_level"]
        assert h["by_risk_level"]["high"]["mapped"] == 1

    def test_heatmap_by_rule_type(self, store):
        store.upsert_obligation("G1", "openai", "R001", "A", "eligibility", "c", "mapped")
        store.upsert_obligation("G1", "openai", "R002", "B", "eligibility", "h", "unmapped")
        store.upsert_obligation("G1", "openai", "R003", "C", "process", "c", "mapped")

        h = store.get_heatmap("G1", "openai")
        assert "eligibility" in h["by_rule_type"]
        assert h["by_rule_type"]["eligibility"]["mapped"] == 1
        assert h["by_rule_type"]["eligibility"]["unmapped"] == 1

    def test_full_compliance_score(self, store):
        store.upsert_obligation("G1", "openai", "R001", "A", "e", "c", "mapped")
        store.upsert_obligation("G1", "openai", "R002", "B", "p", "h", "mapped")
        h = store.get_heatmap("G1", "openai")
        assert h["compliance_score"] == 100.0


# ═══════════════════════════════════════════════════════════════════
# OBLIGATION SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSeedObligations:
    def test_seed_from_graph(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            result = service.seed_obligations("TestGraph", "openai")
            assert result["created"] == 5
            assert result["existing"] == 0
            assert result["total_rules"] == 5
            # Verify in DB
            obs = store.list_obligations("TestGraph", "openai")
            assert len(obs) == 5
            assert all(ob["status"] == "unmapped" for ob in obs)

    def test_seed_idempotent(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            service.seed_obligations("TestGraph", "openai")
            result = service.seed_obligations("TestGraph", "openai")
            assert result["created"] == 0
            assert result["existing"] == 5

    def test_seed_missing_graph(self, service):
        with patch.object(service.graph_service, "get_graph_data", return_value=None):
            result = service.seed_obligations("Missing", "openai")
            assert "error" in result

    def test_seed_preserves_existing_status(self, store, service, sample_graph_data):
        with patch.object(service.graph_service, "get_graph_data", return_value=sample_graph_data):
            service.seed_obligations("G", "openai")
            store.update_obligation_status("G", "openai", "R001", "mapped", "Done")
            service.seed_obligations("G", "openai")
            ob = store.get_obligation("G", "openai", "R001")
            assert ob["status"] == "mapped"


class TestSuggestControls:
    def test_eligibility_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R001", "LTV Rule", "eligibility", "critical")
        suggestions = service.suggest_controls("G", "openai", "R001")
        assert len(suggestions) > 0
        names = [s["control_name"] for s in suggestions]
        assert "Eligibility Verification Checklist" in names

    def test_critical_risk_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R001", "Test Rule", "compliance", "critical")
        suggestions = service.suggest_controls("G", "openai", "R001")
        names = [s["control_name"] for s in suggestions]
        assert "Executive Review & Sign-off" in names
        assert "Independent Audit Verification" in names

    def test_wire_transfer_keyword(self, store, service):
        store.upsert_obligation("G", "openai", "R005", "Wire Transfer Auth", "prohibition", "critical")
        suggestions = service.suggest_controls("G", "openai", "R005")
        names = [s["control_name"] for s in suggestions]
        assert "Wire Transfer Authorization" in names

    def test_appraisal_keyword(self, store, service):
        store.upsert_obligation("G", "openai", "R003", "Property Appraisal Required", "compliance", "critical")
        suggestions = service.suggest_controls("G", "openai", "R003")
        names = [s["control_name"] for s in suggestions]
        assert "Appraisal Independence Policy" in names

    def test_aml_keyword(self, store, service):
        store.upsert_obligation("G", "openai", "R010", "AML Suspicious Activity", "compliance", "high")
        suggestions = service.suggest_controls("G", "openai", "R010")
        names = [s["control_name"] for s in suggestions]
        assert "Transaction Monitoring System" in names

    def test_no_duplicates(self, store, service):
        store.upsert_obligation("G", "openai", "R001", "Test Rule", "compliance", "critical")
        suggestions = service.suggest_controls("G", "openai", "R001")
        names = [s["control_name"] for s in suggestions]
        assert len(names) == len(set(names))

    def test_nonexistent_obligation(self, service):
        suggestions = service.suggest_controls("G", "openai", "NOPE")
        assert suggestions == []

    def test_documentation_type_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R004", "Income Docs", "documentation", "medium")
        suggestions = service.suggest_controls("G", "openai", "R004")
        names = [s["control_name"] for s in suggestions]
        assert "Document Retention Policy" in names

    def test_process_type_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R002", "Processing Steps", "process", "high")
        suggestions = service.suggest_controls("G", "openai", "R002")
        names = [s["control_name"] for s in suggestions]
        assert "Standard Operating Procedure" in names

    def test_calculation_type_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R010", "Interest Calc", "calculation", "high")
        suggestions = service.suggest_controls("G", "openai", "R010")
        names = [s["control_name"] for s in suggestions]
        assert "Calculation Validation Engine" in names

    def test_prohibition_type_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R015", "No Insider Trading", "prohibition", "critical")
        suggestions = service.suggest_controls("G", "openai", "R015")
        names = [s["control_name"] for s in suggestions]
        assert "Prohibited Activity Monitoring" in names

    def test_validation_type_suggestions(self, store, service):
        store.upsert_obligation("G", "openai", "R020", "Data Validation", "validation", "medium")
        suggestions = service.suggest_controls("G", "openai", "R020")
        names = [s["control_name"] for s in suggestions]
        assert "Data Validation Rules" in names


class TestExportObligations:
    def test_export_csv(self, store, service):
        store.upsert_obligation("G", "openai", "R001", "LTV Rule", "eligibility", "critical", "mapped")
        ob = store.get_obligation("G", "openai", "R001")
        store.add_control(ob["id"], "SOC2 Audit", "audit", "Annual audit")
        csv_str = service.export_obligations("G", "openai", "csv")
        assert "Obligation ID" in csv_str
        assert "LTV Rule" in csv_str
        assert "SOC2 Audit" in csv_str

    def test_export_csv_no_controls(self, store, service):
        store.upsert_obligation("G", "openai", "R001", "LTV Rule", "eligibility", "critical", "unmapped")
        csv_str = service.export_obligations("G", "openai", "csv")
        assert "LTV Rule" in csv_str

    def test_export_json(self, store, service):
        store.upsert_obligation("G", "openai", "R001", "LTV Rule", "eligibility", "critical", "mapped")
        result = service.export_obligations("G", "openai", "json")
        assert result["graph_name"] == "G"
        assert "heatmap" in result
        assert "obligations" in result
        assert len(result["obligations"]) == 1


class TestValidConstants:
    def test_valid_statuses(self, service):
        assert "mapped" in service.VALID_STATUSES
        assert "unmapped" in service.VALID_STATUSES
        assert "partially-mapped" in service.VALID_STATUSES
        assert "exempted" in service.VALID_STATUSES

    def test_valid_control_types(self, service):
        assert "policy" in service.VALID_CONTROL_TYPES
        assert "procedure" in service.VALID_CONTROL_TYPES
        assert "technical-control" in service.VALID_CONTROL_TYPES
        assert "manual-control" in service.VALID_CONTROL_TYPES
        assert "audit" in service.VALID_CONTROL_TYPES
        assert "training" in service.VALID_CONTROL_TYPES


# ═══════════════════════════════════════════════════════════════════
# ENRICHED OBLIGATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestEnrichedSchema:
    def test_upsert_with_enriched_fields(self, store):
        ob = store.upsert_obligation(
            "G1", "openai", "R001", "LTV Rule", "eligibility", "critical",
            description="Loan-to-value must not exceed 80%",
            jurisdiction="agency:FNMA",
            mandatory=1,
            effective_date="2023-01-01",
            conditions=json.dumps(["LTV > 80%", "Property is residential"]),
            consequences=json.dumps(["Loan rejection"]),
            exceptions=json.dumps(["VA loans exempt"]),
            applicability_scope=json.dumps({"loan_types": ["conventional"], "occupancy_types": ["primary"]}),
            audit_frequency="quarterly",
            enforcement_action="Loan repurchase demand",
            source_reference=json.dumps({"section_id": "B3-3.1", "source_text": "LTV must not exceed 80 percent"}),
        )
        assert ob["description"] == "Loan-to-value must not exceed 80%"
        assert ob["jurisdiction"] == "agency:FNMA"
        assert ob["mandatory"] == 1
        assert ob["effective_date"] == "2023-01-01"
        assert ob["audit_frequency"] == "quarterly"
        assert ob["enforcement_action"] == "Loan repurchase demand"

    def test_enriched_fields_in_list(self, store):
        store.upsert_obligation(
            "G1", "openai", "R001", "Rule A", "eligibility", "high",
            description="Desc A",
            jurisdiction="agency:FHLMC",
        )
        obs = store.list_obligations("G1", "openai")
        assert len(obs) == 1
        assert obs[0]["description"] == "Desc A"
        assert obs[0]["jurisdiction"] == "agency:FHLMC"

    def test_upsert_preserves_status_updates_enriched(self, store):
        store.upsert_obligation("G1", "openai", "R001", "Rule A", "eligibility", "high")
        store.update_obligation_status("G1", "openai", "R001", "mapped", "test notes")
        # Re-upsert with enriched data (simulating re-seed)
        store.upsert_obligation(
            "G1", "openai", "R001", "Rule A Updated", "eligibility", "critical",
            description="New description",
            jurisdiction="agency:FNMA",
        )
        ob = store.get_obligation("G1", "openai", "R001")
        # Note: upsert ON CONFLICT doesn't update status/notes, so they are preserved
        assert ob["description"] == "New description"
        assert ob["jurisdiction"] == "agency:FNMA"
        assert ob["rule_name"] == "Rule A Updated"

    def test_default_enriched_fields_are_empty(self, store):
        ob = store.upsert_obligation("G1", "openai", "R001", "Rule A")
        assert ob["description"] == ""
        assert ob["jurisdiction"] == ""
        assert ob["mandatory"] == 1  # default
        assert ob["effective_date"] == ""
        assert ob["source_reference"] == ""
        assert ob["conditions"] == ""
        assert ob["consequences"] == ""
        assert ob["exceptions"] == ""
        assert ob["applicability_scope"] == ""
        assert ob["audit_frequency"] == ""
        assert ob["enforcement_action"] == ""

    def test_migration_adds_columns(self, store, temp_db):
        """Re-running init_tables should not fail (migration is idempotent)."""
        store.init_tables()
        store.init_tables()
        ob = store.upsert_obligation(
            "G1", "openai", "R001", "Rule A",
            description="Test",
        )
        assert ob["description"] == "Test"


class TestEnrichedSeeding:
    def test_seed_populates_enriched_fields(self, store, service):
        graph_data = {
            "business_rules": [
                {
                    "rule_id": "R001",
                    "rule_name": "LTV Ratio Must Not Exceed 80%",
                    "rule_type": "eligibility",
                    "risk_level": "critical",
                    "description": "The combined LTV must not exceed 80 percent.",
                    "conditions": ["LTV > 80%"],
                    "consequences": ["Loan ineligible for delivery"],
                    "exceptions": ["VA loans"],
                    "source_reference": {
                        "chunk_path": "chunks/B3-3.1.txt",
                        "section_id": "B3-3.1",
                        "source_text": "The combined LTV must not exceed 80 percent.",
                    },
                    "jurisdiction": "agency:FNMA",
                    "mandatory": True,
                    "effective_date": "2023-06-01",
                    "applicability_scope": {
                        "loan_types": ["conventional", "conforming"],
                        "occupancy_types": ["primary_residence"],
                    },
                    "audit_frequency": "quarterly",
                    "enforcement_action": "Loan repurchase demand",
                },
            ],
            "entity_types": {},
        }
        with patch.object(service.graph_service, "get_graph_data", return_value=graph_data):
            result = service.seed_obligations("TestGraph", "openai")
            assert result["created"] == 1

        ob = store.get_obligation("TestGraph", "openai", "R001")
        assert ob["description"] == "The combined LTV must not exceed 80 percent."
        assert ob["jurisdiction"] == "agency:FNMA"
        assert ob["mandatory"] == 1
        assert ob["effective_date"] == "2023-06-01"
        assert ob["audit_frequency"] == "quarterly"
        assert ob["enforcement_action"] == "Loan repurchase demand"

        # JSON fields stored correctly
        src_ref = json.loads(ob["source_reference"])
        assert src_ref["section_id"] == "B3-3.1"
        conditions = json.loads(ob["conditions"])
        assert "LTV > 80%" in conditions
        scope = json.loads(ob["applicability_scope"])
        assert "conventional" in scope["loan_types"]

    def test_reseed_updates_enriched_preserves_status(self, store, service):
        graph_data_v1 = {
            "business_rules": [
                {
                    "rule_id": "R001",
                    "rule_name": "LTV Rule",
                    "rule_type": "eligibility",
                    "risk_level": "high",
                    "description": "Old description",
                },
            ],
            "entity_types": {},
        }
        graph_data_v2 = {
            "business_rules": [
                {
                    "rule_id": "R001",
                    "rule_name": "LTV Rule Updated",
                    "rule_type": "eligibility",
                    "risk_level": "critical",
                    "description": "New description",
                    "jurisdiction": "agency:FNMA",
                    "enforcement_action": "Repurchase",
                },
            ],
            "entity_types": {},
        }
        with patch.object(service.graph_service, "get_graph_data", return_value=graph_data_v1):
            service.seed_obligations("G", "openai")

        store.update_obligation_status("G", "openai", "R001", "mapped", "Reviewed")

        with patch.object(service.graph_service, "get_graph_data", return_value=graph_data_v2):
            result = service.seed_obligations("G", "openai")
            assert result["existing"] == 1

        ob = store.get_obligation("G", "openai", "R001")
        assert ob["status"] == "mapped"
        assert ob["notes"] == "Reviewed"
        assert ob["description"] == "New description"
        assert ob["jurisdiction"] == "agency:FNMA"
        assert ob["enforcement_action"] == "Repurchase"

    def test_seed_optional_rule(self, store, service):
        graph_data = {
            "business_rules": [
                {
                    "rule_id": "R010",
                    "rule_name": "Optional Guidance",
                    "rule_type": "documentation",
                    "risk_level": "medium",
                    "mandatory": False,
                },
            ],
            "entity_types": {},
        }
        with patch.object(service.graph_service, "get_graph_data", return_value=graph_data):
            service.seed_obligations("G", "openai")

        ob = store.get_obligation("G", "openai", "R010")
        assert ob["mandatory"] == 0


class TestEnrichedExport:
    def test_csv_includes_enriched_columns(self, store, service):
        store.upsert_obligation(
            "G", "openai", "R001", "LTV Rule", "eligibility", "critical", "mapped",
            description="LTV must be under 80%",
            jurisdiction="agency:FNMA",
            mandatory=1,
            effective_date="2023-06-01",
            audit_frequency="quarterly",
            enforcement_action="Repurchase",
        )
        csv_str = service.export_obligations("G", "openai", "csv")
        assert "Description" in csv_str
        assert "Jurisdiction" in csv_str
        assert "Mandatory" in csv_str
        assert "Effective Date" in csv_str
        assert "Audit Frequency" in csv_str
        assert "Enforcement Action" in csv_str
        assert "agency:FNMA" in csv_str
        assert "quarterly" in csv_str

    def test_json_export_includes_enriched(self, store, service):
        store.upsert_obligation(
            "G", "openai", "R001", "LTV Rule", "eligibility", "critical", "mapped",
            description="Test desc",
            jurisdiction="agency:FNMA",
        )
        result = service.export_obligations("G", "openai", "json")
        ob = result["obligations"][0]
        assert ob["description"] == "Test desc"
        assert ob["jurisdiction"] == "agency:FNMA"
