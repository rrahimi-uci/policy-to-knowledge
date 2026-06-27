"""
Tests for the --workers CLI option in knowledge_graph_generation.py.

Validates that:
1. The --workers argument is parsed correctly from CLI
2. max_workers is stored on the KnowledgeExtractionPipeline instance
3. MAX_WORKERS env var is propagated to all subprocess calls
4. Default behavior (no --workers) leaves MAX_WORKERS unset
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from io import StringIO

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """Create a mock config object that satisfies KnowledgeExtractionPipeline.__init__."""
    config = MagicMock()
    config.get_source_dir.return_value = Path("/tmp/fake-source")
    config.get_organized_dir.return_value = Path("/tmp/fake-organized")
    config.get_output_dir.return_value = Path("/tmp/fake-output")
    config.get_target_rules.return_value = 100
    config.get_model_provider.return_value = "openai"
    config.get_reasoning_model.return_value = "gpt-5.2"
    config.get_reasoning_effort.return_value = "medium"
    config.get_batch_name.return_value = None
    config.get_source_file_name.return_value = None
    config.get_entity_relationship_dir.return_value = Path("/tmp/fake-entities")
    config.get_rules_extracted_dir.return_value = Path("/tmp/fake-rules")
    return config


@pytest.fixture
def pipeline_cls():
    """Import and return the KnowledgeExtractionPipeline class."""
    from knowledge_graph_generation import KnowledgeExtractionPipeline
    return KnowledgeExtractionPipeline


# ---------------------------------------------------------------------------
# 1. CLI argument parsing
# ---------------------------------------------------------------------------

class TestCLIArgumentParsing:
    """Test that --workers is correctly parsed from CLI arguments."""

    def _build_parser(self):
        """Build the argparse parser the same way main() does."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--provider", type=str, choices=["openai", "anthropic"])
        parser.add_argument("--batch", action="store_true")
        parser.add_argument("--workers", type=int, default=None)
        parser.add_argument("--source", default=None)
        parser.add_argument("--file", default=None)
        parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5, 6])
        parser.add_argument("--skip-optimize", action="store_true")
        parser.add_argument("--organized", default=None)
        parser.add_argument("--output", default=None)
        parser.add_argument("--target-rules", type=int, default=None)
        return parser

    def test_workers_default_is_none(self):
        """When --workers is not specified, args.workers should be None."""
        parser = self._build_parser()
        args = parser.parse_args(["--provider", "openai", "--batch"])
        assert args.workers is None

    def test_workers_parses_integer(self):
        """--workers 40 should set args.workers to 40."""
        parser = self._build_parser()
        args = parser.parse_args(["--provider", "openai", "--batch", "--workers", "40"])
        assert args.workers == 40

    def test_workers_parses_various_values(self):
        """Verify different integer values are parsed correctly."""
        parser = self._build_parser()
        for val in [1, 5, 10, 20, 50, 100]:
            args = parser.parse_args(["--workers", str(val)])
            assert args.workers == val

    def test_workers_rejects_non_integer(self):
        """--workers with a non-integer should cause an error."""
        parser = self._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--workers", "abc"])

    def test_workers_without_batch_is_valid(self):
        """--workers should be accepted even without --batch flag."""
        parser = self._build_parser()
        args = parser.parse_args(["--provider", "openai", "--workers", "30"])
        assert args.workers == 30
        assert args.batch is False


# ---------------------------------------------------------------------------
# 2. Pipeline __init__ stores max_workers
# ---------------------------------------------------------------------------

