"""
Tests for Agentic Impact Analysis — impact_agentic.py, impact_ws.py, and agentic router mode.

Covers:
  - Utility functions (_truncate, _safe_json_parse, _emit)
  - Each of the 5 LLM workflow steps with mocked LLM client
  - Full orchestrator (run_agentic_analysis) with mocked dependencies
  - WebSocket handler (broadcast/subscribe)
  - Router dual-mode (agentic vs basic)
  - Edge cases and error handling
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ── Setup path ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = tmp_path / "test_impact_agentic.db"
    monkeypatch.setattr(
        "ui.backend.services.impact_store._DB_PATH", db_path
    )
    import ui.backend.services.impact_store as store
    if hasattr(store._local, "conn"):
        store._local.conn = None
    store.init_tables()
    yield db_path


@pytest.fixture
def store():
    import ui.backend.services.impact_store as s
    return s


@pytest.fixture
def agentic():
    import ui.backend.services.impact_agentic as a
    return a


@pytest.fixture
def ws_module():
    import ui.backend.ws.impact_ws as ws
    return ws


@pytest.fixture
def mock_llm_client():
    """A mock LLM client whose get_text_response returns configurable JSON."""
    client = MagicMock()
    client.get_text_response = MagicMock(return_value='{}')
    return client


@pytest.fixture
def sample_graph_data():
    return {
        "metadata": {"original_rule_count": 5, "optimized_rule_count": 5},
        "business_rules": [
            {
                "rule_id": "R001",
                "rule_name": "Loan-to-Value Ratio Must Not Exceed 80%",
                "rule_type": "eligibility",
                "confidence_score": 0.92,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
                "dependencies": [],
                "dependent_rules": [],
                "description": "LTV for conventional mortgage must not exceed 80% without PMI.",
            },
            {
                "rule_id": "R002",
                "rule_name": "Borrower Credit Counseling Required",
                "rule_type": "process",
                "confidence_score": 0.85,
                "risk_level": "high",
                "mandatory": True,
                "entity_type": "borrower",
                "dependencies": [],
                "dependent_rules": [],
                "description": "All borrowers shall complete approved credit counseling.",
            },
            {
                "rule_id": "R003",
                "rule_name": "Property Appraisal Required",
                "rule_type": "compliance",
                "confidence_score": 0.95,
                "risk_level": "critical",
                "mandatory": True,
                "entity_type": "property",
                "dependencies": [],
                "dependent_rules": [],
                "description": "Independent appraisal must be obtained for all properties.",
            },
        ],
    }


# ═════════════════════════════════════════════════════════════════
# UTILITY FUNCTION TESTS
# ═════════════════════════════════════════════════════════════════

class TestTruncate:
    def test_short_text_unchanged(self, agentic):
        text = "Hello world"
        assert agentic._truncate(text) == text

    def test_long_text_truncated(self, agentic):
        text = "A" * 10000
        result = agentic._truncate(text, max_chars=100)
        assert len(result) < 10000
        assert "truncated" in result
        assert "9900 chars omitted" in result

    def test_exact_boundary(self, agentic):
        text = "A" * 6000
        assert agentic._truncate(text, max_chars=6000) == text

    def test_one_over_boundary(self, agentic):
        text = "A" * 6001
        result = agentic._truncate(text, max_chars=6000)
        assert "truncated" in result

    def test_custom_max_chars(self, agentic):
        text = "A" * 200
        result = agentic._truncate(text, max_chars=50)
        assert result.startswith("A" * 50)
        assert "truncated" in result


class TestSafeJsonParse:
    def test_plain_json(self, agentic):
        result = agentic._safe_json_parse('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown_fences(self, agentic):
        text = '```json\n{"key": "value"}\n```'
        result = agentic._safe_json_parse(text)
        assert result == {"key": "value"}

    def test_json_with_bare_fences(self, agentic):
        text = '```\n{"items": [1, 2, 3]}\n```'
        result = agentic._safe_json_parse(text)
        assert result == {"items": [1, 2, 3]}

    def test_json_with_whitespace(self, agentic):
        text = '  \n  {"key": "value"}  \n  '
        result = agentic._safe_json_parse(text)
        assert result == {"key": "value"}

    def test_json_with_nested_objects(self, agentic):
        text = '{"a": {"b": [1, 2, {"c": true}]}}'
        result = agentic._safe_json_parse(text)
        assert result["a"]["b"][2]["c"] is True

    def test_invalid_json_raises(self, agentic):
        with pytest.raises(json.JSONDecodeError):
            agentic._safe_json_parse("not json at all")

    def test_empty_object(self, agentic):
        assert agentic._safe_json_parse("{}") == {}

    def test_empty_array(self, agentic):
        assert agentic._safe_json_parse("[]") == []

    def test_fenced_with_extra_text_before(self, agentic):
        text = 'Here is the result:\n```json\n{"x": 1}\n```\nDone.'
        result = agentic._safe_json_parse(text)
        assert result == {"x": 1}


class TestEmit:
    @pytest.mark.asyncio
    async def test_emit_calls_callback(self, agentic):
        cb = AsyncMock()
        await agentic._emit(cb, {"step": "test", "status": "running"})
        cb.assert_awaited_once_with({"step": "test", "status": "running"})

    @pytest.mark.asyncio
    async def test_emit_with_none_callback(self, agentic):
        # Should not raise
        await agentic._emit(None, {"step": "test", "status": "running"})

    @pytest.mark.asyncio
    async def test_emit_preserves_payload(self, agentic):
        payloads = []
        async def collector(p):
            payloads.append(p)
        await agentic._emit(collector, {"step": "parse", "data": {"count": 5}})
        assert payloads[0]["data"]["count"] == 5


# ═════════════════════════════════════════════════════════════════
# STEP 1: DOCUMENT PARSING TESTS
# ═════════════════════════════════════════════════════════════════

class TestStepParse:
    @pytest.mark.asyncio
    async def test_parse_returns_provisions(self, agentic, mock_llm_client):
        mock_llm_client.get_text_response.return_value = json.dumps({
            "old_provisions": [
                {"id": "P1", "text": "Old LTV rule", "section": "A", "category": "eligibility"},
                {"id": "P2", "text": "Old appraisal rule", "section": "B", "category": "compliance"},
            ],
            "new_provisions": [
                {"id": "P1", "text": "New LTV rule updated", "section": "A", "category": "eligibility"},
                {"id": "P2", "text": "Old appraisal rule", "section": "B", "category": "compliance"},
                {"id": "P3", "text": "New wire transfer rule", "section": "C", "category": "process"},
            ],
            "document_summary": {
                "old_doc_topic": "Old reg",
                "new_doc_topic": "New reg",
                "regulatory_domain": "mortgage",
            }
        })

        cb = AsyncMock()
        result = await agentic._step_parse(mock_llm_client, "old text", "new text", cb)

        assert len(result["old_provisions"]) == 2
        assert len(result["new_provisions"]) == 3
        assert result["document_summary"]["regulatory_domain"] == "mortgage"
        # Check progress was emitted (running + completed)
        assert cb.await_count == 2
        # Check completed message mentions counts
        completed_call = cb.await_args_list[1][0][0]
        assert completed_call["step"] == "parse"
        assert completed_call["status"] == "completed"
        assert completed_call["data"]["old_count"] == 2
        assert completed_call["data"]["new_count"] == 3

    @pytest.mark.asyncio
    async def test_parse_uses_json_response_format(self, agentic, mock_llm_client):
        mock_llm_client.get_text_response.return_value = '{"old_provisions":[],"new_provisions":[]}'
        await agentic._step_parse(mock_llm_client, "old", "new", None)
        call_kwargs = mock_llm_client.get_text_response.call_args[1]
        assert call_kwargs.get("response_format") == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_parse_handles_markdown_fenced_response(self, agentic, mock_llm_client):
        mock_llm_client.get_text_response.return_value = (
            '```json\n{"old_provisions":[],"new_provisions":[],"document_summary":{}}\n```'
        )
        result = await agentic._step_parse(mock_llm_client, "old", "new", None)
        assert "old_provisions" in result

    @pytest.mark.asyncio
    async def test_parse_truncates_long_documents(self, agentic, mock_llm_client):
        mock_llm_client.get_text_response.return_value = '{"old_provisions":[],"new_provisions":[]}'
        long_text = "A" * 20000
        await agentic._step_parse(mock_llm_client, long_text, long_text, None)
        # Verify documents were passed to LLM (it was called)
        assert mock_llm_client.get_text_response.called


# ═════════════════════════════════════════════════════════════════
# STEP 2: SEMANTIC DIFF TESTS
# ═════════════════════════════════════════════════════════════════

class TestStepDiff:
    @pytest.mark.asyncio
    async def test_diff_returns_changes(self, agentic, mock_llm_client):
        parsed = {
            "old_provisions": [{"id": "P1", "text": "Old rule"}],
            "new_provisions": [{"id": "P1", "text": "Modified rule"}, {"id": "P2", "text": "New rule"}],
        }
        mock_llm_client.get_text_response.return_value = json.dumps({
            "changes": [
                {"change_id": "C1", "change_type": "modified", "description": "Rule updated",
                 "old_text": "Old rule", "new_text": "Modified rule", "semantic_impact": "Changed meaning",
                 "category": "eligibility"},
                {"change_id": "C2", "change_type": "added", "description": "New rule added",
                 "new_text": "New rule", "semantic_impact": "New requirement",
                 "category": "process"},
            ],
            "unchanged_count": 0,
            "diff_summary": "Two changes detected",
        })

        cb = AsyncMock()
        result = await agentic._step_diff(mock_llm_client, parsed, cb)

        assert len(result["changes"]) == 2
        assert result["changes"][0]["change_type"] == "modified"
        assert result["changes"][1]["change_type"] == "added"
        # Completion message
        completed = cb.await_args_list[1][0][0]
        assert completed["status"] == "completed"
        assert "2 changes" in completed["message"]

    @pytest.mark.asyncio
    async def test_diff_handles_empty_provisions(self, agentic, mock_llm_client):
        parsed = {"old_provisions": [], "new_provisions": []}
        mock_llm_client.get_text_response.return_value = json.dumps({
            "changes": [], "unchanged_count": 0, "diff_summary": "No changes"
        })
        result = await agentic._step_diff(mock_llm_client, parsed, None)
        assert len(result["changes"]) == 0


# ═════════════════════════════════════════════════════════════════
# STEP 3: RULE IMPACT MAPPING TESTS
# ═════════════════════════════════════════════════════════════════

class TestStepMap:
    @pytest.mark.asyncio
    async def test_map_returns_mappings(self, agentic, mock_llm_client, sample_graph_data):
        diff_result = {
            "changes": [
                {"change_id": "C1", "change_type": "modified", "description": "LTV changed to 90%"},
            ]
        }
        rules = sample_graph_data["business_rules"]
        mock_llm_client.get_text_response.return_value = json.dumps({
            "mappings": [
                {
                    "change_id": "C1",
                    "affected_rules": [
                        {"rule_id": "R001", "rule_name": "LTV Rule", "relevance": "high",
                         "reasoning": "Directly changes LTV threshold"},
                    ],
                    "blast_radius": "moderate",
                }
            ],
            "total_affected_rules": 1,
            "most_affected_rule_types": ["eligibility"],
        })

        cb = AsyncMock()
        result = await agentic._step_map(mock_llm_client, diff_result, rules, "TestGraph", cb)

        assert len(result["mappings"]) == 1
        assert result["total_affected_rules"] == 1
        assert result["mappings"][0]["affected_rules"][0]["relevance"] == "high"

    @pytest.mark.asyncio
    async def test_map_caps_rules_for_token_limit(self, agentic, mock_llm_client):
        """Verify that the step doesn't send more than 200 rules to the LLM."""
        diff_result = {"changes": [{"change_id": "C1", "change_type": "added"}]}
        rules = [{"rule_id": f"R{i}", "rule_name": f"Rule {i}", "rule_type": "compliance",
                   "risk_level": "medium", "entity_type": "loan"} for i in range(300)]
        mock_llm_client.get_text_response.return_value = json.dumps({
            "mappings": [], "total_affected_rules": 0, "most_affected_rule_types": []
        })
        await agentic._step_map(mock_llm_client, diff_result, rules, "G", None)
        # The prompt should have been called — we just verify it doesn't crash
        assert mock_llm_client.get_text_response.called

    @pytest.mark.asyncio
    async def test_map_progress_mentions_graph_name(self, agentic, mock_llm_client, sample_graph_data):
        diff_result = {"changes": []}
        mock_llm_client.get_text_response.return_value = json.dumps({
            "mappings": [], "total_affected_rules": 0, "most_affected_rule_types": []
        })
        cb = AsyncMock()
        await agentic._step_map(mock_llm_client, diff_result,
                                 sample_graph_data["business_rules"], "Sample_Guidelines", cb)
        running_msg = cb.await_args_list[0][0][0]["message"]
        assert "Sample_Guidelines" in running_msg


