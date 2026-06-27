"""
Tests for domain-pluggable platform support.

Covers:
- config.json domain section structure
- Config.get_domain() / set_domain() / get_domain_prompts_dir()
- Domain resolution priority: explicit > KG_DOMAIN env var > config.json 'domain.active'
- PromptManager two-tier fallback (domain dir → shared prompts/)
- PromptManager domain-keyed singleton re-creation
- PromptManager caching and format_prompt()
- Agent 6  _get_rule_type_description() for both domains
- Agent 7  LEGACY_TYPE_TO_BEHAVIOR AML entries
- Agent 8  _extract_thresholds() AML patterns
- domain-prompts/{mortgage,aml}/ file existence and non-emptiness
- --domain CLI arg parsing in knowledge_graph_generation
- KG_DOMAIN propagation to subprocess env
"""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import utils.config as cfg_mod
import utils.prompt_manager as pm_mod
from utils.config import Config, get_config, reload_config


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset Config and PromptManager singletons before and after each test."""
    _clean()
    yield
    _clean()


def _clean():
    Config._instance = None
    Config._config = None
    Config._provider = None
    Config._source_file_name = None
    Config._batch_name = None
    Config._domain = None
    cfg_mod._config = None
    pm_mod._prompt_manager = None
    pm_mod._prompt_manager_domain = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. config.json — domain section structure
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigJsonDomainSection:
    """Verify config.json contains a valid domain section."""

    @pytest.fixture
    def config_data(self):
        with open(PROJECT_ROOT / "config.json") as f:
            return json.load(f)

    def test_has_domain_section(self, config_data):
        assert "domain" in config_data

    def test_domain_has_active_key(self, config_data):
        assert "active" in config_data["domain"]

    def test_domain_active_is_mortgage_or_aml(self, config_data):
        assert config_data["domain"]["active"] in ("mortgage", "aml")

    def test_domain_has_prompts_base_dir(self, config_data):
        assert "prompts_base_dir" in config_data["domain"]
        assert config_data["domain"]["prompts_base_dir"] == "domain-prompts"

    def test_domain_has_available_list(self, config_data):
        assert "available" in config_data["domain"]
        available = config_data["domain"]["available"]
        assert "mortgage" in available
        assert "aml" in available

    def test_config_example_json_has_same_structure(self):
        with open(PROJECT_ROOT / "config.example.json") as f:
            example = json.load(f)
        assert "domain" in example
        assert "active" in example["domain"]
        assert "prompts_base_dir" in example["domain"]
        assert "available" in example["domain"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Config.get_domain() — default and config.json value
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigGetDomain:
    """Tests for Config.get_domain()."""

    def test_get_domain_returns_string(self):
        c = get_config()
        domain = c.get_domain()
        assert isinstance(domain, str)
        assert len(domain) > 0

    def test_get_domain_returns_config_active_when_not_overridden(self):
        """Without env var or explicit domain, should read from config.json 'domain.active'."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KG_DOMAIN", None)
            c = get_config()
            expected = c.get("domain.active", "mortgage")
            assert c.get_domain() == expected

    def test_get_domain_default_is_mortgage_when_config_missing(self):
        """Falls back to 'mortgage' if config has no domain.active."""
        c = get_config()
        # Simulate missing domain key
        original = c._config.pop("domain", None)
        try:
            assert c.get_domain() == "mortgage"
        finally:
            if original is not None:
                c._config["domain"] = original