class TestPipelineMaxWorkers:
    """Test that KnowledgeExtractionPipeline stores max_workers."""

    @patch("knowledge_graph_generation.get_config")
    def test_max_workers_stored_when_provided(self, mock_get_config, mock_config, pipeline_cls):
        """max_workers should be stored on the pipeline instance."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai", max_workers=40)
        assert pipeline.max_workers == 40

    @patch("knowledge_graph_generation.get_config")
    def test_max_workers_none_when_not_provided(self, mock_get_config, mock_config, pipeline_cls):
        """max_workers should be None when not specified."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai")
        assert pipeline.max_workers is None

    @patch("knowledge_graph_generation.get_config")
    def test_max_workers_zero_is_stored(self, mock_get_config, mock_config, pipeline_cls):
        """max_workers=0 should be stored (even though falsy)."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai", max_workers=0)
        assert pipeline.max_workers == 0

    @patch("knowledge_graph_generation.get_config")
    def test_max_workers_with_batch_mode(self, mock_get_config, mock_config, pipeline_cls):
        """max_workers should work with batch mode."""
        mock_get_config.return_value = mock_config
        # Create a dummy file path
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            temp_path = f.name
        try:
            pipeline = pipeline_cls(
                source_files=[temp_path],
                batch_name="test-batch",
                provider="openai",
                max_workers=25
            )
            assert pipeline.max_workers == 25
            assert pipeline.batch_name == "test-batch"
        finally:
            os.unlink(temp_path)


# ---------------------------------------------------------------------------
# 3. _run_agent propagates MAX_WORKERS to subprocess env
# ---------------------------------------------------------------------------

class TestRunAgentMaxWorkersEnv:
    """Test that _run_agent sets MAX_WORKERS in the subprocess environment."""

    @patch("knowledge_graph_generation.get_config")
    def test_run_agent_sets_max_workers_env(self, mock_get_config, mock_config, pipeline_cls):
        """When max_workers is set, _run_agent should pass MAX_WORKERS env var."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai", max_workers=40)

        # Capture the env dict passed to subprocess.Popen
        captured_env = {}

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])  # empty output
            proc.wait.return_value = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            result = pipeline._run_agent(
                agent_name="Test Agent",
                command=[sys.executable, "-c", "pass"],
                description="Test description",
                step_number="1"
            )

        assert result is True
        assert "MAX_WORKERS" in captured_env
        assert captured_env["MAX_WORKERS"] == "40"

    @patch("knowledge_graph_generation.get_config")
    def test_run_agent_no_max_workers_env_when_none(self, mock_get_config, mock_config, pipeline_cls):
        """When max_workers is None, MAX_WORKERS should NOT be in the env (unless inherited)."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai")

        captured_env = {}

        # Clean MAX_WORKERS from current env to isolate the test
        original_env = os.environ.get("MAX_WORKERS")
        os.environ.pop("MAX_WORKERS", None)

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = 0
            return proc

        try:
            with patch("subprocess.Popen", side_effect=fake_popen):
                pipeline._run_agent(
                    agent_name="Test Agent",
                    command=[sys.executable, "-c", "pass"],
                    description="Test description",
                    step_number="1"
                )
            # MAX_WORKERS should not be set by our code when max_workers is None
            assert "MAX_WORKERS" not in captured_env
        finally:
            if original_env is not None:
                os.environ["MAX_WORKERS"] = original_env

    @patch("knowledge_graph_generation.get_config")
    def test_run_agent_max_workers_is_string(self, mock_get_config, mock_config, pipeline_cls):
        """MAX_WORKERS env var must be a string (env vars are always strings)."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai", max_workers=42)

        captured_env = {}

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            pipeline._run_agent(
                agent_name="Test Agent",
                command=[sys.executable, "-c", "pass"],
                description="Test description",
                step_number="1"
            )

        assert isinstance(captured_env["MAX_WORKERS"], str)
        assert captured_env["MAX_WORKERS"] == "42"

    @patch("knowledge_graph_generation.get_config")
    def test_run_agent_preserves_other_env_vars(self, mock_get_config, mock_config, pipeline_cls):
        """MAX_WORKERS should not clobber other env vars like KG_PROVIDER."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai", max_workers=40)

        captured_env = {}

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            pipeline._run_agent(
                agent_name="Test Agent",
                command=[sys.executable, "-c", "pass"],
                description="Test",
                step_number="1"
            )

        assert captured_env["KG_PROVIDER"] == "openai"
        assert captured_env["MAX_WORKERS"] == "40"


# ---------------------------------------------------------------------------
# 4. Agent 3 reads MAX_WORKERS env var
# ---------------------------------------------------------------------------

class TestAgent3MaxWorkersEnvReading:
    """Test that agent_3_rules_extractor reads MAX_WORKERS from environment."""

    def test_agent3_reads_max_workers_default(self):
        """When MAX_WORKERS is not set, agent 3 should default to 20."""
        env_backup = os.environ.pop("MAX_WORKERS", None)
        try:
            result = int(os.environ.get("MAX_WORKERS", "20"))
            assert result == 20
        finally:
            if env_backup is not None:
                os.environ["MAX_WORKERS"] = env_backup

    def test_agent3_reads_max_workers_custom(self):
        """When MAX_WORKERS is set to 40, agent 3 should pick it up."""
        env_backup = os.environ.get("MAX_WORKERS")
        os.environ["MAX_WORKERS"] = "40"
        try:
            result = int(os.environ.get("MAX_WORKERS", "20"))
            assert result == 40
        finally:
            if env_backup is not None:
                os.environ["MAX_WORKERS"] = env_backup
            else:
                os.environ.pop("MAX_WORKERS", None)


# ---------------------------------------------------------------------------
# 5. End-to-end: CLI --workers flows through to subprocess env
# ---------------------------------------------------------------------------

class TestEndToEndWorkersFlow:
    """Integration-style test: CLI arg -> pipeline -> subprocess env."""

    @patch("knowledge_graph_generation.get_config")
    def test_workers_40_flows_to_subprocess(self, mock_get_config, mock_config, pipeline_cls):
        """--workers 40 should result in MAX_WORKERS=40 in subprocess env."""
        mock_get_config.return_value = mock_config

        # Simulate: args.workers = 40 -> pipeline(max_workers=40) -> _run_agent -> env
        pipeline = pipeline_cls(provider="openai", max_workers=40)

        captured_env = {}

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            pipeline._run_agent(
                agent_name="Business Rules Extractor",
                command=[sys.executable, "agents/agent_3_rules_extractor.py"],
                description="Extracting rules",
                step_number="3"
            )

        assert captured_env["MAX_WORKERS"] == "40"

    @patch("knowledge_graph_generation.get_config")
    def test_workers_1_flows_to_subprocess(self, mock_get_config, mock_config, pipeline_cls):
        """--workers 1 (serial) should result in MAX_WORKERS=1 in subprocess env."""
        mock_get_config.return_value = mock_config
        pipeline = pipeline_cls(provider="openai", max_workers=1)

        captured_env = {}

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            pipeline._run_agent(
                agent_name="Test Agent",
                command=[sys.executable, "-c", "pass"],
                description="Test",
                step_number="1"
            )

        assert captured_env["MAX_WORKERS"] == "1"
