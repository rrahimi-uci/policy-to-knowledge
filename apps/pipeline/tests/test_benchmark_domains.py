"""Tests for the four benchmark-corpus domain packs.

`test_data_contracts.py` already parametrises its field contracts over every
entry in its DOMAINS list, so these tests cover only what it cannot:

- the two `_compact` overrides exist. Agents 2 and 3 request
  `entity_extraction_compact` / `business_rules_extraction_compact`, not the
  non-compact names the contract tests check. Without a domain override the
  shared copies apply, and those tell the model to "prefer concrete mortgage
  concepts" no matter which domain is active — so a pack missing them has no
  effect on the two agents that decide what gets extracted.
- every template survives `str.format()` with the kwargs its agent really passes
  (a stray single brace in a JSON block raises KeyError at runtime, not import).
- the committed `.txt` files still match the generator that produced them.
- no mortgage vocabulary bled into a contracts or privacy pack.
- rule-type palettes and quick-filter buttons are registered and agree with the
  rule_type vocabulary each pack's prompts define.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_benchmark_domain_prompts import (  # noqa: E402
    PROFILES,
    RUNTIME_KWARGS,
    TEMPLATE_NAMES,
    render,
)
from utils.config import (  # noqa: E402
    _DOMAIN_PRIORITY_FILTER_TYPES,
    _RULE_TYPE_COLORS_BY_DOMAIN,
)

DOMAIN_PROMPTS = PROJECT_ROOT / "domain-prompts"
BENCHMARK_DOMAINS = [p.key for p in PROFILES]
PROFILE_BY_KEY = {p.key: p for p in PROFILES}

# Requested by an agent at runtime and resolvable per domain. The other prompt
# names in a pack exist to satisfy the contract tests and the repo convention.
RUNTIME_DOMAIN_PROMPTS = [
    "document_structure_analysis",
    "entity_extraction_compact",
    "business_rules_extraction_compact",
    "rule_deduplication",
    "dependency_analysis",
    "rule_matcher_batch",
]


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
@pytest.mark.parametrize("name", RUNTIME_DOMAIN_PROMPTS)
def test_runtime_prompt_is_overridden(domain, name):
    """Every prompt an agent actually loads must exist in the domain pack.

    The two _compact names are the point of this test: they are what Agents 2
    and 3 request, and no pre-existing domain pack overrides them.
    """
    path = DOMAIN_PROMPTS / domain / f"{name}.txt"
    assert path.exists(), (
        f"{domain}/{name}.txt missing — the shared (mortgage-worded) copy would apply"
    )


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_prompt_formats_with_real_kwargs(domain, name):
    """A literal JSON brace written singly raises KeyError when the agent formats it."""
    text = (DOMAIN_PROMPTS / domain / f"{name}.txt").read_text(encoding="utf-8")
    try:
        text.format(**RUNTIME_KWARGS[name])
    except (KeyError, IndexError, ValueError) as exc:
        pytest.fail(
            f"{domain}/{name}.txt fails str.format with the agent's real kwargs "
            f"{sorted(RUNTIME_KWARGS[name])}: {type(exc).__name__}: {exc}"
        )


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_committed_file_matches_generator(domain, name):
    """Guards against hand-edits drifting from scripts/generate_benchmark_domain_prompts.py."""
    path = DOMAIN_PROMPTS / domain / f"{name}.txt"
    assert path.read_text(encoding="utf-8") == render(PROFILE_BY_KEY[domain], name), (
        f"{domain}/{name}.txt is stale — re-run "
        f"scripts/generate_benchmark_domain_prompts.py"
    )


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_no_mortgage_vocabulary_bleed(domain, name):
    """These corpora are contracts and privacy policies; mortgage wording is a copy-paste tell."""
    text = (DOMAIN_PROMPTS / domain / f"{name}.txt").read_text(encoding="utf-8").lower()
    for term in ("mortgage", "borrower", "underwriting", "loan_types", "occupancy_types"):
        assert term not in text, f"{domain}/{name}.txt contains mortgage term '{term}'"


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
def test_rule_types_agree_with_palette(domain):
    """Agent 6 colours nodes by rule_type; a mismatch renders every rule grey."""
    profile = PROFILE_BY_KEY[domain]
    assert domain in _RULE_TYPE_COLORS_BY_DOMAIN, f"{domain} has no rule-type palette"
    assert set(_RULE_TYPE_COLORS_BY_DOMAIN[domain]) == set(profile.rule_types), (
        f"{domain} palette keys differ from the rule_types its prompts define"
    )


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
def test_priority_filters_are_real_rule_types(domain):
    """Quick-filter buttons must name rule types the pack can actually produce."""
    assert domain in _DOMAIN_PRIORITY_FILTER_TYPES, f"{domain} has no priority filters"
    filters = _DOMAIN_PRIORITY_FILTER_TYPES[domain]
    assert len(filters) == 3, f"{domain} should expose exactly 3 quick filters"
    unknown = set(filters) - set(PROFILE_BY_KEY[domain].rule_types)
    assert not unknown, f"{domain} quick filters name unknown rule types: {sorted(unknown)}"


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
def test_rule_type_vocabulary_reaches_the_extraction_prompt(domain):
    """The compact rules prompt is the only place rule_type is constrained at runtime."""
    text = (DOMAIN_PROMPTS / domain / "business_rules_extraction_compact.txt").read_text(
        encoding="utf-8"
    )
    for rule_type in PROFILE_BY_KEY[domain].rule_types:
        assert rule_type in text, (
            f"{domain}/business_rules_extraction_compact.txt never mentions "
            f"rule_type '{rule_type}'"
        )


@pytest.mark.parametrize("config_name", ["config.json", "config.example.json"])
@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
def test_domain_registered_in_config(config_name, domain):
    path = PROJECT_ROOT / config_name
    if not path.exists():
        pytest.skip(f"{config_name} not present")
    available = json.loads(path.read_text(encoding="utf-8"))["domain"]["available"]
    assert domain in available, f"{domain} missing from {config_name} domain.available"


@pytest.mark.parametrize("domain", BENCHMARK_DOMAINS)
def test_prompt_manager_resolves_pack(domain):
    """End-to-end: PromptManager must return the domain copy, not the shared fallback."""
    from utils.prompt_manager import PromptManager

    pm = PromptManager(domain_prompts_dir=DOMAIN_PROMPTS / domain)
    for name in RUNTIME_DOMAIN_PROMPTS:
        text = pm.load_prompt(name)
        assert "mortgage" not in text.lower(), (
            f"PromptManager fell back to the shared mortgage copy for {domain}/{name}"
        )


@pytest.mark.parametrize("graph_name,expected", [
    ("cuad-source-docs", "commercial_contracts"),
    ("contract-nli-source-docs", "nda_confidentiality"),
    ("opp-115-source-docs", "privacy_policy"),
    ("mapp-source-docs", "mobile_app_privacy"),
    # Pre-existing behaviour must survive the new, more specific keyword entries.
    ("commercial-lending", "commercial_lending"),
    ("commercial_lending_q4", "commercial_lending"),
])
def test_graph_name_infers_benchmark_domain(graph_name, expected):
    from ui.backend.services.graph_service import _infer_domain_from_name

    assert _infer_domain_from_name(graph_name) == expected
