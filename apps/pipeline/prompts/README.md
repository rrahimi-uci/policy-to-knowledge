# Prompt Templates

Base prompt templates for the 10-agent extraction pipeline. These are the **domain-agnostic baseline** prompts; each compliance domain ships its own overrides under `domain-prompts/<domain>/`, and the `PromptManager` resolves the domain version first, falling back to the templates here.

All prompts target the OpenAI models configured in `config.json` (reasoning `gpt-5.2`, optimizer `gpt-5.2`).

## Templates

| Template | Consumed by | Purpose |
|----------|-------------|---------|
| `document_structure_analysis.txt` | Agent 1 — Document Organizer | Segment a document into logical sections when no usable table of contents is present. |
| `entity_extraction_compact.txt` | **Agent 2 — Entity Extractor (the template actually loaded)** | Compact entity/relationship extraction. Agent 2 requests this name, not `entity_extraction`. |
| `business_rules_extraction_compact.txt` | **Agent 3 — Rules Extractor (the template actually loaded)** | Compact rule extraction. Agent 3 requests this name, not `business_rules_extraction`. |
| `entity_extraction.txt` | Agent 2 (unused by the current code path) | Full-length entity extraction, retained for the data-contract tests. |
| `entity_refinement.txt` | Agent 2 — Entity Extractor (refinement loop) | Score and iteratively improve entity/relationship extractions across passes. |
| `entity_resolution.txt` | Multi-document merge (Agent 2 path) | Merge and reconcile duplicate or overlapping entities across documents into a canonical set. |
| `business_rules_extraction.txt` | Agent 3 (unused by the current code path) | Full-length rule extraction, retained for the data-contract tests. |
| `rule_contract_v2.txt` | Agent 3 — Rules Extractor | Shared non-overridable v2 rule shape appended after every domain rule-extraction prompt. |
| `validation_report.txt` | Agent 3.5 — Rule Validator | Produce a quality-assessment report over the extracted rules with actionable recommendations. |
| `rule_resolution.txt` | Multi-document merge (Agent 3 path) | Reconcile conflicting or overlapping rules when merging multiple documents. |
| `rule_deduplication.txt` | Agent 5 — Knowledge Graph Optimizer | Identify and merge duplicate rules while preserving meaningful variations. |
| `dependency_analysis.txt` | Agent 5 — Knowledge Graph Optimizer | Map dependencies and relationships between business rules. |
| `rule_matcher.txt` | Agent 8 — Semantic Rule Matcher | Compare rules across two knowledge graphs for semantic equivalence (used by `cli/compare.py`). |
| `rule_matcher_batch.txt` | Agent 8 — Semantic Rule Matcher | Batched variant of the matcher for higher-throughput cross-graph comparison. |

The same 11 domain-specialized template names exist in every domain directory.
`rule_contract_v2.txt` is shared only and intentionally has no domain override.

**Which templates actually run.** Only eight prompt names are requested at
runtime. Four of them resolve per domain — `document_structure_analysis`,
`rule_deduplication`, `dependency_analysis`, `rule_matcher_batch` — and two more
would, but no `mortgage`/`aml`/`healthcare`/`commercial_lending` pack overrides
them: `entity_extraction_compact` (Agent 2) and
`business_rules_extraction_compact` (Agent 3). Those two decide what entities and
rules get extracted at all, and the shared copies are worded for mortgage
("prefer concrete mortgage concepts"), so a domain pack without them does not
influence extraction. The four benchmark domains below ship both. The remaining
two runtime names, `executable_readiness_completion` and
`entity_conflict_analysis` (Agent 5.5), are shared-only by design.

## Domains

Domain overrides live in `domain-prompts/<domain>/`. Each directory contains at least the 11 templates above, specialized with domain terminology, entity vocabularies, rule taxonomies, and worked examples.

