"""Graphs router: visualization, delete, and export (json/csv/bad) branches."""
import json
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from ui.backend.services import graph_service as gs
    monkeypatch.setattr(gs, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "pipeline-output"
    out.mkdir()
    from fastapi.testclient import TestClient
    from ui.backend.main import app
    return TestClient(app), out


def _make_graph(out: Path, name: str, *, viz=True, csv=True):
    opt = out / name / "agent-5-optimized"
    opt.mkdir(parents=True)
    kg = {"business_rules": [{"rule_id": "R1", "rule_name": "r1"}], "entity_types": {"E": {}}}
    (opt / "optimized_compliance_knowledge_graph.json").write_text(json.dumps(kg))
    if csv:
        (opt / "optimized-business_rules_export.csv").write_text("rule_id,rule_name\nR1,r1\n")
    if viz:
        viz_dir = out / name / "agent-6-visualization-and-report"
        viz_dir.mkdir(parents=True)
        (viz_dir / f"{name}_knowledge_graph.html").write_text("<html><body>graph</body></html>")


@allure.feature("Pipeline API")
@allure.story("Graphs router — viz/delete/export")
class TestGraphsRouter:
    @allure.title("GET /{name}/visualization themes the HTML; 404 when absent")
    def test_visualization(self, client):
        c, out = client
        _make_graph(out, "g1")
        ok = c.get("/api/graphs/g1/visualization?theme=dark")
        assert ok.status_code == 200 and "graph" in ok.text
        assert c.get("/api/graphs/none/visualization").status_code == 404

    @allure.title("DELETE /{name} removes the graph; 404 when absent")
    def test_delete(self, client):
        c, out = client
        _make_graph(out, "g2")
        assert c.delete("/api/graphs/g2").json() == {"deleted": "g2"}
        assert not (out / "g2").exists()
        assert c.delete("/api/graphs/g2").status_code == 404

    @allure.title("Export json/csv succeed; unknown name + bad format error")
    def test_export(self, client):
        c, out = client
        _make_graph(out, "g3")
        rj = c.get("/api/graphs/g3/export/json")
        assert rj.status_code == 200 and "attachment" in rj.headers["content-disposition"]
        rc = c.get("/api/graphs/g3/export/csv")
        assert rc.status_code == 200 and "R1" in rc.text
        assert c.get("/api/graphs/missing/export/json").status_code == 404
        assert c.get("/api/graphs/g3/export/xml").status_code == 400

    @allure.title("CSV export 404s when no CSV file exists")
    def test_export_csv_missing(self, client):
        c, out = client
        _make_graph(out, "g4", csv=False)
        assert c.get("/api/graphs/g4/export/csv").status_code == 404