# ─────────────────────────────────────────────────────────────────────────────
# 3. Config.set_domain()
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigSetDomain:
    """Tests for Config.set_domain()."""

    def test_set_domain_changes_get_domain(self):
        c = get_config()
        c.set_domain("aml")
        assert c.get_domain() == "aml"

    def test_set_domain_mortgage(self):
        c = get_config()
        c.set_domain("mortgage")
        assert c.get_domain() == "mortgage"

    def test_set_domain_persists_on_singleton(self):
        c1 = get_config()
        c1.set_domain("aml")
        c2 = get_config()  # Should return same singleton
        assert c2.get_domain() == "aml"

    def test_set_domain_overrides_env_var(self):
        with patch.dict(os.environ, {"KG_DOMAIN": "mortgage"}):
            c = get_config()
            c.set_domain("aml")
            assert c.get_domain() == "aml"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Domain resolution priority
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainResolutionPriority:
    """Explicit domain > KG_DOMAIN env var > config.json domain.active."""

    def test_explicit_domain_takes_highest_priority(self):
        with patch.dict(os.environ, {"KG_DOMAIN": "mortgage"}):
            c = get_config(domain="aml")
            assert c.get_domain() == "aml"

    def test_env_var_used_when_no_explicit_domain(self):
        with patch.dict(os.environ, {"KG_DOMAIN": "aml"}):
            c = get_config()
            assert c.get_domain() == "aml"

    def test_config_json_used_when_no_env_or_explicit(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KG_DOMAIN", None)
            c = get_config()
            # Should equal whatever config.json says
            expected = c.get("domain.active", "mortgage")
            assert c.get_domain() == expected

    def test_reload_config_with_domain(self):
        reload_config(domain="aml")
        c = get_config()
        assert c.get_domain() == "aml"

    def test_reload_config_resets_previous_domain(self):
        get_config(domain="aml")
        reload_config(domain="mortgage")
        assert get_config().get_domain() == "mortgage"

    def test_kg_domain_env_var_read_at_init(self):
        with patch.dict(os.environ, {"KG_DOMAIN": "aml"}):
            reload_config()
            assert get_config().get_domain() == "aml"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Config.get_domain_prompts_dir()
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigGetDomainPromptsDir:
    """Tests for Config.get_domain_prompts_dir()."""

    def test_mortgage_domain_prompts_dir(self):
        c = get_config(domain="mortgage")
        d = c.get_domain_prompts_dir()
        assert d == Path("domain-prompts") / "mortgage"

    def test_aml_domain_prompts_dir(self):
        c = get_config(domain="aml")
        d = c.get_domain_prompts_dir()
        assert d == Path("domain-prompts") / "aml"

    def test_domain_prompts_dir_changes_with_set_domain(self):
        c = get_config(domain="mortgage")
        c.set_domain("aml")
        assert c.get_domain_prompts_dir() == Path("domain-prompts") / "aml"

    def test_domain_prompts_dir_is_path_object(self):
        c = get_config()
        assert isinstance(c.get_domain_prompts_dir(), Path)

    def test_domain_prompts_dir_respects_custom_base(self):
        c = get_config(domain="aml")
        # Override base dir in config data
        original = c._config.get("domain", {}).get("prompts_base_dir")
        c._config.setdefault("domain", {})["prompts_base_dir"] = "custom-prompts"
        try:
            assert c.get_domain_prompts_dir() == Path("custom-prompts") / "aml"
        finally:
            c._config["domain"]["prompts_base_dir"] = original or "domain-prompts"


# ─────────────────────────────────────────────────────────────────────────────
# 6. PromptManager — two-tier fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptManagerFallback:
    """PromptManager tries domain dir first, falls back to prompts/."""

    def test_loads_mortgage_domain_prompt(self):
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "mortgage"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        text = pm.load_prompt("business_rules_extraction")
        assert len(text) > 100

    def test_loads_aml_domain_prompt(self):
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "aml"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        text = pm.load_prompt("entity_extraction")
        assert "AML" in text or "aml" in text.lower() or "Anti-Money" in text

    def test_fallback_to_shared_prompts_dir(self):
        """document_structure_analysis only exists in prompts/, not domain dirs."""
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "mortgage"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        text = pm.load_prompt("document_structure_analysis")
        assert len(text) > 50

    def test_fallback_also_works_for_aml_domain(self):
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "aml"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        text = pm.load_prompt("document_structure_analysis")
        assert len(text) > 50

    def test_raises_file_not_found_when_missing_both_dirs(self):
        with tempfile.TemporaryDirectory() as domain_dir, \
             tempfile.TemporaryDirectory() as fallback_dir:
            pm = pm_mod.PromptManager(
                domain_prompts_dir=domain_dir,
                fallback_dir=fallback_dir,
            )
            with pytest.raises(FileNotFoundError) as exc_info:
                pm.load_prompt("nonexistent_prompt")
            assert "nonexistent_prompt" in str(exc_info.value)

    def test_domain_specific_prompt_takes_precedence_over_fallback(self):
        """If same prompt exists in both dirs, domain-specific wins."""
        with tempfile.TemporaryDirectory() as domain_dir, \
             tempfile.TemporaryDirectory() as fallback_dir:
            # Write different content to each location
            (Path(domain_dir) / "test_prompt.txt").write_text("DOMAIN VERSION")
            (Path(fallback_dir) / "test_prompt.txt").write_text("FALLBACK VERSION")
            pm = pm_mod.PromptManager(
                domain_prompts_dir=domain_dir,
                fallback_dir=fallback_dir,
            )
            assert pm.load_prompt("test_prompt") == "DOMAIN VERSION"


# ─────────────────────────────────────────────────────────────────────────────
# 7. PromptManager — caching
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptManagerCaching:
    """Loaded prompts should be cached — same object returned on second call."""

    def test_prompt_is_cached_after_first_load(self):
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "mortgage"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        first = pm.load_prompt("entity_extraction")
        second = pm.load_prompt("entity_extraction")
        assert first is second  # Same object (cached), not just equal

    def test_cache_is_per_instance(self):
        pm1 = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "mortgage"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        pm2 = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "aml"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        pm1.load_prompt("entity_extraction")
        assert "entity_extraction" not in pm2._cache


# ─────────────────────────────────────────────────────────────────────────────
# 8. PromptManager — format_prompt()
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptManagerFormatPrompt:
    """format_prompt() should substitute placeholders."""

    def test_format_prompt_substitutes_kwargs(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d).joinpath("greet.txt").write_text("Hello {name}, domain={domain}")
            pm = pm_mod.PromptManager(domain_prompts_dir=d, fallback_dir=d)
            result = pm.format_prompt("greet", name="World", domain="aml")
            assert result == "Hello World, domain=aml"

    def test_format_prompt_with_no_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d).joinpath("plain.txt").write_text("No placeholders here.")
            pm = pm_mod.PromptManager(domain_prompts_dir=d, fallback_dir=d)
            assert pm.format_prompt("plain") == "No placeholders here."