| Directory | Domain | Focus |
|-----------|--------|-------|
| `prompts/` | Shared baseline | Domain-agnostic fallback templates. |
| `domain-prompts/mortgage/` | Mortgage lending | Agency/investor guidelines and lender overlays. |
| `domain-prompts/aml/` | Anti-money laundering | BSA/AML compliance — SAR, CTR, CDD, KYC. |
| `domain-prompts/commercial_lending/` | Commercial lending | Loan origination — collateral, covenants. |
| `domain-prompts/healthcare/` | Healthcare | HIPAA, patient and provider entities. |
| `domain-prompts/commercial_contracts/` | Commercial contracts | Clause review — obligations, restrictions, licence grants, liability caps. Benchmarked on CUAD v1. |
| `domain-prompts/nda_confidentiality/` | NDA and confidentiality | Confidentiality scope, permitted use and disclosure, return/destroy, survival. Benchmarked on ContractNLI. |
| `domain-prompts/privacy_policy/` | Website privacy policy | First/third-party collection, user choice, retention, security. Benchmarked on OPP-115. |
| `domain-prompts/mobile_app_privacy/` | Mobile app privacy (GDPR) | Processing purposes with an explicit Article 6 legal basis; bilingual EN/DE. Benchmarked on the MAPP Corpus. |

The four benchmark domains ship **13** templates each — the 11 above plus
`entity_extraction_compact.txt` and `business_rules_extraction_compact.txt` — and
are generated by `scripts/generate_benchmark_domain_prompts.py`, which is the
source of truth for them. Edit the generator and re-run it rather than editing
those `.txt` files; `tests/test_benchmark_domains.py` fails if they drift apart.

The active domain is read from `config.json` (`domain.active`) and is configurable in the Settings UI.

## Resolution order

Prompts are loaded through `utils/prompt_manager.py`. For each requested template name, the resolver checks:

```text
1. domain-prompts/<active_domain>/<name>.txt   (domain-specific)
2. prompts/<name>.txt                          (shared fallback)
```

`rule_contract_v2.txt` is the exception: Agent 3 always loads it from the
shared `prompts/` directory after resolving the domain prompt. Domain packs may
specialize vocabulary and examples, but cannot redefine the v2 rule fields.

```python
from utils.prompt_manager import get_prompt_manager

# Singleton; resolves the active domain from Config automatically and
# rebuilds itself if the domain changes.
pm = get_prompt_manager()

# Load the raw template (domain version first, baseline fallback).
template = pm.load_prompt("business_rules_extraction")

# Or load and substitute parameters in one call.
prompt = pm.format_prompt(
    "business_rules_extraction",
    entity_context=entity_definitions,
    rules_per_batch=10,
    batch_num=1,
    sample_content=document_chunks,
)
```

Parameters are substituted with Python `str.format`, so template placeholders use `{name}` syntax.

## Adding a domain

1. Register the domain in `config.json` under `domain.available` and set `domain.active`.
2. Create the directory and copy the baseline templates:

   ```bash
   mkdir -p domain-prompts/insurance
   cp prompts/*.txt domain-prompts/insurance/
   ```

   Include `entity_extraction_compact.txt` and
   `business_rules_extraction_compact.txt` in the copy and edit them. They are
   what Agents 2 and 3 load; a pack without them leaves entity and rule
   extraction running on the mortgage-worded shared copies.

   Then register a rule-type palette and three quick-filter types for the domain
   in `utils/config.py` (`_RULE_TYPE_COLORS_BY_DOMAIN`,
   `_DOMAIN_PRIORITY_FILTER_TYPES`), or Agent 6 colours every rule grey; add
   keywords to `_DOMAIN_KEYWORDS` in
   `ui/backend/services/graph_service.py` so graphs categorise correctly; and add
   the domain to `DOMAINS` in `tests/test_data_contracts.py` so its prompts are
   held to the same field contracts.

3. Edit each template to use domain-specific terminology, entity types, and examples.
4. Run the pipeline against the new domain:

   ```bash
   python3 cli/extract.py
   ```

   `PromptManager` loads the new domain's templates automatically.

## Authoring guidelines

- **Structured output.** Prompts requesting structured data specify an exact JSON schema and instruct the model to return JSON only (no Markdown fences).
- **Traceability.** Extraction prompts require source references (document section, page, clause) on every item.
- **Quality over quantity.** Prefer fewer complete items with all required fields over many partial ones; no placeholder or `TBD` values.
- **Consistent placeholders.** Keep `{parameter}` names aligned with the keyword arguments passed by the corresponding agent.

## Related

- [Agents README](../agents/README.md) — how each agent uses these prompts
- [Utils README](../utils/README.md) — `prompt_manager` and configuration
- [Main README](../README.md) — project overview