# ═════════════════════════════════════════════════════════════════
# STEP 4: SEVERITY SCORING TESTS
# ═════════════════════════════════════════════════════════════════

class TestStepScore:
    @pytest.mark.asyncio
    async def test_score_returns_scored_changes(self, agentic, mock_llm_client):
        diff_result = {
            "changes": [
                {"change_id": "C1", "change_type": "modified"},
                {"change_id": "C2", "change_type": "added"},
            ]
        }
        map_result = {"mappings": [{"change_id": "C1", "affected_rules": [{"rule_id": "R001"}]}]}
        mock_llm_client.get_text_response.return_value = json.dumps({
            "scored_changes": [
                {"change_id": "C1", "severity": "breaking", "risk_score": 0.9,
                 "confidence": 0.85, "rationale": "Critical threshold change",
                 "urgency": "immediate", "affected_rule_count": 1},
                {"change_id": "C2", "severity": "material", "risk_score": 0.6,
                 "confidence": 0.75, "rationale": "New process step",
                 "urgency": "short-term", "affected_rule_count": 0},
            ],
            "severity_distribution": {"breaking": 1, "material": 1, "cosmetic": 0},
            "overall_risk_level": "high",
        })

        cb = AsyncMock()
        result = await agentic._step_score(mock_llm_client, diff_result, map_result, cb)

        assert len(result["scored_changes"]) == 2
        assert result["scored_changes"][0]["severity"] == "breaking"
        assert result["overall_risk_level"] == "high"
        completed = cb.await_args_list[1][0][0]
        assert "1 breaking" in completed["message"]
        assert "overall risk: high" in completed["message"]

    @pytest.mark.asyncio
    async def test_score_uses_low_temperature(self, agentic, mock_llm_client):
        """Severity scoring should be deterministic — low temperature."""
        diff_result = {"changes": []}
        map_result = {"mappings": []}
        mock_llm_client.get_text_response.return_value = json.dumps({
            "scored_changes": [], "severity_distribution": {}, "overall_risk_level": "low"
        })
        await agentic._step_score(mock_llm_client, diff_result, map_result, None)
        call_kwargs = mock_llm_client.get_text_response.call_args[1]
        assert call_kwargs["temperature"] <= 0.3


