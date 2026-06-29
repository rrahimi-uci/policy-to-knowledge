"""
E2E tests for GET /api/graph — graph data retrieval.
"""

import pytest
from conftest import KNOWN_GRAPHS


class TestGetGraph:
    """GET /api/graph?graph_name=..."""

    def test_returns_nodes_and_links(self, api):
        resp = api.get("/api/graph", params={"graph_name": KNOWN_GRAPHS[0]})
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "links" in data
        assert "graph_name" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["links"], list)

    def test_nodes_have_required_fields(self, any_graph_data):
        node = any_graph_data["nodes"][0]
        for field in ("id", "label", "name"):
            assert field in node, f"Node missing field '{field}'"

    def test_node_ids_are_strings(self, any_graph_data):
        for node in any_graph_data["nodes"][:20]:
            assert isinstance(node["id"], str)

    def test_links_have_source_and_target(self, any_graph_data):
        if not any_graph_data["links"]:
            pytest.skip("Graph has no edges")
        link = any_graph_data["links"][0]
        assert "source" in link
        assert "target" in link
        assert "label" in link

    def test_link_ids_are_strings(self, any_graph_data):
        for link in any_graph_data["links"][:20]:
            assert isinstance(link["source"], str)
            assert isinstance(link["target"], str)

    def test_graph_name_echoed_back(self, api):
        gn = KNOWN_GRAPHS[0]
        resp = api.get("/api/graph", params={"graph_name": gn})
        assert resp.json()["graph_name"] == gn

    @pytest.mark.parametrize("graph_name", KNOWN_GRAPHS)
    def test_each_known_graph_loads(self, api, graph_name):
        resp = api.get("/api/graph", params={"graph_name": graph_name})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) > 0, f"Graph '{graph_name}' returned 0 nodes"

    def test_default_graph_fallback(self, api):
        """Omitting graph_name should fall back to the default graph."""
        resp = api.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) > 0

    def test_nodes_have_property_defaults(self, any_graph_data):
        """Every node should carry ALL_VERTEX_PROPERTIES with defaults."""
        required_defaults = [
            "rule_type", "description", "confidence_score",
            "mandatory", "requires_review", "node_type",
        ]
        node = any_graph_data["nodes"][0]
        for key in required_defaults:
            assert key in node, f"Node missing default property '{key}'"

    def test_graph_g_alias_resolves(self, api):
        """'g' is the frontend's initial value and should not 500."""
        resp = api.get("/api/graph", params={"graph_name": "g"})
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) > 0
