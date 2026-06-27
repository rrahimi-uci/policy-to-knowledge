"""
API endpoint tests for Impact Analysis and Obligations routers
using FastAPI TestClient.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Use temp databases for stores."""
    db_path = tmp_path / "test_api.db"
    monkeypatch.setattr("ui.backend.services.impact_store._DB_PATH", db_path)
    monkeypatch.setattr("ui.backend.services.obligation_store._DB_PATH", db_path)
    monkeypatch.setattr("ui.backend.services.run_store._DB_PATH", db_path)

    import ui.backend.services.impact_store as is_
    import ui.backend.services.obligation_store as os_
    import ui.backend.services.run_store as rs_

    for mod in (is_, os_, rs_):
        if hasattr(mod._local, "conn"):
            mod._local.conn = None

    rs_.init_db()
    is_.init_tables()
    os_.init_tables()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from ui.backend.main import app
    return TestClient(app)


@pytest.fixture
def sample_graph_data():
    return {
        "business_rules": [
            {
                "rule_id": "R001",
                "rule_name": "LTV Must Not Exceed 80%",
                "rule_type": "eligibility",
                "confidence_score": 0.92,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
                "dependencies": [],
                "dependent_rules": [],
            },
            {
                "rule_id": "R002",
                "rule_name": "Credit Counseling Required",
                "rule_type": "process",
                "confidence_score": 0.85,
                "risk_level": "high",
                "mandatory": True,
                "entity_type": "borrower",
                "dependencies": [],
                "dependent_rules": [],
            },
        ],
        "metadata": {"original_rule_count": 2, "optimized_rule_count": 2},
        "entity_types": {},
        "dependency_details": {"dependencies": [], "conflicts": []},
    }


# ═══════════════════════════════════════════════════════════════════
# IMPACT ANALYSIS API TESTS
# ═══════════════════════════════════════════════════════════════════