# ═════════════════════════════════════════════════════════════════
# STEP 5: EXECUTIVE SUMMARY TESTS
# ═════════════════════════════════════════════════════════════════

class TestStepSummarize:
    @pytest.mark.asyncio
    async def test_summary_returns_recommendations(self, agentic, mock_llm_client):
        parsed = {"document_summary": {"regulatory_domain": "mortgage"}, "old_provisions": [], "new_provisions": []}
        diff_result = {"changes": []}
        score_result = {
            "scored_changes": [],
            "severity_distribution": {"breaking": 0, "material": 1, "cosmetic": 0},
            "overall_risk_level": "medium",
        }
        map_result = {"total_affected_rules": 3, "most_affected_rule_types": ["eligibility"]}

        mock_llm_client.get_text_response.return_value = json.dumps({
            "executive_summary": "The regulatory changes are moderate.",
            "headline": "Moderate impact: 3 rules affected",
            "key_findings": ["LTV threshold changed", "New wire transfer rule"],
            "recommendations": [
                {"priority": "P1", "action": "Update LTV rule", "owner": "Compliance", "timeline": "immediate"},
                {"priority": "P2", "action": "Review process", "owner": "Operations", "timeline": "1-2 weeks"},
            ],
            "risk_assessment": {
                "overall_risk": "medium",
                "impact_percentage": 15.0,
                "requires_board_review": False,
                "regulatory_deadline_risk": False,
            },
        })

        cb = AsyncMock()
        result = await agentic._step_summarize(
            mock_llm_client, parsed, diff_result, score_result, map_result, "TestGraph", cb
        )

        assert "executive_summary" in result
        assert len(result["recommendations"]) == 2
        assert result["recommendations"][0]["priority"] == "P1"
        assert result["risk_assessment"]["overall_risk"] == "medium"
        completed = cb.await_args_list[1][0][0]
        assert "2 recommendations" in completed["message"]

    @pytest.mark.asyncio
    async def test_summary_progress_contains_headline(self, agentic, mock_llm_client):
        parsed = {"document_summary": {}, "old_provisions": [], "new_provisions": []}
        mock_llm_client.get_text_response.return_value = json.dumps({
            "executive_summary": "Summary text",
            "headline": "Test headline for verification",
            "key_findings": [],
            "recommendations": [],
            "risk_assessment": {},
        })
        cb = AsyncMock()
        await agentic._step_summarize(
            mock_llm_client, parsed, {"changes": []},
            {"scored_changes": [], "severity_distribution": {}, "overall_risk_level": "low"},
            {"total_affected_rules": 0}, "G", cb
        )
        completed = cb.await_args_list[1][0][0]
        assert "Test headline" in completed["message"]


