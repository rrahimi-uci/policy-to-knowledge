"""
Tests for config centralization — verifies that hardcoded values have been moved to config.json
and that config getters return expected values.
"""
import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import Config, get_config, reload_config


# ── Fixture: fresh config for each test ──

@pytest.fixture(autouse=True)
def reset_config():
    """Reset the singleton config before each test."""
    Config._instance = None
    Config._config = None
    Config._provider = None
    Config._source_file_name = None
    Config._batch_name = None
    import utils.config as cfg_mod
    cfg_mod._config = None
    yield
    Config._instance = None
    Config._config = None
    Config._provider = None
    Config._source_file_name = None
    Config._batch_name = None
    cfg_mod._config = None


# ── 1. config.json structure tests ──

class TestConfigJsonStructure:
    """Verify config.json contains all required sections and keys."""

    @pytest.fixture
    def config_data(self):
        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path) as f:
            return json.load(f)

    def test_has_llm_section(self, config_data):
        assert "llm" in config_data
        assert "default_temperature" in config_data["llm"]
        assert "default_max_tokens" in config_data["llm"]
        assert "default_model" in config_data["llm"]

    def test_has_pipeline_section(self, config_data):
        assert "pipeline" in config_data
        assert "max_workers" in config_data["pipeline"]
        assert "supported_extensions" in config_data["pipeline"]

    def test_has_optimizer_section(self, config_data):
        assert "optimizer" in config_data
        for key in ["model", "dedup_temperature", "dedup_max_tokens",
                     "dependency_temperature", "dependency_max_tokens",
                     "batch_size", "description_truncation_length",
                     "batched_temperature", "batched_max_tokens",
                     "cross_batch_temperature", "cross_batch_max_tokens"]:
            assert key in config_data["optimizer"], f"Missing optimizer.{key}"

    def test_has_semantic_matcher_section(self, config_data):
        assert "semantic_matcher" in config_data
        assert "max_workers" in config_data["semantic_matcher"]
        assert "batch_size" in config_data["semantic_matcher"]
        assert "max_tokens" in config_data["semantic_matcher"]

    def test_has_join_graphs_section(self, config_data):
        assert "join_graphs" in config_data
        assert "max_workers" in config_data["join_graphs"]
        assert "batch_size" in config_data["join_graphs"]

    def test_has_rules_extractor_extended_keys(self, config_data):
        rules = config_data["rules_extractor"]
        for key in ["batch_size", "max_content_length", "target_words_per_batch",
                     "temperature", "max_tokens", "low_confidence_threshold",
                     "default_confidence_score", "confidence_weights"]:
            assert key in rules, f"Missing rules_extractor.{key}"

    def test_has_document_organizer_extended_keys(self, config_data):
        doc = config_data["document_organizer"]
        for key in ["chunk_overlap", "csv_rows_per_chunk", "max_content_for_analysis",
                     "simple_chunk_size", "docx_fallback_chunk_size"]:
            assert key in doc, f"Missing document_organizer.{key}"

    def test_has_entity_extractor_extended_keys(self, config_data):
        entity = config_data["entity_extractor"]
        assert "temperature" in entity
        assert "max_tokens" in entity

    def test_confidence_weights_sum_to_one(self, config_data):
        weights = config_data["rules_extractor"]["confidence_weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"Confidence weights sum to {total}, expected ~1.0"


# ── 2. Config getter tests ──

class TestConfigGetters:
    """Verify all new config getters return correct values from config.json."""

    def test_get_default_temperature(self):
        config = get_config()
        assert config.get_default_temperature() == 0.7

    def test_get_default_max_tokens(self):
        config = get_config()
        assert config.get_default_max_tokens() == 8192

    def test_get_default_model(self):
        config = get_config()
        assert config.get_default_model() == "gpt-4o"

    def test_get_max_workers(self):
        config = get_config()
        assert config.get_max_workers() == 20

    def test_get_max_workers_env_override(self):
        config = get_config()
        with patch.dict(os.environ, {"MAX_WORKERS": "42"}):
            assert config.get_max_workers() == 42

    def test_get_supported_extensions(self):
        config = get_config()
        exts = config.get_supported_extensions()
        assert ".pdf" in exts
        assert ".md" in exts
        assert ".txt" in exts
        assert ".docx" in exts

    def test_get_chunk_overlap(self):
        config = get_config()
        assert config.get_chunk_overlap() == 200

    def test_get_csv_rows_per_chunk(self):
        config = get_config()
        assert config.get_csv_rows_per_chunk() == 50

    def test_get_max_content_for_analysis(self):
        config = get_config()
        assert config.get_max_content_for_analysis() == 12000

    def test_get_simple_chunk_size(self):
        config = get_config()
        assert config.get_simple_chunk_size() == 3000

    def test_get_docx_fallback_chunk_size(self):
        config = get_config()
        assert config.get_docx_fallback_chunk_size() == 2000

    def test_get_entity_extractor_temperature(self):
        config = get_config()
        assert config.get_entity_extractor_temperature() == 0.7

    def test_get_entity_extractor_max_tokens(self):
        config = get_config()
        assert config.get_entity_extractor_max_tokens() == 8192


class TestRulesExtractorGetters:
    """Verify rules extractor config getters."""

    def test_get_rules_batch_size(self):
        assert get_config().get_rules_batch_size() == 8

    def test_get_rules_max_content_length(self):
        assert get_config().get_rules_max_content_length() == 8000

    def test_get_rules_target_words_per_batch(self):
        assert get_config().get_rules_target_words_per_batch() == 8000

    def test_get_rules_temperature(self):
        assert get_config().get_rules_temperature() == 0.7

    def test_get_rules_max_tokens(self):
        assert get_config().get_rules_max_tokens() == 8192

    def test_get_rules_low_confidence_threshold(self):
        assert get_config().get_rules_low_confidence_threshold() == 70

    def test_get_rules_default_confidence_score(self):
        assert get_config().get_rules_default_confidence_score() == 75

    def test_get_rules_confidence_weights(self):
        weights = get_config().get_rules_confidence_weights()
        assert weights["extraction_clarity"] == 0.30
        assert weights["numeric_precision"] == 0.25
        assert weights["context_completeness"] == 0.20
        assert weights["source_authority"] == 0.15
        assert weights["logical_consistency"] == 0.10


class TestOptimizerGetters:
    """Verify optimizer config getters."""

    def test_get_optimizer_model_name(self):
        assert get_config().get_optimizer_model_name() == "gpt-5-mini"

    def test_get_optimizer_dedup_temperature(self):
        assert get_config().get_optimizer_dedup_temperature() == 0.2

    def test_get_optimizer_dedup_max_tokens(self):
        assert get_config().get_optimizer_dedup_max_tokens() == 8192

    def test_get_optimizer_dependency_temperature(self):
        assert get_config().get_optimizer_dependency_temperature() == 0.7

    def test_get_optimizer_dependency_max_tokens(self):
        assert get_config().get_optimizer_dependency_max_tokens() == 16384

    def test_get_optimizer_batch_size(self):
        assert get_config().get_optimizer_batch_size() == 50

    def test_get_optimizer_description_truncation_length(self):
        assert get_config().get_optimizer_description_truncation_length() == 500

    def test_get_optimizer_batched_temperature(self):
        assert get_config().get_optimizer_batched_temperature() == 0.2

    def test_get_optimizer_batched_max_tokens(self):
        assert get_config().get_optimizer_batched_max_tokens() == 16384

    def test_get_optimizer_cross_batch_temperature(self):
        assert get_config().get_optimizer_cross_batch_temperature() == 0.2

    def test_get_optimizer_cross_batch_max_tokens(self):
        assert get_config().get_optimizer_cross_batch_max_tokens() == 8192


class TestMatcherAndJoinGetters:
    """Verify semantic matcher and join graphs config getters."""

    def test_get_matcher_max_workers(self):
        assert get_config().get_matcher_max_workers() == 20

    def test_get_matcher_batch_size(self):
        assert get_config().get_matcher_batch_size() == 10

    def test_get_matcher_max_tokens(self):
        assert get_config().get_matcher_max_tokens() == 8000

    def test_get_join_max_workers(self):
        assert get_config().get_join_max_workers() == 15

    def test_get_join_batch_size(self):
        assert get_config().get_join_batch_size() == 10


# ── 3. Fallback mismatch fixes verified ──

class TestFallbackDefaults:
    """Verify that config.py fallback defaults match config.json values."""

    def test_target_rules_matches_config_json(self):
        config = get_config()
        # config.json says 300, fallback should also be 300
        assert config.get_target_rules() == 300

    def test_chunk_size_target_matches_config_json(self):
        config = get_config()
        # config.json says 1000, fallback should also be 1000
        assert config.get_chunk_size_target() == 1000

    def test_max_chunk_size_matches_config_json(self):
        config = get_config()
        # config.json says 2000, fallback should also be 2000
        assert config.get_max_chunk_size() == 2000


# ── 4. No hardcoded values in source files ──

class TestNoHardcodedValues:
    """Verify that key source files no longer contain hardcoded magic values."""

    @pytest.fixture
    def agent5_source(self):
        path = Path(__file__).parent.parent / "agents" / "agent_5_knowledge_graph_optimizer.py"
        return path.read_text()

    def test_agent5_no_hardcoded_gpt5_mini(self, agent5_source):
        """Agent 5 should not hardcode 'gpt-5-mini' — should use config getter."""
        # Find lines that assign gpt-5-mini (not comments or config references)
        lines = agent5_source.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments and config file references
            if stripped.startswith('#') or stripped.startswith('//'):
                continue
            if 'config' in stripped.lower() and 'gpt-5-mini' in stripped:
                continue
            if "'gpt-5-mini'" in stripped or '"gpt-5-mini"' in stripped:
                # The only acceptable usage is in a comment
                if not stripped.startswith('#'):
                    pytest.fail(f"Line {i}: hardcoded gpt-5-mini found: {stripped}")

    @pytest.fixture
    def pipeline_source(self):
        path = Path(__file__).parent.parent / "knowledge_graph_generation.py"
        return path.read_text()

    def test_pipeline_no_hardcoded_extensions(self, pipeline_source):
        """Pipeline should not have hardcoded {'.pdf', '.txt', '.md', '.docx'} sets."""
        assert "'.pdf', '.txt', '.md', '.docx'" not in pipeline_source
        assert "'.pdf', '.txt', '.docx', '.md'" not in pipeline_source


# ── 5. LLM client config integration ──

class TestLLMClientConfigIntegration:
    """Verify llm_client.py uses config for defaults."""

    def test_llm_client_default_model_from_config(self):
        from utils.llm_client import LLMClient
        client = LLMClient()
        # Should use config default_model (gpt-4o) rather than hardcoded
        assert client.model == "gpt-4o"

    def test_llm_client_explicit_model_overrides(self):
        from utils.llm_client import LLMClient
        client = LLMClient(model="gpt-5.2")
        assert client.model == "gpt-5.2"

    def test_llm_client_default_timeout_from_config(self):
        from utils.llm_client import LLMClient
        client = LLMClient()
        assert client.timeout == 300

    def test_llm_client_default_max_retries_from_config(self):
        from utils.llm_client import LLMClient
        client = LLMClient()
        assert client.max_retries == 3
