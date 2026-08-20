from pathlib import Path

from utils.prompt_manager import PromptManager


PROJECT_ROOT = Path(__file__).parent.parent


def test_v2_rule_contract_is_shared_and_not_overridden_by_domain_prompt():
    manager = PromptManager(
        domain_prompts_dir=PROJECT_ROOT / "domain-prompts" / "aml",
        fallback_dir=PROJECT_ROOT / "prompts",
    )

    contract = manager.load_rule_contract_v2()

    assert '"schema_version": "2.0"' in contract
    assert '"condition_predicates"' in contract
    assert '"field_evidence"' in contract
    assert "not_found_in_chunk_recheck_needed" in contract
