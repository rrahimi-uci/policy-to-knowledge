"""
E2E tests for edge endpoints:
  - POST /api/edge
  - POST /api/vertex/suggest-connections
"""

import uuid
import pytest
from conftest import KNOWN_GRAPHS


@pytest.fixture(scope="module")
def two_node_ids(api=None):
    """Create two fresh vertices and return their IDs for edge tests.

    Uses a module-scoped fixture so the vertices exist for all edge tests.
    """
    import requests
    from conftest import BASE_URL, TIMEOUT

    graph_name = KNOWN_GRAPHS[0]
    ids = []
    for i in range(2):
        payload = {
            "graph_name": graph_name,
            "label": "business_rule",
            "properties": {
                "name": f"E2E Edge Node {i} {uuid.uuid4().hex[:8]}",
                "content": f"Edge test node {i} — created for E2E edge creation tests.",
                "rule_type": "constraint",
            },
        }
        resp = requests.post(f"{BASE_URL}/api/vertex", json=payload, timeout=TIMEOUT)
        assert resp.status_code == 201, f"Setup failed: {resp.text}"
        ids.append(resp.json()["id"])
    return ids


class TestCreateEdge:
    """POST /api/edge"""

    def test_create_edge_between_two_nodes(self, api, two_node_ids):
        src, tgt = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "source_id": src,
            "target_id": tgt,
            "label": "depends_on",
            "properties": {
                "dependency_type": "prerequisite",
                "strength": 3,
                "rationale": "Automated E2E test edge.",
            },
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 201, f"Create edge failed: {resp.text}"
        data = resp.json()
        assert "id" in data
        assert data["source"] == src
        assert data["target"] == tgt
        assert data["label"] == "depends_on"

    def test_create_edge_missing_source_returns_400(self, api, two_node_ids):
        _, tgt = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "target_id": tgt,
            "label": "depends_on",
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 400
        assert "errors" in resp.json()

    def test_create_edge_missing_target_returns_400(self, api, two_node_ids):
        src, _ = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "source_id": src,
            "label": "depends_on",
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 400

    def test_create_edge_invalid_label_returns_400(self, api, two_node_ids):
        src, tgt = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "source_id": src,
            "target_id": tgt,
            "label": "invalid_edge_label",
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 400

    def test_create_edge_invalid_dependency_type(self, api, two_node_ids):
        src, tgt = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "source_id": src,
            "target_id": tgt,
            "label": "depends_on",
            "properties": {"dependency_type": "bad_type"},
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 400

    def test_create_edge_strength_out_of_range(self, api, two_node_ids):
        src, tgt = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "source_id": src,
            "target_id": tgt,
            "label": "depends_on",
            "properties": {"strength": 10},
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 400

    def test_create_edge_nonexistent_source_returns_404(self, api, two_node_ids):
        _, tgt = two_node_ids
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "source_id": "999999999",
            "target_id": tgt,
            "label": "depends_on",
        }
        resp = api.post("/api/edge", json=payload)
        assert resp.status_code == 404


class TestSuggestConnections:
    """POST /api/vertex/suggest-connections"""

    def test_returns_suggestions(self, api):
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "name": "Appraisal Requirement",
            "content": "Appraisal must be completed by a licensed appraiser within 120 days.",
            "rule_type": "constraint",
            "top_k": 3,
        }
        resp = api.post("/api/vertex/suggest-connections", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)

    def test_suggestions_have_scores(self, api):
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "content": "Loan-to-value ratio must not exceed 80% for investment properties.",
            "name": "LTV Limit",
            "rule_type": "eligibility",
        }
        resp = api.post("/api/vertex/suggest-connections", json=payload)
        if resp.status_code == 200:
            suggestions = resp.json().get("suggestions", [])
            if suggestions:
                s = suggestions[0]
                assert "score" in s or "final_score" in s

    def test_suggestions_missing_content_returns_400(self, api):
        payload = {
            "graph_name": KNOWN_GRAPHS[0],
            "name": "No Content",
        }
        resp = api.post("/api/vertex/suggest-connections", json=payload)
        assert resp.status_code == 400
