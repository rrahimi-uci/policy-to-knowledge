"""Unit tests for the pipeline graph_service (filesystem-backed, no live graph DB)."""
import json
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ui.backend.services import graph_service as gs  # noqa: E402


@pytest.fixture
def fake_output(tmp_path, monkeypatch):
    """Point graph_service at a temp pipeline-output tree."""
    monkeypatch.setattr(gs, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "pipeline-output"
    out.mkdir()
    return out


def _write_graph(out: Path, name: str, rules=2, entities=1):
    d = out / name / "agent-5-optimized"
    d.mkdir(parents=True)
    kg = {
        "business_rules": [{"rule_id": f"R{i}"} for i in range(rules)],
        "entity_types": {f"E{i}": {} for i in range(entities)},
    }
    (d / "optimized_compliance_knowledge_graph.json").write_text(json.dumps(kg))


@allure.feature("Pipeline graph_service")
@allure.story("Listing generated graphs")
class TestListGraphs:
    @allure.title("Lists source dirs directly under pipeline-output/ (no provider segment)")
    def test_lists_flat_layout(self, fake_output):
        _write_graph(fake_output, "sample_a", rules=3, entities=2)
        _write_graph(fake_output, "sample_b", rules=1, entities=1)
        graphs = {g["name"]: g for g in gs.list_graphs()}
        assert set(graphs) == {"sample_a", "sample_b"}
        assert graphs["sample_a"]["rules"] == 3
        assert graphs["sample_a"]["entities"] == 2
        assert graphs["sample_a"]["has_optimized"] is True

    @allure.title("Skips internal _merged/_joined folders")
    def test_skips_internal_dirs(self, fake_output):
        _write_graph(fake_output, "real", rules=1)
        (fake_output / "_merged" / "x").mkdir(parents=True)
        (fake_output / "_joined" / "y").mkdir(parents=True)
        names = [g["name"] for g in gs.list_graphs()]
        assert names == ["real"]

    @allure.title("Empty / missing output returns []")
    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gs, "PROJECT_ROOT", tmp_path)
        assert gs.list_graphs() == []


@allure.feature("Pipeline graph_service")
@allure.story("Loading graph data")
class TestGetGraphData:
    @allure.title("Loads the optimized KG JSON by name")
    def test_load(self, fake_output):
        _write_graph(fake_output, "g1", rules=2)
        data = gs.get_graph_data("g1")
        assert data is not None and len(data["business_rules"]) == 2

    @allure.title("Returns None for an unknown graph")
    def test_missing(self, fake_output):
        assert gs.get_graph_data("nope") is None


@allure.feature("Pipeline graph_service")
@allure.story("Comparison discovery")
class TestComparisons:
    @allure.title("Finds comparisons under _merged with no provider segment (regression)")
    def test_comparison_base_dirs_flat(self, fake_output):
        (fake_output / "_merged" / "g1_g2" / "agent-9-set-operations").mkdir(parents=True)
        bases = gs._comparison_base_dirs()
        assert (fake_output / "_merged") in bases
        # The provider-segment path must NOT be used anymore.
        assert all("openai" not in str(b) for b in bases)


@allure.feature("Pipeline graph_service")
@allure.story("Domain inference")
class TestDomainInference:
    @allure.title("'commercial-lending' is commercial_lending, not mortgage (ordering fix)")
    def test_commercial_not_mortgage(self):
        assert gs._infer_domain_from_name("commercial-lending") == "commercial_lending"
        assert gs._infer_domain_from_name("commercial_lending_q4") == "commercial_lending"

    @pytest.mark.parametrize("name,domain", [
        ("mortgage_guidelines", "mortgage"),
        ("aml_kyc_rules", "aml"),
        ("healthcare_hipaa", "healthcare"),
        ("totally_unknown", ""),
    ])
    @allure.title("infer({name}) == {domain}")
    def test_other_domains(self, name, domain):
        assert gs._infer_domain_from_name(name) == domain


@allure.feature("Pipeline graph_service")
@allure.story("Theme injection")
class TestThemeInjection:
    @allure.title("apply_theme injects dark for 'dark' and light otherwise (default)")
    def test_apply_theme(self):
        html = "<html><head></head><body>x</body></html>"
        assert "p2k-dark-theme" in gs.apply_theme(html, "dark")
        assert "p2k-light-theme" in gs.apply_theme(html, "light")
        # Unknown theme falls back to light (documented default).
        assert "p2k-light-theme" in gs.apply_theme(html, "unknown")
