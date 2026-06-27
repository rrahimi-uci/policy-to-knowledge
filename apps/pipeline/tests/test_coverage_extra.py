"""Extra coverage: graph_service comparisons, config getters, run_store extras."""
import json
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── graph_service comparisons ────────────────────────────────────────────────
from ui.backend.services import graph_service as gs  # noqa: E402


@pytest.fixture
def merged(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "PROJECT_ROOT", tmp_path)
    base = tmp_path / "pipeline-output" / "_merged" / "alpha_bank_beta_bank"
    ops = base / "agent-9-set-operations"
    ops.mkdir(parents=True)
    (ops / "union.json").write_text(json.dumps({
        "metadata": {"g1_name": "alpha_bank", "g2_name": "beta_bank"},
        "business_rules": [{"rule_id": "R1"}, {"rule_id": "R2"}],
    }))
    (ops / "contradictions.json").write_text(json.dumps({
        "metadata": {"g1_name": "alpha_bank", "g2_name": "beta_bank"},
        "contradictions": [{"a": "R1", "b": "R2"}],
    }))
    viz = base / "agent-10-visualizations"
    viz.mkdir()
    (viz / "union.html").write_text("<html>union</html>")
    return tmp_path


@allure.feature("Pipeline graph_service")
@allure.story("Comparisons")
class TestComparisons:
    @allure.title("list_comparisons surfaces g1/g2 + per-operation counts")
    def test_list(self, merged):
        comps = gs.list_comparisons()
        assert len(comps) == 1
        c = comps[0]
        assert c["name"] == "alpha_bank_beta_bank"
        assert c["g1"] == "alpha_bank" and c["g2"] == "beta_bank"
        assert c["union_count"] == 2
        assert c["contradictions_count"] == 1
        assert c["has_visualizations"] is True

    @allure.title("get_comparison_data returns every set-operation file")
    def test_data(self, merged):
        data = gs.get_comparison_data("alpha_bank_beta_bank")
        assert set(data) == {"union", "contradictions"}
        assert data["union"]["business_rules"][0]["rule_id"] == "R1"

    @allure.title("get_comparison_html returns the operation HTML; None when absent")
    def test_html(self, merged):
        assert "union" in gs.get_comparison_html("alpha_bank_beta_bank", "union")
        assert gs.get_comparison_html("alpha_bank_beta_bank", "missing") is None

    @allure.title("Unknown comparison returns None")
    def test_missing(self, merged):
        assert gs.get_comparison_data("nope") is None


# ── config getters ───────────────────────────────────────────────────────────
from utils.config import Config  # noqa: E402


@allure.feature("Pipeline config")
@allure.story("Getters")
class TestConfigGetters:
    @pytest.fixture
    def cfg(self, monkeypatch):
        monkeypatch.setenv("P2K_CONFIG_PATH", str(PROJECT_ROOT / "config.example.json"))
        Config._instance = None
        Config._config = None
        return Config()

    @allure.title("Model/provider getters return sane values")
    def test_models(self, cfg):
        assert cfg.get_model_provider() == "openai"
        assert isinstance(cfg.get_reasoning_model(), str)
        assert cfg.get_reasoning_effort() in ("low", "medium", "high")
        assert isinstance(cfg.get_optimizer_model(), str)

    @allure.title("Numeric tuning getters are positive ints/floats")
    def test_numbers(self, cfg):
        assert cfg.get_target_rules() == 300
        assert cfg.get_max_workers() >= 1
        assert cfg.get_chunk_size_target() >= 1
        assert cfg.get_max_chunk_size() >= cfg.get_chunk_size_target()
        assert cfg.get_rules_per_batch() >= 1
        assert cfg.get_max_retries() >= 0
        assert cfg.get_timeout() >= 1
        assert 0.0 <= cfg.get_default_temperature() <= 2.0

    @allure.title("Domain getters resolve the active domain + prompt dir")
    def test_domain(self, cfg):
        assert cfg.get_domain() in ("mortgage", "aml", "healthcare", "commercial_lending")
        assert "domain-prompts" in str(cfg.get_domain_prompts_dir())

    @allure.title("Output path getters are under pipeline-output (no provider segment)")
    def test_paths(self, cfg):
        base = str(cfg.get_pipeline_base_path())
        assert base.startswith("pipeline-output")
        assert "openai" not in base
        for getter in ("get_organized_dir", "get_rules_extracted_dir", "get_optimized_dir"):
            assert "pipeline-output" in str(getattr(cfg, getter)())


# ── run_store extras ─────────────────────────────────────────────────────────
from ui.backend.services import run_store as rs  # noqa: E402


@allure.feature("Pipeline run store")
@allure.story("Listing helpers")
class TestRunStoreExtra:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rs, "_DB_PATH", tmp_path / "runs.db")
        if hasattr(rs._local, "conn"):
            rs._local.conn = None
        rs.init_db()
        yield rs
        if getattr(rs._local, "conn", None):
            rs._local.conn.close(); rs._local.conn = None

    @allure.title("list_running_runs returns only running runs")
    def test_list_running(self, store):
        store.create_run("a", run_type="extraction")          # running by default
        store.create_run("b", run_type="extraction")
        store.update_run("b", status="completed")
        running = {r["id"] for r in store.list_running_runs()}
        assert running == {"a"}

    @allure.title("delete_all_runs clears everything")
    def test_delete_all(self, store):
        store.create_run("a", run_type="extraction")
        store.create_run("b", run_type="extraction")
        assert store.delete_all_runs() >= 2
        assert store.list_runs() == []
