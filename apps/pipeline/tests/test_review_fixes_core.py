"""
Regression tests for the core pipeline review fixes.

Each test pins a specific confirmed bug so it cannot silently return:

1. agent_8: LLM client must receive the real OpenAI key (config getter), not None.
2. safe_json_for_html: inline-<script> JSON must never contain a literal </script>.
3. agent_10 generate_summary_html: a partial all_results must not raise KeyError.
4. agent_2 run_iterations_with_optimization: n_iterations < 1 must raise ValueError.
5. agent_1 resolve_output_folder: an option-like argv[2] (e.g. --files) is ignored.
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Bug 1: agent_8 passes the configured OpenAI key, not None ──────────────

class TestAgent8ApiKey:
    def test_llm_client_gets_config_key(self, monkeypatch):
        import agents.agent_8_semantic_rule_matcher as a8

        # No env key; the key must come from config (openai.api_key).
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        captured = {}

        def fake_create_llm_client(api_key=None, model=None, **kwargs):
            captured["api_key"] = api_key
            return object()

        monkeypatch.setattr(a8, "create_llm_client", fake_create_llm_client)

        matcher = a8.SemanticRuleMatcher.__new__(a8.SemanticRuleMatcher)

        class _Cfg:
            def get_openai_api_key(self):
                return "sk-config-key-123"

            def get_reasoning_model(self):
                return "test-model"

            # The old buggy path: returns None for a dotted key via flat get().
            def get(self, key, default=None):
                return default

        matcher.config = _Cfg()

        import threading
        matcher._thread_local = threading.local()
        monkeypatch.setattr(a8, "get_config", lambda: _Cfg())

        matcher._get_llm_client()

        assert captured["api_key"] == "sk-config-key-123"
        assert captured["api_key"] is not None


# ── Bug 2: safe_json_for_html escapes inline-<script> terminators ──────────

class TestSafeJsonForHtml:
    def test_no_literal_script_close(self):
        from utils.text_to_html_converter import safe_json_for_html

        payload = {"x": "</script><script>alert(1)</script>"}
        out = safe_json_for_html(payload)

        assert "</script>" not in out
        assert "</" not in out  # no '<' survives unescaped

    def test_round_trips_to_input(self):
        from utils.text_to_html_converter import safe_json_for_html

        payload = {"x": "</script>", "y": ["<a>", "b < c"], "n": 3}
        out = safe_json_for_html(payload)

        # JSON parsers treat < as '<', so it parses back to the original.
        assert json.loads(out) == payload


# ── Bug 3: agent_10 summary survives a partial all_results ─────────────────

class TestAgent10SummaryPartial:
    def _matcher(self):
        import agents.agent_10_set_visualization as a10
        m = a10.SetOperationsVisualizer.__new__(a10.SetOperationsVisualizer)
        # generate_summary_html references a couple of presentation helpers.
        m._get_common_styles = lambda: ""
        m._get_logo_base64 = lambda: ""
        return m

    def test_empty_results_no_crash(self):
        m = self._matcher()
        html = m.generate_summary_html({})
        assert isinstance(html, str)
        assert "Knowledge Graph Merge Summary" in html

    def test_only_union_present_no_crash(self):
        m = self._matcher()
        partial = {
            "union": {
                "metadata": {"g1_name": "Alpha", "g2_name": "Beta"},
                "stats": {"total_rules": 7},
            }
        }
        html = m.generate_summary_html(partial)
        assert isinstance(html, str)
        assert "Alpha" in html and "Beta" in html
        assert ">7<" in html  # union total rendered


# ── Bug 4: agent_2 rejects n_iterations < 1 ────────────────────────────────

class TestAgent2Iterations:
    def _agent(self):
        import agents.agent_2_entity_extractor as a2
        # Construction is lazy w.r.t. the LLM client, so a dummy key is fine.
        return a2.ComplianceEntityRelationshipAgent(api_key="sk-dummy")

    def test_zero_iterations_raises(self):
        agent = self._agent()
        with pytest.raises(ValueError):
            agent.run_iterations_with_optimization(documents=[], n_iterations=0)

    def test_negative_iterations_raises(self):
        agent = self._agent()
        with pytest.raises(ValueError):
            agent.run_iterations_with_optimization(documents=[], n_iterations=-1)


# ── Bug 5: agent_1 ignores an option-like positional output arg ────────────

class TestAgent1OutputFolder:
    def test_files_option_is_not_output_folder(self):
        from agents.agent_1_document_organizer import resolve_output_folder

        argv = ["agent_1.py", "input-folder", "--files", "a.pdf", "b.pdf"]
        assert resolve_output_folder(argv) == "knowledge-files-organized"

    def test_real_output_folder_used(self):
        from agents.agent_1_document_organizer import resolve_output_folder

        argv = ["agent_1.py", "input-folder", "out-dir", "--files", "a.pdf"]
        assert resolve_output_folder(argv) == "out-dir"

    def test_default_when_absent(self):
        from agents.agent_1_document_organizer import resolve_output_folder

        assert resolve_output_folder(["agent_1.py", "input-folder"]) == "knowledge-files-organized"