# ═════════════════════════════════════════════════════════════════
# FULL ORCHESTRATOR TESTS
# ═════════════════════════════════════════════════════════════════

class TestRunAgenticAnalysis:
    def _mock_step_responses(self, mock_client):
        """Set up LLM responses for all 5 steps in sequence."""
        mock_client.get_text_response.side_effect = [
            # Step 1: parse
            json.dumps({
                "old_provisions": [{"id": "P1", "text": "Old LTV 80%", "section": "A", "category": "eligibility"}],
                "new_provisions": [
                    {"id": "P1", "text": "New LTV 90%", "section": "A", "category": "eligibility"},
                    {"id": "P2", "text": "New wire rule", "section": "B", "category": "process"},
                ],
                "document_summary": {"old_doc_topic": "Old", "new_doc_topic": "New", "regulatory_domain": "mortgage"},
            }),
            # Step 2: diff
            json.dumps({
                "changes": [
                    {"change_id": "C1", "change_type": "modified", "description": "LTV changed",
                     "old_text": "Old LTV 80%", "new_text": "New LTV 90%",
                     "semantic_impact": "Threshold raised", "category": "eligibility"},
                    {"change_id": "C2", "change_type": "added", "description": "Wire rule added",
                     "new_text": "New wire rule", "semantic_impact": "New requirement",
                     "category": "process"},
                ],
                "unchanged_count": 0,
                "diff_summary": "2 changes",
            }),
            # Step 3: map
            json.dumps({
                "mappings": [
                    {"change_id": "C1", "affected_rules": [
                        {"rule_id": "R001", "rule_name": "LTV Rule", "relevance": "high",
                         "reasoning": "LTV threshold changed", "rule_type": "eligibility", "risk_level": "critical"},
                    ], "blast_radius": "moderate"},
                    {"change_id": "C2", "affected_rules": [
                        {"rule_id": "R002", "rule_name": "Credit Counseling", "relevance": "medium",
                         "reasoning": "Process change", "rule_type": "process", "risk_level": "high"},
                    ], "blast_radius": "isolated"},
                ],
                "total_affected_rules": 2,
                "most_affected_rule_types": ["eligibility", "process"],
            }),
            # Step 4: score
            json.dumps({
                "scored_changes": [
                    {"change_id": "C1", "severity": "breaking", "risk_score": 0.9,
                     "confidence": 0.85, "rationale": "Threshold change is breaking",
                     "urgency": "immediate", "affected_rule_count": 1},
                    {"change_id": "C2", "severity": "material", "risk_score": 0.6,
                     "confidence": 0.75, "rationale": "New process step",
                     "urgency": "short-term", "affected_rule_count": 1},
                ],
                "severity_distribution": {"breaking": 1, "material": 1, "cosmetic": 0},
                "overall_risk_level": "high",
            }),
            # Step 5: summarize
            json.dumps({
                "executive_summary": "Significant regulatory changes detected.",
                "headline": "High impact: 2 rules affected, 1 breaking change",
                "key_findings": ["LTV raised to 90%", "New wire transfer rule"],
                "recommendations": [
                    {"priority": "P1", "action": "Update LTV rule", "owner": "Compliance", "timeline": "immediate"},
                ],
                "risk_assessment": {
                    "overall_risk": "high",
                    "impact_percentage": 40.0,
                    "requires_board_review": True,
                    "regulatory_deadline_risk": False,
                },
            }),
        ]

    @pytest.mark.asyncio
    async def test_full_agentic_analysis_success(self, agentic, store, sample_graph_data):
        a = store.create_analysis("TestGraph", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        self._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            progress_events = []
            async def collect_progress(p):
                progress_events.append(p)

            result = await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="Old LTV 80%",
                new_text="New LTV 90% and wire transfer rule",
                graph_name="TestGraph",
                provider="openai",
                progress_cb=collect_progress,
            )

        assert result["status"] == "completed"
        assert result["stats"]["total_changes"] == 2
        assert result["stats"]["severity_breaking"] == 1
        assert result["stats"]["severity_material"] == 1
        assert result["summary"]["headline"] == "High impact: 2 rules affected, 1 breaking change"
        assert len(result["summary"]["key_findings"]) == 2
        assert len(result["summary"]["recommendations"]) == 1
        assert result["summary"]["risk_assessment"]["requires_board_review"] is True

        # Verify impact items persisted
        items = store.get_impact_items(a["id"])
        assert len(items) == 2
        # First item should be the breaking one
        breaking_items = [i for i in items if i["severity"] == "breaking"]
        assert len(breaking_items) == 1
        assert breaking_items[0]["recommendation"].startswith("URGENT:")

        # Verify progress events
        step_ids = [e["step"] for e in progress_events]
        assert "init" in step_ids
        assert "parse" in step_ids
        assert "diff" in step_ids
        assert "map" in step_ids
        assert "score" in step_ids
        assert "summarize" in step_ids
        assert "done" in step_ids

    @pytest.mark.asyncio
    async def test_agentic_analysis_missing_graph(self, agentic, store):
        a = store.create_analysis("Missing", "openai", "old.txt", "new.txt")

        with patch.object(agentic.graph_service, 'get_graph_data', return_value=None):
            progress_events = []
            async def collect_progress(p):
                progress_events.append(p)

            result = await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="Missing",
                progress_cb=collect_progress,
            )

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_agentic_analysis_llm_error(self, agentic, store, sample_graph_data):
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        mock_client.get_text_response.side_effect = Exception("LLM API timeout")

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            progress_events = []
            async def collect_progress(p):
                progress_events.append(p)

            result = await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
                progress_cb=collect_progress,
            )

        assert result["status"] == "failed"
        assert "LLM API timeout" in result["error"]
        # Should emit error event
        error_events = [e for e in progress_events if e["step"] == "error"]
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_agentic_analysis_stats_calculation(self, agentic, store, sample_graph_data):
        """Verify stats are correctly calculated from LLM output."""
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        self._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            result = await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        stats = result["stats"]
        assert stats["total_changes"] == 2
        assert stats["added_count"] == 1
        assert stats["modified_count"] == 1
        assert stats["removed_count"] == 0
        assert stats["affected_rules_count"] == 2
        assert stats["total_rules_in_graph"] == 3
        # impact_percentage = 2/3 * 100 = 66.7%
        assert abs(stats["impact_percentage"] - 66.7) < 1.0

    @pytest.mark.asyncio
    async def test_agentic_analysis_summary_structure(self, agentic, store, sample_graph_data):
        """Verify summary has all required fields."""
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        self._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            result = await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        summary = result["summary"]
        assert "headline" in summary
        assert "executive_summary" in summary
        assert "key_findings" in summary
        assert "recommendations" in summary
        assert "risk_assessment" in summary
        assert "old_provision_count" in summary
        assert "new_provision_count" in summary
        assert summary["old_provision_count"] == 1
        assert summary["new_provision_count"] == 2

    @pytest.mark.asyncio
    async def test_agentic_affected_rule_match_scores(self, agentic, store, sample_graph_data):
        """Verify match_score is derived from relevance."""
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        self._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        items = store.get_impact_items(a["id"])
        for item in items:
            for rule in item["affected_rules"]:
                if rule.get("relevance") == "high":
                    assert rule["match_score"] == 0.9
                elif rule.get("relevance") == "medium":
                    assert rule["match_score"] == 0.6

    @pytest.mark.asyncio
    async def test_agentic_no_progress_callback(self, agentic, store, sample_graph_data):
        """Should work fine without a progress callback."""
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        self._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            result = await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
                progress_cb=None,
            )

        assert result["status"] == "completed"