# ─────────────────────────────────────────────────────────────────────────────
# 9. PromptManager — domain-keyed singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptManagerSingleton:
    """get_prompt_manager() returns a new instance when domain changes."""

    def test_singleton_returns_same_instance_for_same_domain(self):
        get_config(domain="mortgage")
        pm1 = pm_mod.get_prompt_manager()
        pm2 = pm_mod.get_prompt_manager()
        assert pm1 is pm2

    def test_singleton_recreates_when_domain_changes(self):
        get_config(domain="mortgage")
        pm1 = pm_mod.get_prompt_manager()

        reload_config(domain="aml")
        pm2 = pm_mod.get_prompt_manager()

        assert pm1 is not pm2

    def test_singleton_domain_dir_matches_active_domain_mortgage(self):
        get_config(domain="mortgage")
        pm = pm_mod.get_prompt_manager()
        assert "mortgage" in str(pm.active_domain_dir)

    def test_singleton_domain_dir_matches_active_domain_aml(self):
        get_config(domain="aml")
        pm = pm_mod.get_prompt_manager()
        assert "aml" in str(pm.active_domain_dir)


# ─────────────────────────────────────────────────────────────────────────────
# 10. PromptManager — active_domain_dir property
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptManagerActiveDomainDir:
    def test_active_domain_dir_is_path(self):
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "mortgage"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        assert isinstance(pm.active_domain_dir, Path)

    def test_active_domain_dir_reflects_constructor_arg(self):
        pm = pm_mod.PromptManager(
            domain_prompts_dir=str(PROJECT_ROOT / "domain-prompts" / "aml"),
            fallback_dir=str(PROJECT_ROOT / "prompts"),
        )
        assert "aml" in str(pm.active_domain_dir)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Domain prompt files — existence and content
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_PROMPT_FILES = [
    "business_rules_extraction",
    "dependency_analysis",
    "document_structure_analysis",
    "entity_extraction",
    "entity_refinement",
    "entity_resolution",
    "rule_deduplication",
    "rule_matcher",
    "rule_matcher_batch",
    "rule_resolution",
    "validation_report",
]

# No prompts remain shared-only; domain dirs now have all 11 prompts.
SHARED_PROMPT_FILES: list = []


@pytest.mark.parametrize("prompt_name", EXPECTED_PROMPT_FILES)
class TestMortgagePromptFiles:
    def test_file_exists(self, prompt_name):
        f = PROJECT_ROOT / "domain-prompts" / "mortgage" / f"{prompt_name}.txt"
        assert f.exists(), f"Missing: {f}"

    def test_file_is_non_empty(self, prompt_name):
        f = PROJECT_ROOT / "domain-prompts" / "mortgage" / f"{prompt_name}.txt"
        assert f.stat().st_size > 0, f"Empty file: {f}"

    def test_file_is_utf8_readable(self, prompt_name):
        f = PROJECT_ROOT / "domain-prompts" / "mortgage" / f"{prompt_name}.txt"
        content = f.read_text(encoding="utf-8")
        assert len(content) > 50


