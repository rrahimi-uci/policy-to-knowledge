from copy import deepcopy
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.agent_5_7_grounding_verifier import (
    MODEL_CLAIM_TYPES,
    GroundingVerifier,
    OpenAIGroundingResolver,
    certification_issues,
    extract_claims,
)
from tests.test_executable_readiness import graph_with_two_rules
from tests.test_rule_contract import valid_rule
from utils.kg_readiness import source_document_index


SOURCE_TEXT = "A seller servicer must limit the number of pools to three."


class SupportingResolver:
    model = "test-verifier"
    reasoning_effort = "medium"

    def __init__(self):
        self.calls = 0

    def verify(self, packets):
        self.calls += 1
        return [
            {
                "rule_id": packet["rule_id"],
                "claim_id": claim["claim_id"],
                "verdict": "supported",
                "evidence_id": packet["evidence"][0]["evidence_id"],
                "supporting_quote": SOURCE_TEXT,
                "reasoning": "The supplied source text entails the claim.",
            }
            for packet in packets
            for claim in packet["claims"]
        ]


def _organized_corpus(tmp_path):
    organized = tmp_path / "organized" / "B2-1-01"
    organized.mkdir(parents=True)
    (organized / "001.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    return tmp_path / "organized"


def test_claim_projection_covers_every_executable_claim_family():
    rule = graph_with_two_rules()["business_rules"][0]
    claim_types = {claim["claim_type"] for claim in extract_claims(rule)}

    assert {
        "condition", "condition_logic", "variable", "outcome", "party", "scope",
        "exception", "classification", "execution", "test_vector",
    } <= claim_types


def test_graph_dependencies_and_conflicts_are_bounded_or_deterministic(tmp_path):
    organized = _organized_corpus(tmp_path)
    graph = graph_with_two_rules()
    graph["dependency_details"]["conflicts"] = [{
        "rule_ids": ["BR-1", "BR-2"],
        "status": "non_conflict",
        "reasoning": "The rules have disjoint outcome variables.",
        "resolution": "Execute both.",
    }]

    packets, deterministic = GroundingVerifier.build_relationship_packets(
        graph, source_document_index(str(organized)), 8000
    )

    assert any(packet["claims"][0]["claim_type"] == "dependency" for packet in packets)
    assert deterministic[0]["relationship_id"] == "@conflict:0"


def test_oversized_rule_is_split_without_exceeding_claim_ceiling():
    packet = {
        "rule_id": "RICH-RULE",
        "claims": [{"claim_id": f"c{index}"} for index in range(11)],
        "evidence": [],
        "rule_logic": {},
    }

    batches = GroundingVerifier.make_batches([packet], max_rules=4, max_claims=4)

    assert [sum(len(item["claims"]) for item in batch) for batch in batches] == [4, 4, 3]
    assert all(len(item["claims"]) <= 4 for batch in batches for item in batch)


def test_openai_resolver_retries_incomplete_response(monkeypatch):
    packet = {"rule_id": "R1", "claims": [{"claim_id": "c1"}], "evidence": []}

    class Prompts:
        def format_prompt(self, name, **values):
            return values["packets_json"]

    class Client:
        def __init__(self):
            self.calls = 0

        def chat_completion(self, **kwargs):
            self.calls += 1
            payload = {"verifications": []}
            if self.calls == 2:
                payload["verifications"] = [{
                    "rule_id": "R1", "claim_id": "c1", "verdict": "supported",
                    "evidence_id": "E1", "supporting_quote": "quote", "reasoning": "supported",
                }]
            import json
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    resolver = object.__new__(OpenAIGroundingResolver)
    resolver.model = "test-model"
    resolver.reasoning_effort = "medium"
    resolver.prompts = Prompts()
    resolver.client = Client()
    monkeypatch.setenv("KG_GROUNDING_PARSE_ATTEMPTS", "2")

    results = resolver.verify([packet])

    assert resolver.client.calls == 2
    assert results[0]["claim_id"] == "c1"


def test_supported_graph_is_certified_without_rewriting_rule_claims(tmp_path, monkeypatch):
    organized = _organized_corpus(tmp_path)
    output = tmp_path / "output"
    graph = graph_with_two_rules()
    original_rules = deepcopy(graph["business_rules"])
    resolver = SupportingResolver()
    monkeypatch.setenv("KG_GROUNDING_RULES_PER_REQUEST", "1")
    monkeypatch.setenv("KG_GROUNDING_WORKERS", "4")

    final_graph, report = GroundingVerifier(resolver).verify_graph(graph, organized, output)

    assert report["pass"] is True
    assert report["claim_coverage_percent"] == 100.0
    assert report["rules_certified"] == 2
    assert report["contradicted_claims"] == 0
    assert report["insufficient_evidence_claims"] == 0
    assert all(rule["grounding"]["status"] == "certified" for rule in final_graph["business_rules"])
    for before, after in zip(original_rules, final_graph["business_rules"]):
        for field in (
            "condition_predicates", "condition_logic", "outcomes", "responsible_party",
            "counterparties", "applicability_scope", "exceptions", "test_vectors", "source_reference",
        ):
            assert after[field] == before[field]
    assert certification_issues(final_graph, report, report["corpus_sha256"]) == []


def test_invalid_source_quote_cannot_be_certified(tmp_path):
    organized = _organized_corpus(tmp_path)
    graph = graph_with_two_rules()
    for rule in graph["business_rules"]:
        rule["source_reference"]["source_text"] = "This quotation is not in the corpus."
        for entries in rule["field_evidence"].values():
            for evidence in entries:
                evidence["source_text"] = "This quotation is not in the corpus."

    final_graph, report = GroundingVerifier(SupportingResolver()).verify_graph(
        graph, organized, tmp_path / "output"
    )

    assert report["pass"] is False
    assert report["invalid_evidence_records"] >= 2
    assert report["insufficient_evidence_claims"] > 0
    assert all(rule["requires_review"] is True for rule in final_graph["business_rules"])


def test_missing_duplicate_and_unexpected_responses_fail_closed(tmp_path):
    organized = _organized_corpus(tmp_path)
    graph = graph_with_two_rules()
    graph["dependency_details"]["dependencies"] = []

    class BadProtocolResolver(SupportingResolver):
        def verify(self, packets):
            results = super().verify(packets)
            results.pop()
            results.append(deepcopy(results[0]))
            results.append({
                **deepcopy(results[0]),
                "rule_id": "UNKNOWN-RULE",
                "claim_id": "invented-claim",
            })
            return results

    _, report = GroundingVerifier(BadProtocolResolver()).verify_graph(
        graph, organized, tmp_path / "output"
    )

    assert report["pass"] is False
    assert report["claim_coverage_percent"] < 100.0
    assert report["missing_claim_responses"] == 1
    assert report["duplicate_claim_responses"] == 1
    assert report["unexpected_claim_responses"] == 1


def test_checkpoint_reuses_identical_source_and_claim_packets(tmp_path, monkeypatch):
    organized = _organized_corpus(tmp_path)
    output = tmp_path / "output"
    resolver = SupportingResolver()
    monkeypatch.setenv("KG_GROUNDING_RULES_PER_REQUEST", "1")
    verifier = GroundingVerifier(resolver)
    graph = graph_with_two_rules()
    graph["dependency_details"]["dependencies"] = []

    first_graph, first_report = verifier.verify_graph(graph, organized, output)
    call_count = resolver.calls
    second_graph, second_report = verifier.verify_graph(first_graph, organized, output)

    assert call_count == 2
    assert resolver.calls == call_count
    assert first_report["pass"] is True
    assert second_report["pass"] is True
    assert all(rule["grounding"]["status"] == "certified" for rule in second_graph["business_rules"])


def test_batches_execute_concurrently(tmp_path, monkeypatch):
    organized = _organized_corpus(tmp_path)
    graph = graph_with_two_rules()
    graph["dependency_details"]["dependencies"] = []
    template = graph["business_rules"][0]
    graph["business_rules"] = []
    for index in range(8):
        rule = deepcopy(template)
        rule["rule_id"] = f"BR-{index}"
        graph["business_rules"].append(rule)

    class TrackingResolver(SupportingResolver):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.peak = 0
            self.lock = threading.Lock()

        def verify(self, packets):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.03)
            try:
                return super().verify(packets)
            finally:
                with self.lock:
                    self.active -= 1

    resolver = TrackingResolver()
    monkeypatch.setenv("KG_GROUNDING_RULES_PER_REQUEST", "1")
    monkeypatch.setenv("KG_GROUNDING_WORKERS", "4")

    _, report = GroundingVerifier(resolver).verify_graph(graph, organized, tmp_path / "output")

    assert report["pass"] is True
    assert resolver.peak >= 2


