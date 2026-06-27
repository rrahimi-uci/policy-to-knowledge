"""
E2E tests for vertex endpoints:
  - GET  /api/vertex/<id>
  - POST /api/vertex
  - GET  /api/vertex/schema
"""

import uuid
import pytest
from conftest import KNOWN_GRAPHS


class TestGetVertex:
    """GET /api/vertex/<vertex_id>?graph_name=..."""

    def test_returns_vertex_detail(self, api, any_node_id, default_graph_name):
        resp = api.get(
            f"/api/vertex/{any_node_id}",
            params={"graph_name": default_graph_name},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == any_node_id
        assert "label" in data
        assert "name" in data

    def test_vertex_has_neighbors(self, api, any_node_id, default_graph_name):
        resp = api.get(
            f"/api/vertex/{any_node_id}",
            params={"graph_name": default_graph_name},
        )
        data = resp.json()
        assert "neighbors" in data
        assert isinstance(data["neighbors"], list)

    def test_vertex_has_dependency_lists(self, api, any_node_id, default_graph_name):
        resp = api.get(
            f"/api/vertex/{any_node_id}",
            params={"graph_name": default_graph_name},
        )
        data = resp.json()
        assert "depends_on" in data
        assert "depended_by" in data

    def test_nonexistent_vertex_returns_404(self, api, default_graph_name):
        resp = api.get(
            "/api/vertex/999999999",
            params={"graph_name": default_graph_name},
        )
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_vertex_properties_have_defaults(self, api, any_node_id, default_graph_name):
        resp = api.get(
            f"/api/vertex/{any_node_id}",
            params={"graph_name": default_graph_name},
        )
        data = resp.json()
        expected_keys = ["rule_type", "description", "confidence_score", "mandatory"]
        for key in expected_keys:
            assert key in data, f"Vertex detail missing '{key}'"


class TestCreateVertex:
    """POST /api/vertex"""

    def test_create_and_retrieve(self, api, default_graph_name):
        unique_name = f"E2E Test Rule {uuid.uuid4().hex[:8]}"
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {
                "name": unique_name,
                "content": "This is an end-to-end test rule created by pytest.",
                "rule_type": "constraint",
                "description": "Automated E2E test vertex",
                "mandatory": True,
                "confidence_score": 95.0,
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        created = resp.json()
        assert "id" in created
        assert created["name"] == unique_name
        assert created["label"] == "business_rule"

        # Retrieve the created vertex
        vid = created["id"]
        detail = api.get(
            f"/api/vertex/{vid}",
            params={"graph_name": default_graph_name},
        )
        assert detail.status_code == 200
        assert detail.json()["name"] == unique_name

    def test_create_missing_name_returns_400(self, api, default_graph_name):
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {"content": "Some content here for the rule"},
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 400
        assert "errors" in resp.json()

    def test_create_missing_content_returns_400(self, api, default_graph_name):
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {"name": f"NoContent-{uuid.uuid4().hex[:6]}"},
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 400

    def test_create_short_content_returns_400(self, api, default_graph_name):
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {
                "name": f"ShortContent-{uuid.uuid4().hex[:6]}",
                "content": "Short",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 400

    def test_create_invalid_label_returns_400(self, api, default_graph_name):
        payload = {
            "graph_name": default_graph_name,
            "label": "invalid_label",
            "properties": {
                "name": f"BadLabel-{uuid.uuid4().hex[:6]}",
                "content": "Some content that is at least 10 chars long.",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 400

    def test_create_invalid_rule_type_returns_400(self, api, default_graph_name):
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {
                "name": f"BadType-{uuid.uuid4().hex[:6]}",
                "content": "Some valid content for a business rule.",
                "rule_type": "nonexistent_type",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 400

    def test_create_duplicate_name_returns_409(self, api, any_node, default_graph_name):
        """Creating a vertex with an existing name should conflict."""
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {
                "name": any_node["name"],
                "content": "Duplicate name test — this should fail.",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 409

    def test_create_entity_category(self, api, default_graph_name):
        unique_name = f"E2E Category {uuid.uuid4().hex[:8]}"
        payload = {
            "graph_name": default_graph_name,
            "label": "entity_category",
            "properties": {
                "name": unique_name,
                "content": "An entity category created by the E2E test suite.",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 201
        assert resp.json()["label"] == "entity_category"

    def test_confidence_score_out_of_range(self, api, default_graph_name):
        payload = {
            "graph_name": default_graph_name,
            "label": "business_rule",
            "properties": {
                "name": f"BadScore-{uuid.uuid4().hex[:6]}",
                "content": "Content for confidence score validation test.",
                "confidence_score": 150,
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 400


class TestVertexSchema:
    """GET /api/vertex/schema"""

    def test_returns_schema_metadata(self, api):
        resp = api.get("/api/vertex/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "labels" in data
        assert "rule_types" in data
        assert "dependency_types" in data
        assert "edge_labels" in data
        assert "properties" in data

    def test_schema_labels_match(self, api):
        data = api.get("/api/vertex/schema").json()
        assert "business_rule" in data["labels"]
        assert "entity_category" in data["labels"]

    def test_schema_properties_per_label(self, api):
        data = api.get("/api/vertex/schema").json()
        br = data["properties"]["business_rule"]
        assert "name" in br["required"]
        assert "content" in br["required"]
        assert len(br["optional"]) > 0
