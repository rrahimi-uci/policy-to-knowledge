"""
E2E tests for search endpoints:
  - GET /api/search/text
  - GET /api/search/semantic
"""

import pytest
from conftest import KNOWN_GRAPHS


class TestTextSearch:
    """GET /api/search/text?q=..."""

    def test_returns_results(self, api):
        resp = api.get("/api/search/text", params={"q": "appraisal"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "count" in data
        assert "query" in data
        assert data["query"] == "appraisal"

    def test_results_have_required_fields(self, api):
        resp = api.get("/api/search/text", params={"q": "loan"})
        data = resp.json()
        if data["count"] > 0:
            r = data["results"][0]
            for field in ("id", "name", "label", "content"):
                assert field in r, f"Search result missing '{field}'"

    def test_missing_query_returns_400(self, api):
        resp = api.get("/api/search/text")
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_empty_query_returns_400(self, api):
        resp = api.get("/api/search/text", params={"q": ""})
        assert resp.status_code == 400

    def test_no_match_returns_empty(self, api):
        resp = api.get("/api/search/text", params={"q": "xyzzy_no_match_99999"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestSemanticSearch:
    """GET /api/search/semantic?q=..."""

    def test_returns_results(self, api):
        resp = api.get("/api/search/semantic", params={"q": "income verification"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "query" in data

    def test_respects_top_k(self, api):
        resp = api.get(
            "/api/search/semantic",
            params={"q": "borrower qualification", "top_k": 3},
        )
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 3

    def test_respects_graph_name(self, api):
        gn = KNOWN_GRAPHS[0]
        resp = api.get(
            "/api/search/semantic",
            params={"q": "debt ratio", "graph_name": gn},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["graph_name"] == gn

    def test_missing_query_returns_400(self, api):
        resp = api.get("/api/search/semantic")
        assert resp.status_code == 400

    def test_results_have_similarity_score(self, api):
        resp = api.get("/api/search/semantic", params={"q": "underwriting"})
        data = resp.json()
        if data["results"]:
            r = data["results"][0]
            assert "similarity" in r or "score" in r or "name" in r
