"""
E2E tests for Gremlin console endpoints:
  - GET  /api/gremlin/examples
  - POST /api/gremlin/execute
"""


class TestGremlinExamples:
    """GET /api/gremlin/examples"""

    def test_returns_example_list(self, api):
        resp = api.get("/api/gremlin/examples")
        assert resp.status_code == 200
        data = resp.json()
        assert "examples" in data
        assert isinstance(data["examples"], list)
        assert len(data["examples"]) > 0

    def test_examples_have_fields(self, api):
        examples = api.get("/api/gremlin/examples").json()["examples"]
        for ex in examples:
            assert "name" in ex
            assert "query" in ex
            assert "description" in ex


class TestGremlinExecute:
    """POST /api/gremlin/execute"""

    def test_simple_count_query(self, api):
        resp = api.post("/api/gremlin/execute", json={"query": "g.V().count()"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "elapsed_ms" in data
        assert data["count"] >= 1
        # The count result should be a list with one integer
        assert isinstance(data["results"][0], int)

    def test_group_count_query(self, api):
        resp = api.post(
            "/api/gremlin/execute",
            json={"query": "g.V().groupCount().by(label()).toList()"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    def test_empty_query_returns_400(self, api):
        resp = api.post("/api/gremlin/execute", json={"query": ""})
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_missing_query_returns_400(self, api):
        resp = api.post("/api/gremlin/execute", json={})
        assert resp.status_code == 400

    def test_invalid_gremlin_returns_400(self, api):
        resp = api.post(
            "/api/gremlin/execute",
            json={"query": "this.is.not.valid.gremlin"},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_query_returns_elapsed_ms(self, api):
        resp = api.post("/api/gremlin/execute", json={"query": "g.V().count()"})
        data = resp.json()
        assert isinstance(data["elapsed_ms"], (int, float))
        assert data["elapsed_ms"] >= 0
