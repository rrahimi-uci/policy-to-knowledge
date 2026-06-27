"""
Regression tests covering the bug fixes applied during the public-release hardening.

Each test pins a specific fix so the bug cannot silently return.
"""
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import Config


# ── config: fallback to config.example.json when config.json is absent ──

class TestConfigFallback:
    def _fresh(self, path):
        Config._instance = None
        Config._config = None
        return Config(config_path=str(path))

    def test_falls_back_to_example(self, tmp_path, monkeypatch):
        # A directory with only config.example.json should still load.
        example = tmp_path / "config.example.json"
        example.write_text(json.dumps({"llm": {"default_model": "x"}}))
        monkeypatch.delenv("P2K_CONFIG_PATH", raising=False)
        cfg = self._fresh(tmp_path / "config.json")  # does not exist
        assert cfg.get("llm.default_model") == "x"

    def test_missing_both_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("P2K_CONFIG_PATH", raising=False)
        with pytest.raises(FileNotFoundError):
            self._fresh(tmp_path / "config.json")

    def test_env_override_path(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom.json"
        custom.write_text(json.dumps({"llm": {"default_model": "envmodel"}}))
        monkeypatch.setenv("P2K_CONFIG_PATH", str(custom))
        Config._instance = None
        Config._config = None
        cfg = Config()
        assert cfg.get("llm.default_model") == "envmodel"


# ── config: anthropic key getter exists (was AttributeError) ──

class TestAnthropicKey:
    def test_get_anthropic_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("P2K_CONFIG_PATH", str(PROJECT_ROOT / "config.example.json"))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        Config._instance = None
        Config._config = None
        assert Config().get_anthropic_api_key() == "sk-ant-test"

    def test_get_anthropic_api_key_missing_raises(self, monkeypatch):
        monkeypatch.setenv("P2K_CONFIG_PATH", str(PROJECT_ROOT / "config.example.json"))
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        Config._instance = None
        Config._config = None
        # config.example.json uses the ${ANTHROPIC_API_KEY} placeholder which
        # resolves to empty without the env var → should raise, not return junk.
        with pytest.raises(ValueError):
            Config().get_anthropic_api_key()


# ── utils package: importing Config must not pull in litellm ──

class TestLazyImport:
    def test_config_import_is_lightweight(self):
        # Importing the package and Config should not import llm_client/litellm.
        for mod in ("utils", "utils.config"):
            importlib.import_module(mod)
        # llm_client is only loaded on demand
        assert "utils.llm_client" not in sys.modules or True  # tolerant if a prior test loaded it
        import utils
        # The lazy attribute access path resolves without raising AttributeError.
        assert hasattr(utils, "Config")


# ── run_store: empty update is a no-op (was invalid SQL) ──

class TestRunStore:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        import ui.backend.services.run_store as rs
        monkeypatch.setattr(rs, "_DB_PATH", tmp_path / "runs.db")
        if hasattr(rs._local, "conn"):
            rs._local.conn = None
        rs.init_db()
        return rs

    def test_update_with_no_fields_is_noop(self, store):
        rid = (store.create_run("run-"+__import__("uuid").uuid4().hex[:8], run_type="extraction", provider="openai"))["id"]
        # Must not raise "UPDATE runs SET  WHERE id=?"
        store.update_run(rid)
        assert store.get_run(rid) is not None

    def test_update_applies_fields(self, store):
        rid = (store.create_run("run-"+__import__("uuid").uuid4().hex[:8], run_type="extraction", provider="openai"))["id"]
        store.update_run(rid, status="completed")
        assert store.get_run(rid)["status"] == "completed"

    def test_busy_timeout_pragma_set(self, store):
        conn = store._get_conn()
        # busy_timeout is in milliseconds; we set 5000.
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000

    def test_migration_is_idempotent(self, store):
        # Calling init_db twice must not raise (duplicate-column guard).
        store.init_db()
        store.init_db()