class TestImpactAnalysisAPI:
    def test_analyze_endpoint(self, client, sample_graph_data):
        with patch("ui.backend.services.impact_service.graph_service.get_graph_data", return_value=sample_graph_data):
            old_content = b"Section 1: LTV\n\nThe maximum loan-to-value ratio is 80% for conventional loans."
            new_content = b"Section 1: LTV\n\nThe maximum loan-to-value ratio is 90% for conventional loans. This must be mandatory."
            resp = client.post(
                "/api/impact/analyze",
                # mode=basic → deterministic heuristic engine (no LLM calls)
                data={"graph_name": "TestGraph", "provider": "openai", "mode": "basic"},
                files=[
                    ("old_doc", ("old.txt", old_content, "text/plain")),
                    ("new_doc", ("new.txt", new_content, "text/plain")),
                ],
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "completed"
            assert data["stats"]["total_changes"] > 0
            assert "items" in data

    def test_analyze_empty_old_doc(self, client):
        resp = client.post(
            "/api/impact/analyze",
            data={"graph_name": "G", "provider": "openai"},
            files=[
                ("old_doc", ("old.txt", b"", "text/plain")),
                ("new_doc", ("new.txt", b"some content here", "text/plain")),
            ],
        )
        assert resp.status_code == 400

    def test_analyze_empty_new_doc(self, client):
        resp = client.post(
            "/api/impact/analyze",
            data={"graph_name": "G", "provider": "openai"},
            files=[
                ("old_doc", ("old.txt", b"old content here", "text/plain")),
                ("new_doc", ("new.txt", b"", "text/plain")),
            ],
        )
        assert resp.status_code == 400

    def test_list_analyses_empty(self, client):
        resp = client.get("/api/impact/analyses")
        assert resp.status_code == 200
        assert resp.json()["analyses"] == []

    def test_list_analyses_after_creation(self, client, sample_graph_data):
        with patch("ui.backend.services.impact_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post(
                "/api/impact/analyze",
                data={"graph_name": "G", "provider": "openai"},
                files=[
                    ("old_doc", ("old.txt", b"Old provision about mortgages.", "text/plain")),
                    ("new_doc", ("new.txt", b"New provision about mandatory mortgages.", "text/plain")),
                ],
            )
        resp = client.get("/api/impact/analyses")
        assert len(resp.json()["analyses"]) == 1

    def test_get_analysis_not_found(self, client):
        resp = client.get("/api/impact/analyses/nonexistent")
        assert resp.status_code == 404

    def test_delete_analysis(self, client, sample_graph_data):
        with patch("ui.backend.services.impact_service.graph_service.get_graph_data", return_value=sample_graph_data):
            create_resp = client.post(
                "/api/impact/analyze",
                data={"graph_name": "G", "provider": "openai"},
                files=[
                    ("old_doc", ("old.txt", b"Old provision about lending.", "text/plain")),
                    ("new_doc", ("new.txt", b"New provision about lending.", "text/plain")),
                ],
            )
            aid = create_resp.json()["id"]
        resp = client.delete(f"/api/impact/analyses/{aid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == aid

    def test_delete_analysis_not_found(self, client):
        resp = client.delete("/api/impact/analyses/nope")
        assert resp.status_code == 404

    def test_export_json(self, client, sample_graph_data):
        with patch("ui.backend.services.impact_service.graph_service.get_graph_data", return_value=sample_graph_data):
            create_resp = client.post(
                "/api/impact/analyze",
                data={"graph_name": "G", "provider": "openai"},
                files=[
                    ("old_doc", ("old.txt", b"Old provision about documentation.", "text/plain")),
                    ("new_doc", ("new.txt", b"New provision about documentation.", "text/plain")),
                ],
            )
            aid = create_resp.json()["id"]
        resp = client.get(f"/api/impact/analyses/{aid}/export/json")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_export_csv(self, client, sample_graph_data):
        with patch("ui.backend.services.impact_service.graph_service.get_graph_data", return_value=sample_graph_data):
            create_resp = client.post(
                "/api/impact/analyze",
                data={"graph_name": "G", "provider": "openai"},
                files=[
                    ("old_doc", ("old.txt", b"Old provision about compliance.", "text/plain")),
                    ("new_doc", ("new.txt", b"New provision about compliance.", "text/plain")),
                ],
            )
            aid = create_resp.json()["id"]
        resp = client.get(f"/api/impact/analyses/{aid}/export/csv")
        assert resp.status_code == 200
        assert "change_type" in resp.text

    def test_export_unsupported_format(self, client):
        resp = client.get("/api/impact/analyses/any/export/xml")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# OBLIGATIONS API TESTS
# ═══════════════════════════════════════════════════════════════════

class TestObligationsAPI:
    def test_seed_obligations(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            resp = client.post("/api/obligations/TestGraph/seed?provider=openai")
            assert resp.status_code == 200
            data = resp.json()
            assert data["created"] == 2
            assert data["total_rules"] == 2

    def test_seed_missing_graph(self, client):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=None):
            resp = client.post("/api/obligations/Missing/seed?provider=openai")
            assert resp.status_code == 404

    def test_list_obligations_empty(self, client):
        resp = client.get("/api/obligations/TestGraph?provider=openai")
        assert resp.status_code == 200
        assert resp.json()["obligations"] == []

    def test_list_obligations_after_seed(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.get("/api/obligations/G?provider=openai")
        data = resp.json()
        assert len(data["obligations"]) == 2
        assert "heatmap" in data

    def test_update_status(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.put(
            "/api/obligations/G/R001?provider=openai",
            json={"status": "mapped", "notes": "Verified"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "mapped"
        assert resp.json()["notes"] == "Verified"

    def test_update_invalid_status(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.put(
            "/api/obligations/G/R001?provider=openai",
            json={"status": "invalid-status"},
        )
        assert resp.status_code == 400

    def test_update_nonexistent_rule(self, client):
        resp = client.put(
            "/api/obligations/G/NOPE?provider=openai",
            json={"status": "mapped"},
        )
        assert resp.status_code == 404

    def test_add_control(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.post(
            "/api/obligations/G/R001/controls?provider=openai",
            json={
                "control_name": "SOC2 Audit",
                "control_type": "audit",
                "description": "Annual audit",
                "owner": "Compliance Team",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["control_name"] == "SOC2 Audit"

    def test_add_control_invalid_type(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.post(
            "/api/obligations/G/R001/controls?provider=openai",
            json={"control_name": "X", "control_type": "bad-type"},
        )
        assert resp.status_code == 400

    def test_add_control_nonexistent_rule(self, client):
        resp = client.post(
            "/api/obligations/G/NOPE/controls?provider=openai",
            json={"control_name": "X", "control_type": "policy"},
        )
        assert resp.status_code == 404

    def test_delete_control(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        add_resp = client.post(
            "/api/obligations/G/R001/controls?provider=openai",
            json={"control_name": "Test", "control_type": "policy"},
        )
        ctrl_id = add_resp.json()["id"]
        del_resp = client.delete(f"/api/obligations/controls/{ctrl_id}")
        assert del_resp.status_code == 200

    def test_delete_control_not_found(self, client):
        resp = client.delete("/api/obligations/controls/99999")
        assert resp.status_code == 404

    def test_suggest_controls(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.get("/api/obligations/G/R001/suggest?provider=openai")
        assert resp.status_code == 200
        assert len(resp.json()["suggestions"]) > 0

    def test_suggest_nonexistent(self, client):
        resp = client.get("/api/obligations/G/NOPE/suggest?provider=openai")
        assert resp.status_code == 404

    def test_heatmap(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.get("/api/obligations/G/heatmap?provider=openai")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_obligations"] == 2
        assert "compliance_score" in data

    def test_export_csv(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.get("/api/obligations/G/export/csv?provider=openai")
        assert resp.status_code == 200
        assert "Obligation ID" in resp.text

    def test_export_json(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.get("/api/obligations/G/export/json?provider=openai")
        assert resp.status_code == 200
        assert "obligations" in resp.json()

    def test_export_unsupported_format(self, client):
        resp = client.get("/api/obligations/G/export/xml?provider=openai")
        assert resp.status_code == 400

    def test_reset_obligations(self, client, sample_graph_data):
        with patch("ui.backend.services.obligation_service.graph_service.get_graph_data", return_value=sample_graph_data):
            client.post("/api/obligations/G/seed?provider=openai")
        resp = client.delete("/api/obligations/G?provider=openai")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 2