@pytest.mark.parametrize("prompt_name", EXPECTED_PROMPT_FILES)
class TestAmlPromptFiles:
    def test_file_exists(self, prompt_name):
        f = PROJECT_ROOT / "domain-prompts" / "aml" / f"{prompt_name}.txt"
        assert f.exists(), f"Missing: {f}"

    def test_file_is_non_empty(self, prompt_name):
        f = PROJECT_ROOT / "domain-prompts" / "aml" / f"{prompt_name}.txt"
        assert f.stat().st_size > 0, f"Empty file: {f}"

    def test_file_contains_aml_terminology(self, prompt_name):
        f = PROJECT_ROOT / "domain-prompts" / "aml" / f"{prompt_name}.txt"
        content = f.read_text(encoding="utf-8")
        aml_terms = ["AML", "BSA", "SAR", "CTR", "KYC", "OFAC", "FinCEN", "FATF",
                     "Anti-Money", "beneficial owner", "suspicious activity"]
        assert any(t.lower() in content.lower() for t in aml_terms), \
            f"{prompt_name}.txt lacks AML terminology"


class TestSharedPromptFiles:
    """All 11 prompts exist in both domain dirs AND the shared fallback prompts/ dir."""

    @pytest.mark.parametrize("prompt_name", EXPECTED_PROMPT_FILES)
    def test_base_prompt_still_exists_for_fallback(self, prompt_name):
        """The shared prompts/ dir must always keep a fallback copy."""
        f = PROJECT_ROOT / "prompts" / f"{prompt_name}.txt"
        assert f.exists(), f"Fallback prompt missing from prompts/: {f}"

    def test_document_structure_analysis_in_all_domain_dirs(self):
        """document_structure_analysis is now domain-specific — must be in every domain dir."""
        for domain in ("aml", "mortgage"):
            f = PROJECT_ROOT / "domain-prompts" / domain / "document_structure_analysis.txt"
            assert f.exists(), f"Missing domain-specific prompt: {f}"
            assert f.stat().st_size > 100, f"Suspiciously small file: {f}"

    def test_all_domains_have_same_prompt_set(self):
        """aml/ and mortgage/ must have exactly the same set of .txt files."""
        aml_files = {p.name for p in (PROJECT_ROOT / "domain-prompts" / "aml").glob("*.txt")}
        mortgage_files = {p.name for p in (PROJECT_ROOT / "domain-prompts" / "mortgage").glob("*.txt")}
        assert aml_files == mortgage_files, (
            f"Domain dirs out of sync.\n  AML only: {aml_files - mortgage_files}\n"
            f"  Mortgage only: {mortgage_files - aml_files}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 12. AML prompts contain critical compliance thresholds
# ─────────────────────────────────────────────────────────────────────────────

class TestAmlPromptContent:
    """Critical AML thresholds must appear in the relevant prompt files."""

    def _read(self, name):
        return (PROJECT_ROOT / "domain-prompts" / "aml" / f"{name}.txt").read_text()

    def test_business_rules_ctr_threshold(self):
        content = self._read("business_rules_extraction")
        assert "10,000" in content or "10000" in content

    def test_business_rules_sar_threshold_known_suspect(self):
        content = self._read("business_rules_extraction")
        assert "5,000" in content or "5000" in content

    def test_business_rules_sar_threshold_unknown(self):
        content = self._read("business_rules_extraction")
        assert "25,000" in content or "25000" in content

    def test_business_rules_beneficial_ownership_threshold(self):
        content = self._read("business_rules_extraction")
        assert "25%" in content or "25 %" in content

    def test_entity_refinement_beneficial_ownership(self):
        content = self._read("entity_refinement")
        assert "25%" in content

    def test_rule_deduplication_warns_about_sar_threshold_variation(self):
        content = self._read("rule_deduplication")
        # Warns that $5K vs $25K SAR thresholds are NOT duplicates
        assert "5,000" in content or "$5" in content

    def test_document_structure_analysis_mentions_sar(self):
        content = self._read("document_structure_analysis")
        assert "SAR" in content

    def test_document_structure_analysis_mentions_ctr(self):
        content = self._read("document_structure_analysis")
        assert "CTR" in content

    def test_document_structure_analysis_mentions_fatf(self):
        content = self._read("document_structure_analysis")
        assert "FATF" in content

    def test_document_structure_analysis_mentions_beneficial_ownership(self):
        content = self._read("document_structure_analysis")
        assert "beneficial owner" in content.lower() or "beneficial_owner" in content.lower()

    def test_document_structure_analysis_contains_content_variable(self):
        content = self._read("document_structure_analysis")
        assert "{content}" in content, "Missing required {content} template variable"

    def test_document_structure_analysis_contains_json_format(self):
        content = self._read("document_structure_analysis")
        assert "document_type" in content and "sections" in content


class TestMortgageDocStructureAnalysisContent:
    """Mortgage document_structure_analysis.txt must contain expected mortgage terms."""

    def _read(self):
        return (PROJECT_ROOT / "domain-prompts" / "mortgage" / "document_structure_analysis.txt").read_text()

    def test_file_exists(self):
        f = PROJECT_ROOT / "domain-prompts" / "mortgage" / "document_structure_analysis.txt"
        assert f.exists()

    def test_contains_content_variable(self):
        assert "{content}" in self._read(), "Missing required {content} template variable"

    def test_mentions_ltv(self):
        assert "LTV" in self._read()

    def test_mentions_dti(self):
        assert "DTI" in self._read()

    def test_mentions_fannie_mae_or_freddie(self):
        content = self._read()
        assert "Fannie Mae" in content or "Freddie Mac" in content

    def test_mentions_fha(self):
        assert "FHA" in self._read()

    def test_mentions_credit_score(self):
        assert "credit score" in self._read().lower() or "FICO" in self._read()

    def test_contains_json_format_keys(self):
        content = self._read()
        assert "document_type" in content and "sections" in content


# ─────────────────────────────────────────────────────────────────────────────
# 13. Agent 6 — _get_rule_type_description()
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent6RuleTypeDescriptions:
    """_get_rule_type_description() should return domain-appropriate strings."""

    def _desc(self, rule_type, domain="mortgage"):
        with patch.dict(os.environ, {"KG_DOMAIN": domain}):
            from agents.agent_6_visualization_and_report import _get_rule_type_description
            # Reload so env var is picked up fresh each call
            import importlib
            import agents.agent_6_visualization_and_report as a6
            importlib.reload(a6)
            return a6._get_rule_type_description(rule_type)

    # Mortgage domain
    def test_mortgage_eligibility_description(self):
        d = self._desc("eligibility", "mortgage")
        assert isinstance(d, str) and len(d) > 10
        # Should reference loans/borrowers, not AML
        assert "loan" in d.lower() or "qualification" in d.lower() or "borrower" in d.lower()

    def test_mortgage_constraint_description(self):
        d = self._desc("constraint", "mortgage")
        assert "limit" in d.lower() or "threshold" in d.lower() or "restriction" in d.lower()

    def test_mortgage_unknown_type_returns_fallback(self):
        d = self._desc("totally_unknown_type", "mortgage")
        assert isinstance(d, str) and len(d) > 0

    # AML domain
    def test_aml_eligibility_description(self):
        d = self._desc("eligibility", "aml")
        assert "AML" in d or "aml" in d.lower() or "obligation" in d.lower() or "trigger" in d.lower()

    def test_aml_reporting_description(self):
        d = self._desc("reporting", "aml")
        # AML-only type — should mention SAR/CTR or filing
        assert any(t in d.upper() for t in ["SAR", "CTR", "FILING", "MANDATORY"])

    def test_aml_monitoring_description(self):
        d = self._desc("monitoring", "aml")
        assert "monitoring" in d.lower() or "transaction" in d.lower() or "alert" in d.lower()

    def test_aml_screening_description(self):
        d = self._desc("screening", "aml")
        assert any(t in d.upper() for t in ["OFAC", "PEP", "SCREENING", "SANCTION"])

    def test_aml_investigation_description(self):
        d = self._desc("investigation", "aml")
        assert "SAR" in d or "investigation" in d.lower() or "workflow" in d.lower()

    def test_aml_onboarding_description(self):
        d = self._desc("onboarding", "aml")
        assert "KYC" in d or "CDD" in d or "onboard" in d.lower()

    def test_aml_prohibition_description(self):
        d = self._desc("prohibition", "aml")
        assert "prohibit" in d.lower() or "sanction" in d.lower() or "forbidden" in d.lower()

    def test_aml_unknown_type_returns_fallback(self):
        d = self._desc("nonexistent_aml_type", "aml")
        assert isinstance(d, str) and len(d) > 0

    def test_mortgage_does_not_expose_aml_reporting_type(self):
        """Mortgage descriptions dict should not have 'reporting' as a key."""
        d = self._desc("reporting", "mortgage")
        # In mortgage domain, 'reporting' is not a known key — should fall back
        assert d == "Business rules in this category."

    def test_mortgage_all_core_types_have_descriptions(self):
        core_types = ["eligibility", "constraint", "compliance", "validation",
                      "documentation", "process", "calculation"]
        for rt in core_types:
            d = self._desc(rt, "mortgage")
            assert d != "Business rules in this category.", \
                f"mortgage '{rt}' returned fallback string — missing dedicated description"

    def test_aml_all_types_have_descriptions(self):
        aml_types = ["eligibility", "constraint", "compliance", "validation",
                     "documentation", "process", "calculation", "reporting",
                     "monitoring", "screening", "investigation", "onboarding",
                     "prohibition", "unknown"]
        for rt in aml_types:
            d = self._desc(rt, "aml")
            assert d != "Business rules in this category.", \
                f"aml '{rt}' returned fallback string — missing dedicated description"


# ─────────────────────────────────────────────────────────────────────────────
# 14. Agent 7 — LEGACY_TYPE_TO_BEHAVIOR AML entries
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent7LegacyTypeToBehavior:
    """LEGACY_TYPE_TO_BEHAVIOR must contain all original and AML-specific entries."""

    @pytest.fixture
    def mapping(self):
        from agents.agent_7_rule_type_clusterer import LEGACY_TYPE_TO_BEHAVIOR
        return LEGACY_TYPE_TO_BEHAVIOR

    # Original mortgage entries
    def test_eligibility_maps_to_threshold(self, mapping):
        assert mapping["eligibility"] == "threshold"

    def test_constraint_maps_to_threshold(self, mapping):
        assert mapping["constraint"] == "threshold"

    def test_compliance_maps_to_mandate(self, mapping):
        assert mapping["compliance"] == "mandate"

    def test_validation_maps_to_method(self, mapping):
        assert mapping["validation"] == "method"

    def test_documentation_maps_to_mandate(self, mapping):
        assert mapping["documentation"] == "mandate"

    def test_process_maps_to_sequence(self, mapping):
        assert mapping["process"] == "sequence"

    def test_calculation_maps_to_formula(self, mapping):
        assert mapping["calculation"] == "formula"

    # AML-specific entries
    def test_reporting_maps_to_mandate(self, mapping):
        assert "reporting" in mapping
        assert mapping["reporting"] == "mandate"

    def test_monitoring_maps_to_method(self, mapping):
        assert "monitoring" in mapping
        assert mapping["monitoring"] == "method"

    def test_screening_maps_to_method(self, mapping):
        assert "screening" in mapping
        assert mapping["screening"] == "method"

    def test_investigation_maps_to_sequence(self, mapping):
        assert "investigation" in mapping
        assert mapping["investigation"] == "sequence"

    def test_onboarding_maps_to_sequence(self, mapping):
        assert "onboarding" in mapping
        assert mapping["onboarding"] == "sequence"

    def test_prohibition_maps_to_prohibition(self, mapping):
        assert "prohibition" in mapping
        assert mapping["prohibition"] == "prohibition"

    def test_all_values_are_valid_rule_behaviors(self, mapping):
        """Every value must be one of the allowed rule_behavior strings."""
        from agents.agent_7_rule_type_clusterer import RULE_BEHAVIORS
        valid_behaviors = set(RULE_BEHAVIORS)
        for rule_type, behavior in mapping.items():
            assert behavior in valid_behaviors, \
                f"'{rule_type}' maps to invalid behavior '{behavior}'"

    def test_mapping_is_dict(self, mapping):
        assert isinstance(mapping, dict)

    def test_mapping_covers_at_least_13_types(self, mapping):
        """7 original + 6 AML = 13 minimum."""
        assert len(mapping) >= 13


# ─────────────────────────────────────────────────────────────────────────────
# 15. Agent 8 — _extract_thresholds() AML patterns
# ─────────────────────────────────────────────────────────────────────────────

class TestAgent8ExtractThresholds:
    """_extract_thresholds() should detect AML-specific values."""

    @pytest.fixture
    def matcher(self):
        """Return a SemanticRuleMatcher without triggering any LLM calls."""
        from agents.agent_8_semantic_rule_matcher import SemanticRuleMatcher
        with patch("agents.agent_8_semantic_rule_matcher.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            mock_cfg.return_value.get_model_provider.return_value = "openai"
            mock_cfg.return_value.get.return_value = 8
            instance = SemanticRuleMatcher.__new__(SemanticRuleMatcher)
            instance.prompt_manager = MagicMock()
            return instance

    def _rule(self, description="", conditions=""):
        """Helper: build the dict shape _extract_thresholds expects."""
        return {"description": description, "conditions": conditions}

    def test_dollar_amounts_detected(self, matcher):
        thresholds = matcher._extract_thresholds(self._rule("Transactions over $500 require review."))
        assert "$500" in thresholds

    def test_ctr_amount_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("CTR reporting threshold $10,000 for cash transactions.")
        )
        hits = [t for t in thresholds if "ctr_sar" in t]
        assert len(hits) > 0

    def test_sar_amount_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("SAR filing required for suspicious activity above $5,000.")
        )
        hits = [t for t in thresholds if "ctr_sar" in t]
        assert len(hits) > 0

    def test_currency_transaction_phrase_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Currency transaction reporting for amounts exceeding 10000.")
        )
        hits = [t for t in thresholds if "ctr_sar" in t]
        assert len(hits) > 0

    def test_suspicious_activity_phrase_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Suspicious activity filing threshold 25000.")
        )
        hits = [t for t in thresholds if "ctr_sar" in t]
        assert len(hits) > 0

    def test_beneficial_ownership_25_percent(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Beneficial ownership threshold is 25% for legal entities.")
        )
        hits = [t for t in thresholds if "bo_pct" in t]
        assert len(hits) > 0
        assert "25%" in hits[0]

    def test_beneficial_ownership_10_percent(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Beneficial owner percentage at 10% for enhanced due diligence.")
        )
        hits = [t for t in thresholds if "bo_pct" in t]
        assert len(hits) > 0
        assert "10%" in hits[0]

    def test_fatf_reference_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Countries on the FATF grey list require enhanced due diligence.")
        )
        assert "fatf_ref" in thresholds

    def test_grey_list_reference_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Jurisdictions on the greylist face additional scrutiny.")
        )
        assert "fatf_ref" in thresholds

    def test_high_risk_jurisdiction_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("High-risk jurisdictions require EDD procedures.")
        )
        assert "fatf_ref" in thresholds

    def test_ofac_reference_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Screen against OFAC SDN list before account opening.")
        )
        assert "sanctions_ref" in thresholds

    def test_sdn_list_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Check the SDN list for all wire transfers.")
        )
        assert "sanctions_ref" in thresholds

    def test_sanctions_list_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Verify against the sanctions list before processing.")
        )
        assert "sanctions_ref" in thresholds

    def test_specially_designated_detected(self, matcher):
        thresholds = matcher._extract_thresholds(
            self._rule("Specially designated nationals must be blocked.")
        )
        assert "sanctions_ref" in thresholds

    def test_multiple_aml_signals_in_one_text(self, matcher):
        description = (
            "CTR threshold $10,000. SAR filing for $5,000 known suspects. "
            "Beneficial ownership 25%. OFAC SDN screening required. "
            "FATF high-risk jurisdiction EDD."
        )
        thresholds = matcher._extract_thresholds(self._rule(description))
        has_ctr_sar = any("ctr_sar" in t for t in thresholds)
        has_bo = any("bo_pct" in t for t in thresholds)
        has_fatf = "fatf_ref" in thresholds
        has_sanctions = "sanctions_ref" in thresholds
        assert has_ctr_sar, "CTR/SAR amount not detected"
        assert has_bo, "Beneficial ownership % not detected"
        assert has_fatf, "FATF reference not detected"
        assert has_sanctions, "Sanctions reference not detected"

    def test_empty_text_returns_list(self, matcher):
        result = matcher._extract_thresholds(self._rule())
        assert isinstance(result, list)

    def test_no_aml_signals_returns_no_aml_markers(self, matcher):
        result = matcher._extract_thresholds(
            self._rule("The minimum credit score is 620 and LTV must not exceed 80%.")
        )
        assert "fatf_ref" not in result
        assert "sanctions_ref" not in result
        assert not any("bo_pct" in t for t in result)
        assert not any("ctr_sar" in t for t in result)

    def test_returns_list(self, matcher):
        result = matcher._extract_thresholds(self._rule("some text $100"))
        assert isinstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# 16. knowledge_graph_generation — --domain CLI arg parsing