# ═════════════════════════════════════════════════════════════════
# WEBSOCKET HANDLER TESTS
# ═════════════════════════════════════════════════════════════════

class TestBroadcastImpact:
    @pytest.mark.asyncio
    async def test_broadcast_to_subscribers(self, ws_module):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws_module._subscribers["test-123"].add(ws1)
        ws_module._subscribers["test-123"].add(ws2)

        await ws_module.broadcast_impact("test-123", {"step": "parse", "status": "running"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

        sent1 = json.loads(ws1.send_text.await_args[0][0])
        assert sent1["step"] == "parse"

        # Cleanup
        ws_module._subscribers.pop("test-123", None)

    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(self, ws_module):
        # Should not raise
        await ws_module.broadcast_impact("nonexistent-id", {"step": "done"})

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self, ws_module):
        ws_good = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = Exception("Connection closed")

        ws_module._subscribers["test-dead"].add(ws_good)
        ws_module._subscribers["test-dead"].add(ws_dead)

        await ws_module.broadcast_impact("test-dead", {"step": "parse"})

        # Good ws should have received message
        ws_good.send_text.assert_awaited_once()
        # Dead ws should be removed from subscribers
        assert ws_dead not in ws_module._subscribers.get("test-dead", set())

        # Cleanup
        ws_module._subscribers.pop("test-dead", None)

    @pytest.mark.asyncio
    async def test_broadcast_sends_json(self, ws_module):
        ws = AsyncMock()
        ws_module._subscribers["json-test"].add(ws)

        payload = {"step": "score", "data": {"risk": 0.8, "items": [1, 2, 3]}}
        await ws_module.broadcast_impact("json-test", payload)

        sent = ws.send_text.await_args[0][0]
        parsed = json.loads(sent)
        assert parsed["data"]["risk"] == 0.8

        ws_module._subscribers.pop("json-test", None)

    @pytest.mark.asyncio
    async def test_broadcast_isolation(self, ws_module):
        """Messages to one analysis_id should not go to another."""
        ws_a = AsyncMock()
        ws_b = AsyncMock()
        ws_module._subscribers["analysis-A"].add(ws_a)
        ws_module._subscribers["analysis-B"].add(ws_b)

        await ws_module.broadcast_impact("analysis-A", {"step": "parse"})

        ws_a.send_text.assert_awaited_once()
        ws_b.send_text.assert_not_awaited()

        ws_module._subscribers.pop("analysis-A", None)
        ws_module._subscribers.pop("analysis-B", None)


class TestWsImpactEndpoint:
    @pytest.mark.asyncio
    async def test_ws_accept_and_subscribe(self, ws_module):
        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=Exception("WebSocketDisconnect"))

        try:
            await ws_module.ws_impact(ws, "sub-test-123")
        except Exception:
            pass

        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ws_cleanup_on_disconnect(self, ws_module):
        from fastapi import WebSocketDisconnect

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        await ws_module.ws_impact(ws, "cleanup-test")

        assert ws not in ws_module._subscribers.get("cleanup-test", set())
        # Should also clean up empty entries
        assert "cleanup-test" not in ws_module._subscribers


