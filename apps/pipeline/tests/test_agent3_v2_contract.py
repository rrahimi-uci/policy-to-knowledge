from agents.agent_3_rules_extractor import BusinessRulesExtractor
from tests.test_rule_contract import valid_rule


class _PromptManager:
    def format_prompt(self, *args, **kwargs):
        return "DOMAIN PROMPT"

    def load_rule_contract_v2(self):
        return "V2 CONTRACT"


class _Config:
    def get_rules_per_batch(self):
        return 3


def _extractor():
    extractor = object.__new__(BusinessRulesExtractor)
    extractor.entity_definitions = {"SELLER_SERVICER": {}, "FANNIE_MAE": {}}
    extractor.relationship_definitions = {}
    extractor.prompt_manager = _PromptManager()
    extractor.global_config = _Config()
    return extractor


def test_agent_three_appends_non_overridable_v2_contract():
    prompt = _extractor().create_batch_prompt(
        [{"path": "chunk.txt", "content": "source text"}],
        batch_num=1,
        total_batches=1,
    )

    assert prompt == "DOMAIN PROMPT\n\nV2 CONTRACT"


def test_agent_three_retains_invalid_v2_candidate_for_review():
    candidate = valid_rule()
    candidate.pop("variables")

    annotated = _extractor()._annotate_v2_contract(candidate)

    assert annotated["rule_id"] == "BR-1"
    assert annotated["requires_review"] is True
    assert annotated["readiness"]["status"] == "review_required"