def test_certificate_detects_graph_or_corpus_drift(tmp_path):
    organized = _organized_corpus(tmp_path)
    final_graph, report = GroundingVerifier(SupportingResolver()).verify_graph(
        graph_with_two_rules(), organized, tmp_path / "output"
    )
    final_graph["business_rules"][0]["outcomes"][0]["value"] = 99

    issues = certification_issues(final_graph, report, report["corpus_sha256"])

    assert "optimized graph has changed since grounding verification" in issues
    assert "source corpus has changed since grounding verification" in certification_issues(
        final_graph, report, "different-corpus"
    )


def test_stage_6_rejects_optimized_graph_without_certificate(tmp_path):
    from cli.extract import KnowledgeExtractionPipeline

    optimized = tmp_path / "optimized"
    optimized.mkdir()
    (optimized / "optimized_compliance_knowledge_graph.json").write_text("{}", encoding="utf-8")
    config = MagicMock()
    config.get_optimized_dir.return_value = optimized
    config.get_rules_with_entities_dir.return_value = tmp_path / "merged"
    pipeline = object.__new__(KnowledgeExtractionPipeline)
    pipeline.config = config
    pipeline.organized_dir = tmp_path / "organized"
    pipeline.output_dir = tmp_path / "visualization"

    assert pipeline.step6_visualize_knowledge_graph() is False