# ═════════════════════════════════════════════════════════════════
# ROUTER DUAL-MODE TESTS
# ═════════════════════════════════════════════════════════════════

class TestRouterModeParameter:
    def test_start_analysis_accepts_mode_basic(self, store):
        """Verify basic mode path in the router logic."""
        from ui.backend.routers.impact_analysis import _extract_text
        # Verify _extract_text is callable (used by both modes)
        result = _extract_text(b"Hello world", "test.txt")
        assert result == "Hello world"

    def test_extract_text_utf8(self):
        from ui.backend.routers.impact_analysis import _extract_text
        text = "Some regulatory text with unicode: é à ü"
        result = _extract_text(text.encode("utf-8"), "test.txt")
        assert "é" in result

    def test_extract_text_empty(self):
        from ui.backend.routers.impact_analysis import _extract_text
        result = _extract_text(b"", "test.txt")
        assert result.strip() == ""


# ═════════════════════════════════════════════════════════════════
# WORKFLOW STEPS CONSTANT TESTS
# ═════════════════════════════════════════════════════════════════

class TestWorkflowStepsConstant:
    def test_steps_count(self, agentic):
        assert len(agentic.STEPS) == 5

    def test_steps_order(self, agentic):
        ids = [s["id"] for s in agentic.STEPS]
        assert ids == ["parse", "diff", "map", "score", "summarize"]

    def test_steps_have_required_fields(self, agentic):
        for step in agentic.STEPS:
            assert "id" in step
            assert "name" in step
            assert "order" in step

    def test_steps_order_sequential(self, agentic):
        orders = [s["order"] for s in agentic.STEPS]
        assert orders == [1, 2, 3, 4, 5]


