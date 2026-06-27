"""Broad FastAPI TestClient coverage for the smaller routers."""
import json
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "runs.db"
    import ui.backend.services.run_store as rs
    import ui.backend.services.impact_store as is_
    import ui.backend.services.obligation_store as os_
    for mod in (rs, is_, os_):
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        if hasattr(mod._local, "conn"):
            mod._local.conn = None
    rs.init_db()
    is_.init_tables()
    os_.init_tables()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from ui.backend.main import app
    return TestClient(app)


@pytest.fixture
def fake_output(tmp_path, monkeypatch):
    from ui.backend.services import graph_service as gs
    monkeypatch.setattr(gs, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "pipeline-output"
    out.mkdir()
    return out


def _write_graph(out: Path, name: str, rules=2):
    d = out / name / "agent-5-optimized"
    d.mkdir(parents=True)
    kg = {"business_rules": [{"rule_id": f"R{i}", "rule_name": f"r{i}"} for i in range(rules)],
          "entity_types": {"E0": {}}}
    (d / "optimized_compliance_knowledge_graph.json").write_text(json.dumps(kg))


@allure.feature("Pipeline API")
@allure.story("Runs router")
class TestRunsRouter:
    @allure.title("GET /api/runs returns [] when empty")
    def test_list_empty(self, client):
        r = client.get("/api/runs")
        assert r.status_code == 200 and r.json() == {"runs": []}

    @allure.title("GET /api/runs/{id} 404 for unknown run")
    def test_get_404(self, client):
        assert client.get("/api/runs/nope").status_code == 404

    @allure.title("DELETE /api/runs/{id} 404 for unknown run")
    def test_delete_404(self, client):
        assert client.delete("/api/runs/nope").status_code == 404

    @allure.title("Created run is listed and fetchable")
    def test_create_then_list(self, client):
        import ui.backend.services.run_store as rs
        rs.create_run("r1", run_type="extraction", provider="openai")
        assert any(x["id"] == "r1" for x in client.get("/api/runs").json()["runs"])
        assert client.get("/api/runs/r1").status_code == 200


@allure.feature("Pipeline API")
@allure.story("Pipeline router")
class TestPipelineRouter:
    @allure.title("GET /api/pipeline/running returns a list")
    def test_running(self, client):
        r = client.get("/api/pipeline/running")
        assert r.status_code == 200 and isinstance(r.json()["runs"], list)

    @allure.title("GET /api/pipeline/history returns a list")
    def test_history(self, client):
        r = client.get("/api/pipeline/history")
        assert r.status_code == 200 and isinstance(r.json()["runs"], list)

    @allure.title("GET /api/pipeline/{id}/status 404 for unknown run")
    def test_status_404(self, client):
        assert client.get("/api/pipeline/nope/status").status_code == 404


@allure.feature("Pipeline API")
@allure.story("Settings router")
class TestSettingsRouter:
    @allure.title("GET /api/settings masks the API key")
    def test_get_masks_key(self, client, tmp_path, monkeypatch):
        from ui.backend.routers import settings
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"openai": {"api_key": "sk-secret-1234567890"}}))
        monkeypatch.setattr(settings, "CONFIG_PATH", cfg)
        body = client.get("/api/settings").json()
        assert "sk-secret-1234567890" not in json.dumps(body)

    @allure.title("PUT /api/settings keeps the real key when a masked value is sent back")
    def test_put_preserves_key(self, client, tmp_path, monkeypatch):
        from ui.backend.routers import settings
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"openai": {"api_key": "sk-real-secret-key-9999"}}))
        monkeypatch.setattr(settings, "CONFIG_PATH", cfg)
        masked = client.get("/api/settings").json()
        client.put("/api/settings", json={"settings": masked})
        saved = json.loads(cfg.read_text())
        assert saved["openai"]["api_key"] == "sk-real-secret-key-9999"


@allure.feature("Pipeline API")
@allure.story("Graphs router")
class TestGraphsRouter:
    @allure.title("GET /api/graphs lists flat-layout graphs")
    def test_list(self, client, fake_output):
        _write_graph(fake_output, "g_alpha", rules=3)
        names = [g["name"] for g in client.get("/api/graphs").json()["graphs"]]
        assert "g_alpha" in names

    @allure.title("GET /api/graphs/{name} returns the KG; 404 when missing")
    def test_get(self, client, fake_output):
        _write_graph(fake_output, "g_beta", rules=2)
        assert client.get("/api/graphs/g_beta").status_code == 200
        assert client.get("/api/graphs/missing").status_code == 404


@allure.feature("Pipeline API")
@allure.story("Compare router")
class TestCompareRouter:
    @allure.title("GET /api/compare returns [] with no comparisons")
    def test_list_empty(self, client, fake_output):
        assert client.get("/api/compare").json() == {"comparisons": []}

    @allure.title("GET /api/compare/{name}/data 404 when absent")
    def test_data_404(self, client, fake_output):
        assert client.get("/api/compare/none/data").status_code == 404
