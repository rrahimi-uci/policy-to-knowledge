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

    def test_entity_prompt_has_bounded_machine_readable_scope(self):
        import agents.agent_2_entity_extractor as a2

        prompt = a2.EntityRelationshipExtractor(
            api_key="sk-dummy"
        ).generate_optimized_prompt(
            documents=[{"path": "section.txt", "content": "Mortgage rules."}]
        )

        normalized_prompt = " ".join(prompt.split())
        assert "10 entity types" in normalized_prompt
        assert "10 relationships" in normalized_prompt

    def test_entity_prompt_uses_substantive_distributed_samples(self):
        import agents.agent_2_entity_extractor as a2

        documents = [
            {"path": "table_of_contents_part_1.txt", "content": "TOC"},
            *[
                {"path": f"part_{index}/section.txt", "content": str(index)}
                for index in range(10)
            ],
        ]
        selected = a2.EntityRelationshipExtractor.select_representative_documents(documents)

        assert len(selected) == 6
        assert all("table_of_contents" not in item["path"] for item in selected)
        assert selected[0]["content"] == "0"
        assert selected[-1]["content"] == "9"

    def test_entity_extraction_failure_is_terminal(self):
        agent = self._agent()
        agent.client = type(
            "FailingClient", (),
            {"chat_completion": lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout"))}
        )()

        with pytest.raises(RuntimeError, match="request failed"):
            agent.extract_entities_and_relationships("prompt")

    def test_entity_catalog_iterations_are_unionable(self):
        import agents.agent_2_entity_extractor as a2

        merged = a2.ComplianceEntityRelationshipAgent.merge_catalogs(
            {"entity_types": {"LENDER": {"attributes": ["name"]}}, "relationships": {}},
            {
                "entity_types": {
                    "LENDER": {"attributes": ["name", "id"]},
                    "BORROWER": {"attributes": ["name"]},
                },
                "relationships": {},
            },
        )
        assert set(merged["entity_types"]) == {"LENDER", "BORROWER"}
        assert merged["entity_types"]["LENDER"]["attributes"] == ["name", "id"]

    def test_entity_catalog_merge_collapses_case_and_punctuation_aliases(self):
        import agents.agent_2_entity_extractor as a2

        merged = a2.ComplianceEntityRelationshipAgent.merge_catalogs(
            {"entity_types": {"FANNIE_MAE": {"attributes": ["id"]}}, "relationships": {}},
            {"entity_types": {"FannieMae": {"attributes": ["name"]}}, "relationships": {}},
        )
        assert list(merged["entity_types"]) == ["FANNIE_MAE"]
        assert merged["entity_types"]["FANNIE_MAE"]["attributes"] == ["id", "name"]

    def test_agent3_retries_transient_request(self, monkeypatch):
        from types import SimpleNamespace
        import agents.agent_3_rules_extractor as a3

        extractor = a3.BusinessRulesExtractor.__new__(a3.BusinessRulesExtractor)
        calls = {"count": 0}

        class _Client:
            def chat_completion(self, **kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise ConnectionError("transient connection failure")
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps({
                        "entity_types": {"LENDER": {"business_rules": [{"rule_id": "r1"}]}},
                        "relationships": {},
                    })
                ))])

        extractor.client = _Client()
        extractor.global_config = SimpleNamespace(
            get_rules_temperature=lambda: 0.0,
            get_rules_max_tokens=lambda: 100,
        )
        extractor.reasoning_effort = "high"
        monkeypatch.setenv("KG_BATCH_MAX_ATTEMPTS", "2")
        monkeypatch.setattr(a3.time, "sleep", lambda _seconds: None)

        result = extractor.extract_batch("prompt", 1)

        assert calls["count"] == 2
        assert result["total_rules"] == 1

    def test_agent3_main_wires_configured_content_limit(self):
        import agents.agent_3_rules_extractor as a3

        source = (Path(a3.__file__)).read_text(encoding="utf-8")
        assert "max_content_length=config.get_rules_max_content_length()" in source

    def test_agent3_uses_compact_prompt(self):
        import agents.agent_3_rules_extractor as a3

        source = Path(a3.__file__).read_text(encoding="utf-8")
        assert '"business_rules_extraction_compact"' in source


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


# ── Bug 6: agent_2's quality-analysis stub returns the wrong key names ─────
#
# run_iterations_with_optimization reads overall_score/entity_quality_score/
# relationship_quality_score/business_rules_score/coverage_score from
# EntityRelationshipExtractor.analyze_extraction_quality's return value —
# the stub instead returned quality_score/completeness/suggestions, so every
# one of those .get(key, 0) reads silently defaulted to 0. On a real
# OPP-115 benchmark run this printed "Overall/Entity/Relationship/Coverage
# Score: 0/100" on every iteration despite genuine, non-empty extraction
# results (6 entities, 9-10 relationships), and permanently disabled the
# `quality_score >= entity_quality_target` early-stop path — the configured
# KG_ENTITY_QUALITY_TARGET could never be satisfied, only the new_items
# diminishing-returns heuristic could ever trigger convergence.

class TestAgent2QualityAnalysisKeys:
    def test_stub_returns_every_key_the_convergence_check_reads(self):
        import agents.agent_2_entity_extractor as a2

        analysis = a2.EntityRelationshipExtractor(api_key="sk-dummy").analyze_extraction_quality(
            extraction_results={"entity_types": {"LENDER": {}}, "relationships": {}},
            iteration=1,
        )

        for key in (
            "overall_score", "entity_quality_score", "relationship_quality_score",
            "business_rules_score", "coverage_score", "improvement_priorities",
        ):
            assert key in analysis, f"missing {key!r} — run_iterations_with_optimization would silently read 0"
        assert analysis["overall_score"] > 0
        assert analysis["entity_quality_score"] > 0
        assert analysis["relationship_quality_score"] > 0

    def test_quality_based_early_stop_can_actually_fire(self, monkeypatch):
        """End-to-end: with the target set at or below the stub's overall_score,
        the quality path (not just new_items) must be able to converge the
        run — proving the read and write sides now genuinely agree."""
        import agents.agent_2_entity_extractor as a2

        monkeypatch.setenv("KG_ENTITY_QUALITY_TARGET", "85")
        monkeypatch.setenv("KG_ENTITY_MIN_ITERATIONS", "1")
        # Every fake iteration below adds one genuinely new entity (new_items=1),
        # so the new_items<=0 path never fires — only the quality path can converge.
        monkeypatch.setenv("KG_ENTITY_MIN_NEW_ITEMS", "0")

        agent = a2.ComplianceEntityRelationshipAgent(api_key="sk-dummy")
        calls = {"count": 0}

        def fake_extract(prompt):
            calls["count"] += 1
            return {"entity_types": {f"ENTITY_{calls['count']}": {}}, "relationships": {}}

        monkeypatch.setattr(agent, "extract_entities_and_relationships", fake_extract)

        agent.run_iterations_with_optimization(documents=[], n_iterations=5)

        assert calls["count"] == 1, "quality_score >= quality_target should have converged after iteration 1"