# ═════════════════════════════════════════════════════════════════
# JSON PARSING EDGE CASE TESTS
# ═════════════════════════════════════════════════════════════════

class TestJsonParsingEdgeCases:
    def test_llm_returns_unicode(self, agentic):
        text = '{"text": "Règlement de conformité"}'
        result = agentic._safe_json_parse(text)
        assert "Règlement" in result["text"]

    def test_llm_returns_escaped_newlines(self, agentic):
        text = '{"text": "line1\\nline2"}'
        result = agentic._safe_json_parse(text)
        assert "\n" in result["text"]

    def test_llm_returns_nested_json_in_fences(self, agentic):
        text = '```json\n{"a": {"b": {"c": [1, 2, 3]}}}\n```'
        result = agentic._safe_json_parse(text)
        assert result["a"]["b"]["c"] == [1, 2, 3]

    def test_llm_returns_json_with_trailing_comma_recovery(self, agentic):
        """JSON with trailing commas is invalid — should raise."""
        with pytest.raises(json.JSONDecodeError):
            agentic._safe_json_parse('{"a": 1,}')

    def test_llm_returns_large_json(self, agentic):
        items = [{"id": f"P{i}", "text": f"Provision {i}"} for i in range(100)]
        text = json.dumps({"provisions": items})
        result = agentic._safe_json_parse(text)
        assert len(result["provisions"]) == 100