# ─────────────────────────────────────────────────────────────────────────────

def _build_kg_parser():
    """Build the argparse parser matching the one in main()."""
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
    parser.add_argument("--domain", type=str, default=None,
                        help="Compliance domain (e.g., 'mortgage', 'aml')")
    return parser


class TestDomainCLIArgParsing:
    """--domain argument is parsed correctly."""

    def test_domain_default_is_none(self):
        parser = _build_kg_parser()
        args = parser.parse_args([])
        assert args.domain is None

    def test_domain_aml_parsed(self):
        parser = _build_kg_parser()
        args = parser.parse_args(["--domain", "aml"])
        assert args.domain == "aml"

    def test_domain_mortgage_parsed(self):
        parser = _build_kg_parser()
        args = parser.parse_args(["--domain", "mortgage"])
        assert args.domain == "mortgage"

    def test_domain_combined_with_provider(self):
        parser = _build_kg_parser()
        args = parser.parse_args(["--provider", "openai", "--domain", "aml"])
        assert args.domain == "aml"
        assert args.provider == "openai"

    def test_domain_combined_with_workers(self):
        parser = _build_kg_parser()
        args = parser.parse_args(["--workers", "10", "--domain", "aml"])
        assert args.domain == "aml"
        assert args.workers == 10

    def test_domain_registered_in_real_parser(self):
        """The knowledge_graph_generation module's actual parser must register --domain."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "knowledge_graph_generation.py"), "--help"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT)
        )
        assert "--domain" in result.stdout, \
            "--domain not found in knowledge_graph_generation.py --help output"


# ─────────────────────────────────────────────────────────────────────────────
# 17. KG_DOMAIN propagated to subprocess env via _run_agent
# ─────────────────────────────────────────────────────────────────────────────

class TestKGDomainEnvPropagation:
    """KG_DOMAIN must be present in the env dict passed to subprocess calls."""

    @pytest.fixture
    def mock_config_obj(self):
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
        config.get_domain.return_value = "aml"
        return config

    @patch("knowledge_graph_generation.get_config")
    def test_run_agent_propagates_kg_domain(self, mock_get_config, mock_config_obj):
        mock_get_config.return_value = mock_config_obj
        from knowledge_graph_generation import KnowledgeExtractionPipeline
        pipeline = KnowledgeExtractionPipeline(provider="openai", domain="aml")

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
                step_number="1",
            )

        assert "KG_DOMAIN" in captured_env
        assert captured_env["KG_DOMAIN"] == "aml"

    @patch("knowledge_graph_generation.get_config")
    def test_run_agent_kg_domain_is_string(self, mock_get_config, mock_config_obj):
        mock_get_config.return_value = mock_config_obj
        from knowledge_graph_generation import KnowledgeExtractionPipeline
        pipeline = KnowledgeExtractionPipeline(provider="openai", domain="aml")

        captured_env = {}

        def fake_popen(command, stdout, stderr, env, universal_newlines, bufsize):
            captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            pipeline._run_agent(
                agent_name="Agent",
                command=[sys.executable, "-c", "pass"],
                description="Test",
                step_number="1",
            )

        assert isinstance(captured_env["KG_DOMAIN"], str)

    @patch("knowledge_graph_generation.get_config")
    def test_pipeline_stores_domain(self, mock_get_config, mock_config_obj):
        mock_get_config.return_value = mock_config_obj
        from knowledge_graph_generation import KnowledgeExtractionPipeline
        pipeline = KnowledgeExtractionPipeline(provider="openai", domain="aml")
        assert pipeline.domain == "aml"

    @patch("knowledge_graph_generation.get_config")
    def test_pipeline_domain_none_when_not_provided(self, mock_get_config, mock_config_obj):
        mock_get_config.return_value = mock_config_obj
        from knowledge_graph_generation import KnowledgeExtractionPipeline
        pipeline = KnowledgeExtractionPipeline(provider="openai")
        assert pipeline.domain is None