# ─────────────────────────────────────────────────────────────────────────
# condition_logic / test_vector: verified structurally, not against source
# quotes. These two are DERIVED from a rule's own condition_predicates and
# outcomes — no policy sentence ever states "Conditions combine as
# {predicate_ref: p1}" or a synthesized {inputs -> expected_output} example
# verbatim, so routing them through the LLM quote-grounding path scored
# near-100% insufficient_evidence regardless of how well-grounded the rule
# actually was. See MODEL_CLAIM_TYPES and deterministic_rule_claims.
# ─────────────────────────────────────────────────────────────────────────

def test_condition_logic_and_test_vector_are_not_model_claim_types():
    assert "condition_logic" not in MODEL_CLAIM_TYPES
    assert "test_vector" not in MODEL_CLAIM_TYPES


def test_valid_condition_logic_and_test_vector_are_certified_without_a_model_call():
    rule = valid_rule()
    results = GroundingVerifier.deterministic_rule_claims(rule, entity_keys=["SELLER_SERVICER", "FANNIE_MAE"])
    by_id = {r["claim_id"]: r for r in results}

    assert by_id["condition_logic"]["verdict"] == "supported"
    assert by_id["condition_logic"]["evidence_id"] is None
    assert "not against source prose" in by_id["condition_logic"]["reasoning"]

    assert by_id["test_vector:0"]["verdict"] == "supported"
    assert "own contract" in by_id["test_vector:0"]["reasoning"]


def test_test_vector_naming_an_undeclared_variable_fails_deterministically():
    rule = valid_rule()
    rule["test_vectors"][0]["inputs"]["undeclared_variable"] = 1
    results = GroundingVerifier.deterministic_rule_claims(rule, entity_keys=["SELLER_SERVICER", "FANNIE_MAE"])
    by_id = {r["claim_id"]: r for r in results}

    assert by_id["test_vector:0"]["verdict"] == "insufficient_evidence"
    assert "undeclared_variable" in by_id["test_vector:0"]["reasoning"]


def test_test_vector_expected_output_naming_undeclared_outcome_fails():
    rule = valid_rule()
    rule["test_vectors"][0]["expected_output"] = {"not_a_real_outcome": 1}
    results = GroundingVerifier.deterministic_rule_claims(rule, entity_keys=["SELLER_SERVICER", "FANNIE_MAE"])
    by_id = {r["claim_id"]: r for r in results}

    assert by_id["test_vector:0"]["verdict"] == "insufficient_evidence"
    assert "not_a_real_outcome" in by_id["test_vector:0"]["reasoning"]


def test_condition_logic_referencing_unknown_predicate_fails_deterministically():
    rule = valid_rule()
    rule["condition_logic"] = {"predicate_ref": "p_does_not_exist"}
    results = GroundingVerifier.deterministic_rule_claims(rule, entity_keys=["SELLER_SERVICER", "FANNIE_MAE"])
    by_id = {r["claim_id"]: r for r in results}

    assert by_id["condition_logic"]["verdict"] == "insufficient_evidence"


def test_condition_logic_failure_does_not_fail_unrelated_test_vector():
    """A condition_logic defect must not blanket-fail every other derived claim
    on the rule — that would just reintroduce the imprecision this fix removes."""
    rule = valid_rule()
    rule["condition_logic"] = {"predicate_ref": "p_does_not_exist"}
    results = GroundingVerifier.deterministic_rule_claims(rule, entity_keys=["SELLER_SERVICER", "FANNIE_MAE"])
    by_id = {r["claim_id"]: r for r in results}

    assert by_id["condition_logic"]["verdict"] == "insufficient_evidence"
    assert by_id["test_vector:0"]["verdict"] == "supported"


def test_test_vector_with_no_inputs_or_outputs_is_insufficient():
    rule = valid_rule()
    rule["test_vectors"][0]["inputs"] = {}
    rule["test_vectors"][0]["expected_output"] = {}
    results = GroundingVerifier.deterministic_rule_claims(rule, entity_keys=["SELLER_SERVICER", "FANNIE_MAE"])
    by_id = {r["claim_id"]: r for r in results}

    assert by_id["test_vector:0"]["verdict"] == "insufficient_evidence"


def test_condition_logic_and_test_vector_absent_from_model_packet():
    """build_packet must not send these two claim types to the LLM at all."""
    rule = valid_rule()
    packet = GroundingVerifier.build_packet(rule, corpus={}, max_chars=8000)
    claim_types = {c["claim_type"] for c in packet["claims"]}
    assert "condition_logic" not in claim_types
    assert "test_vector" not in claim_types