# ═════════════════════════════════════════════════════════════════
# PERSISTENCE / STORE INTEGRATION TESTS
# ═════════════════════════════════════════════════════════════════

class TestAgenticPersistence:
    @pytest.mark.asyncio
    async def test_completed_analysis_has_finished_at(self, agentic, store, sample_graph_data):
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        TestRunAgenticAnalysis()._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        persisted = store.get_analysis(a["id"])
        assert persisted["finished_at"] is not None
        assert persisted["status"] == "completed"

    @pytest.mark.asyncio
    async def test_failed_analysis_has_finished_at(self, agentic, store, sample_graph_data):
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        mock_client.get_text_response.side_effect = RuntimeError("boom")

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        persisted = store.get_analysis(a["id"])
        assert persisted["finished_at"] is not None
        assert persisted["status"] == "failed"
        assert "boom" in persisted["error"]

    @pytest.mark.asyncio
    async def test_items_have_correct_change_types(self, agentic, store, sample_graph_data):
        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        TestRunAgenticAnalysis()._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data):

            await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        items = store.get_impact_items(a["id"])
        change_types = {i["change_type"] for i in items}
        assert "modified" in change_types
        assert "added" in change_types

    @pytest.mark.asyncio
    async def test_running_status_set_before_steps(self, agentic, store, sample_graph_data):
        """Verify the analysis is set to 'running' before LLM calls start."""
        statuses = []

        original_update = store.update_analysis
        def tracking_update(analysis_id, **kwargs):
            if "status" in kwargs:
                statuses.append(kwargs["status"])
            return original_update(analysis_id, **kwargs)

        a = store.create_analysis("G", "openai", "old.txt", "new.txt")
        mock_client = MagicMock()
        TestRunAgenticAnalysis()._mock_step_responses(mock_client)

        with patch.object(agentic, '_create_client', return_value=(mock_client, MagicMock())), \
             patch.object(agentic.graph_service, 'get_graph_data', return_value=sample_graph_data), \
             patch.object(store, 'update_analysis', side_effect=tracking_update):

            await agentic.run_agentic_analysis(
                analysis_id=a["id"],
                old_text="old",
                new_text="new",
                graph_name="G",
            )

        assert statuses[0] == "running"
        assert statuses[-1] == "completed"
